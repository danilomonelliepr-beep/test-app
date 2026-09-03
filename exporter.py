import io
import html
import base64
import requests
from typing import Dict, Any, List, Optional

# ReportLab (Engine PDF 100% Python)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# Python-Docx (Engine Word)
import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls


# =============================================================================
# HELPER: MERMAID CODE TO PNG BYTES
# =============================================================================
def get_mermaid_image_bytes(mermaid_code: str) -> Optional[bytes]:
    """Converte una stringa di codice Mermaid in un'immagine PNG tramite l'API mermaid.ink."""
    if not mermaid_code or not mermaid_code.strip():
        return None
    try:
        graph_bytes = mermaid_code.strip().encode('utf-8')
        base64_bytes = base64.b64encode(graph_bytes)
        base64_string = base64_bytes.decode('utf-8')
        
        url = f"https://mermaid.ink/img/{base64_string}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.content
    except Exception:
        pass
    return None


# =============================================================================
# HELPERS FOR DOCX STYLING
# =============================================================================
def set_cell_background(cell, hex_color: str):
    tcPr = cell._element.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
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

def add_callout_box(doc: Document, title: str, text: str):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    
    cell = table.cell(0, 0)
    cell.width = Inches(6.5)
    set_cell_background(cell, "EBF8FF")
    set_cell_margins(cell, top=140, bottom=140, left=200, right=200)
    
    tcPr = cell._element.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:left w:val="single" w:sz="24" w:space="0" w:color="3182CE"/>'
        f'<w:top w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'<w:bottom w:val="none"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(2)
    
    run_title = p.add_run(f"{title.upper()}\n")
    run_title.bold = True
    run_title.font.size = Pt(9.5)
    run_title.font.color.rgb = RGBColor(43, 108, 176)
    
    run_text = p.add_run(text)
    run_text.font.size = Pt(9.5)
    run_text.font.color.rgb = RGBColor(45, 55, 72)
    
    doc.add_paragraph()


# =============================================================================
# 1. EXPORT TO PDF (REPORTLAB)
# =============================================================================
def generate_pdf_report(analysis_result: Dict[str, Any], metadata: Dict[str, Any], provider: str, model_name: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor('#1A365D'), spaceAfter=4
    )
    sub_style = ParagraphStyle(
        'DocSub', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=12, textColor=colors.HexColor('#718096'), spaceAfter=14
    )
    h2_style = ParagraphStyle(
        'SectionHeader', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor('#1A365D'), spaceBefore=14, spaceAfter=6, keepWithNext=True
    )
    body_style = ParagraphStyle(
        'BodyTextCustom', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=11.5, textColor=colors.HexColor('#2D3748'), spaceAfter=8
    )
    cell_style = ParagraphStyle(
        'TableCell', parent=styles['Normal'], fontName='Helvetica', fontSize=7.5, leading=9.5, textColor=colors.HexColor('#2D3748')
    )
    header_cell_style = ParagraphStyle(
        'HeaderTableCell', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7.5, leading=9.5, textColor=colors.white
    )

    story = []

    # Header
    story.append(Paragraph("Legacy System Knowledge Extraction", title_style))
    story.append(Paragraph(
        f"Reverse Engineering Report &nbsp;|&nbsp; Provider: <b>{html.escape(provider)}</b> ({html.escape(model_name)}) &nbsp;|&nbsp; Files: <b>{metadata.get('file_count', 0)}</b>",
        sub_style
    ))

    # Metric Table Summary
    metric_data = [
        [
            Paragraph(f"<b>{metadata.get('file_count', 0)}</b><br/><font size=6 color='#718096'>FILES</font>", cell_style),
            Paragraph(f"<b>{metadata.get('total_line_count', 0):,}</b><br/><font size=6 color='#718096'>LOC</font>", cell_style),
            Paragraph(f"<b>{len(analysis_result.get('components', []))}</b><br/><font size=6 color='#718096'>COMPONENTS</font>", cell_style),
            Paragraph(f"<b>{len(analysis_result.get('technical_risks', []))}</b><br/><font size=6 color='#718096'>RISKS</font>", cell_style)
        ]
    ]
    t_metrics = Table(metric_data, colWidths=[130, 130, 130, 130])
    t_metrics.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F7FAFC')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E0')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t_metrics)
    story.append(Spacer(1, 10))

    # 1. Executive Summary & Purpose
    story.append(Paragraph("1. Executive Summary & Application Purpose", h2_style))
    story.append(Paragraph(f"<b>Core Purpose:</b> {html.escape(analysis_result.get('application_purpose', 'N/A'))}", body_style))
    story.append(Paragraph(html.escape(analysis_result.get('executive_summary', 'N/A')), body_style))

    # Helper Tabelle PDF
    def build_pdf_table(headers: List[str], data: List[Dict[str, Any]], keys: List[str], col_widths: List[int]):
        table_rows = [[Paragraph(f"<b>{h}</b>", header_cell_style) for h in headers]]
        
        if not data:
            empty_row = [Paragraph("<i>No data recorded</i>", cell_style)] + [Paragraph("", cell_style) for _ in range(len(headers) - 1)]
            table_rows.append(empty_row)
        else:
            for item in data:
                row_cells = []
                sme_approved = item.get("sme_approved", False)
                status_str = "<font color='#22543D'><b>APPROVED</b></font>" if sme_approved else "<font color='#744210'><b>PENDING</b></font>"
                row_cells.append(Paragraph(status_str, cell_style))
                
                for key in keys[1:]:
                    val = html.escape(str(item.get(key, "")))
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
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        return t

    # 2. Business Rules
    story.append(Paragraph("2. SME Validated Business Rules", h2_style))
    story.append(build_pdf_table(
        ["Status", "Rule ID", "Rule Name", "Condition / Action", "Impact"],
        analysis_result.get("business_rules", []),
        ["sme_approved", "rule_id", "rule_name", "condition", "business_impact"],
        [55, 50, 110, 175, 130]
    ))

    # 3. Components
    story.append(Paragraph("3. System Components Architecture", h2_style))
    story.append(build_pdf_table(
        ["Status", "Component Name", "Type", "Source File"],
        analysis_result.get("components", []),
        ["sme_approved", "component_name", "component_type", "source_file"],
        [55, 160, 110, 195]
    ))

    # 4. Dependencies & Data Flow
    story.append(Paragraph("4. Dependencies & Data Flow", h2_style))
    story.append(build_pdf_table(
        ["Status", "Target / Entity", "Access Type", "Component Source"],
        analysis_result.get("dependencies", []),
        ["sme_approved", "target_entity", "access_type", "source_component"],
        [55, 170, 100, 195]
    ))

    # 5. Technical Risks
    story.append(Paragraph("5. Technical Risks & Vulnerabilities", h2_style))
    story.append(build_pdf_table(
        ["Status", "Risk ID", "Severity", "Description", "Recommendation"],
        analysis_result.get("technical_risks", []),
        ["sme_approved", "risk_id", "severity", "description", "recommendation"],
        [55, 50, 55, 180, 180]
    ))

    # 6. Mermaid Diagrams Rendering
    mermaid_code = analysis_result.get("mermaid_diagram") or analysis_result.get("architecture_diagram")
    if mermaid_code:
        story.append(Paragraph("6. Architecture & Data Flow Diagram", h2_style))
        img_data = get_mermaid_image_bytes(mermaid_code)
        if img_data:
            img_buffer = io.BytesIO(img_data)
            story.append(Image(img_buffer, width=480, height=260))
        else:
            # Fallback se l'API non risponde: stampa il codice sintattico
            story.append(Paragraph(f"<font fontName='Courier' size=7>{html.escape(mermaid_code)}</font>", body_style))

    doc.build(story)
    return buffer.getvalue()


# =============================================================================
# 2. EXPORT TO WORD (.DOCX)
# =============================================================================
def generate_docx_report(analysis_result: Dict[str, Any], metadata: Dict[str, Any], provider: str, model_name: str) -> bytes:
    doc = Document()
    
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)
        
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Arial'
    font.size = Pt(9.5)
    font.color.rgb = RGBColor(45, 55, 72)
    
    # Title
    title_p = doc.add_paragraph()
    run_title = title_p.add_run("Legacy Application Knowledge Extraction")
    run_title.bold = True
    run_title.font.size = Pt(18)
    run_title.font.color.rgb = RGBColor(26, 54, 93)
    
    sub_p = doc.add_paragraph()
    sub_p.paragraph_format.space_after = Pt(12)
    run_sub = sub_p.add_run(f"Reverse Engineering Documentation | Provider: {provider} ({model_name})")
    run_sub.font.size = Pt(9)
    run_sub.font.color.rgb = RGBColor(113, 128, 150)
    
    # 1. Executive Summary
    h1 = doc.add_heading(level=1)
    h1.add_run("1. Executive Summary & Application Purpose").font.color.rgb = RGBColor(26, 54, 93)
    
    add_callout_box(doc, "Application Purpose", analysis_result.get("application_purpose", "N/A"))
    doc.add_paragraph(analysis_result.get("executive_summary", "N/A"))
    
    # Helper Tabelle Word
    def create_docx_table(headers: List[str], data: List[Dict[str, Any]], keys: List[str]):
        table = doc.add_table(rows=1, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True
        
        hdr_cells = table.rows[0].cells
        for i, header_text in enumerate(headers):
            hdr_cells[i].text = header_text
            set_cell_background(hdr_cells[i], "2D3748")
            set_cell_margins(hdr_cells[i], top=90, bottom=90, left=100, right=100)
            p = hdr_cells[i].paragraphs[0]
            for run in p.runs:
                run.font.bold = True
                run.font.size = Pt(8)
                run.font.color.rgb = RGBColor(255, 255, 255)
        
        for item in data:
            row_cells = table.add_row().cells
            sme = "Approved" if item.get("sme_approved", False) else "Pending"
            row_values = [sme] + [str(item.get(k, "")) for k in keys[1:]]
            
            for i, val in enumerate(row_values):
                row_cells[i].text = val
                set_cell_margins(row_cells[i], top=70, bottom=70, left=100, right=100)
                p = row_cells[i].paragraphs[0]
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.space_before = Pt(0)
                
                for run in p.runs:
                    run.font.size = Pt(8)
                    if i == 0:
                        run.font.bold = True
                        run.font.color.rgb = RGBColor(34, 84, 61) if sme == "Approved" else RGBColor(116, 66, 16)
        
        doc.add_paragraph()

    # 2. Business Rules
    h2 = doc.add_heading(level=1)
    h2.add_run("2. SME Validated Business Rules").font.color.rgb = RGBColor(26, 54, 93)
    create_docx_table(
        ["Status", "Rule ID", "Rule Name", "Condition", "Impact"],
        analysis_result.get("business_rules", []),
        ["sme_approved", "rule_id", "rule_name", "condition", "business_impact"]
    )

    # 3. Components
    h3 = doc.add_heading(level=1)
    h3.add_run("3. System Components Architecture").font.color.rgb = RGBColor(26, 54, 93)
    create_docx_table(
        ["Status", "Component Name", "Type", "Source File"],
        analysis_result.get("components", []),
        ["sme_approved", "component_name", "component_type", "source_file"]
    )

    # 4. Dependencies & Data Flow
    h4 = doc.add_heading(level=1)
    h4.add_run("4. Dependencies & Data Flow").font.color.rgb = RGBColor(26, 54, 93)
    create_docx_table(
        ["Status", "Target / Entity", "Access Type", "Component Source"],
        analysis_result.get("dependencies", []),
        ["sme_approved", "target_entity", "access_type", "source_component"]
    )

    # 5. Technical Risks
    h5 = doc.add_heading(level=1)
    h5.add_run("5. Technical Risks & Vulnerabilities").font.color.rgb = RGBColor(26, 54, 93)
    create_docx_table(
        ["Status", "Risk ID", "Severity", "Description", "Recommendation"],
        analysis_result.get("technical_risks", []),
        ["sme_approved", "risk_id", "severity", "description", "recommendation"]
    )

    # 6. Mermaid Diagram
    mermaid_code = analysis_result.get("mermaid_diagram") or analysis_result.get("architecture_diagram")
    if mermaid_code:
        h6 = doc.add_heading(level=1)
        h6.add_run("6. Architecture & Data Flow Diagram").font.color.rgb = RGBColor(26, 54, 93)
        
        img_data = get_mermaid_image_bytes(mermaid_code)
        if img_data:
            img_buffer = io.BytesIO(img_data)
            doc.add_picture(img_buffer, width=Inches(6.2))
        else:
            p_code = doc.add_paragraph(mermaid_code)
            p_code.style.font.name = 'Courier New'
            p_code.style.font.size = Pt(8)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
