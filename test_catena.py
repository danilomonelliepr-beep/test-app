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

print()
print(f"{sum(ESITI)}/{len(ESITI)} casi passati")
sys.exit(0 if all(ESITI) else 1)
