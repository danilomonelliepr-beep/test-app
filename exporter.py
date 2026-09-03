import io
import html
import base64
import requests
from typing import Dict, Any, List, Optional

# ReportLab (PDF Engine)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# Python-Docx (Word Engine)
import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls


# =============================================================================
# HELPER: CONVERSIONE MERMAID IN IMMAGINE PNG VIA MERMAID.INK
# =============================================================================
def get_mermaid_image_bytes(mermaid_code: str) -> Optional[bytes]:
    """Converte codice Mermaid in immagine PNG usando il servizio gratuito mermaid.ink."""
    if not mermaid_code or not str(mermaid_code).strip():
        return None
    try:
        clean_code = str(mermaid_code).strip()
        graph_bytes = clean_code.encode('utf-8')
        base64_bytes = base64.b64encode(graph_bytes)
        base64_string = base64_bytes.decode('utf-8')
        
        url = f"https://mermaid.ink/img/{base64_string}"
        response = requests.get(url, timeout=8)
        if response.status_code == 200 and len(response.content) > 100:
            return response.content
    except Exception:
        pass
    return None


# =============================================================================
# HELPERS PER STILIZZAZIONE DOCX
# =============================================================================
def set_cell_background(cell, hex_color: str):
    tcPr = cell._element.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=120, right=120):
    tcPr = cell._element.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)

def add_docx_callout(doc: Document, title: str, text: str):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = table.cell(0, 0)
    cell.width = Inches(6.5)
    set_cell_background(cell, "F7FAFC")
    set_cell_margins(cell, top=140, bottom=140, left=180, right=180)
    
    tcPr = cell._element.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:left w:val="single" w:sz="24" w:space="0" w:color="1A365D"/>'
        f'<w:top w:val="none"/><w:right w:val="none"/><w:bottom w:val="none"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(2)
    
    r_title = p.add_run(f"{title}\n")
    r_title.bold = True
    r_title.font.size = Pt(9.5)
    r_title.font.color.rgb = RGBColor(26, 54, 93)
    
    r_text = p.add_run(text if text else "N/A")
    r_text.font.size = Pt(9)
    r_text.font.color.rgb = RGBColor(45, 55, 72)
    doc.add_paragraph()


# =============================================================================
# 1. GENERATORE REPORT PDF (REPORTLAB)
# =============================================================================
def generate_pdf_report(analysis_result: Dict[str, Any], metadata: Dict[str, Any], provider: str, model_name: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30
    )
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor('#1A365D'), spaceAfter=4
    )
    sub_style = ParagraphStyle(
        'DocSub', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=11, textColor=colors.HexColor('#718096'), spaceAfter=12
    )
    h2_style = ParagraphStyle(
        'SectionHeader', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor('#1A365D'), spaceBefore=12, spaceAfter=6, keepWithNext=True
    )
    body_style = ParagraphStyle(
        'BodyTextCustom', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor('#2D3748'), spaceAfter=6
    )
    cell_style = ParagraphStyle(
        'TableCell', parent=styles['Normal'], fontName='Helvetica', fontSize=7, leading=9, textColor=colors.HexColor('#2D3748')
    )
    header_cell_style = ParagraphStyle(
        'HeaderTableCell', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7, leading=9, textColor=colors.white
    )

    story = []

    # --- HEADER DOCUMENTO ---
    story.append(Paragraph("Legacy Application Knowledge Extraction", title_style))
    story.append(Paragraph(
        f"Reverse Engineering Complete Report &nbsp;|&nbsp; Provider: <b>{html.escape(str(provider))}</b> ({html.escape(str(model_name))}) &nbsp;|&nbsp; Files Analyzed: <b>{metadata.get('file_count', 0)}</b>",
        sub_style
    ))

    # --- TABELLA METRICHE SUMMARY ---
    metric_data = [
        [
            Paragraph(f"<b>{metadata.get('file_count', 0)}</b><br/><font size=5.5 color='#718096'>FILES</font>", cell_style),
            Paragraph(f"<b>{metadata.get('total_line_count', 0):,}</b><br/><font size=5.5 color='#718096'>LOC</font>", cell_style),
            Paragraph(f"<b>{len(analysis_result.get('components', []))}</b><br/><font size=5.5 color='#718096'>COMPONENTS</font>", cell_style),
            Paragraph(f"<b>{len(analysis_result.get('business_rules', []))}</b><br/><font size=5.5 color='#718096'>RULES</font>", cell_style),
            Paragraph(f"<b>{len(analysis_result.get('technical_risks', []))}</b><br/><font size=5.5 color='#718096'>RISKS</font>", cell_style)
        ]
    ]
    t_metrics = Table(metric_data, colWidths=[107, 107, 107, 107, 107])
    t_metrics.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F7FAFC')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_metrics)
    story.append(Spacer(1, 10))

    # --- TAB 1: OVERVIEW ---
    story.append(Paragraph("1. Executive Summary & Purpose", h2_style))
    story.append(Paragraph(f"<b>Executive Summary:</b> {html.escape(analysis_result.get('executive_summary', 'N/A'))}", body_style))
    story.append(Paragraph(f"<b>Application Purpose:</b> {html.escape(analysis_result.get('application_purpose', 'N/A'))}", body_style))
    if analysis_result.get('technical_notes'):
        story.append(Paragraph(f"<b>Technical Notes:</b> {html.escape(analysis_result.get('technical_notes'))}", body_style))

    # Helper Generico per Tabelle Dinamiche
    def build_pdf_table(headers: List[str], data: List[Dict[str, Any]], keys: List[str], col_widths: List[int]):
        table_rows = [[Paragraph(f"<b>{h}</b>", header_cell_style) for h in headers]]
        
        if not data:
            empty_row = [Paragraph("<i>No record extracted</i>", cell_style)] + [Paragraph("", cell_style) for _ in range(len(headers) - 1)]
            table_rows.append(empty_row)
        else:
            for item in data:
                if not isinstance(item, dict):
                    continue
                row_cells = []
                sme_approved = item.get("sme_approved", False)
                status_str = "<font color='#22543D'><b>APPROVED</b></font>" if sme_approved else "<font color='#744210'><b>PENDING</b></font>"
                row_cells.append(Paragraph(status_str, cell_style))
                
                for key in keys[1:]:
                    val = html.escape(str(item.get(key, "-")))
                    if key == "severity":
                        sev = val.upper()
                        c = {"CRITICAL": "#742A2A", "HIGH": "#744210", "MEDIUM": "#2D3748", "LOW": "#234E52"}.get(sev, "#2D3748")
                        val = f"<font color='{c}'><b>{sev}</b></font>"
                    row_cells.append(Paragraph(val, cell_style))
                table_rows.append(row_cells)

        t = Table(table_rows, colWidths=col_widths)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2D3748')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E0')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ]))
        return t

    # --- TAB 2: BUSINESS LOGIC ---
    story.append(Paragraph("2. Business Logic", h2_style))
    story.append(Paragraph("<b>Business Processes:</b>", body_style))
    story.append(build_pdf_table(
        ["Status", "ID", "Process Name", "Description", "Trigger", "Outcome"],
        analysis_result.get("business_processes", []),
        ["sme_approved", "process_id", "process_name", "description", "trigger", "outcome"],
        [45, 45, 90, 165, 95, 95]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Business Rules:</b>", body_style))
    story.append(build_pdf_table(
        ["Status", "Rule ID", "Rule Name", "Condition", "Action", "Business Impact"],
        analysis_result.get("business_rules", []),
        ["sme_approved", "rule_id", "rule_name", "condition", "action", "business_impact"],
        [45, 45, 90, 120, 120, 115]
    ))

    # --- TAB 3: ARCHITECTURE ---
    story.append(Paragraph("3. System Architecture", h2_style))
    story.append(Paragraph("<b>Components:</b>", body_style))
    story.append(build_pdf_table(
        ["Status", "Component Name", "Type", "Source File"],
        analysis_result.get("components", []),
        ["sme_approved", "component_name", "component_type", "source_file"],
        [50, 180, 120, 185]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Dependencies:</b>", body_style))
    story.append(build_pdf_table(
        ["Status", "Source Component", "Target Entity", "Type", "Confidence"],
        analysis_result.get("dependencies", []),
        ["sme_approved", "source", "target", "dependency_type", "confidence"],
        [50, 150, 150, 110, 75]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Interfaces:</b>", body_style))
    story.append(build_pdf_table(
        ["Status", "Interface Name", "Type", "Technology", "Source File"],
        analysis_result.get("interfaces", []),
        ["sme_approved", "name", "interface_type", "technology", "source_file"],
        [50, 150, 110, 95, 130]
    ))

    # --- TAB 4: DATA FLOWS ---
    story.append(Paragraph("4. Data Objects & Data Flows", h2_style))
    story.append(Paragraph("<b>Data Objects:</b>", body_style))
    story.append(build_pdf_table(
        ["Status", "Object Name", "Type", "Operation", "Source File"],
        analysis_result.get("data_objects", []),
        ["sme_approved", "object_name", "object_type", "operation", "source_file"],
        [50, 150, 110, 85, 140]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Data Flows:</b>", body_style))
    story.append(build_pdf_table(
        ["Status", "Flow Name", "From Component", "To Component", "Data Transferred"],
        analysis_result.get("data_flows", []),
        ["sme_approved", "flow_name", "source_component", "target_component", "data_description"],
        [50, 110, 125, 125, 125]
    ))

    # --- TAB 5: RISKS & IMPACT ---
    story.append(Paragraph("5. Risks, Impact & Assumptions", h2_style))
    story.append(Paragraph("<b>Technical Risks:</b>", body_style))
    story.append(build_pdf_table(
        ["Status", "Risk ID", "Severity", "Risk Type", "Affected Component", "Recommendation"],
        analysis_result.get("technical_risks", []),
        ["sme_approved", "risk_id", "severity", "risk_type", "affected_component", "recommendation"],
        [45, 45, 50, 105, 115, 175]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Impact Analysis:</b>", body_style))
    story.append(build_pdf_table(
        ["Status", "Target Component", "Impact Level", "Description", "Mitigation"],
        analysis_result.get("impact_analysis", []),
        ["sme_approved", "component", "impact_level", "description", "mitigation"],
        [50, 125, 65, 155, 140]
    ))
    
    # Questions & Assumptions
    val_q = analysis_result.get("validation_questions", [])
    if val_q:
        story.append(Spacer(1, 4))
        story.append(Paragraph("<b>Open Validation Questions for SME:</b>", body_style))
        for q in val_q:
            story.append(Paragraph(f"• {html.escape(str(q))}", body_style))

    assump = analysis_result.get("assumptions", [])
    if assump:
        story.append(Spacer(1, 4))
        story.append(Paragraph("<b>AI Analysis Assumptions:</b>", body_style))
        for a in assump:
            story.append(Paragraph(f"• {html.escape(str(a))}", body_style))

    # --- TAB 6: DIAGRAMS (CONVERTITI IN PNG) ---
    story.append(PageBreak())
    story.append(Paragraph("6. Architecture & Process Diagrams", h2_style))
    
    diagrams_map = [
        ("Process Flow Diagram", analysis_result.get("mermaid_process_flow")),
        ("Application Mapping Diagram", analysis_result.get("mermaid_application_map")),
        ("Data Flow Diagram", analysis_result.get("mermaid_data_flow")),
        ("Call Graph Diagram", analysis_result.get("mermaid_call_graph"))
    ]

    for diag_title, diag_code in diagrams_map:
        if diag_code and str(diag_code).strip():
            story.append(Paragraph(f"<b>{diag_title}</b>", body_style))
            img_bytes = get_mermaid_image_bytes(diag_code)
            if img_bytes:
                img_buf = io.BytesIO(img_bytes)
                story.append(Image(img_buf, width=470, height=220))
            else:
                story.append(Paragraph(f"<font fontName='Courier' size=6.5>{html.escape(str(diag_code))}</font>", body_style))
            story.append(Spacer(1, 10))

    # --- TAB 7: STATIC EVIDENCE ---
    story.append(Paragraph("7. Static Code Evidence", h2_style))
    sql_tables = metadata.get("detected_tables", [])
    if sql_tables:
        story.append(Paragraph(f"<b>SQL Tables Extracted via Static Analysis:</b> {html.escape(', '.join(sql_tables))}", body_style))

    files_list = metadata.get("files", [])
    if files_list:
        file_summary = ", ".join([f"{f.get('filename')} ({f.get('line_count')} LOC)" for f in files_list])
        story.append(Paragraph(f"<b>Source Code Files Breakdown:</b> {html.escape(file_summary)}", body_style))

    doc.build(story)
    return buffer.getvalue()


# =============================================================================
# 2. GENERATORE REPORT WORD (.DOCX)
# =============================================================================
def generate_docx_report(analysis_result: Dict[str, Any], metadata: Dict[str, Any], provider: str, model_name: str) -> bytes:
    doc = Document()
    
    for section in doc.sections:
        section.top_margin = Inches(0.7)
        section.bottom_margin = Inches(0.7)
        section.left_margin = Inches(0.7)
        section.right_margin = Inches(0.7)
        
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Arial'
    font.size = Pt(9)
    font.color.rgb = RGBColor(45, 55, 72)

    # Header
    title_p = doc.add_paragraph()
    r_title = title_p.add_run("Legacy Application Knowledge Extraction")
    r_title.bold = True
    r_title.font.size = Pt(18)
    r_title.font.color.rgb = RGBColor(26, 54, 93)
    
    sub_p = doc.add_paragraph()
    sub_p.paragraph_format.space_after = Pt(10)
    r_sub = sub_p.add_run(f"Reverse Engineering Complete Report | Provider: {provider} ({model_name}) | Files: {metadata.get('file_count', 0)}")
    r_sub.font.size = Pt(8.5)
    r_sub.font.color.rgb = RGBColor(113, 128, 150)

    # 1. Overview
    h1 = doc.add_heading(level=1)
    h1.add_run("1. Executive Summary & Application Purpose").font.color.rgb = RGBColor(26, 54, 93)
    add_docx_callout(doc, "Executive Summary", analysis_result.get("executive_summary", "N/A"))
    add_docx_callout(doc, "Application Purpose", analysis_result.get("application_purpose", "N/A"))

    # Helper Tabelle Word
    def create_docx_table(headers: List[str], data: List[Dict[str, Any]], keys: List[str]):
        table = doc.add_table(rows=1, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True
        
        hdr_cells = table.rows[0].cells
        for i, h_text in enumerate(headers):
            hdr_cells[i].text = h_text
            set_cell_background(hdr_cells[i], "2D3748")
            set_cell_margins(hdr_cells[i], top=80, bottom=80, left=100, right=100)
            p = hdr_cells[i].paragraphs[0]
            for run in p.runs:
                run.font.bold = True
                run.font.size = Pt(8)
                run.font.color.rgb = RGBColor(255, 255, 255)
        
        if not data:
            row_cells = table.add_row().cells
            row_cells[0].text = "No records extracted"
            return

        for item in data:
            if not isinstance(item, dict):
                continue
            row_cells = table.add_row().cells
            sme = "Approved" if item.get("sme_approved", False) else "Pending"
            row_values = [sme] + [str(item.get(k, "-")) for k in keys[1:]]
            
            for i, val in enumerate(row_values):
                row_cells[i].text = val
                set_cell_margins(row_cells[i], top=60, bottom=60, left=80, right=80)
                p = row_cells[i].paragraphs[0]
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.space_before = Pt(0)
                
                for run in p.runs:
                    run.font.size = Pt(7.5)
                    if i == 0:
                        run.font.bold = True
                        run.font.color.rgb = RGBColor(34, 84, 61) if sme == "Approved" else RGBColor(116, 66, 16)
        doc.add_paragraph()

    # 2. Business Logic
    h2 = doc.add_heading(level=1)
    h2.add_run("2. Business Logic").font.color.rgb = RGBColor(26, 54, 93)
    doc.add_paragraph("Business Processes:").runs[0].bold = True
    create_docx_table(
        ["Status", "ID", "Process Name", "Description", "Trigger", "Outcome"],
        analysis_result.get("business_processes", []),
        ["sme_approved", "process_id", "process_name", "description", "trigger", "outcome"]
    )
    doc.add_paragraph("Business Rules:").runs[0].bold = True
    create_docx_table(
        ["Status", "Rule ID", "Rule Name", "Condition", "Action", "Business Impact"],
        analysis_result.get("business_rules", []),
        ["sme_approved", "rule_id", "rule_name", "condition", "action", "business_impact"]
    )

    # 3. Architecture
    h3 = doc.add_heading(level=1)
    h3.add_run("3. System Architecture").font.color.rgb = RGBColor(26, 54, 93)
    create_docx_table(
        ["Status", "Component Name", "Type", "Source File"],
        analysis_result.get("components", []),
        ["sme_approved", "component_name", "component_type", "source_file"]
    )
    create_docx_table(
        ["Status", "Source Component", "Target Entity", "Type", "Confidence"],
        analysis_result.get("dependencies", []),
        ["sme_approved", "source", "target", "dependency_type", "confidence"]
    )

    # 4. Data Flows
    h4 = doc.add_heading(level=1)
    h4.add_run("4. Data Objects & Data Flows").font.color.rgb = RGBColor(26, 54, 93)
    doc.add_paragraph("Data Objects:").runs[0].bold = True
    create_docx_table(
        ["Status", "Object Name", "Type", "Operation", "Source File"],
        analysis_result.get("data_objects", []),
        ["sme_approved", "object_name", "object_type", "operation", "source_file"]
    )
    doc.add_paragraph("Data Flows:").runs[0].bold = True
    create_docx_table(
        ["Status", "Flow Name", "From Component", "To Component", "Data Transferred"],
        analysis_result.get("data_flows", []),
        ["sme_approved", "flow_name", "source_component", "target_component", "data_description"]
    )

    # 5. Risks
    h5 = doc.add_heading(level=1)
    h5.add_run("5. Technical Risks & Impact").font.color.rgb = RGBColor(26, 54, 93)
    create_docx_table(
        ["Status", "Risk ID", "Severity", "Risk Type", "Affected Component", "Recommendation"],
        analysis_result.get("technical_risks", []),
        ["sme_approved", "risk_id", "severity", "risk_type", "affected_component", "recommendation"]
    )

    # 6. Diagrams
    h6 = doc.add_heading(level=1)
    h6.add_run("6. Architecture & Process Diagrams").font.color.rgb = RGBColor(26, 54, 93)
    diagrams_map = [
        ("Process Flow Diagram", analysis_result.get("mermaid_process_flow")),
        ("Application Mapping Diagram", analysis_result.get("mermaid_application_map")),
        ("Data Flow Diagram", analysis_result.get("mermaid_data_flow")),
        ("Call Graph Diagram", analysis_result.get("mermaid_call_graph"))
    ]
    for diag_title, diag_code in diagrams_map:
        if diag_code and str(diag_code).strip():
            doc.add_paragraph(diag_title).runs[0].bold = True
            img_bytes = get_mermaid_image_bytes(diag_code)
            if img_bytes:
                img_buf = io.BytesIO(img_bytes)
                doc.add_picture(img_buf, width=Inches(6.0))
            else:
                p_code = doc.add_paragraph(str(diag_code))
                p_code.style.font.name = 'Courier New'
                p_code.style.font.size = Pt(7.5)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
