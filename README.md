# Legacy Application Knowledge Extractor

Estrae conoscenza da applicazioni legacy (PL/SQL, COBOL, RPG, Java, Python…):
analisi statica del codice + analisi con un modello, validazione da parte di un
esperto di dominio, ed esportazione in PDF, Word e JSON.

## Avvio

```bash
pip install -r requirements.txt
streamlit run app.py
```

Nella barra laterale: provider, chiave, sorgenti. Le chiavi si possono anche
mettere nell'ambiente: `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`,
`AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_DEPLOYMENT`.

## Com'è fatto

| File | Cosa fa |
|---|---|
| `app.py` | Interfaccia Streamlit, analisi statica, orchestrazione |
| `model_chain.py` | Scoperta, prova e scalata dei modelli (impianto di Nuvia) |
| `contract.py` | Il contratto JSON: prompt, schema, riparazione, normalizzazione |
| `exporter.py` | Generazione PDF e Word |
| `diagrams.py` | I quattro diagrammi ricavati dai dati validati |
| `mermaid_render.py` | Disegno dei diagrammi, in locale se possibile |
| `test_catena.py` | Collaudo, senza rete e senza chiavi |

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
python test_catena.py     # 45 casi, nessuna rete, nessuna chiave, nessun costo
```

## Modifiche

L'elenco completo delle modifiche di questa versione è in [MODIFICHE.md](MODIFICHE.md).
