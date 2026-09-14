#!/usr/bin/env python3
"""
Controlla che una copia appena clonata sia completa e funzionante.

    python verifica.py

Non chiama nessun modello, non installa niente e non spende niente: dice solo
cosa manca. Per installarlo e partire c'è `avvia.py`, che fa entrambe le cose.

Esiste separato perché a volte serve sapere com'è messa una macchina senza
toccarla — un server di qualcun altro, un ambiente condiviso, una verifica
prima di un'installazione.
"""
import importlib
import os
import sys
from pathlib import Path

QUI = Path(__file__).parent
ESITI = []


def esito(ok, titolo, rimedio=""):
    ESITI.append(bool(ok))
    print(("  ok   " if ok else "  MANCA") + "  " + titolo)
    if not ok and rimedio:
        print("         → " + rimedio)


print("\nFile del progetto")
for nome in ["app.py", "model_chain.py", "contract.py", "diagrams.py",
             "mermaid_render.py", "exporter.py", "ui.py", "requirements.txt"]:
    esito((QUI / nome).exists(), nome, "il clone è incompleto")

print("\nCartelle che si perdono facilmente nella copia")
font = [f for f in ["IBMPlexSans-Regular.ttf", "IBMPlexSans-SemiBold.ttf",
                    "IBMPlexMono-Regular.ttf", "IBMPlexMono-Medium.ttf"]
        if (QUI / "fonts" / f).exists()]
esito(len(font) == 4, f"fonts/ ({len(font)} di 4 file)",
      "senza: il PDF esce in Helvetica invece che in IBM Plex")

print("\nPacchetti Python")
for modulo, pacchetto in [("streamlit", "streamlit"), ("streamlit_mermaid", "streamlit-mermaid"),
                          ("sqlglot", "sqlglot"), ("pandas", "pandas"), ("requests", "requests"),
                          ("reportlab", "reportlab"), ("docx", "python-docx")]:
    try:
        importlib.import_module(modulo)
        esito(True, pacchetto)
    except ImportError:
        esito(False, pacchetto, "pip install -r requirements.txt")

print("\nDisegno dei diagrammi")
try:
    import mermaid_render
    presente, dettaglio = mermaid_render.disponibile()
    ok = mermaid_render.prova_locale() if presente else False
    if presente and not ok:
        dettaglio += " — il comando c'è ma non disegna"
except Exception as e:  # noqa: BLE001
    ok, dettaglio = False, str(e)
esito(ok, f"mermaid-cli in locale — {dettaglio}",
      "python avvia.py lo installa (accanto al progetto, senza permessi speciali). "
      "Se c'è ma non disegna, gli manca il browser: node node_modules/puppeteer/install.mjs "
      "(oppure export PUPPETEER_EXECUTABLE_PATH=/percorso/di/chrome). "
      "Finché non disegna, il codice dei diagrammi esce dalla macchina verso "
      "mermaid.ink; con MERMAID_LOCAL_ONLY=1 i documenti portano il sorgente "
      "invece dell'immagine")

print("\nChiavi nell'ambiente (facoltative: si possono scrivere nell'app)")
for variabile in ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "AZURE_OPENAI_API_KEY"]:
    print(("  ok     " if os.environ.get(variabile) else "  assente ") + variabile)

print("\nAvvio")
esito((QUI / "avvia.py").exists(), "avvia.py",
      "il clone è incompleto")

print("\nVersione di Python")
esito(sys.version_info >= (3, 9), f"Python {sys.version_info.major}.{sys.version_info.minor}",
      "serve almeno 3.9")

mancanti = len(ESITI) - sum(ESITI)
print()
if mancanti == 0:
    print("Tutto a posto: python avvia.py")
else:
    print(("1 cosa da sistemare." if mancanti == 1 else f"{mancanti} cose da sistemare.")
          + " Quasi tutte le sistema da solo:")
    print("    python avvia.py")
sys.exit(0 if mancanti == 0 else 1)
