import os
import json
import streamlit as st
import sqlglot
from sqlglot import exp
import google.generativeai as genai
from streamlit_mermaid import st_mermaid

# Minimal configuration free of optional parameters causing TypeError
st.set_page_config(page_title="Legacy Code Analyzer")

st.sidebar.title("⚙️ Configuration")
api_key = st.sidebar.text_input(
    "Gemini API Key", 
    type="password", 
    value=os.environ.get("GEMINI_API_KEY", ""),
    help="Enter your Google Gemini API Key"
)

# -----------------------------------------------------------------------------
# 2. SAMPLE LEGACY CODE FILES (DUMMY DATA FOR DEMO)
# -----------------------------------------------------------------------------
SAMPLE_COBOL = """
000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. PROCESS-DISCOUNT.
000300 DATA DIVISION.
000400 WORKING-STORAGE SECTION.
000500 01 CUST-BAL        PIC 9(6)V99.
000600 01 DISC-RATE       PIC 9(2)V99.
000700 01 CUST-STATUS     PIC X(10).
000800 PROCEDURE DIVISION.
000900     EXEC SQL
001000         SELECT BALANCE, STATUS INTO :CUST-BAL, :CUST-STATUS 
001100         FROM CUSTOMER_TABLE WHERE CUST_ID = :C-ID
001200     END-EXEC.
001300     IF CUST-STATUS = 'ACTIVE' THEN
001400         IF CUST-BAL > 50000 THEN
001500             MOVE 0.15 TO DISC-RATE
001600         ELSE
001700             MOVE 0.05 TO DISC-RATE
001800         END-IF
001900     ELSE
002000         MOVE 0.00 TO DISC-RATE
002100     END-IF.
"""

SAMPLE_JAVA = """
public class OrderProcessor {
    public void processOrder(String customerId, double orderAmount) {
        // Embedded SQL Query
        String query = "SELECT status, total_spent FROM users JOIN orders ON users.id = orders.user_id WHERE users.id = '" + customerId + "'";
        
        boolean isActive = true; // State simulation
        if (isActive) {
            if (orderAmount > 1000) {
                applyDiscount(0.20); // 20% discount for large orders
            } else {
                applyDiscount(0.05); // 5% default discount
            }
        } else {
            throw new IllegalArgumentException("Customer account is inactive");
        }
    }

    private void applyDiscount(double rate) {
        System.out.println("Applying discount: " + rate);
    }
}
"""

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
    """Simulates AST extraction of SQL constructs and basic metrics"""
    lines = code.strip().split("\n")
    sql_tables = []
    
    # Basic SQL string search for demo purposes
    if "SELECT" in code.upper():
        if "CUSTOMER_TABLE" in code.upper():
            sql_tables = parse_sql_tables("SELECT BALANCE, STATUS FROM CUSTOMER_TABLE")
        elif "USERS" in code.upper():
            sql_tables = parse_sql_tables("SELECT status, total_spent FROM users JOIN orders ON users.id = orders.user_id")

    return {
        "line_count": len(lines),
        "detected_tables": sql_tables,
        "has_conditionals": "IF" in code.upper() or "if (" in code
    }

# -----------------------------------------------------------------------------
# 4. LLM SERVICE CALLS (GOOGLE GEMINI)
# -----------------------------------------------------------------------------
def analyze_legacy_code(code, metadata, api_key):
    """Sends code to Gemini with dynamic model selection and error handling."""
    genai.configure(api_key=api_key)
    
    # 1. Find a valid available model on your account
    selected_model_name = None
    priority_models = ["gemini-3.6-flash"]
    
    try:
        # Retrieve the actual list of models supported by your API key
        available_models = [
            m.name.replace("models/", "") 
            for m in genai.list_models() 
            if "generateContent" in m.supported_generation_methods
        ]
        
        # Pick the first compatible model present in priority list
        for target in priority_models:
            if target in available_models:
                selected_model_name = target
                break
                
        # If none from priority list is present, pick the first available
        if not selected_model_name and available_models:
            selected_model_name = available_models[0]
            
    except Exception:
        # Safety fallback if list_models fails
        selected_model_name = "gemini-3.6-flash"

    if not selected_model_name:
        raise ValueError("No valid Gemini model found for this API Key.")

    # 2. Initialize the identified model
    model = genai.GenerativeModel(selected_model_name)

    system_prompt = f"""
    You are a specialist in Legacy Code Reverse Engineering and Business Analysis.
    Analyze the following source code and synthetic metadata extracted from the AST.

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

    # 3. API Call
    response = model.generate_content(
        system_prompt,
        generation_config={"response_mime_type": "application/json"}
    )
    
    # 4. Clean response text to prevent JSON parsing errors
    clean_text = response.text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
        
    return json.loads(clean_text.strip())

# -----------------------------------------------------------------------------
# 5. USER INTERFACE (STREAMLIT DUAL-VIEW)
# -----------------------------------------------------------------------------
st.title("🔄 Legacy Code to Business Knowledge Platform")
st.caption("Hackathon Prototype: Transform legacy source code into actionable business logic & diagrams.")

# File Selection or Custom Input
st.sidebar.subheader("📂 Codebase Explorer")
file_option = st.sidebar.selectbox(
    "Select a legacy module:",
    ["COBOL: PROCESS-DISCOUNT.cbl", "JAVA: OrderProcessor.java", "Enter Custom Code"]
)

if file_option == "COBOL: PROCESS-DISCOUNT.cbl":
    source_code = SAMPLE_COBOL
    language = "cobol"
elif file_option == "JAVA: OrderProcessor.java":
    source_code = SAMPLE_JAVA
    language = "java"
else:
    source_code = st.sidebar.text_area("Paste legacy code here:", height=300)
    language = "text"

# Pipeline Execution Button
st.sidebar.divider()
run_analysis = st.sidebar.button("🚀 Start Reverse Engineering", type="primary", use_container_width=True)

# METRICS & PIPELINE STATE
metadata = extract_technical_metadata(source_code)

# WORKSPACE DUAL-VIEW (SPLIT 50/50)
col_left, col_right = st.columns(2)

# --- LEFT COLUMN: TECHNICAL VIEW ---
with col_left:
    st.subheader("💻 Technical View (Source & AST)")
    st.markdown("**Legacy Source Code:**")
    st.code(source_code, language=language)

    st.markdown("**Locally Extracted Metadata (AST & SQL Parser):**")
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
        if not api_key:
            st.error("⚠️ Please enter your Gemini API key in the sidebar to proceed with LLM analysis.")
        else:
            with st.spinner("AI at work: extracting rules and synthesizing diagram..."):
                try:
                    result = analyze_legacy_code(source_code, metadata, api_key)

                    # 1. Executive Summary
                    st.success("**Functional Purpose of the Process:**")
                    st.write(result.get("summary", ""))

                    # 2. Mermaid Diagram
                    st.markdown("#### 📊 Operational Flow (Mermaid Diagram)")
                    mermaid_str = result.get("mermaid_code", "")
                    if mermaid_str:
                        st_mermaid(mermaid_str, height="300px")
                    
                    # 3. Business Rules Table
                    st.markdown("#### ⚙️ Business Rules (Decision Table)")
                    rules = result.get("business_rules", [])
                    if rules:
                        st.dataframe(rules, use_container_width=True)

                    # 4. Prerequisites & Technical Notes
                    with st.expander("📌 Prerequisites & Technical Debt Notes"):
                        st.markdown("**Process Prerequisites:**")
                        for pre in result.get("prerequisites", []):
                            st.write(f"- {pre}")
                        st.markdown("**Architecture / Technical Debt Notes:**")
                        st.write(result.get("technical_notes", "No notes available."))

                except Exception as e:
                    st.error(f"Error during AI processing: {str(e)}")
    else:
        st.info("👈 Click on **'Start Reverse Engineering'** in the sidebar to generate business documentation and diagrams.")
