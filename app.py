import os
import json
import io
import streamlit as st
import sqlglot
from sqlglot import exp
import google.generativeai as genai
from streamlit_mermaid import st_mermaid

# 1. Page Configuration (Wide Mode)
st.set_page_config(page_title="Legacy Code Analyzer", layout="wide")

# 2. Sidebar Configuration
st.sidebar.title("⚙️ Configuration")

api_key = st.sidebar.text_input(
    "Gemini API Key", 
    type="password", 
    value=os.environ.get("GEMINI_API_KEY", ""),
    help="Enter your Google Gemini API Key"
)

# -----------------------------------------------------------------------------
# 3. UTILITY FUNCTIONS: AST & SQL PARSING
# -----------------------------------------------------------------------------
def parse_sql_tables(sql_text):
    """Extracts read or written tables using sqlglot"""
    try:
        expression = sqlglot.parse_one(sql_text)
        tables = [table.name for table in expression.find_all(exp.Table)]
        return list(set(tables))
    except Exception:
        return []

def extract_technical_metadata(code):
    """Extracts basic metadata from the source code"""
    lines = code.strip().split("\n") if code.strip() else []
    sql_tables = []
    
    if "SELECT" in code.upper():
        try:
            sql_tables = parse_sql_tables(code)
        except Exception:
            sql_tables = []

    return {
        "line_count": len(lines),
        "detected_tables": sql_tables,
        "has_conditionals": "IF" in code.upper() or "if (" in code
    }

# -----------------------------------------------------------------------------
# 4. LLM SERVICE CALLS (GOOGLE GEMINI)
# -----------------------------------------------------------------------------
def analyze_legacy_code(code, metadata, api_key):
    """Sends code to Gemini for reverse engineering analysis."""
    genai.configure(api_key=api_key)
    
    selected_model_name = None
    # Model configuration forced to gemini-3.6-flash
    priority_models = ["gemini-3.6-flash"]
    
    try:
        available_models = [
            m.name.replace("models/", "") 
            for m in genai.list_models() 
            if "generateContent" in m.supported_generation_methods
        ]
        
        for target in priority_models:
            if target in available_models:
                selected_model_name = target
                break
                
        if not selected_model_name and available_models:
            selected_model_name = available_models[0]
            
    except Exception:
        # Direct fallback to gemini-3.6-flash if model list API call fails
        selected_model_name = "gemini-3.6-flash"

    if not selected_model_name:
        selected_model_name = "gemini-3.6-flash"

    model = genai.GenerativeModel(selected_model_name)

    system_prompt = f"""
    You are a specialist in Legacy Code Reverse Engineering and Business Analysis.
    Analyze the following source code and synthetic metadata extracted from the AST.
    Provide a very detailed explanation of the logic, clearly describing how the code behaves and how each part of the implementation works.

    EXTRACTED METADATA:
    - Identified SQL Tables: {metadata['detected_tables']}
    - Presence of conditional blocks: {metadata['has_conditionals']}

    LEGACY CODE:
    ```
    {code}
    ```

    Return EXACTLY a valid JSON object with the following structure:
    {{
      "summary": "One or two sentences describing the business purpose of this code.",
      "prerequisites": ["List of prerequisites or necessary conditions"],
      "business_rules": [
        {{"rule_id": "BR-01", "condition": "Condition description", "action": "Business action"}}
      ],
      "mermaid_code": "graph TD\\n  Node1[Start] --> Node2[Action]",
      "technical_notes": "Notes on technical debt or identified vulnerabilities."
    }}

    IMPORTANT for mermaid_code: Generate a clean 'graph TD' flowchart, use simple labels inside nodes without special characters that break Mermaid syntax.
    """

    response = model.generate_content(
        system_prompt,
        generation_config={"response_mime_type": "application/json"}
    )
    
    clean_text = response.text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
        
    return json.loads(clean_text.strip())

# -----------------------------------------------------------------------------
# 5. USER INTERFACE
# -----------------------------------------------------------------------------
st.title("🔄 Legacy Code to Business Knowledge Platform")
st.caption("Transform legacy source code into actionable business logic & visual diagrams.")

# Custom Code Input in Sidebar
st.sidebar.subheader("📝 Source Code Input")
source_code = st.sidebar.text_area("Paste legacy code here:", height=400)

run_analysis = st.sidebar.button("🚀 Start Reverse Engineering", type="primary", use_container_width=True)

# Wide layout columns
col_left, col_right = st.columns(2)

# Extract basic metadata
metadata = extract_technical_metadata(source_code)

# --- LEFT COLUMN: TECHNICAL VIEW ---
with col_left:
    st.subheader("💻 Technical View (Code & AST)")
    
    if source_code:
        st.markdown("**Source Code:**")
        st.code(source_code, height=450)
        
        # Download Source Code Button
        st.download_button(
            label="💾 Download Source Code",
            data=source_code,
            file_name="source_code.txt",
            mime="text/plain"
        )
    else:
        st.info("👈 Paste your code in the sidebar to get started.")

    st.markdown("**Locally Extracted Metadata:**")
    m_col1, m_col2, m_col3 = st.columns(3)
    m_col1.metric("Lines of Code", metadata["line_count"])
    m_col2.metric("SQL Tables", len(metadata["detected_tables"]))
    m_col3.metric("Conditional Logic", "Yes" if metadata["has_conditionals"] else "No")

    if metadata["detected_tables"]:
        st.info(f"🔍 **Identified SQL Tables:** `{', '.join(metadata['detected_tables'])}`")

# --- RIGHT COLUMN: BUSINESS VIEW ---
with col_right:
    st.subheader("📋 Business View (Knowledge Extraction)")

    if run_analysis:
        if not source_code.strip():
            st.error("⚠️ Please enter source code in the sidebar before starting the analysis.")
        elif not api_key:
            st.error("⚠️ Please enter your Gemini API key in the sidebar.")
        else:
            with st.spinner("AI at work: extracting rules and synthesizing diagram..."):
                try:
                    result = analyze_legacy_code(source_code, metadata, api_key)
                    st.session_state['analysis_result'] = result
                except Exception as e:
                    st.error(f"Error during AI processing: {str(e)}")

    # Display results saved in session state
    if 'analysis_result' in st.session_state:
        res = st.session_state['analysis_result']

        # 1. Executive Summary
        st.success("**Functional Purpose of the Process:**")
        st.write(res.get("summary", ""))

        # 2. Mermaid Diagram
        st.markdown("#### 📊 Operational Flow (Mermaid Diagram)")
        mermaid_str = res.get("mermaid_code", "")
        if mermaid_str:
            st_mermaid(mermaid_str, height="400px")
            
            # Download Mermaid Code Button
            st.download_button(
                label="💾 Download Mermaid Diagram (.mmd)",
                data=mermaid_str,
                file_name="flow_diagram.mmd",
                mime="text/plain"
            )

        # 3. Business Rules Table
        st.markdown("#### ⚙️ Business Rules (Decision Table)")
        rules = res.get("business_rules", [])
        if rules:
            st.dataframe(rules, use_container_width=True)

        # 4. Prerequisites & Technical Debt Notes
        with st.expander("📌 Prerequisites & Technical Debt Notes", expanded=True):
            st.markdown("**Process Prerequisites:**")
            for pre in res.get("prerequisites", []):
                st.write(f"- {pre}")
            st.markdown("**Architecture / Technical Debt Notes:**")
            st.write(res.get("technical_notes", "No notes available."))

        st.divider()
        
        # Download Full Analysis JSON Button
        json_bytes = json.dumps(res, indent=2).encode('utf-8')
        st.download_button(
            label="📥 Download Full Analysis (JSON)",
            data=json_bytes,
            file_name="business_analysis.json",
            mime="application/json",
            type="primary",
            use_container_width=True
        )
    elif not run_analysis:
        st.info("👈 Click on **'Start Reverse Engineering'** in the sidebar to generate the analysis.")
