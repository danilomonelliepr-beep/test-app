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

· COLORE. La palette corporate Electrolux Professional: blu `#011E41`
  (PMS 282 C) per inchiostro e accento, grigio-azzurro `#7B8A9C` (PMS 5415 C)
  per i bordi dei campi e i toni secondari, azzurro chiarissimo `#DFE7EA`
  (PMS 642 C) per righe e fondi, bianco `#FFFFFF` per le superfici. L'accento non è mai portatore di significato: serve solo a
  dire dove si può cliccare. Il significato sta nella scala di gravità, che è l'unica cosa calda
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

__version__ = "2026.10.02d"

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
# I valori sono scelti per il contrasto: inchiostro su carta è 14:1, l'accento
# su bianco è 15:1, ogni testo di stato sul proprio fondo supera 4,5:1.
# =============================================================================
TEMA = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
  /* Palette corporate: #011E41 · #7B8A9C · #DFE7EA · #FFFFFF.
     Le voci senza nome di palette sono sfumature di queste quattro, scurite
     dove il testo piccolo deve arrivare a 4,5:1 di contrasto. */
  --inchiostro:  #011E41;
  --inchiostro-2:#4B5868;
  --carta:       #F1F5F6;
  --superficie:  #FFFFFF;
  /* La barra laterale usa la palette Golden, per staccarsi dal blu:
     #7D653F · #9E8864 · #BFAF8F. */
  --sfondo-lato: #BFAF8F;
  --oro:         #9E8864;
  --oro-scuro:   #7D653F;
  --riga:        #DFE7EA;
  --bordo-campo: #7B8A9C;
  --accento:     #011E41;
  --accento-cupo:#00132B;
  --tinta:       #DFE7EA;
  --critico:     #9B2226;
  --alto:        #9A5B00;
  --medio:       #4B5868;
  --basso:       #5E6D80;
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
/* L'iniziale di ogni parola del titolo: il nome del prodotto — Legacy
   Application Knowledge Extractor — si legge anche come sigla, LAKE. */
.testata h1 .sigla { color: var(--accento); }
/* Il banner al posto del titolo scritto. Angoli arrotondati come il resto
   dell'interfaccia; nessun bordo, perché l'immagine è scura e su carta
   chiara si stacca già da sé. `display:block` toglie lo spazio che il
   browser lascia sotto un'immagine trattata come testo. */
.testata svg { display: block; width: 100%; height: auto;
               border-radius: var(--r); margin: 0 0 0.55rem 0; }
/* Il titolo resta nella pagina per chi la ascolta invece di guardarla:
   fuori dallo schermo, non `display:none`, che lo toglierebbe anche a loro. */
.solo-lettori { position: absolute; width: 1px; height: 1px; padding: 0;
                margin: -1px; overflow: hidden; clip: rect(0 0 0 0);
                white-space: nowrap; border: 0; }
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
                  background: var(--tinta); }
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
/* una barra sottile dentro la carta, per il solo numero che cresce mentre si
   lavora: le righe confermate */
.cifra .pista-c { height: 5px; background: var(--riga); border-radius: 999px; margin-top: 0.45rem; overflow: hidden; }
.cifra .pista-c i { display: block; height: 100%; background: var(--conferma); border-radius: 999px; }

/* ── la fascia dei fatti dell'esecuzione ──────────────────────────────────
   Chi ha risposto, con che sforzo, in quanti lotti, in quanto tempo, a che
   costo. Schede piatte su fondo chiaro, valore grande e etichetta piccola in
   tondo: niente maiuscole spaziate né monospazio, che sanno di terminale. Il
   costo è la cosa che si cerca per prima, e ha il colore d'accento. */
.fascia { display: flex; flex-wrap: wrap; align-items: stretch; margin: 0.1rem 0 0.8rem 0; }
.fascia div { display: flex; flex-direction: column; justify-content: center;
              background: var(--superficie); border: 1px solid var(--riga); border-radius: 10px;
              padding: 0.5rem 0.85rem; margin: 0 0.5rem 0.5rem 0; min-width: 6rem; }
.fascia .v { font-size: 1.02rem; font-weight: 600; color: var(--inchiostro); line-height: 1.25;
             letter-spacing: -0.005em; }
.fascia .v.spenta { color: var(--basso); font-weight: 500; }
.fascia .k { font-size: 0.72rem; color: var(--basso); margin-top: 0.12rem; order: 2; }
.fascia div.costo { background: var(--tinta); border-color: var(--bordo-campo); }
.fascia div.costo .v { color: var(--accento-cupo); }
.fascia .avviso { align-self: center; font-size: 0.76rem; font-weight: 600; color: var(--alto);
                  border: 1px solid var(--alto); border-radius: 999px; padding: 0.15rem 0.65rem;
                  margin: 0 0.5rem 0.5rem 0; }
/* la legenda delle tabelle: una riga sola sopra le schede, non nascosta in una */
.legenda { display: flex; flex-wrap: wrap; align-items: center;
           font-size: 0.78rem; color: var(--inchiostro-2); margin: 0.2rem 0 0.35rem 0; }
.legenda .marca { font-size: 0.74rem; margin: 0 0.3rem 0.25rem 0; }
.legenda span:last-child { margin-left: 0.4rem; }

/* ── intestazione di sezione ──────────────────────────────────────────── */
.sezione { display: flex; align-items: baseline; gap: 0.6rem; flex-wrap: wrap;
           margin: 0.2rem 0 0.15rem 0; }
.sezione .nome { font-size: 1.08rem; font-weight: 600; }
.sezione .conto { font-family: 'IBM Plex Mono', monospace; font-size: 0.82rem;
                  color: var(--inchiostro-2); margin-left: 0.45rem; }
.spiega { color: var(--inchiostro-2); font-size: 0.86rem; margin: 0 0 0.5rem 0;
          max-width: 76ch; }

/* barra di validazione: la quota confermata, non una decorazione */
.avanza { height: 6px; background: var(--riga); border-radius: 999px; overflow: hidden;
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
  border: 1px solid var(--bordo-campo); background: var(--superficie); color: var(--inchiostro);
}
div.stButton > button:hover, div.stDownloadButton > button:hover {
  border-color: var(--accento); color: var(--accento-cupo); }
div.stButton > button[kind="primary"] {
  background: var(--accento); border-color: var(--accento); color: #fff; }
div.stButton > button[kind="primary"]:hover {
  background: var(--accento-cupo); border-color: var(--accento-cupo); color: #fff; }

/* ── I CAMPI IN CUI SI SCRIVE ──────────────────────────────────────────
   Un bordo che si vede, un fondo bianco, e l'accento quando ci passi sopra o
   ci entri col tasto tab. Di serie i campi di Streamlit hanno un bordo
   quasi invisibile e lo stesso fondo del contenitore: nella barra laterale
   bianca sparivano del tutto, e non si capiva dove andasse scritto. */
[data-testid="stSidebar"] [data-baseweb="input"],
[data-testid="stSidebar"] [data-baseweb="textarea"],
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {
  background: var(--superficie) !important;
  border: 1px solid var(--bordo-campo) !important;
  border-radius: var(--r) !important;
  transition: border-color .12s ease;
}
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea { background: transparent !important; }
[data-baseweb="input"]:hover, [data-baseweb="textarea"]:hover,
[data-baseweb="select"] > div:hover { border-color: var(--accento) !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="select"]:focus-within,
[data-baseweb="textarea"]:focus-within { border-color: var(--accento) !important;
                                         box-shadow: 0 0 0 1px var(--accento) !important; }
/* l'area di caricamento: lo stesso trattamento, così si vede che è un bersaglio */
[data-testid="stFileUploaderDropzone"] { border: 1px dashed var(--bordo-campo) !important;
                                         background: var(--superficie) !important;
                                         border-radius: var(--r) !important; }
[data-testid="stFileUploaderDropzone"]:hover { border-color: var(--accento) !important; }
/* i pannelli richiudibili nella barra laterale: bianchi come i campi */
[data-testid="stSidebar"] [data-testid="stExpander"] { background: var(--superficie); }

/* ── RIQUADRI DI PARI ALTEZZA ──────────────────────────────────────────
   Una riga di colonne che contiene un titolo `.pari-titolo` allunga i suoi
   riquadri all'altezza del più alto. Senza, ognuno è alto quanto il suo
   contenuto: una descrizione su una riga invece che su due, o un bottone di
   download in più, e i riquadri vengono di tre misure diverse.
   Nomi dei contenitori verificati sul pacchetto di Streamlit 1.64
   (`stHorizontalBlock` → `stColumn` → `stLayoutWrapper` / `stVerticalBlock`);
   `:has()` limita la regola alle sole righe marcate, il resto non cambia. */
[data-testid="stHorizontalBlock"]:has(.pari-titolo) { align-items: stretch !important; }
[data-testid="stHorizontalBlock"]:has(.pari-titolo) > [data-testid="stColumn"] > [data-testid="stVerticalBlock"],
[data-testid="stHorizontalBlock"]:has(.pari-titolo) > [data-testid="stColumn"] [data-testid="stLayoutWrapper"],
[data-testid="stHorizontalBlock"]:has(.pari-titolo) > [data-testid="stColumn"] [data-testid="stVerticalBlock"] {
  height: 100%; }
.pari-titolo { font-weight: 600; margin: 0; color: var(--inchiostro); }
/* La descrizione occupa sempre due righe, anche quando ne basta una: così i
   bottoni cominciano alla stessa altezza in tutti i riquadri, qualunque cosa
   facciano i contenitori di Streamlit. */
.pari-testo { color: var(--inchiostro-2); font-size: 0.875rem; line-height: 1.45;
              min-height: 2.9em; margin: 0; }

/* ── I LOTTI IN PARALLELO ──────────────────────────────────────────────
   Una riga per lotto; a destra una striscia sul tempo comune dell'analisi:
   due barre sovrapposte sono due lotti che lavorano insieme. Lo stato è
   sempre simbolo + parola, mai solo colore. */
.lotti-capo { font-size: 0.82rem; color: var(--inchiostro-2); margin: 0 0 0.45rem; }
.lotti-t { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.lotti-t th { text-align: left; font-weight: 600; color: var(--basso); padding: 0.2rem 0.5rem 0.3rem 0;
              border-bottom: 1px solid var(--riga); white-space: nowrap; }
.lotti-t td { padding: 0.32rem 0.5rem 0.32rem 0; border-bottom: 1px solid #EAF0F2;
              vertical-align: middle; white-space: nowrap; }
.lotti-t td.num { font-family: 'IBM Plex Mono', monospace; color: var(--basso); width: 1.6rem; }
.lotti-t td.file { max-width: 16rem; overflow: hidden; text-overflow: ellipsis; }
.lotti-t td.cifra-l { font-family: 'IBM Plex Mono', monospace; text-align: right; }
.lotti-t td.pista-l { width: 34%; min-width: 9rem; }
.lotti-t .atteso { color: var(--basso); font-weight: 400; }
.pista-lotto { position: relative; height: 8px; background: var(--riga); border-radius: 999px; }
.pista-lotto i { position: absolute; top: 0; height: 100%; border-radius: 999px; min-width: 3px; }
.st-coda  { color: var(--basso); }       .pista-lotto i.st-coda  { background: transparent; }
.st-cache { color: var(--basso); }       .pista-lotto i.st-cache { background: var(--bordo-campo); }
.st-corso { color: var(--accento); }     .pista-lotto i.st-corso { background: var(--accento); }
.st-continua, .st-incompleto { color: var(--alto); }
.pista-lotto i.st-continua, .pista-lotto i.st-incompleto { background: var(--alto); }
.st-fatto { color: var(--conferma); }    .pista-lotto i.st-fatto { background: var(--conferma); }
.st-errore { color: var(--critico); }    .pista-lotto i.st-errore { background: var(--critico); }
.st-fermato { color: var(--basso); }     .pista-lotto i.st-fermato { background: var(--bordo-campo); }
/* Il pallino di chi sta lavorando pulsa piano — se la persona non ha chiesto
   di ridurre le animazioni. */
@keyframes pulsa { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
.lotti-t .st-corso .seg { animation: pulsa 1.4s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) { .lotti-t .st-corso .seg { animation: none; } }

/* il fuoco da tastiera si vede sempre, su tutto */
:where(button, input, select, textarea, a, [role="tab"], [role="checkbox"]):focus-visible {
  outline: 3px solid var(--accento); outline-offset: 2px; border-radius: 3px; }

/* ── barra laterale ───────────────────────────────────────────────────── */
/* Dorata, non bianca: i campi di inserimento sono bianchi, e su bianco
   sparivano. Il fondo Golden `#BFAF8F` li stacca e separa a colpo d'occhio
   i comandi dai risultati, che stanno sul blu e sull'azzurro. Il blu sul
   dorato è 7,7:1; il grigio che Streamlit usa per le note e le icone d'aiuto
   sul dorato si leggerebbe male (3,4:1), quindi lì diventa blu pieno. */
[data-testid="stSidebar"] { background: var(--sfondo-lato); border-right: 1px solid var(--oro); }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: var(--inchiostro) !important; }
[data-testid="stSidebar"] [data-testid="stTooltipIcon"],
[data-testid="stSidebar"] [data-testid="stTooltipIcon"] svg,
[data-testid="stSidebar"] [data-testid="stSidebarHeader"] button { color: var(--inchiostro) !important; }
[data-testid="stSidebar"] hr { border-color: var(--oro) !important; }
/* il logo in cima alla barra, separato dai comandi da una riga dorata scura */
.logo-barra { margin: -0.6rem 0 0.9rem 0; padding-bottom: 1rem;
              border-bottom: 1px solid var(--oro); }
.logo-barra svg { display: block; height: 62px; width: auto; max-width: 100%; }
[data-testid="stSidebar"] .block-container { padding-top: 1.2rem; }
.tappa { font-size: 0.72rem; font-weight: 600; color: var(--inchiostro);
         letter-spacing: 0.02em; margin: 1.1rem 0 0.15rem 0;
         display: flex; align-items: center; gap: 0.4rem; }
.tappa span { font-family: 'IBM Plex Mono', monospace; background: var(--oro-scuro); color: #FFFFFF;
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

/* ═══ I CONTROLLI DI STREAMLIT ══════════════════════════════════════════
   Cursori, caselle, interruttori e bordi di fuoco prendono il colore dal tema
   di Streamlit, che è una configurazione esterna al codice. Qui gli stessi
   colori vengono riapplicati via CSS, che viaggia dentro `ui.py`: comunque si
   avvii l'applicazione — con `avvia.py` o con `streamlit run app.py` a mano —
   l'accento è il nostro e non il rosso di serie, che litigherebbe con la scala
   di gravità. */
[data-testid="stSlider"] [data-baseweb="slider"] div[role="slider"] { background: var(--accento) !important; }
[data-testid="stSlider"] [data-baseweb="slider"] > div > div > div:first-child { background: var(--accento) !important; }
[data-testid="stCheckbox"] [data-baseweb="checkbox"] span[aria-hidden="true"],
[data-baseweb="checkbox"] span[data-checked="true"] { background-color: var(--accento) !important;
                                                      border-color: var(--accento) !important; }
[data-baseweb="radio"] div[aria-checked="true"] { background-color: var(--accento) !important;
                                                  border-color: var(--accento) !important; }
[data-testid="stToggle"] [aria-checked="true"] { background: var(--accento) !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="select"]:focus-within,
[data-baseweb="textarea"]:focus-within { border-color: var(--accento) !important;
                                         box-shadow: 0 0 0 1px var(--accento) !important; }
[data-testid="stSpinner"] i { border-top-color: var(--accento) !important; }

/* ── rispetto delle preferenze di sistema ─────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important;
                           scroll-behavior: auto !important; }
}
@media (prefers-contrast: more) {
  :root { --riga: #7B8A9C; --bordo-campo: #4B5868; --inchiostro-2: #2F3B49; }
  .marca { border-width: 2px; }
}
@media (max-width: 880px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; }
  .cifra { flex-basis: 45%; }
}
</style>
"""


# ═══ IL TEMA DI STREAMLIT, IMPOSTATO DA CODICE ══════════════════════════════
# Gli stessi colori dei token CSS qui sopra, ma per i controlli che Streamlit
# disegna da sé (cursori, radio, caselle, anelli di fuoco): quelli prendono il
# colore dal tema, non dal nostro CSS.
#
# Il tema, di norma, sta in `.streamlit/config.toml`. Quella cartella comincia
# col punto: il gestore file non la mostra e il caricamento su GitHub la
# salta, e infatti si è persa. Le opzioni di riga di comando valgono solo se si
# parte da `avvia.py`, e su Streamlit Cloud l'app la lancia la piattaforma.
# Quindi si imposta QUI, da codice, con l'API interna di configurazione: il
# messaggio di sessione che porta il tema al browser viene costruito a ogni
# riesecuzione, e legge la configurazione in quel momento. La prima esecuzione
# di una sessione parte col tema di serie; si fa ripartire una volta, e dalla
# seconda in poi il tema è il nostro. Nessun file, nessuna cartella.
TEMA_STREAMLIT = {
    "theme.base": "light",
    "theme.primaryColor": "#011E41",
    "theme.backgroundColor": "#F1F5F6",
    "theme.secondaryBackgroundColor": "#FFFFFF",
    "theme.textColor": "#011E41",
    "server.maxUploadSize": 50,
    "client.toolbarMode": "minimal",
}


def imposta_tema_streamlit() -> None:
    """Imposta il tema da codice e fa ripartire la prima esecuzione della
    sessione, così il browser lo riceve subito. Se l'API interna non c'è o
    cambia, non succede niente: restano i colori del CSS."""
    try:
        import streamlit.config as configurazione
        cambiato = False
        for chiave, valore in TEMA_STREAMLIT.items():
            if configurazione.get_option(chiave) != valore:
                configurazione.set_option(chiave, valore)
                cambiato = True
        # Una sola ripartenza per sessione: alla seconda esecuzione get_option
        # restituisce già il nostro valore e `cambiato` resta falso.
        if cambiato and not st.session_state.get("_tema_applicato"):
            st.session_state["_tema_applicato"] = True
            st.rerun()
    except Exception:
        pass


def applica_tema() -> None:
    st.markdown(TEMA, unsafe_allow_html=True)


def tema_configurato() -> bool:
    """Dice se le impostazioni di Streamlit sono quelle nostre.

    Le passa `avvia.py` come variabili d'ambiente. Non servono all'aspetto —
    quello lo tiene su il CSS qui sopra — ma portano il limite di caricamento e
    la barra degli strumenti ridotta, e sapere se mancano evita mezz'ora di
    dubbi a chi lancia `streamlit run app.py` a mano."""
    try:
        return str(st.get_option("theme.primaryColor") or "").lower() == "#011e41"
    except Exception:
        return False


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
def _con_iniziali_in_evidenza(titolo: str) -> str:
    """Il titolo con la sigla in evidenza.

    Nella forma «LAKE: Legacy Application Knowledge Extractor» la sigla sta
    davanti per esteso e il nome la spiega: si colora la sigla, e le iniziali
    delle parole che la compongono, così il legame fra le due si vede senza
    doverlo dire. Senza i due punti si colorano le sole iniziali.

    Non è legata a queste parole in particolare: cambiando il nome, cambia da
    sé quello che viene evidenziato."""
    prefisso = ""
    if ": " in titolo:
        sigla, titolo = titolo.split(": ", 1)
        prefisso = f'<span class="sigla">{_e(sigla)}</span>{_e(":")} '
    parole = titolo.split(" ")
    pezzi = [f'<span class="sigla">{_e(p[0])}</span>{_e(p[1:])}' if p else ""
             for p in parole]
    return prefisso + " ".join(pezzi)


# ═══ IL MARCHIO ═════════════════════════════════════════════════════════════
# Il logo Electrolux Professional Group — il simbolo nel quadrato e la scritta
# su tre righe — ridisegnato come tracciato vettoriale, in mezzi pixel
# (riquadro LOGO_LARGHEZZA × LOGO_ALTEZZA) e con coordinate relative, così
# pesa poco. Il quadrato ha il simbolo «bucato» dentro (regola evenodd): in
# blu su chiaro è il logo com'è, in bianco su blu è la sua versione negativa.
# Sta qui dentro per la stessa ragione del banner: un file accanto si perde,
# un modulo Python no. Lo usano la barra laterale e l'icona della scheda
# del browser.
LOGO_LARGHEZZA, LOGO_ALTEZZA = 1519, 560
LOGO_TRACCIATO = "M1018 560c0-1 1-5 1-21-1-11 0-21 0-21 0 0 2 2 3 4 3 3 8 6 9 6 1 0 2 0 2 1 1 1 3 1 9 1 10 0 11 0 20-4 4-2 7-5 11-9 3-3 7-10 7-11 0-1 0-2 1-3 0-2 1-4 2-7 2-10-1-25-7-34-2-3-8-9-10-10-5-4-13-7-19-7-3-1-13 1-15 2-1 0-3 1-4 1 0 0-3 2-5 4-2 2-4 4-4 4 0 0-1-2-1-5l0-4-9 0-9 0 0 56c0 45 0 56 1 57 0 0 16 0 17 0zM862 529c6-2 9-4 14-8 4-3 8-7 10-11 1-2 4-8 4-8 0-1 0-2 1-4 1-2 1-4 1-10 0-4 0-8 0-9-2-5-3-7-3-9-1-1-1-2-1-2-2-4-6-9-10-13-2-2-4-3-6-5-1 0-2-1-2-1-1-1-2-1-3-1 0 0-1 0-2-1-1-1-3-1-3-1-1 0-3 0-4-1-3-1-5-1-8-1-4 0-6 0-9 1-1 1-3 1-4 1 0 0-2 0-3 1-1 1-2 1-2 1-2 0-10 5-14 9-4 5-9 13-10 18 0 1-1 3-1 4-1 5 0 19 2 24 4 8 6 12 11 16 2 2 7 5 9 7 1 0 5 2 5 2 1 0 2 0 3 1 4 2 19 2 25 0zM956 529c8-2 10-4 15-9 2-2 5-5 5-6 0 0 0-1 1-2 0 0 1-1 1-2 0-1 1-3 1-4 1-2 1-5 1-30 1-25 0-28 0-29-1 0-3 0-9 0l-9 0 0 26c0 24 0 26-1 29-2 5-6 9-11 10-2 1-9 1-12 0-3-1-7-4-9-8l-1-2 0-27c-1-15-1-28-1-28 0 0-3-1-10-1l-8 0-1 2c0 0 0 13 0 28 0 25 0 28 1 30 2 5 4 10 7 13 2 3 7 7 8 7 1 0 2 0 3 1 1 1 2 1 2 1 1 0 2 0 3 1 2 1 5 1 13 1 5 0 8 0 11-1zM697 529c4-1 10-3 12-4 1-1 2-1 3-1 0 0 1-1 3-2 1-1 3-2 3-2 1 0 4-3 7-6l6-5 0-23c0-21-1-22-1-22-2-1-47-1-47 0-1 1-1 16 0 16 0 1 4 1 14 1 9 0 14 0 15 0 0 1 0 5 0 11l0 10-2 2c-2 2-4 2-6 4-1 0-3 1-3 1 0 0-2 1-4 1-1 1-4 1-6 1-5 2-14 1-20-2-1-1-2-1-3-1 0 0-2-2-6-4-1-1-3-2-4-4-2-2-6-8-6-8 0-1 0-1-1-2 0-1-1-3-2-5-1-4-1-5-1-14 0-11 0-11 4-20 2-3 3-5 7-9 4-4 9-8 11-8 1 0 2 0 4-1 7-2 11-2 18-1 4 0 9 1 10 3 1 0 2 0 3 1 2 1 4 2 6 4 1 1 2 1 2 1 1 1 13-10 13-11 0-1-3-4-10-8-3-2-10-6-14-7-5-1-5-1-16-1-11 0-12 0-15 1-2 1-3 1-4 1 0 0-1 0-2 1-1 0-3 1-3 1-1 1-2 1-2 1-1 1-2 1-2 1-4 2-6 3-10 7-4 4-10 10-12 13-4 9-6 12-8 20 0 3 0 22 1 25 1 1 1 3 1 3 0 1 0 2 1 3 1 1 1 2 1 3 0 0 2 5 4 7 1 2 3 5 3 5 0 1 1 1 1 2 2 3 8 9 12 11 5 3 12 7 13 7 0 0 1 0 2 1 1 1 8 2 13 3 4 0 12 0 17-1zM768 528c1-1 1-2 1-23 0-25 0-26 2-31 2-3 7-8 10-9 3-1 5-1 10-1 4 0 7-1 7-1 0 0 0-4 0-9l0-8-2-1c-1 0-2 0-5 0-2 1-4 1-5 1-3 0-12 5-14 8 0 1-2 3-3 3 0 0 0-2 0-4 0-7 1-7-10-6l-8 0 0 40c0 30 0 41 0 41 0 1 2 1 8 1 7 0 8 0 9-1zM506 528c0-1 1-118 1-262l0-261-2-1c-1-1-503-1-504 0-1 1-1 4-1 262 0 144 0 261 0 262 1 0 506 0 506 0zM844 512c-5-1-9-3-12-6-4-5-6-8-6-14-1-6-1-12 2-17 2-3 6-8 8-9 1 0 2-1 2-1 2-2 7-3 11-3 7 0 12 2 17 7 5 5 8 12 8 19 0 9-6 19-13 22-4 2-10 3-12 3-1 0-3 0-5-1zM1034 512c-2-1-5-2-7-4-3-2-7-7-7-8 0 0 0-1-1-2-1-2-2-7-2-11 0-6 1-9 5-15 1-2 5-6 6-6 0 0 1 0 1-1 5-3 14-4 19-2 7 2 11 6 14 12 2 4 3 9 2 15 0 8-3 13-9 18-5 4-6 4-13 4-3 0-7 0-8 0zM234 499c-6 0-10 0-14-2-1 0-4-1-6-1-2 0-5 0-7-1-2 0-5-1-8-2-3-1-7-1-9-2-1-1-3-1-4-1 0 0-2-1-3-1-2-1-5-2-6-3-7-3-7-3-18-8-3-1-5-2-6-2 0 0-1 0-1-1-1-1-2-1-2-1-1 0-7-3-10-6-2-1-4-2-5-3-6-4-9-6-13-9-2-1-4-3-7-5-5-4-17-15-25-24-7-7-9-10-14-16-1-1-3-3-4-5-2-2-3-4-4-5 0-1-1-3-2-4-1-1-2-3-2-3 0 0-1-2-3-4-1-3-4-7-5-10-2-3-3-6-4-6 0 0 0 0 0-1 0 0-1-2-2-4-1-2-2-4-2-4 0-1-1-4-3-7-1-3-2-6-3-8 0-1-1-3-1-3-1-1-4-12-5-15 0-2-1-5-2-7-1-3-2-7-2-9 0-3-1-6-1-7-1-3-2-13-3-23 0-6 0-6 1-7 1-1 3-1 32 0 32 0 38 0 43 2 2 0 6 1 9 1 3 0 6 1 7 1 3 1 10 3 16 5 2 0 5 1 7 2 2 1 5 2 6 2 1 0 2 1 3 1 0 0 1 1 2 1 3 1 19 9 20 10 0 0 1 0 1 0 1 0 3 1 4 2 2 1 3 2 4 2 0 0 1 1 3 2 1 1 4 2 5 3 3 1 7 4 20 12 2 2 5 5 7 6 2 2 5 4 7 6 4 4 20 20 24 25 8 9 13 15 13 16 1 1 2 3 3 4 4 7 6 10 7 12 4 7 9 16 9 17 1 0 1 1 1 1 0 1 0 2 1 3 4 8 9 22 9 24 0 1 1 3 1 5 2 6 3 9 3 10 0 0 0 3 1 5 1 6 3 18 4 27 0 6 0 7-1 8 0 1-1 2-2 2-1 0-3 0-4 1-10 2-14 3-35 3-11 0-22 0-25-1zM326 487l-1-1 0-219c0-120 0-219 0-220 0-2 4-2 9 0 1 1 3 2 5 2 2 1 4 2 5 2 1 1 2 1 4 2 7 3 13 6 14 7 1 1 3 2 4 3 8 4 31 21 38 28 10 10 22 23 26 29 2 2 3 3 3 4 2 2 5 6 5 7 0 0 0 1 1 1 1 2 5 8 7 11 1 2 2 4 3 6 1 2 2 4 3 6 1 1 2 3 2 3 0 0 0 1 1 2 1 3 5 10 6 12 0 2 1 4 2 6 1 4 1 5 5 14 1 4 2 7 2 8 0 0 1 3 2 6 0 2 1 6 2 8 0 2 1 5 1 7 1 2 1 6 1 9 1 3 1 8 2 11 1 11 2 17 2 29 0 10-1 14-2 21 0 5-1 11-2 14 0 3 0 6-1 8 0 2-1 5-1 7 0 1-1 4-2 6-1 3-1 6-2 7 0 3-2 8-4 13 0 2-1 5-2 6 0 1-1 4-2 6-1 2-2 4-2 4 0 0-1 2-1 4-1 1-3 5-4 7-1 2-2 4-2 5-1 0-2 1-2 3-4 6-5 9-8 13-1 2-3 5-4 6-1 2-8 12-10 14-9 11-25 28-32 33-4 4-6 6-10 9-1 1-2 2-3 2-2 1-3 2-6 4-1 1-3 2-5 3-1 1-3 2-3 2-3 2-31 17-32 17-1 0-2 0-3 1 0 0-2 1-3 1-2 1-3 1-4 1 0 0-1 0-2 0zM834 322c3 0 7-1 8-1 0-1 1-1 2-1 1 0 5-2 7-4 1-1 3-2 3-3 3-1 7-5 9-9 2-3 3-5 3-5 0 0 0-1 1-2 1-1 1-3 1-3 0 0 0-2 1-4 1-2 1-4 1-10 0-6-1-9-1-11-4-12-9-19-18-25-3-2-6-4-7-4 0 0-2 0-3-1-1-1-2-1-3-1-1 0-3 0-4-1-5-1-18 0-21 2-1 1-2 1-2 1-2 0-10 5-13 8-4 3-8 9-10 12 0 1-1 3-1 4-1 1-1 2-1 3 0 0 0 2-1 3-1 5 0 22 2 25 0 0 1 1 1 2 1 2 1 4 4 7 2 5 12 13 16 15 6 2 7 3 12 4 7 1 7 1 14-1zM1054 323c7-1 9-1 11-2 1-1 2-1 4-2 3-2 7-6 9-9 1-2 2-5 3-7 1-5 1-5 0-9-1-3-2-6-2-7-2-3-6-7-9-9-5-3-12-6-14-6 0 0-1 0-2-1-1-1-3-1-3-1-1 0-3-1-5-2-4-2-6-4-6-7 0-2 2-5 4-6 1-1 2-1 6-1 6 0 9 1 13 4l2 2 5-6c3-2 5-5 5-5 0-3-12-11-15-11 0 0-2 0-3-1-3-1-8-1-12 0-2 1-4 1-5 1-1 0-4 2-7 4-4 2-9 8-9 10 0 0 0 2-1 3-1 3-1 9 1 13 2 7 5 10 12 14 4 2 5 2 6 2 1 0 9 3 13 5 1 1 3 1 3 1 1 0 4 3 4 4 3 4 2 7-3 10-2 1-3 2-6 2-7 1-13 0-17-3-4-3-5-4-6-5-1-2-2-1-6 2-6 6-8 7-7 8 2 3 4 6 6 7 2 2 4 3 9 6 1 0 3 1 6 1 5 1 11 2 16 1zM1128 323c7-1 10-1 11-2 1-1 2-1 4-2 3-2 7-6 9-9 1-2 2-5 3-7 1-5 1-5 0-9-1-3-2-6-2-7-2-3-6-7-9-9-5-3-12-6-14-6 0 0-1 0-2-1-1-1-3-1-3-1-1 0-3-1-5-2-3-1-4-2-5-4 0-1-1-2-1-3 0-2 2-5 4-6 1-1 2-1 6-1 6 0 9 1 13 4l2 2 5-6c3-2 5-5 5-5 0-3-12-11-15-11 0 0-2 0-3-1-3-1-8-1-12 0-2 1-4 1-5 1-2 0-8 4-11 7-5 5-6 8-6 15-1 9 3 16 10 20 4 2 8 4 9 4 1 0 9 3 13 5 1 1 3 1 3 1 1 0 4 3 5 5 1 3 1 3 0 5-1 3-6 6-10 6-7 1-13 0-17-3-4-3-5-4-6-5-1-2-2-1-6 2-6 6-8 7-7 8 2 3 4 6 6 7 2 2 4 3 9 6 1 0 3 1 6 1 5 1 11 2 16 1zM1254 323c11-2 17-5 26-13 3-3 10-15 10-17 0-1 0-2 1-4 1-3 1-12 0-18-2-7-5-14-9-19-4-5-14-12-17-12 0 0-1 0-2-1 0 0-2-1-4-1-1 0-3-1-4-1-2-1-10-1-13 0-2 1-4 1-5 1-5 2-9 4-12 6-2 2-3 2-3 2-1 0-2 2-4 3-4 5-8 11-10 19-2 3-2 4-2 12 0 8 1 12 5 20 0 1 2 5 5 8 3 4 14 12 16 12 1 0 2 0 3 1 1 0 10 2 13 2 1 0 4 0 6 0zM1443 322c8-1 15-5 17-9 1-3 3-2 2 3 0 6 0 6 9 6 5 0 9-1 9-1 1 0 1-4 1-41 0-39 0-40-1-40-1-1-4-1-9-1-9 0-9 0-9 5 1 4-1 7-2 4 0-1-1-2-2-3-1-2-6-5-7-5 0 0-1 0-3-1-1-1-4-1-8-1-5-1-6-1-10 0-6 1-11 3-15 6-6 4-14 14-15 20 0 1-1 3-1 4-1 2-1 4-1 11 0 5 0 10 0 11 2 6 3 8 4 11 3 5 9 12 14 15 1 1 3 3 4 3 0 1 1 1 2 1 0 0 1 0 3 1 3 1 10 2 12 2 0 0 3 0 6-1zM977 322c5 0 6-1 11-3 6-3 14-9 13-10 0-1-10-11-10-11-1 0-2 1-3 2-2 2-3 2-8 5-3 1-3 1-10 1-7 0-8 0-10-1-6-2-10-6-13-11-1-3-2-7-1-8 0-1 6-1 30-1 24 0 29 0 30-1 2-1 2-4 1-11-1-7-3-12-5-15 0-2-1-3-2-4-1-3-3-5-7-8-4-4-9-7-17-9-3-1-11-1-15 0-1 1-3 1-4 1-1 0-3 0-4 1 0 0-2 1-3 1-3 1-10 7-15 13-5 7-9 19-8 28 0 5 1 13 2 14 1 1 1 2 1 2 0 2 4 9 8 13 2 3 9 8 10 8 1 0 2 0 2 1 4 2 8 3 14 3 7 1 8 1 13 0zM653 321c0-1 1-6 1-20 0-13 0-18 0-19 1 0 4-1 11-1 10 0 12 0 17-1 5-1 9-2 10-3 0-1 1-1 1-1 1 0 5-3 7-5 3-3 6-7 6-8 0 0 0-1 1-1 1-1 3-7 4-13 0-4 0-5-1-10 0-6-2-10-3-12 0-1-1-2-1-3-1-1-6-6-9-9-4-3-6-4-11-6-4-1-4-1-27-1-13 0-24 0-24 0-1 0-1 12-1 56 0 31 0 57 0 57 1 1 18 1 19 0zM747 298c0-26 0-27 3-32 1-3 6-7 10-9 2-1 4-1 9-1l7 0 0-9 0-9-7 0c-5 0-7 0-9 1-3 2-6 4-8 6-4 4-5 5-5 5 0 0-1-3-1-5 0-4 0-5 0-5-2-1-16-1-17-1-1 1-1 6-1 40 0 26 0 40 0 41l1 2 9-1 8 0 1-23zM903 321c0-1 1-12 1-32 0-23 0-32 0-32 0 0 3 0 7 0 5 0 6 0 6-1 1 0 1-3 1-9l0-8-7-1c-4 0-7 0-7 0-1-1-1-9 0-11 0-1 2-3 3-4 1-1 2-1 7-1l6-1 0-7c1-7 0-8 0-8-2-1-10-1-15 0-11 2-17 7-20 17 0 4-1 6-1 50 1 31 1 47 1 48 0 0 1 1 9 1 8 0 9-1 9-1zM1189 321c1-1 1-15 1-41 0-26 0-39-1-40 0-1-1-1-8-1-6 0-9 0-9 1-1 0-1 3-1 40 0 32 0 41 1 41 0 0 4 0 9 0 7 0 8 0 8 0zM1327 321c0-1 0-9 1-27l0-26 1-3c4-7 12-11 20-10 6 2 9 4 12 9l1 3 0 27c1 21 1 27 1 27 1 0 4 0 10 0l8 0 0-28c0-26 0-29-1-33-1-6-4-10-7-14-3-3-8-6-9-6-1 0-2 0-3-1-2-1-3-1-10-1-8 0-11 1-13 3-1 1-2 1-2 1-1 0-6 4-6 6-1 0-1 1-2 0 0 0 0-1 0-4 0-3-1-4-1-4-2-1-16-1-17 0-1 0-1 1-1 40 0 31 0 40 1 41 0 1 16 1 17 0zM1519 265c0-32 0-56 0-57-1 0-18 0-18 1-1 0-1 112 0 112 0 0 4 0 9 0l9 0 0-56zM822 305c-7-2-10-4-13-8-3-3-4-6-5-10-2-8 0-17 4-22 5-7 12-11 20-11 3 0 7 1 9 3 0 0 1 0 2 1 3 1 9 7 10 10 3 6 4 15 2 20-4 10-8 14-18 17-5 1-7 1-11 0zM1243 305c-7-2-9-4-13-8-6-8-7-20-3-29 2-4 5-7 8-9 9-6 17-6 26-1 3 1 8 7 10 10 1 4 3 10 2 13 0 2-1 9-2 11-4 7-8 10-17 13-4 1-7 1-11 0zM1432 304c-2 0-3-1-3-1-1-1-2-1-2-1-1 0-7-7-8-9 0-1-1-3-2-5-2-6-1-17 2-22 0 0 1-2 2-3 5-7 16-10 24-8 8 3 12 6 15 12 1 0 1 1 1 2 2 2 3 7 3 11 0 7-2 12-6 17-3 3-8 6-12 7-3 1-12 1-14 0zM946 271c0 0 0-1 0-2 0-3 6-11 10-12 5-3 6-3 12-3 5 0 8 0 11 3 0 0 1 0 2 1 2 1 7 9 7 11 0 2 0 2-21 2-12 0-20 0-21 0zM654 263c-1-1-1-1-1-18 0-14 0-18 1-19 0-1 2-1 13 0l13 0 2 1c11 6 13 21 5 30-3 3-6 5-10 5-4 1-21 1-23 1zM29 254c-2-1-2-2-2-6 1-1 1-5 1-9 1-7 2-13 3-17 1-2 1-4 1-5 0-1 2-10 3-12 0 0 1-2 1-3 0-1 1-3 1-4 1-2 1-4 2-6 0-1 1-3 2-5 0-2 1-3 1-4 2-5 8-18 11-24 0-1 2-3 3-6 2-4 4-8 9-15 1-2 2-4 3-5 1-3 14-19 18-23 13-15 25-26 38-35 2-2 5-4 7-5 1-1 2-2 2-2 1 0 7-4 8-5 1-1 2-1 2-1 0 0 1-1 3-2 2-1 16-8 16-8 0 0 2-1 5-2 2-1 4-2 5-2 0 0 1 0 2-1 1 0 3-1 5-2 1-1 3-1 4-2 2-1 5-2 13-4 11-2 12-3 15-3 2 0 7-1 12-2l8-2 22 0c23 0 24 0 37 3 3 1 6 1 7 1 2 0 2 1 3 2 1 2 1 2 1 8 0 4-1 9-1 11-1 3-1 7-1 9-2 9-3 16-6 24 0 2-1 4-1 5 0 1-4 11-5 14-1 1-1 2-1 2 0 0-1 3-2 5-1 3-2 6-3 6 0 1-1 3-2 5-1 2-2 4-3 5-2 5-7 12-12 20-2 2-3 4-4 5 0 1-1 2-2 4-2 2-7 8-9 11-4 4-20 21-25 24-1 1-3 3-6 5-6 5-7 6-14 11-2 1-4 3-5 4-2 1-3 2-4 2-1 1-2 1-2 1-2 2-7 5-10 6-8 4-31 15-33 15 0 0-1 0-2 1-2 1-7 3-8 3 0 0-1 0-2 1-1 0-2 1-3 1-2 0-6 1-10 2-4 1-9 2-11 2-2 0-5 1-6 1-8 2-30 3-56 3-18 0-22 0-23 0zM1184 228c6-2 8-8 6-14-1-3-2-5-5-6-4-3-9-2-13 3-3 3-4 6-2 11 1 5 8 8 14 6zM897 116c4-1 10-2 11-3 0 0 2-1 2-1 2-1 3-1 6-3 3-2 8-7 7-7 0-2-10-12-11-12 0 0-1 1-2 2-4 4-10 6-18 6-5 0-6 0-12-3-2-1-8-7-8-8 0 0 0-1-1-1-2-3-3-8-3-14 0-6 1-10 3-14 2-2 6-7 9-8 1-1 2-1 2-1 2-2 7-3 11-3 3 0 7 1 10 3 3 1 5 3 7 4 2 2 3 2 4 0 1-1 4-3 6-6l4-4-3-3c-4-3-7-6-11-7-1-1-4-1-4-2-3-1-7-1-12-2-5 0-14 1-20 4-1 1-2 1-2 1-2 1-3 2-6 4-7 6-12 13-15 22-1 4-1 5-1 13 0 7 0 9 1 12 1 3 3 7 4 9 0 1 2 2 3 4 2 4 9 11 13 12 7 3 8 4 9 4 1 0 3 0 4 1 3 1 8 1 13 1zM1098 115c2-1 5-2 6-2 1-1 2-1 3-1 2-1 11-8 14-11 2-2 7-10 7-11 0 0 0-2 1-3 1-1 1-2 1-3 0 0 0-2 1-3 1-4 1-11 0-17-1-3-2-6-2-7-1 0-1-1-1-2 0-1-1-3-4-7-2-3-8-9-13-13-5-3-16-6-22-6-7 0-19 3-23 6 0 1-1 2-2 2-3 2-7 5-9 8-2 3-7 12-7 13 0 0 0 2-1 4-1 2-1 4-1 10 0 4 0 8 0 9 2 6 3 8 3 9 1 0 1 1 1 1 0 1 1 2 2 4 1 2 2 3 2 3 0 1 5 6 7 8 3 2 9 6 10 6 0 0 1 0 2 1 2 1 6 2 11 3 4 0 8 0 14-1zM1228 115c1 0 3-1 5-1 2 0 4-1 4-1 1-1 2-1 2-1 1 0 6-3 9-6 3-2 6-7 6-8 0 0 0-1 1-1 0 0 1-1 1-2 0-1 0-3 1-3 0-1 0-2 1-3 0-2 0-56 0-57 0 0-4 0-9 0-7 0-9 0-9 1 0 0 0 11-1 25 0 30 0 30-4 35-4 4-7 5-13 5-4 0-5 0-7-1-3-2-6-4-8-7-2-3-2-7-2-33 0-15 0-25 0-25-1 0-15 0-18 0-1 0-1 6-1 29 0 27 0 29 1 31 1 1 1 2 1 3 0 1 4 7 6 10 3 3 9 7 10 7 1 0 2 0 2 1 1 0 6 2 10 3 3 0 10 0 12-1zM809 114c2 0 5-1 6-1 0-1 1-1 1-1 1 0 2-1 4-2 2-1 3-2 4-2 1-1 8-7 7-7 0-1-10-11-11-11 0 0-1 1-2 2-7 6-14 8-23 7-8-2-14-5-18-12-1-3-2-8-1-9 0 0 14 0 30 0 34-1 31 0 31-6 0-7-2-18-5-22-1-2-2-4-2-4-1-2-7-8-10-10-2-2-4-3-9-5-3-1-10-2-13-2-4 0-12 1-16 3-2 1-6 2-6 3 0 0-1 1-3 2-2 2-7 6-9 9-2 4-4 7-4 8 0 0 0 1-1 2-1 1-1 3-1 3 0 1 0 3-1 5 0 2-1 4 0 7 0 11 2 18 5 23 0 1 1 3 2 4 1 3 7 9 10 10 1 1 2 1 3 2 3 1 3 2 6 3 1 0 5 1 8 1 3 1 5 1 5 1 1 1 8 0 13-1zM974 114c0 0 0-1 0-9 0-6 0-8 0-8 0-1-2-1-3-1-5-1-9-4-12-9l-1-2 0-17c-1-13 0-17 0-18 0 0 2 0 8 0 7 0 8-1 8-1 1-2 1-16 0-17 0 0-3 0-7 0-5 0-8 0-8 0-1-1-1-2-1-16l0-15-2-1c-1 0-16 0-17 0 0 1-1 9-1 43 1 44 1 46 3 53 2 5 6 10 9 12 1 1 3 2 4 2 5 3 6 4 12 4 3 0 6 0 6 0 0 0 1 0 2 0zM702 105c0-5 0-8-1-9 0-1-1-1-18-1-12 0-19 0-20-1-2 0-3-1-6-3-4-5-5-7-5-18l0-9 22 0c13 0 23 0 23 0 1-1 1-14 1-18 0 0-10 0-22 0-20 0-23 0-23-1-1-1-1-25 0-26 1-1 3-1 24-1 12 0 23 0 23 0 0 0 0-4 0-9 0-7 0-8 0-9-1 0-65 0-66 0l-2 1 1 38c0 22 0 42 1 45 0 8 2 14 6 19 3 3 5 5 9 7 8 4 10 4 33 4l20 0 0-9zM739 114c0-1 1-26 1-57 0-45-1-56-1-57-1 0-16 0-17 1-1 0-1 1-1 56 0 53 0 56 1 56 1 1 17 1 17 1zM1008 90c0-24 0-25 1-28 3-7 7-11 14-13 3-1 10-1 13 0l1 0 0-9c1-9 1-9-1-10-1 0-8 0-13 1-5 2-10 6-13 10 0 1-1 1-2 1 0 0 0-2 0-5 0-3 0-5-1-5 0 0-16 0-17 0 0 0 0 81 0 82 0 0 4 0 9 0l9 0 0-24zM1167 113c0 0 0-1 0-56l0-56-1-1c-2 0-17 0-17 1-1 0-1 16-1 56 0 40 0 56 1 56 0 1 16 1 18 0zM1291 113c1 0 1 0 1 0 0-1 1-2 2-3 0-1 2-4 3-6 1-1 4-5 6-8 2-3 5-7 6-8 1-2 2-3 2-3 0 0 3 3 6 8 1 2 3 4 3 5 1 1 2 2 2 3 1 0 2 2 3 4 2 2 4 5 4 6 1 1 3 3 3 3 1 0 5 0 10 0 7 0 8 0 8-1 0 0 0-1 0-2-1-1-2-1-6-8-2-3-4-6-5-7-2-2-3-4-3-4 0-1-2-3-4-6-6-9-10-15-10-16 0 0 2-3 8-12 4-6 7-10 10-14 1-2 3-4 3-4 1-1 1-1 1-2 0 0 1-1 2-3 1-1 2-2 2-3-1 0-19 0-20 0-2 3-4 5-4 6 0 0-1 1-2 3-2 3-6 9-9 12-1 1-2 2-2 2 0 0-1-1-2-2-2-3-5-7-7-10-7-9-8-11-9-11 0 0-4 0-9 0-10 0-10 0-9 2 1 0 2 2 3 4 3 4 6 8 10 14 2 2 4 5 5 7 1 2 2 3 2 3 0 0 1 1 2 2 1 2 2 3 2 4 2 2 2 3 0 6-1 1-3 3-4 5-1 2-2 3-2 3 0 0-1 1-2 2-1 2-2 4-3 5-1 1-2 2-2 3-1 1-2 4-4 6-2 2-4 5-5 7-1 2-2 3-2 3-5 6-5 6 6 6 5 0 9 0 10-1zM1085 98c-3-1-7-2-8-3 0 0-1-1-1-1-2 0-7-6-9-9-4-8-4-17 0-25 4-6 10-11 18-13 9-1 17 2 23 10 1 1 2 3 2 3 0 0 0 1 1 2 0 1 1 3 2 6 0 4 0 5 0 9-2 8-6 15-12 18-5 3-11 4-16 3zM777 64c-2-1-1-4 1-7 3-6 6-8 12-10 7-2 15-1 20 3 3 2 8 9 8 12 0 2 0 2-21 2-11 0-20 0-20 0z"


def logo_svg(altezza: int = 48, colore: str = "#011E41") -> str:
    """Il logo come SVG autonomo, a fondo trasparente."""
    larghezza = round(altezza * LOGO_LARGHEZZA / LOGO_ALTEZZA)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {LOGO_LARGHEZZA} {LOGO_ALTEZZA}" '
            f'width="{larghezza}" height="{altezza}" role="img" '
            f'aria-label="Electrolux Professional Group">'
            f'<path fill="{colore}" fill-rule="evenodd" d="{LOGO_TRACCIATO}"/></svg>')


def _sottotracciati() -> List[List[tuple]]:
    """Il tracciato del logo come elenco di poligoni in coordinate assolute
    (le curve spezzate in 12 segmenti). Serve a Pillow, che le curve SVG
    non le sa leggere."""
    import re as _re
    pezzi = _re.findall(r"[MmLlCcZz]|-?\d+(?:\.\d+)?", LOGO_TRACCIATO)
    poligoni: List[List[tuple]] = []
    x = y = 0.0
    comando, i = "", 0
    while i < len(pezzi):
        if pezzi[i] in "MmLlCcZz":
            comando = pezzi[i]; i += 1
            if comando in "Zz":
                continue
        if comando == "M":
            x, y = float(pezzi[i]), float(pezzi[i + 1]); i += 2
            poligoni.append([(x, y)])
            comando = "l"
        elif comando == "l":
            x, y = x + float(pezzi[i]), y + float(pezzi[i + 1]); i += 2
            poligoni[-1].append((x, y))
        elif comando == "c":
            d = [float(n) for n in pezzi[i:i + 6]]; i += 6
            x1, y1, x2, y2, x3, y3 = x + d[0], y + d[1], x + d[2], y + d[3], x + d[4], y + d[5]
            for k in range(1, 13):
                t = k / 12; u = 1 - t
                poligoni[-1].append((u**3 * x + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                                     u**3 * y + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3))
            x, y = x3, y3
        else:
            i += 1
    return poligoni


def icona_pagina(riserva: str = "\U0001F9ED"):
    """L'icona della scheda del browser: il solo quadrato col simbolo, preso
    dal tracciato del logo e disegnato al volo con Pillow. Se qualcosa manca,
    resta l'icona di prima: l'aspetto non deve mai poter fermare l'avvio."""
    try:
        from PIL import Image, ImageDraw
        quadrato = [p for p in _sottotracciati() if max(x for x, _ in p) < LOGO_ALTEZZA * 1.1]
        bordo = max(quadrato, key=lambda p: (max(x for x, _ in p) - min(x for x, _ in p)))
        x0, y0 = min(x for x, _ in bordo), min(y for _, y in bordo)
        lato_logo = max(max(x for x, _ in bordo) - x0, max(y for _, y in bordo) - y0)
        lato, s = 128, 4                      # disegnato 4× e poi ridotto: bordi lisci
        tela = Image.new("RGB", (lato * s, lato * s), "#011E41")
        penna = ImageDraw.Draw(tela)
        k = lato * s / lato_logo
        for p in quadrato:
            if p is not bordo:                 # i buchi del quadrato sono il simbolo
                penna.polygon([((x - x0) * k, (y - y0) * k) for x, y in p], fill="#FFFFFF")
        return tela.resize((lato, lato), Image.LANCZOS)
    except Exception:
        return riserva


# ═══ IL BANNER ══════════════════════════════════════════════════════════════
# Sta QUI DENTRO, non in un file accanto. Un file separato si perde: la
# cartella `assets/` non è arrivata nella copia in produzione e la testata è
# tornata al titolo scritto — lo stesso che era successo con `.streamlit/`.
# Un modulo Python invece arriva sempre, perché senza non parte niente.
#
# È un SVG e non un'immagine: pesa pochi chilobyte, resta nitido a qualunque
# ingrandimento e su qualunque schermo, il testo dentro è testo vero
# (selezionabile, pulito in stampa), e usa i colori esatti della palette
# corporate — `#011E41` il blu, `#7B8A9C` il grigio-azzurro, `#DFE7EA`
# l'azzurro chiaro, `#FFFFFF` il bianco. Basso (1600 × 260) perché la
# testata non rubi spazio ai risultati; il logo non sta qui ma in cima alla
# barra laterale (`logo_barra`).
#
# Inline e non come `data:` in un `<img>`: il ripulitore di HTML del browser
# tratta le due cose in modo diverso, e l'SVG scritto direttamente nella
# pagina è la forma che passa sempre.
BANNER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 260" preserveAspectRatio="xMidYMid meet" role="img">
  <defs>
    <clipPath id="lake-taglio"><rect width="1600" height="260" rx="12"/></clipPath>
    <linearGradient id="lake-acqua" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0"   stop-color="#00132B"/>
      <stop offset="0.55" stop-color="#011E41"/>
      <stop offset="1"   stop-color="#0B3258"/>
    </linearGradient>
    <radialGradient id="lake-bagliore" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#7B8A9C" stop-opacity=".45"/>
      <stop offset="1" stop-color="#7B8A9C" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <g clip-path="url(#lake-taglio)">
    <rect width="1600" height="260" fill="url(#lake-acqua)"/>
    <ellipse cx="430" cy="232" rx="300" ry="62" fill="url(#lake-bagliore)"/>
    <ellipse cx="1180" cy="232" rx="270" ry="56" fill="url(#lake-bagliore)"/>
    <g fill="none" stroke="#DFE7EA">
      <g transform="translate(430,232)">
        <ellipse rx="58"  ry="10" opacity=".80" stroke-width="2"/>
        <ellipse rx="112" ry="19" opacity=".55" stroke-width="1.7"/>
        <ellipse rx="176" ry="29" opacity=".36" stroke-width="1.5"/>
        <ellipse rx="248" ry="41" opacity=".22" stroke-width="1.3"/>
        <ellipse rx="326" ry="54" opacity=".12" stroke-width="1.2"/>
      </g>
      <g transform="translate(1180,232)">
        <ellipse rx="50"  ry="8"  opacity=".70" stroke-width="2"/>
        <ellipse rx="98"  ry="17" opacity=".48" stroke-width="1.7"/>
        <ellipse rx="156" ry="26" opacity=".30" stroke-width="1.5"/>
        <ellipse rx="220" ry="36" opacity=".18" stroke-width="1.3"/>
        <ellipse rx="292" ry="49" opacity=".10" stroke-width="1.2"/>
      </g>
    </g>
    <line x1="0" y1="190" x2="1600" y2="190" stroke="#DFE7EA" stroke-width="1" opacity=".30"/>
    <g fill="#DFE7EA" opacity=".30">
      <rect x="140" y="64"  width="92"  height="4" rx="2"/>
      <rect x="140" y="79"  width="148" height="4" rx="2"/>
      <rect x="140" y="94"  width="66"  height="4" rx="2"/>
      <rect x="1318" y="64" width="126" height="4" rx="2"/>
      <rect x="1318" y="79" width="78"  height="4" rx="2"/>
      <rect x="1318" y="94" width="164" height="4" rx="2"/>
    </g>
    <text x="800" y="126" text-anchor="middle"
          font-family="IBM Plex Sans, Segoe UI, Arial, sans-serif"
          font-size="92" font-weight="600" letter-spacing="12" fill="#FFFFFF">LAKE</text>
    <text x="800" y="164" text-anchor="middle"
          font-family="IBM Plex Sans, Segoe UI, Arial, sans-serif"
          font-size="17" font-weight="500" letter-spacing="6.5" fill="#DFE7EA">LEGACY APPLICATION KNOWLEDGE EXTRACTOR</text>
  </g>
</svg>"""


def logo_barra() -> None:
    """Il logo in cima alla barra laterale, in blu sul fondo dorato.
    Va chiamata prima di ogni altro elemento della barra: Streamlit la
    riempie nell'ordine delle chiamate."""
    st.sidebar.markdown(f'<div class="logo-barra">{logo_svg(62)}</div>',
                        unsafe_allow_html=True)


def testata(titolo: str, compito: str, marcatori: Optional[List[str]] = None,
           sigla: bool = False) -> None:
    """L'intestazione della pagina.

    Se il banner c'è, prende il posto del titolo scritto — e il titolo diventa
    il suo testo alternativo, che è quello che legge chi usa uno screen reader
    e quello che compare se l'immagine non si carica. Il nome del prodotto non
    deve mai dipendere da un file che potrebbe mancare."""
    # Il titolo resta scritto nella pagina, anche col banner: è quello che
    # legge uno screen reader e quello che resta se l'SVG non venisse
    # disegnato. Nascosto alla vista, non al lettore.
    st.markdown(
        f'<div class="testata">{BANNER_SVG}'
        f'<h1 class="solo-lettori">{_e(titolo)}</h1>'
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
        barra = ""
        if v.get("quota") is not None:
            quota = max(0.0, min(float(v["quota"]), 1.0))
            barra = f'<div class="pista-c"><i style="width:{quota * 100:.0f}%"></i></div>'
        classe = "cifra rilievo" if v.get("rilievo") else "cifra"
        pezzi.append(f'<div class="{classe}"><div class="valore">{_e(v["valore"])}</div>'
                     f'<div class="voce">{_e(v["voce"])}</div>{nota}{barra}</div>')
    st.markdown('<div class="cifre">' + "".join(pezzi) + "</div>", unsafe_allow_html=True)


def fascia(coppie: List[tuple], avviso: str = "") -> None:
    """La fascia dei fatti dell'esecuzione: [(etichetta, valore), …]. Un
    valore vuoto si scrive «—» in grigio. `avviso` è una pillola in fondo
    (per esempio INCOMPLETE)."""
    pezzi = []
    for k, v in coppie:
        v = str(v or "").strip()
        e_costo = k.lower() == "cost" and bool(v) and v[0] in "≈€$£"
        # un suggerimento («set prices…») non è un valore: pesa meno
        classe = "v" if v and (k.lower() != "cost" or e_costo) else "v spenta"
        scheda = ' class="costo"' if e_costo else ""
        pezzi.append(f'<div{scheda}><span class="{classe}">{_e(v) if v else "—"}</span>'
                     f'<span class="k">{_e(k)}</span></div>')
    if avviso:
        pezzi.append(f'<span class="avviso">{_e(avviso)}</span>')
    st.markdown('<div class="fascia">' + "".join(pezzi) + "</div>", unsafe_allow_html=True)


def legenda(marcatori: List[str], testo: str = "") -> None:
    """La legenda delle tabelle in una riga: le marche e una frase."""
    st.markdown('<div class="legenda">' + "".join(marcatori)
                + (f"<span>{_e(testo)}</span>" if testo else "") + "</div>",
                unsafe_allow_html=True)


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
    """L'intestazione di una tappa NELLA BARRA LATERALE.

    `st.sidebar.markdown`, non `st.markdown`: con il secondo le tre tappe
    finivano in cima alla pagina, sopra il titolo, dove non volevano dire
    niente — e nella barra laterale restavano i controlli senza intestazione.
    I numeri ci stanno perché questa È una sequenza: senza chiave non si
    analizza, senza sorgenti non si esporta."""
    st.sidebar.markdown(f'<div class="tappa"><span>{_e(numero)}</span>{_e(testo)}</div>',
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
STATI_LOTTO = {
    "coda": ("◷", "queued"), "cache": ("↺", "from cache"), "corso": ("●", "running"),
    "continua": ("↻", "continuing"), "fatto": ("✓", "done"),
    "incompleto": ("◐", "incomplete"), "errore": ("✕", "failed"), "fermato": ("■", "stopped"),
}


def _durata(secondi) -> str:
    if secondi is None:
        return "—"
    s = int(round(secondi))
    return f"{s // 60}:{s % 60:02d}"


def _atteso(r: Dict[str, Any]) -> str:
    """«/ ~2:10» accanto al tempo, finché il lotto non è finito, se la storia
    delle esecuzioni passate permette di dirlo."""
    if r.get("stima") and r.get("stato") in ("coda", "corso", "continua"):
        return f' <span class="atteso">/ ~{_durata(r["stima"])}</span>'
    return ""


def tabellone_lotti(foto: List[Dict[str, Any]], parallelismo: int = 0) -> str:
    """I lotti, uno per riga, con una striscia sul tempo comune.

    `foto` viene da `Tabellone.copia()`: numero, file, stato, secondi
    trascorsi, scostamento dall'inizio (`da`), giri di continuazione, token.
    Restituisce HTML: si disegna con `st.markdown(..., unsafe_allow_html=True)`
    dentro un segnaposto che si ridisegna a ogni fotografia."""
    if not foto:
        return ""
    fine_asse = max([(r["da"] or 0) + (r["secondi"] or 0) for r in foto] + [1.0])
    conta: Dict[str, int] = {}
    for r in foto:
        conta[r["stato"]] = conta.get(r["stato"], 0) + 1
    ordine = ["corso", "continua", "fatto", "incompleto", "errore", "fermato", "coda", "cache"]
    capo = " · ".join(f"{conta[k]} {STATI_LOTTO[k][1]}" for k in ordine if conta.get(k))
    if parallelismo:
        capo += f" · up to {parallelismo} at once"
    basi = [r.get("esecuzioni") or 0 for r in foto if r.get("stima")]
    if basi:
        capo += f" · «~» is the usual time for a batch this size, from {max(basi)} earlier runs"
    # A lotti finiti, la risposta alla domanda «il parallelo è servito?»: la
    # somma dei tempi dei lotti è quanto sarebbe durato uno dopo l'altro; il
    # tempo di parete è quanto è durato davvero. La differenza è il guadagno.
    lavorati = [r for r in foto if r.get("secondi") and r.get("da") is not None]
    if len(lavorati) > 1 and all(r["stato"] in ("fatto", "incompleto", "errore") for r in lavorati):
        in_fila = sum(r["secondi"] for r in lavorati)
        di_parete = max(r["da"] + r["secondi"] for r in lavorati) - min(r["da"] for r in lavorati)
        risparmio = in_fila - di_parete
        if risparmio > 1:
            capo += (f" · one after the other: {_durata(in_fila)} · side by side: "
                     f"{_durata(di_parete)} · saved {_durata(risparmio)}")
        else:
            capo += f" · {_durata(in_fila)} total, no overlap: they ran one after the other"
    righe = []
    for r in foto:
        simbolo, parola = STATI_LOTTO.get(r["stato"], ("?", r["stato"]))
        if r["stato"] == "continua" and r.get("giri"):
            parola += f" ({r['giri']})"
        file = r["file"][0] if r["file"] else "—"
        if len(r["file"]) > 1:
            file += f" +{len(r['file']) - 1}"
        uso = r.get("uso") or {}
        token = (f"{uso.get('input', 0):,} / {uso.get('output', 0):,}"
                 if uso.get("input") or uso.get("output") else "—")
        barra = ""
        if r["da"] is not None:
            sinistra = r["da"] / fine_asse * 100
            larghezza = max((r["secondi"] or 0) / fine_asse * 100, 0.8)
            barra = (f'<i class="st-{r["stato"]}" '
                     f'style="left:{sinistra:.1f}%;width:{min(larghezza, 100 - sinistra):.1f}%"></i>')
        elif r["stato"] == "cache":
            barra = '<i class="st-cache" style="left:0;width:0.8%"></i>'
        titolo_file = _e(", ".join(r["file"]))
        righe.append(
            f'<tr><td class="num">{r["n"]}</td>'
            f'<td class="file" title="{titolo_file}">{_e(file)}</td>'
            f'<td class="st-{r["stato"]}"><span class="seg">{simbolo}</span> {_e(parola)}</td>'
            f'<td class="cifra-l">{_durata(r["secondi"])}{_atteso(r)}</td>'
            f'<td class="cifra-l">{token}</td>'
            f'<td class="pista-l"><div class="pista-lotto">{barra}</div></td></tr>')
    return (f'<div class="lotti"><p class="lotti-capo">{_e(capo)}</p>'
            '<table class="lotti-t"><thead><tr><th>#</th><th>Files</th><th>Status</th>'
            '<th style="text-align:right">Time</th><th style="text-align:right">Tokens in / out</th>'
            '<th>Timeline</th></tr></thead><tbody>' + "".join(righe) + '</tbody></table></div>')


def testa_riquadro(titolo: str, descrizione: str) -> None:
    """Titolo e descrizione di un riquadro che deve essere alto quanto i suoi
    vicini di riga (vedi `.pari-titolo` e `.pari-testo` nel CSS)."""
    st.markdown(f'<p class="pari-titolo">{_e(titolo)}</p>'
                f'<p class="pari-testo">{_e(descrizione)}</p>', unsafe_allow_html=True)


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


def lavoro_in_corso(etichetta: str):
    """Un riquadro che dice cosa sta succedendo mentre il modello lavora.

    `st.status` mostra una rotella che gira e si può aprire per leggere le
    righe man mano che arrivano; sulle installazioni che non ce l'hanno si
    ripiega su `st.spinner`, che la rotella ce l'ha comunque. Un'analisi vera
    dura minuti: senza qualcosa che si muove, la pagina sembra bloccata e la
    gente ricarica — buttando via il lavoro fatto fino a lì."""
    if hasattr(st, "status"):
        return st.status(etichetta, expanded=True)
    return st.spinner(etichetta)


def passo(contenitore, testo: str) -> None:
    """Aggiorna l'etichetta del riquadro, se il riquadro sa farlo."""
    try:
        contenitore.update(label=testo)
    except Exception:
        pass


def finito(contenitore, testo: str, riuscito: bool = True) -> None:
    try:
        contenitore.update(label=testo, state="complete" if riuscito else "error",
                           expanded=False)
    except Exception:
        pass


def avviso_temporaneo(testo: str) -> None:
    """Un avviso che compare e sparisce.

    Niente icona: `st.toast` valida l'icona come emoji vera, e un segno di
    spunta tipografico (✓, U+2713) non lo è — Streamlit alza un'eccezione. Con
    l'avviso in fondo al blocco dell'analisi, quell'eccezione veniva raccolta
    dal `except` di sopra e compariva come «The analysis stopped», su
    un'analisi che era invece finita bene e già salvata. Un avviso di cortesia
    non deve poter far fallire tre minuti di lavoro: qui non ha più un'icona da
    validare, e in più qualunque cosa vada storta nel mostrarlo viene
    ignorata."""
    try:
        if hasattr(st, "toast"):
            st.toast(testo)
        else:
            st.success(testo)
    except Exception:
        pass
