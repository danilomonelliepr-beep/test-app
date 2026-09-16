# Modifiche — Legacy Application Knowledge Extractor

Versione contratto JSON: **2.1** · Collaudo: `python test_catena.py` → 155/155 · Aggiornato al 16 settembre 2026

Dodici blocchi, in ordine cronologico: **A** la catena modelli presa da Nuvia, **B** il contratto JSON,
**C** difetti trovati per strada e robustezza, **D** i diagrammi (disegno locale e
correzione dello schiacciamento nel PDF), **E** i diagrammi mancanti, **F** i limiti dichiarati nella guida,
**G** velocità e provenienza dei diagrammi,
**H** gli id che facevano esplodere il disegno,
**I** interfaccia e accessibilità,
**J** i documenti,
**K** avvio e installazione,
**L** i limiti dichiarati, chiusi,
**M** il controllo generale,
**N** il secondo controllo,
**O** i formati accettati,
**P** la velocità,
**Q** le risposte a metà,
**R** la guida,
**S** la scelta del modello,
**T** le vie d'uscita da una risposta a metà,
**U** file di versioni diverse,
**V** tre difetti visti in produzione,
**Z** i campi senza bordo e il tema che non arrivava,
**AA** la barra laterale semplificata,
**AB** il tema senza cartella nascosta.

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
| C15 | **Collaudo automatico `test_catena.py`** — 155 casi, nessuna rete, nessuna chiave, nessun costo: scoperta, scalata, memoria, messaggi, tetti, riparazione JSON, enum, Mermaid, lotti. | Porting del collaudo di Nuvia. È il modo per cambiare una regola e sapere subito cosa si rompe. |
| C16 | **`requirements.txt`**: tolti `openai`, `anthropic`, `google-genai`; `requests` è ora una dipendenza dichiarata dell'app, non solo dell'esportatore. | Vedi A16. Tre dipendenze pesanti in meno da aggiornare e da far passare in azienda. |
| C17 | **README vero** (prima conteneva la parola «Ciao») e questo elenco. | — |

---

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

## F · I limiti dichiarati nella guida, chiusi

Tre dei limiti elencati in fondo a `GUIDA.md` erano risolvibili. Lo sono.

| # | Modifica | Perché |
|---|---|---|
| F1 | **Passata di consolidamento fra lotti.** Quando i lotti sono più di uno, una chiamata finale che riceve **solo l'inventario** (nessun codice sorgente) produce una sintesi unica dell'intera applicazione e cerca i collegamenti che nessun lotto poteva vedere. Costa poche migliaia di token contro le centinaia di migliaia dell'analisi. | I lotti non si vedevano fra loro: ognuno scriveva la propria sintesi come se fosse tutta l'applicazione, e una dipendenza fra un file del lotto 1 e uno del lotto 3 non la guardava nessuno. |
| F2 | **Ogni nome tornato dal consolidamento viene verificato** contro l'inventario: se anche un solo capo del collegamento non esiste, la riga si butta e si scrive che si è buttata. | In quella chiamata il modello non ha il codice davanti: un nome inventato non lo smentirebbe nessuno. È il punto del progetto in cui l'invenzione sarebbe più facile e meno verificabile. |
| F3 | **Il consolidamento che fallisce non fa perdere l'analisi**: si tengono le sintesi per lotto e lo si dichiara negli avvisi. | Una visione d'insieme mancante è un peccato; tre minuti di analisi persi per una chiamata accessoria sarebbero un difetto. |
| F4 | **I diagrammi si rifanno dopo il consolidamento.** | I collegamenti fra lotti sono archi nuovi del call graph — cioè esattamente quello che prima non si vedeva. |
| F5 | **Le PROBABLE_CALL vengono risolte contro l'indice dei componenti di TUTTA la codebase**, non solo del file corrente. Tre esiti: dichiarata da qualche parte → diventa `CALL` a confidenza `HIGH`; nome di libreria o troppo corto → si butta; nient'altro → resta `PROBABLE_CALL` ma a confidenza `LOW`, con scritto che punta fuori dal perimetro. | Prima una chiamata fra due file era indistinguibile dal rumore: entrambe `PROBABLE_CALL` a `MEDIUM`. Ora la dipendenza vera fra `fatt.pkb` e `sconti.pkb` è certa e il rumore è sparito. |
| F6 | **Lista di ~120 nomi di libreria** (Java, Python, JavaScript, generici) esclusi alla fonte. Non contiene i package Oracle tipo `UTL_FILE` o `DBMS_SQL`: quelle sono dipendenze reali. | `string`, `logger`, `append`, `println` non sono componenti dell'applicazione. |
| F7 | **`new Cliente(...)` non è più una chiamata a procedura.** | Il pattern generico non distingue una costruzione di oggetto da una chiamata; i cinque caratteri prima sì. |
| F8 | **CORRETTO: il pattern `JAVA_METHOD` fabbricava componenti fantasma.** Aveva `\s` fra le alternative dei modificatori, quindi bastava uno spazio per farlo scattare: in un PL/SQL, `BEGIN CALC_SCONTO(x)` registrava `CALC_SCONTO` come metodo Java. Ora servono `public`/`private`/`protected`. | Componenti inesistenti nelle tabelle e nel PDF — e, peggio, dentro l'indice usato per risolvere le chiamate, dove facevano **sparire** le dipendenze vere: la procedura era «già dichiarata qui», quindi la chiamata non veniva registrata. Difetto ereditato dalla versione originale. |
| F9 | **Il conteggio della risoluzione finisce nei metadati e in interfaccia**: quante risolte, quante fuori perimetro, quante buttate. | Chi legge la mappa delle dipendenze deve sapere quanta parte è certa e quanta è un sospetto. |
| F10 | **La «Coverage %» è sparita.** Al suo posto: *Files described* (quota dei file citati da almeno una riga) e un pannello con righe totali, quota con evidenza, quota ad alta confidenza, chiamate non risolte, sezioni riempite, **e l'elenco dei file che nessuna riga menziona**. | La vecchia percentuale contava quante delle sei sezioni non erano vuote: un'applicazione descritta con una riga per sezione dava 100%. Un numero così, grande in cima alla pagina, non è ottimista — è fuorviante, e qualcuno lo mette in una slide. Nessuna misura automatica può dire quanta parte di un'applicazione è stata catturata; si può però misurare quanto è solido quello che c'è. |
| F11 | **Tredici casi in più nel collaudo**, compresi il collegamento inventato che dev'essere buttato e il componente fantasma che non deve più nascere. | — |

### Cosa resta aperto, e perché

- **Il process flow del modello resta migliore del nostro** quando lui lo
  produce: sa mettere i passi in ordine di esecuzione, cosa che dalle tabelle
  non si ricava. Non è un difetto da chiudere — è il modello che aggiunge
  valore dove sa aggiungerlo, e infatti il suo disegno viene tenuto.
- **Le chiamate fuori perimetro restano un sospetto.** Distinguere una chiamata
  vera da un cast o da un costruttore in ogni linguaggio richiede un parser per
  linguaggio, non un'espressione regolare. Ora però sono marcate `LOW` e
  contate, quindi si sa quanto pesano.

---

## G · Velocità di risposta e falso allarme sui diagrammi

Due segnalazioni dal campo: «ci mette minuti anziché secondi» e un avviso su
`mermaid_call_graph` letto come un errore.

| # | Modifica | Perché |
|---|---|---|
| G1 | **Selettore «Reasoning effort» nella barra laterale**: Fast · Balanced · Thorough · Deep. Tradotto per provider: `thinkingLevel` su Gemini, `thinking` con budget su Anthropic, `reasoning_effort` su Azure/OpenAI. | È la leva che sposta di più il tempo di risposta, molto più della scelta fra un modello e l'altro: lo stesso flash col ragionamento alto impiega minuti dove col basso impiega secondi. Prima non c'era: si prendeva il valore di serie del provider, che sui modelli nuovi è alto. |
| G2 | **Il livello è un punto di partenza, non un ordine.** Alcuni modelli rifiutano i livelli bassi con un 400 (il 3.8 non scende sotto medium). L'app legge il corpo dell'errore, **sale di un gradino**, ricorda il minimo per QUEL modello e riprova. La volta dopo parte già giusta. | Chi sceglie «Fast» ottiene il più veloce che quel modello sa fare, non un errore. È lo stesso meccanismo del `thinkingLevel` di Nuvia, esteso ai tre provider. |
| G3 | **Un adattamento non consuma i tentativi.** La scala ha tre gradini: con due soli tentativi non ci si arriva in cima. Ora gli adattamenti hanno un contatore separato (3 nella prova, 4 nella chiamata vera). | Il tentativo dopo un adattamento è una richiesta *diversa*, non la ripetizione di una fallita: consumare la seconda chance che serve ai guasti veri era sbagliato. |
| G4 | **La prova di contatto usa sempre il livello più basso.** | È una domanda da due parole: farla pensare vanificherebbe il tetto dei cinque secondi che la prova esiste per rispettare. |
| G5 | **Su Anthropic il ragionamento esteso disattiva il prefill `{`** e alza `max_tokens` sopra il budget di pensiero. | Le due cose non convivono, e il budget si scala da `max_tokens`: senza alzarlo il modello pensa e non gli resta spazio per scrivere. |
| G6 | **Su Azure `reasoning_effort` si manda solo ai modelli che ragionano** (`o…`, `gpt-5`, nomi con «reason»), con l'adattamento come rete. | Mandarlo a un `gpt-4o` costa un 400 e un giro a vuoto ogni volta. |
| G7 | **Tempo visibile**: secondi trascorsi nella barra di avanzamento, durata totale e livello di ragionamento usato nella scheda Overview. | Un'analisi vera dura minuti. Una barra ferma senza numeri sembra bloccata — ed è così che nasce «ci mette troppo». |
| G8 | **«Diagramma costruito dai dati» non è più un avviso di contratto.** La provenienza si dice accanto al disegno, nella scheda Diagrams; nel pannello degli avvisi resta solo il caso vero: nessun diagramma disponibile da nessuna delle due parti. | Nel pannello «what the app had to fix» sembrava un errore, e infatti è stato segnalato come tale. Costruire il diagramma dai dati è il funzionamento previsto, non un guasto. |
| G9 | **Sei casi in più nel collaudo**: la scala che sale, il minimo ricordato, la prova che resta al livello più basso, la provenienza registrata fuori dagli avvisi. | — |

---

## H · «Cannot set properties of undefined (setting 'order')»

Segnalazione dal campo: il file `.mmd` esportato, aperto su mermaid.live, muore
con quell'errore. Il messaggio non nomina il nodo colpevole, e manda a cercare
ovunque tranne che nel posto giusto.

**La causa.** Mermaid tiene i nodi del grafo in un oggetto JavaScript normale,
usato come dizionario. Un nodo che si chiama `toLocaleString` non finisce in una
casella vuota: trova già lì la funzione che *ogni* oggetto JavaScript eredita dal
prototipo. La libreria conclude che il nodo esiste di già, prova a scrivergli
sopra la proprietà `.order` che serve al posizionamento, e muore.

Non è un caso di scuola. `toLocaleString`, `valueOf`, `toString`, `constructor`
sono metodi normalissimi in un sorgente JavaScript: l'analisi statica li trova
come chiamate, diventano righe di dipendenza, e da lì nodi del call graph.

| # | Modifica | Perché |
|---|---|---|
| H1 | **Ogni id generato nasce con il prefisso `n_`**, non solo quelli che cominciano per cifra. L'etichetta visibile resta il nome vero. | Elencare le parole da evitare è una rincorsa: un id che comincia per `n_` non può collidere con niente di JavaScript, oggi né alle prossime versioni. Il nodo diventa `n_toLocaleString["toLocaleString"]`: illeggibile per la macchina, identico per chi guarda. |
| H2 | **Anche il Mermaid scritto dal modello viene sanificato**: le proprietà del prototipo (`toString`, `valueOf`, `constructor`, `prototype`, `hasOwnProperty`, `__proto__`…) vengono rinominate dove compaiono come identificatori, in modo coerente su tutto il diagramma. | Il prefisso copre i disegni che costruiamo noi; questo copre l'altra metà. Erano due strade verso lo stesso renderer e andavano chiuse tutte e due. |
| H3 | **`end`, `subgraph`, `graph` NON vengono toccati.** | Lì la parola ha un significato nella sintassi di Mermaid: rinominarla romperebbe diagrammi validi. Le proprietà del prototipo invece per Mermaid non significano niente, quindi rinominarle è sempre sicuro. |
| H4 | **Le etichette sugli archi (`-->\|testo\|`) sono protette** come quelle dei nodi: si ripuliscono, non si sanificano. | Nel testo che si legge `toLocaleString` è la parola giusta. |
| H5 | **Otto casi in più nel collaudo**, compresi la rinomina coerente ai due capi di un arco, `subgraph`/`end` intatti e le frecce `--o` / `--x` che non devono essere scambiate per etichette. | — |

> La diagnosi che aveva trovato Danilo era giusta sulla causa. La soluzione
> proposta — aggiungere un prefisso e tenere una lista di parole da evitare —
> era però metà del lavoro: copriva i diagrammi generati dal codice ma non
> quelli scritti dal modello, e una lista di parole va aggiornata ogni volta
> che JavaScript ne aggiunge una. Qui il prefisso è sistematico e la lista
> serve solo per il testo che non possiamo prefissare.

---

## I · Interfaccia e accessibilità

L'interfaccia era quella di serie di Streamlit: nove schede tutte uguali,
tabelle senza intestazioni leggibili, nessuna idea di dove si fosse nel lavoro.
Il mestiere di questa applicazione però non è mostrare dati, è **far giudicare a
una persona delle righe prodotte da una macchina**: l'interfaccia deve dire
prima di tutto da dove viene ogni riga e quanto è solida.

### Il sistema visivo

| # | Modifica | Perché |
|---|---|---|
| I1 | **Nuovo `ui.py`**: token di colore e spaziatura, tema CSS, componenti (testata, cifre, intestazioni di sezione, marcatori, stato vuoto) e `.streamlit/config.toml` con gli stessi valori. | Un posto solo per il colore e la spaziatura. Se cambia lì, cambia ovunque. |
| I2 | **Carattere: IBM Plex Sans e IBM Plex Mono.** Il monospazio è riservato a ciò che è letterale — nomi di componenti, file, frammenti, numeri. | Non è un vezzo: questa applicazione documenta COBOL, RPG e PL/SQL, e Plex è il carattere dell'azienda le cui macchine fanno girare quella roba. E la differenza fra «testo scritto da qualcuno» e «stringa presa dal sorgente» si vede senza doverla leggere. |
| I3 | **Colore: inchiostro blu-nero su carta grigio-fredda, accento verde-petrolio.** L'accento dice solo dove si può agire, mai cosa significa. | Il significato sta nella scala di gravità, che è l'unica cosa calda della pagina: così l'occhio ci va subito, invece di doverla cercare in mezzo ad altri colori. |
| I4 | **I marcatori di provenienza**, coerenti ovunque: ■ Parser, □ Model, ●●● / ●●○ / ●○○ per la confidenza, ▲ ◆ • per la gravità. Con una legenda nella scheda Summary. | È l'unica cosa su cui l'interfaccia si permette di essere vistosa, ed è anche l'unica che porta informazione: quadrato pieno = fatto che il parser non può sbagliare, quadrato vuoto = lettura del modello, con la sua confidenza. |
| I5 | **Mai il colore da solo.** Ogni marcatore porta forma + parola + colore; gli enum nelle tabelle sono menù a tendina con la parola per esteso. | Un daltonico e uno schermo in bianco e nero devono leggere la stessa cosa. |
| I6 | **Nessuna animazione d'ingresso.** Le uniche transizioni rispondono a un gesto, e si spengono con `prefers-reduced-motion`. | Le entrate in dissolvenza su ogni sezione sono il tic dell'interfaccia generata, e qui si sta lavorando, non guardando una presentazione. |

### Il lavoro di chi valida

| # | Modifica | Perché |
|---|---|---|
| I7 | **Quante righe restano da guardare**, per sezione (barra) e in cima alla pagina (cifra «Rows checked»). | È dodici tabelle di lavoro: senza un avanzamento non si sa se manca un'ora o tre giorni, e non si sa dove riprendere dopo una pausa. |
| I8 | **Ricerca dentro la sezione** e filtro «solo le righe ancora da controllare». Con un filtro attivo le righe non si aggiungono né si tolgono, e la pagina lo dice. | Il vincolo non è pigrizia: le modifiche tornano al loro posto per posizione, e questo funziona solo se il numero di righe non cambia sotto le mani. Meglio un limite dichiarato di una perdita silenziosa. |
| I9 | **Gli enum sono menù a tendina**, non testo libero. | Finché `severity` si scriveva a mano, chi validava poteva metterci «molto alto» e il filtro per gravità smetteva di funzionare senza dirlo a nessuno. |
| I10 | **Ogni colonna porta la propria spiegazione** (in `help`), presa dal contratto — la stessa frase che legge il modello. | Non possono divergere, e nessuno deve indovinare cosa voglia dire `source_component`. |
| I11 | **Intestazioni di colonna leggibili** («File», «Kind», «Why it matters») al posto dei nomi di campo. | — |
| I12 | **Cifre di sintesi in cima**: file letti, regole di business (in rilievo), componenti, rischi gravi, righe controllate. | Le regole di business sono la sezione che ripaga l'esecuzione: è giusto che sia l'unica evidenziata. |
| I13 | **Stato vuoto che spiega e invita**, con i tre passi numerati. | Una schermata vuota è un invito ad agire, non un'alzata di spalle. I numeri ci stanno perché questa è una sequenza vera: senza chiave non si analizza, senza sorgenti non si esporta. |
| I14 | **Barra laterale in tre tappe** (Model · Source code · Run), con la verifica della connessione raccolta in un pannello. | Prima era un elenco piatto di controlli in cui non si capiva cosa fosse obbligatorio e in che ordine. |
| I15 | **Schede rinominate e raggruppate**: Summary · Business · Architecture · Data · Risks · Diagrams · For the expert · Parser evidence · Export. | «SME Validation» e «Static Evidence» sono nomi del sistema, non di chi lavora. |
| I16 | **Export come tre schede con una riga di spiegazione** l'una, invece di tre bottoni nudi. | Chi esporta deve sapere quale dei tre gli serve prima di premere. |
| I17 | **Testi riscritti**: verbi attivi, frasi in minuscolo, niente scuse negli errori. «The API key is missing. Add it under step 1 and run again.» invece di «Missing API Key». | Un errore dice cosa è successo e come si rimedia. |

### Accessibilità

| # | Modifica | Perché |
|---|---|---|
| I18 | **Contrasto**: inchiostro su carta 13:1, accento su bianco 5,6:1, ogni testo di stato oltre 4,5:1 sul proprio fondo. | AA superato ovunque, AAA sul testo corrente. |
| I19 | **Fuoco da tastiera sempre visibile**, contorno di 3px con scarto, su bottoni, campi, schede e caselle. | Si può percorrere tutta l'applicazione senza mouse e sapere sempre dove si è. |
| I20 | **Bersagli da 42px** su bottoni, schede ed espansori. | Sotto i 40px si sbaglia, col mouse e soprattutto col dito. |
| I21 | **Nessuna etichetta nascosta**: ogni controllo ha la sua, visibile, più un `help`. La colonna di spunta si chiama «Checked», non «✓». | Un lettore di schermo legge «Checked», non «segno di spunta». |
| I22 | **`prefers-reduced-motion` e `prefers-contrast: more`** rispettati (nel secondo caso bordi e testi secondari si scuriscono). | Sono preferenze di sistema che qualcuno ha impostato per un motivo. |
| I23 | **Adattamento a schermo stretto** sotto gli 880px. | — |
| I24 | **Tema scuro pronto** in `.streamlit/config.toml`, commentato. | — |

### Manutenzione

| # | Modifica | Perché |
|---|---|---|
| I25 | **I componenti nuovi verificano che Streamlit li sappia fare** (`segmented_control`, `toggle`, `container(border=…)`, `toast`): se manca, si ripiega su un controllo equivalente. | Un'installazione più vecchia perde un bordo, non una funzione. |
| I27 | **L'aspetto non dipende da una configurazione esterna.** Gli stessi colori vengono riapplicati ai controlli di Streamlit (cursori, caselle, interruttori, bordi di fuoco) via CSS, che viaggia dentro `ui.py`. Il file resta per il limite di caricamento e la barra strumenti. | Una cartella che comincia col punto è invisibile nel gestore file e viene saltata dal caricamento per trascinamento su GitHub: il progetto arrivava senza, partiva lo stesso, e mostrava l'accento rosso di serie che litiga con la scala di gravità. Un aspetto che dipende da un file nascosto è una dipendenza fragile. |
| I28 | **`ui.tema_configurato()`** dice se le impostazioni di Streamlit sono quelle nostre. | Evita mezz'ora di dubbi a chi lancia `streamlit run app.py` a mano e trova qualcosa fuori posto. |
| I29 | **Nuovo `verifica.py`**: dopo un clone dice in dieci righe cosa manca e come si rimedia — file, cartelle nascoste, pacchetti, chiavi, versione di Python. Per i diagrammi **disegna davvero** un diagramma da due nodi invece di controllare che il comando esista. | `mmdc` può essere installato e non disegnare, perché gli manca il browser che si porta dietro: il comando c'è, la verifica diceva «ok», e il difetto saltava fuori dentro un'esportazione. |
| I30 | **`fonts/LICENSE.txt` e `fonts/README.md`.** IBM Plex è SIL Open Font 1.1: si ridistribuisce anche in un progetto commerciale, ma la licenza deve viaggiare con i file. | Ridistribuire font senza la licenza è un problema legale, non una svista di forma — e in un repository aziendale è il tipo di cosa che qualcuno controlla. |
| I26 | **`use_container_width` sostituito con `width="stretch"`**, deciso guardando la firma vera della funzione invece del numero di versione. | Il vecchio nome è in via di rimozione e riempiva la console di avvisi. Guardare la firma funziona anche sulle versioni in mezzo. |

---

## J · I documenti (PDF e Word), rifatti

È il PDF, non l'applicazione, quello che finisce in mano al cliente. Era rimasto
com'era mentre tutto il resto cambiava. `exporter.py` è riscritto.

### Struttura

| # | Modifica | Perché |
|---|---|---|
| J1 | **Una sola descrizione, due rese.** `prepara()` costruisce l'elenco dei blocchi del documento; PDF e Word si limitano a disegnarlo. | Prima erano due funzioni lunghe e parallele: ogni aggiunta andava fatta due volte, e avevano già smesso di dire le stesse cose. |
| J2 | **Copertina** con quanto è stato letto, chi ha risposto, quante righe ci sono, quante hanno un riscontro nel codice, quante sono ad alta confidenza, **quante ha confermato un esperto**, quanti rischi gravi. | Chi riceve il documento deve sapere su cosa sta mettendo il nome prima di leggere la prima riga. |
| J3 | **«How to read this document»**: la legenda di provenienza, confidenza, conferma e gravità, in copertina. | La distinzione fra fatto e lettura è il perno di tutto il progetto e non era scritta da nessuna parte nel documento. |
| J4 | **Indice** delle otto sezioni. | — |
| J5 | **Nuova sezione 7, «Open questions and assumptions»**: le domande per l'esperto e le assunzioni. | Erano nel contratto, erano nell'applicazione, e nel documento non arrivavano affatto. È la parte più utile per chi deve validare. |
| J6 | **Numerazione cambiata**: §7 «Static Code Evidence» diventa **§8 «Appendix: what the parser found»**, con l'inventario e i conteggi della risoluzione delle chiamate. Le sezioni da 1 a 6 restano dov'erano. | Chi cita «sezione 7» nei propri documenti deve saperlo: è l'unico spostamento. |
| J7 | **Piè di pagina** con titolo e numero di pagina. | — |

### Contenuto delle tabelle

| # | Modifica | Perché |
|---|---|---|
| J8 | **La provenienza si vede**: colonna «Found by» con `parser` o `model`. | Prima un fatto del parser e un'ipotesi del modello erano due righe identiche. |
| J9 | **La confidenza è un conteggio di puntini** (`•••` `••·` `•··`) invece di una parola in maiuscolo. | Si confronta con l'occhio scorrendo la colonna, e si legge anche stampata in bianco e nero. |
| J10 | **CORRETTO: `source` significava due cose diverse** e il documento ne mostrava una sola. In `components` e `technical_risks` è la provenienza; in `dependencies` e `data_flows` è l'origine della dipendenza. Il documento scriveva «Found by» su entrambe e trasformava `PKG_BILLING` in `pkg_billing`. Ora lo decide il contratto — nel primo caso il campo ha valori ammessi, nel secondo no. | Difetto trovato guardando il PDF generato, non il codice. Un nome di package abbassato di maiuscole in un documento di consegna è un errore che il cliente nota. |
| J11 | **Rischi e impatti ordinati per gravità**, più alta per prima. | Un CRITICAL trentesimo, dopo ventinove LOW, è un CRITICAL che nessuno legge. Prima non si poteva ordinare: la gravità era testo libero. |
| J12 | **Dipendenze ordinate per affidabilità**: prima le `CALL` certe, poi i `PROBABLE_CALL`. | L'ordine dice già quanto fidarsi, senza leggere colonna per colonna. |
| J13 | **Gravità con fondo tinto e parola per esteso.** | Il colore rinforza, la parola porta il significato: si stampa in bianco e nero e si legge uguale. |
| J14 | **Le colonne vuote in tutte le righe spariscono.** | Non sono informazione: sono spazio tolto alle colonne che contano. |
| J15 | **`evidence` esce dalle tabelle** (resta nell'applicazione e nel JSON). | In una tabella a nove colonne rendeva illeggibile tutto il resto. |
| J16 | **Intestazioni leggibili** e monospazio sui valori letterali (id, file, componenti). | Le stesse etichette dell'applicazione: chi passa dall'una all'altro ritrova le stesse parole. |

### Aspetto

| # | Modifica | Perché |
|---|---|---|
| J17 | **IBM Plex Sans e Mono nel PDF**, gli stessi dell'applicazione. I quattro file sono in `fonts/` (licenza OFL, ridistribuibili). Se la cartella manca si scende su Helvetica senza rumore. | Il documento e l'applicazione devono sembrare la stessa cosa. |
| J18 | **Niente simboli geometrici.** IBM Plex non ha ■ □ ● ○ ▲, e in un PDF un glifo mancante diventa un rettangolo nero. Verificato sulla tabella dei caratteri del font, non dato per buono: la confidenza usa `•` e `·`, la provenienza una parola. | — |
| J19 | **Colori dei token**, intestazioni di tabella verde-petrolio, righe alternate, filetti sottili. | — |
| J20 | **Word: stessi caratteri, stesse tinte, stesso ordine.** Se IBM Plex non è installato sulla macchina di chi apre il file, Word ricade sul carattere di sistema: la struttura resta, cambia la faccia. | È un limite di Word, non aggirabile senza incorporare i font nel documento. |
| J21 | **Tabelle allineate a sinistra.** | ReportLab le centra di serie: in un documento allineato a sinistra galleggiavano in mezzo alla pagina. |
| J22 | **Undici casi in più nel collaudo**: ordinamento, le due accezioni di `source`, i puntini, le otto sezioni, e che PDF e Word si costruiscano davvero. | — |

---

## K · Avvio, installazione, e un'icona che fermava l'analisi

| # | Modifica | Perché |
|---|---|---|
| K1 | **CORRETTO: «The analysis stopped: The value "✓" is not a valid emoji».** L'avviso di fine analisi passava un segno di spunta tipografico (U+2713) come icona a `st.toast`, che valida l'icona come emoji vera e alza un'eccezione. L'eccezione veniva raccolta dal `except` dell'analisi e compariva come se l'analisi fosse fallita — mentre era finita bene ed era già salvata. Ora l'avviso non ha icona, e qualunque errore nel mostrarlo viene ignorato. | Un avviso di cortesia non deve poter far fallire tre minuti di lavoro, né far credere che siano andati persi. |
| K2 | **Niente più cartelle nascoste: `.streamlit/` è sparita.** Le stesse impostazioni (tema, limite di caricamento a 50 MB, barra strumenti ridotta) le passa `avvia.py` come opzioni della riga di comando. | Una cartella che comincia col punto è invisibile nel gestore file e sparisce copiando il progetto per trascinamento. Ora la configurazione è in un file normale, che si vede e si legge. |
| K3 | **Opzioni, non variabili d'ambiente.** Le variabili equivalenti esistono, ma Streamlit le legge solo quando avvia il server: provate altrove non hanno effetto. | Una configurazione che funziona «solo qualche volta» è peggio di una che manca. Verificato: le opzioni vengono accettate, le variabili in un interprete normale no. |
| K4 | **Nuovo `avvia.py`: un comando solo.** Controlla i pacchetti Python e li installa, controlla mermaid-cli e lo installa, imposta Streamlit, apre l'applicazione. | Su una macchina pulita `python avvia.py` basta. Le due cose che non possono stare nel repository se le prende da sé. |
| K5 | **Installa alla luce del sole.** Ogni comando viene stampato prima di essere eseguito; l'installazione Python va nell'interprete corrente, quindi dentro il virtualenv se ce n'è uno attivo; `--niente-installazioni` fa girare solo i controlli. | Installare pacchetti di nascosto tocca l'ambiente di chi lancia il comando, e se quell'ambiente è condiviso il danno non è suo. |
| K6 | **mermaid-cli si installa accanto al progetto, non globalmente.** `mermaid_render` lo cerca anche in `node_modules/.bin`. | `npm install -g` chiede i permessi di amministratore, che su una macchina aziendale spesso non ci sono. Così non servono. |
| K7 | **Se manca il browser, `avvia.py` lo scarica** (`npx puppeteer browsers install chrome-headless-shell`) e riprova. | `mmdc` può essere installato e non disegnare: è il caso che prima passava inosservato fino a un'esportazione. |
| K8 | **`verifica.py` non installa niente.** Resta separato per guardare com'è messa una macchina senza toccarla: un server di qualcun altro, un ambiente condiviso, un controllo prima di un'installazione. | — |
| K9 | **CORRETTO: le etichette che uscivano dalle caselle.** Con `htmlLabels: true` Mermaid disegna il testo dei nodi dentro un `foreignObject`, cioè HTML vero dentro l'SVG, ma dimensiona il riquadro PRIMA, misurando il testo con il carattere che crede di avere. In un browser headless quel carattere spesso non c'è: si misura con uno, si disegna con un altro, e il testo esce dalla casella. Ora `htmlLabels: false`, con un carattere presente ovunque e una larghezza di ritorno a capo dichiarata. | È il difetto dei diagrammi con le etichette su due righe dentro riquadri alti una riga. Con le etichette SVG, Mermaid misura con lo stesso motore con cui disegna, e la casella viene della misura giusta. |
| K10 | **La configurazione viaggia dentro il diagramma** (`%%{init: …}%%` in testa, aggiunta al momento del disegno). | Il file di configurazione locale vale solo per `mmdc`. Il servizio esterno riceve **solo il codice**: ecco perché quei diagrammi uscivano col tema di serie e le etichette fuori posto anche dopo aver sistemato la configurazione. Scritta dentro, vale in locale, sul servizio, e anche se qualcuno incolla il codice su mermaid.live. |
| K11 | **Le direttive `%%{…}%%` sono protette dalla pulizia** delle etichette, e un'intestazione mancante si inserisce dopo, non prima. | Le graffe di una direttiva sono JSON: messe fra virgolette come se fossero un'etichetta rompono la configurazione. E un `flowchart TD` messo sopra la direttiva rompe il diagramma. |
| K12 | **Bottone «Install what's missing»** nella barra laterale, sotto *Dependencies*, con lo stato del disegno locale scritto sopra. Lancia lo stesso `avvia.py --solo-preparazione` della riga di comando. | Nessuna logica di installazione duplicata dentro l'app che poi si allontana da quella vera. E chi usa l'applicazione non deve aprire un terminale. |
| K13 | **La prova del disegno sta in un posto solo** (`mermaid_render.prova_locale()`), usata da app, avvio e verifica. | Tre posti che rispondono alla stessa domanda devono rispondere allo stesso modo. |
| K14 | **`fonts/LICENSE.txt`** resta: IBM Plex è SIL Open Font 1.1, si ridistribuisce anche in un progetto commerciale purché la licenza viaggi con i file. | — |

---

## L · I limiti dichiarati nella guida, chiusi

Contratto JSON: **2.1** (era 2.0 — vedi L7).

| # | Modifica | Perché |
|---|---|---|
| L1 | **In Python le chiamate si leggono dall'albero sintattico** (`ast`, libreria standard, nessuna dipendenza in più): nodi `Call` veri, con l'elenco di cosa è definito nel file per escluderlo. Quando l'albero c'è, il pattern generico non gira affatto. | L'espressione regolare «identificatore seguito da parentesi» non distingue una chiamata da un cast, da un costruttore o da una parentesi qualsiasi: produceva righe a confidenza MEDIA che qualcuno doveva controllare a mano. L'albero sa che quello È un nodo Call: confidenza ALTA, nessuna verifica. |
| L2 | **In SQL e PL/SQL l'albero di sqlglot CONFERMA, non sostituisce.** I nomi che riconosce come chiamate non standard promuovono i riscontri dell'espressione regolare da sospetto a certezza. | Su un package PL/SQL vero sqlglot non arriva in fondo: quello che non capisce diventa un nodo `Command` e sparisce dall'albero. Usarlo come unica fonte faceva **perdere** chiamate che l'espressione regolare vedeva benissimo — un passo indietro travestito da passo avanti. Trovato provando, non ragionando. |
| L3 | **Due assi separati: «è una chiamata» e «il bersaglio è nel perimetro».** Confermata e dichiarata → `CALL` / HIGH. Confermata ma fuori dal codice caricato → `CALL` / MEDIUM. Né l'una né l'altra → `PROBABLE_CALL` / LOW. | Prima la conferma dell'albero scavalcava anche il filtro del rumore, e `System.out.println` rientrava come chiamata certa. Sono due domande diverse e vanno risposte separatamente. |
| L4 | **I lotti seguono il grafo delle dipendenze**, non l'ordine di dimensione. I file che si chiamano fra loro vanno nello stesso lotto quando ci stanno; un gruppo più grande di un lotto viene spezzato, ma mai un file. | Prima due file legati finivano separati per puro ordine alfabetico, e il loro collegamento non lo vedeva nessuno: al consolidamento arriva solo l'inventario, da cui si può indovinare ma non vedere. Il buco non sparisce, si stringe molto. |
| L5 | **Nuovi indicatori: quanto dei FATTI DEL PARSER è stato descritto.** Quanti dei componenti dichiarati compaiono in almeno una riga del modello, quante delle tabelle trovate sono descritte. | Quanta parte di un'applicazione sia stata capita non lo può dire nessuno — servirebbe conoscere in anticipo la risposta. Ma i fatti del parser sono verità nota, e chiedersi quanti ne sono stati descritti è una domanda vera con una risposta vera. |
| L6 | **I file muti vengono segnalati**: quelli che contengono IF, CASE o WHEN e non hanno prodotto nemmeno una regola di business. | È il segnale più forte che l'applicazione sa dare su sé stessa. Un file pieno di condizioni da cui non esce nessuna regola è quasi sempre un file che il modello ha saltato, e vale un secondo passaggio su quello solo. |
| L7 | **Contratto 2.1: `business_processes.steps`**, i passi in ordine di esecuzione. Il diagramma costruito dai dati li incatena nell'ordine dato. | L'ordine di esecuzione è la sola cosa che il modello sa e che dalle tabelle non si ricava: era il motivo per cui il suo disegno restava migliore del nostro. Chiedendolo come dato diventa una riga che l'esperto può correggere, invece di stare dentro un disegno che nessuno può validare — e il disegno si rifà dopo le correzioni. |
| L8 | **Il Word usa Arial e Courier New**, non più IBM Plex. Il PDF resta su Plex. | Word non incorpora i caratteri se non in un formato offuscato che alcune installazioni aziendali rifiutano, e che gonfia ogni documento di 700 KB. Il risultato sarebbe un documento che si apre bene da noi e con un carattere di ripiego dal cliente: **imprevedibile**, che per un documento di consegna è la cosa peggiore. Due caratteri presenti ovunque danno un documento identico dappertutto. Nel PDF il problema non c'è: i font sono dentro il file. |
| L9 | **Una rotella che gira mentre il modello lavora.** `st.status` con l'etichetta che cambia a ogni lotto, i secondi trascorsi, i file in lavorazione e le ultime righe del diario; alla fine diventa un riepilogo richiuso. Anche la prova di connessione ha la sua. | Un'analisi vera dura minuti. Senza qualcosa che si muove la pagina sembra bloccata, la gente ricarica, e il lavoro fatto fin lì se ne va. |
| L10 | **Quindici casi in più nel collaudo**, compresi il file Python illeggibile che non deve far saltare nulla e la chiamata che l'albero SQL non vede e che non deve andare persa. | — |

### Cosa resta aperto

- **Java, COBOL e RPG restano sull'euristica.** Lì un albero sintattico vorrebbe
  un parser per linguaggio, che è un progetto a sé. Le righe restano marcate e
  contate per quello che sono.
- **Il consolidamento vede l'inventario, non il codice.** Ora però i lotti sono
  formati meglio, quindi ha molto meno da recuperare.

---

## M · Controllo generale (12 settembre 2026)

Lo zip è stato spacchettato in una cartella vuota e tutto è stato fatto girare
da lì, come farebbe chi lo riceve: collaudo, verifica, avvio, analisi statica,
pagina intera contro Streamlit reale, PDF e Word. Poi analisi statica del codice
con pyflakes e confronto fra documenti e file reali.

| # | Trovato | Sistemato |
|---|---|---|
| M1 | Le etichette fisse dei diagrammi costruiti dai dati erano in italiano («Questa applicazione», «e altri N non mostrati») dentro documenti in inglese. | Tradotte. I commenti nel codice restano in italiano. |
| M2 | La tabella dei file in `GUIDA.md` e in `README.md` non elencava `ui.py`, `fonts/`, `avvia.py` e `verifica.py`. | Complete, e coerenti fra loro. |
| M3 | L'intestazione di questo file diceva ancora contratto 2.0 e «quattro blocchi». | 2.1, dodici blocchi. |
| M4 | Una variabile e tre import inutilizzati (segnalati da pyflakes). | Rimossi; pyflakes ora tace. |
| M5 | `markdown` è usato solo da `guida_pdf.py` e non è in `requirements.txt`. | Scelta confermata: è uno script di servizio, e il README dice cosa installare per usarlo. |

Nessun residuo nel pacchetto (`__pycache__`, `node_modules`, cache della
catena), nessun riferimento a cose rimosse, nessun testo in italiano
nell'interfaccia, dipendenze dichiarate uguali a quelle usate.

---

## N · Secondo controllo generale: quello che il primo non copriva

Non una ripetizione: tre percorsi che nessun collaudo aveva mai fatto girare
per intero.

| # | Cosa | Esito |
|---|---|---|
| N1 | **L'orchestrazione completa** — lotti → modello → JSON → normalizzazione → unione → consolidamento → statica → diagrammi — con un provider finto, a uno e a tre lotti. | Corretta: una prova di contatto, tre analisi, un consolidamento; id unici fra i lotti; il collegamento fra lotti accettato; le sintesi per lotto sostituite da quella d'insieme. |
| N2 | **L'installazione vera dei pacchetti Python** con `avvia.py` in un ambiente virtuale vuoto. | Corretta: `pip` li ha installati, e il collaudo è passato nell'ambiente appena riempito. |
| N3 | **L'installazione locale di mermaid-cli** con `npm`, accanto al progetto. | Corretta: `node_modules/.bin/mmdc` compare e `mermaid_render` lo trova. |

E due difetti veri, trovati per strada.

| # | Trovato | Sistemato |
|---|---|---|
| N4 | **Il lavoro dell'esperto viveva solo nella sessione del browser.** Chiusa la scheda, spunte e correzioni erano perse. C'era il download del JSON ma **nessun modo di ricaricarlo** — e la guida diceva che «i JSON della 2.0 si aprono», il che era falso: non esisteva niente che li aprisse. | Nuovo pannello **«Or resume a saved analysis»** sotto il passo 2. Il JSON esportato ora porta con sé anche i metadati del parser e chi ha risposto; ricaricandolo si riprende da dove si era, spunte comprese. I file della versione 2.0 (senza `steps`, con le domande a stringhe) passano dal contratto e salgono alla 2.1. Un file caricato viene letto **una volta sola**: il caricatore resta pieno a ogni giro della pagina, e rileggerlo ogni volta avrebbe cancellato le spunte messe dopo. |
| N5 | **Il comando che scaricava il browser per mermaid-cli era sbagliato due volte.** La sintassi era rifiutata (stampava l'aiuto), e comunque prendeva un puppeteer diverso da quello di mermaid-cli, quindi scaricava Chrome 131 dove serve la 152: anche riuscendo, `mmdc` non avrebbe trovato il browser. | Ora si usa l'installatore di puppeteer **stesso**, quello dentro `node_modules`: è l'unico che conosce la versione esatta che pretende. Provato: ora fallisce solo per la rete (bloccata nell'ambiente di sviluppo), non per il comando. Il messaggio finale spiega le due vie d'uscita: `PUPPETEER_EXECUTABLE_PATH` verso un Chrome già installato, o `MERMAID_LOCAL_ONLY=1`. |
| N6 | Con un JSON ricaricato senza metadati, due cifre in testa alla pagina esplodevano (`metadata['file_count']`). | `.get` con un trattino al posto del numero. La pagina intera gira anche da un file vecchio senza metadati. |
| N7 | **Sei casi in più nel collaudo** sul ricaricamento. | 108 in tutto. |

---

## O · I formati accettati (segnalazione: «non riconosce i .vb»)

Il caricatore aveva un elenco fisso di estensioni, e `.vb` non c'era. La
correzione giusta non era aggiungerlo all'elenco: era smettere di rifiutare
file. Un estrattore per il legacy non può sapere in anticipo cosa gli arriverà.

| # | Modifica | Perché |
|---|---|---|
| O1 | **Il caricatore accetta qualunque file.** L'elenco delle estensioni serve ora solo a dire al modello che linguaggio sta leggendo; un'estensione ignota entra lo stesso, marcata «Unknown (.xyz)». | Il modello riconosce il linguaggio dal contenuto: è la cosa che gli riesce meglio. Respingere un file per il nome è tenere fuori un'informazione per un dettaglio. |
| O2 | **I binari vengono respinti con un motivo e un rimedio** (un byte nullo nei primi 8 KB). | Un `.dll` o un `.fmb` decodificato a forza è spazzatura mandata a pagamento al modello. Il messaggio dice di esportare il sorgente come testo. |
| O3 | **Ottanta estensioni riconosciute**, non venti: tutte le vite di Visual Basic (`.vb`, `.bas`, `.frm`, `.cls`, `.ctl`, `.vbs`, `.asp`), i dialetti PL/SQL (`.prc`, `.fnc`, `.trg`, `.pck`, `.spc`, `.bdy`), il mainframe (`.cpy`, `.jcl`, `.pli`, `.asm`), IBM i per intero (`.sqlrpgle`, `.clle`, `.dds`, `.pf`, `.lf`, `.dspf`), Delphi, PHP, Perl, ABAP, Progress, PowerBuilder, gli script di shell. | Sono i linguaggi in cui il legacy è scritto davvero. |
| O4 | **Pattern statici per VB**: `Sub`, `Function`, `Property`, `Class`/`Module`, `Imports`; e tre rischi tipici — `On Error Resume Next` (gli errori dopo quella riga spariscono), `GoTo`, `CreateObject` (dipendenza COM risolta a runtime). | Il .vb entrava, ma l'analisi statica lo guardava con gli occhi del PL/SQL. |
| O5 | **Pattern per JCL**: gli step come componenti, `EXEC PGM=` come dipendenza, `DSN=` come oggetto dato. | Un JCL è la mappa di un batch: chi esegue cosa e su quali dataset. |
| O6 | **CORRETTO: ogni pattern gira solo sul suo linguaggio.** Prima i pattern di tutti i linguaggi giravano su tutti i file. | È il difetto che il .vb ha reso visibile: la stessa `ApplyDiscount` usciva quattro volte con quattro etichette (`FUNCTION`, `JAVA_METHOD`, `JAVASCRIPT_FUNCTION`, `VB_FUNCTION`), e `End Function` seguito da una riga che comincia con `Public` fabbricava una funzione fantasma di nome Public. Sui file di linguaggio ignoto si provano tutti, che è meglio di niente. |
| O7 | **`[ \t]+` invece di `\s+`** dopo `PROCEDURE`, `FUNCTION`, `PACKAGE`. | `\s+` attraversa gli a capo: era la meccanica del fantasma. |
| O8 | **I pattern VB distinguono le maiuscole.** | `Sub`, `Function` e `Property` in VB sono sempre così; senza distinzione, `function` in un commento diventava un componente. |
| O9 | **Otto casi in più nel collaudo**: il .vb accettato, l'estensione ignota, il binario respinto, VB e JCL riconosciuti, il fantasma che non nasce più, i rischi VB che non girano sui file SQL. | 116 in tutto. |

---

## P · La velocità

Il tempo di un'analisi non lo fa la lettura del codice: lo fa la **scrittura
della risposta**. Un modello genera qualche decina di token al secondo, e una
risposta piena da sedicimila token sono minuti. Le tre leve stanno lì.

| # | Modifica | Perché |
|---|---|---|
| P1 | **Profondità «Quick»** accanto a «Full», al passo 3. Chiede le otto sezioni che ripagano l'esecuzione — processi, regole, componenti, dipendenze, interfacce, dati, rischi, domande — e mette un tetto alla risposta di 7.000 token invece di 16.000. Analisi d'impatto, mappa applicativa, assunzioni e diagrammi del modello restano vuoti, dichiarati come saltati (non come mancanti); i diagrammi si costruiscono comunque dalle tabelle. | È la leva più grossa che esiste: meno token da scrivere, meno minuti. Grosso modo metà tempo. Il prompt, lo schema nativo e la normalizzazione seguono tutti la stessa scelta, quindi non possono divergere. |
| P2 | **Lotti in parallelo**: da 1 a 4 insieme, scelto dall'utente (predefinito 2). La prova di contatto si fa una volta sola prima di aprire i thread; l'avanzamento conta i lotti **finiti**, aggiornato solo dal thread principale perché Streamlit lo pretende. | La chiamata al modello è attesa di rete, e tenerne una sola in volo alla volta è tempo buttato. Il tetto lo sceglie chi paga, perché è la sua quota che si consuma più in fretta: su una chiave gratuita conviene restare a 1 o 2. Collaudato con un provider finto: tre lotti da 0,25 s finiscono in 0,26 s. |
| P3 | **Cache dei lotti su disco**, in `cache/` (visibile, non versionata). Un lotto è identificato dai suoi file, dal contratto e da come è stato chiesto; stessa chiave, stessa risposta, letta dal disco invece di ripagata. Sopravvive alla chiusura della sessione. | Rilanciare dopo aver aggiunto un file paga solo il lotto nuovo; riaprire il giorno dopo non paga niente; due colleghi sulla stessa macchina non pagano due volte. «Analyse again from scratch» la ignora. Quick e Full sono chiavi diverse. |
| P4 | **La memoria della catena si è spostata in `cache/`** (`catena_modelli.json`): era un file nascosto accanto al codice. | Niente file nascosti, e una sola cartella rigenerabile da ignorare in git. |
| P5 | **In Overview** si legge la profondità usata e quanti lotti vengono dalla cache. | Chi legge deve sapere se ha davanti un'analisi rapida o completa. |
| P7 | **Tolti dal pacchetto `package.json` e `package-lock.json`.** Li aveva fabbricati `npm` durante il collaudo dell'installazione ed erano finiti nello zip senza che nessuno li volesse. `avvia.py` ora installa con `--no-save`, e i due nomi sono in `.gitignore`. | Un file nel repository deve esserci perché qualcuno l'ha deciso. |
| P6 | **Otto casi in più nel collaudo**, sull'orchestrazione intera con un provider finto: il parallelismo misurato, la prova unica, la cache che riusa, il file aggiunto che paga solo il suo lotto, il «da capo» che ripaga tutto, Quick che non segnala come mancante ciò che ha saltato. | 124 in tutto. |

Cosa NON accelera: la prova di contatto (già in memoria per dieci minuti) e
l'analisi statica (frazioni di secondo). E cosa costa: la cache non sa che il
modello è migliorato — se cambia il modello o il ragionamento la chiave cambia
da sola, ma un modello aggiornato sotto lo stesso nome dà la risposta vecchia
finché non si spunta «from scratch».

---

## Q · Le risposte a metà: si continuano, non si rifanno

Prima, una risposta tagliata dal tetto di token veniva ritentata da capo con lo
stesso prompt (che non la accorcia), poi consegnata a metà e riparata buttando
l'ultima riga. E se il modello cadeva, si scendeva al successivo, che avrebbe
scritto altrettanto. Ora una risposta a metà è una risposta da **continuare**,
con lo **stesso modello**, dal **punto esatto** in cui si è fermata.

| # | Modifica | Perché |
|---|---|---|
| Q1 | **Il tag di chiusura.** Il contratto chiede che l'ultima proprietà dell'oggetto sia `"complete": true`; nello schema di Gemini è obbligatoria e l'ordine è imposto. La risposta è completa se il JSON si legge per intero **e** c'è il tag — oppure, se il tag manca, se il provider non l'ha segnalata come tagliata. | Il tag da solo non basta (un modello può dimenticarlo); il segnale del provider da solo nemmeno (un JSON può chiudersi giusto sul limite). Insieme sono affidabili. E il prompt dice: se finisce lo spazio, non accorciare le righe per farcele stare — fermati, ti verrà chiesto di continuare. |
| Q2 | **La catena non cambia più modello su una risposta tagliata.** La consegna subito, marcata, e chi chiama chiede il seguito. | Cambiare modello butta via il pezzo scritto per rifarlo con un altro che scriverà altrettanto. |
| Q3 | **`continua()` nella catena**: stesso modello, niente scoperta, niente prova, niente scalata. Se è occupato si riprova con lui; se è definitivamente giù si fallisce, non si passa a un altro. | Solo chi ha scritto la prima parte sa proseguirla con la stessa voce. |
| Q4 | **Il seguito si chiede nel dialetto di ciascun provider.** Gemini: il pezzo scritto torna come turno del modello, poi la richiesta di proseguire, in modo testo (il seguito da solo non è un JSON valido e uno schema lo rifiuterebbe). Azure/OpenAI: idem, senza `response_format`. **Anthropic: il pezzo scritto diventa il prefill** e il modello continua la stessa frase senza nemmeno sapere di essersi fermato — il modo migliore che esista; con il ragionamento esteso, dove il prefill non è ammesso, si torna alla forma a turni. | — |
| Q5 | **Il riattacco.** Il seguito viene ripulito dai recinti markdown e si cerca la sovrapposizione più lunga fra la coda della prima parte e la testa della seconda: i modelli, quando riprendono, ripetono spesso gli ultimi caratteri. | «Discount ov» + «er 100» → «Discount over 100», anche se il modello ripete «Discount ov». |
| Q6 | **Due continuazioni automatiche** prima di fermarsi. | Se il modello si è fermato a metà, chiedergli di proseguire non è una decisione che valga un clic. Se due giri non bastano, è giusto che sia una persona a decidere se spendere ancora. |
| Q7 | **Il bottone «Continue with the same model»** compare in cima alla pagina quando una risposta resta incompleta, con scritto quali lotti e quali file. Le righe già scritte si vedono intanto, riparate, con l'avviso che possono cambiare. | Chi guarda sa cosa manca e cosa può fare. |
| Q8 | **Finché la risposta non è completa, «Analyse the application» è spento**, con scritto perché. Si sblocca a risposta completa (o svuotando i risultati). | È la regola chiesta: prima si finisce, poi eventualmente si rifà. |
| Q9 | **Il consolidamento aspetta** che tutti i lotti siano completi; **la cache** salva solo i lotti completi. | Un inventario a metà produce collegamenti a metà; una risposta a metà in cache sarebbe una risposta a metà per sempre. |
| Q10 | **Lo stato dei lotti** (prompt, testo scritto finora, modello, chiave di cache) vive nella sessione, **non** nel risultato esportato. | Il prompt contiene il sorgente del cliente: non deve finire in un JSON che gira per e-mail. Per questo un'analisi incompleta ricaricata da file non si può continuare — lo dice, e sblocca l'avvio. |
| Q11 | **Otto casi in più nel collaudo**: la continuazione automatica fino al tag, il riattacco a metà parola, il secondo modello mai chiamato, la risposta che resta a metà dopo due giri e si ferma, il bottone che la porta in fondo, il ricomponimento che sblocca l'avvio, il modello occupato riprovato e non sostituito. | 132 in tutto. Corretto anche un collaudo che leggeva la cache vera invece di quella di prova, e passava solo la prima volta. |

---

## R · La guida

| # | Modifica | Perché |
|---|---|---|
| R1 | **Guida in inglese**: `GUIDE.md` e `GUIDE.pdf`, traduzione integrale della guida italiana, stessa struttura. `guida_pdf.py` senza argomenti le rigenera tutte e due. | Per i colleghi e i clienti che non leggono l'italiano. |
| R2 | **Aggiornata su velocità e ripresa**: le quattro manopole (profondità, ragionamento, lotti insieme, memoria del lavoro fatto), la continuazione dal punto in cui il modello si è fermato, il ricaricamento di un'analisi salvata. Nella parte tecnica: profondità, lotti in parallelo, cache, completezza e continuazione, stato di sessione. | Erano cambiamenti recenti e la guida era rimasta indietro. |
| R3 | **Tolte le sezioni «Cosa non è mai stato provato davvero» e «Da dove cominciare a provare».** Nella guida resta un solo elenco di limiti, di progetto. | Richiesta esplicita: il dettaglio di cosa è stato verificato e come sta in questo file, non nella guida che si consegna. |
| R4 | Sistemata una sezione della parte 1 in cui il paragrafo sulla continuazione era finito in mezzo a quello sul ragionamento. | — |

---

## S · La scelta del modello

| # | Modifica | Perché |
|---|---|---|
| S1 | **«Check the connection» sta subito dopo la chiave** (e l'endpoint, su Azure), prima della scelta del modello. Verifica la chiave e la catena così come la trova, e rifà la scoperta: aggiorna anche il menù qui sotto. | Si controlla la chiave, non una scelta. |
| S2 | **«Preferred model» è un menù a tendina riempito dai modelli trovati sulla chiave**, dal più nuovo in giù. La prima voce è *Automatic (the chain decides)*; le altre sono i modelli che la scoperta ha trovato, nell'ordine della preferenza (qualità o velocità). La scoperta si fa una volta per chiave e la catena la tiene in memoria sei ore. | Chi sceglie sceglie fra cose che esistono. Prima c'era un campo di testo libero in cui si poteva scrivere qualunque nome. |
| S3 | **CORRETTO: su Gemini e Claude il campo «Preferred model» non faceva niente.** Il valore veniva passato alla catena come `deployment`, che conta solo per Azure. Si poteva scrivere qualunque cosa e la catena andava per conto suo — e nessuno se ne accorgeva, perché la catena andava comunque. | Ora il modello scelto va in testa alla catena per qualunque provider; se non risponde si ricade sugli altri, il migliore per primo; la scelta della persona vince sulla memoria del modello «buono». |
| S4 | **Su Azure il menù elenca i deployment** trovati sull'endpoint. Se l'elenco non si può leggere (la chiave può non avere quel permesso), resta un campo di testo per scrivere il nome: è l'unico caso. | Il nome chiamabile su Azure è il deployment, e solo chi ha creato la risorsa lo conosce. |
| S5 | Le variabili d'ambiente `GEMINI_MODEL`, `ANTHROPIC_MODEL`, `AZURE_OPENAI_DEPLOYMENT` preselezionano la voce del menù, se c'è. | — |
| S6 | **Quattro casi in più nel collaudo**: il modello scelto provato per primo, la ricaduta sul migliore se è giù, la scelta che vince sulla memoria, un nome non in elenco comunque provato. | 136 in tutto. |

---

## T · Le vie d'uscita da una risposta a metà

Due domande dal campo: c'è un modo per ricominciare da capo se «Continue» non
funziona? E se il modello che scriveva ha finito la quota, si resta bloccati?
Risposta di prima: la via d'uscita c'era ma si chiamava «Clear results» in un
altro posto; e sì, si restava bloccati — la regola «mai cambiare modello a
metà» era diventata «restare fermi». Peggio: se la quota finiva durante le
continuazioni automatiche, l'errore faceva cadere **l'intera esecuzione**,
lotti buoni compresi.

| # | Modifica | Perché |
|---|---|---|
| T1 | **CORRETTO: una continuazione automatica che fallisce non fa più cadere l'esecuzione.** Il lotto viene consegnato a metà, con la causa (`quota`, `busy`…), e gli altri lotti restano buoni. | Tre lotti riusciti non devono andare persi perché il quarto si è fermato. |
| T2 | **Tre vie d'uscita nel pannello**, una accanto all'altra: *Continue with the same model*, *Keep what was written*, *Discard and start over*. | Chi guarda una risposta a metà deve poter scegliere, non solo aspettare. |
| T3 | **«Continue with the next model»** compare quando il modello che scriveva ha smesso di rispondere: consegna il seguito al modello successivo della catena (`CatenaModelli.successivo`). Le righe già scritte restano; il risultato e il documento dicono quale lotto è stato finito da un modello diverso e da quale. | Il passaggio non avviene mai da solo: è una decisione della persona, e resta scritta. La regola «non cambiare modello a metà» era giusta come regola automatica e sbagliata come muro. |
| T4 | **«Keep what was written»** accetta i lotti a metà così come sono — le righe già riparate restano — e lo dichiara negli avvisi; il consolidamento parte, l'avvio si sblocca. | A volte quello che c'è basta, e pagare ancora non ha senso. Non finisce in cache: una risposta a metà in cache sarebbe a metà per sempre. |
| T5 | **«Discard and start over»** butta l'esecuzione e riaccende «Analyse the application». | La via d'uscita chiamata col suo nome, dove serve. |
| T6 | Quando «Continue with the same model» fallisce, il pannello mostra la causa e apre la via del modello successivo, senza far cadere niente. | — |
| T7 | **Sei casi in più nel collaudo**: la quota che finisce in continuazione automatica senza far cadere l'esecuzione, il modello dopo interpellato solo su decisione, la risposta chiusa dal secondo modello, l'avviso nel risultato. | 142 in tutto. |

---

---

## U · File di versioni diverse (segnalazione: «AttributeError… prova_locale»)

L'errore arrivava dalla riga 1589 di `app.py`, che è esattamente quella del
pacchetto attuale: `app.py` era nuovo e `mermaid_render.py` **vecchio**, di
prima dell'11 settembre. Nel repository erano finiti file di due versioni —
probabilmente copiando un file solo. Il codice non era rotto; l'app però
moriva con un errore redatto dal servizio che non nominava nemmeno il file.

| # | Modifica | Perché |
|---|---|---|
| U1 | **Ogni modulo dichiara la propria versione** (`__version__ = "2026.09.14"`, uguale in tutti e sette). | Un file solo si può confrontare con gli altri solo se porta una data. |
| U2 | **All'avvio, `app.py` confronta le versioni prima di fare qualunque altra cosa.** Se non coincidono mostra un errore con i nomi dei file da aggiornare e si ferma. | È l'unica informazione utile in quel momento: *quali* file. Provato con un `mermaid_render.py` retrodatato: si ferma con «these are not: mermaid_render.py (2026.09.10)». |
| U3 | **`verifica.py` fa lo stesso controllo** senza avviare l'app. | Per accorgersene prima del deploy. |
| U4 | **CORRETTO: `MODIFICHE.md` conteneva ogni blocco da E a T due volte.** Un inserimento fatto male al blocco D aveva sdoppiato la coda del file, e ogni blocco successivo veniva aggiunto in entrambe le copie. Ricomposto nell'ordine giusto, da A a U, una volta sola. | Trovato cercando dove fosse nata `prova_locale`: c'era due volte. |

**Da fare nel repository di Danilo**: sostituire **tutta** la cartella con il
contenuto dello zip, non i singoli file, e su Streamlit Cloud riavviare l'app
(«Reboot») dopo il push: il processo tiene in memoria i moduli già importati.

---

## V · Tre difetti visti in produzione

Segnalazioni con lo schermo davanti, che è il modo migliore per trovarli.

| # | Trovato | Sistemato |
|---|---|---|
| V1 | **«1 Model / 2 Source code / 3 Run» comparivano in cima alla pagina**, sopra il titolo, dove non volevano dire niente — e nella barra laterale i controlli restavano senza intestazione. | `ui.tappa` usava `st.markdown` invece di `st.sidebar.markdown`. Una parola. |
| V2 | **La barra di avanzamento si riempiva subito e poi stava ferma.** Due cause: una regola CSS colorava la pista invece del riempimento, quindi appariva piena sempre; e con pochi lotti non c'è comunque niente da misurare — il tempo lo fa il modello mentre scrive, e quanto manchi non lo sa nessuno. | **Barra tolta.** Restano la rotella che gira, l'etichetta che cambia, i secondi che passano e il diario dei lotti finiti: sono informazioni vere. Una barra che dice una cosa falsa è peggio di nessuna barra. |
| V3 | **«Data flow — built from the tables»: «Syntax error in text».** Le etichette sugli archi non erano fra virgolette e non venivano ripulite abbastanza. Una freccia dentro l'etichetta (`order --> invoice`, che i modelli scrivono di continuo) è un secondo arco e fa esplodere la riga; `&` è l'operatore «più nodi insieme»; `#` apre un codice di entità. | Le frecce diventano «to», `&` diventa «and», `#` sparisce, e ogni etichetta sull'arco va fra virgolette (`-->\|"testo"\|`). La regex delle frecce riconosce le forme vere di Mermaid, non un trattino qualsiasi: `co-ordinate` e `24-48 ore` restano parole. Vale sia per i diagrammi costruiti dalle tabelle sia per quelli scritti dal modello. |
| V4 | **Sette casi in più nel collaudo** sulle etichette. | 149 in tutto. |

---

## Z · I campi senza bordo, e il tema che non arrivava

Segnalazione: «un po' di bordatura dove vanno inseriti i dati ci andrebbe».
Vera, e nello stesso screenshot c'era un secondo segnale più grave: il cursore
e il radio erano **rossi**, cioè il tema non era applicato affatto.

| # | Trovato | Sistemato |
|---|---|---|
| Z1 | **CORRETTO: su Streamlit Cloud il tema non arrivava.** Lo passava solo `avvia.py` come opzioni della riga di comando, ma lassù l'applicazione la lancia la piattaforma e `avvia.py` non gira mai. L'accento restava il rosso di serie — che è il colore che l'applicazione riserva alla gravità dei rischi, quindi non un dettaglio estetico. | **`.streamlit/config.toml` rimessa.** Era stata tolta per non avere cartelle nascoste; la decisione era giusta come principio e sbagliata nei fatti, perché su Streamlit Cloud non esiste altra via. Le opzioni di `avvia.py` restano per chi parte da riga di comando senza quel file. `verifica.py` ora controlla che ci sia e spiega cosa si perde. |
| Z2 | **I campi di inserimento non avevano un bordo visibile**: fondo bianco su barra laterale bianca, con il bordo quasi invisibile di serie. Non si capiva dove andasse scritto. | Bordo pieno di 1px, fondo bianco, angoli arrotondati, e l'accento quando ci si passa sopra o ci si entra col tab. Vale per campi di testo, aree di testo, menù a tendina e area di caricamento. |
| Z3 | **La barra laterale è leggermente tinta** (`#F6F8FA`) invece che bianca. | Il bordo da solo non bastava: serviva lo stacco fra il campo e quello che gli sta intorno. Contrasto del testo invariato. |
| Z4 | I pannelli richiudibili nella barra laterale restano bianchi, come i campi. | — |

---

## AA · La barra laterale semplificata

Quattro domande dal campo, tutte con una risposta nel codice.

| # | Domanda / difetto | Risposta |
|---|---|---|
| AA1 | *Perché i modelli appaiono ogni tanto in verticale e ogni tanto in orizzontale?* | Il diario scriveva la catena su **una riga sola** (`Catena: a → b → c`), che nella barra laterale veniva tagliata a metà: si leggeva il primo nome e basta. Ora è **un modello per riga, numerato**. |
| AA2 | **Il diario era in italiano** dentro un'interfaccia inglese («Catena», «Modello buono ricordato», «risponde»). Si vedeva in «Check the connection» e nel pannello degli errori. | Tradotto tutto. I commenti nel codice restano in italiano, come sempre. |
| AA3 | *Perché non c'è direttamente «Run check» ma prima un menù a tendina?* | Nessun buon motivo: è la prima cosa che si fa con una chiave nuova. Ora è **un bottone diretto**; l'esito resta sotto, e il diario dettagliato in un pannello che si apre solo se interessa. |
| AA4 | *La parte «Source» si può semplificare?* | Sì, togliendo un pannello: **un'analisi salvata si riconosce da sola** se la si trascina nel campo dei file. Si guarda cosa c'è dentro il JSON (le sezioni del contratto), non come si chiama: un `config.json` qualunque resta un file da analizzare. Il pannello «Or resume a saved analysis» non serve più — e chi non lo trovava rifaceva l'analisi da capo. |
| AA5 | *Le cose che non si fanno ogni volta si possono mettere in un menù?* | Sì: **Expert settings**, un pannello in fondo con preferenza dei modelli, modello preferito, tempo di ragionamento, profondità, lotti in parallelo, «analizza da capo» e installazione delle dipendenze. Nella barra restano tre tappe e sei controlli. Dieci controlli in vista fanno credere che vadano decisi tutti; i valori predefiniti vanno bene quasi sempre. |
| AA6 | **Quattro casi in più nel collaudo**: il diario in inglese e su più righe, l'analisi salvata riconosciuta col suo contenuto, il JSON estraneo che resta un sorgente. | 153 in tutto. |

---

## AB · Il tema senza cartella nascosta — definitivo

Nel blocco Z avevo rimesso `.streamlit/config.toml` per far arrivare il tema su
Streamlit Cloud, ribaltando da solo una decisione già presa (niente cartelle
nascoste, perché si perdono nella copia). Errore di metodo, prima che di
merito: una decisione presa insieme non si ribalta da soli, si torna a
chiedere. La cartella è tolta di nuovo, e stavolta il tema ha un'altra strada.

| # | Modifica | Perché |
|---|---|---|
| AB1 | **`.streamlit/` rimossa, e non torna.** | Decisione presa il 12 settembre e che vale. |
| AB2 | **Il tema si imposta da codice**, in `ui.imposta_tema_streamlit()`, chiamata da `app.py` subito dopo `set_page_config`: colori, limite di caricamento, barra strumenti. Usa l'API interna di configurazione di Streamlit, che accetta il valore anche per le opzioni «non modificabili» (il blocco sta solo nell'API pubblica). | Il messaggio di sessione che porta il tema al browser viene costruito **a ogni riesecuzione** e legge la configurazione in quel momento — verificato nel sorgente di Streamlit, non supposto. Quindi vale ovunque, Streamlit Cloud compreso, dove l'app la lancia la piattaforma. |
| AB3 | **Una ripartenza automatica alla prima esecuzione della sessione.** | La primissima esecuzione parte col tema di serie perché il messaggio era già partito; si fa ripartire una volta (un `rerun`, invisibile), e dalla seconda il tema è il nostro. Non si ripete: alla seconda la configurazione è già quella giusta. |
| AB4 | Se l'API interna cambiasse o mancasse, non succede nulla: restano i colori del CSS. `avvia.py` passa le stesse opzioni per chi parte da lì, così non ha nemmeno la ripartenza. `verifica.py` non cerca più la cartella. | Un'API interna può cambiare: ci si appoggia senza dipenderne. |

---

## Cosa NON è stato cambiato

- Le sezioni da 1 a 6 dei documenti restano dov'erano e come si chiamavano.
  L'unico spostamento è l'ex §7, diventata §8 (vedi J6).
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
