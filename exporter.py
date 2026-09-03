import io
import html
import base64
import requests
from typing import Dict, Any, List, Optional

# ReportLab (PDF Engine)
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# Python-Docx (Word Engine)
import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.section import WD_SECTION_START, WD_ORIENTATION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls


# =============================================================================
# HELPER: CONVERSIONE MERMAID IN IMMAGINE PNG VIA MERMAID.INK
# =============================================================================
def get_mermaid_image_bytes(mermaid_code: str) -> Optional[bytes]:
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

def set_cell_margins(cell, top=80, bottom=80, left=100, right=100):
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


# =============================================================================
# 1. GENERATORE REPORT PDF (LANDSCAPE / ORIZZONTALE)
# =============================================================================
def generate_pdf_report(analysis_result: Dict[str, Any], metadata: Dict[str, Any], provider: str, model_name: str) -> bytes:
    buffer = io.BytesIO()
    
    # IMPOSTAZIONE PAGINA IN ORIZZONTALE (LANDSCAPE)
    # Larghezza totale: 841.89 pt | Area utile di stampa: 781.89 pt
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
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
        'DocSub', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=11, textColor=colors.HexColor('#718096'), spaceAfter=10
    )
    h2_style = ParagraphStyle(
        'SectionHeader', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor('#1A365D'), spaceBefore=10, spaceAfter=6, keepWithNext=True
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
    t_metrics = Table(metric_data, colWidths=[156, 156, 156, 156, 156])
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
    story.append(Spacer(1, 8))

    # --- OVERVIEW ---
    story.append(Paragraph("1. Executive Summary & Purpose", h2_style))
    story.append(Paragraph(f"<b>Executive Summary:</b> {html.escape(str(analysis_result.get('executive_summary', 'N/A')))}", body_style))
    story.append(Paragraph(f"<b>Application Purpose:</b> {html.escape(str(analysis_result.get('application_purpose', 'N/A')))}", body_style))
    if analysis_result.get('technical_notes'):
        story.append(Paragraph(f"<b>Technical Notes:</b> {html.escape(str(analysis_result.get('technical_notes')))}", body_style))

    # Helper per costruire tabelle PDF dinamiche
    def build_pdf_table(data: List[Dict[str, Any]], columns_config: List[tuple], total_width: int = 780):
        headers = [c[0] for c in columns_config]
        keys = [c[1] for c in columns_config]
        widths = [c[2] for c in columns_config]
        
        table_rows = [[Paragraph(f"<b>{h}</b>", header_cell_style) for h in headers]]
        
        if not data:
            empty_row = [Paragraph("<i>No record extracted</i>", cell_style)] + [Paragraph("", cell_style) for _ in range(len(headers) - 1)]
            table_rows.append(empty_row)
        else:
            for item in data:
                if not isinstance(item, dict):
                    continue
                row_cells = []
                for key in keys:
                    if key == "sme_approved":
                        val_bool = item.get("sme_approved", False)
                        val_str = "<font color='#22543D'><b>APPROVED</b></font>" if val_bool else "<font color='#744210'><b>PENDING</b></font>"
                    else:
                        val_str = html.escape(str(item.get(key, "-")))
                        if key == "severity":
                            sev = val_str.upper()
                            c = {"CRITICAL": "#742A2A", "HIGH": "#744210", "MEDIUM": "#2D3748", "LOW": "#234E52"}.get(sev, "#2D3748")
                            val_str = f"<font color='{c}'><b>{sev}</b></font>"
                    row_cells.append(Paragraph(val_str, cell_style))
                table_rows.append(row_cells)

        t = Table(table_rows, colWidths=widths)
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

    # --- BUSINESS LOGIC ---
    story.append(Paragraph("2. Business Logic", h2_style))
    story.append(Paragraph("<b>Business Processes:</b>", body_style))
    story.append(build_pdf_table(
        analysis_result.get("business_processes", []),
        [("Status", "sme_approved", 55), ("Process ID", "process_id", 65), ("Process Name", "process_name", 140), ("Description", "description", 240), ("Trigger", "trigger", 140), ("Outcome", "outcome", 140)]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Business Rules:</b>", body_style))
    story.append(build_pdf_table(
        analysis_result.get("business_rules", []),
        [("Status", "sme_approved", 55), ("Rule ID", "rule_id", 65), ("Rule Name", "rule_name", 140), ("Condition", "condition", 180), ("Action", "action", 170), ("Business Impact", "business_impact", 170)]
    ))

    # --- ARCHITECTURE ---
    story.append(Paragraph("3. System Architecture", h2_style))
    story.append(Paragraph("<b>Components:</b>", body_style))
    story.append(build_pdf_table(
        analysis_result.get("components", []),
        [("Status", "sme_approved", 60), ("Component Name", "component_name", 220), ("Type", "component_type", 180), ("Source File", "source_file", 320)]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Dependencies:</b>", body_style))
    story.append(build_pdf_table(
        analysis_result.get("dependencies", []),
        [("Status", "sme_approved", 60), ("Source Component", "source", 220), ("Target Entity", "target", 220), ("Type", "dependency_type", 180), ("Confidence", "confidence", 100)]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Interfaces:</b>", body_style))
    story.append(build_pdf_table(
        analysis_result.get("interfaces", []),
        [("Status", "sme_approved", 60), ("Interface Name", "name", 200), ("Type", "interface_type", 140), ("Technology", "technology", 140), ("Source File", "source_file", 240)]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Application Mapping:</b>", body_style))
    story.append(build_pdf_table(
        analysis_result.get("application_mapping", []),
        [("Status", "sme_approved", 60), ("Source Module", "source_module", 200), ("Target Module", "target_module", 200), ("Mapping Type", "mapping_type", 140), ("Notes", "notes", 180)]
    ))

    # --- DATA FLOWS ---
    story.append(Paragraph("4. Data Objects & Data Flows", h2_style))
    story.append(Paragraph("<b>Data Objects:</b>", body_style))
    story.append(build_pdf_table(
        analysis_result.get("data_objects", []),
        [("Status", "sme_approved", 60), ("Object Name", "object_name", 200), ("Type", "object_type", 140), ("Operation", "operation", 140), ("Source File", "source_file", 240)]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Data Flows:</b>", body_style))
    story.append(build_pdf_table(
        analysis_result.get("data_flows", []),
        [("Status", "sme_approved", 60), ("Flow Name", "flow_name", 160), ("From Component", "source_component", 180), ("To Component", "target_component", 180), ("Data Transferred", "data_description", 200)]
    ))

    # --- RISKS & IMPACT ---
    story.append(Paragraph("5. Technical Risks & Impact Analysis", h2_style))
    story.append(Paragraph("<b>Technical Risks:</b>", body_style))
    story.append(build_pdf_table(
        analysis_result.get("technical_risks", []),
        [("Status", "sme_approved", 55), ("Risk ID", "risk_id", 60), ("Severity", "severity", 65), ("Risk Type", "risk_type", 150), ("Affected Component", "affected_component", 180), ("Recommendation", "recommendation", 270)]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Impact Analysis:</b>", body_style))
    story.append(build_pdf_table(
        analysis_result.get("impact_analysis", []),
        [("Status", "sme_approved", 60), ("Target Component", "component", 180), ("Impact Level", "impact_level", 90), ("Description", "description", 240), ("Mitigation Strategy", "mitigation", 210)]
    ))

    # --- DIAGRAMS ---
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
                story.append(Image(img_buf, width=720, height=260))
            else:
                story.append(Paragraph(f"<font fontName='Courier' size=6.5>{html.escape(str(diag_code))}</font>", body_style))
            story.append(Spacer(1, 10))

    # --- STATIC EVIDENCE ---
    story.append(Paragraph("7. Static Code Evidence", h2_style))
    sql_tables = metadata.get("detected_tables", [])
    if sql_tables:
        story.append(Paragraph(f"<b>SQL Tables Extracted:</b> {html.escape(', '.join(sql_tables))}", body_style))

    files_list = metadata.get("files", [])
    if files_list:
        file_summary = ", ".join([f"{f.get('filename')} ({f.get('line_count')} LOC)" for f in files_list])
        story.append(Paragraph(f"<b>Files Breakdown:</b> {html.escape(file_summary)}", body_style))

    doc.build(story)
    return buffer.getvalue()


# =============================================================================
# 2. GENERATORE REPORT WORD (.DOCX) - IN ORIZZONTALE (LANDSCAPE)
# =============================================================================
def generate_docx_report(analysis_result: Dict[str, Any], metadata: Dict[str, Any], provider: str, model_name: str) -> bytes:
    doc = Document()
    
    # Impostazione Orientamento Landscape in Word
    section = doc.sections[0]
    section.orientation = WD_ORIENTATION.LANDSCAPE
    section.page_width = Inches(11.69)
    section.page_height = Inches(8.27)
    section.top_margin = Inches(0.6)
    section.bottom_margin = Inches(0.6)
    section.left_margin = Inches(0.6)
    section.right_margin = Inches(0.6)
        
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Arial'
    font.size = Pt(8.5)
    font.color.rgb = RGBColor(45, 55, 72)

    # Header Documento
    title_p = doc.add_paragraph()
    r_title = title_p.add_run("Legacy Application Knowledge Extraction")
    r_title.bold = True
    r_title.font.size = Pt(16)
    r_title.font.color.rgb = RGBColor(26, 54, 93)
    
    sub_p = doc.add_paragraph()
    sub_p.paragraph_format.space_after = Pt(8)
    r_sub = sub_p.add_run(f"Reverse Engineering Complete Report | Provider: {provider} ({model_name}) | Files: {metadata.get('file_count', 0)}")
    r_sub.font.size = Pt(8)
    r_sub.font.color.rgb = RGBColor(113, 128, 150)

    # 1. Overview
    h1 = doc.add_heading(level=1)
    h1.add_run("1. Executive Summary & Application Purpose").font.color.rgb = RGBColor(26, 54, 93)
    
    p_exec = doc.add_paragraph()
    p_exec.add_run("Executive Summary: ").bold = True
    p_exec.add_run(str(analysis_result.get("executive_summary", "N/A")))
    
    p_purp = doc.add_paragraph()
    p_purp.add_run("Application Purpose: ").bold = True
    p_purp.add_run(str(analysis_result.get("application_purpose", "N/A")))

    # Helper Tabelle Word dinamiche
    def create_docx_table(data: List[Dict[str, Any]], columns_config: List[tuple]):
        headers = [c[0] for c in columns_config]
        keys = [c[1] for c in columns_config]
        
        table = doc.add_table(rows=1, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True
        
        hdr_cells = table.rows[0].cells
        for i, h_text in enumerate(headers):
            hdr_cells[i].text = h_text
            set_cell_background(hdr_cells[i], "2D3748")
            set_cell_margins(hdr_cells[i], top=60, bottom=60, left=80, right=80)
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
            for i, key in enumerate(keys):
                if key == "sme_approved":
                    val = "Approved" if item.get("sme_approved", False) else "Pending"
                else:
                    val = str(item.get(key, "-"))
                
                row_cells[i].text = val
                set_cell_margins(row_cells[i], top=50, bottom=50, left=60, right=60)
                p = row_cells[i].paragraphs[0]
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.space_before = Pt(0)
                
                for run in p.runs:
                    run.font.size = Pt(7.5)
                    if key == "sme_approved":
                        run.font.bold = True
                        run.font.color.rgb = RGBColor(34, 84, 61) if val == "Approved" else RGBColor(116, 66, 16)
        doc.add_paragraph()

    # 2. Business Logic
    h2 = doc.add_heading(level=1)
    h2.add_run("2. Business Logic").font.color.rgb = RGBColor(26, 54, 93)
    doc.add_paragraph("Business Processes:").runs[0].bold = True
    create_docx_table(
        analysis_result.get("business_processes", []),
        [("Status", "sme_approved"), ("Process ID", "process_id"), ("Process Name", "process_name"), ("Description", "description"), ("Trigger", "trigger"), ("Outcome", "outcome")]
    )
    doc.add_paragraph("Business Rules:").runs[0].bold = True
    create_docx_table(
        analysis_result.get("business_rules", []),
        [("Status", "sme_approved"), ("Rule ID", "rule_id"), ("Rule Name", "rule_name"), ("Condition", "condition"), ("Action", "action"), ("Business Impact", "business_impact")]
    )

    # 3. Architecture
    h3 = doc.add_heading(level=1)
    h3.add_run("3. System Architecture").font.color.rgb = RGBColor(26, 54, 93)
    doc.add_paragraph("Components:").runs[0].bold = True
    create_docx_table(
        analysis_result.get("components", []),
        [("Status", "sme_approved"), ("Component Name", "component_name"), ("Type", "component_type"), ("Source File", "source_file")]
    )
    doc.add_paragraph("Dependencies:").runs[0].bold = True
    create_docx_table(
        analysis_result.get("dependencies", []),
        [("Status", "sme_approved"), ("Source Component", "source"), ("Target Entity", "target"), ("Type", "dependency_type"), ("Confidence", "confidence")]
    )
    doc.add_paragraph("Interfaces:").runs[0].bold = True
    create_docx_table(
        analysis_result.get("interfaces", []),
        [("Status", "sme_approved"), ("Interface Name", "name"), ("Type", "interface_type"), ("Technology", "technology"), ("Source File", "source_file")]
    )
    doc.add_paragraph("Application Mapping:").runs[0].bold = True
    create_docx_table(
        analysis_result.get("application_mapping", []),
        [("Status", "sme_approved"), ("Source Module", "source_module"), ("Target Module", "target_module"), ("Mapping Type", "mapping_type"), ("Notes", "notes")]
    )

    # 4. Data Flows
    h4 = doc.add_heading(level=1)
    h4.add_run("4. Data Objects & Data Flows").font.color.rgb = RGBColor(26, 54, 93)
    doc.add_paragraph("Data Objects:").runs[0].bold = True
    create_docx_table(
        analysis_result.get("data_objects", []),
        [("Status", "sme_approved"), ("Object Name", "object_name"), ("Type", "object_type"), ("Operation", "operation"), ("Source File", "source_file")]
    )
    doc.add_paragraph("Data Flows:").runs[0].bold = True
    create_docx_table(
        analysis_result.get("data_flows", []),
        [("Status", "sme_approved"), ("Flow Name", "flow_name"), ("From Component", "source_component"), ("To Component", "target_component"), ("Data Transferred", "data_description")]
    )

    # 5. Risks & Impact
    h5 = doc.add_heading(level=1)
    h5.add_run("5. Technical Risks & Impact Analysis").font.color.rgb = RGBColor(26, 54, 93)
    doc.add_paragraph("Technical Risks:").runs[0].bold = True
    create_docx_table(
        analysis_result.get("technical_risks", []),
        [("Status", "sme_approved"), ("Risk ID", "risk_id"), ("Severity", "severity"), ("Risk Type", "risk_type"), ("Affected Component", "affected_component"), ("Recommendation", "recommendation")]
    )
    doc.add_paragraph("Impact Analysis:").runs[0].bold = True
    create_docx_table(
        analysis_result.get("impact_analysis", []),
        [("Status", "sme_approved"), ("Target Component", "component"), ("Impact Level", "impact_level"), ("Description", "description"), ("Mitigation Strategy", "mitigation")]
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
                doc.add_picture(img_buf, width=Inches(9.5))
            else:
                p_code = doc.add_paragraph(str(diag_code))
                p_code.style.font.name = 'Courier New'
                p_code.style.font.size = Pt(7)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
