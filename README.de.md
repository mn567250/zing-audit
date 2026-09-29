# zing — Realitätscheck für LLM-Relays

> [🇬🇧 English](README.md) · [🇨🇳 中文](README.zh-CN.md) · [🇫🇷 Français](README.fr.md) · [🇪🇸 Español](README.es.md) · [🇵🇹 Português](README.pt.md) · [🇮🇹 Italiano](README.it.md) · **🇩🇪 Deutsch**

[![CI](https://github.com/cenbonew/zing/actions/workflows/ci.yml/badge.svg)](https://github.com/cenbonew/zing/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**zing** ist ein Local-first-Kommandozeilenwerkzeug, das prüft, ob ein API-Relay
(Wiederverkäufer / Proxy) tatsächlich das Modell liefert, das es verspricht — oder ob es
stillschweigend ein billigeres unterschiebt, das Kontextfenster kürzt, Streaming
vortäuscht oder die Token-Abrechnung aufbläht. Kurz: Bekommen Sie, wofür Sie bezahlen?
Es spricht **OpenAI Chat Completions**, die **Anthropic Messages API** und die **OpenAI
Responses API** (`/v1/responses`) — automatisch erkannt oder erzwungen mit
`--api openai|anthropic|responses`.

Sie geben ihm den Endpunkt eines Relays und das beworbene Modell; zing führt eine Reihe
von Black-Box-Tests aus, vergleicht das beobachtete Verhalten mit einer mitgelieferten
Wissensbasis von **85 nativen Modellprofilen auf 7 Plattformen** und gibt ein klares,
mit Belegen untermauertes Urteil aus — für Menschen oder als JSON für ein anderes
Werkzeug / LLM.

> zing liefert **Black-Box-Belege für Abweichungen und Risiken, keinen
> kryptografischen Betrugsnachweis.** Siehe [Verantwortungsvoller Einsatz](#verantwortungsvoller-einsatz).

---

## Warum

Der Markt für Relay-Schlüssel ist voller Angebote wie „GPT-4o für ein Zehntel des
Preises“. Viele sind ehrlich. Manche nicht — und die unehrlichen sind mit bloßem Auge
schwer zu erkennen:

- Sie fordern `gpt-4o` an und bekommen stillschweigend `gpt-4o-mini` oder ein offenes Modell.
- Das Relay bewirbt 1M Token Kontext, kürzt aber stillschweigend auf 32K.
- „Streaming“ ist die komplett gepufferte und neu zerstückelte Antwort, ganz ohne Latenzvorteil.
- Die gemeldeten `usage`-Token sind aufgebläht, sodass Ihr Guthaben schneller schwindet als nötig.
- Ein Modell, das Tool-Calling / JSON-Modus unterstützen sollte, tut es stillschweigend nicht.

zing macht aus „da stimmt doch was nicht“ einen reproduzierbaren Bericht.

## Installation

Erfordert Python 3.10+. Jede der folgenden Varianten stellt den Befehl `zing` bereit.

### Mit pip

```bash
# von PyPI
pip install zing-audit

# oder aus dem Quellcode
git clone https://github.com/cenbonew/zing
cd zing
pip install -e .
```

### Mit [uv](https://docs.astral.sh/uv/)

```bash
# von PyPI, als eigenständiges Werkzeug in Ihrem PATH
uv tool install zing-audit

# oder einmalig ausführen, ohne zu installieren
uvx --from zing-audit zing --help

# oder aus dem Quellcode, in eine projektlokale virtuelle Umgebung
git clone https://github.com/cenbonew/zing
cd zing
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

Sie können auch direkt aus dem Git-Repository installieren, ohne es zu klonen:
`uv tool install git+https://github.com/cenbonew/zing`.

(Maintainer: siehe [docs/PUBLISHING.md](docs/PUBLISHING.md) für den Release-Prozess.)

### Optionale Extras

- `tokenizers` — genaue Token-Zählung für die OpenAI-Familie in der Abrechnungsprüfung.
- `web` — die lokale Weboberfläche (`zing serve`).
- `pdf` — PDF-Berichte (`--format pdf` und der PDF-Download in der Weboberfläche),
  aus dem HTML-Bericht mit [WeasyPrint](https://weasyprint.org/) erzeugt; benötigt die
  Systembibliothek Pango (unter macOS `brew install pango`).

```bash
pip install 'zing-audit[tokenizers,web]'          # pip, von PyPI
pip install -e '.[tokenizers,web]'                # pip, aus dem Quellcode
uv tool install 'zing-audit[tokenizers,web]'      # uv, von PyPI
uv pip install -e '.[tokenizers,web]'             # uv, aus dem Quellcode
```

## Schnellstart

```bash
# 1) ein Relay gegen seine Angaben prüfen (Modell-ID + Anbieterhinweis)
export ZING_API_KEY=sk-ihr-relay-schluessel
zing check \
  --base-url https://relay.example.com/v1 \
  --api-key env:ZING_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) die stärkste Prüfung: Vergleich mit einer vertrauenswürdigen Referenz desselben Modells
export OPENAI_API_KEY=sk-ihr-openai-schluessel
zing compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:ZING_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) ein natives Anthropic-Relay (Messages API) prüfen — das Protokoll wird anhand von
#    base_url/model automatisch erkannt oder mit --api anthropic erzwungen
zing check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:ZING_API_KEY --api anthropic

# 4) einen vermuteten Austausch bestätigen: die ECHTE Modell-ID des Relays gegen das Profil
#    prüfen, unter dem es verkauft wird (hier: ein Doubao-Modell, ausgegeben als deepseek-v4-flash)
zing check --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) die mitgelieferte Wissensbasis ansehen
zing kb            # alle 85 Modelle
zing kb deepseek   # ein Anbieter

# 6) eine Konfiguration zum Einchecken erzeugen
zing init          # schreibt zing.yaml
zing check -c zing.yaml
```

### Als Werkzeug für ein LLM / einen Agenten

zing ist dafür gebaut, von einem anderen Programm oder Modell gesteuert zu werden. Alles
geht als JSON nach stdout, auch Fehler, und der Exit-Code dient als Schranke.

```bash
# schlankes, agentenfreundliches Urteil (~5x kleiner als --json: ohne umfangreiche Belege)
zing check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# vollständiger strukturierter Bericht, wenn Sie die Belege jedes Befunds brauchen
zing check --base-url ... --model gpt-4o --json

# erst das Budget: welche Detektoren laufen + geschätzte API-Aufrufe, OHNE einen auszuführen
zing check --base-url ... --model gpt-4o --suite deep --dry-run --json

# Schranke über den Exit-Code (1 bei Risiko >= medium); Konfigurations-/Aufruffehler enden mit 2, als JSON
zing check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# maschinenlesbare Erkundung
zing kb --json                 # die gesamte Wissensbasis
zing models --base-url ... --json   # was ein Endpunkt bewirbt
```

Im Modus `--json`/`--compact` gibt eine fehlerhafte Konfiguration `{"error": {...}}`
(Exit-Code 2) statt einer Meldung für Menschen aus, sodass eine Pipeline Fehler
einheitlich auswerten kann.

## Weboberfläche (`zing serve`)

Lieber klicken? Eine lokale Weboberfläche nutzt dieselbe Engine — ganz ohne
Kommandozeile.

```bash
pip install 'zing-audit[web]'     # oder: uv tool install 'zing-audit[web]'
zing serve            # öffnet http://localhost:8000
```

Geben Sie ein Relay und das beworbene Modell ein; verfolgen Sie die Prüfung **live**
(Fortschritt je Detektor per SSE) und lesen Sie anschließend einen teilbaren
Urteilsbericht (Note, Aufschlüsselung je Dimension, Befunde in verständlicher Sprache,
herunterladbares JSON). Alles läuft auf Ihrem Rechner — ein im Browser eingegebener
Schlüssel erreicht nur Ihren lokalen Server und das geprüfte Relay, niemals Dritte.
Standardmäßig wird nur an `127.0.0.1` gebunden.

Ein Sprachmenü in der Kopfzeile jeder Seite schaltet die Oberfläche zwischen
**🇬🇧 Englisch** (Standard), **🇨🇳 Chinesisch** (die ursprüngliche Oberfläche),
**🇫🇷 Französisch**, **🇪🇸 Spanisch**, **🇵🇹 Portugiesisch**, **🇮🇹 Italienisch** und
**🇩🇪 Deutsch** um; die Wahl wird pro Browser gespeichert. Aus der Oberfläche
heruntergeladene Berichte (**Bericht herunterladen (JSON)**) folgen ebenfalls der
gewählten Sprache: JSON-Schlüssel, Enum-Werte (`risk_level`, `status`, `severity`, …),
IDs und Belege bleiben exakt wie im Bericht der CLI (es ist weiterhin ein gültiger
zing-Bericht), während die für Menschen lesbaren Werte (Überschrift/Zusammenfassung des
Urteils, Titel/Zusammenfassungen der Befunde, Empfehlungen, Detektornamen, Hinweise)
übersetzt werden und der Dateiname die Sprache trägt (`zing-report.de.json`). Die
Berichte der CLI mit `--format json|md|html|pdf` bleiben englisch.

**An den geprüften Endpunkt gesendete Prompts folgen nicht der Sprache der
Oberfläche.** Jeder Text, den zing an eine LLM-API sendet — Chat-Tests, der Prompt des
LLM-Richters, Tool-Schemata, Eingaben für Embedding / Rerank / Bild / Audio — liegt in
einer einzigen Prompt-Bibliothek, `zing/prompts/en.json`, und ist englisch, damit
dasselbe Relay dasselbe Urteil erhält, egal wer den Bericht liest (Antwortprüfungen und
Token-Schätzungen sind auf genau diese Texte kalibriert). Die einzigen Ausnahmen sind
Fingerabdrücke der Wissensbasis, deren Sprache *selbst* die Messgröße ist — z. B. die
Tests zu chinesischer Sprachgewandtheit, Tokenizer und Selbstidentifikation
chinesischer Modelle —, die in `zing/knowledge/data/*.yaml` `prompt_lang` und einen
`language_bound`-Grund angeben. Jeder Bericht vermerkt die tatsächlich verwendeten
Testsprachen (`prompt_languages`, z. B. `["en", "zh"]`).

Die Übersetzungen sind Daten, die sich Weboberfläche und Webhook-Warnungen teilen:
`zing/i18n/locales/<code>.json`, eine Datei pro Sprache. Um eine Sprache hinzuzufügen,
legen Sie eine Datei an (kopieren Sie `de.json`); Sprachmenü, Seiten und Warnungen
übernehmen sie automatisch. `tests/test_web_locales.py` schlägt fehl, bis jeder Text der
Oberfläche und jeder Befund mit intakten Platzhaltern und intaktem Markup übersetzt ist.

## Was geprüft wird

zing bewertet zehn Dimensionen. Die drei, die eine Mogelpackung am direktesten
aufdecken (Modellidentität, tatsächliches Kontextfenster, beworbene Fähigkeiten), werden
am stärksten gewichtet.

| Dimension | Was sie aufdeckt |
|---|---|
| **model_identity** | Stillschweigende Herabstufung/Austausch des Modells — Selbstidentifikation, Wissensstichtag, Tokenizer-Fingerabdrücke, das zurückgegebene `model`-Feld |
| **context_window** | Stillschweigende Kontextkürzung (1M beworben, Abruf scheitert bei 32K) und „Lost in the Middle“ durch billige RAG-/Zusammenfassungs-Zwischenschichten, per Nadel im Heuhaufen + binärer Suche |
| **capability** | Beworbene Fähigkeiten für Tool-Calling / JSON-Modus / json-schema / maximale Ausgabe, die tatsächlich nicht geliefert werden (oder *über*erfüllt werden, ein Hinweis auf ein Ersatzmodell); dazu **Vision** — ein Modell, das Bildeingabe bewirbt, erhält ein generiertes Bild mit bekannter Antwort, um zu bestätigen, dass es tatsächlich „sieht“ |
| **billing** | Aufgeblähte Token/Nutzung und fehlende/nicht überprüfbare Nutzungsabrechnung, per unabhängiger Tokenizer-Schätzung |
| **streaming** | Vorgetäuschtes Streaming (erst puffern, dann zerstückeln), erkannt an der Anzahl der Chunks und ihrem zeitlichen Abstand |
| **protocol** | Konformität zur OpenAI-Kompatibilität: Mehrfachdialoge, Stoppsequenzen, Antwortstruktur, Fehlerschema — sowie eine Determinismus-Teilprüfung auf Antwort-Caches, die temperature/seed ignorieren |
| **reliability** | Erfolgsquote bei Parallelität und Latenz (HTTP-429-Drosselung wird gesondert gezählt) |
| **performance** | Wie *gleichmäßig* Latenz, Zeit bis zum ersten Token und Durchsatz sind, Fehlerquote der Messung und Verlangsamung unter Last; das Tempo selbst nur im Vergleich zu einer Referenz |
| **connectivity** | Erreichbarkeit des Endpunkts und die beworbene `/v1/models`-Liste |
| **security** | Transport (HTTPS), Header-Hygiene, Echo von Geheimnissen; versteckt injizierter System-Prompt (fester Mehraufwand an Eingabe-Token + Leck), Manipulation von Antworten/Tool-Calls unterwegs per Kanarien mit bekannter Antwort (URL-/Paketaustausch) und Prompt-Präfix-Caching (Timing) |

Siehe [docs/METHODOLOGY.md](docs/METHODOLOGY.md) für die Technik hinter jeder Prüfung,
den Relay-Trick, dem sie entspricht, und ihre Einschränkungen bezüglich Fehlalarmen.

### Performance

Jeder Bericht enthält außerdem einen Abschnitt **performance**: Latenz, Zeit bis zum
ersten Token (TTFT), Decode- und End-to-End-Token/s, Latenz und Jitter zwischen Chunks,
Fehler-/Timeout-/429-Raten, eine Netzwerkaufschlüsselung (TCP-Verbindung, TLS, ein
`GET /models`-Roundtrip, Serverzeit) und Kaltstart, jeweils als
count / min / mean / p50 / p75 / p90 / p95 / p99 / max / stdev. Läuft die eigene Messung, bewertet sie die Dimension **performance** (Gewicht 6) — nach *Gleichmäßigkeit* von Latenz, TTFT und Durchsatz, Fehlerquote und Verhalten unter Last, nicht nach reiner Geschwindigkeit; ein langsames, aber gleichmäßiges (z. B. lokales) Modell wird nicht abgewertet. Das Tempo selbst zählt nur im Vergleich zur Referenz (Baseline oder veröffentlichter Bereich in der Wissensbasis). Die Befunde sind höchstens von niedrigem Schweregrad und ändern nie das Risikourteil.

- **standard** erhebt ihn aus den eigenen Anfragen der Prüfung.
- **deep / full** fügen einen eigenen Test hinzu: 100 nicht cachebare Anfragen mit 128
  Ausgabe-Token (eine zufällige Anfrage-ID eröffnet jeden Prompt, es werden keine Cache-
  oder Reasoning-Parameter gesendet) sowie einen Burst mit `--concurrency`. Einstellbar
  über `--performance-requests` (0 deaktiviert ihn) und `--performance-max-tokens`.
- Der Test streamt standardmäßig; `--performance-non-streaming` (oder der Schalter in der
  Weboberfläche) misst Relays, die nicht streamen können. **full** misst beide Modi,
  verschränkt, und stellt sie nebeneinander dar.
- **compare** führt den Test auf beiden Endpunkten mit abwechselnden Anfragen aus und
  ergänzt eine Tabelle Ziel-vs.-Referenz (5 Anfragen je Seite bei `standard`), deren
  Unterschiede grün ✓ markiert sind, wo das Ziel besser ist, und rot ✗, wo es schlechter
  ist. Ein Ziel, das mehr als 2x schneller generiert als die Referenz, wird als Hinweis
  geringer Schwere markiert.

Token werden doppelt gezählt: aus der `usage` des Relays und lokal, sodass der Durchsatz
auch ohne `usage` messbar ist. Ein Perzentil wird nur bei ausreichend Stichproben
angezeigt (p90 ab 10, p95 ab 20, p99 ab 100). Der JSON-Bericht speichert die Zeiten jeder
Anfrage (nur Zahlen, kein Text); HTML-Bericht und Weboberfläche stellen sie entlang der
Zeitachse der Prüfung dar.

## Zwei Erkennungsmodi

- **Reiner Code (Standard):** alle deterministischen Tests — Fingerabdrücke,
  Kontext-Durchlauf, Abrechnungsberechnung, Streaming-Timing. Kein zweites Modell
  nötig; vollständig reproduzierbar.
- **Hybrid aus Code + LLM (`--judge`):** zieht zusätzlich ein *vertrauenswürdiges*
  Richtermodell hinzu (separat konfiguriert, niemals das Ziel), um unscharfe Signale wie
  Qualität und Denktiefe zu bewerten, die reiner Code nicht entscheiden kann. Treibt den
  Detektor `quality_judge` an.

```bash
zing check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

## Überwachung (`zing watch`)

Ein Relay kann heute das echte Modell liefern und es nächste Woche stillschweigend
austauschen. `zing watch` wiederholt die Prüfung nach Zeitplan, speichert jeden Lauf im
Verlauf und alarmiert einen Webhook, wenn das Risiko eine Schwelle überschreitet oder
sich gegenüber dem vorherigen Lauf **verschlechtert**.

```bash
zing watch --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang de                                     # oder --once für cron
```

Warnungen werden für **Slack / Feishu / DingTalk / generisches JSON** formatiert,
automatisch anhand der Webhook-URL erkannt, und in der Warnsprache verfasst —
standardmäßig Englisch; `--alert-lang en|zh|fr|es|pt|it|de`. Die generische JSON-Nutzlast
hält ihre Schlüssel und Maschinenwerte (`risk_level`, `score`, …) sprachneutral,
übersetzt die für Menschen lesbaren (`text`, `headline`, `key_findings`) und gibt die
`language` an.

Lieber eine Oberfläche? `zing serve` bringt unter **`/watches`** (🔔 Überwachung) einen
Monitor mit: Legen Sie im Browser eine Überwachung an, und ein Hintergrund-Scheduler im
selben Prozess führt sie in ihrem Intervall erneut aus, speichert jeden Lauf im Verlauf
und löst dieselben Webhook-Warnungen bei Schwellenüberschreitung oder Verschlechterung
aus. Jede Überwachung hat ihre eigene Warnsprache (im Formular gewählt, standardmäßig die
Sprache der Oberfläche, und auf ihrer Karte änderbar). Jetzt ausführen / pausieren /
löschen direkt auf der Seite. Schlüssel werden nur in `~/.zing` gespeichert und nie an
den Browser zurückgegeben.

## Embedding- & Rerank-Prüfungen

Embeddings und Rerank sind keine Chat-Schnittstelle, daher prüft zing sie mit einem
eigenen, fokussierten Prüfer statt mit der Chat-Pipeline mit 9 Dimensionen.

```bash
# Die erwartete Vektordimension wird für das beworbene Modell aus der mitgelieferten Wissensbasis ermittelt.
zing embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Oder die erwartete Dimension direkt vorgeben:
zing embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: ein eingebauter Test mit bekannter Antwort — ein echter Reranker muss das
# offensichtlich relevante Dokument an erster Stelle einordnen.
zing rerank --base-url https://relay.example.com/v1 --model my-rerank
```

`embed` prüft Konnektivität, **Übereinstimmung der Dimension** (Länge des
zurückgegebenen Vektors gegenüber der nativen Dimension des beworbenen Modells — das
Hauptsignal für eine Mogelpackung; ein Relay, das `text-embedding-3-large` mit 3072-d
bewirbt, aber 1024-d zurückgibt, liefert ein Ersatzmodell), Determinismus (gleiche
Eingabe → Kosinus ≈ 1), Unterscheidbarkeit (unzusammenhängende Eingaben → Kosinus
deutlich unter 1) und das zurückgegebene `model`-Feld. Mitgelieferte Profile: OpenAI
`text-embedding-3-small` (1536), `text-embedding-3-large` (3072),
`text-embedding-ada-002` (1536), Qwen `text-embedding-v3`/`-v4` (1024).

Beide gibt es auch in der Weboberfläche — `zing serve` hat eine Seite **Werkzeuge**
unter `/tools` (in der Navigation verlinkt) mit Formularen für embed/rerank, die dasselbe
lokalisierte Urteil anzeigen.

## Prüfungen für Bild- & Audio-Generierung (TTS)

Zwei weitere Nicht-Chat-Schnittstellen: Bildgenerierung (`POST /v1/images/generations`)
und Sprachsynthese (`POST /v1/audio/speech`). Die gesamte Dekodierung erfolgt mit der
reinen Standardbibliothek — Bildabmessungen aus den Header-Bytes (PNG/JPEG/GIF/WebP),
WAV-Dauer über das Modul `wave`.

```bash
# Liefert ein Relay, das DALL·E 3 bewirbt, wirklich das angeforderte 1792x1024? Ein
# verkleinertes Bild / eines in falscher Größe (oder eine Größe außerhalb der nativen Größen
# des beworbenen Modells, ermittelt aus der Wissensbasis) ist das Hauptsignal für eine Mogelpackung.
zing image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Liefert ein Relay, das tts-1-hd bewirbt, echtes Audio, dessen Länge mit der Eingabe
# wächst (kein fester Platzhalter, kein als Audio getarntes HTML/JSON)?
zing audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --format wav --save clip.wav
```

`image` prüft: Konnektivität, gültiges/dekodierbares Format, **Übereinstimmung der
Größe** (dekodierte BxH gegenüber der Anfrage und den nativen Größen des beworbenen
Modells — FAIL/HIGH bei Abweichung), Unterscheidbarkeit (zwei Prompts → verschiedene
Bilder, um einen festen Platzhalter zu entlarven), Anzahl, model-Feld. `audio` prüft:
Konnektivität, Gültigkeit von Container/Format, Einhaltung des Formats, nicht triviale
Dauer (wächst mit der Eingabelänge), Unterscheidbarkeit, model-Feld. Die Wissensbasis
enthält OpenAI DALL·E 2/3, gpt-image-1, tts-1/tts-1-hd/gpt-4o-mini-tts sowie Bild-/TTS-
Profile von Qwen.

## Einsatz in CI (GitHub Action)

Machen Sie jeden Workflow mit der mitgelieferten Composite Action von einer
Relay-Prüfung abhängig. Sie führt `zing check --compact --fail-on-risk` aus, stellt
`risk` / `score` / `rating` als Ausgaben bereit, schreibt eine Zusammenfassung in den
Lauf und lässt den Job fehlschlagen, wenn die Risikoschranke auslöst.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: zing
        uses: cenbonew/zing@v0.9.0          # auf ein Release-Tag festlegen
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # Secret des Aufrufers; wird nie ausgegeben
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.zing.outputs.risk }} score=${{ steps.zing.outputs.score }}"
```

Der Relay-Schlüssel wird über eine Umgebungsvariable weitergereicht (`--api-key env:…`)
und erscheint daher nie auf einer Kommandozeile. Siehe [docs/CI.md](docs/CI.md) für die
vollständige Tabelle der Ein- und Ausgaben sowie ein Beispiel für eine
Deployment-Schranke.

## Suiten

| Suite | Detektoren | Kosten |
|---|---|---|
| `smoke` | connectivity, security | sehr gering |
| `standard` | + protocol, model_identity, capability, streaming, billing, reliability | gering–mittel |
| `deep` | + context_window, determinism, injected_prompt, integrity, performance, prompt_cache, quality_judge (mit `--judge`) | höher (Langkontext- und Timing-Tests kosten Token) |
| `full` | alles | am höchsten |
| `custom` | nur die gewählten Dimensionen, in `deep`-Tiefe | je nach Auswahl |

**Benutzerdefinierte Suite:** `zing check ... -D protocol -D performance` (oder `--suite custom --dimension billing,streaming`, in der Konfiguration `run.dimensions`) führt nur die gewählten Dimensionen aus. Die Gesamtbewertung ist das gewichtete Mittel allein dieser Dimensionen; ohne Kerndimension (Modellidentität, Kontextfenster, Fähigkeiten) ist das Risikourteil *nicht eindeutig*. Die Web-UI bietet dieselbe Auswahl.

Der Kontextfenster-Test ist durch `--max-context-tokens` (Standard 200K) begrenzt,
sodass die Prüfung eines Modells mit 1M Token bezahlbar bleibt.

## Beispielurteil

```text
╭─ ✗ HIGH RISK — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · confidence medium                             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • Gibt sich unter der beworbenen Modell-ID gpt-4o als Konkurrenzmarke (anthropic) aus
  • Tatsächliches Kontextfenster ~8000 << angegebene 128000 (stillschweigende Kürzung vermutet)
  • Gemeldete Prompt-Token übersteigen die unabhängige Schätzung deutlich
```

Berichte werden als JSON, Markdown und HTML nach `reports/` geschrieben – mit dem Extra `pdf` zusätzlich als PDF.

## Wissensbasis

Die Profile liegen in [`zing/knowledge/data/`](zing/knowledge/data) als bearbeitbares
YAML — eine Datei pro Anbieter (OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM,
Moonshot). Jedes Modell enthält sein natives Kontextfenster, die maximale Ausgabe, den
Tokenizer, Fähigkeits-Flags, Identitäts-Schlüsselwörter und Verhaltens-Fingerabdrücke.
Profile lassen sich ohne Fork ergänzen oder überschreiben:

```bash
zing check --kb-dir ./my-profiles ...     # oder ZING_KB_DIR setzen
```

## Verantwortungsvoller Einsatz

zing ist ein Hilfsmittel für Black-Box-Prüfungen. Es **kann nicht beweisen**,

- dass ein Anbieter Ihre Prompts speichert oder damit trainiert,
- dass er immer an genau ein bestimmtes Modell weiterleitet (Relays können probabilistisch routen),
- Abrechnungsbetrug über das hinaus, was die unabhängige Token-Schätzung nahelegen kann.

Nutzen Sie die Berichte für Ihre eigene Sorgfaltsprüfung. **Beschuldigen Sie einen
Anbieter nicht öffentlich** auf Grundlage eines einzelnen Laufs, ohne
Stichprobengröße, Kosteneinstellungen und lokales Recht zu prüfen. Führen Sie
`zing compare` gegen eine vertrauenswürdige Referenz aus, bevor Sie weitreichende
Schlüsse ziehen.

## Lizenz

[Apache-2.0](LICENSE)
