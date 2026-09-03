import os
import re
import json
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import sqlglot
from sqlglot import exp
from streamlit_mermaid import st_mermaid
from openai import OpenAI
from anthropic import Anthropic
from google import genai
from google.genai import types

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
MAX_TOTAL_SOURCE_CHARS = 180_000

RISK_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

DEFAULT_ANALYSIS_RESULT = {
    "executive_summary": "",
    "application_purpose": "",
    "business_processes": [],
    "business_rules": [],
    "components": [],
    "dependencies": [],
    "interfaces": [],
    "data_objects": [],
    "data_flows": [],
    "technical_risks": [],
    "impact_analysis": [],
    "application_mapping": [],
    "validation_questions": [],
    "assumptions": [],
    "mermaid_process_flow": "",
    "mermaid_application_map": "",
    "mermaid_data_flow": "",
    "mermaid_call_graph": "",
    "technical_notes": ""
}

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
        raise ValueError("The total submitted source code exceeds limit.")
    
    return sources

def serialize_sources_for_prompt(sources):
    sections = []
    fence = "`" * 3
    for index, source in enumerate(sources, start=1):
        sections.append(f"""SOURCE FILE {index}
Filename: {source["filename"]}
Detected language: {source["language"]}
Source hash: {source["hash"]}

{fence}text
{source["content"]}
{fence}
""")
    return "\n".join(sections)

# =============================================================================
# 5. SQL PARSING
# =============================================================================
def parse_sql_expressions(sql_text):
    candidate_dialects = [None, "oracle", "mysql", "postgres", "tsql"]
    for dialect in candidate_dialects:
        try:
            expressions = sqlglot.parse(sql_text, read=dialect, error_level="ignore") if dialect else sqlglot.parse(sql_text, error_level="ignore")
            valid_expressions = [exp for exp in expressions if exp is not None]
            if valid_expressions:
                return valid_expressions
        except Exception:
            continue
    return []

def extract_sql_metadata(code, filename):
    expressions = parse_sql_expressions(code)
    tables, columns, operations, relationships = [], [], [], []

    for expression in expressions:
        expression_tables = unique_strings([normalize_identifier(table.sql()) for table in expression.find_all(exp.Table)])
        expression_columns = unique_strings([normalize_identifier(col.sql()) for col in expression.find_all(exp.Column)])
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
        "operations": operations,
        "relationships": relationships
    }

# =============================================================================
# 6. STATIC SOURCE ANALYSIS
# =============================================================================
def extract_functions_and_procedures(code, filename):
    patterns = [
        ("PROCEDURE", r"\bPROCEDURE\s+([A-Z_][A-Z0-9_$#.]*)"),
        ("FUNCTION", r"\bFUNCTION\s+([A-Z_][A-Z0-9_$#.]*)"),
        ("PACKAGE", r"\bPACKAGE(?:\s+BODY)?\s+([A-Z_][A-Z0-9_$#.]*)"),
        ("JAVA_METHOD", r"\b(?:public|private|protected|static|final|synchronized|\s)+[\w<>\[\], ?]+\s+([A-Za-z_]\w*)\s*\("),
        ("PYTHON_FUNCTION", r"(?m)^\s*def\s+([A-Za-z_]\w*)\s*\("),
        ("JAVASCRIPT_FUNCTION", r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\("),
        ("COBOL_PARAGRAPH", r"(?m)^\s*([A-Z0-9][A-Z0-9-]+)\.\s*$")
    ]
    components = []
    for component_type, pattern in patterns:
        for match in re.findall(pattern, code, flags=re.IGNORECASE):
            components.append({
                "component_name": normalize_identifier(match),
                "component_type": component_type,
                "source_file": filename
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
        for match in re.findall(pattern, code, flags=re.IGNORECASE):
            dependencies.append({
                "source": filename, "target": normalize_identifier(match),
                "dependency_type": dep_type, "evidence": "Static source pattern", "confidence": "HIGH"
            })
    return unique_dicts(dependencies, ["source", "target", "dependency_type"])

def extract_probable_calls(code, filename, components):
    declarations = {comp.get("component_name", "").lower() for comp in components}
    excluded = {"if","for","while","switch","return","print","len","str","int","float","list","dict","set","tuple","select","insert","update","delete","merge","values","count","sum","min","max","coalesce","nvl","decode"}
    patterns = [
        r"\bCALL\s+([A-Z_][A-Z0-9_$#.]*)",
        r"\bEXEC(?:UTE)?\s+([A-Z_][A-Z0-9_$#.]*)",
        r"\bPERFORM\s+([A-Z0-9-]+)",
        r"\b([A-Za-z_][A-Za-z0-9_$.]*)\s*\("
    ]
    dependencies = []
    for pattern in patterns:
        for match in re.findall(pattern, code, flags=re.IGNORECASE):
            norm_match = normalize_identifier(match)
            if not norm_match.lower() or norm_match.lower() in excluded or norm_match.lower() in declarations:
                continue
            dependencies.append({
                "source": filename, "target": norm_match, "dependency_type": "PROBABLE_CALL",
                "evidence": "Static call-pattern detection", "confidence": "MEDIUM"
            })
    return unique_dicts(dependencies, ["source", "target", "dependency_type"])

def extract_interfaces(code, filename):
    interfaces = []
    for url in re.findall(r"""https?://[^\s"'<>]+""", code, flags=re.IGNORECASE):
        interfaces.append({
            "name": url, "interface_type": "HTTP_ENDPOINT", "direction": "UNKNOWN",
            "technology": "HTTP/HTTPS", "source_file": filename, "evidence": url, "confidence": "HIGH"
        })
    for file_ref in re.findall(r"""[^"']+\.(?:csv|txt|xml|json|dat|xlsx|xls|pdf)["']""", code, flags=re.IGNORECASE):
        interfaces.append({
            "name": file_ref.strip('\'"'), "interface_type": "FILE_INTERFACE", "direction": "UNKNOWN",
            "technology": Path(file_ref.strip('\'"')).suffix.upper().lstrip("."),
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
        for match in re.findall(pattern, code, flags=re.IGNORECASE):
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
        for match in re.finditer(risk_def["pattern"], code, flags=re.IGNORECASE | re.MULTILINE):
            line_num = code[:match.start()].count("\n") + 1
            risks.append({
                "risk_id": "", "risk_type": risk_def["type"], "severity": risk_def["sev"],
                "description": risk_def["desc"], "affected_component": filename,
                "evidence": match.group(0)[:200], "line_number": line_num,
                "impact": "", "recommendation": "", "confidence": "HIGH", "source": "STATIC_ANALYSIS"
            })
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
            for match in re.findall(pattern, code, flags=re.IGNORECASE):
                data_objects.append({
                    "object_name": normalize_identifier(match), "object_type": "DATABASE_OBJECT",
                    "operation": operation, "source_file": filename, "purpose": "",
                    "evidence": safe_text(match), "confidence": "HIGH"
                })
    return unique_dicts(data_objects, ["object_name", "operation", "source_file"])

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
        "sql_tables": sql_metadata["tables"], "sql_columns": sql_metadata["columns"],
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
    return {
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

# =============================================================================
# 7. JSON RESPONSE HANDLING
# =============================================================================
def extract_json_object(response_text):
    if not response_text: raise ValueError("Empty response.")
    # Sostituito il backtick letterale con la sintassi regex `{3}` per sicurezza
    clean_text = re.sub(r"^`{3}(?:json)?\s*", "", response_text.strip(), flags=re.IGNORECASE)
    clean_text = re.sub(r"\s*`{3}$", "", clean_text)
    try:
        return json.loads(clean_text)
    except json.JSONDecodeError:
        start_position, end_position = clean_text.find("{"), clean_text.rfind("}")
        if start_position == -1 or end_position == -1 or end_position <= start_position:
            raise ValueError("No valid JSON object found in response.")
        return json.loads(clean_text[start_position:end_position + 1])

def clean_mermaid_code(value):
    value = safe_text(value).strip()
    value = re.sub(r"^`{3}(?:mermaid)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*`{3}$", "", value)
    return value.replace("--&gt;", "-->").replace("&gt;", ">").strip()

def validate_analysis_result(result):
    validated = DEFAULT_ANALYSIS_RESULT.copy()
    if isinstance(result, dict): validated.update(result)
    for field in ["business_processes", "business_rules", "components", "dependencies", "interfaces", "data_objects", "data_flows", "technical_risks", "impact_analysis", "application_mapping", "validation_questions", "assumptions"]:
        if not isinstance(validated.get(field), list): validated[field] = []
    for field in ["executive_summary", "application_purpose", "technical_notes"]:
        validated[field] = safe_text(validated.get(field))
    for field in ["mermaid_process_flow", "mermaid_application_map", "mermaid_data_flow", "mermaid_call_graph"]:
        validated[field] = clean_mermaid_code(validated.get(field))
    return validated

def merge_static_and_ai_results(ai_result, metadata):
    result = validate_analysis_result(ai_result)
    result["components"] = unique_dicts(result["components"] + metadata.get("components", []), ["component_name", "component_type", "source_file"])
    result["dependencies"] = unique_dicts(result["dependencies"] + metadata.get("dependencies", []), ["source", "target", "dependency_type"])
    result["interfaces"] = unique_dicts(result["interfaces"] + metadata.get("interfaces", []), ["name", "interface_type", "source_file"])
    result["data_objects"] = unique_dicts(result["data_objects"] + metadata.get("data_objects", []), ["object_name", "operation", "source_file"])
    result["technical_risks"] = unique_dicts(result["technical_risks"] + metadata.get("local_risks", []), ["risk_type", "affected_component", "evidence"])
    for index, risk in enumerate(result["technical_risks"], start=1):
        if not risk.get("risk_id"): risk["risk_id"] = f"TR-{index:03d}"
    return result

# =============================================================================
# 8. PROMPT GENERATION
# =============================================================================
def build_analysis_prompt(sources, metadata):
    metadata_json = json.dumps(metadata, indent=2, ensure_ascii=False)
    source_text = serialize_sources_for_prompt(sources)
    return f"""You are a senior specialist in Legacy application reverse engineering.
Analyze the supplied codebase. Distinguish verified facts (STATIC) from AI inferences (LLM).

STATIC METADATA:
{metadata_json}

SOURCE CODE:
{source_text}

Return ONLY ONE valid JSON matching this structure exactly (No Markdown fences outside):
{{
  "executive_summary": "Concise summary",
  "application_purpose": "App purpose",
  "business_processes": [{{ "process_id": "BP-01", "process_name": "Name", "description": "Desc", "trigger": "Trig", "outcome": "Out", "involved_components": ["C1"], "confidence": "HIGH", "evidence": "file" }}],
  "business_rules": [{{ "rule_id": "BR-01", "rule_name": "Name", "condition": "Cond", "action": "Act", "business_impact": "Imp", "source_file": "File", "source_component": "Comp", "confidence": "HIGH", "evidence": "Ev" }}],
  "components": [],
  "dependencies": [],
  "interfaces": [],
  "data_objects": [],
  "data_flows": [],
  "technical_risks": [{{ "risk_id": "TR-01", "risk_type": "Type", "severity": "HIGH", "description": "Desc", "affected_component": "Comp", "impact": "Imp", "recommendation": "Rec", "confidence": "HIGH", "source": "LLM_ANALYSIS", "evidence": "Ev" }}],
  "impact_analysis": [],
  "application_mapping": [],
  "validation_questions": ["Q1"],
  "assumptions": ["A1"],
  "mermaid_process_flow": "graph TD\\n A-->B",
  "mermaid_application_map": "graph TD\\n A-->B",
  "mermaid_data_flow": "graph TD\\n A-->B",
  "mermaid_call_graph": "graph TD\\n A-->B",
  "technical_notes": "Notes"
}}
"""

# =============================================================================
# 9. AI PROVIDERS
# =============================================================================
def analyze_with_azure_openai(prompt, api_key, azure_endpoint, deployment_name):
    base_url = azure_endpoint.rstrip("/") + "/openai/v1/"
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=deployment_name,
        messages=[{"role": "system", "content": "Return only valid JSON."}, {"role": "user", "content": prompt}],
        temperature=0
    )
    return extract_json_object(response.choices[0].message.content)

def analyze_with_claude(prompt, api_key, model_name):
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model_name, max_tokens=8000, temperature=0,
        system="Return only valid JSON matching the schema.",
        messages=[{"role": "user", "content": prompt}]
    )
    return extract_json_object("".join(b.text for b in response.content if b.type == "text"))

def analyze_with_gemini(prompt, api_key, model_name):
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name, contents=prompt,
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
    )
    return extract_json_object(response.text)

def analyze_legacy_application(sources, metadata, provider, api_key, model_name, azure_endpoint=None):
    prompt = build_analysis_prompt(sources, metadata)
    if provider == "Microsoft Azure OpenAI": ai_result = analyze_with_azure_openai(prompt, api_key, azure_endpoint, model_name)
    elif provider == "Anthropic Claude": ai_result = analyze_with_claude(prompt, api_key, model_name)
    elif provider == "Google Gemini": ai_result = analyze_with_gemini(prompt, api_key, model_name)
    else: raise ValueError(f"Unsupported provider: {provider}")
    return merge_static_and_ai_results(ai_result, metadata)

# =============================================================================
# 10. RENDERING FUNCTIONS (SME REVIEW WORKFLOW ADDED)
# =============================================================================
def render_dataframe_section(title, records, empty_message, key):
    """
    Renders an editable dataframe to allow SME review and validation.
    Returns the edited records to be synced with state.
    """
    st.markdown(f"#### {title}")
    if records:
        df = pd.DataFrame(records)
        # Add a review boolean column if not present
        if "sme_approved" not in df.columns:
            df.insert(0, "sme_approved", False)
        
        edited_df = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            key=key
        )
        return edited_df.to_dict('records')
    else:
        st.info(empty_message)
        return records

def render_mermaid_diagram(title, diagram, filename, height="500px"):
    st.markdown(f"#### {title}")
    if not diagram:
        st.info("No diagram generated.")
        return
    try:
        st_mermaid(diagram, height=height)
    except Exception:
        st.warning("Diagram could not be rendered. Source below.")
        st.code(diagram, language="mermaid")
    st.download_button(label=f"Download {filename}", data=diagram, file_name=filename, mime="text/plain", use_container_width=True)

def calculate_coverage(result):
    reqs = {
        "Business logic": bool(result.get("business_rules") or result.get("business_processes")),
        "Dependencies": bool(result.get("dependencies")),
        "Interfaces": bool(result.get("interfaces")),
        "Data flows": bool(result.get("data_flows")),
        "Technical risks": bool(result.get("technical_risks")),
        "Application mapping": bool(result.get("application_mapping"))
    }
    return reqs, round(sum(reqs.values()) / len(reqs) * 100)

# =============================================================================
# 11. SIDEBAR
# =============================================================================
st.sidebar.title("⚙️ Configuration")
provider = st.sidebar.selectbox("AI Provider", ["Microsoft Azure OpenAI", "Anthropic Claude", "Google Gemini"])

azure_endpoint = None
if provider == "Microsoft Azure OpenAI":
    api_key = st.sidebar.text_input("API Key", type="password", value=os.environ.get("AZURE_OPENAI_API_KEY", ""))
    azure_endpoint = st.sidebar.text_input("Endpoint", value=os.environ.get("AZURE_OPENAI_ENDPOINT", ""))
    model_name = st.sidebar.text_input("Deployment Name", value=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"))
elif provider == "Anthropic Claude":
    api_key = st.sidebar.text_input("API Key", type="password", value=os.environ.get("ANTHROPIC_API_KEY", ""))
    model_name = st.sidebar.text_input("Claude Model", value=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620"))
else:
    api_key = st.sidebar.text_input("API Key", type="password", value=os.environ.get("GEMINI_API_KEY", ""))
    model_name = st.sidebar.text_input("Gemini Model", value=os.environ.get("GEMINI_MODEL", "gemini-1.5-pro"))

st.sidebar.divider()
st.sidebar.subheader("📂 Pilot Codebase")
uploaded_files = st.sidebar.file_uploader("Upload files", type=SUPPORTED_EXTENSIONS, accept_multiple_files=True)
pasted_filename = st.sidebar.text_input("Pasted source filename", value="pasted_source.sql")
pasted_code = st.sidebar.text_area("Or paste source code", height=200)

run_analysis = st.sidebar.button("🚀 Analyze Application", type="primary", use_container_width=True)
if st.sidebar.button("🗑️ Clear Analysis", use_container_width=True):
    for key in ["analysis_result", "analysis_metadata", "analysis_sources", "analysis_provider", "analysis_model"]:
        st.session_state.pop(key, None)
    st.rerun()

# =============================================================================
# 12. MAIN
# =============================================================================
st.title("🧭 Legacy Application Knowledge Extractor")
st.caption("AI-assisted reverse engineering with human-in-the-loop SME validation.")

try:
    sources = build_source_collection(uploaded_files, pasted_code, pasted_filename)
except Exception as error:
    st.error(str(error))
    sources = []

if run_analysis:
    if not sources: st.error("Provide source code.")
    elif not api_key: st.error("Missing API Key.")
    else:
        with st.spinner("Extracting knowledge..."):
            try:
                metadata = extract_technical_metadata(sources)
                result = analyze_legacy_application(sources, metadata, provider, api_key, model_name, azure_endpoint)
                st.session_state["analysis_result"] = result
                st.session_state["analysis_metadata"] = metadata
                st.session_state["analysis_sources"] = sources
                st.session_state["analysis_provider"] = provider
                st.session_state["analysis_model"] = model_name
            except Exception as e:
                st.error(f"Analysis failed: {str(e)}")

if "analysis_result" not in st.session_state:
    st.info("Upload source files and start the analysis.")
    st.stop()

result = st.session_state["analysis_result"]
metadata = st.session_state["analysis_metadata"]
saved_sources = st.session_state["analysis_sources"]

reqs, cov = calculate_coverage(result)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Files", metadata["file_count"])
c2.metric("Lines of Code", metadata["total_line_count"])
c3.metric("Components", len(result["components"]))
c4.metric("Coverage", f"{cov}%")

tabs = st.tabs(["Overview", "Business Logic", "Architecture", "Data Flows", "Risks & Impact", "Diagrams", "Static Evidence", "Downloads"])

with tabs[0]:
    st.success(result.get("executive_summary") or "N/A")
    st.write("**Purpose:**", result.get("application_purpose") or "N/A")
    st.write("**Notes:**", result.get("technical_notes") or "N/A")

with tabs[1]:
    result["business_processes"] = render_dataframe_section("Business Processes", result["business_processes"], "None", "bp_edit")
    result["business_rules"] = render_dataframe_section("Business Rules", result["business_rules"], "None", "br_edit")

with tabs[2]:
    result["components"] = render_dataframe_section("Components", result["components"], "None", "comp_edit")
    result["dependencies"] = render_dataframe_section("Dependencies", result["dependencies"], "None", "dep_edit")
    result["interfaces"] = render_dataframe_section("Interfaces", result["interfaces"], "None", "int_edit")
    result["application_mapping"] = render_dataframe_section("App Mapping", result["application_mapping"], "None", "map_edit")

with tabs[3]:
    result["data_objects"] = render_dataframe_section("Data Objects", result["data_objects"], "None", "obj_edit")
    result["data_flows"] = render_dataframe_section("Data Flows", result["data_flows"], "None", "flow_edit")

with tabs[4]:
    result["technical_risks"] = render_dataframe_section("Technical Risks", result["technical_risks"], "None", "risk_edit")
    result["impact_analysis"] = render_dataframe_section("Impact Analysis", result["impact_analysis"], "None", "impact_edit")

with tabs[5]:
    dt = st.selectbox("Diagram", ["Process Flow", "App Map", "Data Flow", "Call Graph"])
    if dt == "Process Flow": render_mermaid_diagram("Process Flow", result["mermaid_process_flow"], "bp.mmd")
    elif dt == "App Map": render_mermaid_diagram("App Map", result["mermaid_application_map"], "app.mmd")
    elif dt == "Data Flow": render_mermaid_diagram("Data Flow", result["mermaid_data_flow"], "df.mmd")
    else: render_mermaid_diagram("Call Graph", result["mermaid_call_graph"], "cg.mmd")

with tabs[6]:
    st.json(metadata, expanded=False)

with tabs[7]:
    st.markdown("#### Export SME-Reviewed Knowledge Base")
    package = {
        "metadata": {"provider": st.session_state.get("analysis_provider"), "file_count": metadata["file_count"]},
        "reviewed_knowledge": result
    }
    st.download_button("📥 Download JSON Base", json.dumps(package, indent=2).encode("utf-8"), "knowledge.json", "application/json", type="primary")
