#!/usr/bin/env python3
"""
AVVIO — un comando solo.

    python avvia.py

Controlla cosa manca, lo installa, imposta Streamlit e lancia l'applicazione.
Su una macchina pulita basta questo: né `pip install`, né `npm`, né cartelle di
configurazione da ricordarsi.

── PERCHÉ NON INSTALLA DI NASCOSTO ───────────────────────────────────────
Installare pacchetti senza dirlo è una brutta abitudine: tocca l'ambiente di
chi lancia il comando, e se quell'ambiente è condiviso il danno non è suo. Qui
ogni comando viene stampato prima di essere eseguito, l'installazione Python va
nell'interprete corrente (quindi dentro il virtualenv, se ce n'è uno attivo), e
`--niente-installazioni` fa girare solo i controlli.

── IL TEMA ───────────────────────────────────────────────────────────────
Lo imposta `ui.imposta_tema_streamlit()` da codice, a ogni avvio dell'app:
nessun file di configurazione, nessuna cartella nascosta, e vale anche su
Streamlit Cloud. Le stesse impostazioni vengono passate anche qui come
opzioni, per chi parte da questo script.

── OPZIONI ───────────────────────────────────────────────────────────────
    --niente-installazioni   controlla e basta, non installa nulla
    --senza-mermaid          salta mermaid-cli (i diagrammi useranno la rete)
    --solo-preparazione      installa quello che manca e si ferma lì, senza
                             aprire l'applicazione. È quello che lancia il
                             bottone «Install what's missing» nella barra
                             laterale, che non può certo riaprire sé stesso.
    --porta 8502             porta su cui aprire l'applicazione
"""
import os
import subprocess
import sys
from pathlib import Path

QUI = Path(__file__).parent
PACCHETTI = ["streamlit", "streamlit_mermaid", "sqlglot", "pandas", "requests",
             "reportlab", "docx"]

# Le stesse impostazioni che `ui.imposta_tema_streamlit` mette da codice a
# ogni avvio dell'app. Passarle anche qui fa sì che chi parte da questo script
# le abbia fin dalla primissima esecuzione, senza la ripartenza. Le variabili d'ambiente equivalenti esistono, ma
# Streamlit le legge solo quando avvia il server: provate in un interprete
# normale non hanno effetto, e una configurazione che funziona «solo qualche
# volta» è peggio di una che manca. Le opzioni, invece, valgono sempre.
# Il tema serve ai controlli di Streamlit; i colori dei nostri componenti sono
# già nel CSS di `ui.py`.
OPZIONI = [
    ("--theme.base", "light"),
    ("--theme.primaryColor", "#15616D"),
    ("--theme.backgroundColor", "#F1F4F7"),
    ("--theme.secondaryBackgroundColor", "#FFFFFF"),
    ("--theme.textColor", "#17212B"),
    ("--server.maxUploadSize", "50"),
    ("--client.toolbarMode", "minimal"),
    ("--browser.gatherUsageStats", "false"),
]


def dimmi(testo: str) -> None:
    print(testo, flush=True)


def esegui(comando: list, descrizione: str) -> bool:
    dimmi(f"  $ {' '.join(comando)}")
    try:
        esito = subprocess.run(comando, cwd=str(QUI))
    except OSError as e:
        dimmi(f"    non eseguibile: {e}")
        return False
    if esito.returncode != 0:
        dimmi(f"    {descrizione}: non riuscito (codice {esito.returncode})")
    return esito.returncode == 0


def mancanti() -> list:
    fuori = []
    for modulo in PACCHETTI:
        try:
            __import__(modulo)
        except ImportError:
            fuori.append(modulo)
    return fuori


def sistema_python(installa: bool) -> bool:
    fuori = mancanti()
    if not fuori:
        dimmi("Pacchetti Python: già a posto.")
        return True
    dimmi(f"Pacchetti Python mancanti: {', '.join(fuori)}")
    if not installa:
        dimmi("  (installazione saltata: pip install -r requirements.txt)")
        return False
    esegui([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
           "installazione dei pacchetti")
    restano = mancanti()
    if restano:
        dimmi(f"  restano fuori: {', '.join(restano)}")
        return False
    dimmi("  installati.")
    return True


def mermaid_disegna() -> bool:
    try:
        sys.path.insert(0, str(QUI))
        import importlib

        import mermaid_render
        importlib.reload(mermaid_render)   # dopo un'installazione, la cache è vecchia
        return mermaid_render.prova_locale()
    except Exception:
        return False


def sistema_mermaid(installa: bool) -> bool:
    if mermaid_disegna():
        dimmi("Diagrammi: si disegnano in locale.")
        return True
    if not installa:
        dimmi("Diagrammi: nessun disegno locale (installazione saltata).")
        return False
    import shutil
    if not shutil.which("npm"):
        dimmi("Diagrammi: serve Node.js per disegnarli in locale — https://nodejs.org")
        dimmi("  senza, il codice dei diagrammi esce dalla macchina verso mermaid.ink.")
        return False
    dimmi("Diagrammi: installo mermaid-cli (la prima volta scarica anche un browser).")
    # Prima accanto al progetto: non servono permessi di amministratore, e
    # `mermaid_render` lo cerca già in `node_modules/.bin`.
    # `--no-save`: senza, npm fabbrica un package.json e un package-lock.json
    # accanto al codice, che poi finiscono nel repository senza che nessuno li
    # abbia voluti. È successo.
    if not esegui(["npm", "install", "--silent", "--no-audit", "--no-fund", "--no-save",
                   "@mermaid-js/mermaid-cli"], "installazione locale"):
        return False
    if mermaid_disegna():
        dimmi("  installato: i diagrammi restano sulla macchina.")
        return True
    # Il comando c'è ma non disegna: gli manca il browser.
    # Lo scarica l'installatore di puppeteer STESSO, quello dentro
    # node_modules: è l'unico che conosce la versione esatta di Chrome che
    # quel puppeteer pretende. Un `npx puppeteer browsers install` generico
    # prende un altro puppeteer, scarica un'altra versione, e mmdc continua a
    # non trovare il browser — provato, non supposto.
    dimmi("  installato, ma manca il browser che si porta dietro. Lo scarico.")
    installatore = QUI / "node_modules" / "puppeteer" / "install.mjs"
    if installatore.exists():
        esegui(["node", str(installatore)], "scaricamento del browser")
    else:
        esegui(["npx", "-y", "@puppeteer/browsers", "install", "chrome"],
               "scaricamento del browser")
    if mermaid_disegna():
        dimmi("  ora disegna.")
        return True
    dimmi("  non disegna ancora: i diagrammi passeranno da mermaid.ink.")
    dimmi("  di solito è la rete che blocca il download del browser. Con un")
    dimmi("  Chrome già installato: export PUPPETEER_EXECUTABLE_PATH=/percorso/di/chrome")
    dimmi("  se in azienda l'uscita non va bene: export MERMAID_LOCAL_ONLY=1")
    return False


def main() -> int:
    argomenti = sys.argv[1:]
    installa = "--niente-installazioni" not in argomenti
    porta = None
    if "--porta" in argomenti:
        try:
            porta = argomenti[argomenti.index("--porta") + 1]
        except IndexError:
            dimmi("--porta vuole un numero.")
            return 2

    dimmi("\nLegacy Application Knowledge Extractor — avvio\n")
    if not sistema_python(installa):
        dimmi("\nSenza i pacchetti Python non si parte. "
              "Comando: pip install -r requirements.txt")
        return 1
    if "--senza-mermaid" not in argomenti:
        sistema_mermaid(installa)

    if "--solo-preparazione" in argomenti:
        dimmi("\nPreparazione finita.")
        return 0

    chiavi = [v for v in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "AZURE_OPENAI_API_KEY")
              if os.environ.get(v)]
    dimmi("Chiave API: " + (", ".join(chiavi) if chiavi
                            else "nessuna nell'ambiente — si scrive nella barra laterale."))

    comando = [sys.executable, "-m", "streamlit", "run", str(QUI / "app.py")]
    for opzione, valore in OPZIONI:
        comando += [opzione, valore]
    if porta:
        comando += ["--server.port", porta]
    dimmi("\nApro l'applicazione. Per fermarla: Ctrl+C.\n")
    try:
        return subprocess.call(comando, cwd=str(QUI))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
