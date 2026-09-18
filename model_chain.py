"""
═══════════════════════════════════════════════════════════════════════════
CATENA MODELLI — scoperta, prova, scalata.
Porting Python della catena di Nuvia (src/15_6_ai_gemini…js) esteso ai tre
provider dell'app: Azure OpenAI, Anthropic Claude, Google Gemini.

Se qui cambia una regola, deve cambiare anche in Nuvia: sono lo stesso
impianto e le costanti sono volutamente le stesse.

── COSA FA, NELL'ORDINE ──────────────────────────────────────────────────
1. SCOPERTA. Chiede al provider l'elenco dei modelli VERI di quella chiave
   e tiene solo quelli buoni per questo lavoro, ordinati dal migliore.
   Se l'elenco non si legge, si usa la catena scritta qui sotto come rete:
   l'app funziona anche con modelli usciti dopo, senza toccare il codice.
2. PROVA. Manda a ogni modello, in ordine, una domanda da due parole con un
   tetto di CINQUE secondi. Il primo che risponde ha vinto. Tetto
   complessivo DIECI secondi: se in dieci secondi nessuno ha risposto,
   nessuno risponde.
3. CHIAMATA VERA. Parte DAL MODELLO CHE HA RISPOSTO, non dal primo della
   catena, e se cade scende in giù — mai risalire a chi era già giù. Il
   modello buono si ricorda per dieci minuti, così la chiamata dopo non
   rifà la prova.
4. NESSUNO RISPONDE. Un messaggio che dice la verità: vedi MESSAGGI e la
   nota sul perché non si dice sempre «riprova più tardi».

── PERCHÉ CINQUE SECONDI PER LA PROVA ────────────────────────────────────
Una domanda da due parole torna in qualche centinaio di ms. Aspettarne
venticinque non rende la prova più affidabile: rende più lunga l'attesa che
la prova doveva togliere. Il rischio del tetto secco (una rete lenta per un
momento scambiata per modello morto) si copre con UN solo secondo tentativo,
e solo sui guasti che possono cambiare (occupato, timeout, rete). Chiave
sbagliata, quota finita e contesto pieno sono definitivi: si passa oltre.

── DIFFERENZA VOLUTA RISPETTO A NUVIA ────────────────────────────────────
· Nuvia tiene SOLO i «flash» perché è una chat: lì contano costo e velocità.
  Qui una singola analisi legge decine di migliaia di righe di legacy e la
  qualità conta più del costo, quindi la catena parte dalla fascia ALTA
  (pro / opus / modelli grandi) e scende verso le fasce economiche.
  Con `preferenza="velocita"` si ottiene esattamente la regola di Nuvia.
· Nella PROVA, «200 con testo vuoto» qui vale come vivo: i modelli che
  ragionano possono consumare il tetto di token del test prima di scrivere,
  e scartarli per questo significherebbe buttare i migliori della catena.
  La prova risponde a «questo modello risponde?», non a «risponde bene?».

── USO ───────────────────────────────────────────────────────────────────
    catena = CatenaModelli(provider="Google Gemini", chiave="AIza…")
    esito  = catena.chiedi(prompt, sistema="…", json_mode=True)
    esito.testo, esito.modello, esito.troncata
  oppure:
    try: …
    except NessunModello as e: print(catena.messaggio_nessuno(e))

── DA RIGA DI COMANDO (collaudo rapido, senza Streamlit) ─────────────────
    GEMINI_API_KEY=… python model_chain.py --provider gemini --modelli
    ANTHROPIC_API_KEY=… python model_chain.py --provider claude --prova
    GEMINI_API_KEY=… python model_chain.py --provider gemini "il tuo prompt"
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

__version__ = "2026.09.18c"

import hashlib
import json
import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

# =============================================================================
# LE COSTANTI — tutte in un posto solo. Sono i numeri di Nuvia in produzione.
# =============================================================================
CFG_BASE: Dict[str, Any] = {
    "prova_s": 5.0,             # tetto per modello, nella prova
    "prova_totale_s": 10.0,     # tetto complessivo della prova
    "vera_s": 300.0,            # la chiamata vera può durare minuti
    "memoria_s": 10 * 60,       # quanto si ricorda il modello buono
    "elenco_s": 6 * 60 * 60,    # ogni quanto rifare la scoperta
    "tentativi_vera": 3,        # riprove per modello sulla chiamata vera
    "quanti": 5,                # quante generazioni/modelli tenere in catena
    "max_token": 16000,         # tetto di output della chiamata vera
    "max_token_prova": 64,      # tetto di output della prova
    "pausa_base_s": 0.8,        # attesa fra due tentativi sullo stesso modello
}

PROMPT_PROVA = "Rispondi con una sola parola: OK."

# La richiesta di proseguire, uguale per i tre provider. In inglese perché in
# inglese è il contratto che il modello sta scrivendo.
_CONTINUA = ("Continue your previous answer exactly from the point where it stopped. "
             "Output only the remaining characters: no preamble, no code fences, do not "
             "repeat anything you already wrote. Finish the JSON object and end it with "
             "the \"complete\": true property.")

# ═══ QUANTO DEVE PENSARE IL MODELLO ═══════════════════════════════════════
# È la leva che sposta di più il tempo di risposta, molto più della scelta fra
# un modello e l'altro: lo stesso flash con il ragionamento alto ci mette
# minuti dove con quello basso ci mette secondi.
#
# Ma NON tutti i modelli accettano tutti i livelli: alcuni rifiutano i livelli
# bassi con un 400. Per questo il livello scelto è un PUNTO DI PARTENZA, non un
# ordine: se il modello lo rifiuta si sale di un gradino, si ricorda per QUEL
# modello, e la volta dopo si parte già giusti. Chi sceglie «veloce» ottiene il
# più veloce che quel modello sa fare, non un errore.
LIVELLI = ["minimal", "low", "medium", "high"]


def _su_di_uno(livello: str) -> Optional[str]:
    try:
        i = LIVELLI.index(livello)
    except ValueError:
        return "medium"
    return LIVELLI[i + 1] if i + 1 < len(LIVELLI) else None


def _almeno(scelto: str, minimo: Optional[str]) -> str:
    """Il livello davvero usabile: quello scelto, alzato al minimo che quel
    modello ha già dimostrato di pretendere."""
    if not minimo:
        return scelto
    return scelto if LIVELLI.index(scelto) >= LIVELLI.index(minimo) else minimo

# =============================================================================
# I GUASTI, IN DUE FAMIGLIE
# È la distinzione che fa funzionare tutto il resto: un guasto che può passare
# da solo merita un secondo tentativo, uno definitivo no.
# =============================================================================
RIPROVA = {"busy", "timeout", "rete", "vuota", "troncata", "parametro"}
CAMBIA = {"quota", "modello", "badkey", "blocked", "contesto"}
# i guasti che non dipendono dal modello: inutile scendere la catena
NON_SCENDERE = {"badkey", "nokey", "contesto", "endpoint"}

# =============================================================================
# IL MESSAGGIO QUANDO NON RISPONDE NESSUNO
# «Nessun modello disponibile, riprova più tardi» è la frase giusta SOLO se
# riprovare può cambiare qualcosa. Se la chiave è sbagliata o la quota è
# finita, quella frase è una bugia: la persona riproverà stasera, domani, e
# continuerà a non funzionare. Un messaggio che promette quello che il codice
# non farà è un difetto, non una gentilezza. Quindi: la frase generale quando
# il guasto è un momento, la verità quando è uno stato.
# =============================================================================
MESSAGGI: Dict[str, Dict[str, str]] = {
    "it": {
        "nessuno": "In questo momento nessuno dei modelli è disponibile. Riprova più tardi.",
        "quota": "Hai raggiunto il limite di richieste (al minuto o al giorno). Aspetta qualche minuto e riprova.",
        "badkey": "La chiave non è valida o non ha i permessi per questi modelli. Controllala: riprovare più tardi non cambierebbe nulla.",
        "nokey": "Manca la chiave: senza, non posso contattare nessun modello.",
        "endpoint": "L'endpoint non è raggiungibile o non è quello giusto. Controlla l'indirizzo: riprovare non cambierebbe nulla.",
        "blocked": "La richiesta è stata bloccata dai filtri di sicurezza del modello.",
        "contesto": "Il codice sorgente inviato supera la finestra di contesto del modello. Riduci i file o attiva l'analisi a lotti: scendere di modello non aiuta, hanno finestre uguali o più piccole.",
        "modello": "Il modello indicato non esiste su questa chiave o su questo endpoint. Controlla il nome del deployment.",
        "rete": "In questo momento nessuno dei modelli è disponibile: la rete è caduta durante la richiesta. Controlla la connessione e riprova più tardi.",
        "timeout": "Nessun modello ha risposto entro il tempo massimo. Riprova più tardi, oppure riduci la quantità di codice inviata.",
    },
    "en": {
        "nessuno": "None of the models are available right now. Please try again later.",
        "quota": "You've hit the request limit (per minute or per day). Wait a few minutes and try again.",
        "badkey": "The key is invalid or lacks permission for these models. Check it: trying again later would change nothing.",
        "nokey": "The API key is missing: without it I can't reach any model.",
        "endpoint": "The endpoint is unreachable or wrong. Check the address: retrying would change nothing.",
        "blocked": "The request was blocked by the model's safety filters.",
        "contesto": "The submitted source code exceeds the model's context window. Send fewer files or turn on batch analysis: moving down the chain won't help, those models have equal or smaller windows.",
        "modello": "That model does not exist for this key or endpoint. Check the deployment name.",
        "rete": "None of the models are available right now: the network dropped during the request. Check your connection and try again later.",
        "timeout": "No model answered within the time limit. Try again later, or send less source code.",
    },
}


class ErroreModello(Exception):
    """Un guasto su UN modello, con un NOME CORTO (quota, busy, badkey…).

    Sono quei nomi a far girare tutto il resto: chi chiama non deve leggere i
    messaggi del provider per decidere se riprovare o cambiare modello.
    """

    def __init__(self, causa: str, dettaglio: str = "", parziale: str = "", adatta: Optional[Dict[str, Any]] = None):
        super().__init__(causa)
        self.causa = causa
        self.dettaglio = dettaglio or ""
        self.parziale = parziale or ""
        self.adatta = adatta or {}


class NessunModello(Exception):
    """Nessun modello della catena ha risposto. Porta con sé l'ultima causa
    tecnica e il diario dei tentativi, per il messaggio e per il log."""

    def __init__(self, causa: str, diario: Optional[List[str]] = None):
        super().__init__(causa)
        self.causa = causa
        self.diario = diario or []


class Risposta:
    """Il risultato buono: testo, chi l'ha scritto, e se era troncato."""

    def __init__(self, testo: str, modello: str, troncata: bool = False, ms: int = 0, provider: str = ""):
        self.testo = testo
        self.modello = modello
        self.troncata = troncata
        self.ms = ms
        self.provider = provider

    def __repr__(self) -> str:  # pragma: no cover - solo per il debug
        return f"<Risposta {self.provider}/{self.modello} {len(self.testo)}c troncata={self.troncata}>"


# =============================================================================
# LA GUARDIA DEVE VINCERE COMUNQUE
# Il `timeout` di requests è per singola lettura del socket, non per la
# chiamata intera: un server che manda un byte ogni tre secondi non lo fa mai
# scattare, e il tetto dei cinque secondi smette di esistere — la prova che
# doveva togliere l'attesa diventa l'attesa. Qui la richiesta corre in un
# thread CONTRO una scadenza a orologio: chi arriva primo vince, e allo
# scadere si esce a prescindere da cosa fa il thread di sotto.
# (In Nuvia è `conAbort`, src/15_6 — stessa funzione, stesso perché.)
# =============================================================================
def con_scadenza(fn: Callable[[], Any], tetto_s: float) -> Any:
    esito: "queue.Queue[tuple]" = queue.Queue(maxsize=1)

    def corri() -> None:
        try:
            esito.put(("ok", fn()))
        except BaseException as e:  # noqa: BLE001 - va rilanciata identica a chi chiama
            try:
                esito.put(("ko", e))
            except Exception:
                pass

    t = threading.Thread(target=corri, daemon=True)
    t.start()
    try:
        stato, valore = esito.get(timeout=tetto_s)
    except queue.Empty:
        # Il thread resta appeso al socket: è daemon, morirà col processo.
        # Quello che conta è che NOI siamo usciti nel tempo promesso.
        raise ErroreModello("timeout", f"nessuna risposta entro {tetto_s:.0f}s")
    if stato == "ko":
        raise valore
    return valore


# =============================================================================
# LA MEMORIA — tre cose da ricordare, tutte piccole e tutte a scadenza:
# · il modello buono (10 minuti — un modello «giù» stamattina è su stasera, e
#   il migliore deve poter tornare in testa da solo);
# · l'elenco scoperto (6 ore);
# · gli adattamenti per modello (per sempre: sono proprietà del modello, non
#   un suo umore — vedi «il 400 che non è una chiave sbagliata»).
# Di suo è un file JSON in `cache/`. Chi ha un posto migliore (Redis, la
# sessione, un database) passa la propria `memoria`.
# =============================================================================
class MemoriaFile:
    def __init__(self, percorso: Optional[str] = None):
        # Nella cartella `cache/`, visibile e non versionata, insieme ai lotti
        # dell'applicazione: niente file nascosti accanto al codice.
        if percorso:
            self.f = Path(percorso)
        else:
            self.f = Path(__file__).parent / "cache" / "catena_modelli.json"
        self._lock = threading.Lock()

    def _leggi(self) -> Dict[str, Any]:
        try:
            return json.loads(self.f.read_text("utf-8"))
        except Exception:
            return {}

    def _scrivi(self, dati: Dict[str, Any]) -> None:
        try:
            self.f.parent.mkdir(exist_ok=True)
            tmp = self.f.with_suffix(".tmp")
            tmp.write_text(json.dumps(dati, ensure_ascii=False), "utf-8")
            tmp.replace(self.f)
        except Exception:
            pass  # la memoria è un lusso: se non si scrive, si riparte dalla prova

    def leggi_buono(self, spazio: str, entro_s: float) -> Optional[str]:
        b = (self._leggi().get(spazio) or {}).get("buono") or {}
        if b.get("m") and (time.time() - float(b.get("at", 0))) < entro_s:
            return str(b["m"])
        return None

    def scrivi_buono(self, spazio: str, modello: str) -> None:
        with self._lock:
            d = self._leggi()
            d.setdefault(spazio, {})["buono"] = {"m": modello, "at": time.time()}
            self._scrivi(d)

    def leggi_elenco(self, spazio: str, entro_s: float) -> Optional[List[str]]:
        e = (self._leggi().get(spazio) or {}).get("elenco") or {}
        if e.get("lista") and (time.time() - float(e.get("at", 0))) < entro_s:
            return list(e["lista"])
        return None

    def scrivi_elenco(self, spazio: str, lista: List[str]) -> None:
        with self._lock:
            d = self._leggi()
            d.setdefault(spazio, {})["elenco"] = {"lista": list(lista), "at": time.time()}
            self._scrivi(d)

    def leggi_adatta(self, spazio: str, modello: str) -> Dict[str, Any]:
        return dict(((self._leggi().get(spazio) or {}).get("adatta") or {}).get(modello) or {})

    def scrivi_adatta(self, spazio: str, modello: str, patch: Dict[str, Any]) -> None:
        with self._lock:
            d = self._leggi()
            a = d.setdefault(spazio, {}).setdefault("adatta", {})
            a.setdefault(modello, {}).update(patch)
            self._scrivi(d)


class MemoriaRam(MemoriaFile):
    """Stessa interfaccia, ma senza toccare il disco (collaudi, ambienti a
    sola lettura, contenitori effimeri)."""

    def __init__(self) -> None:  # noqa: D107
        self._dati: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def _leggi(self) -> Dict[str, Any]:
        return self._dati

    def _scrivi(self, dati: Dict[str, Any]) -> None:
        self._dati = dati


# =============================================================================
# I PROVIDER
# Ogni provider sa fare due cose sole: dire quali modelli esistono davvero per
# quella chiave, e chiamarne uno traducendo il proprio dialetto di errori nei
# NOMI CORTI comuni. Tutto il resto (prova, scalata, memoria, messaggi) è
# scritto una volta sola e vale per tutti e tre.
# =============================================================================
def _versione(nome: str) -> float:
    """Il numero di versione dentro un nome, per ordinare: gemini-3.7-flash →
    3.7, claude-sonnet-4-5-20250929 → 4.5, gpt-4o → 4.0."""
    n = nome.lower()
    m = re.search(r"(?:gemini|gpt|claude[a-z-]*?)-(\d+)[._-](\d+)(?!\d)", n)
    if m and not re.match(r"^\d{6,}$", m.group(2)):
        return int(m.group(1)) + int(m.group(2)) / 10.0
    m = re.search(r"-(\d+)(?:\b|-)", n)
    return float(m.group(1)) if m else 0.0


class Provider:
    nome = "?"
    catena_rete: List[str] = []
    # fasce, dalla migliore alla peggiore, per la preferenza "qualita"
    fasce_qualita: List[str] = []
    fasce_velocita: List[str] = []

    def __init__(self, chiave: str, endpoint: str = "", api_version: str = ""):
        self.chiave = (chiave or "").strip()
        self.endpoint = (endpoint or "").strip().rstrip("/")
        self.api_version = (api_version or "").strip()

    # -- identità della memoria: provider + endpoint + impronta della chiave.
    #    Della chiave si salva SOLO l'impronta: due chiavi diverse non si
    #    scambiano la cache, e la chiave non finisce mai su disco.
    def spazio(self) -> str:
        impronta = hashlib.sha256((self.chiave or "-").encode()).hexdigest()[:10]
        return f"{self.nome}|{self.endpoint}|{impronta}"

    def elenco(self, tetto_s: float) -> List[str]:  # pragma: no cover - sovrascritto
        raise NotImplementedError

    def chiama(self, modello: str, prompt: str, **o: Any) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    # -- ordinamento comune: prima la fascia, poi la versione più alta ------
    def ordina(self, modelli: List[str], preferenza: str) -> List[str]:
        fasce = self.fasce_velocita if preferenza == "velocita" else self.fasce_qualita

        def rango(n: str) -> tuple:
            basso = n.lower()
            for i, f in enumerate(fasce):
                if f in basso:
                    return (i, -_versione(n), n)
            return (len(fasce), -_versione(n), n)

        tenuti = [m for m in modelli if any(f in m.lower() for f in fasce)] or list(modelli)
        return sorted(tenuti, key=rango)

    # -- traduzione comune degli errori di trasporto ------------------------
    @staticmethod
    def _rete(e: Exception) -> ErroreModello:
        testo = str(e)
        if isinstance(e, requests.exceptions.Timeout):
            return ErroreModello("timeout", testo)
        return ErroreModello("rete", testo)


class GeminiProvider(Provider):
    nome = "Google Gemini"
    base = "https://generativelanguage.googleapis.com/v1beta"
    catena_rete = ["gemini-3-pro", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"]
    fasce_qualita = ["pro", "flash"]
    fasce_velocita = ["flash"]
    versione_min = 2.0  # sotto la 2 la finestra è piccola e i JSON schema non reggono

    def elenco(self, tetto_s: float) -> List[str]:
        url = f"{self.base}/models?key={requests.utils.quote(self.chiave)}&pageSize=200"
        r = con_scadenza(lambda: requests.get(url, timeout=(5, tetto_s)), tetto_s + 2)
        if r.status_code in (401, 403):
            raise ErroreModello("badkey", r.text[:300])
        if not r.ok:
            raise ErroreModello("busy", f"HTTP {r.status_code}")
        modelli = r.json().get("models", []) or []
        nomi = []
        for m in modelli:
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            n = str(m.get("name", "")).replace("models/", "")
            # COSA VOGLIAMO: gemini pieni dalla 2 in su.
            # COSA NON VOGLIAMO: preview/exp (cambiano sotto i piedi), lite
            # (qualità), embedding/tts/vision/live (altro mestiere), `latest` e
            # i nomi con data (puntano a modelli che si spostano).
            if not re.match(r"^gemini-\d", n):
                continue
            if re.search(r"preview|exp|experimental|latest|-lite\b|\d{3,}", n):
                continue
            if re.search(r"embedding|aqa|image|tts|audio|native|vision|live|realtime|dialog|robotics", n):
                continue
            if _versione(n) < self.versione_min:
                continue
            nomi.append(n)
        if not nomi:
            raise ErroreModello("modello", "nessun gemini utilizzabile in elenco")
        return nomi

    def chiama(self, modello: str, prompt: str, **o: Any) -> Dict[str, Any]:
        tetto = float(o.get("tetto_s", CFG_BASE["vera_s"]))
        adatta = dict(o.get("adatta") or {})
        cfg: Dict[str, Any] = {
            "maxOutputTokens": int(o.get("max_token", CFG_BASE["max_token"])),
            "temperature": 0,
        }
        if not adatta.get("no_thinking"):
            cfg["thinkingConfig"] = {
                "thinkingLevel": _almeno(o.get("ragionamento") or "low", adatta.get("thinking_min"))}
        if o.get("json_mode") and not adatta.get("no_json_mode"):
            cfg["responseMimeType"] = "application/json"
            # Lo schema imposto è la garanzia più forte sui nomi dei campi, ma
            # non tutti i modelli lo accettano: se questo l'ha già rifiutato una
            # volta, si riparte senza, invece di risbatterci contro.
            if o.get("schema") and not adatta.get("no_schema"):
                cfg["responseSchema"] = o["schema"]
        contenuti = [{"role": "user", "parts": [{"text": prompt}]}]
        if o.get("parziale"):
            # Continuazione: il pezzo già scritto torna come turno del modello,
            # seguito dalla richiesta di proseguire. In modo testo, non JSON:
            # il seguito da solo non è un JSON valido e uno schema lo
            # rifiuterebbe.
            contenuti.append({"role": "model", "parts": [{"text": o["parziale"]}]})
            contenuti.append({"role": "user", "parts": [{"text": _CONTINUA}]})
            cfg.pop("responseMimeType", None)
            cfg.pop("responseSchema", None)
        corpo: Dict[str, Any] = {"contents": contenuti, "generationConfig": cfg}
        if o.get("sistema"):
            corpo["systemInstruction"] = {"parts": [{"text": o["sistema"]}]}
        url = f"{self.base}/models/{modello}:generateContent?key={requests.utils.quote(self.chiave)}"

        def fai():
            return requests.post(url, json=corpo, timeout=(5, tetto),
                                 headers={"Content-Type": "application/json"})

        try:
            r = con_scadenza(fai, tetto)
        except requests.exceptions.RequestException as e:
            raise self._rete(e)
        self._stato(r, modello, o)
        j = r.json()
        if (j.get("promptFeedback") or {}).get("blockReason"):
            raise ErroreModello("blocked", str(j["promptFeedback"]["blockReason"]))
        cand = (j.get("candidates") or [{}])[0]
        if cand.get("finishReason") in ("SAFETY", "RECITATION"):
            raise ErroreModello("blocked", str(cand.get("finishReason")))
        testo = "".join(p.get("text", "") for p in ((cand.get("content") or {}).get("parts") or []))
        if cand.get("finishReason") == "MAX_TOKENS":
            # Una risposta troncata NON si butta: il chiamante decide.
            raise ErroreModello("troncata", "MAX_TOKENS", parziale=testo)
        if not testo.strip():
            raise ErroreModello("vuota", str(cand.get("finishReason") or ""))
        return {"testo": testo, "uso": j.get("usageMetadata") or {}}

    def _stato(self, r, modello: str, o: Dict[str, Any]) -> None:
        if r.ok:
            return
        if r.status_code == 429:
            raise ErroreModello("quota", r.text[:300])
        if r.status_code == 404:
            raise ErroreModello("modello", r.text[:300])
        if r.status_code in (500, 502, 503, 504):
            raise ErroreModello("busy", f"HTTP {r.status_code}")
        if r.status_code == 400:
            det = r.text[:600]
            # IL 400 CHE NON È UNA CHIAVE SBAGLIATA. Un parametro rifiutato dal
            # modello (schema, mime, thinking) trattato come «chiave non
            # valida» scarterebbe il modello MIGLIORE della catena con la
            # diagnosi sbagliata, e manderebbe la persona a rigenerare una
            # chiave sana. Quindi il corpo si legge PRIMA di dare la colpa.
            if re.search(r"context|token count|too (?:large|long)|exceeds", det, re.I):
                raise ErroreModello("contesto", det)
            gia = dict(o.get("adatta") or {})
            if re.search(r"thinking", det, re.I):
                # IL 400 SUL THINKING. Questo modello non accetta il livello
                # chiesto: si sale di un gradino e si riprova. Non è la chiave,
                # non è il modello: è il parametro. Trattarlo come «chiave non
                # valida» scarterebbe il modello migliore della catena con la
                # diagnosi sbagliata.
                usato = _almeno(o.get("ragionamento") or "low", gia.get("thinking_min"))
                su = _su_di_uno(usato)
                patch = {"thinking_min": su} if su else {"no_thinking": True}
                raise ErroreModello("parametro", det, adatta=patch)
            if re.search(r"schema|responseMimeType|generationConfig|json", det, re.I):
                # Si scende di un gradino per volta: prima si toglie lo schema,
                # e solo se non basta si rinuncia anche al modo JSON.
                patch = {"no_json_mode": True} if gia.get("no_schema") else {"no_schema": True}
                raise ErroreModello("parametro", det, adatta=patch)
            raise ErroreModello("badkey", det)
        if r.status_code in (401, 403):
            raise ErroreModello("badkey", r.text[:300])
        raise ErroreModello("busy" if r.status_code >= 500 else "badkey", f"HTTP {r.status_code}")


class ClaudeProvider(Provider):
    nome = "Anthropic Claude"
    base = "https://api.anthropic.com/v1"
    versione_api = "2023-06-01"
    catena_rete = ["claude-opus-4-1", "claude-sonnet-4-5", "claude-haiku-4-5"]
    fasce_qualita = ["opus", "sonnet", "haiku"]
    fasce_velocita = ["haiku", "sonnet", "opus"]

    def _testate(self) -> Dict[str, str]:
        return {
            "x-api-key": self.chiave,
            "anthropic-version": self.versione_api,
            "Content-Type": "application/json",
        }

    def elenco(self, tetto_s: float) -> List[str]:
        url = f"{self.base}/models?limit=100"
        r = con_scadenza(lambda: requests.get(url, headers=self._testate(), timeout=(5, tetto_s)), tetto_s + 2)
        if r.status_code in (401, 403):
            raise ErroreModello("badkey", r.text[:300])
        if not r.ok:
            raise ErroreModello("busy", f"HTTP {r.status_code}")
        # L'elenco arriva già dal più recente al più vecchio.
        nomi = [str(m.get("id", "")) for m in (r.json().get("data") or []) if m.get("id")]
        nomi = [n for n in nomi if re.match(r"^claude-", n) and not re.search(r"latest", n)]
        if not nomi:
            raise ErroreModello("modello", "nessun claude in elenco")
        return nomi

    def ordina(self, modelli: List[str], preferenza: str) -> List[str]:
        # L'ordine dell'API è già «più recente prima»: lo si usa come criterio
        # secondario invece di indovinare la versione dalla data nel nome.
        fasce = self.fasce_velocita if preferenza == "velocita" else self.fasce_qualita
        posizione = {n: i for i, n in enumerate(modelli)}

        def rango(n: str) -> tuple:
            basso = n.lower()
            for i, f in enumerate(fasce):
                if f in basso:
                    return (i, posizione.get(n, 999))
            return (len(fasce), posizione.get(n, 999))

        tenuti = [m for m in modelli if any(f in m.lower() for f in fasce)] or list(modelli)
        return sorted(tenuti, key=rango)

    def chiama(self, modello: str, prompt: str, **o: Any) -> Dict[str, Any]:
        tetto = float(o.get("tetto_s", CFG_BASE["vera_s"]))
        adatta = dict(o.get("adatta") or {})
        ragionamento = _almeno(o.get("ragionamento") or "low", adatta.get("thinking_min"))
        pensa = ragionamento in ("medium", "high") and not adatta.get("no_thinking")
        messaggi: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]
        # PREFILL: si apre la risposta con «{» al posto del modello. Costa
        # zero e toglie alla radice preamboli e recinti markdown, che erano la
        # prima causa di JSON non parsabile su questo provider.
        # Con il ragionamento esteso il prefill non è ammesso, e si rinuncia:
        # le difese a valle (estrai_json, ripara_troncato) bastano.
        prefill = "{" if (o.get("json_mode") and not pensa) else ""
        if o.get("parziale"):
            if pensa:
                # Con il ragionamento esteso il prefill non è ammesso: il pezzo
                # scritto torna come turno precedente e si chiede il seguito.
                messaggi.append({"role": "assistant", "content": o["parziale"]})
                messaggi.append({"role": "user", "content": _CONTINUA})
                prefill = ""
            else:
                # Il modo migliore che esista: il pezzo scritto diventa il
                # prefill, e il modello continua LA STESSA frase, senza
                # nemmeno sapere di essersi fermato.
                prefill = o["parziale"].rstrip()
        if prefill:
            messaggi.append({"role": "assistant", "content": prefill})
        corpo: Dict[str, Any] = {
            "model": modello,
            "max_tokens": int(o.get("max_token", CFG_BASE["max_token"])),
            "temperature": 0,
            "messages": messaggi,
        }
        if o.get("sistema"):
            corpo["system"] = o["sistema"]
        if pensa:
            # Il budget di ragionamento si scala DENTRO max_tokens, quindi il
            # tetto va alzato: altrimenti il modello pensa e non gli resta
            # spazio per scrivere. E con il thinking la temperatura dev'essere
            # quella di serie, non zero.
            budget = 4000 if ragionamento == "medium" else 10000
            corpo["thinking"] = {"type": "enabled", "budget_tokens": budget}
            corpo["max_tokens"] = max(int(corpo["max_tokens"]), budget + 8000)
            corpo.pop("temperature", None)

        def fai():
            return requests.post(f"{self.base}/messages", headers=self._testate(), json=corpo,
                                 timeout=(5, tetto))

        try:
            r = con_scadenza(fai, tetto)
        except requests.exceptions.RequestException as e:
            raise self._rete(e)
        self._stato(r)
        j = r.json()
        testo = prefill + "".join(b.get("text", "") for b in (j.get("content") or []) if b.get("type") == "text")
        if j.get("stop_reason") == "max_tokens":
            raise ErroreModello("troncata", "max_tokens", parziale=testo)
        if not testo.strip():
            raise ErroreModello("vuota", str(j.get("stop_reason") or ""))
        return {"testo": testo, "uso": j.get("usage") or {}}

    def _stato(self, r) -> None:
        if r.ok:
            return
        tipo = ""
        try:
            tipo = str(((r.json() or {}).get("error") or {}).get("type") or "")
        except Exception:
            pass
        det = r.text[:600]
        if r.status_code == 429 or tipo == "rate_limit_error":
            raise ErroreModello("quota", det)
        if r.status_code == 404 or tipo == "not_found_error":
            raise ErroreModello("modello", det)
        if r.status_code in (500, 502, 503, 529) or tipo in ("overloaded_error", "api_error"):
            raise ErroreModello("busy", det)
        if r.status_code in (401, 403) or tipo in ("authentication_error", "permission_error"):
            raise ErroreModello("badkey", det)
        if r.status_code == 400:
            if re.search(r"context|too (?:large|long)|max.*token|exceed", det, re.I):
                raise ErroreModello("contesto", det)
            if re.search(r"thinking|budget_tokens", det, re.I):
                raise ErroreModello("parametro", det, adatta={"no_thinking": True})
            if re.search(r"temperature|top_p|unexpected", det, re.I):
                raise ErroreModello("parametro", det, adatta={"no_temperature": True})
            raise ErroreModello("badkey", det)
        raise ErroreModello("busy" if r.status_code >= 500 else "badkey", det)


class AzureProvider(Provider):
    nome = "Microsoft Azure OpenAI"
    catena_rete = ["gpt-4o", "gpt-4o-mini"]
    fasce_qualita = ["o3", "gpt-5", "gpt-4.1", "gpt-4o", "gpt-4", "gpt-35", "mini"]
    fasce_velocita = ["mini", "gpt-4o", "gpt-4.1", "gpt-4"]

    def __init__(self, chiave: str, endpoint: str = "", api_version: str = "", deployment: str = ""):
        super().__init__(chiave, endpoint, api_version or "2024-10-21")
        # Su Azure il nome che si chiama è quello del DEPLOYMENT, deciso da chi
        # ha creato la risorsa: non è derivabile dal nome del modello. Perciò
        # il deployment scritto a mano resta sempre il primo della catena.
        self.deployment = (deployment or "").strip()

    def _testate(self) -> Dict[str, str]:
        # Si mandano entrambe: l'API classica vuole `api-key`, la superficie
        # /openai/v1 accetta il Bearer. Mandarle tutte e due evita un giro di
        # tentativi solo per indovinare quale versione è attiva.
        return {
            "api-key": self.chiave,
            "Authorization": f"Bearer {self.chiave}",
            "Content-Type": "application/json",
        }

    def elenco(self, tetto_s: float) -> List[str]:
        if not self.endpoint:
            raise ErroreModello("endpoint", "endpoint Azure mancante")
        url = f"{self.endpoint}/openai/deployments?api-version={self.api_version}"
        try:
            r = con_scadenza(lambda: requests.get(url, headers=self._testate(), timeout=(5, tetto_s)), tetto_s + 2)
        except requests.exceptions.RequestException as e:
            raise self._rete(e)
        if r.status_code in (401, 403):
            raise ErroreModello("badkey", r.text[:300])
        if not r.ok:
            raise ErroreModello("busy", f"HTTP {r.status_code}")
        dati = (r.json() or {}).get("data") or []
        nomi = []
        for d in dati:
            nome = str(d.get("id") or "")
            # `model` dice qual è il modello sotto: serve per ordinare per
            # fascia anche quando il deployment si chiama «prod-01».
            sotto = str(d.get("model") or "")
            stato = str(d.get("status") or "succeeded")
            if not nome or stato not in ("succeeded", "updating", ""):
                continue
            if re.search(r"embedding|whisper|tts|dall-e|sora", (nome + sotto).lower()):
                continue
            nomi.append(nome + ("\u0000" + sotto if sotto else ""))
        if not nomi:
            raise ErroreModello("modello", "nessun deployment utilizzabile")
        return nomi

    def ordina(self, modelli: List[str], preferenza: str) -> List[str]:
        # I nomi arrivano come «deployment\0modello-sotto»: si ordina sul
        # modello sotto e si restituisce il nome del deployment.
        fasce = self.fasce_velocita if preferenza == "velocita" else self.fasce_qualita
        coppie = [(m.split("\u0000")[0], (m.split("\u0000") + [""])[1]) for m in modelli]

        def rango(c) -> tuple:
            base = (c[1] or c[0]).lower()
            for i, f in enumerate(fasce):
                if f in base:
                    return (i, -_versione(base), c[0])
            return (len(fasce), -_versione(base), c[0])

        ordinati = [c[0] for c in sorted(coppie, key=rango)]
        if self.deployment:
            ordinati = [self.deployment] + [n for n in ordinati if n != self.deployment]
        return ordinati

    def chiama(self, modello: str, prompt: str, **o: Any) -> Dict[str, Any]:
        if not self.endpoint:
            raise ErroreModello("endpoint", "endpoint Azure mancante")
        tetto = float(o.get("tetto_s", CFG_BASE["vera_s"]))
        adatta = dict(o.get("adatta") or {})
        messaggi: List[Dict[str, str]] = []
        if o.get("sistema"):
            messaggi.append({"role": "system", "content": o["sistema"]})
        messaggi.append({"role": "user", "content": prompt})
        if o.get("parziale"):
            messaggi.append({"role": "assistant", "content": o["parziale"]})
            messaggi.append({"role": "user", "content": _CONTINUA})
        corpo: Dict[str, Any] = {"model": modello, "messages": messaggi}
        campo_token = "max_completion_tokens" if adatta.get("max_completion_tokens") else "max_tokens"
        corpo[campo_token] = int(o.get("max_token", CFG_BASE["max_token"]))
        if not adatta.get("no_temperature"):
            corpo["temperature"] = 0
        if o.get("json_mode") and not adatta.get("no_json_mode") and not o.get("parziale"):
            corpo["response_format"] = {"type": "json_object"}
        # `reasoning_effort` esiste solo sui modelli che ragionano: mandarlo a
        # un gpt-4o costa un 400 e un giro a vuoto. Si guarda il nome prima, e
        # l'adattamento resta come rete per i nomi che non riconosciamo.
        if (re.search(r"\b(o\d|gpt-5|reason)", modello, re.I)
                and not adatta.get("no_reasoning")):
            corpo["reasoning_effort"] = _almeno(o.get("ragionamento") or "low",
                                                adatta.get("thinking_min"))
            corpo.pop("temperature", None)
        url = f"{self.endpoint}/openai/deployments/{modello}/chat/completions?api-version={self.api_version}"

        def fai():
            return requests.post(url, headers=self._testate(), json=corpo, timeout=(5, tetto))

        try:
            r = con_scadenza(fai, tetto)
        except requests.exceptions.RequestException as e:
            raise self._rete(e)
        self._stato(r, o)
        j = r.json()
        scelta = (j.get("choices") or [{}])[0]
        testo = ((scelta.get("message") or {}).get("content")) or ""
        if scelta.get("finish_reason") == "length":
            raise ErroreModello("troncata", "length", parziale=testo)
        if scelta.get("finish_reason") == "content_filter":
            raise ErroreModello("blocked", "content_filter")
        if not testo.strip():
            raise ErroreModello("vuota", str(scelta.get("finish_reason") or ""))
        return {"testo": testo, "uso": j.get("usage") or {}}

    def _stato(self, r, o: Optional[Dict[str, Any]] = None) -> None:
        o = o or {}
        if r.ok:
            return
        det = r.text[:600]
        if r.status_code == 429:
            raise ErroreModello("quota", det)
        if r.status_code == 404:
            raise ErroreModello("modello", det)
        if r.status_code in (500, 502, 503, 504):
            raise ErroreModello("busy", det)
        if r.status_code in (401, 403):
            raise ErroreModello("badkey", det)
        if r.status_code == 400:
            # Stessa lezione del 400 di Gemini, con i parametri di OpenAI: i
            # modelli che ragionano rifiutano `max_tokens` e `temperature`.
            # Sono guasti DEL PARAMETRO, non della chiave: si adatta e si
            # riprova, e la volta dopo si parte già giusti.
            if re.search(r"context length|maximum context|too many tokens|reduce the length", det, re.I):
                raise ErroreModello("contesto", det)
            if re.search(r"max_tokens.*not supported|max_completion_tokens", det, re.I):
                raise ErroreModello("parametro", det, adatta={"max_completion_tokens": True})
            if re.search(r"temperature", det, re.I):
                raise ErroreModello("parametro", det, adatta={"no_temperature": True})
            if re.search(r"reasoning_effort|reasoning", det, re.I):
                gia = dict(o.get("adatta") or {})
                usato = _almeno(o.get("ragionamento") or "low", gia.get("thinking_min"))
                su = _su_di_uno(usato)
                # Il valore può essere rifiutato perché è troppo basso per quel
                # modello (si sale), oppure perché il modello non ragiona
                # affatto (si toglie del tutto).
                patch = ({"thinking_min": su} if su and re.search(r"value|invalid|support", det, re.I)
                         else {"no_reasoning": True})
                raise ErroreModello("parametro", det, adatta=patch)
            if re.search(r"response_format|json_object|json_schema", det, re.I):
                raise ErroreModello("parametro", det, adatta={"no_json_mode": True})
            raise ErroreModello("badkey", det)
        raise ErroreModello("busy" if r.status_code >= 500 else "badkey", det)


PROVIDER = {
    "Google Gemini": GeminiProvider,
    "Anthropic Claude": ClaudeProvider,
    "Microsoft Azure OpenAI": AzureProvider,
}
ALIAS = {"gemini": "Google Gemini", "claude": "Anthropic Claude",
         "anthropic": "Anthropic Claude", "azure": "Microsoft Azure OpenAI",
         "openai": "Microsoft Azure OpenAI"}


# =============================================================================
# LA FABBRICA
# =============================================================================
class CatenaModelli:
    def __init__(self, provider: str, chiave: str, endpoint: str = "", api_version: str = "",
                 deployment: str = "", preferenza: str = "qualita",
                 ragionamento: str = "low", lingua: str = "it", preferito: str = "",
                 cfg: Optional[Dict[str, Any]] = None, memoria: Optional[MemoriaFile] = None,
                 log: Optional[Callable[[str], None]] = None):
        nome = ALIAS.get(str(provider).lower(), provider)
        if nome not in PROVIDER:
            raise ValueError(f"Provider non gestito: {provider}")
        self.C = dict(CFG_BASE)
        self.C.update(cfg or {})
        self.lingua = "en" if lingua == "en" else "it"
        self.preferenza = "velocita" if preferenza == "velocita" else "qualita"
        self.ragionamento = ragionamento if ragionamento in LIVELLI else "low"
        # Il modello scelto a mano va IN TESTA alla catena, per qualunque
        # provider; gli altri restano sotto come rete. Prima questo valore
        # contava solo per Azure (dove è il nome del deployment): su Gemini e
        # Claude il campo «Preferred model» non faceva niente, e nessuno se ne
        # accorgeva perché la catena andava comunque.
        self.preferito = (preferito or deployment or "").strip()
        self.log = log or (lambda s: None)
        self.memoria = memoria if memoria is not None else MemoriaFile()
        self.diario: List[str] = []
        klass = PROVIDER[nome]
        if klass is AzureProvider:
            self.p = AzureProvider(chiave, endpoint, api_version, deployment)
        else:
            self.p = klass(chiave, endpoint, api_version)
        self.nome_provider = nome

    # ── traccia: va nel log dell'app E nel diario mostrato a schermo ──────
    def _nota(self, riga: str) -> None:
        self.diario.append(riga)
        self.log(riga)

    # ═══ 1 · LA SCOPERTA ═════════════════════════════════════════════════
    def catena(self, forza: bool = False) -> Dict[str, Any]:
        spazio = self.p.spazio()
        if not self.p.chiave:
            return {"lista": list(self.p.catena_rete), "fonte": "rete (nessuna chiave)"}
        if not forza:
            salvato = self.memoria.leggi_elenco(spazio, self.C["elenco_s"])
            if salvato:
                return {"lista": salvato, "fonte": "memoria"}
        try:
            grezzi = self.p.elenco(tetto_s=min(10.0, self.C["prova_totale_s"]))
            lista = self.p.ordina(grezzi, self.preferenza)[: int(self.C["quanti"])]
            if not lista:
                raise ErroreModello("modello", "elenco vuoto dopo i filtri")
            self.memoria.scrivi_elenco(spazio, lista)
            return {"lista": lista, "fonte": "provider"}
        except Exception as e:
            # La scoperta che fallisce NON è un guasto da mostrare: l'app
            # continua con la catena scritta, che è il suo mestiere.
            causa = getattr(e, "causa", None) or str(e)
            self._nota(f"discovery failed ({causa}): using the built-in chain")
            rete = list(self.p.catena_rete)
            dep = getattr(self.p, "deployment", "")
            if dep:
                rete = [dep] + [n for n in rete if n != dep]
            return {"lista": rete, "fonte": f"rete ({causa})"}

    @staticmethod
    def _in_testa(lista: List[str], m: Optional[str]) -> List[str]:
        """Il modello buono va IN TESTA; gli altri restano dietro come rete."""
        return [m] + [x for x in lista if x != m] if m and m in lista else list(lista)

    # ═══ UNA CHIAMATA, CON GLI ADATTAMENTI RICORDATI ═════════════════════
    def _chiama_uno(self, modello: str, prompt: str, **o: Any) -> Dict[str, Any]:
        spazio = self.p.spazio()
        o = dict(o)
        o.setdefault("ragionamento", self.ragionamento)
        o["adatta"] = self.memoria.leggi_adatta(spazio, modello)
        try:
            return self.p.chiama(modello, prompt, **o)
        except ErroreModello as e:
            if e.causa == "parametro" and e.adatta:
                # Si ricorda per QUEL modello: la volta dopo si parte già dal
                # parametro giusto, senza spendere un tentativo.
                self.memoria.scrivi_adatta(spazio, modello, e.adatta)
            raise

    # ═══ 2 · LA PROVA: SCENDE LA CATENA, CON DUE TETTI ═══════════════════
    # Un tetto per modello (5 s, con la guardia a orologio) e uno complessivo
    # (10 s). Il secondo tentativo sullo stesso modello si fa solo se restano
    # almeno altri cinque secondi: altrimenti la seconda chance è il modello
    # dopo, che vale di più.
    def prova(self, catena: List[str]) -> Dict[str, Any]:
        if not self.p.chiave:
            return {"ok": False, "causa": "nokey"}
        t0 = time.time()
        ultima = "timeout"
        for m in catena:
            if time.time() - t0 >= self.C["prova_totale_s"]:
                break
            tentativo, adattamenti = 0, 0
            while True:
                t1 = time.time()
                try:
                    # La prova va al livello di ragionamento più basso: è una
                    # domanda da due parole, e farla pensare vanificherebbe il
                    # tetto dei cinque secondi che la prova esiste per rispettare.
                    self._chiama_uno(m, PROMPT_PROVA, tetto_s=self.C["prova_s"],
                                     max_token=self.C["max_token_prova"], json_mode=False,
                                     ragionamento="minimal")
                    self._nota(f"  {m}: answered in {int((time.time()-t1)*1000)} ms")
                    self.memoria.scrivi_buono(self.p.spazio(), m)
                    return {"ok": True, "modello": m}
                except ErroreModello as e:
                    if e.causa in ("vuota", "troncata"):
                        # Vivo: ha risposto, semplicemente non aveva spazio per
                        # scrivere. Per la prova basta e avanza.
                        self._nota(f"  {m}: answered empty but answered ({int((time.time()-t1)*1000)} ms)")
                        self.memoria.scrivi_buono(self.p.spazio(), m)
                        return {"ok": True, "modello": m}
                    ultima = e.causa
                    self._nota(f"  {m}: {e.causa} after {int((time.time()-t1)*1000)} ms")
                    if e.causa in NON_SCENDERE:
                        return {"ok": False, "causa": e.causa}
                    resta = time.time() - t0 < self.C["prova_totale_s"] - self.C["prova_s"]
                    # UN ADATTAMENTO NON È UN FALLIMENTO. Il modello ha detto
                    # quale parametro non gli va bene: la richiesta è cambiata,
                    # quindi il tentativo successivo è una cosa diversa dalla
                    # precedente e non deve consumare la seconda chance, che
                    # serve ai guasti veri. La scala del ragionamento ha tre
                    # gradini: con due soli tentativi non arriverebbe in cima.
                    if e.causa == "parametro" and adattamenti < 3 and resta:
                        adattamenti += 1
                        continue
                    if e.causa in RIPROVA and tentativo == 0 and resta:
                        tentativo += 1
                        continue
                    break
                except Exception as e:  # noqa: BLE001
                    ultima = "rete"
                    self._nota(f"  {m}: unexpected {type(e).__name__} ({e})")
                    break
        return {"ok": False, "causa": ultima}

    # ═══ 3 · LA CHIAMATA VERA ════════════════════════════════════════════
    # Parte dal modello buono e scende SOLO in giù: risalire a chi era già giù
    # significa pagare tre tentativi e le attese per sapere una cosa che
    # sappiamo già.
    def chiamata_vera(self, catena: List[str], buono: str, prompt: str, **o: Any) -> Risposta:
        da = max(0, catena.index(buono)) if buono in catena else 0
        ultima = "nessuno"
        for m in catena[da:]:
            tentativo, adattamenti = 0, 0
            while tentativo < int(self.C["tentativi_vera"]):
                t1 = time.time()
                try:
                    r = self._chiama_uno(m, prompt, tetto_s=self.C["vera_s"],
                                         max_token=o.get("max_token", self.C["max_token"]),
                                         json_mode=o.get("json_mode", False),
                                         schema=o.get("schema"), sistema=o.get("sistema"),
                                         ragionamento=o.get("ragionamento", self.ragionamento))
                    ms = int((time.time() - t1) * 1000)
                    self._nota(f"  {m}: answer in {ms} ms ({len(r['testo'])} characters)")
                    self.memoria.scrivi_buono(self.p.spazio(), m)
                    return Risposta(r["testo"], m, False, ms, self.nome_provider)
                except ErroreModello as e:
                    ultima = e.causa
                    self._nota(f"  {m}: {e.causa} (attempt {tentativo+1}/{int(self.C['tentativi_vera'])})")
                    # Una risposta TAGLIATA non è un guasto: è una risposta a
                    # metà, dello stesso modello, che va CONTINUATA. Ripetere
                    # lo stesso prompt non la accorcia, e cambiare modello
                    # butta via il pezzo scritto per rifarlo con un altro che
                    # scriverà altrettanto. Si consegna subito, marcata, e chi
                    # chiama chiede il seguito con `continua`.
                    if e.causa == "troncata" and e.parziale.strip():
                        return Risposta(e.parziale, m, True, int((time.time() - t1) * 1000), self.nome_provider)
                    if e.causa == "parametro":
                        # Adattato e ricordato: si riprova con la richiesta
                        # corretta, senza consumare i tentativi veri.
                        adattamenti += 1
                        if adattamenti <= 4:
                            continue
                        break
                    if e.causa in CAMBIA:
                        break
                    if e.causa in RIPROVA:
                        tentativo += 1
                        time.sleep(self.C["pausa_base_s"] * tentativo)
                        continue
                    break
                except Exception as e:  # noqa: BLE001
                    ultima = "rete"
                    self._nota(f"  {m}: unexpected {type(e).__name__} ({e})")
                    break
            if ultima in NON_SCENDERE:
                break
        raise NessunModello(ultima, list(self.diario))

    # ═══ LA CONTINUAZIONE: stesso modello, dallo stesso punto ════════════
    # Niente scoperta, niente prova, niente scalata: il modello è quello che
    # ha scritto la prima parte, e solo lui sa proseguirla con la stessa voce.
    # Se è occupato si riprova con lui; se è definitivamente giù si fallisce,
    # non si passa a un altro — un altro ricomincerebbe da capo.
    def continua(self, modello: str, prompt: str, parziale: str, **o: Any) -> Risposta:
        ultima = "nessuno"
        tentativo, adattamenti = 0, 0
        while tentativo < int(self.C["tentativi_vera"]):
            t1 = time.time()
            try:
                r = self._chiama_uno(modello, prompt, tetto_s=self.C["vera_s"],
                                     max_token=o.get("max_token", self.C["max_token"]),
                                     json_mode=False, sistema=o.get("sistema"),
                                     ragionamento=o.get("ragionamento", self.ragionamento),
                                     parziale=parziale)
                ms = int((time.time() - t1) * 1000)
                self._nota(f"  {modello}: continued in {ms} ms (+{len(r['testo'])} characters)")
                return Risposta(r["testo"], modello, False, ms, self.nome_provider)
            except ErroreModello as e:
                ultima = e.causa
                self._nota(f"  {modello}: {e.causa} while continuing (attempt {tentativo+1})")
                if e.causa == "troncata" and e.parziale.strip():
                    return Risposta(e.parziale, modello, True, int((time.time() - t1) * 1000),
                                    self.nome_provider)
                if e.causa == "parametro":
                    adattamenti += 1
                    if adattamenti <= 4:
                        continue
                    break
                if e.causa in RIPROVA:
                    tentativo += 1
                    time.sleep(self.C["pausa_base_s"] * tentativo)
                    continue
                break
            except Exception as e:  # noqa: BLE001
                ultima = "rete"
                self._nota(f"  {modello}: unexpected {type(e).__name__} ({e})")
                break
        raise NessunModello(ultima, list(self.diario))

    def successivo(self, modello: str) -> Optional[str]:
        """Il modello che viene dopo nella catena: quello a cui passare il
        seguito quando chi ha scritto la prima parte non risponde più. Non si
        sceglie da soli — è la persona a decidere — ma bisogna sapere chi è."""
        lista = self.catena()["lista"]
        if self.preferito and self.preferito in lista:
            lista = self._in_testa(lista, self.preferito)
        candidati = [m for m in lista if m != modello]
        if modello in lista:
            dopo = lista[lista.index(modello) + 1:]
            candidati = dopo + [m for m in lista[:lista.index(modello)]]
        return candidati[0] if candidati else None

    # ═══ IL FILO: scoperta → buono in memoria o prova → chiamata ═════════
    def chiedi(self, prompt: str, **o: Any) -> Risposta:
        esito = self.catena(forza=o.get("forza_elenco", False))
        lista, fonte = esito["lista"], esito["fonte"]
        # Un modello per riga: nella barra laterale una riga sola veniva
        # tagliata a metà e non si leggeva più nessun nome.
        self._nota(f"chain ({fonte}):")
        for _i, _m in enumerate(lista, start=1):
            self._nota(f"  {_i}. {_m}")
        if not self.p.chiave:
            raise NessunModello("nokey", list(self.diario))

        buono = self.memoria.leggi_buono(self.p.spazio(), self.C["memoria_s"])
        if self.preferito:
            # La scelta della persona vince sulla memoria: la catena parte dal
            # modello scelto, e il ricordo del «buono» vale solo se è lui.
            if self.preferito not in lista:
                lista = [self.preferito] + lista
            catena = self._in_testa(lista, self.preferito)
            if buono != self.preferito:
                buono = None
        else:
            catena = self._in_testa(lista, buono)
        if buono and buono in lista:
            self._nota(f"remembered good model: {buono} — skipping the probe")
        else:
            self._nota("probing:")
            p = self.prova(catena)
            if not p["ok"]:
                raise NessunModello(p["causa"], list(self.diario))
            buono = p["modello"]
        if o.get("solo_prova"):
            return Risposta("", buono, False, 0, self.nome_provider)
        return self.chiamata_vera(catena, buono, prompt, **o)

    # ═══ 4 · IL MESSAGGIO PER LA PERSONA ═════════════════════════════════
    def messaggio_nessuno(self, e: Any) -> str:
        causa = getattr(e, "causa", None) or str(e or "")
        M = MESSAGGI.get(self.lingua, MESSAGGI["it"])
        return M.get(str(causa).strip(), M["nessuno"])


# =============================================================================
# RIGA DI COMANDO — per collaudare la catena senza aprire Streamlit.
# =============================================================================
def _main() -> int:  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(description="Collaudo della catena modelli.")
    ap.add_argument("prompt", nargs="*", help="il prompt da mandare")
    ap.add_argument("--provider", default="gemini", help="gemini | claude | azure")
    ap.add_argument("--modelli", action="store_true", help="stampa solo la catena scoperta")
    ap.add_argument("--prova", action="store_true", help="fa solo la prova di contatto")
    ap.add_argument("--velocita", action="store_true", help="preferisci i modelli veloci (regola Nuvia)")
    ap.add_argument("--ragionamento", default="low", choices=LIVELLI,
                    help="quanto deve pensare il modello (si adatta da solo se lo rifiuta)")
    a = ap.parse_args()

    nome = ALIAS.get(a.provider.lower(), a.provider)
    chiave = {
        "Google Gemini": os.environ.get("GEMINI_API_KEY", ""),
        "Anthropic Claude": os.environ.get("ANTHROPIC_API_KEY", ""),
        "Microsoft Azure OpenAI": os.environ.get("AZURE_OPENAI_API_KEY", ""),
    }.get(nome, "")
    if not chiave:
        print("Manca la chiave nell'ambiente per " + nome)
        return 2

    catena = CatenaModelli(
        provider=nome, chiave=chiave,
        endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
        preferenza="velocita" if a.velocita else "qualita",
        ragionamento=a.ragionamento,
        log=lambda s: print(s, flush=True),
    )
    if a.modelli:
        e = catena.catena(forza=True)
        print("fonte: " + e["fonte"])
        print("\n".join(e["lista"]))
        return 0
    try:
        r = catena.chiedi(" ".join(a.prompt) or "Ciao", solo_prova=a.prova)
    except NessunModello as e:
        print(catena.messaggio_nessuno(e))
        print(f"(causa tecnica: {e.causa})")
        return 1
    print(f"— modello usato: {r.modello}" + (" (risposta troncata, consegnata comunque)" if r.troncata else ""))
    if not a.prova:
        print(r.testo)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
