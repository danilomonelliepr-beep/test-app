import os
import io
import html
from typing import Dict, Any, List

import pandas as pd
from weasyprint import HTML

import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

# =============================================================================
# HELPER FUNCTIONS FOR DOCX STYLING
# =============================================================================
def set_cell_background(cell, hex_color: str):
    """Sets the background fill color of a table cell in docx."""
    tcPr = cell._element.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Sets internal padding for a table cell in dxa units (1 pt = 20 dxa)."""
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
    """Creates a styled callout box with a left accent border in docx."""
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    
    cell = table.cell(0, 0)
    cell.width = Inches(6.5)
    set_cell_background(cell, "EBF8FF")  # Soft ice blue
    set_cell_margins(cell, top=140, bottom=140, left=200, right=200)
    
    # Left border styling
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
    
    doc.add_paragraph()  # Spacing

# =============================================================================
# 1. EXPORT TO PDF VIA WEASYPRINT
# =============================================================================
def generate_pdf_report(analysis_result: Dict[str, Any], metadata: Dict[str, Any], provider: str, model_name: str) -> bytes:
    """Generates a publication-grade PDF report using WeasyPrint and inline CSS."""
    
    def safe_h(val):
        return html.escape(str(val)) if val is not None else ""

    def render_rows(items: List[Dict[str, Any]], columns: List[str]):
        if not items:
            return f'<tr><td colspan="{len(columns)}" style="text-align:center; color:#718096;">No records found.</td></tr>'
        
        rows_html = []
        for item in items:
            sme = item.get("sme_approved", False)
            status_badge = '<span class="badge badge-approved">Approved</span>' if sme else '<span class="badge badge-pending">Pending</span>'
            
            cells = [f'<td>{status_badge}</td>']
            for col in columns[1:]:
                val = safe_h(item.get(col, ""))
                if col.lower() in ["risk_id", "process_id", "rule_id", "component_name"]:
                    val = f'<code>{val}</code>'
                elif col.lower() == "severity":
                    sev = str(item.get("severity", "LOW")).upper()
                    badge_cls = f"badge-{sev.lower()}"
                    val = f'<span class="badge {badge_cls}">{sev}</span>'
                cells.append(f'<td>{val}</td>')
            
            rows_html.append(f'<tr>{"".join(cells)}</tr>')
        return "\n".join(rows_html)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
    @page {{
        size: A4;
        margin: 18mm 14mm 18mm 14mm;
        @bottom-right {{
            content: "Page " counter(page) " of " counter(pages);
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 8pt;
            color: #718096;
        }}
        @bottom-left {{
            content: "Legacy Application Knowledge Extractor — SME Validated Report";
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 8pt;
            color: #718096;
        }}
    }}

    *, *::before, *::after {{ box-sizing: border-box; }}

    body {{
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-size: 9pt;
        line-height: 1.45;
        color: #2d3748;
        background-color: #ffffff;
        margin: 0;
        padding: 0;
    }}

    /* Header Banner */
    .header-container {{
        background: linear-gradient(135deg, #1a365d 0%, #2b6cb0 100%);
        color: #ffffff;
        padding: 20px 24px;
        margin: -18mm -14mm 20px -14mm;
        border-bottom: 4px solid #3182ce;
    }}

    .header-title {{
        font-size: 18pt;
        font-weight: 700;
        margin: 0 0 4px 0;
        letter-spacing: -0.5px;
    }}

    .header-subtitle {{
        font-size: 10pt;
        font-weight: 300;
        opacity: 0.9;
        margin: 0 0 12px 0;
    }}

    .header-meta {{
        display: table;
        width: 100%;
        border-top: 1px solid rgba(255, 255, 255, 0.2);
        padding-top: 8px;
        font-size: 8pt;
    }}

    .meta-item {{
        display: table-cell;
        width: 33.33%;
        color: #e2e8f0;
    }}

    .meta-item strong {{ color: #ffffff; }}

    /* Key Metrics Grid */
    .metrics-grid {{
        display: table;
        width: 100%;
        table-layout: fixed;
        margin-bottom: 18px;
        border-spacing: 8px;
        margin-left: -8px;
        margin-right: -8px;
    }}

    .metric-card {{
        display: table-cell;
        background-color: #f7fafc;
        border: 1px solid #e2e8f0;
        border-radius: 5px;
        padding: 10px;
        text-align: center;
    }}

    .metric-value {{
        font-size: 15pt;
        font-weight: 700;
        color: #2b6cb0;
        line-height: 1.1;
    }}

    .metric-label {{
        font-size: 7pt;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: #718096;
        margin-top: 3px;
        font-weight: 600;
    }}

    /* Typography & Headers */
    h2 {{
        font-size: 12pt;
        font-weight: 700;
        color: #1a365d;
        border-left: 4px solid #3182ce;
        padding-left: 8px;
        margin: 18px 0 10px 0;
        page-break-after: avoid;
    }}

    p {{ margin: 0 0 8px 0; }}

    /* Callout Boxes */
    .callout {{
        background-color: #ebf8ff;
        border-left: 4px solid #3182ce;
        padding: 10px 12px;
        margin-bottom: 14px;
        border-radius: 0 5px 5px 0;
    }}

    .callout-title {{
        font-weight: 700;
        color: #2b6cb0;
        font-size: 8.5pt;
        text-transform: uppercase;
        margin-bottom: 3px;
    }}

    /* Tables */
    table {{
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 16px;
        font-size: 8pt;
        page-break-inside: auto;
    }}

    tr {{ page-break-inside: avoid; page-break-after: auto; }}

    th {{
        background-color: #2d3748;
        color: #ffffff;
        font-weight: 600;
        text-align: left;
        padding: 6px 8px;
        font-size: 7.5pt;
        text-transform: uppercase;
        letter-spacing: 0.3px;
        border: 1px solid #2d3748;
    }}

    td {{
        padding: 6px 8px;
        border: 1px solid #e2e8f0;
        vertical-align: top;
    }}

    tbody tr:nth-child(even) {{ background-color: #f7fafc; }}

    /* Badges */
    .badge {{
        display: inline-block;
        padding: 2px 5px;
        border-radius: 3px;
        font-size: 6.5pt;
        font-weight: 700;
        text-transform: uppercase;
    }}
    .badge-approved {{ background-color: #c6f6d5; color: #22543d; }}
    .badge-pending {{ background-color: #feebc8; color: #744210; }}
    .badge-critical {{ background-color: #fed7d7; color: #742a2a; }}
    .badge-high {{ background-color: #feebc8; color: #744210; }}
    .badge-medium {{ background-color: #e2e8f0; color: #2d3748; }}
    .badge-low {{ background-color: #e6fffa; color: #234e52; }}

    code {{
        font-family: 'Courier New', Courier, monospace;
        font-size: 7.5pt;
        background-color: #edf2f7;
        padding: 1px 3px;
        border-radius: 2px;
    }}
</style>
</head>
<body>

<div class="header-container">
    <div class="header-title">Legacy System Knowledge Extraction</div>
    <div class="header-subtitle">Reverse Engineering & Technical Documentation Report</div>
    <div class="header-meta">
        <div class="meta-item"><strong>Provider:</strong> {safe_h(provider)}</div>
        <div class="meta-item"><strong>Model:</strong> {safe_h(model_name)}</div>
        <div class="meta-item"><strong>Files Analyzed:</strong> {metadata.get('file_count', 0)}</div>
    </div>
</div>

<div class="metrics-grid">
    <div class="metric-card">
        <div class="metric-value">{metadata.get('file_count', 0)}</div>
        <div class="metric-label">Source Files</div>
    </div>
    <div class="metric-card">
        <div class="metric-value">{metadata.get('total_line_count', 0):,}</div>
        <div class="metric-label">Lines of Code</div>
    </div>
    <div class="metric-card">
        <div class="metric-value">{len(analysis_result.get('components', []))}</div>
        <div class="metric-label">Components</div>
    </div>
    <div class="metric-card">
        <div class="metric-value">{len(analysis_result.get('technical_risks', []))}</div>
        <div class="metric-label">Technical Risks</div>
    </div>
</div>

<h2>1. Executive Summary & Application Purpose</h2>
<div class="callout">
    <div class="callout-title">Core Purpose</div>
    {safe_h(analysis_result.get('application_purpose', 'N/A'))}
</div>
<p>{safe_h(analysis_result.get('executive_summary', 'N/A'))}</p>

<h2>2. SME Validated Business Rules</h2>
<table>
    <thead>
        <tr>
            <th style="width: 12%;">SME Status</th>
            <th style="width: 12%;">Rule ID</th>
            <th style="width: 22%;">Rule Name</th>
            <th style="width: 32%;">Condition / Action</th>
            <th style="width: 22%;">Impact</th>
        </tr>
    </thead>
    <tbody>
        {render_rows(analysis_result.get('business_rules', []), ['sme_approved', 'rule_id', 'rule_name', 'condition', 'business_impact'])}
    </tbody>
</table>

<h2>3. Key Architecture Components</h2>
<table>
    <thead>
        <tr>
            <th style="width: 12%;">SME Status</th>
            <th style="width: 30%;">Component Name</th>
            <th style="width: 20%;">Type</th>
            <th style="width: 38%;">Source File</th>
        </tr>
    </thead>
    <tbody>
        {render_rows(analysis_result.get('components', []), ['sme_approved', 'component_name', 'component_type', 'source_file'])}
    </tbody>
</table>

<h2>4. Technical Risks & Vulnerabilities</h2>
<table>
    <thead>
        <tr>
            <th style="width: 12%;">SME Status</th>
            <th style="width: 12%;">Risk ID</th>
            <th style="width: 14%;">Severity</th>
            <th style="width: 31%;">Description</th>
            <th style="width: 31%;">Recommendation</th>
        </tr>
    </thead>
    <tbody>
        {render_rows(analysis_result.get('technical_risks', []), ['sme_approved', 'risk_id', 'severity', 'description', 'recommendation'])}
    </tbody>
</table>

</body>
</html>
"""
    return HTML(string=html_content).write_pdf()

# =============================================================================
# 2. EXPORT TO WORD (.DOCX) VIA PYTHON-DOCX
# =============================================================================
def generate_docx_report(analysis_result: Dict[str, Any], metadata: Dict[str, Any], provider: str, model_name: str) -> bytes:
    """Generates an editable Word (.docx) document with custom formatting and tables."""
    doc = Document()
    
    # Set standard margins (1 inch)
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)
        
    # Set default document font
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Arial'
    font.size = Pt(10)
    font.color.rgb = RGBColor(45, 55, 72)
    
    # Title
    title_p = doc.add_paragraph()
    run_title = title_p.add_run("Legacy Application Knowledge Extraction")
    run_title.bold = True
    run_title.font.size = Pt(20)
    run_title.font.color.rgb = RGBColor(26, 54, 93)
    
    sub_p = doc.add_paragraph()
    sub_p.paragraph_format.space_after = Pt(14)
    run_sub = sub_p.add_run(f"Reverse Engineering & SME Technical Documentation  |  Provider: {provider} ({model_name})")
    run_sub.font.size = Pt(10)
    run_sub.font.color.rgb = RGBColor(113, 128, 150)
    
    # 1. Purpose & Executive Summary
    h1 = doc.add_heading(level=1)
    h1_run = h1.add_run("1. Executive Summary & Application Purpose")
    h1_run.font.color.rgb = RGBColor(26, 54, 93)
    
    add_callout_box(doc, "Application Purpose", analysis_result.get("application_purpose", "N/A"))
    doc.add_paragraph(analysis_result.get("executive_summary", "N/A"))
    
    # Helper to add styled tables in docx
    def create_docx_table(headers: List[str], data: List[Dict[str, Any]], keys: List[str]):
        table = doc.add_table(rows=1, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = True
        
        # Format Header Row
        hdr_cells = table.rows[0].cells
        for i, header_text in enumerate(headers):
            hdr_cells[i].text = header_text
            set_cell_background(hdr_cells[i], "2D3748")  # Dark slate fill
            set_cell_margins(hdr_cells[i], top=100, bottom=100, left=120, right=120)
            p = hdr_cells[i].paragraphs[0]
            for run in p.runs:
                run.font.bold = True
                run.font.size = Pt(8.5)
                run.font.color.rgb = RGBColor(255, 255, 255)
        
        # Populate Data Rows
        for item in data:
            row_cells = table.add_row().cells
            sme = "Approved" if item.get("sme_approved", False) else "Pending"
            
            row_values = [sme] + [str(item.get(k, "")) for k in keys[1:]]
            
            for i, val in enumerate(row_values):
                row_cells[i].text = val
                set_cell_margins(row_cells[i], top=80, bottom=80, left=120, right=120)
                p = row_cells[i].paragraphs[0]
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.space_before = Pt(0)
                
                for run in p.runs:
                    run.font.size = Pt(8.5)
                    if i == 0:
                        run.font.bold = True
                        run.font.color.rgb = RGBColor(34, 84, 61) if sme == "Approved" else RGBColor(116, 66, 16)
        
        doc.add_paragraph()  # Spacing

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
    h3.add_run("3. System Components").font.color.rgb = RGBColor(26, 54, 93)
    create_docx_table(
        ["Status", "Component Name", "Type", "Source File"],
        analysis_result.get("components", []),
        ["sme_approved", "component_name", "component_type", "source_file"]
    )

    # 4. Technical Risks
    h4 = doc.add_heading(level=1)
    h4.add_run("4. Technical Risks").font.color.rgb = RGBColor(26, 54, 93)
    create_docx_table(
        ["Status", "Risk ID", "Severity", "Description", "Recommendation"],
        analysis_result.get("technical_risks", []),
        ["sme_approved", "risk_id", "severity", "description", "recommendation"]
    )

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
