# Legacy Application Knowledge Extractor

Estrae conoscenza da applicazioni legacy (PL/SQL, COBOL, RPG, Visual Basic,
Java, Python e qualunque altro file di testo):
analisi statica del codice + analisi con un modello, validazione da parte di un
esperto di dominio, ed esportazione in PDF, Word e JSON.

## Avvio

```bash
python avvia.py
```

Un comando solo: controlla cosa manca, lo installa, imposta Streamlit e apre
l'applicazione. Su una macchina pulita non serve altro — né `pip`, né `npm`,
né configurazioni da ricordarsi. Ogni comando che esegue viene stampato prima,
e l'installazione Python finisce nell'interprete corrente, quindi dentro il
virtualenv se ne hai uno attivo.

| Opzione | Cosa fa |
|---|---|
| `--niente-installazioni` | controlla e basta |
| `--senza-mermaid` | salta mermaid-cli (i diagrammi useranno la rete) |
| `--porta 8502` | apre su un'altra porta |

Per guardare com'è messa una macchina senza toccarla: `python verifica.py`.
Dentro l'applicazione, la stessa cosa la fa il bottone *Install what's missing*
nella barra laterale, sotto *Dependencies*.
Per avviare a mano: `streamlit run app.py` (funziona, ma senza il limite di
caricamento e la barra strumenti ridotta che imposta `avvia.py`).

`cache/` viene creata al primo uso: contiene i lotti già analizzati (per non
ripagarli) e la memoria della catena. È esclusa da git e si può cancellare
senza perdere nulla.

La validazione si può interrompere e riprendere: il JSON scaricato dalla
scheda *Export* si ricarica dal pannello *«Or resume a saved analysis»*, spunte
comprese.

Le chiavi si scrivono nella barra laterale, oppure si mettono nell'ambiente:
`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `AZURE_OPENAI_API_KEY` con
`AZURE_OPENAI_ENDPOINT` e `AZURE_OPENAI_DEPLOYMENT`.

## Metterlo su git

Tutto il progetto va versionato così com'è. Non c'è niente da tenere fuori: le
chiavi non sono nel codice e l'unico file generato (`.catena_modelli.json`, la
memoria della catena) è già escluso. Non ci sono cartelle nascoste: le
impostazioni di Streamlit le passa `avvia.py`, che è un file normale e visibile.

Chi clona fa `python avvia.py` e si trova l'applicazione aperta. Le uniche due
cose che non possono stare nel repository — i pacchetti Python e mermaid-cli —
se le installa quel comando; per mermaid-cli serve Node.js sulla macchina, e se
manca `avvia.py` lo dice e prosegue senza (i diagrammi passeranno dalla rete).

I caratteri in `fonts/` sono IBM Plex, licenza SIL Open Font 1.1: si
ridistribuiscono con il progetto, anche commerciale, purché la licenza resti
insieme ai file — è in `fonts/LICENSE.txt`.

## Com'è fatto

| File | Cosa fa |
|---|---|
| `app.py` | Pagina, analisi statica, orchestrazione |
| `ui.py` | Tema, componenti e marcatori dell'interfaccia |
| `model_chain.py` | Scoperta, prova e scalata dei modelli (impianto di Nuvia) |
| `contract.py` | Il contratto JSON: prompt, schema, riparazione, normalizzazione |
| `diagrams.py` | I quattro diagrammi ricavati dai dati validati |
| `mermaid_render.py` | Disegno dei diagrammi, in locale se possibile |
| `exporter.py` | PDF e Word: una descrizione, due rese |
| `fonts/` | IBM Plex per il PDF, con licenza |
| `avvia.py` | Installa quello che manca, configura e apre l'applicazione |
| `verifica.py` | Controlla che un clone sia completo, senza toccare niente |
| `test_catena.py` | Collaudo, senza rete e senza chiavi |
| `guida_pdf.py` | Rigenera le due guide in PDF (servizio, non serve all'app) |

### La catena dei modelli

Il modello non è fisso. All'avvio l'app chiede al provider quali modelli sono
davvero disponibili per quella chiave, tiene i migliori (al massimo cinque), li
prova con una domanda da due parole (5 s per modello, 10 s in tutto) e lancia
l'analisi sul primo che risponde. Se quello cade a metà, si scende al
successivo; non si risale mai a chi era già giù. Il modello che ha risposto si
ricorda per dieci minuti.

Quando non risponde nessuno, il messaggio dice la verità: «riprova più tardi»
solo se riprovare può cambiare qualcosa. Chiave sbagliata, quota finita e
contesto pieno hanno il loro messaggio.

Per collaudare una configurazione senza aprire l'interfaccia:

```bash
GEMINI_API_KEY=… python model_chain.py --provider gemini --modelli   # la catena
GEMINI_API_KEY=… python model_chain.py --provider gemini --prova     # chi risponde
```

### Il contratto JSON

Tutte le sezioni, i campi e i valori ammessi stanno in `contract.py`. Il prompt
e lo schema nativo del provider sono **generati** da lì, quindi non possono
divergere dal contratto che poi il codice pretende. In arrivo, la risposta viene
riparata se troncata, gli enum raddrizzati, gli id assegnati dal codice, i
doppioni tolti e i diagrammi ripuliti. Quello che l'app ha dovuto correggere è
scritto in chiaro nella scheda con gli avvisi di contratto.

### I diagrammi

I quattro diagrammi arrivano dal modello quando li produce, e vengono
costruiti dalle tabelle quando non li produce (o li produce troppo scarni):
sono le stesse dipendenze, gli stessi flussi e gli stessi processi che si
vedono nelle schede. Nella scheda *Diagrams* si sceglie quale versione
guardare e si possono rifare dalle tabelle dopo le correzioni dello SME.

Il disegno vero e proprio avviene **in locale**, se sulla macchina c'è mermaid-cli:

```bash
npm install -g @mermaid-js/mermaid-cli    # si porta dietro un Chromium
python mermaid_render.py                  # verifica: deve dire «locale (mmdc)»
```

Senza mermaid-cli l'app ricade sul servizio pubblico `mermaid.ink`, a cui il
codice del diagramma esce dalla macchina. `MERMAID_LOCAL_ONLY=1` lo vieta: in
quel caso i documenti portano il sorgente del diagramma invece dell'immagine.
La scheda *Downloads* dice sempre quale dei due sta per succedere.

## Collaudo

```bash
python test_catena.py     # 142 casi, nessuna rete, nessuna chiave, nessun costo
```

## Documentazione

- [GUIDA.md](GUIDA.md) — cosa fa e come funziona: una parte divulgativa e una
  tecnica, file per file. In inglese: [GUIDE.md](GUIDE.md). Entrambe anche in
  PDF (`GUIDA.pdf`, `GUIDE.pdf`); per rigenerarli dopo una modifica:
  `pip install markdown` e `wkhtmltopdf` installato, poi `python guida_pdf.py`.

## Modifiche

L'elenco completo delle modifiche di questa versione è in [MODIFICHE.md](MODIFICHE.md).
