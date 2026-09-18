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

__version__ = "2026.09.18c"

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

    # `?type=png`: senza, il servizio restituisce un JPEG, e la lettura delle
    # dimensioni — fatta sull'intestazione PNG — falliva in silenzio. Il
    # risultato era la misura fissa di ripiego, cioè il diagramma schiacciato
    # che avevamo già corretto per i PNG. Tornato dalla porta di servizio.
    url = ("https://mermaid.ink/img/"
           + base64.urlsafe_b64encode(codice.encode("utf-8")).decode() + "?type=png")
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
def dimensioni_immagine(dati: bytes) -> Optional[Tuple[int, int]]:
    """Larghezza e altezza di un'immagine, qualunque sia il formato.

    Prima si leggeva solo l'intestazione PNG. Bastava che il disegno arrivasse
    come JPEG — ed è quello che il servizio esterno manda di serie — perché la
    lettura fallisse e la misura tornasse quella fissa di ripiego, 3:1. Ora:
    PNG e JPEG dall'intestazione, tutto il resto tramite PIL, che c'è comunque
    perché ReportLab la usa per mettere le immagini nel PDF."""
    if not dati or len(dati) < 24:
        return None
    if dati[:8] == b"\x89PNG\r\n\x1a\n":
        larghezza = int.from_bytes(dati[16:20], "big")
        altezza = int.from_bytes(dati[20:24], "big")
        return (larghezza, altezza) if larghezza and altezza else None
    if dati[:2] == b"\xff\xd8":   # JPEG: si cerca il segmento SOF
        i = 2
        while i + 9 < len(dati):
            if dati[i] != 0xFF:
                i += 1
                continue
            marcatore = dati[i + 1]
            if marcatore in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                altezza = int.from_bytes(dati[i + 5:i + 7], "big")
                larghezza = int.from_bytes(dati[i + 7:i + 9], "big")
                return (larghezza, altezza) if larghezza and altezza else None
            lunghezza = int.from_bytes(dati[i + 2:i + 4], "big")
            i += 2 + max(lunghezza, 2)
    try:
        from PIL import Image as _Immagine
        import io as _io
        with _Immagine.open(_io.BytesIO(dati)) as im:
            return im.size
    except Exception:
        return None


# Nome vecchio, mantenuto: chi chiamava `dimensioni_png` continua a funzionare,
# e ora funziona anche sui JPEG.
dimensioni_png = dimensioni_immagine


def misura_per_riquadro(dati: bytes, max_larghezza: float, max_altezza: float,
                        difetto=None) -> Optional[Tuple[float, float]]:
    """Le misure con cui mettere l'immagine in un riquadro SENZA deformarla.

    Se le dimensioni non si leggono torna `None`, e chi chiama decide: prima
    tornava una misura fissa 720×240, e quella misura fissa è esattamente il
    diagramma schiacciato che si voleva eliminare. Un ripiego che riproduce il
    difetto non è un ripiego."""
    misura = dimensioni_immagine(dati)
    if not misura:
        return difetto
    l, a = misura
    fattore = min(max_larghezza / l, max_altezza / a)
    return (l * fattore, a * fattore)
