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
import ui
from exporter import generate_docx_report, generate_pdf_report
from model_chain import CatenaModelli, NessunModello

# =============================================================================
# 1. PAGE CONFIGURATION
# =============================================================================
st.set_page_config(
    page_title="Legacy Application Knowledge Extractor",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui.applica_tema()

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
# =============================================================================
# 8. LE TABELLE DI VALIDAZIONE
# È qui che si consuma il tempo di chi usa l'applicazione: dodici tabelle da
# leggere riga per riga. Tre cose le rendono sopportabili, e sono tutte qui
# sotto: sapere quante righe restano da guardare, poter cercare dentro una
# sezione, e non dover scrivere a mano i valori che sono a scelta fissa.
# =============================================================================
SEZIONI = {
    "business_processes": ("Business processes",
        "What the application does, reconstructed from the code."),
    "business_rules": ("Business rules",
        "The decisions encoded in the code. Usually the most valuable section — and the one to check hardest."),
    "components": ("Components",
        "Procedures, functions, packages and modules found in the source."),
    "dependencies": ("Dependencies",
        "What calls, imports or reads what. Rows still marked PROBABLE_CALL point outside the submitted code."),
    "interfaces": ("Interfaces",
        "Where this application touches the outside world."),
    "data_objects": ("Data objects",
        "Tables, views, files and queues the code reads or writes."),
    "data_flows": ("Data flows",
        "Where data comes from, where it goes, and what changes on the way."),
    "technical_risks": ("Technical risks",
        "What a migration team should know before touching this."),
    "impact_analysis": ("Impact analysis",
        "What breaks if you change what."),
    "application_mapping": ("Application map",
        "Links to the other systems in the perimeter."),
    "validation_questions": ("Questions for the expert",
        "What the code cannot answer. Take these to the business, not to the source."),
    "assumptions": ("Assumptions",
        "What the analysis took for granted to reach its conclusions."),
}

ETICHETTE = {
    "process_id": "ID", "rule_id": "ID", "flow_id": "ID", "risk_id": "ID",
    "impact_id": "ID", "mapping_id": "ID", "question_id": "ID", "assumption_id": "ID",
    "source_file": "File", "source_component": "In", "component_name": "Name",
    "component_type": "Kind", "dependency_type": "Kind", "interface_type": "Kind",
    "object_name": "Object", "object_type": "Kind", "external_system": "System",
    "integration_type": "Via", "affected_component": "Affects",
    "business_impact": "Why it matters", "why_it_matters": "Why it matters",
    "risk_if_wrong": "If wrong", "line_number": "Line", "related_ids": "Related",
    "addressed_to": "Ask", "data_description": "Data", "impact_description": "Effect",
    "change_scenario": "Change", "involved_components": "Components",
    "affected_components": "Components", "source": "Found by",
}
# I campi che contengono prosa: vogliono spazio, gli altri no.
LARGHI = {"description", "evidence", "condition", "action", "impact", "recommendation",
          "impact_description", "business_impact", "question", "why_it_matters",
          "assumption", "purpose", "data_description", "transformation", "mitigation",
          "basis", "risk_if_wrong", "change_scenario", "outcome", "trigger"}


def _etichetta(campo):
    return ETICHETTE.get(campo) or campo.replace("_", " ").capitalize()


def _config_colonne(nome):
    """Le colonne, descritte una per una.

    Due cose che l'interfaccia guadagna qui: ogni colonna porta con sé la
    propria spiegazione (la stessa che il contratto dà al modello, quindi non
    possono divergere), e i campi a scelta fissa diventano menù a tendina. Il
    secondo punto non è estetica: finché `severity` era testo libero, chi
    validava poteva scriverci «molto alto» e il filtro per gravità smetteva di
    funzionare senza dire niente a nessuno."""
    spec = contract.CAMPI[nome]
    # L'intestazione è una parola, non solo un segno di spunta: un lettore di
    # schermo legge «Checked», non «segno di spunta».
    cfg = {"sme_approved": st.column_config.CheckboxColumn(
        "Checked", help="Tick when you have checked this row against the code or with the business.",
        default=False, width="small")}
    for campo, (descrizione, valori) in spec["campi"].items():
        if valori:
            cfg[campo] = st.column_config.SelectboxColumn(
                _etichetta(campo), options=list(valori), help=descrizione or None, width="small")
        else:
            larghezza = "large" if campo in LARGHI else (
                "small" if campo.endswith("_id") or campo == "line_number" else "medium")
            cfg[campo] = st.column_config.TextColumn(
                _etichetta(campo), help=descrizione or None, width=larghezza)
    return cfg


def _ordina_colonne(df, nome):
    spec = contract.CAMPI[nome]
    if "sme_approved" not in df.columns:
        df.insert(0, "sme_approved", False)
    df["sme_approved"] = df["sme_approved"].fillna(False).astype(bool)
    previste = ["sme_approved"] + list(spec["campi"].keys())
    extra = [c for c in df.columns if c not in previste and not str(c).startswith("_")]
    return df.reindex(columns=previste + extra)


def render_tabella(nome, risultato, chiave):
    spec = contract.CAMPI[nome]
    titolo, spiegazione = SEZIONI[nome]
    righe = list(risultato.get(nome, []) or [])
    confermate = sum(1 for r in righe if r.get("sme_approved"))
    ui.sezione(titolo, spiegazione, len(righe), confermate if righe else None)

    if not righe:
        ui.nota("Nothing here. An empty section is a valid answer: it means the code "
                "did not show any — not that the analysis gave up.")
        return righe

    c1, c2 = st.columns([3, 2])
    cerca = c1.text_input("Search", key=chiave + "_q",
                          placeholder="any word in any column",
                          help="Filters the rows below. Clear it to add or remove rows.")
    da_vedere = c2.checkbox("Only rows still to check", key=chiave + "_f",
                            value=False, disabled=confermate == 0)

    coppie = []
    for i, r in enumerate(righe):
        if cerca and cerca.lower() not in " ".join(str(v) for v in r.values()).lower():
            continue
        if da_vedere and r.get("sme_approved"):
            continue
        coppie.append((i, r))

    filtrato = bool(cerca) or da_vedere
    if filtrato and not coppie:
        ui.nota("No row matches the filter.")
        return righe

    df = _ordina_colonne(pd.DataFrame([r for _, r in coppie]), nome)
    modificato = st.data_editor(
        df, hide_index=True, **ui.LARGA,
        # Con un filtro attivo non si aggiungono né si tolgono righe: le
        # modifiche tornano al loro posto per posizione, e questo funziona solo
        # se il numero di righe non cambia sotto le mani.
        num_rows="fixed" if filtrato else "dynamic",
        key=chiave, column_config=_config_colonne(nome))
    nuove = modificato.to_dict("records")

    if not filtrato:
        return nuove
    for (indice, _), nuova in zip(coppie, nuove):
        righe[indice] = nuova
    st.caption(f"Showing {len(coppie)} of {len(righe)} rows. Clear the filter to add or remove rows.")
    return righe


def render_diagramma(titolo, diagramma, nomefile):
    if not diagramma:
        ui.nota("No diagram for this one — neither the model nor the tables had enough to draw.")
        return
    try:
        st_mermaid(diagramma, height="520px")
    except Exception:
        st.warning("The diagram could not be drawn here. Its source is below — "
                   "paste it into mermaid.live to see what is wrong.")
    with st.expander("Diagram source"):
        st.code(diagramma, language="mermaid")
    st.download_button(f"Download {nomefile}", data=diagramma, file_name=nomefile,
                       mime="text/plain")


def quality_indicators(result, metadata):
    """Indicatori su QUANTO È ANCORATO il risultato, non su quanto è completo.

    Prima l'unico numero mostrato era una «Coverage %» che contava quante delle
    sei sezioni non erano vuote. Un'applicazione descritta con una riga per
    sezione dava 100%. Un numero del genere, messo grande in cima alla pagina,
    non è ottimista: è fuorviante, e qualcuno lo mette in una slide.

    Nessuna misura automatica può dire quanta parte di un'applicazione è stata
    catturata — servirebbe sapere in anticipo la risposta. Si può però misurare
    quanto è solido quello che c'è, ed è quello che si mostra."""
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
    righe, con_evidenza, alta, non_risolte, confermate = 0, 0, 0, 0, 0
    gravi = {"CRITICAL": 0, "HIGH": 0}
    for nome in contract.CAMPI:
        for r in result.get(nome, []) or []:
            righe += 1
            if str(r.get("evidence", "")).strip():
                con_evidenza += 1
            if str(r.get("confidence", "")).strip().upper() == "HIGH":
                alta += 1
            if r.get("sme_approved"):
                confermate += 1
            if r.get("dependency_type") == "PROBABLE_CALL":
                non_risolte += 1
            sev = str(r.get("severity", "")).strip().upper()
            if sev in gravi:
                gravi[sev] += 1
            for campo in ("source_file", "affected_component", "source"):
                if str(r.get(campo, "")).strip() in file_totali:
                    citati.add(str(r.get(campo, "")).strip())

    def pct(parte, tutto):
        return round(parte / tutto * 100) if tutto else 0

    return {"sezioni": sezioni, "sezioni_pct": pct(sum(sezioni.values()), len(sezioni)),
            "file_totali": len(file_totali), "file_citati": len(citati),
            "file_pct": pct(len(citati), len(file_totali)),
            "file_mai_citati": sorted(file_totali - citati),
            "righe": righe, "confermate": confermate,
            "confermate_pct": pct(confermate, righe),
            "evidenza_pct": pct(con_evidenza, righe),
            "confidenza_alta_pct": pct(alta, righe),
            "dipendenze_non_risolte": non_risolte,
            "critici": gravi["CRITICAL"], "alti": gravi["HIGH"]}


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
# 9. LA BARRA LATERALE — tre tappe, in ordine.
# I numeri ci stanno perché questa È una sequenza: senza chiave non si analizza,
# senza sorgenti non si esporta. Fuori da una sequenza vera, numerare è
# decorazione.
# =============================================================================
ui.tappa("1", "Model")
provider = st.sidebar.selectbox(
    "Provider", ["Microsoft Azure OpenAI", "Anthropic Claude", "Google Gemini"],
    help="Where the analysis runs. The app finds the usable models on your key by itself.")

azure_endpoint = None
if provider == "Microsoft Azure OpenAI":
    api_key = st.sidebar.text_input("API key", type="password",
                                    value=os.environ.get("AZURE_OPENAI_API_KEY", ""))
    azure_endpoint = st.sidebar.text_input("Endpoint",
                                           value=os.environ.get("AZURE_OPENAI_ENDPOINT", ""))
    model_name = st.sidebar.text_input(
        "Deployment name", value=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        help="On Azure the callable name is the deployment name, which only you know. "
             "It stays first in the chain; other deployments on the endpoint act as fallback.")
elif provider == "Anthropic Claude":
    api_key = st.sidebar.text_input("API key", type="password",
                                    value=os.environ.get("ANTHROPIC_API_KEY", ""))
    model_name = st.sidebar.text_input(
        "Preferred model", value=os.environ.get("ANTHROPIC_MODEL", ""),
        placeholder="leave empty to choose automatically",
        help="Leave empty and the app uses the best model your key can reach.")
else:
    api_key = st.sidebar.text_input("API key", type="password",
                                    value=os.environ.get("GEMINI_API_KEY", ""))
    model_name = st.sidebar.text_input(
        "Preferred model", value=os.environ.get("GEMINI_MODEL", ""),
        placeholder="leave empty to choose automatically",
        help="Leave empty and the app uses the best model your key can reach.")

preferenza = "qualita" if st.sidebar.radio(
    "Pick models by", ["Quality", "Speed and cost"], index=0, horizontal=True,
    help="Quality starts from the strongest models and falls back downwards. "
         "Speed keeps only the fast ones."
) == "Quality" else "velocita"

RAGIONAMENTO = {"Fast": "minimal", "Balanced": "low", "Thorough": "medium", "Deep": "high"}
ragionamento = RAGIONAMENTO[st.sidebar.select_slider(
    "Thinking time", options=list(RAGIONAMENTO), value="Balanced",
    help="How much the model may think before answering. This is the biggest lever on how "
         "long a run takes — more than the choice of model. If a model refuses the level you "
         "pick, the app moves up one step for that model and carries on.")]

with st.sidebar.expander("Check the connection"):
    st.caption("Runs a two-word question against each model in turn and reports "
               "the first that answers.")
    if st.button("Run check", disabled=not api_key, **ui.LARGA):
        diario = []
        catena = build_chain(provider, api_key, azure_endpoint, model_name, preferenza, diario,
                             ragionamento)
        t0 = time.time()
        try:
            r = catena.chiedi("ping", solo_prova=True, forza_elenco=True)
            st.success(f"{r.modello} answered in {int((time.time()-t0)*1000)} ms")
        except NessunModello as e:
            st.error(catena.messaggio_nessuno(e))
            st.caption(f"technical cause: {e.causa}")
        st.code("\n".join(diario) or "no log", language="text")

ui.tappa("2", "Source code")
uploaded_files = st.sidebar.file_uploader(
    "Files", type=SUPPORTED_EXTENSIONS, accept_multiple_files=True,
    help="Oracle PL/SQL, COBOL, RPG, Java, Python and more. Up to 2 MB per file.")
with st.sidebar.expander("Or paste a snippet"):
    pasted_filename = st.text_input("File name", value="pasted_source.sql")
    pasted_code = st.text_area("Source", height=180,
                               placeholder="Paste code here to analyse it without uploading a file.")

ui.tappa("3", "Run")
force_rerun = st.sidebar.checkbox(
    "Analyse again from scratch", value=False,
    help="Off: the same files, provider and contract reuse the previous answer "
         "instead of paying for it a second time.")
run_analysis = st.sidebar.button("Analyse the application", type="primary", **ui.LARGA)
if st.sidebar.button("Clear results", **ui.LARGA):
    for key in ["analysis_result", "analysis_metadata", "analysis_sources",
                "analysis_provider", "analysis_model", "analysis_signature",
                "pdf_bytes", "docx_bytes"]:
        st.session_state.pop(key, None)
    st.rerun()

# =============================================================================
# 10. LA PAGINA
# =============================================================================
try:
    sources = build_source_collection(uploaded_files, pasted_code, pasted_filename)
except Exception as error:
    st.error(str(error))
    sources = []

stato = []
stato.append(ui.marca(provider.replace("Microsoft ", "").replace("Anthropic ", ""), "◇",
                      "accesa" if api_key else "spenta"))
stato.append(ui.marca("API key set" if api_key else "API key missing", "⌁",
                      "ok" if api_key else "alta"))
if sources:
    caratteri = sum(len(s["content"]) for s in sources)
    lotti = len(split_into_batches(sources))
    stato.append(ui.marca(f"{len(sources)} file{'s' if len(sources) != 1 else ''}"
                          f" · {caratteri:,} characters", "▤"))
    if lotti > 1:
        stato.append(ui.marca(f"{lotti} batches", "▥"))
else:
    stato.append(ui.marca("No source loaded", "▤", "spenta"))

ui.testata("Legacy Application Knowledge Extractor",
           "Read a legacy codebase and hand a domain expert something they can check, "
           "correct and sign.", stato)

if run_analysis:
    if not sources:
        st.error("Add at least one file, or paste a snippet, before running the analysis.")
    elif not api_key:
        st.error("The API key is missing. Add it under step 1 and run again.")
    elif provider == "Microsoft Azure OpenAI" and not azure_endpoint:
        st.error("Azure needs the endpoint of your resource. Add it under step 1.")
    else:
        firma = analysis_signature(sources, provider, model_name, preferenza)
        if not force_rerun and st.session_state.get("analysis_signature") == firma:
            st.info("Same files and same settings as the last run — showing that result. "
                    "Tick «Analyse again from scratch» to pay for a new one.")
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
                barra.empty()
                st.session_state.update({
                    "analysis_result": result, "analysis_metadata": metadata,
                    "analysis_sources": sources, "analysis_provider": provider,
                    "analysis_model": result.get("_modello", model_name),
                    "analysis_signature": firma})
                st.session_state.pop("pdf_bytes", None)
                st.session_state.pop("docx_bytes", None)
                ui.avviso_temporaneo(f"Analysed in {result.get('_durata_s', '?')}s")
            except NessunModello as e:
                barra.empty()
                catena = build_chain(provider, api_key, azure_endpoint, model_name, preferenza, [],
                                     ragionamento)
                st.error(catena.messaggio_nessuno(e))
                with st.expander("What the app tried"):
                    st.code("\n".join(e.diario) or f"cause: {e.causa}", language="text")
            except Exception as e:
                barra.empty()
                st.error(f"The analysis stopped: {e}")

if "analysis_result" not in st.session_state:
    ui.stato_vuoto(
        "Start with one file",
        "The application reads your source twice — once with a parser, which is never wrong "
        "but understands nothing, and once with a model, which understands but can be wrong. "
        "You get both, marked for where each row came from.",
        ["<b>Connect a model.</b> Paste an API key under step 1. The app finds the usable "
         "models on that key by itself — you do not have to name one.",
         "<b>Add source code.</b> Upload files, or paste a snippet. A single stored "
         "procedure is enough for a first look.",
         "<b>Run the analysis</b>, then work down the tables. Tick a row when you have "
         "checked it, and export when you are done."])
    st.stop()

result = st.session_state["analysis_result"]
metadata = st.session_state["analysis_metadata"]
q = quality_indicators(result, metadata)

ui.cifre([
    {"valore": f"{metadata['file_count']}", "voce": "Files read",
     "nota": f"{metadata['total_line_count']:,} lines"},
    {"valore": f"{len(result.get('business_rules', []))}", "voce": "Business rules",
     "nota": "the section that pays for the run", "rilievo": True},
    {"valore": f"{len(result.get('components', []))}", "voce": "Components",
     "nota": f"{len(result.get('dependencies', []))} dependencies"},
    {"valore": f"{q['critici'] + q['alti']}", "voce": "Serious risks",
     "nota": f"{q['critici']} critical · {q['alti']} high"},
    {"valore": f"{q['confermate_pct']}%", "voce": "Rows checked",
     "nota": f"{q['confermate']} of {q['righe']}"},
])

tabs = st.tabs(["Summary", "Business", "Architecture", "Data", "Risks", "Diagrams",
                "For the expert", "Parser evidence", "Export"])

with tabs[0]:
    st.markdown("#### What this application does")
    st.write(result.get("application_purpose") or "—")
    st.markdown("#### In full")
    st.write(result.get("executive_summary") or "—")
    if (result.get("technical_notes") or "").strip():
        st.markdown("#### Notes for a migration team")
        st.write(result["technical_notes"])

    st.markdown("#### How to read the tables")
    ui.fila([ui.marca("Parser", "■"), ui.marca("Model", "□"),
             ui.marca("HIGH", "●●●"), ui.marca("MEDIUM", "●●○"), ui.marca("LOW", "●○○"),
             ui.marca_gravita("CRITICAL"), ui.marca_gravita("HIGH"),
             ui.marca_gravita("MEDIUM"), ui.marca_gravita("LOW")])
    st.caption("A filled square is a fact the parser found in the source and cannot be wrong "
               "about. A hollow square is the model's reading of it, and carries a confidence. "
               "Nothing here is conveyed by colour alone.")

    with st.expander("How well grounded is this analysis?"):
        st.caption("These numbers say how solid the rows are — not how much of the "
                   "application has been captured. No automatic measure can tell you that.")
        ui.cifre([
            {"valore": f"{q['file_pct']}%", "voce": "Files described",
             "nota": f"{q['file_citati']} of {q['file_totali']}"},
            {"valore": f"{q['evidenza_pct']}%", "voce": "Rows with evidence"},
            {"valore": f"{q['confidenza_alta_pct']}%", "voce": "High confidence"},
            {"valore": f"{q['dipendenze_non_risolte']}", "voce": "Unresolved calls",
             "nota": "target not declared in the code you sent"},
        ])
        st.write("**Sections filled:** " + ", ".join(
            ("✓ " if v else "· ") + k for k, v in q["sezioni"].items()))
        if q["file_mai_citati"]:
            st.warning("No row refers to these files. Worth checking whether they were "
                       "understood at all: " + ", ".join(q["file_mai_citati"][:12])
                       + (" …" if len(q["file_mai_citati"]) > 12 else ""))
        risoluzione = metadata.get("dependency_resolution")
        if risoluzione:
            st.caption(
                f"Dependencies — resolved to a declared component: "
                f"{risoluzione['resolved_to_declared_component']} · outside the perimeter: "
                f"{risoluzione['unresolved_outside_perimeter']} · discarded as library noise: "
                f"{risoluzione['discarded_as_library_noise']}")

    avvisi = result.get("contract_warnings") or []
    if avvisi:
        with st.expander(f"What the app had to fix in the model's answer ({len(avvisi)})"):
            st.caption("Missing fields, values put back in range, rows dropped. Kept in the "
                       "open so you know how much to trust what you are reading.")
            st.code("\n".join(avvisi[:200]), language="text")

    st.caption(f"Answered by {st.session_state.get('analysis_model', '?')} · "
               f"thinking: {result.get('_ragionamento', '?')} · "
               f"batches: {result.get('_lotti', 1)} · "
               f"took {result.get('_durata_s', '?')}s · "
               f"contract v{result.get('contract_version', '?')}")

with tabs[1]:
    result["business_processes"] = render_tabella("business_processes", result, "bp_edit")
    st.divider()
    result["business_rules"] = render_tabella("business_rules", result, "br_edit")

with tabs[2]:
    result["components"] = render_tabella("components", result, "comp_edit")
    st.divider()
    result["dependencies"] = render_tabella("dependencies", result, "dep_edit")
    st.divider()
    result["interfaces"] = render_tabella("interfaces", result, "int_edit")
    st.divider()
    result["application_mapping"] = render_tabella("application_mapping", result, "map_edit")

with tabs[3]:
    result["data_objects"] = render_tabella("data_objects", result, "obj_edit")
    st.divider()
    result["data_flows"] = render_tabella("data_flows", result, "flow_edit")

with tabs[4]:
    result["technical_risks"] = render_tabella("technical_risks", result, "risk_edit")
    st.divider()
    result["impact_analysis"] = render_tabella("impact_analysis", result, "impact_edit")

with tabs[5]:
    DIAGRAMMI = {
        "Process flow": ("mermaid_process_flow", "process_flow.mmd"),
        "Application map": ("mermaid_application_map", "application_map.mmd"),
        "Data flow": ("mermaid_data_flow", "data_flow.mmd"),
        "Call graph": ("mermaid_call_graph", "call_graph.mmd"),
    }
    scelto = ui.scelta_segmentata("Diagram", list(DIAGRAMMI), 0, "scelta_diagramma")
    campo, nomefile = DIAGRAMMI[scelto]
    dai_dati = (result.get("_diagrammi_dai_dati") or {}).get(campo, "")
    dal_modello = (result.get("_diagrammi_dal_modello") or {}).get(campo, "")

    versioni = []
    if dal_modello.strip():
        versioni.append("From the model")
    if dai_dati.strip():
        versioni.append("Built from the tables")
    if len(versioni) > 1:
        predefinita = "Built from the tables" if result.get(campo) == dai_dati else "From the model"
        quale = ui.scelta_segmentata("Version", versioni, versioni.index(predefinita),
                                     "versione_diagramma",
                                     "The tables version cannot contradict the rows you "
                                     "are validating, because it is drawn from them.")
        diagramma = dai_dati if quale == "Built from the tables" else dal_modello
    else:
        diagramma = result.get(campo) or dai_dati or dal_modello
        fonte = (result.get("_diagrammi_fonte") or {}).get(campo, "")
        if fonte == "dati":
            st.caption("Drawn from the validated tables — the model did not return this one.")
        elif fonte == "modello":
            st.caption("Written by the model.")

    if st.button("Redraw from the current tables",
                 help="Draws all four again from the rows as they are now, "
                      "including your corrections."):
        result["_diagrammi_dai_dati"] = diagrams.costruisci(result)
        for _c in diagrams.COSTRUTTORI:
            if result["_diagrammi_dai_dati"].get(_c):
                result[_c] = result["_diagrammi_dai_dati"][_c]
                (result.setdefault("_diagrammi_fonte", {}))[_c] = "dati"
        st.session_state["analysis_result"] = result
        ui.avviso_temporaneo("Diagrams redrawn")
        st.rerun()

    render_diagramma(scelto, diagramma, nomefile)

with tabs[6]:
    result["validation_questions"] = render_tabella("validation_questions", result, "vq_edit")
    st.divider()
    result["assumptions"] = render_tabella("assumptions", result, "as_edit")

with tabs[7]:
    ui.sezione("What the parser found",
               "Produced by sqlglot and pattern matching, with no model involved. "
               "These are facts: if a row here disagrees with a table, the table is wrong.")
    ui.cifre([
        {"valore": f"{len(metadata.get('components', []))}", "voce": "Components"},
        {"valore": f"{len(metadata.get('dependencies', []))}", "voce": "Dependencies"},
        {"valore": f"{len(metadata.get('detected_tables', []))}", "voce": "SQL objects"},
        {"valore": f"{len(metadata.get('local_risks', []))}", "voce": "Risk patterns"},
    ])
    with st.expander("Full parser output (JSON)"):
        st.json(metadata, expanded=False)

# Le correzioni fatte nelle tabelle rientrano nello stato prima dell'export,
# altrimenti si scaricherebbe la versione di prima delle correzioni.
st.session_state["analysis_result"] = result

with tabs[8]:
    ui.sezione("Export", "The tables as they are now, including your corrections.")
    locale_ok, locale_dettaglio = mermaid_render.disponibile()
    if locale_ok:
        ui.nota(f"Diagrams are drawn on this machine — nothing leaves it ({locale_dettaglio}).")
    elif os.environ.get("MERMAID_LOCAL_ONLY") == "1":
        st.warning("Local diagram rendering is unavailable and the external service is off: "
                   f"the documents will carry the diagram source instead of the picture. ({locale_dettaglio})")
    else:
        st.warning("Local diagram rendering is unavailable, so diagram code will be sent to the "
                   f"public mermaid.ink service. ({locale_dettaglio}) Install it with "
                   "`npm install -g @mermaid-js/mermaid-cli`, or set MERMAID_LOCAL_ONLY=1 "
                   "to forbid the call.")

    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    metadata_payload = json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str)
    col_pdf, col_docx, col_json = st.columns(3)

    with col_pdf:
        with ui.riquadro():
            st.markdown("**PDF report**")
            st.caption("Landscape, with the diagrams drawn in. For sharing and signing.")
            if st.button("Build PDF", key="fai_pdf", **ui.LARGA):
                with st.spinner("Drawing diagrams and laying out the PDF…"):
                    st.session_state["pdf_bytes"] = build_pdf(
                        payload, metadata_payload,
                        st.session_state.get("analysis_provider", "AI Provider"),
                        st.session_state.get("analysis_model", "Default Model"))
            if st.session_state.get("pdf_bytes"):
                st.download_button("Download PDF", data=st.session_state["pdf_bytes"],
                                   file_name="Legacy_Application_Documentation.pdf",
                                   mime="application/pdf", **ui.LARGA)

    with col_docx:
        with ui.riquadro():
            st.markdown("**Word document**")
            st.caption("The same content, editable. For teams that keep working on it.")
            if st.button("Build Word", key="fai_docx", **ui.LARGA):
                with st.spinner("Laying out the Word document…"):
                    st.session_state["docx_bytes"] = build_docx(
                        payload, metadata_payload,
                        st.session_state.get("analysis_provider", "AI Provider"),
                        st.session_state.get("analysis_model", "Default Model"))
            if st.session_state.get("docx_bytes"):
                st.download_button(
                    "Download Word", data=st.session_state["docx_bytes"],
                    file_name="Legacy_Application_Documentation.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    **ui.LARGA)

    with col_json:
        with ui.riquadro():
            st.markdown("**Raw data**")
            st.caption("Every row and every field, for whatever comes next.")
            st.download_button(
                "Download JSON",
                data=json.dumps(result, indent=2, ensure_ascii=False, default=str).encode("utf-8"),
                file_name="Legacy_Application_Analysis.json",
                mime="application/json", **ui.LARGA)
