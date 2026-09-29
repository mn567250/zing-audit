# zing — verifica di realtà per i relay LLM

> [🇬🇧 English](README.md) · [🇨🇳 中文](README.zh-CN.md) · [🇫🇷 Français](README.fr.md) · [🇪🇸 Español](README.es.md) · [🇵🇹 Português](README.pt.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](README.de.md)

[![CI](https://github.com/cenbonew/zing/actions/workflows/ci.yml/badge.svg)](https://github.com/cenbonew/zing/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**zing** è uno strumento da riga di comando local-first che verifica se un relay di API
(rivenditore / proxy) serve davvero il modello che dichiara — o se lo sostituisce in
silenzio con uno più economico, tronca la finestra di contesto, simula lo streaming o
gonfia la fatturazione dei token. In breve: ottieni ciò per cui paghi? Parla **OpenAI
Chat Completions**, l'**API Anthropic Messages** e l'**API OpenAI Responses**
(`/v1/responses`) — con rilevamento automatico, o forzato con
`--api openai|anthropic|responses`.

Gli indichi l'endpoint di un relay e il modello che dichiara; zing esegue una batteria di
sonde black-box, confronta il comportamento osservato con una base di conoscenza
integrata di **85 profili di modelli nativi su 7 piattaforme** e stampa un verdetto
chiaro e supportato da prove — per una persona, o in JSON per un altro strumento / LLM.

> zing fornisce **prove black-box di divergenze e rischi, non una prova crittografica
> di frode.** Vedi [Uso responsabile](#uso-responsabile).

---

## Perché

Il mercato delle chiavi per relay è pieno di offerte «GPT-4o a un decimo del prezzo».
Molte sono oneste. Alcune no — e quelle disoneste sono difficili da smascherare a occhio
nudo:

- Chiedi `gpt-4o`; in silenzio ti viene servito `gpt-4o-mini` o un modello open.
- Il relay dichiara un contesto da 1M di token ma lo tronca silenziosamente a 32K.
- Lo «streaming» è la risposta completa bufferizzata e poi rispezzettata, senza alcun vantaggio di latenza.
- I token di `usage` riportati sono gonfiati, quindi il tuo credito si consuma più in fretta del dovuto.
- Un modello che dovrebbe supportare le chiamate a strumenti / la modalità JSON in silenzio non lo fa.

zing trasforma «qui qualcosa non torna» in un rapporto riproducibile.

## Installazione

Richiede Python 3.10+. Ciascuna delle opzioni seguenti fornisce il comando `zing`.

### Con pip

```bash
# da PyPI
pip install zing-audit

# oppure dai sorgenti
git clone https://github.com/cenbonew/zing
cd zing
pip install -e .
```

### Con [uv](https://docs.astral.sh/uv/)

```bash
# da PyPI, come strumento autonomo nel tuo PATH
uv tool install zing-audit

# oppure eseguirlo una volta senza installarlo
uvx --from zing-audit zing --help

# oppure dai sorgenti, in un ambiente virtuale locale al progetto
git clone https://github.com/cenbonew/zing
cd zing
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

Puoi anche installarlo direttamente dal repository Git senza clonarlo:
`uv tool install git+https://github.com/cenbonew/zing`.

(Manutentori: vedere [docs/PUBLISHING.md](docs/PUBLISHING.md) per il processo di rilascio.)

### Extra opzionali

- `tokenizers` — conteggio accurato dei token della famiglia OpenAI nell'audit della fatturazione.
- `web` — l'interfaccia web locale (`zing serve`).
- `pdf` — rapporti PDF (`--format pdf` e il download PDF dell'interfaccia web),
  generati dal rapporto HTML con [WeasyPrint](https://weasyprint.org/); richiede la
  libreria di sistema Pango (su macOS `brew install pango`).

```bash
pip install 'zing-audit[tokenizers,web]'          # pip, da PyPI
pip install -e '.[tokenizers,web]'                # pip, dai sorgenti
uv tool install 'zing-audit[tokenizers,web]'      # uv, da PyPI
uv pip install -e '.[tokenizers,web]'             # uv, dai sorgenti
```

## Avvio rapido

```bash
# 1) verificare un relay rispetto a ciò che dichiara (id del modello + indicazione del provider)
export ZING_API_KEY=sk-la-tua-chiave-relay
zing check \
  --base-url https://relay.example.com/v1 \
  --api-key env:ZING_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) il controllo più forte: confronto con un riferimento affidabile dello stesso modello
export OPENAI_API_KEY=sk-la-tua-chiave-openai
zing compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:ZING_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) verificare un relay nativo Anthropic (API Messages) — il protocollo viene rilevato
#    automaticamente da base_url/model, oppure forzato con --api anthropic
zing check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:ZING_API_KEY --api anthropic

# 4) confermare una sostituzione sospetta: verificare l'id REALE del modello del relay
#    rispetto al profilo con cui è venduto (qui: un modello Doubao spacciato per deepseek-v4-flash)
zing check --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) consultare la base di conoscenza integrata
zing kb            # tutti gli 85 modelli
zing kb deepseek   # un provider

# 6) generare una configurazione da mettere sotto versione
zing init          # scrive zing.yaml
zing check -c zing.yaml
```

### Come strumento per un LLM / agente

zing è pensato per essere pilotato da un altro programma o modello. Tutto va su stdout in
JSON, errori compresi, e il codice di uscita fa da cancello.

```bash
# verdetto snello, adatto agli agenti (~5x più piccolo di --json: senza le prove voluminose)
zing check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# rapporto strutturato completo quando servono le prove di ogni rilievo
zing check --base-url ... --model gpt-4o --json

# prima il budget: quali rilevatori vengono eseguiti + chiamate API stimate, SENZA farne nessuna
zing check --base-url ... --model gpt-4o --suite deep --dry-run --json

# cancello sul codice di uscita (1 se rischio >= medium); errori di config/uso escono con 2, in JSON
zing check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# individuazione leggibile da macchina
zing kb --json                 # l'intera base di conoscenza
zing models --base-url ... --json   # ciò che un endpoint dichiara
```

In modalità `--json`/`--compact` una configurazione errata stampa `{"error": {...}}`
(codice 2) invece di un messaggio per persone, così una pipeline può analizzare i
fallimenti in modo uniforme.

## Interfaccia web (`zing serve`)

Preferisci cliccare? Un'interfaccia web locale avvolge lo stesso motore — senza bisogno
della riga di comando.

```bash
pip install 'zing-audit[web]'     # oppure: uv tool install 'zing-audit[web]'
zing serve            # apre http://localhost:8000
```

Inserisci un relay e il modello che dichiara; segui l'audit **in diretta** (avanzamento
per rilevatore via SSE), poi leggi un rapporto di verdetto condivisibile (voto,
dettaglio per dimensione, rilievi in linguaggio semplice, JSON scaricabile). Tutto gira
sulla tua macchina — una chiave digitata nel browser raggiunge solo il tuo server locale
e il relay verificato, mai terze parti. Per impostazione predefinita resta in ascolto su
`127.0.0.1`.

Un menu a tendina della lingua nell'intestazione di ogni pagina passa l'interfaccia tra
**🇬🇧 inglese** (predefinito), **🇨🇳 cinese** (l'interfaccia originale), **🇫🇷 francese**,
**🇪🇸 spagnolo**, **🇵🇹 portoghese**, **🇮🇹 italiano** e **🇩🇪 tedesco**; la scelta viene
ricordata per browser. Anche i rapporti scaricati dall'interfaccia (**Scarica il
rapporto (JSON)**) seguono la lingua scelta: le chiavi JSON, i valori enumerati
(`risk_level`, `status`, `severity`, …), gli id e le prove restano esattamente come nel
rapporto della CLI (è sempre un rapporto zing valido), mentre i valori leggibili da una
persona (titolo/sintesi del verdetto, titoli/sintesi dei rilievi, raccomandazioni, nomi
dei rilevatori, note) vengono tradotti, e il nome del file riporta la lingua
(`zing-report.it.json`). I rapporti `--format json|md|html|pdf` della CLI restano in
inglese.

**I prompt inviati all'endpoint verificato non seguono la lingua dell'interfaccia.** Ogni
testo che zing invia a un'API LLM — sonde di chat, il prompt del giudice LLM, schemi
degli strumenti, input di embedding / rerank / immagini / audio — si trova in un'unica
libreria di prompt, `zing/prompts/en.json`, ed è in inglese, così lo stesso relay ottiene
lo stesso verdetto chiunque legga il rapporto (i controlli sulle risposte e le stime dei
token sono calibrati su questi testi esatti). Le uniche eccezioni sono le impronte della
base di conoscenza la cui lingua *è* la misura — ad es. le sonde di fluidità in cinese,
di tokenizer e di autoidentificazione dei modelli nativi cinesi — che dichiarano
`prompt_lang` e un motivo `language_bound` in `zing/knowledge/data/*.yaml`. Ogni rapporto
registra le lingue di sonda effettivamente usate (`prompt_languages`, ad es.
`["en", "zh"]`).

Le traduzioni sono dati, condivisi dall'interfaccia web e dagli avvisi webhook:
`zing/i18n/locales/<code>.json`, un file per lingua. Per aggiungere una lingua, aggiungi
un file (copia `de.json`); il menu, le pagine e gli avvisi lo recepiscono.
`tests/test_web_locales.py` fallisce finché ogni stringa dell'interfaccia e ogni rilievo
non sono tradotti con segnaposto e markup intatti.

## Cosa verifica

zing assegna un punteggio a dieci dimensioni. Le tre che rivelano più direttamente una
merce diversa da quella pattuita (identità del modello, finestra di contesto reale,
capacità dichiarate) pesano di più.

| Dimensione | Cosa rileva |
|---|---|
| **model_identity** | Declassamento/sostituzione silenziosa del modello — autoidentificazione, data limite delle conoscenze, impronte del tokenizer, il campo `model` restituito |
| **context_window** | Troncamento silenzioso del contesto (dichiara 1M, il richiamo fallisce a 32K) e «perdita nel mezzo» dovuta a strati economici di RAG/riassunto, tramite ago nel pagliaio + ricerca binaria |
| **capability** | Capacità dichiarate di chiamata a strumenti / modalità JSON / json-schema / output massimo non realmente fornite (o fornite *in eccesso*, indizio di un sostituto); e **visione** — a un modello che dichiara input di immagini viene inviata un'immagine generata a risposta nota per confermare che «veda» davvero |
| **billing** | Gonfiamento di token/utilizzo e contabilità dell'utilizzo mancante/non verificabile, tramite una stima indipendente con tokenizer |
| **streaming** | Falso streaming (buffer e poi suddivisione) rilevato dal numero di frammenti e dai tempi tra un frammento e l'altro |
| **protocol** | Conformità alla compatibilità OpenAI: più turni, sequenze di stop, forma della risposta, schema degli errori — e un sotto-controllo di determinismo per cache di risposta che ignorano temperature/seed |
| **reliability** | Tasso di successo in concorrenza e latenza (la limitazione HTTP 429 è conteggiata a parte) |
| **performance** | Quanto sono *costanti* latenza, tempo al primo token e throughput, il tasso di errore della sonda e il rallentamento sotto carico; la velocità solo rispetto a un riferimento |
| **connectivity** | Raggiungibilità dell'endpoint e l'elenco `/v1/models` dichiarato |
| **security** | Trasporto (HTTPS), igiene delle intestazioni, eco di segreti; prompt di sistema iniettato nascosto (overhead fisso di token in input + fuga), manomissione in transito di risposte/chiamate a strumenti tramite canarini a risposta nota (sostituzione di URL/pacchetti) e cache del prefisso del prompt (tempi) |

Vedi [docs/METHODOLOGY.md](docs/METHODOLOGY.md) per la tecnica alla base di ogni
controllo, il trucco del relay a cui corrisponde e le avvertenze sui falsi positivi.

### Prestazioni

Ogni rapporto contiene anche una sezione **performance**: latenza, tempo al primo token
(TTFT), token/s di decodifica ed end-to-end, latenza e jitter tra frammenti, tassi di
errore/timeout/429, una scomposizione di rete (connessione TCP, TLS, un round trip
`GET /models`, tempo del server) e avvio a freddo, ciascuno come
count / min / mean / p50 / p75 / p90 / p95 / p99 / max / stdev. Quando viene eseguita la sonda dedicata, valuta la dimensione **performance** (peso 6) in base alla *costanza* di latenza, TTFT e throughput, al tasso di errore e al comportamento sotto carico, non alla velocità pura: un modello lento ma costante (ad es. locale) non viene penalizzato. La velocità conta solo rispetto a un riferimento (la baseline o l'intervallo pubblicato nella base di conoscenza). I rilievi sono al massimo di gravità bassa e non cambiano mai il verdetto di rischio.

- **standard** la raccoglie dalle richieste stesse dell'audit.
- **deep / full** aggiungono una sonda dedicata: 100 richieste non memorizzabili in cache
  da 128 token di output (un id di richiesta casuale apre ogni prompt, non vengono inviati
  parametri di cache o di ragionamento) più una raffica a `--concurrency`. Regolabile con
  `--performance-requests` (0 la disattiva) e `--performance-max-tokens`.
- La sonda usa lo streaming per impostazione predefinita; `--performance-non-streaming`
  (o l'interruttore nell'interfaccia web) misura i relay che non supportano lo streaming.
  **full** misura entrambe le modalità, alternate, e le mostra affiancate.
- **compare** esegue la sonda su entrambi gli endpoint, alternando le richieste, e
  aggiunge una tabella obiettivo-vs-riferimento (5 richieste per lato con `standard`) le
  cui differenze sono segnate in verde ✓ quando l'obiettivo è migliore e in rosso ✗
  quando è peggiore. Un obiettivo che genera più di 2x più velocemente del riferimento
  viene segnalato come indizio di bassa gravità.

I token vengono contati due volte: dall'`usage` del relay e localmente, così il
throughput è misurabile anche quando `usage` manca. Un percentile viene mostrato solo con
abbastanza campioni (p90 da 10, p95 da 20, p99 da 100). Il rapporto JSON conserva i tempi
di ogni richiesta (solo numeri, nessun testo); il rapporto HTML e l'interfaccia web li
rappresentano lungo la cronologia dell'audit.

## Due modalità di rilevamento

- **Solo codice (predefinita):** tutte le sonde deterministiche — impronte, scansione del
  contesto, calcoli di fatturazione, tempi dello streaming. Nessun secondo modello
  necessario; completamente riproducibile.
- **Ibrida codice + LLM (`--judge`):** consulta inoltre un modello giudice *affidabile*
  (configurato a parte, mai l'obiettivo) per valutare segnali sfumati come qualità e
  profondità di ragionamento che il solo codice non può decidere. Alimenta il rilevatore
  `quality_judge`.

```bash
zing check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

## Monitoraggio (`zing watch`)

Un relay può servire il modello vero oggi e sostituirlo in silenzio la settimana
prossima. `zing watch` ripete l'audit secondo una pianificazione, registra ogni
esecuzione nello storico e avvisa un webhook quando il rischio supera una soglia o
**peggiora** rispetto all'esecuzione precedente.

```bash
zing watch --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang it                                     # oppure --once per cron
```

Gli avvisi sono formattati per **Slack / Feishu / DingTalk / JSON generico**, rilevato
automaticamente dall'URL del webhook, e scritti nella lingua degli avvisi — inglese per
impostazione predefinita; `--alert-lang en|zh|fr|es|pt|it|de`. Il payload JSON generico
mantiene chiavi e valori macchina (`risk_level`, `score`, …) indipendenti dalla lingua,
traduce quelli leggibili da una persona (`text`, `headline`, `key_findings`) e riporta la
`language`.

Preferisci un'interfaccia? `zing serve` include un monitor su **`/watches`**
(🔔 Monitor): aggiungi un monitor nel browser e uno scheduler in background, nello stesso
processo, lo riesegue al suo intervallo, salva ogni esecuzione nello storico e invia gli
stessi avvisi webhook al superamento di una soglia o in caso di peggioramento. Ogni
monitor ha la propria lingua degli avvisi (scelta nel modulo, per impostazione
predefinita quella dell'interfaccia, e modificabile sulla sua scheda). Esegui ora /
metti in pausa / elimina dalla pagina. Le chiavi sono conservate solo in `~/.zing` e non
vengono mai restituite al browser.

## Audit di embedding e rerank

Embedding e rerank sono una superficie non di chat, quindi zing li verifica con un
auditor autonomo dedicato invece che con la pipeline di chat a 9 dimensioni.

```bash
# La dimensione del vettore attesa viene ricavata dalla base integrata per il modello dichiarato.
zing embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Oppure impostare direttamente la dimensione attesa:
zing embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: una sonda integrata a risposta nota — un vero reranker deve mettere
# al primo posto il documento palesemente pertinente.
zing rerank --base-url https://relay.example.com/v1 --model my-rerank
```

`embed` verifica la connettività, la **corrispondenza della dimensione** (lunghezza del
vettore restituito rispetto alla dimensione nativa del modello dichiarato — il segnale
principale di merce diversa da quella pattuita; un relay che dichiara
`text-embedding-3-large` a 3072-d ma restituisce 1024-d serve un modello sostituito), il
determinismo (stesso input → coseno ≈ 1), la distinzione (input non correlati → coseno
ben al di sotto di 1) e il campo `model` restituito. Profili integrati: OpenAI
`text-embedding-3-small` (1536), `text-embedding-3-large` (3072),
`text-embedding-ada-002` (1536), Qwen `text-embedding-v3`/`-v4` (1024).

Entrambi sono disponibili anche nell'interfaccia web — `zing serve` ha una pagina
**Strumenti** su `/tools` (raggiungibile dalla navigazione) con moduli embed/rerank che
mostrano lo stesso verdetto localizzato.

## Audit di generazione di immagini e audio (TTS)

Altre due superfici non di chat: generazione di immagini (`POST /v1/images/generations`)
e sintesi vocale (`POST /v1/audio/speech`). Tutta la decodifica usa solo la stdlib —
dimensioni dell'immagine dai byte di intestazione (PNG/JPEG/GIF/WebP), durata WAV tramite
il modulo `wave`.

```bash
# Un relay che dichiara DALL·E 3 restituisce davvero il 1792x1024 richiesto? Un'immagine
# rimpicciolita / di dimensioni errate (o una dimensione fuori da quelle native del modello
# dichiarato, ricavate dalla base) è il segnale principale di merce diversa da quella pattuita.
zing image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Un relay che dichiara tts-1-hd restituisce audio reale la cui durata cresce con l'input
# (non un segnaposto fisso, non HTML/JSON travestito da audio)?
zing audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --format wav --save clip.wav
```

`image` verifica: connettività, formato valido/decodificabile, **corrispondenza delle
dimensioni** (LxA decodificato rispetto alla richiesta e alle dimensioni native del
modello dichiarato — FAIL/HIGH in caso di discrepanza), distinzione (due prompt →
immagini diverse, per scovare un segnaposto fisso), numero, campo model. `audio`
verifica: connettività, validità di contenitore/formato, rispetto del formato, durata non
banale (proporzionale alla lunghezza dell'input), distinzione, campo model. La base
include OpenAI DALL·E 2/3, gpt-image-1, tts-1/tts-1-hd/gpt-4o-mini-tts e profili
immagine/TTS di Qwen.

## Uso in CI (GitHub Action)

Subordina qualsiasi workflow a un audit del relay con l'azione composita inclusa. Esegue
`zing check --compact --fail-on-risk`, espone `risk` / `score` / `rating` come output,
scrive un riepilogo nell'esecuzione e fa fallire il job quando scatta la soglia di
rischio.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: zing
        uses: cenbonew/zing@v0.9.0          # fissare a un tag di release
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # segreto del chiamante; mai mostrato
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.zing.outputs.risk }} score=${{ steps.zing.outputs.score }}"
```

La chiave del relay viene passata tramite una variabile d'ambiente (`--api-key env:…`),
quindi non compare mai su una riga di comando. Vedi [docs/CI.md](docs/CI.md) per la
tabella completa di input/output e un esempio di blocco del deploy.

## Suite

| Suite | Rilevatori | Costo |
|---|---|---|
| `smoke` | connectivity, security | molto basso |
| `standard` | + protocol, model_identity, capability, streaming, billing, reliability | basso–medio |
| `deep` | + context_window, determinism, injected_prompt, integrity, performance, prompt_cache, quality_judge (con `--judge`) | più alto (le sonde di contesto lungo e di tempi consumano token) |
| `full` | tutto | il più alto |
| `custom` | solo le dimensioni scelte, con profondità `deep` | dipende dalla selezione |

**Suite personalizzata:** `zing check ... -D protocol -D performance` (oppure `--suite custom --dimension billing,streaming`; nel file di configurazione `run.dimensions`) esegue solo le dimensioni scelte. Il punteggio complessivo è la media ponderata di quelle sole dimensioni; senza una dimensione centrale (identità del modello, finestra di contesto, capacità) il verdetto di rischio è *non conclusivo*. L'interfaccia web offre la stessa scelta.

La sonda della finestra di contesto è limitata da `--max-context-tokens` (200K per
impostazione predefinita), così verificare un modello da 1M di token resta economico.

## Esempio di verdetto

```text
╭─ ✗ HIGH RISK — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · confidence medium                             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • Si identifica come un marchio concorrente (anthropic) sotto l'id di modello dichiarato gpt-4o
  • Finestra di contesto reale ~8000 << 128000 dichiarati (sospetto troncamento silenzioso)
  • I token di prompt riportati superano di molto la stima indipendente
```

I rapporti vengono scritti in `reports/` come JSON, Markdown e HTML, e anche in PDF con l'extra `pdf`.

## Base di conoscenza

I profili si trovano in [`zing/knowledge/data/`](zing/knowledge/data) come YAML
modificabile — uno per provider (OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM,
Moonshot). Ogni modello riporta la finestra di contesto nativa, l'output massimo, il
tokenizer, i flag di capacità, le parole chiave di identità e le impronte
comportamentali. Aggiungi o sovrascrivi profili senza fare un fork:

```bash
zing check --kb-dir ./my-profiles ...     # oppure imposta ZING_KB_DIR
```

## Uso responsabile

zing è un ausilio per audit black-box. **Non può dimostrare**:

- che un provider conservi i tuoi prompt o li usi per l'addestramento,
- che instradi sempre verso un unico modello preciso (un relay può instradare in modo probabilistico),
- frodi di fatturazione oltre quanto la stima indipendente dei token possa suggerire.

Usa i rapporti per la tua due diligence. **Non accusare pubblicamente un fornitore**
sulla base di una singola esecuzione senza valutare la dimensione del campione, le
impostazioni di costo e la legge locale. Esegui `zing compare` contro un riferimento
affidabile prima di trarre conclusioni forti.

## Licenza

[Apache-2.0](LICENSE)
