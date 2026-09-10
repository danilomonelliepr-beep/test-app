# Modifiche — Legacy Application Knowledge Extractor

Versione contratto JSON: **2.0** · Collaudo: `python test_catena.py` → 45/45

Quattro blocchi: **A** la catena modelli presa da Nuvia, **B** il contratto JSON,
**C** difetti trovati per strada e robustezza, **D** i diagrammi (disegno locale e
correzione dello schiacciamento nel PDF), **E** i diagrammi mancanti.

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
| C4 | **`mermaid.ink`: secondo tentativo, timeout 20 s, niente riprova sui 4xx, guardia sulla lunghezza dell'URL.** Ora vale solo come ricaduta: vedi il blocco D. | Un intoppo momentaneo non deve costare un PDF senza diagrammi; un diagramma non valido darebbe lo stesso 400 all'infinito. |
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
| C15 | **Collaudo automatico `test_catena.py`** — 45 casi, nessuna rete, nessuna chiave, nessun costo: scoperta, scalata, memoria, messaggi, tetti, riparazione JSON, enum, Mermaid, lotti. | Porting del collaudo di Nuvia. È il modo per cambiare una regola e sapere subito cosa si rompe. |
| C16 | **`requirements.txt`**: tolti `openai`, `anthropic`, `google-genai`; `requests` è ora una dipendenza dichiarata dell'app, non solo dell'esportatore. | Vedi A16. Tre dipendenze pesanti in meno da aggiornare e da far passare in azienda. |
| C17 | **README vero** (prima conteneva la parola «Ciao») e questo elenco. | — |

---

## E · I diagrammi che il modello non consegna

Segnalazione dal campo: nel pannello degli avvisi comparivano tre righe
«diagramma assente o non utilizzabile» — il modello aveva prodotto un diagramma
su quattro. Non era un guasto dell'app (l'avviso era l'app che diceva la verità),
ma il risultato mancava lo stesso.

Causa: i quattro diagrammi sono l'ultima cosa che il contratto chiede, dopo
dodici sezioni, ed è il punto in cui i modelli mollano. Con un aggravante mio,
vedi E1.

| # | Modifica | Perché |
|---|---|---|
| E1 | **I quattro campi Mermaid sono ora obbligatori nello schema di Gemini.** Erano rimasti fuori da `required`. | Ometterli era formalmente legittimo: il modello che si stancava non stava violando niente. Ora deve almeno dichiarare una lista vuota, e una lista vuota è un fatto che l'app sa gestire. |
| E2 | **Nuovo `diagrams.py`: i quattro diagrammi si costruiscono dai dati.** `call graph` = `dependencies`, `application map` = `application_mapping` (o `interfaces`), `data flow` = `data_flows` (o `data_objects`), `process flow` = `business_processes` (trigger → processo → esito, con i componenti coinvolti appesi). | Quei disegni non contengono niente che non sia già nelle tabelle. Chiederli al modello è chiedergli di ridisegnare a mano una cosa che abbiamo già in forma strutturata — e infatti a volte tornava con nodi che nelle tabelle non esistono. |
| E3 | **Si costruiscono DOPO l'unione con l'analisi statica.** | Così il call graph contiene anche le dipendenze trovate dal parser, non solo quelle viste dal modello. |
| E4 | **Il disegno del modello non viene buttato.** Se ha prodotto qualcosa di sostanzioso (almeno tre righe) resta lui; sotto quella soglia si mostra quello costruito dai dati. Entrambe le versioni restano nel risultato. | Sul process flow il modello dà davvero qualcosa in più: sa mettere i passi in ordine. Sugli altri tre, quello costruito dai dati è normalmente migliore. |
| E5 | **Interruttore in interfaccia** (*From the model* / *Built from the tables*) quando esistono tutte e due. | La scelta dev'essere reversibile da chi guarda, non decisa una volta per tutte dal codice. |
| E6 | **Bottone «Rebuild from the current tables».** | È il punto vero: prima lo SME cancellava una dipendenza sbagliata e il diagramma continuava a mostrarla. Il documento firmato conteneva due verità diverse. |
| E7 | **Tetti e sfoltimento**: massimo 40 archi, 8 processi, etichette a 44 caratteri, e una riga «… e altri N non mostrati». Quando le dipendenze eccedono, le `PROBABLE_CALL` e le confidenze basse sono le prime a uscire. | Un diagramma con duecento archi non documenta niente. Meglio venti archi veri e la dichiarazione di quanti ne restano fuori. |
| E8 | **Nodi sempre validi per costruzione**: id ripuliti e unici, mai a cominciare per cifra, etichette senza `( ) [ ] { } " ; \|`, tutti rettangoli. | Sono esattamente gli errori che facevano fallire il disegno quando il mermaid lo scriveva il modello. |
| E9 | **Un diagramma che non si costruisce non fa cadere l'analisi** (eccezione catturata per diagramma). | — |
| E10 | **Avvisi di contratto tradotti in inglese**, come il resto dell'interfaccia, e più precisi: distinguono «non consegnato» da «troppo scarno» da «né il modello né le tabelle bastano». | Erano in italiano dentro un'interfaccia inglese — è la riga che ha visto il collega. |
| E11 | **Undici casi in più nel collaudo**, incluso quello che riproduce la segnalazione: modello che consegna un diagramma su quattro. | — |

---

## Cosa NON è stato cambiato

- La struttura di `exporter.py` (PDF e Word): due sole correzioni chirurgiche
  (C2, C4). Impaginazione, stili e sezioni sono rimasti quelli.
- L'interfaccia resta in inglese; i commenti dei file nuovi sono in italiano,
  come in Nuvia.
- L'analisi statica (sqlglot + espressioni regolari) resta l'ancora dei fatti:
  nessuna delle modifiche la sostituisce con il modello.
- Il modello continua a essere interrogato sui diagrammi: la costruzione dai
  dati è una rete, non un rimpiazzo.

## D · Diagrammi disegnati in casa, e la forma giusta nel PDF

Nuovo file **`mermaid_render.py`**. Prima l'unico modo di ottenere l'immagine di
un diagramma era `mermaid.ink`: il codice Mermaid dell'applicazione del cliente
veniva messo in un URL e mandato a un servizio pubblico.

| # | Modifica | Perché |
|---|---|---|
| D1 | **Disegno locale con `mmdc`** (`@mermaid-js/mermaid-cli`), che è mermaid.js dentro un Chromium headless — lo stesso motore di mermaid.ink, sulla nostra macchina. Stessa libreria, stessa immagine. | Su una codebase altrui, mandare fuori la mappa applicativa è una decisione, non un dettaglio di implementazione. |
| D2 | **Ordine dei tentativi**: `mmdc` → `npx` (solo con `MERMAID_ALLOW_NPX=1`, perché scarica un pacchetto) → `mermaid.ink` come rete di sicurezza. | L'app continua a girare dove Node non c'è, senza che nessuno debba installare niente per provarla. |
| D3 | **`MERMAID_LOCAL_ONLY=1` vieta del tutto l'uscita.** In quel caso il documento porta il sorgente del diagramma invece dell'immagine. | Serve un interruttore netto per gli ambienti dove la cosa non è negoziabile. |
| D4 | **`--no-sandbox` gestito** con un file di configurazione temporaneo per Puppeteer, e rispetto di `PUPPETEER_EXECUTABLE_PATH`. | Senza `--no-sandbox` Chromium non parte dentro un container, con un errore che non nomina la sandbox: è il primo scoglio di chiunque installi mmdc su un server. Con `PUPPETEER_EXECUTABLE_PATH` si riusa il Chrome già presente ed si evita il download da 300 MB, utile dietro un proxy aziendale. |
| D5 | **Configurazione del disegno**: tema `neutral`, larghezza 2.400 px, `maxTextSize` e `maxEdges` alzati. | I limiti predefiniti di mermaid tagliano le mappe applicative vere. |
| D6 | **Niente più tetto sulla lunghezza dell'URL** quando si disegna in locale. | Il vincolo degli 8.000 caratteri era del servizio esterno: in locale le mappe grosse si disegnano e basta. |
| D7 | **Gli errori di sintassi di mermaid arrivano interi** (riga e colonna) nei log, invece del 400 muto del servizio. | Quando un diagramma non esce, ora si sa perché. |
| D8 | **Cache sull'impronta del codice**: PDF e Word chiedono gli stessi quattro diagrammi, si disegnano una volta sola. | Prima erano otto disegni per un'esportazione completa. |
| D9 | **Diagnostica**: `python mermaid_render.py` disegna un diagramma di prova e dice chi l'ha disegnato, scrivendo `prova_mermaid.png`. Nella scheda Downloads l'app dice, **prima** che si prema il bottone, se i diagrammi restano in casa o no. | Da lanciare su ogni macchina prima di dire «i diagrammi non escono più dall'azienda». |
| **D10** | **CORRETTO: i diagrammi schiacciati nel PDF.** L'immagine veniva inserita con misure fisse `width=720, height=240` — 3:1, qualunque forma avesse davvero. Ora le proporzioni si leggono dal PNG e si adatta al riquadro disponibile (780×460 pt), centrata. | Era il difetto noto: un `flowchart TD` con otto nodi in colonna è alto due volte e mezzo la sua larghezza, e schiacciato in un 3:1 diventava una striscia illeggibile. Nel Word non succedeva perché lì si passava **solo** la larghezza e l'altezza la calcolava python-docx: le proporzioni erano già rispettate. Verificato sul PDF finito: un disegno 800×2000 esce 1:2,5 e uno 2400×400 esce 6:1. |
| D11 | **Word: vincolo sull'altezza** quando il diagramma è più alto che largo (oltre 6,6 pollici si passa l'altezza invece della larghezza). | Le proporzioni erano giuste, ma un diagramma molto alto sforava la pagina. |
| D12 | **Lettura delle dimensioni PNG senza PIL** (24 byte di intestazione). | Nessuna dipendenza in più per una cosa che sono quattro righe. |
| D13 | **Cinque casi in più nel collaudo** sulla geometria dei diagrammi, incluso il caso che riproduce il difetto D10. | Un difetto corretto senza un caso di collaudo torna. |

### Installazione del disegno locale

```bash
npm install -g @mermaid-js/mermaid-cli    # si porta dietro un Chromium (~300 MB)
python mermaid_render.py                  # verifica: deve dire «locale (mmdc)»
```

Se sulla macchina c'è già Chrome:
`export PUPPETEER_EXECUTABLE_PATH=/usr/bin/google-chrome` prima dell'installazione.

> Nota onesta: il disegno locale non è stato provato end-to-end nell'ambiente in
> cui è stato scritto, perché lì il download di Chromium è bloccato dalla rete.
> Sono stati provati per davvero la scelta del motore, la ricaduta sul servizio
> esterno, la geometria e i due documenti finiti. Il primo `python
> mermaid_render.py` su una macchina vostra è il collaudo che manca.

---

## E · I diagrammi che il modello non consegna

Segnalazione dal campo: nel pannello degli avvisi comparivano tre righe
«diagramma assente o non utilizzabile» — il modello aveva prodotto un diagramma
su quattro. Non era un guasto dell'app (l'avviso era l'app che diceva la verità),
ma il risultato mancava lo stesso.

Causa: i quattro diagrammi sono l'ultima cosa che il contratto chiede, dopo
dodici sezioni, ed è il punto in cui i modelli mollano. Con un aggravante mio,
vedi E1.

| # | Modifica | Perché |
|---|---|---|
| E1 | **I quattro campi Mermaid sono ora obbligatori nello schema di Gemini.** Erano rimasti fuori da `required`. | Ometterli era formalmente legittimo: il modello che si stancava non stava violando niente. Ora deve almeno dichiarare una lista vuota, e una lista vuota è un fatto che l'app sa gestire. |
| E2 | **Nuovo `diagrams.py`: i quattro diagrammi si costruiscono dai dati.** `call graph` = `dependencies`, `application map` = `application_mapping` (o `interfaces`), `data flow` = `data_flows` (o `data_objects`), `process flow` = `business_processes` (trigger → processo → esito, con i componenti coinvolti appesi). | Quei disegni non contengono niente che non sia già nelle tabelle. Chiederli al modello è chiedergli di ridisegnare a mano una cosa che abbiamo già in forma strutturata — e infatti a volte tornava con nodi che nelle tabelle non esistono. |
| E3 | **Si costruiscono DOPO l'unione con l'analisi statica.** | Così il call graph contiene anche le dipendenze trovate dal parser, non solo quelle viste dal modello. |
| E4 | **Il disegno del modello non viene buttato.** Se ha prodotto qualcosa di sostanzioso (almeno tre righe) resta lui; sotto quella soglia si mostra quello costruito dai dati. Entrambe le versioni restano nel risultato. | Sul process flow il modello dà davvero qualcosa in più: sa mettere i passi in ordine. Sugli altri tre, quello costruito dai dati è normalmente migliore. |
| E5 | **Interruttore in interfaccia** (*From the model* / *Built from the tables*) quando esistono tutte e due. | La scelta dev'essere reversibile da chi guarda, non decisa una volta per tutte dal codice. |
| E6 | **Bottone «Rebuild from the current tables».** | È il punto vero: prima lo SME cancellava una dipendenza sbagliata e il diagramma continuava a mostrarla. Il documento firmato conteneva due verità diverse. |
| E7 | **Tetti e sfoltimento**: massimo 40 archi, 8 processi, etichette a 44 caratteri, e una riga «… e altri N non mostrati». Quando le dipendenze eccedono, le `PROBABLE_CALL` e le confidenze basse sono le prime a uscire. | Un diagramma con duecento archi non documenta niente. Meglio venti archi veri e la dichiarazione di quanti ne restano fuori. |
| E8 | **Nodi sempre validi per costruzione**: id ripuliti e unici, mai a cominciare per cifra, etichette senza `( ) [ ] { } " ; \|`, tutti rettangoli. | Sono esattamente gli errori che facevano fallire il disegno quando il mermaid lo scriveva il modello. |
| E9 | **Un diagramma che non si costruisce non fa cadere l'analisi** (eccezione catturata per diagramma). | — |
| E10 | **Avvisi di contratto tradotti in inglese**, come il resto dell'interfaccia, e più precisi: distinguono «non consegnato» da «troppo scarno» da «né il modello né le tabelle bastano». | Erano in italiano dentro un'interfaccia inglese — è la riga che ha visto il collega. |
| E11 | **Undici casi in più nel collaudo**, incluso quello che riproduce la segnalazione: modello che consegna un diagramma su quattro. | — |

---

## Cosa NON è stato cambiato

- La struttura di `exporter.py` (PDF e Word): correzioni chirurgiche soltanto
  (C2, C4, D1, D10, D11). Impaginazione, stili e sezioni sono rimasti quelli.
- **Le chiavi restano nella barra laterale**: è un prototipo, va bene così. Da
  rivedere solo se l'app viene esposta a più utenti.
- **`Quality first` resta il predefinito**: la catena parte dai modelli grandi.
  `Speed / cost first` è lì per chi vuole la regola di Nuvia.
- L'interfaccia resta in inglese; i commenti dei file nuovi sono in italiano,
  come in Nuvia.
- L'analisi statica (sqlglot + espressioni regolari) resta l'ancora dei fatti:
  nessuna delle modifiche la sostituisce con il modello.
- Il modello continua a essere interrogato sui diagrammi: la costruzione dai
  dati è una rete, non un rimpiazzo.

## Dipendenze

Python: `streamlit`, `streamlit-mermaid`, `sqlglot`, `pandas`, `requests`,
`reportlab`, `python-docx`. Tolti `openai`, `anthropic`, `google-genai`.

Fuori da Python, facoltativo ma consigliato:
`npm install -g @mermaid-js/mermaid-cli`.
