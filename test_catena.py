"""
Collaudo della catena modelli e del contratto JSON — nessuna rete, nessuna
chiave, nessun costo. È il porting del collaudo di Nuvia (catena_modelli test)
più i casi nuovi del contratto.

    python test_catena.py

Ogni riga stampata è un caso: ✓ passa, ✗ no. In fondo il conto.
Serve solo `requests` installato (per le classi di eccezione), non usato in rete.
"""
import json
import sys
import time
import types

import contract
import model_chain
from model_chain import CatenaModelli, MemoriaRam, NessunModello

ESITI = []


def P(titolo, ok):
    ESITI.append(bool(ok))
    print(("✓ " if ok else "✗ ") + titolo)


# =============================================================================
# IL FINTO PROVIDER: si dice quali modelli rispondono e come.
# =============================================================================
class FintaRisposta:
    def __init__(self, status, corpo=None, testo=""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._corpo = corpo if corpo is not None else {}
        self.text = testo or json.dumps(self._corpo)

    def json(self):
        return self._corpo


ELENCO_GEMINI = [
    "models/gemini-3.7-flash", "models/gemini-3.7-flash-lite", "models/gemini-3.7-pro",
    "models/gemini-3.6-flash", "models/gemini-3.5-flash", "models/gemini-2.5-pro",
    "models/gemini-3.7-flash-preview-09-2026", "models/gemini-1.5-pro",
    "models/text-embedding-004", "models/gemini-2.5-flash-image",
]


def finto(regole, elenco=None):
    """regole: {"nome-modello": {"stato":…, "testo":…, "attesa":…, "corpo":…}}
    "*" vale per tutti gli altri. Torna la lista delle chiamate fatte."""
    chiamate = []

    def get(url, **kw):
        nomi = elenco if elenco is not None else ELENCO_GEMINI
        return FintaRisposta(200, {"models": [
            {"name": n, "supportedGenerationMethods": ["generateContent"]} for n in nomi]})

    def post(url, **kw):
        modello = url.split("/models/")[1].split(":")[0]
        chiamate.append(modello)
        r = regole.get(modello) or regole.get("*") or {"stato": 200, "testo": "OK"}
        if r.get("attesa"):
            time.sleep(r["attesa"])
        if r.get("stato", 200) != 200:
            return FintaRisposta(r["stato"], {}, r.get("corpo", ""))
        return FintaRisposta(200, {"candidates": [
            {"content": {"parts": [{"text": r.get("testo", "OK")}]},
             "finishReason": r.get("fine", "STOP")}]})

    falso = types.SimpleNamespace(get=get, post=post,
                                  utils=model_chain.requests.utils,
                                  exceptions=model_chain.requests.exceptions)
    model_chain.requests = falso
    return chiamate


def nuova(regole=None, elenco=None, memoria=None, **kw):
    ch = finto(regole or {}, elenco)
    AI = CatenaModelli(provider="gemini", chiave="k",
                       memoria=memoria if memoria is not None else MemoriaRam(),
                       lingua=kw.pop("lingua", "it"), **kw)
    return AI, ch


# ── 1 · la scoperta tiene solo i modelli buoni, nell'ordine giusto ──────────
AI, _ = nuova()
lista = AI.catena(forza=True)["lista"]
P("scoperta: solo gemini pieni ≥2, qualità prima → " + " → ".join(lista),
  lista[0] == "gemini-3.7-pro" and "gemini-3.7-flash-lite" not in lista
  and "gemini-1.5-pro" not in lista and not any("preview" in m for m in lista)
  and not any("image" in m for m in lista))

# ── 1b · con preferenza «velocita» si torna alla regola di Nuvia ────────────
AI, _ = nuova(preferenza="velocita")
lista = AI.catena(forza=True)["lista"]
P("preferenza velocità: solo flash pieni, dal più nuovo → " + " → ".join(lista),
  all("flash" in m and "lite" not in m for m in lista) and lista[0] == "gemini-3.7-flash")

# ── 2 · scende fino a chi risponde ─────────────────────────────────────────
AI, ch = nuova({"gemini-3.7-pro": {"stato": 404},
                "gemini-3.6-flash": {"stato": 503},
                "*": {"stato": 200, "testo": "OK"}})
r = AI.chiedi("dimmi qualcosa")
P("scende sui 404/503 e la chiamata vera parte da chi ha risposto: " + r.modello,
  r.modello not in ("gemini-3.7-pro",) and r.testo == "OK")

# ── 3 · la chiamata vera NON risale a chi era già giù ───────────────────────
dopo_prova = ch[ch.index(r.modello):]
P("la chiamata vera non ribussa ai modelli caduti",
  "gemini-3.7-pro" not in dopo_prova[1:])

# ── 4 · il 503 merita un secondo tentativo, il 404 no ──────────────────────
AI, ch = nuova({"gemini-3.7-pro": {"stato": 503}, "*": {"stato": 200}})
AI.chiedi("x")
P("un occupato (503) ha diritto a un secondo tentativo nella prova",
  ch.count("gemini-3.7-pro") == 2)
AI, ch = nuova({"gemini-3.7-pro": {"stato": 404}, "*": {"stato": 200}})
AI.chiedi("x")
P("un modello inesistente (404) non lo ha", ch.count("gemini-3.7-pro") == 1)

# ── 5 · il modello buono si ricorda: la seconda volta niente prova ─────────
mem = MemoriaRam()
AI, ch = nuova({"gemini-3.7-pro": {"stato": 429}, "*": {"stato": 200}}, memoria=mem)
AI.chiedi("uno")
prima = len(ch)
AI2 = CatenaModelli(provider="gemini", chiave="k", memoria=mem)
AI2.chiedi("due")
P("la seconda richiesta salta la prova e parte dal buono", len(ch) - prima == 1)

# ── 6 · nessuno risponde: il messaggio giusto ──────────────────────────────
AI, _ = nuova({"*": {"stato": 503}})
try:
    AI.chiedi("x")
    P("doveva fallire", False)
except NessunModello as e:
    m = AI.messaggio_nessuno(e)
    P("tutti occupati → «" + m + "»", "Riprova più tardi" in m)

# ── 7 · ma con la chiave sbagliata NON si dice «riprova più tardi» ─────────
AI, _ = nuova({"*": {"stato": 403}})
try:
    AI.chiedi("x")
    P("doveva fallire", False)
except NessunModello as e:
    m = AI.messaggio_nessuno(e)
    P("chiave sbagliata → «" + m + "»", "non è valida" in m and "Riprova più tardi" not in m)

# ── 8 · e in inglese ───────────────────────────────────────────────────────
AI, _ = nuova({"*": {"stato": 503}}, lingua="en")
try:
    AI.chiedi("x")
except NessunModello as e:
    m = AI.messaggio_nessuno(e)
    P("in inglese → «" + m + "»", "try again later" in m)

# ── 9 · il contesto pieno non fa scendere la catena (sarebbe inutile) ──────
AI, ch = nuova({"*": {"stato": 200}})
AI.chiedi("x")  # scalda la memoria del buono
ch = finto({"*": {"stato": 400, "corpo": "input token count exceeds the maximum"}})
try:
    AI.chiedi("y")
    P("doveva fallire", False)
except NessunModello as e:
    m = AI.messaggio_nessuno(e)
    P("contesto pieno: non scende e lo dice → «" + m[:60] + "…»",
      e.causa == "contesto" and len(set(ch)) == 1 and "finestra di contesto" in m)

# ── 10 · un 400 su un parametro NON è una chiave sbagliata ─────────────────
visti = []


def post_parametro(url, **kw):
    corpo = kw.get("json") or {}
    ha_schema = "responseSchema" in (corpo.get("generationConfig") or {})
    visti.append(ha_schema)
    if ha_schema:
        return FintaRisposta(400, {}, "Invalid JSON payload: responseSchema not supported")
    return FintaRisposta(200, {"candidates": [
        {"content": {"parts": [{"text": '{"ok":1}'}]}, "finishReason": "STOP"}]})


finto({"*": {"stato": 200}})
model_chain.requests.post = post_parametro
mem = MemoriaRam()
AI = CatenaModelli(provider="gemini", chiave="k", memoria=mem)
r = AI.chiedi("x", json_mode=True, schema={"type": "OBJECT"})
P("uno schema rifiutato si toglie e si riprova, senza accusare la chiave",
  r.testo == '{"ok":1}' and True in visti and visti[-1] is False)
P("l'adattamento si ricorda per quel modello",
  mem.leggi_adatta(AI.p.spazio(), r.modello).get("no_schema") is True)

# ── 11 · il tetto complessivo della prova ─────────────────────────────────
AI, _ = nuova({"*": {"stato": 200, "attesa": 5, "testo": "tardi"}},
              cfg={"prova_s": 0.3, "prova_totale_s": 0.9})
t0 = time.time()
try:
    AI.chiedi("x")
except NessunModello:
    pass
durata = time.time() - t0
P(f"la prova si ferma al tetto complessivo ({durata:.1f}s, tetto 0.9s)", durata < 3.0)

# ── 12 · una risposta troncata si consegna, non si butta ──────────────────
AI, _ = nuova({"*": {"stato": 200, "testo": "meta' risposta", "fine": "MAX_TOKENS"}})
r = AI.chiedi("x")
P("una risposta troncata viene consegnata e segnalata",
  r.troncata and r.testo == "meta' risposta")

# ── 13 · senza chiave non si finge di provare ────────────────────────────
AI = CatenaModelli(provider="gemini", chiave="", memoria=MemoriaRam())
try:
    AI.chiedi("x")
    P("doveva fallire", False)
except NessunModello as e:
    P("senza chiave lo dice subito → «" + AI.messaggio_nessuno(e) + "»", e.causa == "nokey")


# =============================================================================
# IL CONTRATTO JSON
# =============================================================================
# ── 14 · un JSON troncato a metà non perde le righe intere ────────────────
troncato = ('{"executive_summary":"x","business_rules":['
            '{"rule_id":"BR-01","rule_name":"Sconto","condition":"importo>100"},'
            '{"rule_id":"BR-02","rule_name":"Sped')
r = contract.ripara_troncato(troncato)
n = contract.normalizza(r)
P("un JSON tagliato a metà conserva le righe complete e butta quella a metà",
  r is not None and r["executive_summary"] == "x"
  and r["business_rules"][0]["rule_name"] == "Sconto" and len(n["business_rules"]) == 1)

# ── 15 · gli enum sbagliati si raddrizzano, non si buttano ────────────────
n = contract.normalizza({"technical_risks": [
    {"risk_type": "DYNAMIC_SQL", "severity": "High", "description": "d", "affected_component": "a"},
    {"risk_type": "DEAD_CODE", "severity": "critico", "description": "d2", "affected_component": "b"},
]})
P("«High» e «critico» diventano HIGH e CRITICAL",
  [x["severity"] for x in n["technical_risks"]] == ["HIGH", "CRITICAL"])
P("gli id li assegna il codice, in ordine",
  [x["risk_id"] for x in n["technical_risks"]] == ["TR-001", "TR-002"])
P("i campi mancanti ci sono comunque, vuoti",
  all(k in n["technical_risks"][0] for k in contract.CAMPI["technical_risks"]["campi"]))
P("le sezioni assenti sono segnalate, non silenziose",
  any("business_rules" in a for a in n["contract_warnings"]))

# ── 16 · le liste dentro le celle diventano testo leggibile ───────────────
n = contract.normalizza({"business_processes": [
    {"process_name": "Fatturazione", "description": "d", "involved_components": ["A", "B"]}]})
P("una lista in una cella diventa «A; B»",
  n["business_processes"][0]["involved_components"] == "A; B")

# ── 17 · i doppioni spariscono ────────────────────────────────────────────
n = contract.normalizza({"business_rules": [
    {"rule_name": "R", "source_component": "P", "condition": "c"},
    {"rule_name": "r", "source_component": "p", "condition": "c bis"}]})
P("due righe uguali a meno di maiuscole restano una", len(n["business_rules"]) == 1)

# ── 18 · il Mermaid arriva a righe e esce disegnabile ─────────────────────
n = contract.normalizza({"mermaid_process_flow": [
    "flowchart TD", "  A[Ordine (nuovo)] --> B[Verifica]"]})
d = n["mermaid_process_flow"]
P("le etichette con parentesi vengono messe fra virgolette",
  '"Ordine nuovo"' in d and d.startswith("flowchart TD"))
n = contract.normalizza({"mermaid_data_flow": "```mermaid\nA--&gt;B\n```"})
P("recinti markdown ed entità HTML spariscono, e l'intestazione si aggiunge",
  n["mermaid_data_flow"].startswith("flowchart TD") and "-->" in n["mermaid_data_flow"])

# ── 19 · le vecchie domande a stringa non si perdono ──────────────────────
n = contract.normalizza({"validation_questions": ["Perché 30 giorni?"], "assumptions": ["A"]})
P("le sezioni che una volta erano stringhe si convertono da sole",
  n["validation_questions"][0]["question"] == "Perché 30 giorni?"
  and n["validation_questions"][0]["question_id"] == "VQ-001")

# ── 20 · il recinto del sorgente è diverso a ogni esecuzione ──────────────
src = [{"filename": "a.sql", "language": "SQL", "hash": "h", "content": "SELECT 1"}]
p1 = contract.prompt_analisi(src, {}, (1, 1))
p2 = contract.prompt_analisi(src, {}, (1, 1))
P("il recinto attorno al sorgente è irripetibile (niente iniezione dal codice)",
  p1 != p2 and "SRC-" in p1)

# ── 21 · l'unione di più lotti non duplica e rinumera ─────────────────────
a = contract.normalizza({"business_rules": [{"rule_name": "R1", "source_component": "P", "condition": "c"}]})
b = contract.normalizza({"business_rules": [
    {"rule_name": "R1", "source_component": "P", "condition": "c"},
    {"rule_name": "R2", "source_component": "P", "condition": "d"}]})
u = contract.unisci([a, b])
P("due lotti si uniscono senza doppioni e con id rinumerati",
  [x["rule_id"] for x in u["business_rules"]] == ["BR-001", "BR-002"])

# ── 22 · lo schema per Gemini copre tutte le sezioni ──────────────────────
s = contract.schema_gemini()
P("lo schema nativo elenca tutte le sezioni del contratto",
  all(k in s["properties"] for k in contract.CAMPI))


# =============================================================================
# I DIAGRAMMI (senza disegnarli davvero: si controlla la geometria)
# =============================================================================
import io as _io

import mermaid_render as mr


def _png(w, h):
    """Un PNG minimo valido, scritto a mano: serve solo l'intestazione."""
    import struct
    import zlib

    grezzo = b"".join(b"\x00" + b"\xff" * (w * 3) for _ in range(h))

    def blocco(tipo, dati):
        return (struct.pack(">I", len(dati)) + tipo + dati
                + struct.pack(">I", zlib.crc32(tipo + dati) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + blocco(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + blocco(b"IDAT", zlib.compress(grezzo))
            + blocco(b"IEND", b""))


alto = _png(800, 2000)     # flowchart TD con molti nodi
largo = _png(2400, 400)    # flowchart LR
P("le dimensioni del PNG si leggono senza dipendenze", mr.dimensioni_png(alto) == (800, 2000))
l, a = mr.misura_per_riquadro(alto, 780, 460)
P(f"un diagramma alto NON viene schiacciato ({l:.0f}x{a:.0f} pt, era 720x240 fisso)",
  abs(a / l - 2.5) < 0.01 and l <= 780 and a <= 460)
l, a = mr.misura_per_riquadro(largo, 780, 460)
P(f"un diagramma largo riempie la pagina senza deformarsi ({l:.0f}x{a:.0f} pt)",
  abs(a / l - 400 / 2400) < 0.01 and l <= 780)
P("un PNG illeggibile non fa saltare l'esportazione, torna la misura di riserva",
  mr.misura_per_riquadro(b"non-e-un-png", 780, 460) == (720.0, 240.0))
P("il servizio esterno si può vietare",
  hasattr(mr, "_rendi_remoto") and "MERMAID_LOCAL_ONLY" in open("mermaid_render.py").read())


# =============================================================================
# I DIAGRAMMI COSTRUITI DAI DATI
# (il caso segnalato: il modello ne consegna uno su quattro)
# =============================================================================
import re

import diagrams

parziale = contract.normalizza({
    "business_processes": [{"process_name": "Fatturazione mensile", "trigger": "Job notturno (cron)",
                            "outcome": "Fatture emesse", "involved_components": ["PKG_FATT"]}],
    "dependencies": [{"source": "PKG_FATT", "target": "UTL_MAIL", "dependency_type": "CALL",
                      "confidence": "HIGH"}],
    "application_mapping": [{"source_component": "PKG_FATT", "external_system": "SAP FI",
                             "integration_type": "FILE_EXCHANGE", "direction": "OUTBOUND"}],
    "data_flows": [{"source": "ORDINI", "target": "FATTURE", "data_description": "Righe d'ordine"}],
    "mermaid_process_flow": ["flowchart TD", '  A["Job"] --> B["Verifica"]', '  B --> C["Fattura"]'],
    "mermaid_application_map": [], "mermaid_data_flow": "", "mermaid_call_graph": [],
})
arricchito = diagrams.arricchisci(parziale)
P("i tre diagrammi che il modello non ha dato vengono costruiti dai dati",
  all(arricchito[c].strip() for c in diagrams.COSTRUTTORI))
P("il diagramma che il modello ha dato resta il suo",
  arricchito["mermaid_process_flow"] == arricchito["_diagrammi_dal_modello"]["mermaid_process_flow"])
P("entrambe le versioni restano disponibili per il confronto",
  set(arricchito["_diagrammi_dai_dati"]) == set(diagrams.COSTRUTTORI))
P("la provenienza di ogni diagramma è registrata accanto al disegno",
  arricchito["_diagrammi_fonte"]["mermaid_process_flow"] == "modello"
  and sum(1 for v in arricchito["_diagrammi_fonte"].values() if v == "dati") == 3)
P("un diagramma costruito dai dati NON è un avviso di contratto",
  not any("built from the validated data" in a for a in arricchito["contract_warnings"]))

grafo = arricchito["mermaid_call_graph"]
P("il call graph esce dalle dipendenze, con nodi validi",
  "PKG_FATT" in grafo and "UTL_MAIL" in grafo and grafo.startswith("flowchart"))
P("le etichette non contengono caratteri che rompono il disegno",
  not re.search(r'\[[^\]]*[()|;][^\]]*\]', arricchito["mermaid_process_flow"]))
P("un id di nodo non comincia mai per cifra",
  all(not re.match(r"^\s*\d", r) for r in grafo.splitlines()[1:]))

vuoto = diagrams.arricchisci(contract.normalizza({}))
P("senza dati non si inventa un diagramma vuoto, e QUELLO sì è un avviso",
  all(not vuoto[c] for c in diagrams.COSTRUTTORI)
  and any("neither the model nor the tables" in a for a in vuoto["contract_warnings"]))

grosso = contract.normalizza({"dependencies": [
    {"source": f"MOD_{i}", "target": f"MOD_{i+1}", "dependency_type": "CALL", "confidence": "HIGH"}
    for i in range(80)]})
disegno = diagrams.call_graph(grosso)
P(f"un grafo enorme viene tagliato e lo dichiara ({len(disegno.splitlines())-1} righe su 80)",
  len(disegno.splitlines()) - 1 <= diagrams.MAX_ARCHI + 1 and "non mostrati" in disegno)

P("i campi mermaid sono ora obbligatori nello schema di Gemini",
  all(m in contract.schema_gemini()["required"] for m in contract.CAMPI_MERMAID))
P("gli avvisi di contratto sono in inglese, come l'interfaccia",
  all(not re.search(r"assente|mancante|scartata|risposta non", a)
      for a in contract.normalizza({})["contract_warnings"]))


# =============================================================================
# CONSOLIDAMENTO FRA LOTTI
# =============================================================================
base = contract.normalizza({
    "executive_summary": "Sintesi del lotto 1.",
    "components": [{"component_name": "EMETTI_FATTURA", "component_type": "PROCEDURE",
                    "source_file": "fatt.pkb"},
                   {"component_name": "CALC_SCONTO", "component_type": "PROCEDURE",
                    "source_file": "sconti.pkb"}],
})
consolidato = contract.applica_consolidamento(base, {
    "executive_summary": "Sintesi dell'intera applicazione.",
    "application_purpose": "Fatturazione.",
    "cross_batch_dependencies": [
        {"source": "EMETTI_FATTURA", "target": "CALC_SCONTO",
         "dependency_type": "CROSS_BATCH_CALL", "confidence": "HIGH", "evidence": "inventario"},
        {"source": "EMETTI_FATTURA", "target": "MODULO_INVENTATO",
         "dependency_type": "CROSS_BATCH_CALL", "confidence": "HIGH", "evidence": "-"},
    ],
    "validation_questions": [{"question": "Chi lancia il job notturno?"}],
})
P("la sintesi per lotto viene sostituita da quella d'insieme",
  consolidato["executive_summary"] == "Sintesi dell'intera applicazione.")
P("il collegamento fra due nomi noti viene tenuto",
  any(d["target"] == "CALC_SCONTO" for d in consolidato["dependencies"]))
P("il collegamento con un nome inventato viene buttato",
  not any(d["target"] == "MODULO_INVENTATO" for d in consolidato["dependencies"])
  and any("dropped" in a for a in consolidato["contract_warnings"]))
P("la domanda d'insieme entra nelle domande per lo SME",
  any("job notturno" in d["question"] for d in consolidato["validation_questions"]))
P("una risposta inutilizzabile non cancella le sintesi per lotto",
  contract.applica_consolidamento(
      contract.normalizza({"executive_summary": "resta"}), None)["executive_summary"] == "resta")
P("il prompt di consolidamento non contiene codice sorgente, solo l'inventario",
  "SOURCE CODE" not in contract.prompt_consolidamento(base, [["fatt.pkb"], ["sconti.pkb"]])
  and "EMETTI_FATTURA" in contract.prompt_consolidamento(base, [["fatt.pkb"], ["sconti.pkb"]]))

# =============================================================================
# ANALISI STATICA: RISOLUZIONE DELLE CHIAMATE E INDICATORI
# (serve app.py, quindi si finge Streamlit)
# =============================================================================
import types as _types


class _FintoSt:
    def __getattr__(self, k):
        if k in ("sidebar", "column_config"):
            return _FintoSt()
        if k == "cache_data":
            return lambda **kw: (lambda fn: fn)
        if k == "stop":
            def _stop(*a, **kw):
                raise SystemExit(0)
            return _stop

        def _f(*a, **kw):
            if k == "columns":
                return [_FintoSt() for _ in range(a[0] if a and isinstance(a[0], int) else 3)]
            if k == "tabs":
                return [_FintoSt() for _ in a[0]]
            if k in ("selectbox", "radio"):
                return a[1][0] if len(a) > 1 and a[1] else ""
            if k == "select_slider":
                return kw.get("value") or (kw.get("options") or [""])[0]
            if k in ("text_input", "text_area"):
                return kw.get("value", "")
            if k in ("button", "checkbox"):
                return False
            if k == "file_uploader":
                return []
            if k == "data_editor":
                return a[0]
            return _FintoSt()
        return _f

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_st = _FintoSt()
_st.session_state = {}
sys.modules["streamlit"] = _st
sys.modules["streamlit_mermaid"] = _types.SimpleNamespace(st_mermaid=lambda *a, **kw: None)
_ns = {"__name__": "app_collaudo", "__file__": "app.py"}
try:
    exec(compile(open("app.py").read(), "app.py", "exec"), _ns)
except SystemExit:
    pass
app = _types.SimpleNamespace(**_ns)

sorgenti = [
    {"filename": "fatt.pkb", "language": "Oracle PL/SQL Package Body", "hash": "a",
     "content": "PROCEDURE EMETTI_FATTURA IS BEGIN CALC_SCONTO(x); UTL_FILE.PUT_LINE(y); "
                "System.out.println(z); END;"},
    {"filename": "sconti.pkb", "language": "Oracle PL/SQL Package Body", "hash": "b",
     "content": "PROCEDURE CALC_SCONTO IS BEGIN NULL; END;"},
]
meta = app.extract_technical_metadata(sorgenti)
tipi = {d["target"]: (d["dependency_type"], d["confidence"]) for d in meta["dependencies"]}
P("una chiamata a una procedura dichiarata in un ALTRO file diventa CALL certa",
  tipi.get("CALC_SCONTO") == ("CALL", "HIGH"))
P("una chiamata fuori dal perimetro resta probabile, ma a confidenza bassa",
  tipi.get("UTL_FILE.PUT_LINE") == ("PROBABLE_CALL", "LOW"))
P("il rumore di libreria non arriva nemmeno alle tabelle",
  "System.out.println" not in tipi and meta["dependency_resolution"]["discarded_as_library_noise"] >= 1)
P("in un PL/SQL non nascono più «metodi Java» fantasma",
  all(c["component_type"] != "JAVA_METHOD" for c in meta["components"]))

java = [{"filename": "F.java", "language": "Java", "hash": "c",
         "content": 'public class F { public void tot() { C c = new Cliente("x"); logger.info("o"); } }'}]
mj = app.extract_technical_metadata(java)
P("`new Cliente(...)` non è una chiamata a una procedura",
  not any(d["target"].lower() == "cliente" for d in mj["dependencies"]))

ind = app.quality_indicators(contract.normalizza({
    "business_rules": [{"rule_name": "R", "condition": "c", "source_file": "fatt.pkb",
                        "evidence": "riga 1", "confidence": "HIGH"}]}), meta)
P(f"gli indicatori dicono quali file non ha citato nessuno ({ind['file_mai_citati']})",
  ind["file_mai_citati"] == ["sconti.pkb"] and ind["file_pct"] == 50)
P("l'indicatore misura l'ancoraggio, non promette completezza",
  ind["evidenza_pct"] == 100 and "coverage" not in str(ind.keys()).lower())


# =============================================================================
# IL LIVELLO DI RAGIONAMENTO
# =============================================================================
from model_chain import LIVELLI, _almeno, _su_di_uno

P("la scala del ragionamento sale di un gradino per volta",
  _su_di_uno("minimal") == "low" and _su_di_uno("low") == "medium" and _su_di_uno("high") is None)
P("il livello scelto viene alzato al minimo che il modello pretende",
  _almeno("minimal", "medium") == "medium" and _almeno("high", "low") == "high")

livelli_visti = []


def _post_thinking(url, **kw):
    corpo = kw.get("json") or {}
    liv = ((corpo.get("generationConfig") or {}).get("thinkingConfig") or {}).get("thinkingLevel")
    livelli_visti.append(liv)
    if liv in ("minimal", "low"):
        return FintaRisposta(400, {}, "thinkingLevel LOW is not supported for this model")
    return FintaRisposta(200, {"candidates": [
        {"content": {"parts": [{"text": "OK"}]}, "finishReason": "STOP"}]})


finto({"*": {"stato": 200}})
model_chain.requests.post = _post_thinking
mem = MemoriaRam()
AI = CatenaModelli(provider="gemini", chiave="k", memoria=mem, ragionamento="minimal")
r = AI.chiedi("x")
P(f"un modello che rifiuta i livelli bassi fa salire la scala, non fallisce (visti: {livelli_visti})",
  r.testo == "OK" and livelli_visti[0] == "minimal" and "medium" in livelli_visti)
P("il livello minimo di quel modello si ricorda",
  mem.leggi_adatta(AI.p.spazio(), r.modello).get("thinking_min") in ("low", "medium", "high"))

livelli_visti.clear()
finto({"*": {"stato": 200}})
model_chain.requests.post = _post_thinking
AI = CatenaModelli(provider="gemini", chiave="k", memoria=MemoriaRam(), ragionamento="high")
AI.chiedi("x")
P("la prova di contatto usa sempre il livello più basso, per non sforare i 5 s",
  livelli_visti[0] == "minimal")


# =============================================================================
# GLI ID CHE FACEVANO ESPLODERE IL DISEGNO
# («Cannot set properties of undefined (setting 'order')»)
# =============================================================================
grafo_js = contract.normalizza({"dependencies": [
    {"source": "report_logic2.js", "target": "toLocaleString",
     "dependency_type": "PROBABLE_CALL", "confidence": "LOW"},
    {"source": "report_logic2.js", "target": "constructor",
     "dependency_type": "PROBABLE_CALL", "confidence": "LOW"}]})
disegno = diagrams.call_graph(grafo_js)
P("un nodo che si chiama come un metodo del prototipo JS ha comunque un id sicuro",
  "n_toLocaleString" in disegno and "n_constructor" in disegno
  and not re.search(r"(?<![\w_])toLocaleString\s*\[", disegno))
P("il nome vero resta leggibile nell'etichetta",
  '"toLocaleString"' in disegno and '"constructor"' in disegno)

ids = re.findall(r"^\s*([A-Za-z_]\w*)", disegno, flags=re.M)[1:]
P("tutti gli id generati nascono con il prefisso, non solo quelli sospetti",
  ids and all(i.startswith("n_") for i in ids))

modello = contract.pulisci_mermaid([
    "flowchart LR",
    '  toLocaleString["toLocaleString()"] -->|calls toString| valueOf["valueOf"]',
    "  subgraph gruppo",
    '    prototype["prototype"] --> toLocaleString',
    "  end"])
P("anche nel Mermaid scritto dal modello gli id pericolosi vengono rinominati",
  modello.count("n_toLocaleString") == 2 and "n_prototype" in modello)
P("la rinomina è coerente: i due capi dello stesso arco restano collegati",
  "n_prototype[\"prototype\"] --> n_toLocaleString" in modello)
P("`subgraph` ed `end` NON si toccano: lì la parola ha un significato",
  "subgraph gruppo" in modello and re.search(r"^\s*end\s*$", modello, flags=re.M))
P("l'etichetta sull'arco resta quella che l'autore ha scritto",
  "|calls toString|" in modello)
P("le frecce con lettera (--o, --x) non vengono scambiate per etichette",
  contract.pulisci_mermaid(["flowchart TD", '  A["x"] --o B["y"]']).endswith('--o B["y"]'))

print()
print(f"{sum(ESITI)}/{len(ESITI)} casi passati")
sys.exit(0 if all(ESITI) else 1)
