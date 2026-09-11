import hashlib
import json
import os
import re
import time
from pathlib import Path

import pandas as pd
import sqlglot
import streamlit as st
from sqlglot import exp
from streamlit_mermaid import st_mermaid

import contract
import diagrams
import mermaid_render
from exporter import generate_docx_report, generate_pdf_report
from model_chain import CatenaModelli, NessunModello

# =============================================================================
# 1. PAGE CONFIGURATION
# =============================================================================
st.set_page_config(
    page_title="Legacy Application Knowledge Extractor",
    page_icon="🧭",
    layout="wide"
)

# =============================================================================
# 2. CONSTANTS
# =============================================================================
SUPPORTED_EXTENSIONS = [
    "sql", "pks", "pkb", "pls", "plsql", "java", "py", "js", "ts",
    "cs", "c", "cpp", "h", "hpp", "cbl", "cob", "rpg", "rpgle",
    "cl", "xml", "json", "yaml", "yml", "txt"
]

MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_SOURCE_CHARS = 1_500_000      # con l'analisi a lotti il tetto di una
                                        # singola chiamata non è più il tetto
                                        # dell'applicazione
CHARS_PER_LOTTO = 120_000               # quanto sorgente sta in una chiamata
MAX_LOTTI = 12                          # oltre, si chiede all'utente di ridurre

# Massimo di righe che l'analisi statica può produrre per file su un singolo
# tipo di ritrovamento. Senza tetto, il pattern «qualsiasi_nome(» su un file
# Java da 5.000 righe produce migliaia di PROBABLE_CALL che affogano le poche
# dipendenze vere e gonfiano il prompt fino a farlo costare il doppio.
MAX_RIGHE_PER_TIPO = 300

RISK_LEVELS = contract.SEVERITA

# =============================================================================
# 3. GENERIC UTILITY FUNCTIONS
# =============================================================================
def unique_strings(values):
    cleaned_values = {
        str(value).strip() for value in values
        if value is not None and str(value).strip()
    }
    return sorted(cleaned_values)

def unique_dicts(values, keys):
    output = []
    seen = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        composite_key = tuple(str(value.get(key, "")).strip().lower() for key in keys)
        if composite_key not in seen:
            seen.add(composite_key)
            output.append(value)
    return output

def safe_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)

def normalize_identifier(value):
    if not value:
        return ""
    value = str(value).strip()
    value = value.strip('"').strip("'").strip("`")
    value = value.rstrip(";,)")
    value = value.lstrip("(")
    return value

def detect_language_from_filename(filename):
    extension = Path(filename).suffix.lower()
    language_map = {
        ".sql": "SQL", ".pks": "Oracle PL/SQL Package Specification",
        ".pkb": "Oracle PL/SQL Package Body", ".pls": "Oracle PL/SQL",
        ".plsql": "Oracle PL/SQL", ".java": "Java", ".py": "Python",
        ".js": "JavaScript", ".ts": "TypeScript", ".cs": "C#",
        ".c": "C", ".cpp": "C++", ".h": "C/C++ Header", ".hpp": "C++ Header",
        ".cbl": "COBOL", ".cob": "COBOL", ".rpg": "RPG", ".rpgle": "RPGLE",
        ".cl": "IBM i Control Language", ".xml": "XML", ".json": "JSON",
        ".yaml": "YAML", ".yml": "YAML", ".txt": "Text or Unknown"
    }
    return language_map.get(extension, "Unknown")

def source_hash(filename, content):
    payload = f"{filename}\n{content}".encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()[:16]

# =============================================================================
# 4. FILE INPUT FUNCTIONS
# =============================================================================
def decode_uploaded_file(uploaded_file):
    raw_content = uploaded_file.getvalue()
    if len(raw_content) > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"{uploaded_file.name} exceeds the allowed size.")

    encodings = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]
    for encoding in encodings:
        try:
            return raw_content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_content.decode("utf-8", errors="replace")

def build_source_collection(uploaded_files, pasted_code, pasted_filename):
    sources = []
    for uploaded_file in uploaded_files or []:
        content = decode_uploaded_file(uploaded_file)
        sources.append({
            "filename": uploaded_file.name,
            "language": detect_language_from_filename(uploaded_file.name),
            "content": content,
            "hash": source_hash(uploaded_file.name, content)
        })

    if pasted_code.strip():
        filename = pasted_filename.strip() or "pasted_source.txt"
        sources.append({
            "filename": filename,
            "language": detect_language_from_filename(filename),
            "content": pasted_code,
            "hash": source_hash(filename, pasted_code)
        })

    total_characters = sum(len(s["content"]) for s in sources)
    if total_characters > MAX_TOTAL_SOURCE_CHARS:
        raise ValueError(
            f"The total submitted source code ({total_characters:,} chars) exceeds the "
            f"{MAX_TOTAL_SOURCE_CHARS:,} limit. Split the codebase and analyse it in runs."
        )

    return sources

def split_into_batches(sources, chars_per_batch=CHARS_PER_LOTTO):
    """L'analisi a lotti.

    Prima l'app mandava tutto in una chiamata sola: oltre una certa dimensione
    il modello troncava la risposta a metà e l'analisi andava persa senza che
    nessuno lo dicesse. Ora il sorgente si divide in lotti che stanno in una
    chiamata, ogni lotto è un'analisi completa, e i risultati si uniscono sulle
    stesse chiavi con cui si tolgono i doppioni.
    I file NON si spezzano mai a metà: un file tagliato dà regole di business
    monche, che è peggio di un file in meno.
    """
    batches, corrente, quanti = [], [], 0
    for s in sorted(sources, key=lambda x: -len(x["content"])):
        peso = len(s["content"])
        if corrente and quanti + peso > chars_per_batch:
            batches.append(corrente)
            corrente, quanti = [], 0
        corrente.append(s)
        quanti += peso
    if corrente:
        batches.append(corrente)
    return batches

# =============================================================================
# 5. SQL PARSING
# =============================================================================
def parse_sql_expressions(sql_text):
    candidate_dialects = [None, "oracle", "mysql", "postgres", "tsql"]
    for dialect in candidate_dialects:
        try:
            expressions = (sqlglot.parse(sql_text, read=dialect, error_level="ignore")
                           if dialect else sqlglot.parse(sql_text, error_level="ignore"))
            # NOTA: la variabile si chiama `parsed`, non `exp`. Prima era `exp` e
            # copriva il modulo `sqlglot.exp` importato in testa al file: dentro
            # questa funzione `exp.Table` avrebbe smesso di esistere. Non è mai
            # esploso solo perché qui non serviva — un errore in attesa.
            valid_expressions = [parsed for parsed in expressions if parsed is not None]
            if valid_expressions:
                return valid_expressions
        except Exception:
            continue
    return []

def extract_sql_metadata(code, filename):
    expressions = parse_sql_expressions(code)
    tables, columns, operations, relationships = [], [], [], []

    for expression in expressions:
        expression_tables = unique_strings([normalize_identifier(t.sql()) for t in expression.find_all(exp.Table)])
        expression_columns = unique_strings([normalize_identifier(c.sql()) for c in expression.find_all(exp.Column)])
        tables.extend(expression_tables)
        columns.extend(expression_columns)

        operation = expression.key.upper()
        if operation in {"SELECT", "INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "DROP", "ALTER"}:
            operations.append({
                "source_file": filename,
                "operation": operation,
                "objects": expression_tables
            })

        for join in expression.find_all(exp.Join):
            if join.this is not None:
                relationships.append({
                    "source_file": filename,
                    "relationship_type": "JOIN",
                    "target": normalize_identifier(join.this.sql()),
                    "condition": safe_text(join.args.get("on"))
                })

    return {
        "tables": unique_strings(tables),
        "columns": unique_strings(columns),
        "operations": operations[:MAX_RIGHE_PER_TIPO],
        "relationships": relationships[:MAX_RIGHE_PER_TIPO]
    }

# =============================================================================
# 6. STATIC SOURCE ANALYSIS
# =============================================================================
def extract_functions_and_procedures(code, filename):
    patterns = [
        ("PROCEDURE", r"\bPROCEDURE\s+([A-Z_][A-Z0-9_$#.]*)"),
        ("FUNCTION", r"\bFUNCTION\s+([A-Z_][A-Z0-9_$#.]*)"),
        ("PACKAGE", r"\bPACKAGE(?:\s+BODY)?\s+([A-Z_][A-Z0-9_$#.]*)"),
        # Il pattern originale aveva `\s` fra le alternative dei modificatori:
        # bastava uno spazio per farlo scattare, quindi in un PL/SQL o in un
        # COBOL «BEGIN CALC_SCONTO(x)» registrava CALC_SCONTO come metodo Java.
        # Componenti fantasma nelle tabelle, e — peggio — nell'indice usato per
        # risolvere le chiamate, dove facevano sparire le dipendenze vere.
        ("JAVA_METHOD", r"\b(?:public|private|protected)\s+(?:(?:static|final|synchronized|abstract|native)\s+)*[\w<>\[\],?]+(?:\s*\[\s*\])?\s+([A-Za-z_]\w*)\s*\("),
        ("PYTHON_FUNCTION", r"(?m)^\s*def\s+([A-Za-z_]\w*)\s*\("),
        ("JAVASCRIPT_FUNCTION", r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\("),
        ("COBOL_PARAGRAPH", r"(?m)^\s*([A-Z0-9][A-Z0-9-]+)\.\s*$")
    ]
    components = []
    for component_type, pattern in patterns:
        for match in re.findall(pattern, code, flags=re.IGNORECASE)[:MAX_RIGHE_PER_TIPO]:
            components.append({
                "component_name": normalize_identifier(match),
                "component_type": component_type,
                "source_file": filename,
                "source": "STATIC_ANALYSIS",
                "confidence": "HIGH",
                "evidence": "Static source pattern"
            })
    return unique_dicts(components, ["component_name", "component_type", "source_file"])

def extract_imports_and_includes(code, filename):
    patterns = [
        ("PYTHON_IMPORT", r"(?m)^\s*import\s+([A-Za-z0-9_., ]+)"),
        ("PYTHON_FROM_IMPORT", r"(?m)^\s*from\s+([A-Za-z0-9_.]+)\s+import"),
        ("JAVA_IMPORT", r"(?m)^\s*import\s+([A-Za-z0-9_.]+)\s*;"),
        ("JAVASCRIPT_IMPORT", r"""from\s+["']([^"']+)["']"""),
        ("REQUIRE", r"""require\s*\(\s*["']([^"']+)["']\s*\)"""),
        ("C_INCLUDE", r"""#include\s*[<"]([^>"]+)[>"]"""),
        ("COBOL_COPY", r"\bCOPY\s+([A-Z0-9_-]+)"),
        ("RPG_COPY", r"/COPY\s+([A-Z0-9_./-]+)")
    ]
    dependencies = []
    for dep_type, pattern in patterns:
        for match in re.findall(pattern, code, flags=re.IGNORECASE)[:MAX_RIGHE_PER_TIPO]:
            dependencies.append({
                "source": filename, "target": normalize_identifier(match),
                "dependency_type": dep_type, "evidence": "Static source pattern", "confidence": "HIGH"
            })
    return unique_dicts(dependencies, ["source", "target", "dependency_type"])

def extract_probable_calls(code, filename, components):
    declarations = {comp.get("component_name", "").lower() for comp in components}
    # La lista di esclusione prima teneva fuori una ventina di parole. Il quarto
    # pattern («qualsiasi identificatore seguito da parentesi») cattura ogni
    # chiamata di funzione del linguaggio, quindi senza una lista seria produce
    # più rumore che segnale: qui ci sono le parole chiave e le funzioni di
    # libreria più comuni dei linguaggi che l'app dichiara di supportare.
    excluded = {
        "if", "for", "while", "switch", "return", "print", "printf", "sprintf", "len", "str",
        "int", "float", "list", "dict", "set", "tuple", "range", "open", "type", "super",
        "select", "insert", "update", "delete", "merge", "values", "count", "sum", "min",
        "max", "avg", "coalesce", "nvl", "nvl2", "decode", "trim", "substr", "instr",
        "to_char", "to_date", "to_number", "sysdate", "nullif", "cast", "convert", "round",
        "trunc", "case", "when", "then", "else", "end", "and", "or", "not", "in", "exists",
        "new", "catch", "try", "throw", "synchronized", "public", "private", "protected",
        "static", "void", "get", "post", "put", "console", "log", "require", "function",
        "define", "include", "printline", "display", "move", "compute", "evaluate"
    }
    patterns = [
        (r"\bCALL\s+([A-Z_][A-Z0-9_$#.]*)", "HIGH"),
        (r"\bEXEC(?:UTE)?\s+([A-Z_][A-Z0-9_$#.]*)", "HIGH"),
        (r"\bPERFORM\s+([A-Z0-9-]+)", "HIGH"),
        (r"\b([A-Za-z_][A-Za-z0-9_$.]*)\s*\(", "MEDIUM")
    ]
    dependencies = []
    for pattern, confidence in patterns:
        trovati = 0
        for riscontro in re.finditer(pattern, code, flags=re.IGNORECASE):
            match = riscontro.group(1)
            # `new Cliente(...)` non è una chiamata a una procedura: è la
            # costruzione di un oggetto. Il pattern generico non lo distingue,
            # ma i quattro caratteri prima sì.
            prima = code[max(0, riscontro.start() - 5):riscontro.start()]
            if re.search(r"\bnew\s*$", prima, flags=re.IGNORECASE):
                continue
            norm_match = normalize_identifier(match)
            basso = norm_match.lower()
            if (not basso or basso in excluded or basso in declarations
                    or basso in LIBRERIE_NOTE or len(basso) < 3):
                continue
            dependencies.append({
                "source": filename, "target": norm_match, "dependency_type": "PROBABLE_CALL",
                "evidence": "Static call-pattern detection", "confidence": confidence
            })
            trovati += 1
            if trovati >= MAX_RIGHE_PER_TIPO:
                break
    return unique_dicts(dependencies, ["source", "target", "dependency_type"])

def extract_interfaces(code, filename):
    interfaces = []
    for url in re.findall(r"""https?://[^\s"'<>]+""", code, flags=re.IGNORECASE)[:MAX_RIGHE_PER_TIPO]:
        interfaces.append({
            "name": url, "interface_type": "HTTP_ENDPOINT", "direction": "UNKNOWN",
            "technology": "HTTP/HTTPS", "source_file": filename, "evidence": url, "confidence": "HIGH"
        })
    # Prima era `[^"']+\.(csv|txt|…)["']`: `[^"']+` è ingordo e con una riga
    # lunga senza virgolette si mangiava centinaia di caratteri, che finivano
    # nel PDF come nome di interfaccia. Ora il nome file è un nome file.
    for file_ref in re.findall(r"""["']([\w./\\ -]{1,120}\.(?:csv|txt|xml|json|dat|xlsx|xls|pdf))["']""",
                               code, flags=re.IGNORECASE)[:MAX_RIGHE_PER_TIPO]:
        interfaces.append({
            "name": file_ref, "interface_type": "FILE_INTERFACE", "direction": "UNKNOWN",
            "technology": Path(file_ref).suffix.upper().lstrip("."),
            "source_file": filename, "evidence": file_ref, "confidence": "MEDIUM"
        })
    patterns = [
        ("REST_API", r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+[/][A-Za-z0-9_./{}-]+"),
        ("SOAP_SERVICE", r"\b(?:SOAP|WSDL|SOAPAction)\b"),
        ("MESSAGE_QUEUE", r"\b(?:KAFKA|RABBITMQ|JMS|MQSERIES|IBM\s+MQ|QUEUE_NAME)\b"),
        ("EMAIL_INTERFACE", r"\b(?:SMTP|SEND_MAIL|SEND_EMAIL|UTL_MAIL|UTL_SMTP)\b"),
        ("FTP_INTERFACE", r"\b(?:FTP|SFTP|FTPS)\b"),
        ("WEBHOOK", r"\bWEBHOOK\b")
    ]
    for i_type, pattern in patterns:
        for match in re.findall(pattern, code, flags=re.IGNORECASE)[:MAX_RIGHE_PER_TIPO]:
            interfaces.append({
                "name": safe_text(match), "interface_type": i_type, "direction": "UNKNOWN",
                "technology": i_type, "source_file": filename, "evidence": safe_text(match), "confidence": "MEDIUM"
            })
    return unique_dicts(interfaces, ["name", "interface_type", "source_file"])

def extract_local_risks(code, filename):
    risks = []
    patterns = [
        {"type": "HARDCODED_CREDENTIAL", "pattern": r"(?i)\b(?:password|passwd|pwd|secret|api_key|apikey)\s*[:=]\s*[\"'][^\"']+[\"']", "sev": "CRITICAL", "desc": "Possible hard-coded credential."},
        {"type": "DYNAMIC_SQL", "pattern": r"\bEXECUTE\s+IMMEDIATE\b|\bsp_executesql\b|\bPREPARE\s+STATEMENT\b", "sev": "HIGH", "desc": "Dynamic SQL detected."},
        {"type": "GENERIC_EXCEPTION_HANDLER", "pattern": r"\bWHEN\s+OTHERS\b|\bcatch\s*\(\s*Exception\b|\bexcept\s+Exception\b", "sev": "MEDIUM", "desc": "Generic exception handling."},
        {"type": "EMPTY_EXCEPTION_HANDLER", "pattern": r"\bWHEN\s+OTHERS\s+THEN\s+NULL\b|\bexcept\s*:\s*pass\b", "sev": "HIGH", "desc": "Exception is potentially suppressed."},
        {"type": "DIRECT_COMMIT", "pattern": r"\bCOMMIT\s*;", "sev": "MEDIUM", "desc": "Explicit transaction commit."},
        {"type": "SELECT_ALL", "pattern": r"\bSELECT\s+\*\s+FROM\b", "sev": "LOW", "desc": "SELECT * creates unnecessary coupling."}
    ]
    for risk_def in patterns:
        trovati = 0
        for match in re.finditer(risk_def["pattern"], code, flags=re.IGNORECASE | re.MULTILINE):
            line_num = code[:match.start()].count("\n") + 1
            risks.append({
                "risk_id": "", "risk_type": risk_def["type"], "severity": risk_def["sev"],
                "description": risk_def["desc"], "affected_component": filename,
                "evidence": match.group(0)[:200], "line_number": str(line_num),
                "impact": "", "recommendation": "", "confidence": "HIGH", "source": "STATIC_ANALYSIS"
            })
            trovati += 1
            if trovati >= MAX_RIGHE_PER_TIPO:
                break
    return risks

def extract_data_operations_with_regex(code, filename):
    patterns = {
        "READ": [r"\bFROM\s+([A-Z0-9_$#.]+)", r"\bJOIN\s+([A-Z0-9_$#.]+)"],
        "CREATE": [r"\bINSERT\s+INTO\s+([A-Z0-9_$#.]+)"],
        "UPDATE": [r"\bUPDATE\s+([A-Z0-9_$#.]+)"],
        "DELETE": [r"\bDELETE\s+FROM\s+([A-Z0-9_$#.]+)"],
        "MERGE": [r"\bMERGE\s+INTO\s+([A-Z0-9_$#.]+)"],
        "DDL_CREATE": [r"\bCREATE\s+(?:TABLE|VIEW)\s+([A-Z0-9_$#.]+)"]
    }
    data_objects = []
    for operation, ops in patterns.items():
        for pattern in ops:
            for match in re.findall(pattern, code, flags=re.IGNORECASE)[:MAX_RIGHE_PER_TIPO]:
                data_objects.append({
                    "object_name": normalize_identifier(match), "object_type": "DATABASE_OBJECT",
                    "operation": operation, "source_file": filename, "purpose": "",
                    "evidence": safe_text(match), "confidence": "HIGH"
                })
    return unique_dicts(data_objects, ["object_name", "operation", "source_file"])

# Nomi che compaiono ovunque e non sono componenti dell'applicazione: sono
# libreria, framework o parole del linguaggio. Tenerli produce righe di
# dipendenza verso «string», «logger» e «append», che non dicono nulla e
# affogano le dipendenze vere. NON contiene i package Oracle come UTL_FILE o
# DBMS_SQL: quelli sono dipendenze reali e vanno documentate.
LIBRERIE_NOTE = {
    # Java / C#
    "system", "string", "stringbuilder", "integer", "long", "double", "boolean",
    "arraylist", "hashmap", "hashset", "linkedlist", "optional", "stream", "collectors",
    "objects", "arrays", "collections", "files", "paths", "localdate", "localdatetime",
    "bigdecimal", "biginteger", "exception", "runtimeexception", "logger", "logfactory",
    "assert", "equals", "hashcode", "tostring", "valueof", "parseint", "parselong",
    "getinstance", "getclass", "getname", "getvalue", "setvalue", "builder", "of",
    # Python
    "append", "extend", "items", "keys", "values", "join", "format", "split", "strip",
    "replace", "isinstance", "enumerate", "zip", "sorted", "reversed", "abs", "any", "all",
    "getattr", "setattr", "hasattr", "super", "self", "staticmethod", "classmethod",
    "property", "datetime", "timedelta", "logging", "json", "loads", "dumps", "sleep",
    # JavaScript / TypeScript
    "settimeout", "setinterval", "promise", "resolve", "reject", "fetch", "foreach",
    "filter", "reduce", "push", "pop", "shift", "slice", "splice", "indexof", "includes",
    "parsefloat", "stringify", "parse", "addeventlistener", "queryselector", "document",
    "window", "error", "warn", "info", "debug", "trace",
    # generici
    "main", "init", "run", "start", "stop", "close", "open", "read", "write", "load",
    "save", "check", "validate", "process", "handle", "execute", "sizeof", "printf",
}


def resolve_dependencies(metadata):
    """Le PROBABLE_CALL, risolte contro TUTTI i componenti della codebase.

    Il pattern «identificatore seguito da parentesi» cattura ogni chiamata del
    linguaggio: da solo produce più rumore che segnale. Prima si escludeva solo
    quello che era dichiarato NELLO STESSO FILE, e la lista di esclusione era di
    venti parole. Ora, avendo l'indice dei componenti di tutta la codebase, ogni
    bersaglio può finire in una di tre categorie:

      · dichiarato da qualche parte nel codice caricato  → è una CALL vera, HIGH;
      · nome di libreria o troppo corto                  → si butta;
      · nient'altro                                      → resta PROBABLE_CALL,
        ma a confidenza LOW e col motivo scritto: punta fuori dal perimetro.

    Il conteggio delle tre categorie finisce nei metadati, così chi legge sa
    quanto della mappa delle dipendenze è certo e quanto è un sospetto."""
    dichiarati = {str(c.get("component_name", "")).strip().lower()
                  for c in metadata.get("components", [])}
    dichiarati.discard("")
    fuori, risolte, incerte, scartate = [], 0, 0, 0
    for d in metadata.get("dependencies", []):
        if d.get("dependency_type") != "PROBABLE_CALL":
            fuori.append(d)
            continue
        bersaglio = str(d.get("target", "")).strip().lower()
        # `pkg.procedura` risolve anche se in codebase è dichiarata `procedura`
        corto = bersaglio.rsplit(".", 1)[-1]
        primo = bersaglio.split(".", 1)[0]
        if bersaglio in dichiarati or corto in dichiarati:
            d["dependency_type"] = "CALL"
            d["confidence"] = "HIGH"
            d["evidence"] = "Call pattern resolved against a component declared in the codebase"
            risolte += 1
        elif (bersaglio in LIBRERIE_NOTE or corto in LIBRERIE_NOTE
              # `System.out.println`: quello che conta è il primo pezzo, non
              # l'ultimo — è lì che sta il nome della libreria.
              or (primo in LIBRERIE_NOTE and primo != bersaglio) or len(corto) < 4):
            scartate += 1
            continue
        else:
            d["confidence"] = "LOW"
            d["evidence"] = "Unresolved call pattern: target is not declared in the submitted code"
            incerte += 1
        fuori.append(d)
    metadata["dependencies"] = fuori
    metadata["dependency_resolution"] = {
        "resolved_to_declared_component": risolte,
        "unresolved_outside_perimeter": incerte,
        "discarded_as_library_noise": scartate,
    }
    return metadata


def analyze_single_source_locally(source):
    filename, code = source["filename"], source["content"]
    components = extract_functions_and_procedures(code, filename)
    dependencies = extract_imports_and_includes(code, filename)
    dependencies.extend(extract_probable_calls(code, filename, components))
    sql_metadata = extract_sql_metadata(code, filename)
    data_objects = extract_data_operations_with_regex(code, filename)
    for table in sql_metadata["tables"]:
        data_objects.append({
            "object_name": table, "object_type": "DATABASE_OBJECT", "operation": "UNKNOWN",
            "source_file": filename, "purpose": "", "evidence": "SQLGlot AST", "confidence": "HIGH"
        })
    return {
        "filename": filename, "language": source["language"], "hash": source["hash"],
        "line_count": len(code.splitlines()) if code.strip() else 0, "character_count": len(code),
        "components": components, "dependencies": unique_dicts(dependencies, ["source", "target", "dependency_type"]),
        "interfaces": extract_interfaces(code, filename),
        "data_objects": unique_dicts(data_objects, ["object_name", "operation", "source_file"]),
        "sql_tables": sql_metadata["tables"], "sql_columns": sql_metadata["columns"][:MAX_RIGHE_PER_TIPO],
        "sql_operations": sql_metadata["operations"], "sql_relationships": sql_metadata["relationships"],
        "local_risks": extract_local_risks(code, filename),
        "has_conditionals": bool(re.search(r"\b(?:IF|ELSE|ELSIF|CASE|WHEN|SWITCH)\b", code, flags=re.IGNORECASE))
    }

def extract_technical_metadata(sources):
    file_metadata = [analyze_single_source_locally(s) for s in sources]
    all_comps, all_deps, all_ints, all_objs, all_risks, all_tabs = [], [], [], [], [], []
    for m in file_metadata:
        all_comps.extend(m["components"])
        all_deps.extend(m["dependencies"])
        all_ints.extend(m["interfaces"])
        all_objs.extend(m["data_objects"])
        all_risks.extend(m["local_risks"])
        all_tabs.extend(m["sql_tables"])
    metadati = {
        "file_count": len(sources),
        "total_line_count": sum(m["line_count"] for m in file_metadata),
        "total_character_count": sum(m["character_count"] for m in file_metadata),
        "languages": unique_strings([m["language"] for m in file_metadata]),
        "detected_tables": unique_strings(all_tabs),
        "components": unique_dicts(all_comps, ["component_name", "component_type", "source_file"]),
        "dependencies": unique_dicts(all_deps, ["source", "target", "dependency_type"]),
        "interfaces": unique_dicts(all_ints, ["name", "interface_type", "source_file"]),
        "data_objects": unique_dicts(all_objs, ["object_name", "operation", "source_file"]),
        "local_risks": all_risks, "files": file_metadata
    }
    return resolve_dependencies(metadati)

def metadata_for_prompt(metadata, sources):
    """I metadati che vanno NEL prompt: solo i file di questo lotto, e senza il
    dettaglio per file, che raddoppia il prompt senza aggiungere fatti."""
    nomi = {s["filename"] for s in sources}
    def filtra(righe, campo):
        return [r for r in righe if r.get(campo) in nomi]
    return {
        "file_count": len(sources),
        "languages": unique_strings([s["language"] for s in sources]),
        "detected_tables": metadata.get("detected_tables", [])[:400],
        "components": filtra(metadata.get("components", []), "source_file")[:400],
        "dependencies": filtra(metadata.get("dependencies", []), "source")[:400],
        "interfaces": filtra(metadata.get("interfaces", []), "source_file")[:200],
        "data_objects": filtra(metadata.get("data_objects", []), "source_file")[:400],
        "local_risks": filtra(metadata.get("local_risks", []), "affected_component")[:200],
    }

# =============================================================================
# 7. AI ORCHESTRATION — catena modelli + contratto JSON
# =============================================================================
def build_chain(provider, api_key, azure_endpoint, model_name, preferenza, diario,
                ragionamento="low"):
    return CatenaModelli(
        provider=provider,
        chiave=api_key,
        endpoint=azure_endpoint or "",
        deployment=model_name or "",
        preferenza=preferenza,
        ragionamento=ragionamento,
        lingua="en",
        log=diario.append,
    )

def ask_model(catena, prompt, provider):
    """Una chiamata, con lo schema nativo dove il provider lo sa imporre."""
    schema = contract.schema_gemini() if provider == "Google Gemini" else None
    return catena.chiedi(
        prompt,
        sistema=contract.SISTEMA,
        json_mode=True,
        schema=schema,
        max_token=16000,
    )

def analyze_batch(catena, provider, sources, metadata, lotto):
    prompt = contract.prompt_analisi(sources, metadata_for_prompt(metadata, sources), lotto=lotto)
    risposta = ask_model(catena, prompt, provider)
    avvisi = []
    if risposta.troncata:
        avvisi.append(
            f"Batch {lotto[0]}/{lotto[1]}: the model hit its output limit; the answer was "
            "repaired and the last (incomplete) row was dropped."
        )
    grezzo = contract.estrai_json(risposta.testo)
    normalizzato = contract.normalizza(grezzo, avvisi)
    normalizzato["_modello"] = risposta.modello
    return normalizzato

def merge_static_and_ai_results(ai_result, metadata):
    """Le due metà si uniscono DOPO essere passate entrambe dal contratto: è
    l'unico modo perché le tabelle abbiano le stesse colonne."""
    r = dict(ai_result)
    statiche = {
        "components": contract.normalizza_righe("components", metadata.get("components", []), "STATIC_ANALYSIS"),
        "dependencies": contract.normalizza_righe("dependencies", metadata.get("dependencies", [])),
        "interfaces": contract.normalizza_righe("interfaces", metadata.get("interfaces", [])),
        "data_objects": contract.normalizza_righe("data_objects", metadata.get("data_objects", [])),
        "technical_risks": contract.normalizza_righe("technical_risks", metadata.get("local_risks", []), "STATIC_ANALYSIS"),
    }
    for nome, righe in statiche.items():
        r[nome] = contract.unisci_righe(nome, r.get(nome, []), righe)
    r = contract.numera_id(r)
    # I diagrammi si costruiscono DOPO l'unione, così il call graph contiene
    # anche le dipendenze trovate dal parser, non solo quelle viste dal modello.
    return diagrams.arricchisci(r)

def analysis_signature(sources, provider, model_name, preferenza):
    """L'impronta dell'analisi: stessi file, stesso provider, stesso contratto
    ⇒ stessa risposta. Serve a non ripagare (e non riaspettare) tre minuti di
    modello ogni volta che Streamlit ricarica la pagina."""
    parti = [contract.VERSIONE_CONTRATTO, provider, model_name or "", preferenza]
    parti += sorted(s["hash"] for s in sources)
    return hashlib.sha256("|".join(parti).encode()).hexdigest()[:16]

def analyze_legacy_application(sources, metadata, provider, api_key, model_name,
                               azure_endpoint=None, preferenza="qualita", progress=None,
                               ragionamento="low"):
    diario = []
    partenza = time.time()
    catena = build_chain(provider, api_key, azure_endpoint, model_name, preferenza, diario,
                         ragionamento)
    lotti = split_into_batches(sources)
    if len(lotti) > MAX_LOTTI:
        raise ValueError(
            f"The codebase would need {len(lotti)} batches (limit {MAX_LOTTI}). "
            "Analyse it in separate runs, by subsystem."
        )
    risultati = []
    for i, lotto in enumerate(lotti, start=1):
        if progress:
            progress(i, len(lotti), [s["filename"] for s in lotto])
        risultati.append(analyze_batch(catena, provider, lotto, metadata, (i, len(lotti))))
    unito = contract.unisci(risultati)
    unito["_modello"] = risultati[-1].get("_modello", "")
    unito["_diario"] = diario
    unito["_lotti"] = len(lotti)
    completo = merge_static_and_ai_results(unito, metadata)
    completo["_ragionamento"] = ragionamento
    completo["_durata_s"] = round(time.time() - partenza)
    if len(lotti) > 1:
        if progress:
            progress(len(lotti) + 1, len(lotti) + 1, ["consolidating the batches"])
        completo = consolida(catena, provider, completo, lotti)
        # I diagrammi si rifanno: i collegamenti fra lotti sono archi nuovi del
        # call graph, ed è esattamente quello che nessun lotto poteva vedere.
        completo = diagrams.arricchisci(completo)
        completo["_durata_s"] = round(time.time() - partenza)
    return completo


def consolida(catena, provider, risultato, lotti):
    """La passata finale sui soli risultati strutturati.

    I lotti non si vedono fra loro: ognuno scrive la propria sintesi come se
    fosse tutta l'applicazione, e una dipendenza fra un file del lotto 1 e uno
    del lotto 3 non la guarda nessuno. Questa chiamata NON contiene codice —
    solo l'inventario — quindi costa poche migliaia di token contro le
    centinaia di migliaia dell'analisi, e chiude il buco che pesa di più.

    Se fallisce non è grave: si tengono le sintesi per lotto e si scrive che è
    andata così. Una visione d'insieme mancante è un peccato; un'analisi persa
    per una chiamata accessoria sarebbe un difetto."""
    nomi_per_lotto = [[s["filename"] for s in lotto] for lotto in lotti]
    prompt = contract.prompt_consolidamento(risultato, nomi_per_lotto)
    try:
        risposta = catena.chiedi(
            prompt, sistema=contract.SISTEMA, json_mode=True,
            schema=contract.schema_consolidamento() if provider == "Google Gemini" else None,
            max_token=8000)
        grezzo = contract.estrai_json(risposta.testo)
    except Exception as e:
        avvisi = list(risultato.get("contract_warnings") or [])
        avvisi.append(f"consolidation pass failed ({getattr(e, 'causa', None) or type(e).__name__}): "
                      "per-batch summaries kept")
        risultato["contract_warnings"] = avvisi
        return risultato
    return contract.applica_consolidamento(risultato, grezzo)

# =============================================================================
# 8. RENDERING FUNCTIONS (SME REVIEW WORKFLOW)
# =============================================================================
def render_dataframe_section(title, records, empty_message, key, help_text=""):
    st.markdown(f"#### {title}")
    if help_text:
        st.caption(help_text)
    if not records:
        st.info(empty_message)
        return records
    df = pd.DataFrame(records)
    if "sme_approved" not in df.columns:
        df.insert(0, "sme_approved", False)
    else:
        df.insert(0, "sme_approved", df.pop("sme_approved").fillna(False).astype(bool))
    # Le colonne di servizio non si mostrano: confondono chi valida.
    df = df[[c for c in df.columns if not str(c).startswith("_")]]
    edited_df = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key=key,
        column_config={"sme_approved": st.column_config.CheckboxColumn(
            "✔", help="Tick when a domain expert has confirmed this row.", default=False)},
    )
    return edited_df.to_dict("records")

def render_contract_section(nome, result, key):
    return render_dataframe_section(
        _titolo_en(nome), result.get(nome, []),
        "Nothing found for this section.", key,
    )

_TITOLI_EN = {
    "business_processes": "Business Processes",
    "business_rules": "Business Rules",
    "components": "Components",
    "dependencies": "Dependencies",
    "interfaces": "Interfaces",
    "data_objects": "Data Objects",
    "data_flows": "Data Flows",
    "technical_risks": "Technical Risks",
    "impact_analysis": "Impact Analysis",
    "application_mapping": "Application Mapping",
    "validation_questions": "Questions for the SME",
    "assumptions": "Assumptions",
}
def _titolo_en(nome):
    return _TITOLI_EN.get(nome, nome.replace("_", " ").title())

def render_mermaid_diagram(title, diagram, filename, height="500px"):
    st.markdown(f"#### {title}")
    if not diagram:
        st.info("No diagram generated.")
        return
    try:
        st_mermaid(diagram, height=height)
    except Exception:
        st.warning("Diagram could not be rendered. Source below.")
    with st.expander("Diagram source"):
        st.code(diagram, language="mermaid")
    st.download_button(label=f"Download {filename}", data=diagram, file_name=filename,
                       mime="text/plain", use_container_width=True)

def quality_indicators(result, metadata):
    """Indicatori su QUANTO È ANCORATO il risultato, non su quanto è completo.

    Prima l'unico numero mostrato era una «Coverage %» che contava quante delle
    sei sezioni non erano vuote. Un'applicazione descritta con una riga per
    sezione dava 100%. Un numero del genere, messo grande in cima alla pagina,
    non è ottimista: è fuorviante, e qualcuno lo mette in una slide.

    Nessuna misura automatica può dire quanta parte di un'applicazione è stata
    catturata — servirebbe sapere in anticipo la risposta. Si può però misurare
    quanto è solido quello che c'è, ed è quello che si mostra:

      · quanti file sono stati effettivamente citati da almeno una riga;
      · quante righe portano un'evidenza dal codice;
      · quante righe sono ad alta confidenza;
      · quante dipendenze restano non risolte.
    """
    sezioni = {
        "Business logic": bool(result.get("business_rules") or result.get("business_processes")),
        "Dependencies": bool(result.get("dependencies")),
        "Interfaces": bool(result.get("interfaces")),
        "Data flows": bool(result.get("data_flows")),
        "Technical risks": bool(result.get("technical_risks")),
        "Application mapping": bool(result.get("application_mapping")),
    }
    file_totali = {f.get("filename") for f in metadata.get("files", [])} - {None, ""}
    citati = set()
    righe, con_evidenza, alta_confidenza, non_risolte = 0, 0, 0, 0
    for nome in contract.CAMPI:
        for r in result.get(nome, []) or []:
            righe += 1
            if str(r.get("evidence", "")).strip():
                con_evidenza += 1
            if str(r.get("confidence", "")).strip().upper() == "HIGH":
                alta_confidenza += 1
            if r.get("dependency_type") == "PROBABLE_CALL":
                non_risolte += 1
            for campo in ("source_file", "affected_component", "source"):
                v = str(r.get(campo, "")).strip()
                if v in file_totali:
                    citati.add(v)
    def pct(parte, tutto):
        return round(parte / tutto * 100) if tutto else 0
    return {
        "sezioni": sezioni,
        "sezioni_pct": pct(sum(sezioni.values()), len(sezioni)),
        "file_totali": len(file_totali),
        "file_citati": len(citati),
        "file_pct": pct(len(citati), len(file_totali)),
        "file_mai_citati": sorted(file_totali - citati),
        "righe": righe,
        "evidenza_pct": pct(con_evidenza, righe),
        "confidenza_alta_pct": pct(alta_confidenza, righe),
        "dipendenze_non_risolte": non_risolte,
    }

@st.cache_data(show_spinner=False)
def build_pdf(payload, metadata_payload, provider, model_name):
    return generate_pdf_report(analysis_result=json.loads(payload),
                               metadata=json.loads(metadata_payload),
                               provider=provider, model_name=model_name)

@st.cache_data(show_spinner=False)
def build_docx(payload, metadata_payload, provider, model_name):
    return generate_docx_report(analysis_result=json.loads(payload),
                                metadata=json.loads(metadata_payload),
                                provider=provider, model_name=model_name)

# =============================================================================
# 9. SIDEBAR
# =============================================================================
st.sidebar.title("⚙️ Configuration")
provider = st.sidebar.selectbox("AI Provider", ["Microsoft Azure OpenAI", "Anthropic Claude", "Google Gemini"])

azure_endpoint = None
if provider == "Microsoft Azure OpenAI":
    api_key = st.sidebar.text_input("API Key", type="password", value=os.environ.get("AZURE_OPENAI_API_KEY", ""))
    azure_endpoint = st.sidebar.text_input("Endpoint", value=os.environ.get("AZURE_OPENAI_ENDPOINT", ""))
    model_name = st.sidebar.text_input(
        "Deployment Name (first in the chain)", value=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        help="On Azure the callable name is the deployment name, which only you know. "
             "It always stays first in the chain; the other deployments found on the "
             "endpoint are used as fallback.")
elif provider == "Anthropic Claude":
    api_key = st.sidebar.text_input("API Key", type="password", value=os.environ.get("ANTHROPIC_API_KEY", ""))
    model_name = st.sidebar.text_input(
        "Preferred model (optional)", value=os.environ.get("ANTHROPIC_MODEL", ""),
        help="Leave empty to let the app discover the models available on this key.")
else:
    api_key = st.sidebar.text_input("API Key", type="password", value=os.environ.get("GEMINI_API_KEY", ""))
    model_name = st.sidebar.text_input(
        "Preferred model (optional)", value=os.environ.get("GEMINI_MODEL", ""),
        help="Leave empty to let the app discover the models available on this key.")

preferenza = "qualita" if st.sidebar.radio(
    "Model preference", ["Quality first", "Speed / cost first"], index=0,
    help="Quality first starts from the strongest models (pro / opus / large) and falls "
         "back downwards. Speed first is the Nuvia rule: fast models only."
) == "Quality first" else "velocita"

RAGIONAMENTO = {"Fast": "minimal", "Balanced": "low", "Thorough": "medium", "Deep": "high"}
ragionamento = RAGIONAMENTO[st.sidebar.select_slider(
    "Reasoning effort", options=list(RAGIONAMENTO), value="Balanced",
    help="How much the model may think before answering. This is the biggest lever on how "
         "long a run takes — far more than the choice of model. If a model refuses the level "
         "you pick (some will not go below medium), the app moves up one step for that model, "
         "remembers it, and carries on: you always get the fastest that model can do.")]

with st.sidebar.expander("🔌 Model chain", expanded=False):
    st.caption(
        "The app asks the provider which models this key can actually use, keeps the "
        "best ones, probes them with a two-word question (5s each, 10s overall) and "
        "runs the analysis on the first that answers — falling back downwards if it dies "
        "mid-run. The winner is remembered for 10 minutes."
    )
    if st.button("Test connection", use_container_width=True, disabled=not api_key):
        diario = []
        catena = build_chain(provider, api_key, azure_endpoint, model_name, preferenza, diario,
                             ragionamento)
        t0 = time.time()
        try:
            r = catena.chiedi("ping", solo_prova=True, forza_elenco=True)
            st.success(f"Answering model: {r.modello}  ({int((time.time()-t0)*1000)} ms)")
        except NessunModello as e:
            st.error(catena.messaggio_nessuno(e))
            st.caption(f"technical cause: {e.causa}")
        st.code("\n".join(diario) or "no log", language="text")

st.sidebar.divider()
st.sidebar.subheader("📂 Pilot Codebase")
uploaded_files = st.sidebar.file_uploader("Upload files", type=SUPPORTED_EXTENSIONS, accept_multiple_files=True)
pasted_filename = st.sidebar.text_input("Pasted source filename", value="pasted_source.sql")
pasted_code = st.sidebar.text_area("Or paste source code", height=200)

force_rerun = st.sidebar.checkbox("Force re-analysis", value=False,
                                  help="Off: identical input, provider and contract reuse the "
                                       "previous answer instead of paying for it again.")
run_analysis = st.sidebar.button("🚀 Analyze Application", type="primary", use_container_width=True)
if st.sidebar.button("🗑️ Clear Analysis", use_container_width=True):
    for key in ["analysis_result", "analysis_metadata", "analysis_sources",
                "analysis_provider", "analysis_model", "analysis_signature"]:
        st.session_state.pop(key, None)
    st.rerun()

# =============================================================================
# 10. MAIN
# =============================================================================
st.title("🧭 Legacy Application Knowledge Extractor")
st.caption("AI-assisted reverse engineering with human-in-the-loop SME validation.")

try:
    sources = build_source_collection(uploaded_files, pasted_code, pasted_filename)
except Exception as error:
    st.error(str(error))
    sources = []

if sources:
    caratteri = sum(len(s["content"]) for s in sources)
    lotti = len(split_into_batches(sources))
    st.caption(f"{len(sources)} file(s), {caratteri:,} characters"
               + (f" — will be analysed in {lotti} batches" if lotti > 1 else ""))

if run_analysis:
    if not sources:
        st.error("Provide source code.")
    elif not api_key:
        st.error("Missing API Key.")
    elif provider == "Microsoft Azure OpenAI" and not azure_endpoint:
        st.error("Missing Azure endpoint.")
    else:
        firma = analysis_signature(sources, provider, model_name, preferenza)
        if not force_rerun and st.session_state.get("analysis_signature") == firma:
            st.info("Same input as the previous run: showing the existing analysis. "
                    "Tick «Force re-analysis» to run it again.")
        else:
            barra = st.progress(0.0, text="Reading the code…")
            try:
                metadata = extract_technical_metadata(sources)

                inizio = time.time()

                def avanza(i, n, nomi):
                    # Il tempo che passa si mostra: un'analisi vera dura minuti,
                    # e una barra ferma senza numeri sembra bloccata.
                    barra.progress((i - 1) / n,
                                   text=f"Batch {i}/{n} · {int(time.time()-inizio)}s · "
                                        f"{', '.join(nomi)[:70]}")

                result = analyze_legacy_application(
                    sources, metadata, provider, api_key, model_name,
                    azure_endpoint, preferenza, progress=avanza,
                    ragionamento=ragionamento)
                barra.progress(1.0, text="Done.")
                st.session_state["analysis_result"] = result
                st.session_state["analysis_metadata"] = metadata
                st.session_state["analysis_sources"] = sources
                st.session_state["analysis_provider"] = provider
                st.session_state["analysis_model"] = result.get("_modello", model_name)
                st.session_state["analysis_signature"] = firma
            except NessunModello as e:
                barra.empty()
                catena = build_chain(provider, api_key, azure_endpoint, model_name, preferenza, [],
                                     ragionamento)
                st.error(catena.messaggio_nessuno(e))
                with st.expander("What the app tried"):
                    st.code("\n".join(e.diario) or f"cause: {e.causa}", language="text")
            except Exception as e:
                barra.empty()
                st.error(f"Analysis failed: {e}")

if "analysis_result" not in st.session_state:
    st.info("Upload source files and start the analysis.")
    st.stop()

result = st.session_state["analysis_result"]
metadata = st.session_state["analysis_metadata"]
saved_sources = st.session_state["analysis_sources"]

q = quality_indicators(result, metadata)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Files", metadata["file_count"])
c2.metric("Lines of Code", metadata["total_line_count"])
c3.metric("Components", len(result.get("components", [])))
c4.metric("Business rules", len(result.get("business_rules", [])))
c5.metric("Files described", f"{q['file_pct']}%",
          help="Share of the submitted files that at least one row refers to. "
               "This is not a measure of how much of the application has been captured — "
               "no automatic measure can tell you that.")

with st.expander("How well grounded is this analysis?"):
    st.caption("These numbers describe how solid the rows are, not how complete the picture is.")
    g1, g2, g3 = st.columns(3)
    g1.metric("Rows with evidence", f"{q['evidenza_pct']}%", help=f"{q['righe']} rows in total")
    g2.metric("HIGH confidence", f"{q['confidenza_alta_pct']}%")
    g3.metric("Unresolved calls", q["dipendenze_non_risolte"],
              help="Call patterns whose target is not declared in the submitted code: "
                   "either outside the perimeter, or noise.")
    st.write("**Sections filled:** " + ", ".join(
        ("✅ " if v else "⬜ ") + k for k, v in q["sezioni"].items()))
    if q["file_mai_citati"]:
        st.warning("No row refers to these files — worth checking whether they were "
                   "understood at all: " + ", ".join(q["file_mai_citati"][:12])
                   + (" …" if len(q["file_mai_citati"]) > 12 else ""))
    risoluzione = metadata.get("dependency_resolution")
    if risoluzione:
        st.caption("Dependency resolution — "
                   f"resolved to a declared component: {risoluzione['resolved_to_declared_component']} · "
                   f"outside the perimeter: {risoluzione['unresolved_outside_perimeter']} · "
                   f"discarded as library noise: {risoluzione['discarded_as_library_noise']}")

avvisi = result.get("contract_warnings") or []
if avvisi:
    with st.expander(f"⚠️ {len(avvisi)} contract notes (what the app had to fix in the model's answer)"):
        st.code("\n".join(avvisi[:200]), language="text")

tabs = st.tabs(["Overview", "Business Logic", "Architecture", "Data Flows",
                "Risks & Impact", "Diagrams", "SME Validation", "Static Evidence", "Downloads"])

with tabs[0]:
    st.success(result.get("executive_summary") or "N/A")
    st.write("**Purpose:**", result.get("application_purpose") or "N/A")
    st.write("**Notes:**", result.get("technical_notes") or "N/A")
    st.caption(f"Model that answered: {st.session_state.get('analysis_model','?')} · "
               f"reasoning: {result.get('_ragionamento','?')} · "
               f"batches: {result.get('_lotti', 1)} · "
               f"took {result.get('_durata_s','?')}s · "
               f"contract v{result.get('contract_version','?')}")

with tabs[1]:
    result["business_processes"] = render_contract_section("business_processes", result, "bp_edit")
    result["business_rules"] = render_contract_section("business_rules", result, "br_edit")

with tabs[2]:
    result["components"] = render_contract_section("components", result, "comp_edit")
    result["dependencies"] = render_contract_section("dependencies", result, "dep_edit")
    result["interfaces"] = render_contract_section("interfaces", result, "int_edit")
    result["application_mapping"] = render_contract_section("application_mapping", result, "map_edit")

with tabs[3]:
    result["data_objects"] = render_contract_section("data_objects", result, "obj_edit")
    result["data_flows"] = render_contract_section("data_flows", result, "flow_edit")

with tabs[4]:
    result["technical_risks"] = render_contract_section("technical_risks", result, "risk_edit")
    result["impact_analysis"] = render_contract_section("impact_analysis", result, "impact_edit")

with tabs[5]:
    DIAGRAMMI = {
        "Process Flow": ("mermaid_process_flow", "bp.mmd"),
        "App Map": ("mermaid_application_map", "app.mmd"),
        "Data Flow": ("mermaid_data_flow", "df.mmd"),
        "Call Graph": ("mermaid_call_graph", "cg.mmd"),
    }
    col_a, col_b = st.columns([2, 1])
    dt = col_a.selectbox("Diagram", list(DIAGRAMMI))
    campo, nomefile = DIAGRAMMI[dt]
    dai_dati = (result.get("_diagrammi_dai_dati") or {}).get(campo, "")
    dal_modello = (result.get("_diagrammi_dal_modello") or {}).get(campo, "")

    # Due versioni dello stesso diagramma: quella del modello e quella
    # costruita dalle tabelle. La seconda non può contraddire le tabelle,
    # perché è le tabelle — e si rifà dopo le correzioni dello SME.
    scelte = []
    if dal_modello.strip():
        scelte.append("From the model")
    if dai_dati.strip():
        scelte.append("Built from the tables")
    if len(scelte) > 1:
        predefinita = "Built from the tables" if result.get(campo) == dai_dati else "From the model"
        sorgente = col_b.radio("Source", scelte, index=scelte.index(predefinita), horizontal=True)
        diagramma = dai_dati if sorgente == "Built from the tables" else dal_modello
    else:
        diagramma = result.get(campo) or dai_dati or dal_modello
    fonte_scelta = (result.get("_diagrammi_fonte") or {}).get(campo, "")
    if fonte_scelta == "dati":
        st.caption("Source: built from the validated tables. "
                   "Use «Rebuild» below after correcting rows to keep it in step.")
    elif fonte_scelta == "modello":
        st.caption("Source: written by the model.")

    if st.button("🔄 Rebuild from the current tables", use_container_width=True,
                 help="Redraws all four diagrams from the rows as they are now, "
                      "including the SME's corrections."):
        result["_diagrammi_dai_dati"] = diagrams.costruisci(result)
        for _c in diagrams.COSTRUTTORI:
            if result["_diagrammi_dai_dati"].get(_c):
                result[_c] = result["_diagrammi_dai_dati"][_c]
        st.session_state["analysis_result"] = result
        st.rerun()

    render_mermaid_diagram(dt, diagramma, nomefile)

with tabs[6]:
    st.caption("What the model could not settle on its own. These are the rows to take "
               "to the business, not to the code.")
    result["validation_questions"] = render_contract_section("validation_questions", result, "vq_edit")
    result["assumptions"] = render_contract_section("assumptions", result, "as_edit")

with tabs[7]:
    st.caption("Everything below was produced by the parser, not by the model.")
    st.json(metadata, expanded=False)

# SALVATAGGIO STATO: sincronizza le modifiche fatte dallo SME nelle tabelle
st.session_state["analysis_result"] = result

with tabs[8]:
    st.markdown("### 📥 Export Validated Knowledge Artifacts")
    st.write("Generate and download the complete technical documentation including all "
             "SME-validated business rules, technical risks and architectural metadata.")
    # Dove vengono disegnati i diagrammi va detto PRIMA di premere il bottone:
    # il codice mermaid descrive l'applicazione del cliente, e mandarlo a un
    # servizio pubblico è una decisione, non un dettaglio di implementazione.
    _locale_ok, _locale_dettaglio = mermaid_render.disponibile()
    if _locale_ok:
        st.caption(f"Diagrams are rendered locally — nothing leaves this machine ({_locale_dettaglio}).")
    elif os.environ.get("MERMAID_LOCAL_ONLY") == "1":
        st.warning("Local diagram rendering is unavailable and the external service is "
                   f"disabled: documents will carry the diagram source instead of the image. ({_locale_dettaglio})")
    else:
        st.warning("Local diagram rendering is unavailable, so diagram code will be sent to the "
                   f"public mermaid.ink service. ({_locale_dettaglio}) "
                   "Install it with: npm install -g @mermaid-js/mermaid-cli — "
                   "or set MERMAID_LOCAL_ONLY=1 to forbid the external call.")
    # I due export costano: il PDF scarica quattro diagrammi da mermaid.ink. Prima
    # venivano rigenerati a OGNI interazione con la pagina, anche solo per spuntare
    # una casella. Ora si generano quando servono, e il risultato si tiene in cache.
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    metadata_payload = json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str)
    col_pdf, col_docx, col_json = st.columns(3)

    with col_pdf:
        if st.button("📄 Build PDF report", use_container_width=True):
            with st.spinner("Rendering diagrams and building the PDF…"):
                st.session_state["pdf_bytes"] = build_pdf(
                    payload, metadata_payload, st.session_state.get("analysis_provider", "AI Provider"),
                    st.session_state.get("analysis_model", "Default Model"))
        if st.session_state.get("pdf_bytes"):
            st.download_button("⬇️ Download PDF", data=st.session_state["pdf_bytes"],
                               file_name="Legacy_Application_Documentation.pdf",
                               mime="application/pdf", use_container_width=True)

    with col_docx:
        if st.button("📝 Build Word (.docx)", use_container_width=True):
            with st.spinner("Building the Word document…"):
                st.session_state["docx_bytes"] = build_docx(
                    payload, metadata_payload, st.session_state.get("analysis_provider", "AI Provider"),
                    st.session_state.get("analysis_model", "Default Model"))
        if st.session_state.get("docx_bytes"):
            st.download_button("⬇️ Download Word", data=st.session_state["docx_bytes"],
                               file_name="Legacy_Application_Documentation.docx",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               use_container_width=True)

    with col_json:
        st.download_button("📦 Export JSON Data",
                           data=json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8"),
                           file_name="Legacy_Application_Analysis.json",
                           mime="application/json", use_container_width=True)
