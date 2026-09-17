__version__ = "2026.09.16b"

import ast
import builtins
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import subprocess
import sys
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
from exporter import __version__ as exporter_versione
from exporter import generate_docx_report, generate_pdf_report
from model_chain import __version__ as model_chain_versione
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
ui.imposta_tema_streamlit()   # prima di tutto: può far ripartire l'esecuzione
ui.applica_tema()

# =============================================================================
# I FILE SONO TUTTI DELLA STESSA VERSIONE?
# È successo: `app.py` nuovo copiato nel repository, `mermaid_render.py`
# rimasto vecchio, e l'app morta con un «AttributeError» redatto dal servizio
# che non nomina nemmeno il file. Ogni modulo porta la sua versione; qui si
# confrontano PRIMA di fare qualunque altra cosa, e se non coincidono lo si
# dice con i nomi dei file da aggiornare — che è l'unica informazione utile.
# =============================================================================
def _versioni_allineate():
    moduli = {"model_chain": model_chain_versione, "contract": contract.__version__,
              "diagrams": diagrams.__version__, "mermaid_render": mermaid_render.__version__,
              "exporter": exporter_versione, "ui": ui.__version__}
    vecchi = [f"{nome}.py ({v})" for nome, v in moduli.items() if v != __version__]
    if vecchi:
        st.error(f"The files of this application are from different versions. app.py is "
                 f"{__version__}; these are not: {', '.join(vecchi)}. Update the whole "
                 "folder from the same package — never single files — then restart the app.")
        st.stop()


_versioni_allineate()

# =============================================================================
# 2. CONSTANTS
# =============================================================================
# Estensione → linguaggio. Serve a DIRE al modello cosa sta leggendo e a
# scegliere il parser giusto; NON serve a rifiutare file. Un estrattore per il
# legacy non può sapere in anticipo cosa gli arriverà — il primo .vb caricato
# da un collega veniva respinto dal caricatore, e non c'era niente di rotto
# nell'analisi, solo un elenco troppo corto. Ora qualunque file di testo entra;
# se l'estensione non è qui, il linguaggio è «Unknown» e il modello la
# riconoscerà dal contenuto, che è quello che sa fare meglio.
LINGUAGGI = {
    # SQL e dialetti procedurali
    ".sql": "SQL", ".pks": "Oracle PL/SQL Package Specification",
    ".pkb": "Oracle PL/SQL Package Body", ".pls": "Oracle PL/SQL", ".plsql": "Oracle PL/SQL",
    ".prc": "Oracle PL/SQL Procedure", ".fnc": "Oracle PL/SQL Function",
    ".trg": "Oracle PL/SQL Trigger", ".pck": "Oracle PL/SQL Package",
    ".spc": "Oracle PL/SQL Package Specification", ".bdy": "Oracle PL/SQL Package Body",
    ".vw": "SQL View", ".tps": "Oracle Type Specification", ".tpb": "Oracle Type Body",
    ".tsql": "Transact-SQL", ".psql": "PostgreSQL", ".ddl": "SQL DDL",
    # Visual Basic, in tutte le sue vite
    ".vb": "VB.NET", ".bas": "Visual Basic 6 Module", ".frm": "Visual Basic 6 Form",
    ".cls": "Visual Basic 6 Class", ".ctl": "Visual Basic 6 Control",
    ".vbs": "VBScript", ".asp": "Classic ASP", ".aspx": "ASP.NET Page", ".ascx": "ASP.NET Control",
    # Mainframe e IBM i
    ".cbl": "COBOL", ".cob": "COBOL", ".cpy": "COBOL Copybook", ".jcl": "JCL",
    ".pli": "PL/I", ".pl1": "PL/I", ".asm": "Assembler",
    ".rpg": "RPG", ".rpgle": "RPGLE", ".sqlrpgle": "RPGLE with embedded SQL",
    ".cl": "IBM i Control Language", ".clle": "IBM i Control Language", ".clp": "IBM i Control Language",
    ".dds": "IBM i DDS", ".pf": "IBM i Physical File (DDS)", ".lf": "IBM i Logical File (DDS)",
    ".dspf": "IBM i Display File (DDS)", ".prtf": "IBM i Printer File (DDS)",
    # linguaggi generali
    ".java": "Java", ".kt": "Kotlin", ".scala": "Scala", ".groovy": "Groovy",
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".jsx": "JavaScript (React)",
    ".tsx": "TypeScript (React)", ".cs": "C#", ".c": "C", ".cpp": "C++", ".cc": "C++",
    ".h": "C/C++ Header", ".hpp": "C++ Header", ".go": "Go", ".rs": "Rust",
    ".php": "PHP", ".rb": "Ruby", ".pl": "Perl", ".pm": "Perl Module",
    ".pas": "Pascal/Delphi", ".dpr": "Delphi Project", ".dfm": "Delphi Form",
    ".abap": "ABAP", ".4gl": "Informix 4GL", ".p": "Progress ABL", ".w": "Progress ABL Window",
    ".i": "Progress ABL Include", ".sru": "PowerBuilder Object", ".srw": "PowerBuilder Window",
    ".srd": "PowerBuilder DataWindow",
    # script e configurazione
    ".sh": "Shell", ".ksh": "Korn Shell", ".bash": "Bash", ".bat": "Windows Batch",
    ".cmd": "Windows Batch", ".ps1": "PowerShell",
    ".xml": "XML", ".json": "JSON", ".yaml": "YAML", ".yml": "YAML",
    ".properties": "Properties", ".ini": "INI", ".cfg": "Configuration", ".conf": "Configuration",
    ".txt": "Text or Unknown",
}
# Ancora usata per il messaggio d'aiuto; il caricatore non filtra più.
SUPPORTED_EXTENSIONS = sorted(e.lstrip(".") for e in LINGUAGGI)

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
    estensione = Path(filename).suffix.lower()
    if estensione in LINGUAGGI:
        return LINGUAGGI[estensione]
    # Non si rifiuta e non si finge: si scrive che non si sa. Il modello vede
    # il contenuto e capisce da solo — è la cosa che gli riesce meglio.
    return f"Unknown ({estensione or 'no extension'})"


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
    # Il caricatore accetta tutto, quindi il controllo che sia TESTO sta qui:
    # un byte nullo nei primi 8 KB vuol dire un binario (.dll, .fmb, .pbl…),
    # e un binario decodificato a forza sarebbe spazzatura mandata al modello.
    if b"\x00" in raw_content[:8000]:
        raise ValueError(f"{uploaded_file.name} looks like a binary file, not source code. "
                         "Export the source as text first (for example .fmb → .fmt, .pbl → .sr*).")

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

def _gruppi_collegati(sources, metadata):
    """I file che si parlano fra loro, messi insieme.

    Il grafo delle dipendenze ce l'ha già il parser: si usa per capire quali
    file vanno letti insieme. Due file che si chiamano a vicenda finiti in
    lotti diversi non li vede insieme nessuno, e il loro collegamento resta un
    buco — al consolidamento arriva solo l'inventario, e da lì si può
    indovinare, non vedere."""
    nomi = [s["filename"] for s in sources]
    posizione = {n: i for i, n in enumerate(nomi)}
    padre = list(range(len(nomi)))

    def radice(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    def unisci(a, b):
        ra, rb = radice(a), radice(b)
        if ra != rb:
            padre[rb] = ra

    # dove è dichiarato ogni componente: serve per risalire dal bersaglio di
    # una chiamata al file che lo contiene
    dove = {}
    for componente in metadata.get("components", []):
        nome = str(componente.get("component_name", "")).strip().lower()
        file_dichiarante = componente.get("source_file")
        if nome and file_dichiarante in posizione:
            dove.setdefault(nome, file_dichiarante)
    base = {Path(n).stem.lower(): n for n in nomi}

    for dipendenza in metadata.get("dependencies", []):
        partenza = dipendenza.get("source")
        if partenza not in posizione:
            continue
        bersaglio = str(dipendenza.get("target", "")).strip().lower()
        corto = bersaglio.rsplit(".", 1)[-1]
        arrivo = (dove.get(bersaglio) or dove.get(corto)
                  or base.get(bersaglio) or base.get(corto))
        if arrivo and arrivo != partenza:
            unisci(posizione[partenza], posizione[arrivo])

    gruppi = {}
    for i, nome in enumerate(nomi):
        gruppi.setdefault(radice(i), []).append(sources[i])
    return list(gruppi.values())


def split_into_batches(sources, chars_per_batch=CHARS_PER_LOTTO, metadata=None):
    """L'analisi a lotti.

    Oltre una certa dimensione il modello troncherebbe la risposta a metà e
    l'analisi andrebbe persa senza che nessuno lo dica. Il sorgente si divide
    quindi in lotti che stanno in una chiamata, ogni lotto è un'analisi
    completa, e i risultati si uniscono sulle stesse chiavi con cui si tolgono
    i doppioni.

    Due regole nella divisione:
    · I file NON si spezzano mai a metà: un file tagliato dà regole di business
      monche, che è peggio di un file in meno.
    · I file che si chiamano fra loro stanno nello stesso lotto, quando ci
      stanno. Prima si divideva per sola dimensione, quindi due file legati
      finivano separati per puro ordine alfabetico e il loro legame non lo
      vedeva nessuno.
    """
    if metadata:
        gruppi = _gruppi_collegati(sources, metadata)
    else:
        gruppi = [[s] for s in sources]
    # i gruppi più grossi per primi: riempiono i lotti, i piccoli chiudono i buchi
    gruppi.sort(key=lambda g: -sum(len(s["content"]) for s in g))

    batches, corrente, quanti = [], [], 0
    for gruppo in gruppi:
        peso = sum(len(s["content"]) for s in gruppo)
        if peso > chars_per_batch:
            # Un gruppo più grande di un lotto va spezzato per forza: si chiude
            # quello che c'è e si dividono i suoi file per dimensione.
            if corrente:
                batches.append(corrente)
                corrente, quanti = [], 0
            interno, dentro = [], 0
            for file_singolo in sorted(gruppo, key=lambda x: -len(x["content"])):
                if interno and dentro + len(file_singolo["content"]) > chars_per_batch:
                    batches.append(interno)
                    interno, dentro = [], 0
                interno.append(file_singolo)
                dentro += len(file_singolo["content"])
            if interno:
                batches.append(interno)
            continue
        if corrente and quanti + peso > chars_per_batch:
            batches.append(corrente)
            corrente, quanti = [], 0
        corrente.extend(gruppo)
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
def _vale_per(lingua, famiglie):
    """Un pattern vale per un file se il linguaggio del file è in una delle
    famiglie indicate, oppure se il linguaggio è ignoto (allora si prova
    tutto, che è meglio di niente). `None` = vale sempre.

    Prima ogni pattern girava su ogni file: la stessa funzione VB usciva
    quattro volte con quattro etichette (FUNCTION, JAVA_METHOD,
    JAVASCRIPT_FUNCTION, VB_FUNCTION), e «End Function» seguito da «Public»
    fabbricava una funzione fantasma di nome Public."""
    if famiglie is None:
        return True
    basso = str(lingua or "").lower()
    if "unknown" in basso or "text" in basso:
        return True
    return any(f in basso for f in famiglie)


SQLISH = ("sql", "pl/", "oracle", "postgres", "transact")
VBISH = ("vb", "visual basic", "asp")
JAVAISH = ("java", "c#", "kotlin", "scala", "groovy")
JSISH = ("javascript", "typescript", "php")


def extract_functions_and_procedures(code, filename, language=""):
    # `[ \t]+` e non `\s+` dopo la parola chiave: `\s+` attraversa gli a capo,
    # e «End Function» seguito da una riga che comincia con «Public» diventava
    # una funzione chiamata Public.
    patterns = [
        ("PROCEDURE", r"\bPROCEDURE[ \t]+([A-Z_][A-Z0-9_$#.]*)", SQLISH + ("pascal", "delphi", "ada")),
        ("FUNCTION", r"\bFUNCTION[ \t]+([A-Z_][A-Z0-9_$#.]*)", SQLISH + ("pascal", "delphi", "ada")),
        ("PACKAGE", r"\bPACKAGE(?:[ \t]+BODY)?[ \t]+([A-Z_][A-Z0-9_$#.]*)", SQLISH),
        ("JAVA_METHOD", r"\b(?:public|private|protected)\s+(?:(?:static|final|synchronized|abstract|native)\s+)*[\w<>\[\],?]+(?:\s*\[\s*\])?\s+([A-Za-z_]\w*)\s*\(", JAVAISH),
        ("PYTHON_FUNCTION", r"(?m)^\s*def\s+([A-Za-z_]\w*)\s*\(", ("python",)),
        ("JAVASCRIPT_FUNCTION", r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", JSISH),
        ("COBOL_PARAGRAPH", r"(?m)^\s*([A-Z0-9][A-Z0-9-]+)\.\s*$", ("cobol",)),
        ("VB_PROCEDURE", r"(?m)^[ \t]*(?:(?:Public|Private|Friend|Protected|Shared|Overrides|Static)[ \t]+)*Sub[ \t]+([A-Za-z_]\w*)", VBISH),
        ("VB_FUNCTION", r"(?m)^[ \t]*(?:(?:Public|Private|Friend|Protected|Shared|Overrides|Static)[ \t]+)*Function[ \t]+([A-Za-z_]\w*)", VBISH),
        ("VB_PROPERTY", r"(?m)^[ \t]*(?:(?:Public|Private|Friend|Protected|Shared)[ \t]+)*Property[ \t]+(?:Get[ \t]+|Let[ \t]+|Set[ \t]+)?([A-Za-z_]\w*)", VBISH),
        ("VB_CLASS", r"(?m)^[ \t]*(?:(?:Public|Private|Friend|Partial)[ \t]+)*(?:Class|Module)[ \t]+([A-Za-z_]\w*)", VBISH),
        ("PERL_SUB", r"(?m)^\s*sub\s+([A-Za-z_]\w*)", ("perl",)),
        ("JCL_STEP", r"(?m)^//([A-Z0-9@#$]{1,8})\s+EXEC\s", ("jcl",)),
    ]
    components = []
    for component_type, pattern, famiglie in patterns:
        if not _vale_per(language, famiglie):
            continue
        # I pattern VB distinguono le maiuscole di proposito: `Sub`, `Function`
        # e `Property` in VB sono sempre così, e senza distinzione `function`
        # dentro un commento o una stringa diventerebbe un componente.
        flags = 0 if component_type.startswith("VB_") else re.IGNORECASE
        for match in re.findall(pattern, code, flags=flags)[:MAX_RIGHE_PER_TIPO]:
            components.append({
                "component_name": normalize_identifier(match),
                "component_type": component_type,
                "source_file": filename,
                "source": "STATIC_ANALYSIS",
                "confidence": "HIGH",
                "evidence": "Static source pattern"
            })
    return unique_dicts(components, ["component_name", "component_type", "source_file"])

def extract_imports_and_includes(code, filename, language=""):
    patterns = [
        ("PYTHON_IMPORT", r"(?m)^\s*import\s+([A-Za-z0-9_., ]+)", ("python",)),
        ("PYTHON_FROM_IMPORT", r"(?m)^\s*from\s+([A-Za-z0-9_.]+)\s+import", ("python",)),
        ("JAVA_IMPORT", r"(?m)^\s*import\s+([A-Za-z0-9_.]+)\s*;", JAVAISH),
        ("JAVASCRIPT_IMPORT", r"""from\s+["']([^"']+)["']""", JSISH),
        ("REQUIRE", r"""require\s*\(\s*["']([^"']+)["']\s*\)""", JSISH + ("ruby", "perl")),
        ("C_INCLUDE", r"""#include\s*[<"]([^>"]+)[>"]""", ("c", "c++", "header")),
        ("COBOL_COPY", r"\bCOPY\s+([A-Z0-9_-]+)", ("cobol",)),
        ("RPG_COPY", r"/COPY\s+([A-Z0-9_./-]+)", ("rpg",)),
        ("VB_IMPORTS", r"(?m)^\s*Imports\s+([A-Za-z_][\w.]*)", VBISH),
        ("VB_REFERENCE", r"(?m)^\s*Reference\s*=.*?#([^#\r\n]+)#", VBISH),
        ("PHP_INCLUDE", r"""\b(?:require|include)(?:_once)?\s*\(?\s*["']([^"']+)["']""", ("php",)),
        ("PASCAL_USES", r"(?im)^\s*uses\s+([A-Za-z_][\w., \r\n]*?);", ("pascal", "delphi")),
        ("JCL_EXEC_PGM", r"\bEXEC\s+PGM=([A-Z0-9@#$]{1,8})", ("jcl",)),
        ("JCL_EXEC_PROC", r"\bEXEC\s+(?:PROC=)?([A-Z0-9@#$]{1,8})(?:\s|,|$)", ("jcl",)),
    ]
    dependencies = []
    for dep_type, pattern, famiglie in patterns:
        if not _vale_per(language, famiglie):
            continue
        for match in re.findall(pattern, code, flags=re.IGNORECASE)[:MAX_RIGHE_PER_TIPO]:
            dependencies.append({
                "source": filename, "target": normalize_identifier(match),
                "dependency_type": dep_type, "evidence": "Static source pattern", "confidence": "HIGH"
            })
    return unique_dicts(dependencies, ["source", "target", "dependency_type"])

def extract_probable_calls(code, filename, components, generico=True, certi=None):
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
    ] + ([(r"\b([A-Za-z_][A-Za-z0-9_$.]*)\s*\(", "MEDIUM")] if generico else [])
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
            # Se l'albero sintattico ha visto quello stesso nome, non è più un
            # sospetto: è una chiamata, e la riga esce a confidenza alta senza
            # che nessuno debba controllarla a mano.
            if certi and basso.rsplit(".", 1)[-1] in certi:
                dependencies.append({
                    "source": filename, "target": norm_match, "dependency_type": "CALL",
                    "evidence": "Call pattern confirmed by the parser's syntax tree",
                    "confidence": "HIGH"})
            else:
                dependencies.append({
                    "source": filename, "target": norm_match, "dependency_type": "PROBABLE_CALL",
                    "evidence": "Static call-pattern detection", "confidence": confidence
                })
            trovati += 1
            if trovati >= MAX_RIGHE_PER_TIPO:
                break
    return unique_dicts(dependencies, ["source", "target", "dependency_type"])

def _nome_chiamato(nodo):
    """Il nome di ciò che viene chiamato: `f()` → f, `mod.f()` → mod.f."""
    if isinstance(nodo, ast.Name):
        return nodo.id
    if isinstance(nodo, ast.Attribute):
        base = _nome_chiamato(nodo.value)
        return f"{base}.{nodo.attr}" if base else nodo.attr
    return ""


_BUILTIN = {n.lower() for n in dir(builtins)}


def extract_calls_python(code, filename):
    """Le chiamate di un file Python, dall'albero sintattico.

    Torna `None` se il file non si lascia leggere: in quel caso chi chiama
    ricade sull'espressione regolare, che indovina ma non si arrende.

    Perché vale la pena: l'espressione regolare «identificatore seguito da
    parentesi» non distingue una chiamata da un cast, da un costruttore o da
    una parentesi qualsiasi, e produce righe a confidenza MEDIA che poi vanno
    tutte controllate a mano. L'albero sa che quello È un nodo Call: la riga
    esce a confidenza ALTA e nessuno deve verificarla."""
    try:
        albero = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        return None
    definiti = {n.name.lower() for n in ast.walk(albero)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    dipendenze = []
    for nodo in ast.walk(albero):
        if not isinstance(nodo, ast.Call):
            continue
        nome = normalize_identifier(_nome_chiamato(nodo.func))
        corto = nome.rsplit(".", 1)[-1].lower()
        if not nome or corto in definiti or corto in _BUILTIN or corto in LIBRERIE_NOTE:
            continue
        dipendenze.append({
            "source": filename, "target": nome, "dependency_type": "CALL",
            "evidence": f"Python AST, line {getattr(nodo, 'lineno', '?')}",
            "confidence": "HIGH"})
    return unique_dicts(dipendenze, ["source", "target", "dependency_type"])


def nomi_chiamati_sql(code):
    """I nomi che l'albero di sqlglot riconosce come chiamate a qualcosa di non
    standard — cioè, quasi sempre, procedure scritte in casa.

    Non si usa al posto dell'espressione regolare ma per CONFERMARLA. Su un
    package PL/SQL vero sqlglot non arriva in fondo: le parti che non capisce
    diventano un nodo `Command` e quello che c'è dentro sparisce dall'albero.
    Usarlo come unica fonte farebbe perdere chiamate che l'espressione regolare
    vedeva benissimo — un passo indietro travestito da passo avanti.

    Le funzioni di libreria (SUBSTR, NVL, TO_DATE) hanno un nodo proprio e
    restano fuori da sole, senza bisogno di elencarle."""
    nomi = set()
    for espressione in parse_sql_expressions(code):
        for chiamata in espressione.find_all(exp.Anonymous):
            nome = normalize_identifier(str(chiamata.this or "")).lower()
            if nome and nome not in LIBRERIE_NOTE and len(nome) >= 3:
                nomi.add(nome)
    return nomi


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

def extract_local_risks(code, filename, language=""):
    risks = []
    patterns = [
        {"type": "HARDCODED_CREDENTIAL", "pattern": r"(?i)\b(?:password|passwd|pwd|secret|api_key|apikey)\s*[:=]\s*[\"'][^\"']+[\"']", "sev": "CRITICAL", "desc": "Possible hard-coded credential."},
        {"type": "DYNAMIC_SQL", "pattern": r"\bEXECUTE\s+IMMEDIATE\b|\bsp_executesql\b|\bPREPARE\s+STATEMENT\b", "sev": "HIGH", "desc": "Dynamic SQL detected."},
        {"type": "GENERIC_EXCEPTION_HANDLER", "pattern": r"\bWHEN\s+OTHERS\b|\bcatch\s*\(\s*Exception\b|\bexcept\s+Exception\b", "sev": "MEDIUM", "desc": "Generic exception handling."},
        {"type": "EMPTY_EXCEPTION_HANDLER", "pattern": r"\bWHEN\s+OTHERS\s+THEN\s+NULL\b|\bexcept\s*:\s*pass\b", "sev": "HIGH", "desc": "Exception is potentially suppressed."},
        {"type": "DIRECT_COMMIT", "pattern": r"\bCOMMIT\s*;", "sev": "MEDIUM", "desc": "Explicit transaction commit."},
        {"type": "SELECT_ALL", "pattern": r"\bSELECT\s+\*\s+FROM\b", "sev": "LOW", "desc": "SELECT * creates unnecessary coupling."},
        # Visual Basic: gli errori ignorati e i salti
        {"type": "SUPPRESSED_ERRORS", "pattern": r"(?im)^\s*On\s+Error\s+Resume\s+Next\b", "sev": "HIGH", "desc": "On Error Resume Next: every error after this line is silently ignored.", "solo": VBISH},
        {"type": "GOTO", "pattern": r"(?im)^\s*GoTo\s+\w+", "sev": "LOW", "desc": "GoTo jump: control flow is hard to follow and to migrate.", "solo": VBISH + ("cobol", "basic", "fortran")},
        {"type": "LATE_BINDING", "pattern": r"(?i)\bCreateObject\s*\(", "sev": "MEDIUM", "desc": "CreateObject: a COM dependency resolved only at run time.", "solo": VBISH},
    ]
    for risk_def in patterns:
        if not _vale_per(language, risk_def.get("solo")):
            continue
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

def extract_data_operations_with_regex(code, filename, language=""):
    patterns = {
        "READ": [r"\bFROM\s+([A-Z0-9_$#.]+)", r"\bJOIN\s+([A-Z0-9_$#.]+)"],
        "CREATE": [r"\bINSERT\s+INTO\s+([A-Z0-9_$#.]+)"],
        "UPDATE": [r"\bUPDATE\s+([A-Z0-9_$#.]+)"],
        "DELETE": [r"\bDELETE\s+FROM\s+([A-Z0-9_$#.]+)"],
        "MERGE": [r"\bMERGE\s+INTO\s+([A-Z0-9_$#.]+)"],
        "DDL_CREATE": [r"\bCREATE\s+(?:TABLE|VIEW)\s+([A-Z0-9_$#.]+)"],
        # JCL: i dataset letti o scritti dagli step
        "DATASET": [r"\bDSN=([A-Z0-9@#$.()+-]+)"]
    }
    data_objects = []
    for operation, ops in patterns.items():
        if operation == "DATASET" and not _vale_per(language, ("jcl",)):
            continue
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
        # Si guardano tutte le chiamate, non solo i sospetti: una conferma
        # dell'albero sintattico dice che quella È una chiamata, non che il
        # bersaglio sia interessante. Sono due assi diversi, e prima la
        # conferma scavalcava il filtro del rumore — `System.out.println`
        # tornava dentro come chiamata certa.
        if d.get("dependency_type") not in ("PROBABLE_CALL", "CALL"):
            fuori.append(d)
            continue
        bersaglio = str(d.get("target", "")).strip().lower()
        corto = bersaglio.rsplit(".", 1)[-1]
        primo = bersaglio.split(".", 1)[0]
        if (bersaglio in LIBRERIE_NOTE or corto in LIBRERIE_NOTE
                # `System.out.println`: quello che conta è il primo pezzo, non
                # l'ultimo — è lì che sta il nome della libreria.
                or (primo in LIBRERIE_NOTE and primo != bersaglio) or len(corto) < 4):
            scartate += 1
            continue
        confermata = "tree" in str(d.get("evidence", "")) or "AST" in str(d.get("evidence", ""))
        if bersaglio in dichiarati or corto in dichiarati:
            d["dependency_type"] = "CALL"
            d["confidence"] = "HIGH"
            d["evidence"] = "Call resolved against a component declared in the codebase"
            risolte += 1
        elif confermata:
            # È una chiamata per certo, ma punta fuori dal codice caricato:
            # certa sul fatto, incerta su cosa ci sia dall'altra parte.
            d["dependency_type"] = "CALL"
            d["confidence"] = "MEDIUM"
            d["evidence"] = "Confirmed call, but the target is not in the submitted code"
            incerte += 1
        else:
            d["dependency_type"] = "PROBABLE_CALL"
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
    lingua_file = source["language"]
    components = extract_functions_and_procedures(code, filename, lingua_file)
    dependencies = extract_imports_and_includes(code, filename, lingua_file)
    # Prima si prova a leggere il file per davvero. Dove l'albero sintattico
    # c'è — Python con `ast`, SQL e PL/SQL con sqlglot — le chiamate sono nodi
    # dell'albero e non indovinelli: escono a confidenza ALTA e il pattern
    # generico non serve. Dove non c'è (Java, COBOL, RPG) si continua a
    # indovinare, marcando le righe per quello che sono.
    lingua = str(source["language"]).lower()
    if "python" in lingua:
        # `ast.parse` legge il file per intero o non legge niente: quando
        # riesce, l'elenco delle chiamate è completo e il pattern generico
        # aggiungerebbe solo rumore.
        da_albero = extract_calls_python(code, filename)
        if da_albero is not None:
            dependencies.extend(da_albero)
            dependencies.extend(extract_probable_calls(code, filename, components, generico=False))
        else:
            dependencies.extend(extract_probable_calls(code, filename, components))
    elif "sql" in lingua:
        # Qui l'albero è spesso parziale: serve a promuovere i sospetti che
        # conferma, non a sostituire la ricerca.
        dependencies.extend(extract_probable_calls(
            code, filename, components, certi=nomi_chiamati_sql(code)))
    else:
        dependencies.extend(extract_probable_calls(code, filename, components))
    sql_metadata = extract_sql_metadata(code, filename)
    data_objects = extract_data_operations_with_regex(code, filename, lingua_file)
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
        "local_risks": extract_local_risks(code, filename, lingua_file),
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
        preferito=model_name or "",
        preferenza=preferenza,
        ragionamento=ragionamento,
        lingua="en",
        log=diario.append,
    )

def ask_model(catena, prompt, provider, profondita="full"):
    """Una chiamata, con lo schema nativo dove il provider lo sa imporre."""
    schema = contract.schema_gemini(profondita) if provider == "Google Gemini" else None
    return catena.chiedi(
        prompt,
        sistema=contract.SISTEMA,
        json_mode=True,
        schema=schema,
        max_token=contract.PROFONDITA[profondita]["max_token"],
    )


# Quante volte si chiede al modello di proseguire da solo, prima di fermarsi
# e mostrare il bottone. Due bastano quasi sempre; se non bastano, è giusto
# che sia una persona a decidere se spendere ancora.
CONTINUAZIONI_AUTOMATICHE = 2


def stato_lotto(prompt, testo, modello, troncata, giri, sources, lotto, profondita, chiave=""):
    """Tutto quello che serve per riprendere un lotto: il prompt, il testo
    scritto finora, il modello che l'ha scritto, e se è finito.

    Vive nella sessione, NON nel risultato esportato: il prompt contiene il
    sorgente del cliente, e non deve finire in un JSON che gira per e-mail."""
    completo = contract.risposta_completa(testo, troncata)
    prof = contract.PROFONDITA[profondita]
    saltate = ([n for n in contract.CAMPI if n not in prof["sezioni"]]
               + [m for m in contract.CAMPI_MERMAID if m not in prof["mermaid"]])
    avvisi = []
    if not completo:
        avvisi.append(f"Batch {lotto[0]}/{lotto[1]}: the model stopped after {len(testo):,} "
                      "characters and the answer is incomplete. Continue with the same model "
                      "before validating these rows — they may change.")
    try:
        grezzo = contract.estrai_json(testo)
    except ValueError:
        grezzo = {}
    risultato = contract.normalizza(grezzo, avvisi, saltate=saltate)
    risultato["_modello"] = modello
    return {"prompt": prompt, "testo": testo, "modello": modello, "troncata": troncata,
            "giri": giri, "completo": completo, "file": [x["filename"] for x in sources],
            "lotto": lotto, "profondita": profondita, "chiave": chiave, "risultato": risultato}


def continua_lotto(catena, stato, ragionamento, modello=None):
    """Un giro di continuazione: dallo stesso punto, con lo stesso modello — o
    con quello indicato, se la persona ha deciso di passare al successivo
    perché il primo non risponde più. In quel caso lo si scrive nel
    risultato: chi legge deve sapere che la riga 40 e la riga 41 le hanno
    scritte due modelli diversi."""
    con = modello or stato["modello"]
    seguito = catena.continua(con, stato["prompt"], stato["testo"],
                              sistema=contract.SISTEMA, ragionamento=ragionamento,
                              max_token=contract.PROFONDITA[stato["profondita"]]["max_token"])
    testo = contract.unisci_continuazione(stato["testo"], seguito.testo)
    nuovo = stato_lotto(stato["prompt"], testo, con, seguito.troncata,
                        stato["giri"] + 1, [{"filename": f} for f in stato["file"]],
                        stato["lotto"], stato["profondita"], stato["chiave"])
    nuovo["cambi_modello"] = list(stato.get("cambi_modello") or [])
    if con != stato["modello"]:
        nuovo["cambi_modello"].append(f"{stato['modello']} → {con}")
    if nuovo["cambi_modello"]:
        avvisi = list(nuovo["risultato"].get("contract_warnings") or [])
        avvisi.append(f"Batch {stato['lotto'][0]}/{stato['lotto'][1]}: completed by a different "
                      f"model after the first stopped answering ({', '.join(nuovo['cambi_modello'])})")
        nuovo["risultato"]["contract_warnings"] = avvisi
    return nuovo


def analyze_batch(catena, provider, sources, metadata, lotto, profondita="full",
                  ragionamento="low", chiave=""):
    """Un lotto: la domanda, poi le continuazioni automatiche finché la
    risposta non è completa o non si è esaurita la pazienza automatica."""
    prompt = contract.prompt_analisi(sources, metadata_for_prompt(metadata, sources),
                                     lotto=lotto, profondita=profondita)
    risposta = ask_model(catena, prompt, provider, profondita)
    stato = stato_lotto(prompt, risposta.testo, risposta.modello, risposta.troncata, 0,
                        sources, lotto, profondita, chiave)
    while not stato["completo"] and stato["giri"] < CONTINUAZIONI_AUTOMATICHE:
        try:
            stato = continua_lotto(catena, stato, ragionamento)
        except NessunModello as e:
            # Il modello che scriveva non risponde più (quota finita, giù).
            # Non si fa cadere l'esecuzione — gli altri lotti sono buoni — e
            # non si cambia modello di nascosto: si consegna il lotto a metà,
            # con la causa, e sarà la persona a decidere cosa fare.
            stato["continuazione_fallita"] = e.causa
            avvisi = list(stato["risultato"].get("contract_warnings") or [])
            avvisi.append(f"Batch {lotto[0]}/{lotto[1]}: the model stopped answering while "
                          f"continuing ({e.causa}); the answer stays incomplete")
            stato["risultato"]["contract_warnings"] = avvisi
            break
    return stato


# =============================================================================
# LA CACHE DEI LOTTI — riconoscere il lavoro già fatto.
# Un lotto è identificato dai suoi file (le impronte), dal contratto e da come
# è stato chiesto (provider, preferenza, ragionamento, profondità). Stessa
# chiave, stessa risposta: si rilegge dal disco invece di ripagarla. Ci si
# guadagna quando si rilancia dopo aver aggiunto un file, quando si chiude e
# si riapre, quando due colleghi analizzano la stessa cosa sulla stessa
# macchina. La cartella è visibile e non è versionata.
# =============================================================================
CARTELLA_CACHE = Path(__file__).parent / "cache"


def chiave_lotto(lotto, provider, model_name, preferenza, ragionamento, profondita):
    parti = [contract.VERSIONE_CONTRATTO, provider, model_name or "", preferenza,
             ragionamento, profondita] + sorted(s["hash"] for s in lotto)
    return hashlib.sha256("|".join(parti).encode()).hexdigest()[:24]


def leggi_cache(chiave):
    try:
        return json.loads((CARTELLA_CACHE / f"{chiave}.json").read_text("utf-8"))
    except Exception:
        return None


def scrivi_cache(chiave, dati):
    try:
        CARTELLA_CACHE.mkdir(exist_ok=True)
        tmp = CARTELLA_CACHE / f"{chiave}.tmp"
        tmp.write_text(json.dumps(dati, ensure_ascii=False, default=str), "utf-8")
        tmp.replace(CARTELLA_CACHE / f"{chiave}.json")
    except Exception:
        pass  # la cache è un lusso: se non si scrive, si ripaga la prossima volta


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

def carica_analisi_salvata(grezzo_bytes):
    """Riporta in vita un JSON esportato, anche di una versione precedente.

    Passa dal contratto come una risposta del modello: i campi mancanti si
    riempiono, gli enum si raddrizzano, le domande scritte come stringhe (v1)
    diventano righe, il campo `steps` assente (v2.0) resta vuoto. Le spunte
    dell'esperto sopravvivono perché `sme_approved` viene conservato riga per
    riga. Le chiavi di servizio (`_…`) si riportano a mano, perché il contratto
    le ignora di proposito."""
    dati = json.loads(grezzo_bytes.decode("utf-8-sig"))
    if not isinstance(dati, dict):
        raise ValueError("not a JSON object")
    if not any(k in dati for k in contract.CAMPI):
        raise ValueError("none of the contract sections is present")
    metadati = dati.get("_metadata") or {}
    risultato = contract.normalizza(dati)
    for chiave in ("_modello", "_provider", "_lotti", "_ragionamento", "_durata_s",
                   "_diagrammi_dal_modello", "_diagrammi_dai_dati", "_diagrammi_fonte"):
        if chiave in dati:
            risultato[chiave] = dati[chiave]
    risultato.setdefault("_lotti", 1)
    if dati.get("_incompleti"):
        # Da un file non si può continuare: il prompt e il testo a metà stanno
        # nella sessione, non nel JSON. Lo si dice, e si sblocca l'avvio.
        avvisi = list(risultato.get("contract_warnings") or [])
        avvisi.append("this analysis was saved while incomplete; it cannot be continued "
                      "from a file — run it again")
        risultato["contract_warnings"] = avvisi
        risultato["_incompleti"] = []
    # I diagrammi si ricostruiscono dai dati se il file non li portava: un
    # JSON vecchio ne ha al massimo quelli del modello.
    return diagrams.arricchisci(risultato), metadati


def analysis_signature(sources, provider, model_name, preferenza, profondita="full"):
    """L'impronta dell'analisi: stessi file, stesso provider, stesso contratto
    ⇒ stessa risposta. Serve a non ripagare (e non riaspettare) tre minuti di
    modello ogni volta che Streamlit ricarica la pagina."""
    parti = [contract.VERSIONE_CONTRATTO, provider, model_name or "", preferenza, profondita]
    parti += sorted(s["hash"] for s in sources)
    return hashlib.sha256("|".join(parti).encode()).hexdigest()[:16]

def analyze_legacy_application(sources, metadata, provider, api_key, model_name,
                               azure_endpoint=None, preferenza="qualita", progress=None,
                               ragionamento="low", profondita="full", parallelismo=1,
                               usa_cache=True):
    """Torna (risultato composto, stati dei lotti). Gli stati servono a
    continuare i lotti incompleti con lo stesso modello."""
    diario = []
    partenza = time.time()
    catena = build_chain(provider, api_key, azure_endpoint, model_name, preferenza, diario,
                         ragionamento)
    lotti = split_into_batches(sources, metadata=metadata)
    if len(lotti) > MAX_LOTTI:
        raise ValueError(
            f"The codebase would need {len(lotti)} batches (limit {MAX_LOTTI}). "
            "Analyse it in separate runs, by subsystem."
        )
    n = len(lotti)
    stati = [None] * n
    da_fare, riusati, completati = [], 0, 0
    for i, lotto in enumerate(lotti):
        chiave = chiave_lotto(lotto, provider, model_name, preferenza, ragionamento, profondita)
        salvato = leggi_cache(chiave) if usa_cache else None
        if salvato is not None:
            stati[i] = {"completo": True, "dalla_cache": True, "risultato": salvato,
                        "file": [x["filename"] for x in lotto], "lotto": (i + 1, n),
                        "profondita": profondita, "chiave": chiave, "giri": 0}
            riusati += 1
            completati += 1
            if progress:
                progress(completati, n, [x["filename"] for x in lotto], riusato=True)
        else:
            da_fare.append((i, lotto, chiave))

    if da_fare:
        # La prova di contatto si fa UNA volta, prima di aprire i thread: così
        # i lotti in parallelo partono tutti dal modello che ha risposto invece
        # di rifare la prova ciascuno per conto suo.
        catena.chiedi("ping", solo_prova=True)
        # I lotti in parallelo: la chiamata al modello è attesa di rete, e
        # tenerne una sola in volo alla volta è tempo buttato. Il tetto lo
        # sceglie l'utente perché è la sua quota che si consuma più in fretta.
        with ThreadPoolExecutor(max_workers=max(1, min(parallelismo, len(da_fare)))) as pool:
            futuri = {pool.submit(analyze_batch, catena, provider, lotto, metadata, (i + 1, n),
                                  profondita, ragionamento, chiave): (i, lotto, chiave)
                      for i, lotto, chiave in da_fare}
            for futuro in as_completed(futuri):
                i, lotto, chiave = futuri[futuro]
                stati[i] = futuro.result()   # un guasto qui risale a chi chiama
                if usa_cache and stati[i]["completo"]:
                    scrivi_cache(chiave, stati[i]["risultato"])
                completati += 1
                if progress:   # sempre dal thread principale: Streamlit lo pretende
                    progress(completati, n, [x["filename"] for x in lotto])

    risultato = componi_risultato(stati, metadata, catena, provider, lotti, profondita,
                                  ragionamento, riusati, diario, partenza)
    return risultato, stati


def componi_risultato(stati, metadata, catena, provider, lotti, profondita, ragionamento,
                      riusati, diario, partenza):
    """Dai lotti al risultato unico. Separata dall'analisi perché si rifà
    anche dopo una continuazione, quando un lotto passa da incompleto a
    completo."""
    risultati = [s["risultato"] for s in stati]
    unito = contract.unisci(risultati)
    unito["_modello"] = next((s.get("modello") or s["risultato"].get("_modello", "")
                              for s in reversed(stati)), "")
    unito["_diario"] = diario
    unito["_lotti"] = len(lotti)
    unito["_riusati"] = riusati
    unito["_profondita"] = profondita
    unito["_ragionamento"] = ragionamento
    unito["_durata_s"] = round(time.time() - partenza)
    unito["_incompleti"] = [i + 1 for i, s in enumerate(stati) if not s["completo"]]
    completo = merge_static_and_ai_results(unito, metadata)
    if len(lotti) > 1 and not completo["_incompleti"]:
        # Il consolidamento vuole tutti i lotti finiti: lavora sull'inventario,
        # e un inventario a metà produce collegamenti a metà.
        completo = consolida(catena, provider, completo, lotti)
        completo = diagrams.arricchisci(completo)
        completo["_durata_s"] = round(time.time() - partenza)
    elif completo["_incompleti"]:
        avvisi = list(completo.get("contract_warnings") or [])
        avvisi.append("consolidation postponed: not all batches are complete yet")
        completo["contract_warnings"] = avvisi
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
    "steps": "Steps, in order",
}
# I campi che contengono prosa: vogliono spazio, gli altri no.
LARGHI = {"steps", "description", "evidence", "condition", "action", "impact", "recommendation",
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
    # Tutto il testo delle righe scritte dal modello, per chiedersi quanto di
    # quello che il parser ha trovato è stato poi DESCRITTO da qualche parte.
    # Non è completezza — quella non la sa nessuno — ma è una domanda vera con
    # una risposta vera, perché i fatti del parser sono verità nota.
    testo_righe = []
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
            if nome != "components":
                testo_righe.append(" ".join(str(v) for v in r.values()).lower())
    tutto_il_testo = " ".join(testo_righe)

    componenti_parser = {str(c.get("component_name", "")).strip()
                         for c in metadata.get("components", [])} - {""}
    componenti_descritti = {c for c in componenti_parser if c.lower() in tutto_il_testo}
    tabelle_parser = {str(t).strip() for t in metadata.get("detected_tables", [])} - {""}
    tabelle_descritte = {t for t in tabelle_parser if t.lower() in tutto_il_testo}

    # Il segnale più forte che l'applicazione sa dare su sé stessa: un file
    # pieno di IF e CASE da cui non è uscita nessuna regola di business è
    # quasi sempre un file che il modello ha saltato.
    con_regole = {str(r.get("source_file", "")).strip()
                  for r in result.get("business_rules", []) or []}
    muti = sorted(f.get("filename") for f in metadata.get("files", [])
                  if f.get("has_conditionals") and f.get("filename") not in con_regole)

    def pct(parte, tutto):
        return round(parte / tutto * 100) if tutto else 0

    return {"sezioni": sezioni, "sezioni_pct": pct(sum(sezioni.values()), len(sezioni)),
            "componenti_parser": len(componenti_parser),
            "componenti_descritti": len(componenti_descritti),
            "componenti_pct": pct(len(componenti_descritti), len(componenti_parser)),
            "tabelle_parser": len(tabelle_parser),
            "tabelle_pct": pct(len(tabelle_descritte), len(tabelle_parser)),
            "file_muti": muti,
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


def scopri_modelli(provider, api_key, azure_endpoint, preferenza):
    """I modelli che questa chiave può usare davvero, dal più nuovo in giù.

    Si chiede al provider una volta per chiave (la catena tiene l'elenco in
    memoria per sei ore); il menù si riempie da solo, e chi sceglie sceglie fra
    cose che esistono."""
    if not api_key:
        return [], "no key"
    impronta = hashlib.sha256(
        f"{provider}|{api_key}|{azure_endpoint}|{preferenza}".encode()).hexdigest()[:16]
    ricordo = st.session_state.get("modelli_scoperti") or {}
    if ricordo.get("impronta") == impronta:
        return ricordo["lista"], ricordo["fonte"]
    try:
        esito = build_chain(provider, api_key, azure_endpoint, "", preferenza, []).catena()
        lista, fonte = esito["lista"], esito["fonte"]
    except Exception as e:  # noqa: BLE001
        lista, fonte = [], f"discovery failed: {e}"
    st.session_state["modelli_scoperti"] = {"impronta": impronta, "lista": lista, "fonte": fonte}
    return lista, fonte


# =============================================================================
# 9. LA BARRA LATERALE — tre tappe, in ordine.
# I numeri ci stanno perché questa È una sequenza: senza chiave non si analizza,
# senza sorgenti non si esporta. Fuori da una sequenza vera, numerare è
# decorazione.
# =============================================================================
# ── 1 · IL MODELLO ────────────────────────────────────────────────────────
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
    _predefinito = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
elif provider == "Anthropic Claude":
    api_key = st.sidebar.text_input("API key", type="password",
                                    value=os.environ.get("ANTHROPIC_API_KEY", ""))
    _predefinito = os.environ.get("ANTHROPIC_MODEL", "")
else:
    api_key = st.sidebar.text_input("API key", type="password",
                                    value=os.environ.get("GEMINI_API_KEY", ""))
    _predefinito = os.environ.get("GEMINI_MODEL", "")

# Il controllo della connessione è un bottone, non un pannello da aprire: è la
# prima cosa che si fa con una chiave nuova, e nasconderla dietro un clic in
# più non aveva senso. L'esito resta sotto finché non si rilancia.
if st.sidebar.button("Check the connection", disabled=not api_key, **ui.LARGA,
                     help="Sends a two-word question to each model in turn and reports the "
                          "first that answers. Also refreshes the model list."):
    diario = []
    catena = build_chain(provider, api_key, azure_endpoint, "", "qualita", diario)
    t0 = time.time()
    try:
        with st.spinner("Asking each model in turn…"):
            r = catena.chiedi("ping", solo_prova=True, forza_elenco=True)
        esito_prova = ("ok", f"{r.modello} answered in {int((time.time()-t0)*1000)} ms")
    except NessunModello as e:
        esito_prova = ("ko", catena.messaggio_nessuno(e) + f"  (cause: {e.causa})")
    st.session_state["esito_prova"] = esito_prova
    st.session_state["diario_prova"] = diario
    st.session_state.pop("modelli_scoperti", None)   # l'elenco è appena stato rifatto

if st.session_state.get("esito_prova"):
    _stato, _testo = st.session_state["esito_prova"]
    (st.sidebar.success if _stato == "ok" else st.sidebar.error)(_testo)
    with st.sidebar.expander("What it tried"):
        st.code("\n".join(st.session_state.get("diario_prova") or []) or "no log",
                language="text")

# ── 2 · IL SORGENTE ───────────────────────────────────────────────────────
ui.tappa("2", "Source code")
caricati = st.sidebar.file_uploader(
    "Files", type=None, accept_multiple_files=True,
    help="Any text file: PL/SQL, COBOL and copybooks, JCL, RPG and DDS, Visual Basic, Java, "
         "C#, Python, PHP, Delphi, ABAP, shell scripts and more. Extensions the app does not "
         "know are still analysed. Drop a JSON exported from this app here to resume a saved "
         "analysis instead. Binary files are refused. Up to 2 MB per file.")
with st.sidebar.expander("Or paste a snippet"):
    pasted_filename = st.text_input("File name", value="pasted_source.sql")
    pasted_code = st.text_area("Source", height=180,
                               placeholder="Paste code here to analyse it without uploading a file.")

# Un'analisi salvata si riconosce da sola: è un JSON con dentro le sezioni del
# contratto. Prima serviva un pannello a parte, e chi non lo trovava rifaceva
# l'analisi da capo. Qui si guarda cosa contiene il file, non come si chiama.
uploaded_files, analisi_caricate = [], []
for _f in caricati or []:
    if _f.name.lower().endswith(".json"):
        try:
            analisi_caricate.append((_f, carica_analisi_salvata(_f.getvalue())))
            continue
        except Exception:
            pass   # un JSON qualunque resta un file da analizzare
    uploaded_files.append(_f)

if analisi_caricate:
    _f, (_ris, _meta) = analisi_caricate[0]
    _impronta = hashlib.sha256(_f.getvalue()).hexdigest()[:16]
    if st.session_state.get("json_caricato") != _impronta:
        st.session_state.update({
            "analysis_result": _ris, "analysis_metadata": _meta, "analysis_sources": [],
            "analysis_provider": _ris.get("_provider", "saved file"),
            "analysis_model": _ris.get("_modello", "saved file"),
            "analysis_signature": "json:" + _impronta, "json_caricato": _impronta})
        st.session_state.pop("pdf_bytes", None)
        st.session_state.pop("docx_bytes", None)
        st.session_state.pop("lotti_stato", None)
    st.sidebar.success(f"Resumed from {_f.name}: "
                       f"{len(_ris.get('business_rules', []))} business rules, "
                       f"contract v{_ris.get('contract_version', '?')}.")

# ── 3 · L'AVVIO ───────────────────────────────────────────────────────────
ui.tappa("3", "Run")
_incompleto = bool((st.session_state.get("analysis_result") or {}).get("_incompleti"))
run_analysis = st.sidebar.button(
    "Analyse the application", type="primary", disabled=_incompleto, **ui.LARGA,
    help=("The previous answer is not complete yet: use «Continue with the same model» "
          "on the page, or clear the results." if _incompleto else None))
if st.sidebar.button("Clear results", **ui.LARGA):
    for key in ["analysis_result", "analysis_metadata", "analysis_sources",
                "analysis_provider", "analysis_model", "analysis_signature",
                "pdf_bytes", "docx_bytes", "lotti_stato", "json_caricato",
                "continua_fallita"]:
        st.session_state.pop(key, None)
    st.rerun()

# ── IMPOSTAZIONI DA ESPERTO ───────────────────────────────────────────────
# Tutto quello che NON si tocca a ogni esecuzione sta qui dentro: i valori
# predefiniti vanno bene nella maggior parte dei casi, e una barra laterale con
# dieci controlli fa credere che vadano decisi tutti.
with st.sidebar.expander("Expert settings"):
    preferenza = "qualita" if st.radio(
        "Pick models by", ["Quality", "Speed and cost"], index=0, horizontal=True,
        help="Quality starts from the strongest models and falls back downwards. "
             "Speed keeps only the fast ones."
    ) == "Quality" else "velocita"

    _modelli, _fonte = scopri_modelli(provider, api_key, azure_endpoint, preferenza)
    _da_rete = _fonte.startswith("rete") or _fonte.startswith("discovery")
    AUTOMATICO = "Automatic (the chain decides)"
    if provider == "Microsoft Azure OpenAI" and (_da_rete or not _modelli):
        # Su Azure l'elenco dei deployment richiede un permesso che la chiave
        # può non avere. Se non si è potuto leggere, il nome si scrive a mano.
        model_name = st.text_input(
            "Deployment name", value=_predefinito or "gpt-4o",
            help="The deployments on this endpoint could not be listed, so type the name. "
                 "It stays first in the chain.")
    else:
        _opzioni = [AUTOMATICO] + _modelli
        _indice = _opzioni.index(_predefinito) if _predefinito in _opzioni else 0
        _scelto = st.selectbox(
            "Preferred model", _opzioni, index=_indice, disabled=not api_key,
            help=("Automatic: the chain starts from the best model found and falls back "
                  "downwards. Pick one to start from that model instead; if it does not "
                  "answer, the chain falls back to the others, best first." if _modelli else
                  "Enter the API key above and the models found on it appear here."))
        model_name = "" if _scelto == AUTOMATICO else _scelto
        if api_key and _modelli:
            st.caption(f"{len(_modelli)} model{'s' if len(_modelli) != 1 else ''} found on "
                       f"this key ({_fonte}), newest first.")
        elif api_key:
            st.caption(f"No model list yet ({_fonte}). The chain falls back to the "
                       "built-in list.")

    RAGIONAMENTO = {"Fast": "minimal", "Balanced": "low", "Thorough": "medium", "Deep": "high"}
    ragionamento = RAGIONAMENTO[st.select_slider(
        "Thinking time", options=list(RAGIONAMENTO), value="Balanced",
        help="How much the model may think before answering. This is the biggest lever on "
             "how long a run takes. If a model refuses the level you pick, the app moves up "
             "one step for that model and carries on.")]

    profondita = "quick" if st.radio(
        "Depth", ["Full", "Quick"], index=0, horizontal=True,
        help="Quick asks for the sections that pay for the run and caps the answer at less "
             "than half the size: roughly half the time. Impact analysis, application map "
             "and assumptions stay empty; diagrams are drawn from the tables anyway."
    ) == "Quick" else "full"

    parallelismo = int(st.select_slider(
        "Batches at once", options=[1, 2, 3, 4], value=2,
        help="How many batches are sent to the model at the same time. More is faster on big "
             "codebases, but eats your rate limit faster: on a free-tier key stay at 1 or 2."))

    force_rerun = st.checkbox(
        "Analyse again from scratch", value=False,
        help="Off: batches whose files, settings and contract have not changed are read back "
             "from the cache on disk instead of being paid for again.")

    st.divider()
    _disegna = mermaid_render.prova_locale()
    st.caption("Diagrams are drawn on this machine." if _disegna else
               "Diagrams are **not** drawn on this machine: their code would be sent to the "
               "public mermaid.ink service. Everything else works.")
    if st.button("Install what's missing", **ui.LARGA,
                 help="Runs the same setup as «python avvia.py»: Python packages and the "
                      "local diagram renderer, including the browser it needs. The first run "
                      "downloads a few hundred MB and takes a while."):
        with st.spinner("Installing… this can take a few minutes the first time."):
            try:
                esito = subprocess.run(
                    [sys.executable, str(Path(__file__).parent / "avvia.py"),
                     "--solo-preparazione"],
                    capture_output=True, text=True, timeout=1800,
                    cwd=str(Path(__file__).parent))
                uscita = (esito.stdout or "") + (esito.stderr or "")
            except subprocess.TimeoutExpired:
                uscita = "Timed out after 30 minutes."
            except Exception as e:  # noqa: BLE001
                uscita = f"Could not run the setup: {e}"
        st.code(uscita[-3000:] or "no output", language="text")
        st.caption("New Python packages only take effect after the app is restarted. "
                   "The diagram renderer works straight away.")

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
        firma = analysis_signature(sources, provider, model_name, preferenza, profondita)
        if not force_rerun and st.session_state.get("analysis_signature") == firma:
            st.info("Same files and same settings as the last run — showing that result. "
                    "Tick «Analyse again from scratch» to pay for a new one.")
        else:
            # Niente barra di avanzamento: non c'è niente da misurare. Il
            # tempo lo fa il modello mentre scrive, e quanto manchi non lo sa
            # nessuno — una barra che si riempie subito e poi sta ferma dice
            # una cosa falsa. Restano la rotella che gira, i secondi che
            # passano e il diario dei lotti finiti, che sono veri.
            lavoro = ui.lavoro_in_corso("Reading the code…")
            with lavoro:
                diario = st.empty()
            try:
                metadata = extract_technical_metadata(sources)
                inizio = time.time()
                righe_diario = []

                def avanza(fatti, n, nomi, riusato=False):
                    # Il tempo che passa e i lotti finiti si mostrano: un'analisi
                    # vera dura minuti, e una pagina ferma sembra bloccata — a
                    # quel punto la gente ricarica, e il lavoro fatto fin lì se
                    # ne va. Con i lotti in parallelo si conta ciò che è FINITO.
                    trascorsi = int(time.time() - inizio)
                    ui.passo(lavoro, f"Asking the model — {fatti} of {n} batches done · {trascorsi}s")
                    righe_diario.append(f"[{trascorsi:>4}s] {'from cache' if riusato else 'done'} "
                                        f"{fatti}/{n}: {', '.join(nomi)[:60]}")
                    diario.code("\n".join(righe_diario[-8:]), language="text")

                result, stati_lotti = analyze_legacy_application(
                    sources, metadata, provider, api_key, model_name,
                    azure_endpoint, preferenza, progress=avanza,
                    ragionamento=ragionamento, profondita=profondita,
                    parallelismo=parallelismo, usa_cache=not force_rerun)
                st.session_state["lotti_stato"] = stati_lotti
                ui.finito(lavoro, f"Analysed in {result.get('_durata_s', '?')}s "
                                  f"with {result.get('_modello', 'the model')}")
                st.session_state.update({
                    "analysis_result": result, "analysis_metadata": metadata,
                    "analysis_sources": sources, "analysis_provider": provider,
                    "analysis_model": result.get("_modello", model_name),
                    "analysis_signature": firma})
                st.session_state.pop("pdf_bytes", None)
                st.session_state.pop("docx_bytes", None)
                ui.avviso_temporaneo(f"Analysed in {result.get('_durata_s', '?')}s")
            except NessunModello as e:
                ui.finito(lavoro, "No model answered", riuscito=False)
                catena = build_chain(provider, api_key, azure_endpoint, model_name, preferenza, [],
                                     ragionamento)
                st.error(catena.messaggio_nessuno(e))
                with st.expander("What the app tried"):
                    st.code("\n".join(e.diario) or f"cause: {e.causa}", language="text")
            except Exception as e:
                ui.finito(lavoro, "The analysis stopped", riuscito=False)
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

if result.get("_incompleti"):
    stati_lotti = st.session_state.get("lotti_stato") or []
    quali = ", ".join(f"batch {i}" + (f" ({', '.join(stati_lotti[i-1]['file'])[:50]})"
                                       if i - 1 < len(stati_lotti) else "")
                      for i in result["_incompleti"])
    fermi = [s_ for s_ in stati_lotti if not s_.get("completo") and s_.get("continuazione_fallita")]
    causa_fermo = fermi[0]["continuazione_fallita"] if fermi else st.session_state.get("continua_fallita")

    def _ricomponi(catena_x, stati_x):
        lotti_nomi = [[{"filename": f} for f in s_["file"]] for s_ in stati_x]
        return componi_risultato(stati_x, metadata, catena_x, provider, lotti_nomi,
                                 result.get("_profondita", "full"), ragionamento,
                                 result.get("_riusati", 0), [],
                                 time.time() - result.get("_durata_s", 0))

    def _salva(res, stati_x):
        st.session_state["analysis_result"] = res
        st.session_state["lotti_stato"] = stati_x
        st.session_state.pop("pdf_bytes", None)
        st.session_state.pop("docx_bytes", None)
        st.session_state.pop("continua_fallita", None)

    with ui.riquadro():
        if causa_fermo:
            st.error(f"The answer is not complete ({quali}) and the model that was writing it "
                     f"has stopped answering: {causa_fermo}. Three ways out, your choice — "
                     "the app will not switch model on its own half-way through an answer.")
        else:
            st.warning(f"The answer is not complete: {quali}. The model stopped before the end "
                       "and the rows below may change. Continue with the same model, from the "
                       "point where it stopped — nothing already written is thrown away.")
        if not stati_lotti:
            st.caption("This analysis was loaded from a file: continuing is not possible, "
                       "only a new run is.")
        else:
            catena_c = build_chain(provider, api_key, azure_endpoint, model_name, preferenza,
                                   [], ragionamento)
            modello_fermo = fermi[0]["modello"] if fermi else next(
                (s_["modello"] for s_ in stati_lotti if not s_.get("completo") and "modello" in s_), "")
            prossimo = catena_c.successivo(modello_fermo) if (causa_fermo and modello_fermo) else None
            c1, c2, c3 = st.columns(3)

            # ── 1. lo stesso modello, dallo stesso punto ───────────────────
            if c1.button("Continue with the same model", type="primary" if not causa_fermo else "secondary",
                         key="continua", **ui.LARGA,
                         help="Asks the model that wrote the first part to pick up exactly where "
                              "it stopped."):
                try:
                    with st.spinner("Asking the model to pick up where it stopped…"):
                        for i, stato in enumerate(stati_lotti):
                            if stato.get("completo") or "prompt" not in stato:
                                continue
                            stati_lotti[i] = continua_lotto(catena_c, stato, ragionamento)
                            stati_lotti[i].pop("continuazione_fallita", None)
                            if stati_lotti[i]["completo"] and not force_rerun and stato.get("chiave"):
                                scrivi_cache(stato["chiave"], stati_lotti[i]["risultato"])
                    _salva(_ricomponi(catena_c, stati_lotti), stati_lotti)
                    ui.avviso_temporaneo("Answer completed" if not st.session_state["analysis_result"].get("_incompleti")
                                         else "Still incomplete — continue once more")
                    st.rerun()
                except NessunModello as e:
                    # Non si cambia modello da soli: si mostra la causa e si apre
                    # la seconda via, che è una decisione della persona.
                    st.session_state["continua_fallita"] = e.causa
                    st.rerun()

            # ── 2. il modello dopo, solo quando il primo non risponde più ───
            if prossimo:
                if c2.button(f"Continue with the next model ({prossimo})", type="primary",
                             key="continua_prossimo", **ui.LARGA,
                             help="Hands the rest of the answer to the next model in the chain. "
                                  "The rows written so far are kept; the document will say which "
                                  "batch was finished by a different model."):
                    try:
                        with st.spinner(f"Asking {prossimo} to finish the answer…"):
                            for i, stato in enumerate(stati_lotti):
                                if stato.get("completo") or "prompt" not in stato:
                                    continue
                                stati_lotti[i] = continua_lotto(catena_c, stato, ragionamento,
                                                                modello=prossimo)
                                stati_lotti[i].pop("continuazione_fallita", None)
                        _salva(_ricomponi(catena_c, stati_lotti), stati_lotti)
                        ui.avviso_temporaneo("Answer completed by " + prossimo)
                        st.rerun()
                    except NessunModello as e:
                        st.error(f"{prossimo} did not answer either: {catena_c.messaggio_nessuno(e)}")
            else:
                c2.caption("«Continue with the next model» appears if the model that was "
                           "writing stops answering.")

            # ── 3. tenersi quello che c'è, o buttare tutto ─────────────────
            if c3.button("Keep what was written", key="tieni", **ui.LARGA,
                         help="Accepts the incomplete batches as they are: the rows already "
                              "repaired stay, nothing more is asked. The document will say the "
                              "batch was cut short."):
                for i, stato in enumerate(stati_lotti):
                    if not stato.get("completo"):
                        stato["completo"] = True
                        stato["accettato_incompleto"] = True
                        avvisi = list(stato["risultato"].get("contract_warnings") or [])
                        avvisi.append(f"Batch {stato['lotto'][0]}/{stato['lotto'][1]}: accepted "
                                      "incomplete by the user; rows after the cut are missing")
                        stato["risultato"]["contract_warnings"] = avvisi
                _salva(_ricomponi(catena_c, stati_lotti), stati_lotti)
                st.rerun()
            if c3.button("Discard and start over", key="butta", **ui.LARGA,
                         help="Throws away this run — cache included for these batches — and "
                              "re-enables «Analyse the application»."):
                for key in ["analysis_result", "analysis_metadata", "analysis_sources",
                            "analysis_provider", "analysis_model", "analysis_signature",
                            "pdf_bytes", "docx_bytes", "lotti_stato", "continua_fallita"]:
                    st.session_state.pop(key, None)
                st.rerun()

q = quality_indicators(result, metadata)

ui.cifre([
    # `.get`: un'analisi ricaricata da un JSON vecchio non porta i metadati.
    {"valore": f"{metadata.get('file_count', '—')}", "voce": "Files read",
     "nota": f"{metadata.get('total_line_count', 0):,} lines"},
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
            {"valore": f"{q['componenti_pct']}%", "voce": "Components described",
             "nota": f"{q['componenti_descritti']} of the {q['componenti_parser']} "
                     "the parser declared"},
            {"valore": f"{q['tabelle_pct']}%", "voce": "SQL objects described",
             "nota": f"of {q['tabelle_parser']} found in the code"},
            {"valore": f"{q['evidenza_pct']}%", "voce": "Rows with evidence"},
            {"valore": f"{q['confidenza_alta_pct']}%", "voce": "High confidence"},
            {"valore": f"{q['dipendenze_non_risolte']}", "voce": "Unresolved calls",
             "nota": "target not declared in the code you sent"},
        ])
        if q["file_muti"]:
            st.warning("These files contain IF, CASE or WHEN but produced no business rule. "
                       "A file full of conditions with no rule out of it is usually a file "
                       "the model skipped — worth a second run on those alone: "
                       + ", ".join(q["file_muti"][:12])
                       + (" …" if len(q["file_muti"]) > 12 else ""))
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

    st.caption(("INCOMPLETE · " if result.get("_incompleti") else "")
               + f"Answered by {st.session_state.get('analysis_model', '?')} · "
               f"thinking: {result.get('_ragionamento', '?')} · "
               f"depth: {result.get('_profondita', 'full')} · "
               f"batches: {result.get('_lotti', 1)}"
               + (f" ({result.get('_riusati')} from cache)" if result.get('_riusati') else "") + " · "
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
            # Dentro ci vanno anche i metadati del parser e chi ha risposto:
            # è quello che serve per RIPRENDERE il lavoro da questo file, non
            # solo per leggerlo. Le chiavi di servizio cominciano con `_`.
            da_salvare = dict(result)
            da_salvare["_metadata"] = metadata
            da_salvare["_provider"] = st.session_state.get("analysis_provider", "")
            da_salvare["_modello"] = st.session_state.get("analysis_model", "")
            st.download_button(
                "Download JSON",
                data=json.dumps(da_salvare, indent=2, ensure_ascii=False, default=str).encode("utf-8"),
                file_name="Legacy_Application_Analysis.json",
                mime="application/json", **ui.LARGA,
                help="Everything, including your ticks. Load it again under step 2 to pick up "
                     "where you left off — the browser session alone does not remember it.")
