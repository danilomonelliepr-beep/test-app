"""
═══════════════════════════════════════════════════════════════════════════
I DIAGRAMMI, DISEGNATI IN CASA.

Prima l'unico modo di trasformare il codice Mermaid in un'immagine per il PDF e
per il Word era `mermaid.ink`: un servizio pubblico a cui si manda, dentro
l'URL, il diagramma dell'applicazione legacy del cliente. Su una codebase
altrui non è una scelta da fare per distrazione.

`mermaid.ink` non ha una tecnologia sua: è mermaid.js dentro un Chromium
headless, sul server di qualcun altro. Farlo girare sul proprio dà la stessa
immagine, dallo stesso motore. Qui si prova, nell'ordine:

  1. `mmdc` — il comando di @mermaid-js/mermaid-cli, se è installato. È la via
     buona: niente esce dalla macchina.
  2. `npx @mermaid-js/mermaid-cli` — solo se lo si abilita a mano (scarica il
     pacchetto la prima volta, quindi non deve succedere di nascosto).
  3. `mermaid.ink` — solo come rete di sicurezza, e solo se non è stato
     proibito. Serve a far girare l'app anche dove Node non c'è.

── COSA INSTALLARE ───────────────────────────────────────────────────────
    python avvia.py                               # fa tutto da solo, oppure:
    npm install @mermaid-js/mermaid-cli           # accanto al progetto
    node node_modules/puppeteer/install.mjs       # il browser, nella versione giusta

Dentro un container servono `--no-sandbox` (ci pensa questo file, con un file
di configurazione temporaneo) e a volte le librerie di sistema di Chrome. Se
sulla macchina c'è già Chrome, si può evitare il download di Chromium con:
    export PUPPETEER_EXECUTABLE_PATH=/usr/bin/google-chrome

── INTERRUTTORI (variabili d'ambiente) ───────────────────────────────────
    MERMAID_CLI=/percorso/di/mmdc   percorso esplicito del comando
    MERMAID_LOCAL_ONLY=1            vieta del tutto la ricaduta su mermaid.ink
    MERMAID_ALLOW_NPX=1             consente il tentativo con npx
    MERMAID_THEME=neutral           default|neutral|dark|forest
    MERMAID_WIDTH=2400              larghezza in pixel del disegno
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

__version__ = "2026.09.16"

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

TIMEOUT_S = 90
_CACHE: dict = {}
_ULTIMO_MOTORE = ""


# =============================================================================
# PULIZIA — la stessa che fa il contratto, ripetuta qui perché questo modulo
# deve funzionare anche su un JSON vecchio, salvato prima del contratto 2.0.
# =============================================================================
def pulisci(codice: str) -> str:
    t = str(codice or "").strip()
    t = re.sub(r"^`{3}(?:mermaid)?", "", t, flags=re.MULTILINE)
    t = re.sub(r"^`{3}$", "", t, flags=re.MULTILINE).strip()
    return html.unescape(t).replace("--&gt;", "-->").strip()


def _config_puppeteer(cartella: Path) -> Path:
    f = cartella / "puppeteer.json"
    # Senza --no-sandbox, dentro un container Chromium non parte e mmdc esce
    # con un errore che non parla di sandbox. È il primo scoglio di chiunque
    # provi a installarlo su un server.
    f.write_text(json.dumps({"args": ["--no-sandbox", "--disable-dev-shm-usage"]}), "utf-8")
    return f


# ═══ LE ETICHETTE CHE ESCONO DALLE CASELLE ═════════════════════════════════
# Con `htmlLabels: true` Mermaid disegna il testo dei nodi dentro un
# `foreignObject`, cioè HTML vero dentro l'SVG. Il riquadro però lo dimensiona
# PRIMA, misurando il testo con il carattere che crede di avere. In un browser
# headless quel carattere spesso non c'è: si misura con uno, si disegna con un
# altro, e il testo esce dalla casella o ci si sovrappone — è il difetto che si
# vedeva nei PDF, con le etichette su due righe dentro riquadri alti una riga.
#
# Con `htmlLabels: false` il testo è un `<text>` SVG normale: Mermaid lo misura
# con lo stesso motore con cui lo disegna, e la casella viene della misura
# giusta. Si perde la formattazione HTML nelle etichette, che non usiamo.
CONFIG_MERMAID = {
    "theme": os.environ.get("MERMAID_THEME", "neutral"),
    "htmlLabels": False,
    "fontFamily": "Arial, Helvetica, sans-serif",   # presente ovunque
    "flowchart": {"useMaxWidth": False, "htmlLabels": False,
                  "wrappingWidth": 220, "padding": 10, "nodeSpacing": 45,
                  "rankSpacing": 55, "curve": "basis"},
    "sequence": {"useMaxWidth": False},
    "er": {"useMaxWidth": False},
    "maxTextSize": 200000,   # una mappa applicativa vera supera il default
    "maxEdges": 2000,
}

# La stessa configurazione, scritta DENTRO il diagramma. Serve per il servizio
# esterno, che riceve solo il codice e del nostro file di configurazione non sa
# niente — ed è il motivo per cui i diagrammi disegnati da `mermaid.ink`
# uscivano col tema di serie e le etichette fuori posto. Scritta così viaggia
# col diagramma: vale in locale, vale sul servizio, e vale anche se qualcuno
# incolla il codice su mermaid.live.
def _direttiva() -> str:
    dentro = {k: CONFIG_MERMAID[k] for k in ("theme", "htmlLabels", "fontFamily", "flowchart")}
    return "%%{init: " + json.dumps(dentro, separators=(",", ":")) + "}%%"


def _config_mermaid(cartella: Path) -> Path:
    f = cartella / "mermaid.json"
    f.write_text(json.dumps(CONFIG_MERMAID), "utf-8")
    return f


def _comando_locale() -> Optional[list]:
    esplicito = os.environ.get("MERMAID_CLI", "").strip()
    if esplicito and Path(esplicito).exists():
        return [esplicito]
    # Installato accanto al progetto (`npm install @mermaid-js/mermaid-cli`,
    # senza -g): non serve essere amministratori, ed è la via che prova per
    # prima `avvia.py` quando l'installazione globale non passa.
    for nome in ("mmdc", "mmdc.cmd"):
        locale = Path(__file__).parent / "node_modules" / ".bin" / nome
        if locale.exists():
            return [str(locale)]
    trovato = shutil.which("mmdc")
    if trovato:
        return [trovato]
    if os.environ.get("MERMAID_ALLOW_NPX") == "1" and shutil.which("npx"):
        return ["npx", "-y", "@mermaid-js/mermaid-cli"]
    return None


def disponibile() -> Tuple[bool, str]:
    """Dice se il disegno locale è possibile e con che comando: serve alla
    barra laterale, per non far scoprire il problema a PDF già lanciato."""
    cmd = _comando_locale()
    if not cmd:
        return False, "mmdc non trovato (npm install -g @mermaid-js/mermaid-cli)"
    return True, " ".join(cmd)


def prova_locale() -> bool:
    """Disegna davvero un diagramma da due nodi, senza ricadute sulla rete.

    Non basta che `mmdc` esista: si porta dietro un browser che può non essere
    stato scaricato, e in quel caso il comando c'è e non disegna. Era il caso
    che passava inosservato fino a un'esportazione. Il risultato finisce nella
    cache, quindi chiamarla più volte non costa niente."""
    if not _comando_locale():
        return False
    prima = os.environ.get("MERMAID_LOCAL_ONLY")
    os.environ["MERMAID_LOCAL_ONLY"] = "1"
    try:
        return bool(rendi('flowchart TD\n  n_a["A"] --> n_b["B"]', "prova"))
    except Exception:
        return False
    finally:
        os.environ.pop("MERMAID_LOCAL_ONLY", None)
        if prima:
            os.environ["MERMAID_LOCAL_ONLY"] = prima


def _rendi_locale(codice: str, titolo: str) -> Optional[bytes]:
    cmd = _comando_locale()
    if not cmd:
        return None
    with tempfile.TemporaryDirectory(prefix="mermaid_") as d:
        cartella = Path(d)
        ingresso = cartella / "diagramma.mmd"
        uscita = cartella / "diagramma.png"
        ingresso.write_text(codice, "utf-8")
        argomenti = cmd + [
            "-i", str(ingresso),
            "-o", str(uscita),
            "-b", "white",
            "-w", os.environ.get("MERMAID_WIDTH", "2400"),
            "-p", str(_config_puppeteer(cartella)),
            "-c", str(_config_mermaid(cartella)),
            "-q",
        ]
        try:
            esito = subprocess.run(argomenti, capture_output=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            print(f"[Mermaid locale - {titolo}] oltre {TIMEOUT_S}s, saltato")
            return None
        except OSError as e:
            print(f"[Mermaid locale - {titolo}] impossibile eseguire mmdc: {e}")
            return None
        if esito.returncode != 0 or not uscita.exists():
            # L'errore vero di mermaid (riga e colonna dell'errore di sintassi)
            # arriva qui: è molto più utile del 400 muto del servizio esterno.
            msg = (esito.stderr or esito.stdout or b"").decode("utf-8", "replace").strip()
            print(f"[Mermaid locale - {titolo}] {msg[:400]}")
            return None
        dati = uscita.read_bytes()
        return dati if len(dati) > 100 else None


def _rendi_remoto(codice: str, titolo: str) -> Optional[bytes]:
    if os.environ.get("MERMAID_LOCAL_ONLY") == "1":
        print(f"[Mermaid - {titolo}] disegno locale non riuscito e servizio esterno vietato")
        return None
    import base64

    import requests

    url = "https://mermaid.ink/img/" + base64.urlsafe_b64encode(codice.encode("utf-8")).decode()
    if len(url) > 8000:
        print(f"[Mermaid - {titolo}] diagramma troppo grande per l'URL del servizio esterno")
        return None
    testate = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for tentativo in (1, 2):
        try:
            r = requests.get(url, headers=testate, timeout=20)
        except requests.RequestException as e:
            print(f"[Mermaid remoto - {titolo}] tentativo {tentativo}: {e}")
            continue
        if r.status_code == 200 and len(r.content) > 100:
            return r.content
        print(f"[Mermaid remoto - {titolo}] tentativo {tentativo}: HTTP {r.status_code}")
        if r.status_code < 500:  # un diagramma non valido darà lo stesso 400
            break
    return None


def rendi(codice: str, titolo: str = "Diagram") -> Optional[bytes]:
    """Il PNG del diagramma, o None. In cache sull'impronta del codice: PDF e
    Word chiedono gli stessi quattro diagrammi e non vanno disegnati otto volte."""
    global _ULTIMO_MOTORE
    pulito = pulisci(codice)
    if not pulito:
        return None
    # La direttiva va in testa, prima dell'intestazione del diagramma, e solo
    # se non c'è già una direttiva scritta da qualcun altro: quella di chi ha
    # scritto il diagramma vince sulla nostra.
    if "%%{init" not in pulito:
        pulito = _direttiva() + "\n" + pulito
    impronta = hashlib.sha256(pulito.encode("utf-8")).hexdigest()
    if impronta in _CACHE:
        return _CACHE[impronta]

    dati = _rendi_locale(pulito, titolo)
    _ULTIMO_MOTORE = "locale (mmdc)" if dati else ""
    if not dati:
        dati = _rendi_remoto(pulito, titolo)
        _ULTIMO_MOTORE = "mermaid.ink" if dati else "nessuno"
    _CACHE[impronta] = dati
    return dati


def ultimo_motore() -> str:
    return _ULTIMO_MOTORE


# =============================================================================
# LE DIMENSIONI VERE DEL PNG, senza dipendere da PIL.
# Servono a NON schiacciare il disegno: vedi `misura_per_riquadro`.
# =============================================================================
def dimensioni_png(dati: bytes) -> Optional[Tuple[int, int]]:
    if not dati or len(dati) < 24 or dati[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    larghezza = int.from_bytes(dati[16:20], "big")
    altezza = int.from_bytes(dati[20:24], "big")
    return (larghezza, altezza) if larghezza and altezza else None


def misura_per_riquadro(dati: bytes, max_larghezza: float, max_altezza: float,
                        difetto=(720.0, 240.0)) -> Tuple[float, float]:
    """Le misure con cui mettere l'immagine in un riquadro SENZA deformarla.

    È il difetto che si vedeva nei PDF: il diagramma veniva inserito con una
    misura fissa 720×240, cioè 3:1, qualunque forma avesse davvero. Un
    `flowchart TD` con otto nodi in colonna è alto il doppio di quanto è largo:
    schiacciato in un rettangolo 3:1 diventava una striscia illeggibile. Nel
    Word non succedeva perché lì si passava solo la larghezza e l'altezza la
    calcolava python-docx, cioè si rispettavano le proporzioni.
    """
    misura = dimensioni_png(dati)
    if not misura:
        return difetto
    l, a = misura
    fattore = min(max_larghezza / l, max_altezza / a)
    return (l * fattore, a * fattore)


# =============================================================================
# DIAGNOSTICA DA RIGA DI COMANDO
#     python mermaid_render.py
# Disegna un diagramma di prova e dice chi l'ha disegnato. Da lanciare su ogni
# macchina prima di dire «i diagrammi non escono più dall'azienda».
# =============================================================================
if __name__ == "__main__":  # pragma: no cover
    ok, dettaglio = disponibile()
    print(("✓ comando locale: " if ok else "✗ nessun comando locale: ") + dettaglio)
    prova = ("flowchart TD\n"
             '  A["Ordine ricevuto"] --> B["Validazione"]\n'
             '  B --> C["Fatturazione"]\n'
             '  C --> D["Archivio"]')
    dati = rendi(prova, "Diagnostica")
    if not dati:
        print("✗ nessun disegno prodotto: guarda i messaggi qui sopra.")
        raise SystemExit(1)
    misura = dimensioni_png(dati)
    Path("prova_mermaid.png").write_bytes(dati)
    print(f"✓ disegnato da: {ultimo_motore()} — {misura[0]}x{misura[1]} px, "
          f"{len(dati)} byte → prova_mermaid.png")
    if ultimo_motore() != "locale (mmdc)":
        print("  ATTENZIONE: il disegno è passato dal servizio pubblico mermaid.ink.")
        print("  Per il locale: npm install -g @mermaid-js/mermaid-cli")
        print("  Per vietare del tutto l'uscita: export MERMAID_LOCAL_ONLY=1")
