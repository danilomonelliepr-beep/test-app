#!/usr/bin/env python3
"""Converte GUIDA.md in un PDF impaginato.

    python guida_pdf.py [sorgente.md] [uscita.pdf]

Markdown → HTML (libreria `markdown`, con tabelle e blocchi di codice) → PDF
(wkhtmltopdf). Il blocco Mermaid della guida non è disegnabile qui, quindi
viene trasformato in una catena di riquadri HTML: dice la stessa cosa e si
stampa ovunque.
"""
import html
import re
import subprocess
import sys
from pathlib import Path

import markdown

CSS = """
@page { size: A4; margin: 20mm 16mm 18mm 16mm; }
body { font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
       font-size: 10.5pt; line-height: 1.55; color: #1a202c; }
h1 { font-size: 21pt; margin: 0 0 4pt 0; color: #1a365d;
     border-bottom: 2.5px solid #2b6cb0; padding-bottom: 6pt; }
h1 + p { color: #4a5568; }
h2 { font-size: 15pt; margin: 22pt 0 6pt 0; color: #2b6cb0;
     border-bottom: 1px solid #cbd5e0; padding-bottom: 3pt; page-break-after: avoid; }
h3 { font-size: 12pt; margin: 14pt 0 4pt 0; color: #2d3748; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
ul, ol { margin: 6pt 0 6pt 0; padding-left: 18pt; }
li { margin-bottom: 3pt; }
strong { color: #1a365d; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 9pt;
       background: #edf2f7; padding: 1px 3px; border-radius: 2px; }
pre { background: #f7fafc; border: 1px solid #e2e8f0; border-left: 3px solid #2b6cb0;
      padding: 8pt; font-size: 8.5pt; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9pt;
        page-break-inside: avoid; }
th { background: #2b6cb0; color: #fff; text-align: left; padding: 5pt 6pt;
     font-weight: bold; }
td { border-bottom: 1px solid #e2e8f0; padding: 5pt 6pt; vertical-align: top; }
tr:nth-child(even) td { background: #f7fafc; }
hr { border: none; border-top: 1px solid #cbd5e0; margin: 18pt 0; }
blockquote { border-left: 3px solid #f6ad55; background: #fffaf0; margin: 8pt 0;
             padding: 6pt 10pt; color: #744210; }
.flusso { margin: 10pt 0; page-break-inside: avoid; }
.passo { border: 1px solid #cbd5e0; background: #f7fafc; border-radius: 3px;
         padding: 5pt 8pt; font-size: 9pt; }
.passo b { color: #2b6cb0; }
.freccia { text-align: center; color: #a0aec0; font-size: 11pt; line-height: 1.1; }
"""

# Il diagramma della guida, in riquadri: stessa sequenza, nessun renderer.
FLUSSO = [
    ("File caricati", "sorgenti del cliente"),
    ("Analisi statica", "sqlglot + espressioni regolari — i fatti"),
    ("Costruzione del prompt", "contratto generato dai CAMPI, recinto irripetibile"),
    ("Divisione in lotti", "~120.000 caratteri, mai un file spezzato"),
    ("Catena dei modelli", "scoperta → prova (5 s / 10 s) → scalata"),
    ("Rientro", "estrazione JSON → riparazione → normalizzazione"),
    ("Unione con i fatti statici", "stesse colonne, stesse chiavi di deduplica"),
    ("Consolidamento e diagrammi", "solo con più lotti; disegni dai dati"),
    ("Validazione dell'esperto", "tabelle editabili, caselle da spuntare"),
    ("Esportazione", "PDF · Word · JSON"),
]


def blocco_flusso() -> str:
    pezzi = ['<div class="flusso">']
    for i, (titolo, nota) in enumerate(FLUSSO):
        pezzi.append(f'<div class="passo"><b>{html.escape(titolo)}</b> — {html.escape(nota)}</div>')
        if i < len(FLUSSO) - 1:
            pezzi.append('<div class="freccia">&#9660;</div>')
    pezzi.append("</div>")
    return "\n".join(pezzi)


def converti(sorgente: Path, uscita: Path) -> int:
    testo = sorgente.read_text("utf-8")
    testo = re.sub(r"```mermaid.*?```", "@@FLUSSO@@", testo, flags=re.S)
    corpo = markdown.markdown(
        testo, extensions=["tables", "fenced_code", "sane_lists", "attr_list"])
    corpo = corpo.replace("<p>@@FLUSSO@@</p>", blocco_flusso())
    pagina = (f"<!doctype html><html><head><meta charset='utf-8'>"
              f"<style>{CSS}</style></head><body>{corpo}</body></html>")
    tmp = uscita.with_suffix(".html")
    tmp.write_text(pagina, "utf-8")
    esito = subprocess.run([
        "wkhtmltopdf", "--quiet", "--encoding", "utf-8",
        "--enable-local-file-access",
        "--margin-top", "18mm", "--margin-bottom", "16mm",
        "--margin-left", "14mm", "--margin-right", "14mm",
        "--footer-font-size", "8",
        "--footer-left", "Legacy Application Knowledge Extractor",
        "--footer-right", "[page]/[topage]",
        str(tmp), str(uscita)], capture_output=True)
    tmp.unlink(missing_ok=True)
    if esito.returncode != 0:
        sys.stderr.write((esito.stderr or b"").decode("utf-8", "replace"))
        return esito.returncode
    print(f"{uscita} — {uscita.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sorg = Path(sys.argv[1] if len(sys.argv) > 1 else "GUIDA.md")
    dest = Path(sys.argv[2] if len(sys.argv) > 2 else sorg.with_suffix(".pdf"))
    raise SystemExit(converti(sorg, dest))
