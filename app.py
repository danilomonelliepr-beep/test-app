import os
import json
import streamlit as st
import sqlglot
import google.generativeai as genai
from streamlit_mermaid import st_mermaid

# Configurazione minimale priva di parametri opzionali che causano il TypeError
st.set_page_config(page_title="Legacy Code Analyzer")

st.sidebar.title("⚙️ Configurazione")
api_key = st.sidebar.text_input(
    "Gemini API Key", 
    type="password", 
    value=os.environ.get("GEMINI_API_KEY", ""),
    help="Inserisci la tua API Key di Google Gemini"
)

# -----------------------------------------------------------------------------
# 2. FILE DI CODICE LEGACY DI ESEMPIO (DUMMY DATA FOR DEMO)
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
        // Query SQL embedded
        String query = "SELECT status, total_spent FROM users JOIN orders ON users.id = orders.user_id WHERE users.id = '" + customerId + "'";
        
        boolean isActive = true; // Simulazione stato
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
# 3. UTILITY FUNZIONI: AST & PARSING SQL
# -----------------------------------------------------------------------------
def parse_sql_tables(sql_text):
    """Estrae le tabelle lette o scritte usando sqlglot"""
    try:
        expression = sqlglot.parse_one(sql_text)
        tables = [table.name for table in expression.find_all(exp.Table)]
        return list(set(tables))
    except Exception:
        return []

def extract_technical_metadata(code):
    """Simula l'estrazione AST di costrutti SQL e metriche base"""
    lines = code.strip().split("\n")
    sql_tables = []
    
    # Ricerca basilare di stringhe SQL per la demo
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
# 4. CHIAMATA AI SERVIZI LLM (GOOGLE GEMINI)
# -----------------------------------------------------------------------------
def analyze_legacy_code(code, metadata, api_key):
    """Invia il codice e il contesto AST a Gemini per estrarre regole e Mermaid"""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash-latest")
    
    system_prompt = f"""
    Sei uno specialista in Legacy Code Reverse Engineering e Business Analysis.
    Analizza il seguente codice sorgente e i metadati sintetici estratti dall'AST.

    METADATI ESTRATTI:
    - Tabelle SQL individuate: {metadata['detected_tables']}
    - Presenza di blocchi condizionali: {metadata['has_conditionals']}

    CODICE LEGACY:
    ```
    {code}
    ```

    Restituisci ESATTAMENTE un oggetto JSON valido (senza testo prima o dopo) con la seguente struttura:
    {{
      "summary": "Una o due frasi che descrivono lo scopo business di questo codice.",
      "prerequisites": ["Elenco dei prerequisiti o condizioni necessarie"],
      "business_rules": [
        {{"rule_id": "BR-01", "condition": "Condizione", "action": "Azione di business"}}
      ],
      "mermaid_code": "graph TD\\n  Node1[Inizio] --> Node2[Azione]\\n  ...",
      "technical_notes": "Note su debito tecnico o vulnerabilità individuate."
    }}

    IMPORTANTE per mermaid_code: Genera un diagramma di flusso pulito 'graph TD', usa etichette semplici nei nodi senza caratteri speciali che rompono la sintassi Mermaid.
    """

    response = model.generate_content(
        system_prompt,
        generation_config={"response_mime_type": "application/json"}
    )
    
    return json.loads(response.text)

# -----------------------------------------------------------------------------
# 5. INTERFACCIA UTENTE (STREAMLIT DUAL-VIEW)
# -----------------------------------------------------------------------------
st.title("🔄 Legacy Code to Business Knowledge Platform")
st.caption("Hackathon Prototype: Transform legacy source code into actionable business logic & diagrams.")

# Selezione File o Custom Input
st.sidebar.subheader("📂 Codebase Explorer")
file_option = st.sidebar.selectbox(
    "Seleziona un modulo legacy:",
    ["COBOL: PROCESS-DISCOUNT.cbl", "JAVA: OrderProcessor.java", "Inserisci Codice Personalizzato"]
)

if file_option == "COBOL: PROCESS-DISCOUNT.cbl":
    source_code = SAMPLE_COBOL
    language = "cobol"
elif file_option == "JAVA: OrderProcessor.java":
    source_code = SAMPLE_JAVA
    language = "java"
else:
    source_code = st.sidebar.text_area("Incolla qui il codice legacy:", height=300)
    language = "text"

# Pulsante di Esecuzione Pipeline
st.sidebar.divider()
run_analysis = st.sidebar.button("🚀 Avvia Reverse Engineering", type="primary", use_container_width=True)

# METRICHE & PIPELINE STATE
metadata = extract_technical_metadata(source_code)

# WORKSPACE DUAL-VIEW (SPLIT 50/50)
col_left, col_right = st.columns(2)

# --- COLONNA SINISTRA: VISTA TECNICA ---
with col_left:
    st.subheader("💻 Vista Tecnica (Source & AST)")
    st.markdown("**Codice Sorgente Legacy:**")
    st.code(source_code, language=language)

    st.markdown("**Metadati Estratti in Locale (AST & SQL Parser):**")
    m_col1, m_col2, m_col3 = st.columns(3)
    m_col1.metric("Righe Codice", metadata["line_count"])
    m_col2.metric("Tabelle SQL", len(metadata["detected_tables"]))
    m_col3.metric("Logica Condizionale", "Sì" if metadata["has_conditionals"] else "No")

    if metadata["detected_tables"]:
        st.info(f"🔍 **Tabelle SQL Riconosciute:** `{', '.join(metadata['detected_tables'])}`")

# --- COLONNA DESTRA: VISTA BUSINESS ---
with col_right:
    st.subheader("📋 Vista Business (Knowledge Extraction)")

    if run_analysis:
        if not api_key:
            st.error("⚠️ Inserisci la chiave API Gemini nella barra laterale per procedere con l'analisi LLM.")
        else:
            with st.spinner("AI al lavoro: estrazione regole e sintesi diagramma..."):
                try:
                    result = analyze_legacy_code(source_code, metadata, api_key)

                    # 1. Sommario Esecutivo
                    st.success("**Scopo Funzionale del Processo:**")
                    st.write(result.get("summary", ""))

                    # 2. Diagramma Mermaid
                    st.markdown("#### 📊 Flusso Operativo (Diagramma Mermaid)")
                    mermaid_str = result.get("mermaid_code", "")
                    if mermaid_str:
                        st_mermaid(mermaid_str, height="300px")
                    
                    # 3. Tabella delle Regole di Business
                    st.markdown("#### ⚙️ Regole di Business (Decision Table)")
                    rules = result.get("business_rules", [])
                    if rules:
                        st.dataframe(rules, use_container_width=True)

                    # 4. Prerequisiti & Note Tecniche
                    with st.expander("📌 Prerequisiti e Note di Debito Tecnico"):
                        st.markdown("**Prerequisiti di Processo:**")
                        for pre in result.get("prerequisites", []):
                            st.write(f"- {pre}")
                        st.markdown("**Note di Architettura/Debito Tecnico:**")
                        st.write(result.get("technical_notes", "Nessuna nota presente."))

                except Exception as e:
                    st.error(f"Errore durante l'elaborazione dell'IA: {str(e)}")
    else:
        st.info("👈 Clicca su **'Avvia Reverse Engineering'** nella barra laterale per generare la documentazione di business e i diagrammi.")
