# Modifiche — Legacy Application Knowledge Extractor

Versione contratto JSON: **2.0** · Collaudo: `python test_catena.py` → 29/29

Tre blocchi: **A** la catena modelli presa da Nuvia, **B** il contratto JSON,
**C** il resto (difetti trovati per strada e robustezza).

---

## A · Selezione, prova e scalata dei modelli (impianto di Nuvia)

Nuovo file **`model_chain.py`**: porting Python della catena di Nuvia
(`src/15_6_ai_gemini…js`), esteso ai tre provider dell'app. Prima il modello
era una stringa scritta a mano nella barra laterale: se quel nome era sbagliato,
dismesso o momentaneamente occupato, l'analisi moriva con l'errore grezzo del
provider stampato a schermo.

| # | Modifica | Perché |
|---|---|---|
| A1 | **Scoperta dei modelli.** All'avvio si chiede al provider l'elenco dei modelli veri di *quella* chiave: `GET /v1beta/models` (Gemini), `GET /v1/models` (Anthropic), `GET /openai/deployments` (Azure). | Il nome scritto a mano invecchia. Così l'app usa i modelli usciti dopo senza toccare il codice. |
| A2 | **Filtri di catena.** Si tengono solo i modelli adatti: niente `-lite`, `preview`, `exp`, `latest`, nomi con data, embedding/tts/vision/live; per Gemini solo dalla 2.0 in su. Restano al massimo 5 modelli. | Un `preview` cambia sotto i piedi; un `embedding` non sa rispondere; `latest` punta a un modello che si sposta. |
| A3 | **Ordine per fascia, non per nome.** Con `Quality first` (predefinito) la catena parte dai modelli grandi (`pro` / `opus` / `gpt-5`,`o3`,`4.1`…) e scende verso quelli economici. Con `Speed / cost first` si ottiene la regola esatta di Nuvia (solo flash/haiku/mini). | **Differenza voluta rispetto a Nuvia**: Nuvia è una chat e tiene solo i flash perché contano costo e latenza. Qui una singola esecuzione legge decine di migliaia di righe di legacy: la qualità vale più del costo. L'interruttore lascia scegliere. |
| A4 | **Prova di contatto.** A ogni modello, in ordine, «Rispondi con una sola parola: OK», tetto **5 s per modello** e **10 s complessivi**. Il primo che risponde vince. | Stessi numeri di Nuvia. Cinque secondi bastano per una risposta da due parole; venticinque non renderebbero la prova più affidabile, solo più lenta. |
| A5 | **Secondo tentativo solo sui guasti che possono passare** (occupato, timeout, rete), e solo se restano almeno altri 5 s. Su 404, quota finita, chiave sbagliata si passa oltre subito. | Riprovare un modello che non esiste costa tempo per sapere una cosa che sappiamo già. |
| A6 | **La chiamata vera parte dal modello che ha risposto** e scende solo in giù, mai risale. 3 tentativi per modello con attesa crescente. | Risalire a chi era già giù significa pagare tre tentativi e tre attese a vuoto. |
| A7 | **Memoria a scadenza.** Modello buono 10 minuti, elenco scoperto 6 ore, adattamenti per modello per sempre. Su file (`.catena_modelli.json`) o in RAM. | La seconda analisi non rifà la prova. Dieci minuti perché un modello «giù» stamattina è su stasera, e il migliore deve poter tornare in testa da solo. |
| A8 | **Della chiave si salva solo l'impronta** (sha256 troncato) come identità della cache. | Due chiavi diverse non si scambiano la cache, e la chiave non finisce mai su disco. |
| A9 | **Tassonomia dei guasti unica per i tre provider**: `quota`, `modello`, `badkey`, `busy`, `timeout`, `rete`, `vuota`, `troncata`, `blocked`, `contesto`, `parametro`. Ogni provider traduce il proprio dialetto in questi nomi. | Chi decide se riprovare non deve leggere i messaggi di Google, di Anthropic e di Azure: legge un nome. |
| A10 | **Il messaggio dice la verità.** «Riprova più tardi» solo quando riprovare può cambiare qualcosa. Chiave sbagliata, quota finita e contesto pieno hanno il loro messaggio, in italiano e in inglese. | Un messaggio che promette quello che il codice non farà è un difetto, non una gentilezza. |
| A11 | **`contesto` non fa scendere la catena** e lo spiega (riduci i file o usa i lotti). | I modelli più in basso hanno finestre uguali o più piccole: scendere è tempo perso. |
| A12 | **Guardia a orologio sulle chiamate.** Ogni richiesta gira in un thread contro una scadenza vera. | Il `timeout` di `requests` è per singola lettura del socket: un server che manda un byte ogni tre secondi non lo fa scattare mai, e il tetto dei 5 s smette di esistere. È il `conAbort` di Nuvia. |
| A13 | **Il 400 che non è una chiave sbagliata.** Prima di accusare la chiave si legge il corpo dell'errore: se parla di uno schema, di `temperature`, di `max_tokens` vs `max_completion_tokens` o del thinking, si adatta la richiesta, si ricorda l'adattamento per *quel* modello e si riprova. | Come in Nuvia col `thinkingLevel`: trattarlo come «chiave non valida» scarterebbe il modello migliore con la diagnosi sbagliata e manderebbe la persona a rigenerare una chiave sana. |
| A14 | **Bottone «Test connection»** nella barra laterale: mostra la catena scoperta, chi ha risposto, in quanti ms, e il diario dei tentativi. | Prima l'unico modo di sapere se la configurazione funzionava era lanciare un'analisi da tre minuti. |
| A15 | **Riga di comando**: `python model_chain.py --provider gemini --modelli` / `--prova`. | Si collauda la configurazione di un ambiente senza aprire Streamlit. |
| A16 | **Trasporto unico via `requests`** al posto dei tre SDK (`openai`, `anthropic`, `google-genai`). | Tre SDK = tre modi di ritentare *sopra* la nostra scalata (il client OpenAI ritenta i 429 da solo, mangiandosi il tempo del nostro tetto), tre modi di nascondere lo status HTTP e tre dipendenze da aggiornare. Con `requests` gli status arrivano interi e la scalata è l'unica cosa che ritenta. |

---

## B · I contratti JSON

Nuovo file **`contract.py`**: il contratto è **uno solo**, e prompt, schema
nativo, riparazione e normalizzazione sono generati dalla stessa struttura, così
non possono divergere.

| # | Modifica | Perché |
|---|---|---|
| B1 | **Contratto completo per tutte e dodici le sezioni.** Prima il prompt mostrava i campi per esteso solo per `business_processes` e `business_rules`; le altre dieci erano `[]` vuote. | Con `"components": []` nel prompt il modello inventa i nomi dei campi a ogni esecuzione: `name` o `component_name`, `file` o `source_file`. Le tabelle uscivano con le colonne mezze vuote. |
| B2 | **Valori enumerati imposti**: `severity` e `criticality` LOW/MEDIUM/HIGH/CRITICAL, `confidence` LOW/MEDIUM/HIGH, `source` STATIC_ANALYSIS/LLM_ANALYSIS/MIXED, `direction` INBOUND/OUTBOUND/BIDIRECTIONAL/UNKNOWN. | Testo libero in `severity` significa: impossibile ordinare per gravità, filtrare o contare. |
| B3 | **Normalizzazione degli enum, non scarto**: «High», «critico», «Sev2», «confidence: high» vengono raddrizzati; ciò che resta ignoto prende un valore di riserva ed è segnalato. | Il modello sbaglia in modi prevedibili. Cinquanta righe di codice li chiudono tutti. |
| B4 | **Schema nativo dove il provider lo sa imporre**: `responseSchema` per Gemini, `response_format: json_object` per Azure/OpenAI. | È l'unica garanzia sui nomi dei campi che non dipende dalla buona volontà del modello. |
| B5 | **Prefill `{` su Anthropic** (si apre la risposta al posto del modello). | Costa zero e toglie alla radice preamboli e recinti markdown, prima causa di JSON non parsabile su quel provider. |
| B6 | **Diagrammi Mermaid come array di righe**, non come stringa con `\n` dentro. | Gli a-capo scappati dentro una stringa JSON erano il posto peggiore dove mettere un diagramma: bastava un `\n` sbagliato per perdere l'intera risposta. |
| B7 | **Pulizia dei diagrammi**: recinti markdown ed entità HTML rimossi, intestazione aggiunta se manca, **etichette messe fra virgolette** e ripulite da `( ) [ ] { } " ;`. | `A[Ordine (nuovo)]` non si disegna. Era la causa più comune di «No diagram generated». |
| B8 | **Riparazione del JSON troncato.** Si torna all'ultimo confine sicuro, si chiudono le parentesi aperte e si tengono tutte le righe complete; la riga a metà viene scartata a valle. | Il tetto di token è il modo più comune di perdere un'analisi da tre minuti: prima `json.loads` buttava via anche le duecento righe perfette che venivano prima. |
| B9 | **Risposta troncata consegnata e segnalata** invece che persa (con avviso in interfaccia). | Ripetere lo stesso prompt non accorcia una risposta troppo lunga. |
| B10 | **`max_tokens` da 8.000 a 16.000.** | Con dodici sezioni e quattro diagrammi, 8.000 token tagliavano la risposta a metà su qualsiasi codebase reale. |
| B11 | **Gli id li assegna il codice** (`BR-001`, `TR-001`, `VQ-001`…), non il modello, e sono rinumerati dopo l'unione dei lotti. | Il modello riparte da 1 a ogni lotto: tre `BR-001` diversi nello stesso documento. |
| B12 | **Deduplica su chiavi dichiarate**, le stesse che usa l'analisi statica, insensibile a maiuscole/spazi. | È così che le due metà (parser e modello) si uniscono senza righe gemelle. |
| B13 | **Righe vuote scartate**: una riga in cui sono pieni solo i campi che abbiamo messo noi non è una riga. | Altrimenti finisce nel PDF come riga di rumore. |
| B14 | **Le liste dentro una cella diventano testo** (`["A","B"]` → `A; B`), celle limitate a 1.500 caratteri. | Una lista Python in una cella si stampa come `['a', 'b']` e nessuno la legge; una cella da 20.000 caratteri rende la tabella illeggibile. |
| B15 | **`validation_questions` e `assumptions` diventano righe strutturate** (domanda, perché conta, a chi va chiesta / assunzione, su cosa si regge, rischio se sbagliata), con una scheda dedicata in interfaccia. Le vecchie liste di stringhe vengono convertite da sole. | Erano nel contratto ma non venivano mostrate da nessuna parte: la parte più utile per lo SME era quella buttata. |
| B16 | **Campi in più tenuti, non buttati.** Se il modello aggiunge un campo sensato, resta in fondo alla riga. | Buttarlo farebbe perdere informazione vera. |
| B17 | **`contract_warnings`**: l'app dice apertamente cosa ha dovuto aggiustare nella risposta del modello (sezioni assenti, enum corretti, righe scartate). | Chi valida deve sapere quanto fidarsi di quello che sta leggendo. |
| B18 | **Anche le righe del parser passano dal contratto** prima di essere unite a quelle del modello. | Prima le due metà avevano forme diverse: unite, davano tabelle a colonne mancanti. |
| B19 | **Regole di ingaggio nel prompt**: mai inventare nomi di file, tabelle o righe; una lista vuota è una risposta corretta; i metadati statici sono fatti e non si contraddicono; se inferisci, abbassa la `confidence` e scrivi il ragionamento in `evidence`. | Il documento va in mano a esperti di dominio che lo validano riga per riga: un fatto mancante è meglio di uno inventato. |
| B20 | **Recinto irripetibile attorno al sorgente** (`<<<SRC-xxxxxx … SRC-xxxxxx>>>`, casuale a ogni esecuzione) e istruzione esplicita a trattarlo come dato. | Con il recinto fisso ` ``` ` un file sorgente che contiene tre backtick chiude il proprio blocco, e il resto del file viene letto come istruzioni. Su una codebase altrui è una porta aperta. |

---

## C · Difetti trovati e robustezza

| # | Modifica | Perché |
|---|---|---|
| C1 | **`exp` non copre più il modulo `sqlglot.exp`** in `parse_sql_expressions` (la variabile si chiama `parsed`). | Era `[exp for exp in expressions …]`: dentro quella funzione il modulo `exp` smetteva di esistere. Non è mai esploso solo perché lì non serviva — un errore in attesa. |
| C2 | **Sintesi esecutiva presa dalla radice** (`extract_field` guarda prima la radice, poi in profondità). | Cercando anche `description` in tutto il JSON, con un summary vuoto il PDF stampava come sintesi esecutiva la descrizione del primo rischio tecnico. Sbagliato in un modo che nessuno nota finché non lo legge il cliente. |
| C3 | **PDF e Word generati su richiesta e messi in cache**, non a ogni ricaricamento della pagina. | Prima ogni spunta su una casella rigenerava PDF *e* Word, scaricando otto immagini da `mermaid.ink`: pagina lentissima e un servizio esterno martellato per niente. |
| C4 | **`mermaid.ink`: secondo tentativo, timeout 20 s, niente riprova sui 4xx, guardia sulla lunghezza dell'URL.** | Un intoppo momentaneo non deve costare un PDF senza diagrammi; un diagramma non valido darebbe lo stesso 400 all'infinito. |
| C5 | **Analisi a lotti.** Oltre ~120.000 caratteri il sorgente si divide in lotti (mai spezzando un file), ogni lotto è un'analisi completa e i risultati si uniscono. Tetto totale alzato da 180.000 a 1.500.000 caratteri. | Prima, oltre una certa dimensione, il modello troncava e l'analisi si perdeva senza che nessuno lo dicesse. Un file spezzato a metà dà regole di business monche, che è peggio di un file in meno. |
| C6 | **Riuso dell'analisi a parità di ingresso** (impronta di file + provider + contratto), con casella «Force re-analysis». | Streamlit riesegue lo script a ogni interazione: prima bastava una spunta per far ripartire tre minuti di modello a pagamento. |
| C7 | **Barra di avanzamento per lotto** con i nomi dei file in lavorazione. | Su una codebase vera l'attesa è di minuti: senza avanzamento sembra bloccata. |
| C8 | **Tetto di 300 righe per tipo di ritrovamento** nell'analisi statica, ed esclusioni ampliate per `PROBABLE_CALL`. | Il pattern «qualsiasi identificatore seguito da parentesi» su un Java da 5.000 righe produceva migliaia di dipendenze finte che affogavano le poche vere e raddoppiavano il costo del prompt. |
| C9 | **Regex dei file di interfaccia non più ingorda.** | Era `[^"']+\.(csv\|txt\|…)["']`: su una riga lunga si mangiava centinaia di caratteri, che finivano nel PDF come «nome dell'interfaccia». |
| C10 | **Nel prompt vanno solo i metadati del lotto**, senza il dettaglio per file. | Il dettaglio per file raddoppiava il prompt senza aggiungere fatti. |
| C11 | **Colonna di validazione SME come casella vera** (`CheckboxColumn`), stato conservato fra i ricaricamenti. | Prima `sme_approved` veniva reinserita a ogni giro e poteva perdere le spunte. |
| C12 | **Controllo dell'endpoint Azure** prima di partire, e **il deployment scritto a mano resta sempre primo in catena**. | Su Azure il nome chiamabile è il deployment, che solo chi ha creato la risorsa conosce: non è derivabile e non va scavalcato dalla scoperta. |
| C13 | **Metriche in interfaccia**: aggiunte «Business rules» e il modello che ha risposto, i lotti eseguiti, la versione del contratto. | Serve sapere chi ha scritto il documento che si sta per firmare. |
| C14 | **Sorgente del diagramma sempre consultabile** in un pannello, anche quando il disegno riesce. | Quando un diagramma non si disegna, il sorgente è l'unico modo per capire perché. |
| C15 | **Collaudo automatico `test_catena.py`** — 29 casi, nessuna rete, nessuna chiave, nessun costo: scoperta, scalata, memoria, messaggi, tetti, riparazione JSON, enum, Mermaid, lotti. | Porting del collaudo di Nuvia. È il modo per cambiare una regola e sapere subito cosa si rompe. |
| C16 | **`requirements.txt`**: tolti `openai`, `anthropic`, `google-genai`; `requests` è ora una dipendenza dichiarata dell'app, non solo dell'esportatore. | Vedi A16. Tre dipendenze pesanti in meno da aggiornare e da far passare in azienda. |
| C17 | **README vero** (prima conteneva la parola «Ciao») e questo elenco. | — |

---

## Cosa NON è stato cambiato

- La struttura di `exporter.py` (PDF e Word): due sole correzioni chirurgiche
  (C2, C4). Impaginazione, stili e sezioni sono rimasti quelli.
- L'interfaccia resta in inglese; i commenti dei file nuovi sono in italiano,
  come in Nuvia.
- L'analisi statica (sqlglot + espressioni regolari) resta l'ancora dei fatti:
  nessuna delle modifiche la sostituisce con il modello.

## Da decidere insieme

1. **`Quality first` come predefinito** (A3): costa più di Nuvia per esecuzione.
   Se il pilota deve girare su molte applicazioni, forse conviene `Speed first`
   con un secondo passaggio in qualità solo sulle regole di business.
2. **Chiavi nella barra laterale**: funzionano, ma se l'app viene esposta a più
   utenti vanno spostate su variabili d'ambiente o su un gestore di segreti.
3. **`mermaid.ink` è un servizio esterno**: il codice dei diagrammi ci esce
   dall'azienda. Se è un problema, va sostituito con un mermaid-cli locale
   (~20 righe, nessun'altra modifica).
