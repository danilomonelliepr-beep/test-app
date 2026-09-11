"""
═══════════════════════════════════════════════════════════════════════════
I DOCUMENTI — PDF e Word.

È questo, non l'applicazione, quello che finisce in mano al cliente. Era rimasto
com'era mentre tutto il resto cambiava, e si vedeva: carattere di sistema,
intestazioni di serie, tabelle in cui un fatto del parser e un'ipotesi del
modello erano due righe identiche.

Tre idee reggono questo file.

· UNA SOLA DESCRIZIONE, DUE RESE. `prepara()` costruisce l'elenco dei blocchi
  del documento — titoli, prosa, tabelle, diagrammi — e PDF e Word si limitano
  a disegnarlo. Prima erano due funzioni lunghe e parallele: ogni aggiunta
  andava fatta due volte, e infatti avevano già smesso di dire le stesse cose.

· LA PROVENIENZA SI VEDE. Ogni tabella porta da dove viene la riga (parser o
  modello), quanta confidenza ha, e se un esperto l'ha confermata. Senza questo
  il documento è un elenco di affermazioni tutte uguali, e chi lo firma non sa
  su cosa sta mettendo il nome.

· NIENTE AFFIDATO AL SOLO COLORE. Ogni marcatore è una parola o un conteggio di
  puntini; il colore rinforza e basta. Non è solo accessibilità: questi
  documenti si stampano, e si stampano in bianco e nero.

  (IBM Plex non ha ■ □ ● ○ ▲: in un PDF un glifo mancante diventa un rettangolo
  nero. La confidenza usa quindi • e ·, che ci sono, e la provenienza una
  parola. Verificato sul font, non dato per buono.)
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

import contract
import mermaid_render

# =============================================================================
# I TOKEN — gli stessi di `ui.py`. Se cambiano lì, cambiano qui.
# =============================================================================
INCHIOSTRO = colors.HexColor("#17212B")
INCHIOSTRO_2 = colors.HexColor("#4A5A6B")
RIGA = colors.HexColor("#D4DCE4")
ACCENTO_CUPO = colors.HexColor("#0E434C")
CONFERMA = colors.HexColor("#1F6B45")
ZEBRA = colors.HexColor("#F7F9FB")

GRAVITA_COLORI = {
    "CRITICAL": (colors.HexColor("#FDF0F0"), colors.HexColor("#9B2226")),
    "HIGH": (colors.HexColor("#FDF5E8"), colors.HexColor("#9A5B00")),
    "MEDIUM": (colors.white, INCHIOSTRO_2),
    "LOW": (colors.white, colors.HexColor("#6B7A89")),
}
ORDINE_GRAVITA = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
ORDINE_CONFIDENZA = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

# Puntini invece di cerchi: • (U+2022) e · (U+00B7) esistono in Plex, ● e ○ no.
PUNTINI = {"HIGH": "\u2022\u2022\u2022", "MEDIUM": "\u2022\u2022\u00b7",
           "LOW": "\u2022\u00b7\u00b7"}
PROVENIENZA = {"STATIC_ANALYSIS": "parser", "LLM_ANALYSIS": "model", "MIXED": "both"}

# =============================================================================
# I CARATTERI. Se la cartella `fonts/` c'è si usa IBM Plex, come
# nell'applicazione; altrimenti si scende su Helvetica senza fare storie.
# =============================================================================
CARTELLA_FONT = Path(__file__).parent / "fonts"
FONT = {"corpo": "Helvetica", "forte": "Helvetica-Bold",
        "mono": "Courier", "mono_forte": "Courier-Bold"}
NOME_WORD = "Calibri"
_registrati = False


def _registra_font() -> bool:
    global _registrati, NOME_WORD
    if _registrati:
        return FONT["corpo"] != "Helvetica"
    _registrati = True
    coppie = [("PlexSans", "IBMPlexSans-Regular.ttf"),
              ("PlexSans-SemiBold", "IBMPlexSans-SemiBold.ttf"),
              ("PlexMono", "IBMPlexMono-Regular.ttf"),
              ("PlexMono-Medium", "IBMPlexMono-Medium.ttf")]
    try:
        for nome, file in coppie:
            percorso = CARTELLA_FONT / file
            if not percorso.exists():
                return False
            pdfmetrics.registerFont(TTFont(nome, str(percorso)))
        FONT.update({"corpo": "PlexSans", "forte": "PlexSans-SemiBold",
                     "mono": "PlexMono", "mono_forte": "PlexMono-Medium"})
        NOME_WORD = "IBM Plex Sans"
        return True
    except Exception:
        return False


# =============================================================================
# PREPARAZIONE — i blocchi del documento, una volta sola per tutti e due.
# =============================================================================
COLONNE_MONO = {"process_id", "rule_id", "flow_id", "risk_id", "impact_id", "mapping_id",
                "question_id", "assumption_id", "source_file", "source_component",
                "component_name", "object_name", "target", "source", "affected_component",
                "line_number", "name"}
# Fuori dalle tabelle del documento: l'evidenza è il ragionamento dietro la
# riga, e in una tabella a nove colonne rende illeggibile tutto il resto. Resta
# nell'applicazione e nell'esportazione JSON.
COLONNE_FUORI = {"evidence"}

ETICHETTE = {
    "process_id": "ID", "rule_id": "ID", "flow_id": "ID", "risk_id": "ID",
    "impact_id": "ID", "mapping_id": "ID", "question_id": "ID", "assumption_id": "ID",
    "source_file": "File", "source_component": "In", "component_name": "Name",
    "component_type": "Kind", "dependency_type": "Kind", "interface_type": "Kind",
    "object_name": "Object", "object_type": "Kind", "external_system": "System",
    "integration_type": "Via", "affected_component": "Affects", "sme_approved": "OK",
    "business_impact": "Why it matters", "why_it_matters": "Why it matters",
    "risk_if_wrong": "If wrong", "line_number": "Line", "related_ids": "Related",
    "addressed_to": "Ask", "data_description": "Data", "impact_description": "Effect",
    "change_scenario": "Change", "involved_components": "Components",
    "affected_components": "Components", "source": "Found by", "confidence": "Conf.",
}
LARGHE = {"description", "condition", "action", "impact", "recommendation",
          "impact_description", "business_impact", "question", "why_it_matters",
          "assumption", "purpose", "data_description", "transformation", "mitigation",
          "basis", "risk_if_wrong", "change_scenario", "outcome", "trigger"}


def _enum_di(nome: str, campo: str):
    """I valori ammessi per quel campo in quella sezione, se ce ne sono."""
    voce = contract.CAMPI[nome]["campi"].get(campo)
    return voce[1] if voce else None


def _etichetta(nome: str, campo: str) -> str:
    # `source` significa due cose diverse a seconda della sezione: in
    # `components` e `technical_risks` è CHI ha trovato la riga (parser o
    # modello), in `dependencies` e `data_flows` è l'ORIGINE della dipendenza.
    # Il contratto lo sa già — nel primo caso il campo ha dei valori ammessi,
    # nel secondo no — e basta chiederglielo invece di indovinare dal nome.
    if campo == "source":
        return "Found by" if _enum_di(nome, campo) else "From"
    return ETICHETTE.get(campo) or campo.replace("_", " ").capitalize()


def _ordina(nome: str, righe: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """L'ordine con cui si leggono le righe.

    I rischi per gravità: un CRITICAL trentesimo, dopo ventinove LOW, è un
    CRITICAL che nessuno legge. Prima non si poteva ordinarli perché la gravità
    era testo libero; ora è un valore fra quattro."""
    if nome in ("technical_risks", "impact_analysis", "application_mapping"):
        campo = "criticality" if nome == "application_mapping" else "severity"
        return sorted(righe, key=lambda r: (
            ORDINE_GRAVITA.get(str(r.get(campo, "")).upper(), 9),
            str(r.get("affected_component", ""))))
    if nome == "dependencies":
        # Prima le dipendenze certe, poi i sospetti: l'ordine dice già quanto
        # fidarsi, senza doverlo leggere colonna per colonna.
        return sorted(righe, key=lambda r: (
            1 if r.get("dependency_type") == "PROBABLE_CALL" else 0,
            ORDINE_CONFIDENZA.get(str(r.get("confidence", "")).upper(), 9),
            str(r.get("source", ""))))
    return righe


def _colonne(nome: str, righe: List[Dict[str, Any]]) -> List[str]:
    spec = contract.CAMPI[nome]
    campi = [c for c in spec["campi"] if c not in COLONNE_FUORI]
    # Una colonna vuota in tutte le righe non è informazione: è spazio tolto
    # alle colonne che contano.
    tenute = [c for c in campi if any(str(r.get(c, "")).strip() for r in righe)]
    if any("sme_approved" in r for r in righe):
        tenute = ["sme_approved"] + tenute
    return tenute


def _valore(nome: str, campo: str, riga: Dict[str, Any]) -> str:
    v = riga.get(campo)
    if campo == "sme_approved":
        return "\u2713" if v else ""
    testo = "" if v is None else str(v).strip()
    if campo == "confidence":
        return PUNTINI.get(testo.upper(), testo)
    if campo == "source" and _enum_di(nome, campo):
        return PROVENIENZA.get(testo.upper(), testo.lower())
    return testo


def _mono(nome: str, campo: str) -> bool:
    """Il monospazio è per ciò che è letterale. `source` lo è quando è il nome
    di un componente, non quando è la parola «parser»."""
    if campo == "source":
        return not _enum_di(nome, campo)
    return campo in COLONNE_MONO


LEGENDA = [
    ("Found by", "parser = a fact the parser read in the source, and it cannot be wrong about "
                 "it. model = the model's reading of that source, which can be."),
    ("Conf.", "How sure the model is: \u2022\u2022\u2022 high, \u2022\u2022\u00b7 medium, "
              "\u2022\u00b7\u00b7 low."),
    ("OK", "\u2713 means a domain expert has checked this row. A blank cell means nobody has yet."),
    ("Severity", "CRITICAL, HIGH, MEDIUM, LOW \u2014 written out, never colour alone."),
]


def prepara(analysis_result: Dict[str, Any], metadata: Dict[str, Any],
            provider: str, model_name: str) -> Dict[str, Any]:
    r, m = analysis_result or {}, metadata or {}

    righe_tot = evidenza = alta = confermate = 0
    for nome in contract.CAMPI:
        for riga in r.get(nome, []) or []:
            righe_tot += 1
            evidenza += 1 if str(riga.get("evidence", "")).strip() else 0
            alta += 1 if str(riga.get("confidence", "")).upper() == "HIGH" else 0
            confermate += 1 if riga.get("sme_approved") else 0

    def quota(parte):
        return f"{round(parte / righe_tot * 100)}%" if righe_tot else "\u2014"

    gravi = [x for x in (r.get("technical_risks") or [])
             if str(x.get("severity", "")).upper() in ("CRITICAL", "HIGH")]

    copertina = [
        ("Files read", f"{m.get('file_count', 0)} \u00b7 {m.get('total_line_count', 0):,} lines"),
        ("Languages", ", ".join(m.get("languages", [])) or "\u2014"),
        ("Analysed by", f"{model_name or '\u2014'} ({provider or '\u2014'})"),
        ("Batches", str(r.get("_lotti", 1))),
        ("Rows in this document", str(righe_tot)),
        ("Rows with evidence in the code", quota(evidenza)),
        ("Rows at high confidence", quota(alta)),
        ("Rows confirmed by a domain expert", f"{confermate} ({quota(confermate)})"),
        ("Critical and high risks", str(len(gravi))),
        ("Contract version", str(r.get("contract_version", "\u2014"))),
    ]

    blocchi: List[Tuple] = []

    def titolo(numero, testo):
        blocchi.append(("titolo", f"{numero}. {testo}"))

    def prosa(testo):
        if str(testo or "").strip():
            blocchi.append(("prosa", str(testo).strip()))

    def sotto(testo):
        blocchi.append(("sottotitolo", testo))

    def tabella(nome):
        blocchi.append(("tabella", nome, _ordina(nome, list(r.get(nome, []) or []))))

    titolo(1, "Executive summary")
    sotto("What this application is for")
    prosa(r.get("application_purpose") or "Not determined.")
    sotto("In full")
    prosa(r.get("executive_summary") or "Not determined.")
    if str(r.get("technical_notes", "")).strip():
        sotto("Notes for a migration team")
        prosa(r["technical_notes"])

    titolo(2, "Business logic")
    sotto("Business processes")
    tabella("business_processes")
    sotto("Business rules")
    tabella("business_rules")

    titolo(3, "System architecture")
    sotto("Components")
    tabella("components")
    sotto("Dependencies")
    blocchi.append(("nota", "Certain calls first, suspected ones last. Rows marked PROBABLE_CALL "
                            "point at something not declared in the submitted code: either "
                            "outside the perimeter, or noise."))
    tabella("dependencies")
    sotto("Interfaces")
    tabella("interfaces")
    sotto("Application map")
    tabella("application_mapping")

    titolo(4, "Data objects and data flows")
    sotto("Data objects")
    tabella("data_objects")
    sotto("Data flows")
    tabella("data_flows")

    titolo(5, "Technical risks and impact")
    blocchi.append(("nota", "Ordered by severity, highest first."))
    sotto("Technical risks")
    tabella("technical_risks")
    sotto("Impact analysis")
    tabella("impact_analysis")

    blocchi.append(("pagina",))
    titolo(6, "Diagrams")
    fonti = r.get("_diagrammi_fonte") or {}
    for campo, nome_umano in [("mermaid_process_flow", "Process flow"),
                              ("mermaid_application_map", "Application map"),
                              ("mermaid_data_flow", "Data flow"),
                              ("mermaid_call_graph", "Call graph")]:
        codice = r.get(campo) or ""
        if not codice.strip():
            continue
        fonte = {"dati": "drawn from the validated tables",
                 "modello": "written by the model"}.get(fonti.get(campo, ""), "")
        blocchi.append(("diagramma", nome_umano, codice, fonte))

    titolo(7, "Open questions and assumptions")
    blocchi.append(("nota", "These are the rows to take to the business, not to the source code. "
                            "Nothing below can be settled by reading the code."))
    sotto("Questions for a domain expert")
    tabella("validation_questions")
    sotto("Assumptions this analysis rests on")
    tabella("assumptions")

    blocchi.append(("pagina",))
    titolo(8, "Appendix: what the parser found")
    blocchi.append(("nota", "Produced by sqlglot and pattern matching, with no model involved. "
                            "If a row above disagrees with this appendix, this appendix is right."))
    risoluzione = m.get("dependency_resolution") or {}
    blocchi.append(("coppie", [
        ("Components declared", str(len(m.get("components", [])))),
        ("Dependencies found", str(len(m.get("dependencies", [])))),
        ("SQL objects detected", str(len(m.get("detected_tables", [])))),
        ("Risk patterns matched", str(len(m.get("local_risks", [])))),
        ("Calls resolved to a declared component",
         str(risoluzione.get("resolved_to_declared_component", "\u2014"))),
        ("Calls pointing outside the perimeter",
         str(risoluzione.get("unresolved_outside_perimeter", "\u2014"))),
    ]))
    if m.get("detected_tables"):
        sotto("SQL objects touched")
        prosa(", ".join(m["detected_tables"][:200]))

    avvisi = r.get("contract_warnings") or []
    if avvisi:
        sotto("What the application had to correct in the model's answer")
        blocchi.append(("elenco", avvisi[:40]))

    return {
        "titolo": "Legacy Application Knowledge Extraction",
        "sottotitolo": (r.get("application_purpose") or "Reverse-engineering report"),
        "data": date.today().strftime("%d %B %Y"),
        "copertina": copertina,
        "blocchi": blocchi,
        "indice": [b[1] for b in blocchi if b[0] == "titolo"],
    }


def _pulisci(testo: str) -> str:
    """Il testo dei dati non è markup: & e < devono restare quello che sono."""
    return str(testo).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# =============================================================================
# RESA PDF
# =============================================================================
def _stili():
    _registra_font()
    return {
        "titolone": ParagraphStyle("titolone", fontName=FONT["forte"], fontSize=24, leading=28,
                                   textColor=INCHIOSTRO, spaceAfter=4),
        "sottotitolone": ParagraphStyle("sottotitolone", fontName=FONT["corpo"], fontSize=11,
                                        leading=16, textColor=INCHIOSTRO_2, spaceAfter=14),
        "h1": ParagraphStyle("h1", fontName=FONT["forte"], fontSize=14, leading=18,
                             textColor=ACCENTO_CUPO, spaceBefore=16, spaceAfter=6),
        "h2": ParagraphStyle("h2", fontName=FONT["forte"], fontSize=10.5, leading=14,
                             textColor=INCHIOSTRO, spaceBefore=10, spaceAfter=4),
        "corpo": ParagraphStyle("corpo", fontName=FONT["corpo"], fontSize=9.5, leading=14,
                                textColor=INCHIOSTRO, alignment=TA_LEFT, spaceAfter=5),
        "nota": ParagraphStyle("nota", fontName=FONT["corpo"], fontSize=8.5, leading=12,
                               textColor=INCHIOSTRO_2, spaceAfter=6),
        "cella": ParagraphStyle("cella", fontName=FONT["corpo"], fontSize=7.4, leading=9.4,
                                textColor=INCHIOSTRO),
        "cella_mono": ParagraphStyle("cella_mono", fontName=FONT["mono"], fontSize=7.0,
                                     leading=9.4, textColor=INCHIOSTRO),
        "intestazione": ParagraphStyle("intestazione", fontName=FONT["forte"], fontSize=7.4,
                                       leading=9.4, textColor=colors.white),
    }


def _pie(canvas, doc):
    canvas.saveState()
    larghezza = landscape(A4)[0]
    canvas.setStrokeColor(RIGA)
    canvas.setLineWidth(0.5)
    canvas.line(28, 26, larghezza - 28, 26)
    canvas.setFont(FONT["corpo"], 7.5)
    canvas.setFillColor(INCHIOSTRO_2)
    canvas.drawString(28, 16, "Legacy Application Knowledge Extraction")
    canvas.drawRightString(larghezza - 28, 16, f"page {doc.page}")
    canvas.restoreState()


def _larghezze(colonne: List[str], totale: float) -> List[float]:
    pesi = []
    for c in colonne:
        if c == "sme_approved":
            pesi.append(0.5)
        elif c in ("severity", "criticality"):
            pesi.append(1.15)   # «CRITICAL» deve starci senza spezzarsi
        elif c in ("confidence", "line_number"):
            pesi.append(0.8)
        elif c.endswith("_id") or c == "source":
            pesi.append(0.9)
        elif c in LARGHE:
            pesi.append(3.0)
        else:
            pesi.append(1.6)
    somma = sum(pesi) or 1
    return [totale * p / somma for p in pesi]


def _tabella_pdf(nome, righe, stili, larghezza):
    if not righe:
        return [Paragraph("Nothing found for this section. An empty section is a valid answer: "
                          "it means the code did not show any.", stili["nota"])]
    colonne = _colonne(nome, righe)
    dati = [[Paragraph(_etichetta(nome, c), stili["intestazione"]) for c in colonne]]
    for riga in righe:
        cella = []
        for c in colonne:
            stile = stili["cella_mono"] if _mono(nome, c) else stili["cella"]
            cella.append(Paragraph(_pulisci(_valore(nome, c, riga))[:400] or "&nbsp;", stile))
        dati.append(cella)

    t = Table(dati, colWidths=_larghezze(colonne, larghezza), repeatRows=1)
    t.hAlign = "LEFT"
    stile = [
        ("BACKGROUND", (0, 0), (-1, 0), ACCENTO_CUPO),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, RIGA),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in range(2, len(dati), 2):
        stile.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    for campo in ("severity", "criticality"):
        if campo in colonne:
            j = colonne.index(campo)
            for i, riga in enumerate(righe, start=1):
                fondo, tinta = GRAVITA_COLORI.get(str(riga.get(campo, "")).upper(), (None, None))
                if fondo is not None and fondo != colors.white:
                    stile.append(("BACKGROUND", (j, i), (j, i), fondo))
                    stile.append(("TEXTCOLOR", (j, i), (j, i), tinta))
    if "sme_approved" in colonne:
        j = colonne.index("sme_approved")
        stile.append(("TEXTCOLOR", (j, 1), (j, -1), CONFERMA))
        stile.append(("ALIGN", (j, 0), (j, -1), "CENTER"))
    t.setStyle(TableStyle(stile))
    return [t, Spacer(1, 8)]


def generate_pdf_report(analysis_result: Dict[str, Any], metadata: Dict[str, Any],
                        provider: str = "", model_name: str = "") -> bytes:
    doc_dati = prepara(analysis_result, metadata, provider, model_name)
    stili = _stili()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            leftMargin=28, rightMargin=28, topMargin=30, bottomMargin=36,
                            title=doc_dati["titolo"],
                            author="Legacy Application Knowledge Extractor")
    larghezza = landscape(A4)[0] - 56
    storia: List[Any] = []

    # ── copertina ────────────────────────────────────────────────────────
    storia.append(Paragraph(doc_dati["titolo"], stili["titolone"]))
    storia.append(Paragraph(_pulisci(doc_dati["sottotitolo"][:300]) + "  \u00b7  " + doc_dati["data"],
                            stili["sottotitolone"]))
    meta = [[Paragraph(k, stili["cella"]), Paragraph(_pulisci(v), stili["cella_mono"])]
            for k, v in doc_dati["copertina"]]
    t = Table(meta, colWidths=[larghezza * 0.30, larghezza * 0.24])
    t.hAlign = "LEFT"
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RIGA),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
    ]))
    storia.append(t)
    storia.append(Spacer(1, 14))

    storia.append(Paragraph("How to read this document", stili["h2"]))
    leg = [[Paragraph(f"<b>{k}</b>", stili["cella"]), Paragraph(v, stili["cella"])]
           for k, v in LEGENDA]
    t = Table(leg, colWidths=[larghezza * 0.11, larghezza * 0.61])
    t.hAlign = "LEFT"
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (0, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    storia.append(t)
    storia.append(Spacer(1, 10))
    storia.append(Paragraph(
        "Every row in this document comes from the source code listed above. A blank "
        "confirmation mark does not mean a row is wrong \u2014 it means nobody has checked "
        "it yet.", stili["nota"]))

    storia.append(Spacer(1, 10))
    storia.append(Paragraph("Contents", stili["h2"]))
    storia.append(Paragraph("&nbsp;&nbsp;\u00b7&nbsp;&nbsp;".join(doc_dati["indice"]),
                            stili["nota"]))
    storia.append(PageBreak())

    # ── corpo ────────────────────────────────────────────────────────────
    for blocco in doc_dati["blocchi"]:
        tipo = blocco[0]
        if tipo == "titolo":
            storia.append(Paragraph(_pulisci(blocco[1]), stili["h1"]))
        elif tipo == "sottotitolo":
            storia.append(Paragraph(_pulisci(blocco[1]), stili["h2"]))
        elif tipo == "prosa":
            for paragrafo in str(blocco[1]).split("\n"):
                if paragrafo.strip():
                    storia.append(Paragraph(_pulisci(paragrafo), stili["corpo"]))
        elif tipo == "nota":
            storia.append(Paragraph(_pulisci(blocco[1]), stili["nota"]))
        elif tipo == "elenco":
            for voce in blocco[1]:
                storia.append(Paragraph("\u2014 " + _pulisci(voce), stili["nota"]))
        elif tipo == "coppie":
            t = Table([[Paragraph(_pulisci(k), stili["cella"]),
                        Paragraph(_pulisci(v), stili["cella_mono"])] for k, v in blocco[1]],
                      colWidths=[larghezza * 0.34, larghezza * 0.16])
            t.hAlign = "LEFT"
            t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -2), 0.4, RIGA),
                                   ("LEFTPADDING", (0, 0), (0, -1), 0),
                                   ("TOPPADDING", (0, 0), (-1, -1), 3),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            storia.append(t)
            storia.append(Spacer(1, 8))
        elif tipo == "tabella":
            storia.extend(_tabella_pdf(blocco[1], blocco[2], stili, larghezza))
        elif tipo == "pagina":
            storia.append(PageBreak())
        elif tipo == "diagramma":
            nome, codice, fonte = blocco[1], blocco[2], blocco[3]
            storia.append(Paragraph(nome, stili["h2"]))
            dati = mermaid_render.rendi(codice, nome)
            if dati:
                # Le proporzioni si prendono dal PNG: una misura fissa
                # schiaccerebbe i diagrammi alti in una striscia illeggibile.
                l, a = mermaid_render.misura_per_riquadro(dati, larghezza, 420)
                immagine = Image(io.BytesIO(dati), width=l, height=a)
                immagine.hAlign = "CENTER"
                storia.append(immagine)
                if fonte:
                    storia.append(Paragraph(fonte.capitalize() + ".", stili["nota"]))
            else:
                storia.append(Paragraph("The picture could not be produced here. The diagram "
                                        "source follows.", stili["nota"]))
                storia.append(Paragraph(_pulisci(codice).replace("\n", "<br/>"),
                                        stili["cella_mono"]))
            storia.append(Spacer(1, 12))

    doc.build(storia, onFirstPage=_pie, onLaterPages=_pie)
    return buffer.getvalue()


# =============================================================================
# RESA WORD
# =============================================================================
def _sfondo_cella(cella, esadecimale: str):
    tcPr = cella._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), esadecimale.lstrip("#"))
    tcPr.append(shd)


def _testo_cella(cella, testo: str, grassetto=False, mono=False, bianco=False,
                 colore: Optional[str] = None, misura=7.5):
    cella.text = ""
    par = cella.paragraphs[0]
    par.paragraph_format.space_after = Pt(0)
    run = par.add_run(testo)
    run.font.size = Pt(misura)
    run.font.name = "IBM Plex Mono" if mono else NOME_WORD
    run.font.bold = grassetto
    if bianco:
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    elif colore:
        run.font.color.rgb = RGBColor.from_string(colore.lstrip("#").upper())


def _tabella_word(doc, nome, righe):
    if not righe:
        p = doc.add_paragraph("Nothing found for this section. An empty section is a valid "
                              "answer: it means the code did not show any.")
        p.runs[0].font.size = Pt(8.5)
        p.runs[0].font.color.rgb = RGBColor(0x4A, 0x5A, 0x6B)
        return
    colonne = _colonne(nome, righe)
    tabella = doc.add_table(rows=1, cols=len(colonne))
    tabella.style = "Table Grid"
    tabella.alignment = WD_TABLE_ALIGNMENT.LEFT
    for j, c in enumerate(colonne):
        cella = tabella.rows[0].cells[j]
        _sfondo_cella(cella, "0E434C")
        _testo_cella(cella, _etichetta(nome, c), grassetto=True, bianco=True)
    for i, riga in enumerate(righe):
        celle = tabella.add_row().cells
        for j, c in enumerate(colonne):
            colore = None
            if i % 2 == 1:
                _sfondo_cella(celle[j], "F7F9FB")
            if c in ("severity", "criticality"):
                fondo, tinta = GRAVITA_COLORI.get(str(riga.get(c, "")).upper(), (None, None))
                if fondo is not None and fondo != colors.white:
                    _sfondo_cella(celle[j], fondo.hexval()[2:])
                    colore = tinta.hexval()[2:]
            elif c == "sme_approved" and riga.get("sme_approved"):
                colore = "1F6B45"
            _testo_cella(celle[j], _valore(nome, c, riga)[:400], mono=_mono(nome, c),
                         colore=colore)


def generate_docx_report(analysis_result: Dict[str, Any], metadata: Dict[str, Any],
                         provider: str = "", model_name: str = "") -> bytes:
    _registra_font()
    doc_dati = prepara(analysis_result, metadata, provider, model_name)
    doc = Document()

    normale = doc.styles["Normal"]
    normale.font.name = NOME_WORD
    normale.font.size = Pt(10)
    sezione = doc.sections[0]
    sezione.page_width, sezione.page_height = Inches(11.69), Inches(8.27)
    for lato in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(sezione, lato, Inches(0.6))

    titolo = doc.add_heading(doc_dati["titolo"], level=0)
    for run in titolo.runs:
        run.font.color.rgb = RGBColor(0x17, 0x21, 0x2B)
        run.font.name = NOME_WORD
    p = doc.add_paragraph(doc_dati["sottotitolo"][:300] + "  \u00b7  " + doc_dati["data"])
    p.runs[0].font.color.rgb = RGBColor(0x4A, 0x5A, 0x6B)

    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for k, v in doc_dati["copertina"]:
        celle = t.add_row().cells
        _testo_cella(celle[0], k, misura=9)
        _testo_cella(celle[1], v, mono=True, misura=9)

    doc.add_heading("How to read this document", level=2)
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for k, v in LEGENDA:
        celle = t.add_row().cells
        _testo_cella(celle[0], k, grassetto=True, misura=9)
        _testo_cella(celle[1], v, misura=9)

    doc.add_heading("Contents", level=2)
    for voce in doc_dati["indice"]:
        doc.add_paragraph(voce, style="List Bullet")
    doc.add_page_break()

    for blocco in doc_dati["blocchi"]:
        tipo = blocco[0]
        if tipo == "titolo":
            h = doc.add_heading(blocco[1], level=1)
            for run in h.runs:
                run.font.color.rgb = RGBColor(0x0E, 0x43, 0x4C)
        elif tipo == "sottotitolo":
            doc.add_heading(blocco[1], level=2)
        elif tipo == "prosa":
            for paragrafo in str(blocco[1]).split("\n"):
                if paragrafo.strip():
                    doc.add_paragraph(paragrafo.strip())
        elif tipo == "nota":
            p = doc.add_paragraph(blocco[1])
            p.runs[0].font.size = Pt(8.5)
            p.runs[0].font.color.rgb = RGBColor(0x4A, 0x5A, 0x6B)
        elif tipo == "elenco":
            for voce in blocco[1]:
                doc.add_paragraph(str(voce), style="List Bullet")
        elif tipo == "coppie":
            t = doc.add_table(rows=0, cols=2)
            t.style = "Table Grid"
            for k, v in blocco[1]:
                celle = t.add_row().cells
                _testo_cella(celle[0], k, misura=9)
                _testo_cella(celle[1], v, mono=True, misura=9)
            doc.add_paragraph()
        elif tipo == "tabella":
            _tabella_word(doc, blocco[1], blocco[2])
            doc.add_paragraph()
        elif tipo == "pagina":
            doc.add_page_break()
        elif tipo == "diagramma":
            nome, codice, fonte = blocco[1], blocco[2], blocco[3]
            doc.add_heading(nome, level=2)
            dati = mermaid_render.rendi(codice, nome)
            if dati:
                misura = mermaid_render.dimensioni_png(dati)
                # python-docx calcola l'altezza dalla sola larghezza, quindi le
                # proporzioni sono salve; si passa l'altezza quando il disegno è
                # più alto che largo, altrimenti sfora la pagina.
                if misura and misura[1] / misura[0] > 6.4 / 9.5:
                    doc.add_picture(io.BytesIO(dati), height=Inches(6.4))
                else:
                    doc.add_picture(io.BytesIO(dati), width=Inches(9.5))
                if fonte:
                    p = doc.add_paragraph(fonte.capitalize() + ".")
                    p.runs[0].font.size = Pt(8.5)
                    p.runs[0].font.color.rgb = RGBColor(0x4A, 0x5A, 0x6B)
            else:
                doc.add_paragraph("The picture could not be produced. Diagram source:")
                p = doc.add_paragraph(codice)
                for run in p.runs:
                    run.font.name = "IBM Plex Mono"
                    run.font.size = Pt(8)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
