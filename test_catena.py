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
  len(disegno.splitlines()) - 1 <= diagrams.MAX_ARCHI + 1 and "more not shown" in disegno)

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
                return [] if kw.get("accept_multiple_files") else None
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
P("una chiamata confermata dall'albero ma fuori dal perimetro: certa sul fatto, "
  "incerta sul bersaglio",
  tipi.get("UTL_FILE.PUT_LINE") == ("CALL", "MEDIUM"))
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
from model_chain import _almeno, _su_di_uno

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
P("l'etichetta sull'arco resta leggibile (fra virgolette, non sanificata)",
  '|"calls toString"|' in modello)
P("le frecce con lettera (--o, --x) non vengono scambiate per etichette",
  contract.pulisci_mermaid(["flowchart TD", '  A["x"] --o B["y"]']).endswith('--o B["y"]'))


# =============================================================================
# I DOCUMENTI
# =============================================================================
import exporter

doc = contract.normalizza({
    "executive_summary": "S.", "application_purpose": "P.",
    "technical_risks": [
        {"risk_type": "SELECT_ALL", "severity": "LOW", "description": "d",
         "affected_component": "a.pkb", "source": "STATIC_ANALYSIS", "confidence": "HIGH"},
        {"risk_type": "HARDCODED_CREDENTIAL", "severity": "CRITICAL", "description": "d",
         "affected_component": "b.pkb", "source": "STATIC_ANALYSIS", "confidence": "HIGH"},
        {"risk_type": "DYNAMIC_SQL", "severity": "HIGH", "description": "d",
         "affected_component": "c.pkb", "source": "LLM_ANALYSIS", "confidence": "MEDIUM"}],
    "dependencies": [
        {"source": "PKG_A", "target": "PKG_B", "dependency_type": "PROBABLE_CALL", "confidence": "LOW"},
        {"source": "PKG_A", "target": "PKG_C", "dependency_type": "CALL", "confidence": "HIGH"}],
    "validation_questions": [{"question": "Why 30 days?", "addressed_to": "business"}],
})
meta_doc = {"file_count": 1, "total_line_count": 10, "languages": ["Oracle PL/SQL"],
            "detected_tables": [], "components": [], "dependencies": [], "interfaces": [],
            "data_objects": [], "local_risks": [], "files": []}

P("i rischi escono in ordine di gravità, non nell'ordine in cui sono arrivati",
  [r["severity"] for r in exporter._ordina("technical_risks", doc["technical_risks"])]
  == ["CRITICAL", "HIGH", "LOW"])
P("le dipendenze certe vengono prima dei sospetti",
  [d["dependency_type"] for d in exporter._ordina("dependencies", doc["dependencies"])]
  == ["CALL", "PROBABLE_CALL"])

P("«source» nei rischi è la provenienza e si legge «parser»",
  exporter._valore("technical_risks", "source", doc["technical_risks"][0]) == "parser")
P("«source» nelle dipendenze è un nome di componente e resta tale",
  exporter._valore("dependencies", "source", doc["dependencies"][0]) == "PKG_A"
  and exporter._etichetta("dependencies", "source") == "From")
P("la confidenza diventa puntini che si leggono anche in bianco e nero",
  exporter._valore("technical_risks", "confidence", doc["technical_risks"][0]) == "\u2022\u2022\u2022")

preparato = exporter.prepara(doc, meta_doc, "Google Gemini", "gemini-3.7-flash")
titoli = [b[1] for b in preparato["blocchi"] if b[0] == "titolo"]
P(f"il documento ha otto sezioni, comprese le domande per l'esperto ({len(titoli)})",
  len(titoli) == 8 and any("Open questions" in t for t in titoli))
P("le domande per l'esperto arrivano nel documento",
  any(b[0] == "tabella" and b[1] == "validation_questions" for b in preparato["blocchi"]))
P("la copertina dichiara quante righe ha confermato un esperto",
  any("confirmed by a domain expert" in k for k, _ in preparato["copertina"]))

pdf = exporter.generate_pdf_report(doc, meta_doc, "Google Gemini", "gemini-3.7-flash")
docx = exporter.generate_docx_report(doc, meta_doc, "Google Gemini", "gemini-3.7-flash")
P(f"il PDF si costruisce ({len(pdf)//1024} KB)", pdf[:5] == b"%PDF-" and len(pdf) > 3000)
P(f"il Word si costruisce ({len(docx)//1024} KB)", docx[:2] == b"PK" and len(docx) > 3000)
P("i caratteri del documento sono quelli dell'applicazione",
  exporter._registra_font() and exporter.FONT["corpo"] == "PlexSans")


# =============================================================================
# LE ETICHETTE CHE USCIVANO DALLE CASELLE
# =============================================================================
direttiva = mr._direttiva()
P("la configurazione del disegno viaggia dentro il diagramma",
  direttiva.startswith("%%{init:") and direttiva.endswith("}%%"))
P("le etichette non sono più HTML: è la causa del testo fuori dalle caselle",
  '"htmlLabels":false' in direttiva.replace(" ", "")
  and mr.CONFIG_MERMAID["flowchart"]["htmlLabels"] is False)

con_direttiva = contract.pulisci_mermaid([
    '%%{init: {"theme":"neutral"}}%%', "flowchart TD",
    '  n_a["Extract & Format Contact Emails"] --> n_b["Call GET_PDF_DATA AJAX"]'])
P("la pulizia non tocca la direttiva e non le mette un'intestazione sopra",
  con_direttiva.splitlines()[0].startswith("%%{init")
  and con_direttiva.splitlines()[1].startswith("flowchart"))
senza_intestazione = contract.pulisci_mermaid(
    ['%%{init: {"theme":"neutral"}}%%', '  n_a["A"] --> n_b["B"]'])
P("l'intestazione mancante si inserisce dopo la direttiva, non prima",
  senza_intestazione.splitlines()[0].startswith("%%{init")
  and senza_intestazione.splitlines()[1] == "flowchart TD")


# =============================================================================
# LEGGERE IL CODICE INVECE DI INDOVINARLO
# =============================================================================
py_src = ("import os\n"
          "def calcola(x):\n"
          "    return applica_sconto(x) + os.path.join('a','b')\n"
          "def applica_sconto(x):\n"
          "    return int(x) * 0.9\n"
          "esito = spedisci_mail(calcola(10))\n")
dip_py = app.extract_calls_python(py_src, "f.py")
bersagli = {d["target"] for d in dip_py}
P("in Python le chiamate si leggono dall'albero, a confidenza alta",
  "spedisci_mail" in bersagli and all(d["confidence"] == "HIGH" for d in dip_py))
P("quello che è definito nel file stesso non è una dipendenza",
  "applica_sconto" not in bersagli and "calcola" not in bersagli)
P("le funzioni di libreria e quelle di Python non sporcano l'elenco",
  not {"int", "os.path.join", "str"} & bersagli)
P("un file Python illeggibile non fa saltare nulla, si torna a indovinare",
  app.extract_calls_python("def (((", "rotto.py") is None)

sql_src = "PROCEDURE EMETTI IS BEGIN CALC_SCONTO(1); SUBSTR(x,1,2); UTL_FILE.PUT_LINE(y); END;"
nomi_sql = app.nomi_chiamati_sql(sql_src)
P(f"l'albero SQL riconosce le chiamate non standard ({sorted(nomi_sql)})",
  "put_line" in nomi_sql and "substr" not in nomi_sql)
sorgenti_sql = [{"filename": "p.sql", "language": "SQL", "hash": "s", "content": sql_src}]
meta_sql = app.extract_technical_metadata(sorgenti_sql)
per_bersaglio = {d["target"]: d for d in meta_sql["dependencies"]}
P("quello che l'albero conferma diventa una chiamata certa",
  per_bersaglio.get("UTL_FILE.PUT_LINE", {}).get("dependency_type") == "CALL")
P("quello che l'albero non vede resta, marcato come sospetto: niente si perde",
  per_bersaglio.get("CALC_SCONTO", {}).get("dependency_type") == "PROBABLE_CALL")

# ── i lotti seguono le dipendenze, non l'alfabeto ─────────────────────────
coppie = []
for a, b in [("alfa", "zulu"), ("beta", "yankee")]:
    coppie.append({"filename": f"{a}.sql", "language": "SQL", "hash": a,
                   "content": f"PROCEDURE P_{a.upper()} IS BEGIN P_{b.upper()}(1); END;" + "x" * 30000})
    coppie.append({"filename": f"{b}.sql", "language": "SQL", "hash": b,
                   "content": f"PROCEDURE P_{b.upper()} IS BEGIN NULL; END;" + "x" * 30000})
meta_coppie = app.extract_technical_metadata(coppie)
lotti = app.split_into_batches(coppie, 70000, metadata=meta_coppie)
insieme = [{s["filename"] for s in l} for l in lotti]
P(f"i file che si chiamano fra loro finiscono nello stesso lotto ({insieme})",
  any({"alfa.sql", "zulu.sql"} <= g for g in insieme)
  and any({"beta.sql", "yankee.sql"} <= g for g in insieme))
P("nessun file viene spezzato a metà",
  sum(len(l) for l in lotti) == len(coppie))

# ── i passi del processo, in ordine ───────────────────────────────────────
proc = contract.normalizza({"business_processes": [
    {"process_name": "Invoicing", "trigger": "cron", "outcome": "Invoices issued",
     "steps": ["read orders", "apply discounts", "send to SAP"]}]})
P("i passi sono un dato ordinato, non solo un disegno",
  proc["business_processes"][0]["steps"] == "read orders; apply discounts; send to SAP")
catena_passi = diagrams.process_flow(proc)
posizioni = [catena_passi.index(x) for x in ("read orders", "apply discounts", "send to SAP")]
P("il diagramma costruito dai dati rispetta l'ordine di esecuzione",
  posizioni == sorted(posizioni) and catena_passi.count("-->") >= 4)
P("il contratto è salito di versione", contract.VERSIONE_CONTRATTO == "2.1")

# ── quanto dei fatti del parser è stato descritto ─────────────────────────
due = [{"filename": "a.pkb", "language": "Oracle PL/SQL Package Body", "hash": "1",
        "content": "PROCEDURE CALC IS BEGIN IF x>100 THEN NULL; END IF; SELECT * FROM ORDINI; END;"},
       {"filename": "b.pkb", "language": "Oracle PL/SQL Package Body", "hash": "2",
        "content": "PROCEDURE MUTO IS BEGIN IF y=1 THEN NULL; END IF; END;"}]
meta_due = app.extract_technical_metadata(due)
risultato_due = app.merge_static_and_ai_results(contract.normalizza({
    "business_rules": [{"rule_name": "Soglia", "condition": "x>100", "source_file": "a.pkb",
                        "source_component": "CALC", "confidence": "HIGH", "evidence": "r.1"}]}),
    meta_due)
ind_due = app.quality_indicators(risultato_due, meta_due)
P(f"si misura quanti componenti del parser sono stati descritti ({ind_due['componenti_pct']}%)",
  ind_due["componenti_descritti"] == 1 and ind_due["componenti_parser"] == 2)
P(f"i file pieni di condizioni senza nemmeno una regola vengono segnalati ({ind_due['file_muti']})",
  ind_due["file_muti"] == ["b.pkb"])

P("il Word usa caratteri che esistono su tutte le macchine",
  exporter.NOME_WORD == "Arial" and exporter.NOME_WORD_MONO == "Courier New")


# =============================================================================
# RIPRENDERE UN'ANALISI SALVATA
# =============================================================================
import json as _json

vecchio_json = {"contract_version": "2.0", "executive_summary": "Old.", "application_purpose": "P.",
                "business_processes": [{"process_name": "Inv", "trigger": "cron", "outcome": "done"}],
                "business_rules": [{"rule_name": "R1", "condition": "c", "sme_approved": True,
                                    "confidence": "High"},
                                   {"rule_name": "R2", "condition": "d", "sme_approved": False}],
                "validation_questions": ["Why 30 days?"]}
ricaricato, meta_ric = app.carica_analisi_salvata(_json.dumps(vecchio_json).encode())
P("un JSON della versione 2.0 si ricarica e sale alla 2.1",
  ricaricato["contract_version"] == "2.1")
P("le spunte dell'esperto sopravvivono al salvataggio e al ricaricamento",
  [r["sme_approved"] for r in ricaricato["business_rules"]] == [True, False])
P("il campo `steps` che il vecchio formato non aveva resta vuoto, non rompe",
  ricaricato["business_processes"][0]["steps"] == "")
P("le domande scritte come stringhe diventano righe",
  ricaricato["validation_questions"][0]["question"] == "Why 30 days?")
try:
    app.carica_analisi_salvata(b'{"x": 1}')
    ESITI.append(False); print("✗ un JSON estraneo doveva essere rifiutato")
except ValueError:
    ESITI.append(True); print("✓ un JSON estraneo viene rifiutato con un motivo")
nuovo_json = dict(vecchio_json, _metadata={"file_count": 2, "files": []}, _modello="gemini-3.7-pro")
ric2, meta2 = app.carica_analisi_salvata(_json.dumps(nuovo_json).encode())
P("un JSON della versione nuova riporta anche i metadati e chi ha risposto",
  meta2.get("file_count") == 2 and ric2["_modello"] == "gemini-3.7-pro")


# =============================================================================
# QUALUNQUE FILE DI TESTO ENTRA; I PATTERN GIRANO SOLO SUL LORO LINGUAGGIO
# =============================================================================
class _Finto:
    def __init__(self, nome, dati):
        self.name, self._d = nome, dati

    def getvalue(self):
        return self._d


P("un .vb non viene più respinto e si chiama col suo nome",
  app.detect_language_from_filename("CPDB_Product_D.vb") == "VB.NET")
P("un'estensione sconosciuta entra lo stesso, dichiarata come tale",
  app.detect_language_from_filename("cosa.xyz").startswith("Unknown"))
try:
    app.build_source_collection([_Finto("x.dll", b"MZ\x90\x00\x03binario")], "", "")
    ESITI.append(False); print("✗ un binario doveva essere respinto")
except ValueError as e:
    P("un binario viene respinto con un motivo e un rimedio", "binary" in str(e))

vb_src = ("Imports System.Data\nPublic Class Prod\n    Public Sub Load()\n        On Error Resume Next\n"
          "    End Sub\n    Private Function Disc() As Decimal\n        Return 1\n    End Function\n"
          "    Public Property Name() As String\n    End Property\nEnd Class\n")
meta_vb = app.extract_technical_metadata([{"filename": "p.vb", "language": "VB.NET", "hash": "v",
                                           "content": vb_src}])
tipi_vb = sorted((c["component_name"], c["component_type"]) for c in meta_vb["components"])
P(f"in VB si riconoscono Sub, Function, Property e Class, una volta ciascuno ({len(tipi_vb)})",
  tipi_vb == [("Disc", "VB_FUNCTION"), ("Load", "VB_PROCEDURE"), ("Name", "VB_PROPERTY"),
              ("Prod", "VB_CLASS")])
P("Imports diventa una dipendenza, On Error Resume Next un rischio",
  any(d["dependency_type"] == "VB_IMPORTS" for d in meta_vb["dependencies"])
  and any(r["risk_type"] == "SUPPRESSED_ERRORS" for r in meta_vb["local_risks"]))

meta_sql = app.extract_technical_metadata([{"filename": "q.pkb", "language": "Oracle PL/SQL Package Body",
                                            "hash": "q", "content": "END FUNCTION;\n  Public x"}])
P("«End Function» seguito da «Public» non fabbrica più una funzione fantasma",
  not any(c["component_name"].lower() == "public" for c in meta_sql["components"]))
P("i rischi VB non girano sui file SQL, e viceversa",
  not any(r["risk_type"] == "SUPPRESSED_ERRORS" for r in app.extract_local_risks(
      "On Error Resume Next", "x.sql", "SQL")))

jcl_src = "//BILL JOB X\n//STEP010 EXEC PGM=CALCINV\n//IN DD DSN=PROD.ORDERS,DISP=SHR\n"
meta_jcl = app.extract_technical_metadata([{"filename": "b.jcl", "language": "JCL", "hash": "j",
                                            "content": jcl_src}])
P("in un JCL gli step sono componenti, i programmi eseguiti dipendenze, i dataset oggetti dati",
  any(c["component_type"] == "JCL_STEP" for c in meta_jcl["components"])
  and any(d["target"] == "CALCINV" for d in meta_jcl["dependencies"])
  and any(o["object_name"] == "PROD.ORDERS" for o in meta_jcl["data_objects"]))


# =============================================================================
# VELOCITÀ: PROFONDITÀ, LOTTI IN PARALLELO, CACHE DEI LOTTI
# (l'orchestrazione intera, con un provider finto e un lock per contare)
# =============================================================================
import json as _j
import shutil as _sh
import threading as _th
import time as _t

_chiamate, _in_volo, _picco = [], [0], [0]
_lock = _th.Lock()


def _post_orchestra(url, **kw):
    corpo = kw.get("json") or {}
    prompt = corpo["contents"][0]["parts"][0]["text"] if "contents" in corpo else ""
    with _lock:
        _in_volo[0] += 1
        _picco[0] = max(_picco[0], _in_volo[0])
    try:
        if "OK." in prompt:
            testo = "OK"
            with _lock:
                _chiamate.append("prova")
        elif "cross_batch_dependencies" in prompt:
            testo = _j.dumps({"executive_summary": "Whole.", "application_purpose": "B.",
                              "cross_batch_dependencies": [], "validation_questions": []})
            with _lock:
                _chiamate.append("consolidamento")
        else:
            _t.sleep(0.25)   # finge il tempo del modello: serve a misurare il parallelismo
            nomi = re.findall(r"name=(\S+)", prompt)
            testo = _j.dumps({"executive_summary": "S.", "application_purpose": "P.",
                              "business_rules": [{"rule_name": "R " + n, "condition": "c",
                                                  "source_file": n, "confidence": "HIGH"} for n in nomi]})
            with _lock:
                _chiamate.append("analisi")
        return FintaRisposta(200, {"candidates": [{"content": {"parts": [{"text": testo}]},
                                                  "finishReason": "STOP"}]})
    finally:
        with _lock:
            _in_volo[0] -= 1


def _get_orchestra(url, **kw):
    return FintaRisposta(200, {"models": [{"name": "models/gemini-3.7-pro",
                                            "supportedGenerationMethods": ["generateContent"]}]})


model_chain.requests = types.SimpleNamespace(get=_get_orchestra, post=_post_orchestra,
                                             utils=__import__("requests").utils,
                                             exceptions=__import__("requests").exceptions)
model_chain.MemoriaFile = MemoriaRam          # niente file di memoria su disco
_cache_prova = app.CARTELLA_CACHE.parent / "cache_collaudo"
# Le funzioni dell'app leggono la variabile dal LORO spazio dei nomi (`_ns`),
# non dall'oggetto `app` che è solo una vista: si cambia là, altrimenti il
# collaudo usa la cache vera e la seconda volta che gira trova tutto già fatto.
_ns["CARTELLA_CACHE"] = _cache_prova
_sh.rmtree(_cache_prova, ignore_errors=True)

sei = []
for a, b in [("alfa", "zulu"), ("beta", "yankee"), ("gamma", "xray")]:
    sei.append({"filename": f"{a}.sql", "language": "SQL", "hash": a,
                "content": f"PROCEDURE P_{a.upper()} IS BEGIN P_{b.upper()}(1); END;" + "x" * 45000})
    sei.append({"filename": f"{b}.sql", "language": "SQL", "hash": b,
                "content": f"PROCEDURE P_{b.upper()} IS BEGIN NULL; END;" + "x" * 45000})
meta_sei = app.extract_technical_metadata(sei)

_chiamate.clear(); _picco[0] = 0
t0 = _t.time()
uno, _ = app.analyze_legacy_application(sei, meta_sei, "Google Gemini", "k", "", None, "qualita",
                                     ragionamento="low", parallelismo=3, usa_cache=True)
t_par = _t.time() - t0
P(f"tre lotti in parallelo: fino a {_picco[0]} chiamate in volo insieme ({t_par:.2f}s)",
  uno["_lotti"] == 3 and _picco[0] >= 2 and t_par < 0.25 * 3)
P("una sola prova di contatto per tutta l'esecuzione, non una per lotto",
  _chiamate.count("prova") == 1 and _chiamate.count("analisi") == 3)
P("i risultati dei lotti sono tutti presenti, in ordine, con id unici",
  len(uno["business_rules"]) == 6
  and len({r["rule_id"] for r in uno["business_rules"]}) == 6)

_chiamate.clear()
due, _ = app.analyze_legacy_application(sei, meta_sei, "Google Gemini", "k", "", None, "qualita",
                                     ragionamento="low", parallelismo=3, usa_cache=True)
P("la seconda esecuzione identica non paga nessun lotto: tutti dalla cache",
  _chiamate.count("analisi") == 0 and due["_riusati"] == 3
  and len(due["business_rules"]) == 6)

sette = sei + [{"filename": "nuovo.sql", "language": "SQL", "hash": "nuovo",
                "content": "PROCEDURE P_NUOVO IS BEGIN NULL; END;" + "x" * 45000}]
_chiamate.clear()
tre, _ = app.analyze_legacy_application(sette, app.extract_technical_metadata(sette), "Google Gemini",
                                     "k", "", None, "qualita", ragionamento="low",
                                     parallelismo=2, usa_cache=True)
P(f"aggiunto un file, si paga solo il lotto nuovo ({_chiamate.count('analisi')} analisi, "
  f"{tre['_riusati']} dalla cache)",
  _chiamate.count("analisi") >= 1 and tre["_riusati"] >= 2)

_chiamate.clear()
app.analyze_legacy_application(sei, meta_sei, "Google Gemini", "k", "", None, "qualita",
                               ragionamento="low", parallelismo=1, usa_cache=False)
P("«da capo» ignora la cache e ripaga tutto", _chiamate.count("analisi") == 3)

_chiamate.clear()
rapida, _ = app.analyze_legacy_application(sei[:2], app.extract_technical_metadata(sei[:2]),
                                        "Google Gemini", "k", "", None, "qualita",
                                        ragionamento="low", profondita="quick", usa_cache=False)
P("la profondità Quick lascia vuote le sezioni non chieste senza segnalarle come mancanti",
  rapida["_profondita"] == "quick" and rapida["impact_analysis"] == []
  and not any("impact_analysis" in a for a in rapida["contract_warnings"]))
P("la cache distingue Quick da Full: sono risposte diverse",
  app.chiave_lotto(sei[:2], "g", "", "q", "low", "quick")
  != app.chiave_lotto(sei[:2], "g", "", "q", "low", "full"))
_sh.rmtree(_cache_prova, ignore_errors=True)


# =============================================================================
# LA RISPOSTA TAGLIATA SI CONTINUA, CON LO STESSO MODELLO
# =============================================================================
_chiamate.clear()
_pezzi = ['{"executive_summary":"S.","application_purpose":"P.","business_rules":[{"rule_name":"Discount ov',
          'er 100","condition":"t>100","confidence":"HIGH"},{"rule_name":"Late fee","condition":"d>30",',
          '"confidence":"HIGH"}],"complete":true}']
_stato_finto = {"giro": 0, "modelli": []}


def _post_taglia(url, **kw):
    corpo = kw.get("json") or {}
    contenuti = corpo.get("contents", [])
    prompt = contenuti[0]["parts"][0]["text"] if contenuti else ""
    _stato_finto["modelli"].append(url.split("/models/")[1].split(":")[0])
    if "OK." in prompt:
        return FintaRisposta(200, {"candidates": [{"content": {"parts": [{"text": "OK"}]},
                                                  "finishReason": "STOP"}]})
    # prima risposta: primo pezzo, tagliato. Continuazioni: i pezzi seguenti.
    # Il pezzo scritto finora deve tornare nella conversazione, come turno
    # del modello: se non torna, il modello non sa da dove riprendere.
    giro = _stato_finto["giro"]
    if giro > 0:
        assert len(contenuti) == 3 and contenuti[1]["role"] == "model", "manca il pezzo scritto"
        assert "responseSchema" not in corpo.get("generationConfig", {}), "schema in continuazione"
    _stato_finto["giro"] += 1
    pezzo = _pezzi[min(giro, len(_pezzi) - 1)]
    ultimo = giro >= len(_pezzi) - 1
    return FintaRisposta(200, {"candidates": [{"content": {"parts": [{"text": pezzo}]},
                                              "finishReason": "STOP" if ultimo else "MAX_TOKENS"}]})


def _get_due(url, **kw):
    return FintaRisposta(200, {"models": [
        {"name": "models/gemini-3.7-pro", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3.7-flash", "supportedGenerationMethods": ["generateContent"]}]})


model_chain.requests = types.SimpleNamespace(get=_get_due, post=_post_taglia,
                                             utils=__import__("requests").utils,
                                             exceptions=__import__("requests").exceptions)
piccolo = [{"filename": "a.sql", "language": "SQL", "hash": "cont1",
            "content": "PROCEDURE P IS BEGIN NULL; END;"}]
_stato_finto.update(giro=0, modelli=[])
ris, stati = app.analyze_legacy_application(piccolo, app.extract_technical_metadata(piccolo),
                                            "Google Gemini", "k", "", None, "qualita",
                                            ragionamento="low", usa_cache=False)
P("una risposta tagliata viene continuata da sola fino al tag di chiusura",
  stati[0]["completo"] and stati[0]["giri"] == 2 and not ris["_incompleti"])
P("il pezzo tagliato a metà parola viene riattaccato giusto",
  any(r["rule_name"] == "Discount over 100" for r in ris["business_rules"])
  and len(ris["business_rules"]) == 2)
P("si continua con LO STESSO modello: il secondo della catena non viene mai chiamato",
  set(_stato_finto["modelli"]) == {"gemini-3.7-pro"})

# ── un modello che non finisce mai in due giri: si ferma e chiede a una persona ──
_pezzi_lunghi = ['{"executive_summary":"S.","application_purpose":"P.","business_rules":[',
                 '{"rule_name":"A","condition":"a","confidence":"HIGH"},',
                 '{"rule_name":"B","condition":"b","confidence":"HIGH"},',
                 '{"rule_name":"C","condition":"c","confidence":"HIGH"}],"complete":true}']
_pezzi[:] = _pezzi_lunghi
_stato_finto.update(giro=0, modelli=[])
ris2, stati2 = app.analyze_legacy_application(
    [{"filename": "b.sql", "language": "SQL", "hash": "cont2", "content": "PROCEDURE Q IS BEGIN NULL; END;"}],
    app.extract_technical_metadata([{"filename": "b.sql", "language": "SQL", "hash": "cont2",
                                     "content": "PROCEDURE Q IS BEGIN NULL; END;"}]),
    "Google Gemini", "k", "", None, "qualita", ragionamento="low", usa_cache=False)
P("dopo le continuazioni automatiche, una risposta ancora a metà si ferma e lo dichiara",
  not stati2[0]["completo"] and ris2["_incompleti"] == [1]
  and any("incomplete" in a for a in ris2["contract_warnings"]))
P("intanto le righe già scritte si vedono, riparate",
  len(ris2["business_rules"]) >= 1)
# il bottone «Continue»: un giro in più, a mano
catena_c = app.build_chain("Google Gemini", "k", None, "", "qualita", [], "low")
stati2[0] = app.continua_lotto(catena_c, stati2[0], "low")
P("il bottone «Continue» riprende dallo stesso punto e arriva in fondo",
  stati2[0]["completo"] and stati2[0]["giri"] == 3)
ric = app.componi_risultato(stati2, {}, catena_c, "Google Gemini", [[]], "full", "low", 0, [], 0)
P("a risposta completa il risultato si ricompone e l'avvio si sblocca",
  ric["_incompleti"] == [] and len(ric["business_rules"]) == 3)


# ── se il modello che scriveva è occupato, si aspetta LUI, non si cambia ──
_conta = {"busy": 0}


def _post_occupato(url, **kw):
    corpo = kw.get("json") or {}
    contenuti = corpo.get("contents", [])
    if len(contenuti) == 3:   # è una continuazione
        _conta["busy"] += 1
        if _conta["busy"] < 2:
            return FintaRisposta(503, {}, "occupato")
        return FintaRisposta(200, {"candidates": [{"content": {"parts": [{"text": '"x"}],"complete":true}'}]},
                                                  "finishReason": "STOP"}]})
    return FintaRisposta(200, {"candidates": [{"content": {"parts": [{"text": "OK"}]}, "finishReason": "STOP"}]})


model_chain.requests = types.SimpleNamespace(get=_get_due, post=_post_occupato,
                                             utils=__import__("requests").utils,
                                             exceptions=__import__("requests").exceptions)
catena_o = CatenaModelli(provider="gemini", chiave="k", memoria=MemoriaRam(),
                         cfg={"pausa_base_s": 0.01})
seguito = catena_o.continua("gemini-3.7-pro", "p", '{"a":[', sistema="s", ragionamento="low")
P("un modello occupato durante la continuazione viene riprovato, non sostituito",
  _conta["busy"] == 2 and seguito.modello == "gemini-3.7-pro")


# =============================================================================
# IL MODELLO PREFERITO CONTA DAVVERO, PER TUTTI I PROVIDER
# =============================================================================
AI, ch = nuova({"*": {"stato": 200}})
r = AI.chiedi("x")
primo_automatico = ch[0]
AI, ch = nuova({"*": {"stato": 200}}, preferito="gemini-3.5-flash")
r = AI.chiedi("x")
P(f"il modello scelto a mano è il primo a essere provato (era {primo_automatico})",
  ch[0] == "gemini-3.5-flash" and r.modello == "gemini-3.5-flash")

AI, ch = nuova({"gemini-3.5-flash": {"stato": 503}, "*": {"stato": 200}}, preferito="gemini-3.5-flash")
r = AI.chiedi("x")
P("se il modello scelto è giù, si ricade sul migliore disponibile — dopo averlo riprovato",
  r.modello == "gemini-3.7-pro" and ch.count("gemini-3.5-flash") == 2)

mem = MemoriaRam()
AI, ch = nuova({"*": {"stato": 200}}, memoria=mem)
AI.chiedi("x")                                            # ricorda il buono automatico
AI2 = CatenaModelli(provider="gemini", chiave="k", memoria=mem, preferito="gemini-3.5-flash")
AI2.chiedi("y")
P("la scelta della persona vince sulla memoria del modello buono",
  ch[-1] == "gemini-3.5-flash")

AI, ch = nuova({"*": {"stato": 200}}, preferito="gemini-9.9-custom")
r = AI.chiedi("x")
P("un modello scelto che la scoperta non conosce viene comunque provato per primo",
  ch[0] == "gemini-9.9-custom")


# =============================================================================
# QUANDO CHI SCRIVEVA NON RISPONDE PIÙ: NON SI RESTA BLOCCATI
# =============================================================================
_quota = {"chiamate": []}


def _post_quota(url, **kw):
    corpo = kw.get("json") or {}
    contenuti = corpo.get("contents", [])
    modello = url.split("/models/")[1].split(":")[0]
    _quota["chiamate"].append(modello)
    prompt = contenuti[0]["parts"][0]["text"] if contenuti else ""
    if "OK." in prompt:
        return FintaRisposta(200, {"candidates": [{"content": {"parts": [{"text": "OK"}]}, "finishReason": "STOP"}]})
    if len(contenuti) == 3:            # continuazione
        if modello == "gemini-3.7-pro":
            return FintaRisposta(429, {}, "quota exhausted")
        return FintaRisposta(200, {"candidates": [{"content": {"parts": [{"text": '"B","condition":"b","confidence":"HIGH"}],"complete":true}'}]},
                                                  "finishReason": "STOP"}]})
    # prima risposta: tagliata
    return FintaRisposta(200, {"candidates": [{"content": {"parts": [{"text": '{"executive_summary":"S.","application_purpose":"P.","business_rules":[{"rule_name":"A","condition":"a","confidence":"HIGH"},{"rule_name":'}]},
                                              "finishReason": "MAX_TOKENS"}]})


model_chain.requests = types.SimpleNamespace(get=_get_due, post=_post_quota,
                                             utils=__import__("requests").utils,
                                             exceptions=__import__("requests").exceptions)
src_q = [{"filename": "q.sql", "language": "SQL", "hash": "quota1", "content": "PROCEDURE Q IS BEGIN NULL; END;"}]
ris_q, stati_q = app.analyze_legacy_application(src_q, app.extract_technical_metadata(src_q),
                                                "Google Gemini", "k", "", None, "qualita",
                                                ragionamento="low", usa_cache=False,
                                                parallelismo=1)
P("se il modello finisce la quota durante la continuazione automatica, l'esecuzione NON cade",
  ris_q["_incompleti"] == [1] and stati_q[0]["continuazione_fallita"] == "quota")
P("e non si cambia modello di nascosto: solo il primo è stato interpellato",
  set(_quota["chiamate"]) == {"gemini-3.7-pro"})
P("le righe già scritte restano leggibili intanto",
  any(r["rule_name"] == "A" for r in ris_q["business_rules"]))

catena_q = app.build_chain("Google Gemini", "k", None, "", "qualita", [], "low")
prossimo = catena_q.successivo("gemini-3.7-pro")
P(f"la catena sa qual è il modello dopo ({prossimo})", prossimo == "gemini-3.7-flash")
stati_q[0] = app.continua_lotto(catena_q, stati_q[0], "low", modello=prossimo)
P("su decisione della persona, il seguito passa al modello dopo e la risposta si chiude",
  stati_q[0]["completo"] and stati_q[0]["modello"] == "gemini-3.7-flash"
  and len([r for r in stati_q[0]["risultato"]["business_rules"]]) == 2)
P("il documento dirà che quel lotto l'hanno finito due modelli diversi",
  any("different model" in a for a in stati_q[0]["risultato"]["contract_warnings"]))


# =============================================================================
# LE ETICHETTE CHE ROMPEVANO IL DIAGRAMMA
# («Syntax error in text» sul data flow costruito dalle tabelle)
# =============================================================================
P("una freccia dentro l'etichetta non è più una freccia",
  contract._pulisci_etichetta("order --> invoice") == "order to invoice"
  and contract._pulisci_etichetta("job -> out") == "job to out"
  and contract._pulisci_etichetta("A -.-> B") == "A to B")
P("le parole col trattino restano parole",
  contract._pulisci_etichetta("co-ordinate le date") == "co-ordinate le date"
  and contract._pulisci_etichetta("24-48 ore") == "24-48 ore")
P("`&` e `#`, che in Mermaid hanno un significato, spariscono dalle etichette",
  "&" not in contract._pulisci_etichetta("R&D data")
  and "#" not in contract._pulisci_etichetta("record #5"))

flusso = diagrams.data_flow(contract.normalizza({"data_flows": [
    {"source": "ORDERS", "target": "SAP #FI", "data_description": "order --> invoice, daily & full"}]}))
riga = flusso.splitlines()[1]
P(f"il data flow costruito dalle tabelle esce sintatticamente sano ({riga.strip()[:52]}…)",
  riga.count("-->") == 1 and '|"' in riga and '"|' in riga
  and "&" not in riga and "#" not in riga)
P("le etichette sugli archi sono fra virgolette, come quelle dei nodi",
  '-->|"' in diagrams.data_flow(contract.normalizza({"data_flows": [
      {"source": "A", "target": "B", "data_description": "x, y: z"}]})))
P("anche il Mermaid scritto dal modello viene ripulito allo stesso modo",
  contract.pulisci_mermaid(["flowchart LR", '  A["x"] -->|da A --> B| B["y"]']
                           ).count("-->") == 1)
P("le frecce con lettera (--o, --x) restano frecce",
  contract.pulisci_mermaid(["flowchart TD", '  A["x"] --o B["y"]']).endswith('--o B["y"]'))

print()
print(f"{sum(ESITI)}/{len(ESITI)} casi passati")
sys.exit(0 if all(ESITI) else 1)
