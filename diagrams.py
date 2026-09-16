"""
═══════════════════════════════════════════════════════════════════════════
I DIAGRAMMI, COSTRUITI DAI DATI.

I quattro diagrammi sono l'ultima cosa che il contratto chiede al modello, dopo
dodici sezioni: è il punto in cui i modelli mollano, e infatti capita che ne
arrivi uno su quattro. Ma quei quattro disegni non contengono niente che non
sia già nelle tabelle:

    call graph        = dependencies
    application map   = application_mapping (o, in mancanza, interfaces)
    data flow         = data_flows (o, in mancanza, data_objects)
    process flow      = business_processes

Chiederli al modello significa chiedergli di ridisegnare a mano una cosa che
abbiamo già in forma strutturata — e infatti il disegno che torna a volte
contiene nodi che nelle tabelle non esistono. Costruirli qui costa un file e
risolve tre problemi in un colpo:

  1. escono sempre, anche quando il modello si ferma prima;
  2. non possono contraddire le tabelle, perché SONO le tabelle;
  3. si rifanno dopo che l'esperto di dominio ha corretto le righe. Prima lo
     SME cancellava una dipendenza sbagliata e il diagramma continuava a
     mostrarla: il documento firmato conteneva due verità diverse.

Il disegno del modello non viene buttato: quando c'è ed è più ricco di poche
righe resta, e in interfaccia si possono confrontare. Il process flow è quello
in cui il modello dà davvero qualcosa in più (sa mettere in ordine i passi);
sugli altri tre, quello costruito qui è normalmente migliore.
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

__version__ = "2026.09.16"

import re
from typing import Any, Callable, Dict, List

import contract

# Tetti: un diagramma che non si legge non documenta niente. Meglio venti archi
# veri e una riga che dice quanti ne restano fuori, che duecento archi.
MAX_ARCHI = 40
MAX_PROCESSI = 8
MAX_ETICHETTA = 44


def _fabbrica_id() -> Callable[[str], str]:
    """Nomi di nodo validi e stabili: lettere, cifre e trattino basso, mai due
    nodi diversi con lo stesso id, mai un id che comincia per cifra (mermaid
    non li accetta)."""
    mappa: Dict[str, str] = {}
    usati = set()

    def id_di(nome: str) -> str:
        chiave = str(nome).strip().lower()
        if chiave in mappa:
            return mappa[chiave]
        base = re.sub(r"[^A-Za-z0-9_]", "_", str(nome).strip())
        base = re.sub(r"_+", "_", base).strip("_")[:24] or "x"
        # PREFISSO SEMPRE, non solo quando il nome comincia per cifra.
        # Un id nudo può coincidere con una proprietà che ogni oggetto
        # JavaScript eredita (`toLocaleString`, `constructor`, `valueOf`): Mermaid
        # tiene i nodi in un oggetto normale, crede che il nodo esista già e
        # muore con «Cannot set properties of undefined (setting 'order')».
        # Elencare le parole da evitare è una rincorsa; il prefisso chiude la
        # famiglia intera, comprese quelle che aggiungeranno domani.
        base = "n_" + base
        candidato, i = base, 2
        while candidato in usati:
            candidato, i = f"{base}_{i}", i + 1
        usati.add(candidato)
        mappa[chiave] = candidato
        return candidato

    return id_di


# Tutti i nodi sono rettangoli `["…"]`. Le forme più espressive (stadio,
# cilindro) attraversano la pulizia del contratto, che le riporta comunque a
# rettangolo dopo aver fatto un giro di troppo sull'etichetta: tanto vale
# partire già nella forma in cui si arriva.
def _et(testo: Any, massimo: int = MAX_ETICHETTA) -> str:
    """L'etichetta, ripulita con le stesse regole del contratto e accorciata."""
    t = contract._pulisci_etichetta(str(testo or "").strip())
    t = re.sub(r"\s+", " ", t)
    if len(t) > massimo:
        t = t[: massimo - 1].rstrip() + "…"
    return t or "?"


def _coda(righe: List[str], scartati: int) -> List[str]:
    if scartati > 0:
        righe.append(f'  n_altri["… and {scartati} more not shown"]')
    return righe


def _valore(riga: Dict[str, Any], *campi: str) -> str:
    for c in campi:
        v = str(riga.get(c, "") or "").strip()
        if v:
            return v
    return ""


# =============================================================================
# 1 · PROCESS FLOW — trigger → processo → esito, un ramo per processo.
# =============================================================================
def process_flow(r: Dict[str, Any]) -> str:
    processi = [p for p in r.get("business_processes", []) if _valore(p, "process_name")]
    if not processi:
        return ""
    idd = _fabbrica_id()
    righe = ["flowchart TD"]
    for p in processi[:MAX_PROCESSI]:
        nome = _valore(p, "process_name")
        np = idd("P_" + nome)
        righe.append(f'  {np}["{_et(nome)}"]')
        trigger = _valore(p, "trigger")
        if trigger:
            nt = idd("T_" + nome)
            righe.append(f'  {nt}["{_et(trigger)}"] --> {np}')
        # I passi, se ci sono, si incatenano NELL'ORDINE in cui il modello li
        # ha scritti: è l'unica cosa che sa lui e che dalle tabelle non si
        # ricava, ed è il motivo per cui il suo disegno era migliore del
        # nostro. Ora è un dato, quindi il disegno costruito qui lo sa.
        passi = [x.strip() for x in _valore(p, "steps").split(";") if x.strip()]
        precedente = np
        for i, passo in enumerate(passi[:8], start=1):
            corrente = idd(f"S_{nome}_{i}")
            righe.append(f'  {precedente} --> {corrente}["{_et(passo, 38)}"]')
            precedente = corrente
        esito = _valore(p, "outcome")
        if esito:
            ne = idd("O_" + nome)
            righe.append(f'  {precedente} --> {ne}["{_et(esito)}"]')
        # I componenti coinvolti appesi al processo: sono il ponte fra il
        # linguaggio del business e i nomi che stanno nel codice.
        componenti = [c.strip() for c in _valore(p, "involved_components").split(";") if c.strip()]
        for c in componenti[:4]:
            righe.append(f'  {np} -.-> {idd("C_" + c)}["{_et(c, 28)}"]')
    return "\n".join(_coda(righe, max(0, len(processi) - MAX_PROCESSI)))


# =============================================================================
# 2 · APPLICATION MAP — questa applicazione al centro, i sistemi attorno.
# =============================================================================
def application_map(r: Dict[str, Any]) -> str:
    idd = _fabbrica_id()
    righe = ["flowchart LR", '  n_app["This application"]']
    visti = set()
    scritti = 0
    for m in r.get("application_mapping", []):
        esterno = _valore(m, "external_system")
        if not esterno:
            continue
        chiave = esterno.lower()
        ne = idd("S_" + esterno)
        if chiave not in visti:
            righe.append(f'  {ne}["{_et(esterno)}"]')
            visti.add(chiave)
        etichetta = _et(_valore(m, "integration_type") or "link", 22)
        direzione = _valore(m, "direction").upper()
        if direzione == "INBOUND":
            righe.append(f'  {ne} -->|"{etichetta}"| n_app')
        elif direzione == "OUTBOUND":
            righe.append(f'  n_app -->|"{etichetta}"| {ne}')
        else:
            righe.append(f'  n_app <-->|"{etichetta}"| {ne}')
        scritti += 1
        if scritti >= MAX_ARCHI:
            break
    if scritti:
        return "\n".join(righe)
    # Senza mappatura applicativa si ripiega sulle interfacce: dicono comunque
    # dov'è il confine dell'applicazione.
    per_tipo: Dict[str, List[str]] = {}
    for i in r.get("interfaces", []):
        tipo = _valore(i, "interface_type") or "INTERFACE"
        nome = _valore(i, "name")
        if nome:
            per_tipo.setdefault(tipo, []).append(nome)
    if not per_tipo:
        return ""
    for tipo, nomi in list(per_tipo.items())[:MAX_ARCHI]:
        nt = idd("I_" + tipo)
        righe.append(f'  n_app <--> {nt}["{_et(tipo, 24)} ({len(nomi)})"]')
    return "\n".join(righe)


# =============================================================================
# 3 · DATA FLOW — da dove a dove, con che dato.
# =============================================================================
def data_flow(r: Dict[str, Any]) -> str:
    idd = _fabbrica_id()
    righe = ["flowchart LR"]
    scritti = 0
    flussi = r.get("data_flows", [])
    for f in flussi:
        sorgente, destinazione = _valore(f, "source"), _valore(f, "target")
        if not sorgente or not destinazione:
            continue
        dato = _et(_valore(f, "data_description", "transformation") or "data", 26)
        righe.append(f'  {idd("F_" + sorgente)}["{_et(sorgente, 30)}"] -->|"{dato}"| '
                     f'{idd("F_" + destinazione)}["{_et(destinazione, 30)}"]')
        scritti += 1
        if scritti >= MAX_ARCHI:
            break
    if scritti:
        return "\n".join(_coda(righe, max(0, len(flussi) - scritti)))
    # In mancanza dei flussi, gli oggetti dati con l'operazione che li tocca:
    # è meno ricco ma è vero, e viene dal parser.
    oggetti = [o for o in r.get("data_objects", []) if _valore(o, "object_name")]
    if not oggetti:
        return ""
    for o in oggetti[:MAX_ARCHI]:
        file_sorgente = _valore(o, "source_file") or "code"
        operazione = _et(_valore(o, "operation") or "USES", 14)
        righe.append(f'  {idd("D_" + file_sorgente)}["{_et(file_sorgente, 30)}"] -->|"{operazione}"| '
                     f'{idd("D_" + _valore(o, "object_name"))}["{_et(_valore(o, "object_name"), 30)}"]')
    return "\n".join(_coda(righe, max(0, len(oggetti) - MAX_ARCHI)))


# =============================================================================
# 4 · CALL GRAPH — le dipendenze, con le certe prima.
# =============================================================================
_PESO = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def call_graph(r: Dict[str, Any]) -> str:
    dipendenze = [d for d in r.get("dependencies", [])
                  if _valore(d, "source") and _valore(d, "target")]
    if not dipendenze:
        return ""
    # Quando le dipendenze sono più di quante ne stanno in un disegno, si
    # tengono le più affidabili: le PROBABLE_CALL sono le prime a uscire.
    def ordine(d):
        tipo = _valore(d, "dependency_type")
        return (1 if tipo == "PROBABLE_CALL" else 0,
                _PESO.get(_valore(d, "confidence").upper(), 3),
                _valore(d, "source"))

    scelte = sorted(dipendenze, key=ordine)[:MAX_ARCHI]
    idd = _fabbrica_id()
    righe = ["flowchart LR"]
    for d in scelte:
        sorgente, destinazione = _valore(d, "source"), _valore(d, "target")
        tipo = _valore(d, "dependency_type")
        freccia = "-.->" if tipo == "PROBABLE_CALL" else "-->"
        etichetta = f'|"{_et(tipo, 20)}"|' if tipo else ""
        righe.append(f'  {idd(sorgente)}["{_et(sorgente, 30)}"] {freccia}{etichetta} '
                     f'{idd(destinazione)}["{_et(destinazione, 30)}"]')
    return "\n".join(_coda(righe, max(0, len(dipendenze) - len(scelte))))


COSTRUTTORI = {
    "mermaid_process_flow": process_flow,
    "mermaid_application_map": application_map,
    "mermaid_data_flow": data_flow,
    "mermaid_call_graph": call_graph,
}


def costruisci(risultato: Dict[str, Any]) -> Dict[str, str]:
    """I quattro diagrammi ricavati dai dati. Passa dalla stessa pulizia che
    subisce il disegno del modello, così non ci sono due strade diverse verso
    il renderer."""
    fuori = {}
    for campo, fn in COSTRUTTORI.items():
        try:
            fuori[campo] = contract.pulisci_mermaid(fn(risultato))
        except Exception as e:  # un diagramma non deve mai far cadere l'analisi
            fuori[campo] = ""
            print(f"[Diagrammi] {campo}: {type(e).__name__} {e}")
    return fuori


MINIMO_RIGHE = 3  # sotto questa soglia il disegno del modello non dice nulla

# Provenienza di ogni diagramma, per dirlo accanto al disegno invece che nel
# pannello degli avvisi: "modello", "dati", oppure "" quando non c'è.
FONTI = {"modello": "From the model",
         "dati": "Built from the validated data",
         "": "No diagram"}


def arricchisci(risultato: Dict[str, Any]) -> Dict[str, Any]:
    """Mette accanto a ogni diagramma quello costruito dai dati e sceglie quale
    mostrare: si tiene il modello se ha prodotto qualcosa di sostanzioso, si
    passa ai dati altrimenti. La scelta è sempre reversibile in interfaccia, e
    dichiarata negli avvisi di contratto."""
    dai_dati = costruisci(risultato)
    risultato["_diagrammi_dai_dati"] = dai_dati
    memoria = risultato.setdefault("_diagrammi_dal_modello", {})
    fonte = risultato.setdefault("_diagrammi_fonte", {})
    avvisi = list(risultato.get("contract_warnings") or [])
    for campo, generato in dai_dati.items():
        # Idempotente: chiamata una seconda volta (dopo il consolidamento, che
        # aggiunge archi al call graph) NON deve prendere per «versione del
        # modello» il disegno che avevamo costruito noi al primo giro.
        del_modello = memoria.get(campo, str(risultato.get(campo) or ""))
        memoria[campo] = del_modello
        magro = len(del_modello.splitlines()) < MINIMO_RIGHE
        avvisi = [a for a in avvisi if not a.startswith(campo + ":")]
        if not magro:
            fonte[campo] = "modello"
            continue
        if generato:
            risultato[campo] = generato
            fonte[campo] = "dati"
            # NON è un avviso di contratto. Costruire il diagramma dai dati è
            # il funzionamento previsto, non un guasto da segnalare in rosso:
            # nel pannello degli avvisi sembrava un errore, e infatti è stato
            # segnalato come tale. La provenienza si dice dove serve — accanto
            # al disegno — e chi vuole l'altra versione ha l'interruttore.
        else:
            fonte[campo] = ""
            avvisi.append(
                f"{campo}: no diagram — neither the model nor the tables have enough to draw one")
    risultato["contract_warnings"] = avvisi
    return risultato
