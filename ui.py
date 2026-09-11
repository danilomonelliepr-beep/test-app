"""
═══════════════════════════════════════════════════════════════════════════
L'INTERFACCIA — tema, componenti, e il sistema dei marcatori.

Il mestiere di questa applicazione non è mostrare dati: è far giudicare a una
persona delle righe prodotte da una macchina. Quindi la cosa che l'interfaccia
deve dire meglio di tutto è **da dove viene ogni riga e quanto è solida** —
fatto del parser o inferenza del modello, confermata da un esperto o ancora da
guardare. È lì che va speso il poco colore che c'è; tutto il resto sta zitto.

Scelte, e perché:

· CARATTERE. IBM Plex Sans e IBM Plex Mono. Non è un vezzo: questa applicazione
  documenta COBOL, RPG e PL/SQL, e Plex è il carattere dell'azienda le cui
  macchine fanno girare quella roba. Il monospazio è riservato a ciò che è
  letterale — nomi di componenti, file, frammenti di codice — così la differenza
  fra «testo scritto da qualcuno» e «stringa presa dal sorgente» si vede senza
  doverla leggere.

· COLORE. Inchiostro blu-nero su carta grigio-fredda, accento verde-petrolio.
  L'accento non è mai portatore di significato: serve solo a dire dove si può
  cliccare. Il significato sta nella scala di gravità, che è l'unica cosa calda
  della pagina e per questo si vede subito.

· MAI IL COLORE DA SOLO. Ogni marcatore porta una forma e una parola oltre al
  colore: un daltonico e uno schermo in bianco e nero devono leggere la stessa
  cosa. Vale anche nelle tabelle, dove gli enum sono menù a tendina con la
  parola scritta per esteso.

· MOTO. Nessuna animazione d'ingresso, nessuna transizione sulle schede. Le
  uniche transizioni sono quelle che rispondono a un gesto (un bottone che si
  scurisce quando ci passi sopra), e si spengono da sole con
  `prefers-reduced-motion`.

Tutti i componenti nuovi verificano prima che Streamlit li sappia fare: se
un'installazione è più vecchia, l'interfaccia perde un bordo, non una funzione.
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import html
import inspect
from typing import Any, Dict, List, Optional

import streamlit as st

# ── Larghezza piena, senza avvisi di obsolescenza ─────────────────────────
# Streamlit ha sostituito `use_container_width=True` con `width="stretch"`, e
# il vecchio nome è in via di rimozione. Si guarda la firma vera invece di
# confrontare numeri di versione: funziona anche sulle versioni in mezzo.
def _accetta_width(funzione) -> bool:
    try:
        return "width" in inspect.signature(funzione).parameters
    except (TypeError, ValueError):
        return False


LARGA = {"width": "stretch"} if _accetta_width(st.button) else {"use_container_width": True}

# =============================================================================
# I TOKEN — tutto il colore e tutta la spaziatura stanno qui.
# I valori sono scelti per il contrasto: inchiostro su carta è 13:1, l'accento
# su bianco è 5,6:1, ogni testo di stato sul proprio fondo supera 4,5:1.
# =============================================================================
TEMA = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
  --inchiostro:  #17212B;
  --inchiostro-2:#4A5A6B;
  --carta:       #F1F4F7;
  --superficie:  #FFFFFF;
  --riga:        #D4DCE4;
  --accento:     #15616D;
  --accento-cupo:#0E434C;
  --critico:     #9B2226;
  --alto:        #9A5B00;
  --medio:       #3F5265;
  --basso:       #6B7A89;
  --conferma:    #1F6B45;
  --r:           6px;
}

/* ── base ─────────────────────────────────────────────────────────────── */
html, body, [class*="css"], .stApp {
  font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  color: var(--inchiostro);
}
.stApp { background: var(--carta); }
.block-container { padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1320px; }
p, li { font-size: 0.95rem; line-height: 1.62; }
h1, h2, h3, h4 { font-weight: 600; letter-spacing: -0.01em; color: var(--inchiostro); }
h1 { font-size: 1.75rem; }
h2 { font-size: 1.25rem; margin-top: 1.6rem; }
h3 { font-size: 1.02rem; }
a { color: var(--accento); }
code, kbd, pre, .stCode { font-family: 'IBM Plex Mono', ui-monospace, monospace; }

/* ── testata ──────────────────────────────────────────────────────────── */
.testata { border-bottom: 2px solid var(--inchiostro); padding-bottom: 0.9rem;
           margin-bottom: 1.1rem; }
.testata h1 { margin: 0 0 0.25rem 0; }
.testata .compito { color: var(--inchiostro-2); font-size: 0.95rem; margin: 0;
                    max-width: 64ch; }

/* ── marcatori: forma + parola + colore, mai il colore da solo ────────── */
.fila { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
.fila > * { margin: 0 0.12rem 0.12rem 0; }   /* riserva se `gap` non è supportato */
.marca { display: inline-flex; align-items: center; gap: 0.32rem;
         border: 1px solid var(--riga); border-radius: 999px;
         padding: 0.14rem 0.6rem; font-size: 0.78rem; font-weight: 500;
         background: var(--superficie); color: var(--inchiostro-2);
         white-space: nowrap; }
.marca .segno { font-family: 'IBM Plex Mono', monospace; font-weight: 600;
                margin-right: 0.18rem; }
.marca.accesa   { border-color: var(--accento); color: var(--accento-cupo);
                  background: #E8F1F2; }
.marca.critica  { border-color: var(--critico); color: var(--critico); background: #FDF0F0; }
.marca.alta     { border-color: var(--alto);    color: var(--alto);    background: #FDF5E8; }
.marca.ok       { border-color: var(--conferma);color: var(--conferma);background: #ECF6F1; }
.marca.spenta   { opacity: 0.75; }

/* ── cifre di sintesi ─────────────────────────────────────────────────── */
.cifre { display: flex; flex-wrap: wrap; gap: 0.55rem; margin: 0.2rem 0 0.9rem 0; }
.cifre > * { margin: 0 0.15rem 0.15rem 0; }
.cifra { flex: 1 1 130px; background: var(--superficie); border: 1px solid var(--riga);
         border-radius: var(--r); padding: 0.65rem 0.8rem; }
.cifra .valore { font-size: 1.45rem; font-weight: 600; line-height: 1.15;
                 font-family: 'IBM Plex Mono', monospace; }
.cifra .voce  { font-size: 0.78rem; color: var(--inchiostro-2); margin-top: 0.15rem; }
.cifra .nota  { font-size: 0.72rem; color: var(--basso); margin-top: 0.2rem; }
.cifra.rilievo { border-left: 3px solid var(--accento); }

/* ── intestazione di sezione ──────────────────────────────────────────── */
.sezione { display: flex; align-items: baseline; gap: 0.6rem; flex-wrap: wrap;
           margin: 0.2rem 0 0.15rem 0; }
.sezione .nome { font-size: 1.08rem; font-weight: 600; }
.sezione .conto { font-family: 'IBM Plex Mono', monospace; font-size: 0.82rem;
                  color: var(--inchiostro-2); margin-left: 0.45rem; }
.spiega { color: var(--inchiostro-2); font-size: 0.86rem; margin: 0 0 0.5rem 0;
          max-width: 76ch; }

/* barra di validazione: la quota confermata, non una decorazione */
.avanza { height: 6px; background: #E3E9EF; border-radius: 999px; overflow: hidden;
          margin: 0.15rem 0 0.55rem 0; max-width: 320px; }
.avanza > span { display: block; height: 100%; background: var(--conferma); }

/* ── stato vuoto: un invito, non un'alzata di spalle ──────────────────── */
.vuoto { background: var(--superficie); border: 1px solid var(--riga);
         border-radius: var(--r); padding: 1.5rem 1.6rem; max-width: 760px; }
.vuoto h3 { margin: 0 0 0.5rem 0; }
.vuoto p { color: var(--inchiostro-2); margin: 0 0 1rem 0; max-width: 62ch; }
.passi { list-style: none; padding: 0; margin: 0; counter-reset: passo; }
.passi li { counter-increment: passo; padding: 0.5rem 0 0.5rem 2.2rem; position: relative;
            border-top: 1px solid var(--riga); font-size: 0.92rem; }
.passi li:before { content: counter(passo); position: absolute; left: 0; top: 0.45rem;
                   width: 1.5rem; height: 1.5rem; border-radius: 50%;
                   background: var(--inchiostro); color: #fff; font-size: 0.78rem;
                   font-family: 'IBM Plex Mono', monospace;
                   display: flex; align-items: center; justify-content: center; }
.passi b { font-weight: 600; }

/* ── schede ───────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] { gap: 0.1rem; border-bottom: 1px solid var(--riga); }
.stTabs [data-baseweb="tab"] { height: 44px; padding: 0 0.9rem; font-size: 0.92rem;
                               font-weight: 500; color: var(--inchiostro-2); }
.stTabs [aria-selected="true"] { color: var(--accento-cupo); font-weight: 600; }

/* ── controlli ────────────────────────────────────────────────────────── */
div.stButton > button, div.stDownloadButton > button {
  min-height: 42px; border-radius: var(--r); font-weight: 500;
  border: 1px solid var(--riga); background: var(--superficie); color: var(--inchiostro);
}
div.stButton > button:hover, div.stDownloadButton > button:hover {
  border-color: var(--accento); color: var(--accento-cupo); }
div.stButton > button[kind="primary"] {
  background: var(--accento); border-color: var(--accento); color: #fff; }
div.stButton > button[kind="primary"]:hover {
  background: var(--accento-cupo); border-color: var(--accento-cupo); color: #fff; }

/* il fuoco da tastiera si vede sempre, su tutto */
:where(button, input, select, textarea, a, [role="tab"], [role="checkbox"]):focus-visible {
  outline: 3px solid var(--accento); outline-offset: 2px; border-radius: 3px; }

/* ── barra laterale ───────────────────────────────────────────────────── */
[data-testid="stSidebar"] { background: var(--superficie); border-right: 1px solid var(--riga); }
[data-testid="stSidebar"] .block-container { padding-top: 1.2rem; }
.tappa { font-size: 0.72rem; font-weight: 600; color: var(--accento-cupo);
         letter-spacing: 0.02em; margin: 1.1rem 0 0.15rem 0;
         display: flex; align-items: center; gap: 0.4rem; }
.tappa span { font-family: 'IBM Plex Mono', monospace; background: #E8F1F2;
              border-radius: 3px; padding: 0 0.32rem; }

/* ── tabelle: il monospazio dove il contenuto è letterale ─────────────── */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { font-size: 0.86rem; }
[data-testid="stDataFrame"] div, [data-testid="stDataEditor"] div { font-feature-settings: 'tnum'; }

/* ── contenitori e riquadri ───────────────────────────────────────────── */
[data-testid="stExpander"] { border: 1px solid var(--riga); border-radius: var(--r);
                             background: var(--superficie); }
[data-testid="stExpander"] summary { font-weight: 500; min-height: 42px; }
.nota-riquadro { background: var(--superficie); border: 1px solid var(--riga);
                 border-left: 3px solid var(--basso); border-radius: var(--r);
                 padding: 0.7rem 0.9rem; font-size: 0.86rem; color: var(--inchiostro-2);
                 margin: 0.4rem 0; }

/* ── rispetto delle preferenze di sistema ─────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important;
                           scroll-behavior: auto !important; }
}
@media (prefers-contrast: more) {
  :root { --riga: #7A8794; --inchiostro-2: #2B3844; }
  .marca { border-width: 2px; }
}
@media (max-width: 880px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; }
  .cifra { flex-basis: 45%; }
}
</style>
"""


def applica_tema() -> None:
    st.markdown(TEMA, unsafe_allow_html=True)


# =============================================================================
# I MARCATORI — forma, parola, colore. In quest'ordine di importanza.
# =============================================================================
SEGNI_GRAVITA = {"CRITICAL": ("▲", "critica"), "HIGH": ("▲", "alta"),
                 "MEDIUM": ("◆", ""), "LOW": ("•", "spenta")}
SEGNI_CONFIDENZA = {"HIGH": "●●●", "MEDIUM": "●●○", "LOW": "●○○"}
SEGNI_ORIGINE = {"STATIC_ANALYSIS": ("■", "Parser"), "LLM_ANALYSIS": ("□", "Model"),
                 "MIXED": ("◧", "Both")}


def _e(t: Any) -> str:
    return html.escape(str(t if t is not None else ""))


def marca(testo: str, segno: str = "", tono: str = "") -> str:
    """Un marcatore. `tono` ∈ {'', 'accesa', 'critica', 'alta', 'ok', 'spenta'}."""
    s = f'<span class="segno">{_e(segno)}</span>' if segno else ""
    return f'<span class="marca {tono}">{s}{_e(testo)}</span>'


def fila(marcatori: List[str]) -> None:
    st.markdown('<div class="fila">' + "".join(marcatori) + "</div>", unsafe_allow_html=True)


def marca_gravita(valore: str) -> str:
    segno, tono = SEGNI_GRAVITA.get(str(valore).upper(), ("•", "spenta"))
    return marca(str(valore).upper(), segno, tono)


def marca_origine(valore: str) -> str:
    segno, etichetta = SEGNI_ORIGINE.get(str(valore).upper(), ("□", "Model"))
    return marca(etichetta, segno)


# =============================================================================
# TESTATA, CIFRE, SEZIONI
# =============================================================================
def testata(titolo: str, compito: str, marcatori: Optional[List[str]] = None) -> None:
    st.markdown(
        f'<div class="testata"><h1>{_e(titolo)}</h1>'
        f'<p class="compito">{_e(compito)}</p></div>', unsafe_allow_html=True)
    if marcatori:
        fila(marcatori)


def cifre(voci: List[Dict[str, Any]]) -> None:
    """Le cifre di sintesi. `voci` = [{valore, voce, nota?, rilievo?}, …]

    Sono `div` e non `st.metric` perché servono la nota sotto e il monospazio
    sul numero: due numeri incolonnati si confrontano con l'occhio solo se le
    cifre hanno tutte la stessa larghezza."""
    pezzi = []
    for v in voci:
        nota = f'<div class="nota">{_e(v["nota"])}</div>' if v.get("nota") else ""
        classe = "cifra rilievo" if v.get("rilievo") else "cifra"
        pezzi.append(f'<div class="{classe}"><div class="valore">{_e(v["valore"])}</div>'
                     f'<div class="voce">{_e(v["voce"])}</div>{nota}</div>')
    st.markdown('<div class="cifre">' + "".join(pezzi) + "</div>", unsafe_allow_html=True)


def sezione(nome: str, spiegazione: str = "", conto: Optional[int] = None,
            confermate: Optional[int] = None) -> None:
    conteggio = ""
    if conto is not None:
        conteggio = f'<span class="conto">{conto} righe</span>'
        if confermate is not None and conto:
            conteggio = (f'<span class="conto">{confermate} di {conto} righe confermate</span>')
    st.markdown(f'<div class="sezione"><span class="nome">{_e(nome)}</span>{conteggio}</div>',
                unsafe_allow_html=True)
    if conto and confermate is not None:
        quota = int(round(confermate / conto * 100))
        st.markdown(f'<div class="avanza"><span style="width:{quota}%"></span></div>',
                    unsafe_allow_html=True)
    if spiegazione:
        st.markdown(f'<p class="spiega">{_e(spiegazione)}</p>', unsafe_allow_html=True)


def tappa(numero: str, testo: str) -> None:
    """L'intestazione di una tappa nella barra laterale. I numeri ci stanno
    perché questo È una sequenza: senza chiave non si analizza, senza sorgenti
    non si esporta."""
    st.markdown(f'<div class="tappa"><span>{_e(numero)}</span>{_e(testo)}</div>',
                unsafe_allow_html=True)


def nota(testo: str) -> None:
    st.markdown(f'<div class="nota-riquadro">{_e(testo)}</div>', unsafe_allow_html=True)


def stato_vuoto(titolo: str, invito: str, passi: List[str]) -> None:
    voci = "".join(f"<li>{p}</li>" for p in passi)  # i passi possono contenere <b>
    st.markdown(f'<div class="vuoto"><h3>{_e(titolo)}</h3><p>{_e(invito)}</p>'
                f'<ul class="passi">{voci}</ul></div>', unsafe_allow_html=True)


# =============================================================================
# COMPATIBILITÀ — Streamlit cambia in fretta. Qui si prova prima di usare, così
# un'installazione più vecchia perde un bordo, non una funzione.
# =============================================================================
def riquadro(bordo: bool = True):
    try:
        return st.container(border=bordo)
    except TypeError:
        return st.container()


def scelta_segmentata(etichetta: str, opzioni: List[str], predefinita: int = 0,
                      chiave: str = "", aiuto: str = "") -> str:
    if hasattr(st, "segmented_control"):
        scelto = st.segmented_control(etichetta, opzioni, default=opzioni[predefinita],
                                      key=chiave, help=aiuto)
        return scelto or opzioni[predefinita]
    return st.radio(etichetta, opzioni, index=predefinita, key=chiave, help=aiuto,
                    horizontal=True)


def interruttore(etichetta: str, valore: bool = False, chiave: str = "", aiuto: str = "") -> bool:
    if hasattr(st, "toggle"):
        return st.toggle(etichetta, value=valore, key=chiave, help=aiuto)
    return st.checkbox(etichetta, value=valore, key=chiave, help=aiuto)


def avviso_temporaneo(testo: str, icona: str = "✓") -> None:
    if hasattr(st, "toast"):
        st.toast(testo, icon=icona)
    else:
        st.success(f"{icona} {testo}")
