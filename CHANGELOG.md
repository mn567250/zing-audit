# Changelog

All notable changes to **zing** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Web UI v2, served side by side with the classic UI for A/B comparison.**
  `/v2/`, `/v2/history`, `/v2/watches`, `/v2/tools` and `/v2/console` rebuild
  every page in the same design language on one shared stylesheet and header.
  Colours meet WCAG AA contrast, the pages have a dark theme, respect reduced
  motion and have no horizontal scroll on phones. Accessibility covers
  segmented controls, disclosures, tabs, meters and the live log. Every page
  uses the same vocabulary ("Model to request" / "Claimed model", which the
  classic audit page had reversed), risk labels and localized dates. All pages
  offer the Responses protocol and the `full` suite, except the tools page,
  which has no embedding/rerank support for them. `?ui=v2` or `?ui=v1` on any
  page picks a UI and a cookie remembers it. Classic pages have a "Try the new
  UI" link and v2 pages a "Classic UI" link back.
- **Locale fragments**: `zing/i18n/locales/fragments/<feature>/<code>.json` add
  UI strings to a language without editing the main locale files.
- **Masked API key fields in the web UI.** Every key input is now a password
  field with a show/hide eye toggle, so keys stay hidden on screen shares.
  `env:`/`file:` references start revealed, and a literal key is re-masked when a
  run starts. The relay `base_url` acts as the username, so the browser's password
  manager can save and fill one key per relay.
- **README translations** in French (`README.fr.md`), Spanish (`README.es.md`),
  Portuguese (`README.pt.md`), Italian (`README.it.md`) and German
  (`README.de.md`), linked from a language switcher at the top of every README.
  The English `README.md` no longer contains Chinese text, and `README.zh-CN.md`
  is brought up to date with it.
- **Performance section in every report.** Latency, time to first token, decode
  and end-to-end tokens/s (from the relay's `usage` and from a local token count),
  inter-chunk latency and jitter, error/timeout/429 rates, a network breakdown
  (TCP connect, TLS, `GET /models` round trip, server time) and cold start, as
  count/min/mean/p50/p75/p90/p95/p99/max/stdev. Percentiles are shown only with
  enough samples. Informational: it never changes the score or the verdict. The
  JSON report adds `performance` with every request's timings (numbers only).
- **Performance probe** (`performance` detector, deep/full, and standard in compare
  mode): uncacheable streaming requests (default 100 × 128 tokens, a random
  request id opens each prompt, no cache or reasoning parameters), `GET /models`
  pings, a warm-up reported as cold start, and a concurrency burst. Compare mode
  alternates target and baseline requests and adds a target-vs-baseline table,
  with each difference marked green ✓ (target better) or red ✗ (target worse).
  The probe streams by default; `--performance-non-streaming` (a switch in the web
  UI) measures relays that cannot stream, and the full suite measures both modes.
  New flags `--performance-requests` / `--performance-max-tokens` /
  `--performance-streaming`; `--dry-run` counts the probe's calls. The web UI's
  suite picker gains `full`.
- **Charts.** The HTML report draws the chosen metric per request over the audit's
  timeline (inline SVG, no scripts). The web UI shows the same chart live while an
  audit runs, the full section in the report and in `/history`, and a latency
  trend per target.

- **Web UI: custom provider with live model fetch.** The model picker's provider
  list gains **Custom (from relay)**. With a base_url filled in, **Fetch models**
  calls the new `POST /api/models`, which lists the relay's own `/models`. You
  see right away whether the connection works (model count, or the HTTP error)
  and can pick an id the relay really accepts instead of typing it. The pick goes
  into the requested `model` field. The API key is optional, so keyless
  self-hosted endpoints such as Ollama or LM Studio work too.
- **Web UI: language switch.** Every page (`/`, `/console`, `/history`, `/tools`,
  `/watches`) gets a **🇬🇧 EN · 🇨🇳 CN · 🇫🇷 FR · 🇪🇸 ES · 🇵🇹 PT · 🇮🇹 IT · 🇩🇪 DE**
  dropdown in its header; English is the default. Every user-facing string is translated (labels,
  placeholders, tooltips, dialogs, verdicts, finding titles/summaries, detector names,
  recommendations, status codes, the model picker); CN keeps the original Chinese UI
  unchanged. Switching is live (no reload) and remembered in `localStorage`. Backed
  by new shared `/lang.js` and `/locales.js`. The dropdown is generated from a single
  language registry, a new language is one registry entry plus one translation block,
  and `tests/test_web_locales.py` enforces that every language is complete.
- **Web UI: downloaded reports follow the UI language.** "Download report (JSON)" (on
  `/` and in `/history`) translates every human-readable value — verdict headline and
  summary, key findings, finding titles/summaries/recommendations, detector names,
  dimension reasons, notes — into the selected language (CN included), keeping the
  JSON keys, enums, ids and evidence unchanged so the file still validates as a zing
  `AuditReport`; the file name carries the language (`zing-report.<lang>.json`).

- **Webhook alerts in the monitor's language.** Alerts from `zing watch` and the
  `/watches` monitors were always Chinese (with the verdict headline and key findings in
  English). They are now written entirely in the alert language — English by default,
  or any supported language: `zing watch --alert-lang <code>`, and a per-monitor
  **Alert language** in the web UI (stored in `~/.zing`; existing monitors are migrated
  and send English). The generic JSON payload gains a `language` field; its other keys
  and machine values are unchanged.
- **Translations are shared data.** All translations now live in
  `zing/i18n/locales/<code>.json`, used by the web UI (served as `/locales.js`) and by
  Python (`zing.i18n`, for alerts). Adding a language is adding one file.

- **Prompt library.** Every text sent to an LLM API (chat probes, the judge prompt,
  tool schemas, embedding / rerank / image / audio inputs — 53 entries) moved out of the
  code into `zing/prompts/en.json`, loaded via `zing.prompts`. Probes are English and
  independent of the UI/alert language, so verdicts don't depend on who reads them; a
  capture of every request of a full audit is byte-identical before and after the move
  except the vision probe (below). Knowledge-base fingerprints gained `prompt_lang` and
  `language_bound`: the 7 Chinese probes of China-native models (fluency, tokenizer
  echo, native self-id, cultural recall) stay Chinese because the language is the
  measurement, and must say so. Reports gain `prompt_languages`, shown in the web UI.

### Changed

- **Vision probe asks in English only.** It was bilingual
  ("仅用一个词回答：图片是什么颜色？/ In one word, what color is this image?"); Chinese
  answers are still accepted.
- **Web UI language menu shows language names** (English, 中文, Français, …)
  instead of flags, and the Chinese UI now translates backend text (verdict
  summaries, recommendations, detector names) like the other languages.
- **Performance panel**: every colour is themeable, tabs are keyboard- and
  screen-reader-accessible, charts have a text summary and a data table, and
  numbers use the UI language's format.

### Fixed

- **Web UI: a page no longer stays blank if a script fails** while loading.
- **Classic audit page: the "Insufficient signal" badge had no background**
  (an invalid colour token).
- **`zing serve --help` dropped `[web]`** from the install hint (Rich markup).
- **Web UI: finding summaries that fell back to English.** Findings emitted by several
  detector branches (pass / warn / inconclusive, request failures) had no matching
  translation template, so their summary appeared in English even in the Chinese UI;
  `embed.dimension` without a known claimed dimension read "should produce 0-d".
  Branch-specific and generic "request failed" templates now cover them.

## [0.11.0] — web UI: claimed-model picker + all-SVG icons

### Added

- **Web UI: claimed-model picker.** The “claimed model” field is now a provider → model
  picker driven by the bundled knowledge base (pick e.g. *DeepSeek* then
  *deepseek-v4-flash*) instead of free typing, with a **自定义输入** toggle that falls back
  to a plain text box for unlisted ids. Wired into the audit form, the advanced console,
  the watch form, and the embeddings tool. Backed by a new `GET /api/kb` endpoint
  (public model metadata only — no secrets).

### Changed

- **Web UI: all emoji replaced with SVG icons.** A single canonical inline-SVG icon set
  (`/icons.js`, `window.zingIcon`) renders every glyph — logo, nav (tools/history/watch),
  lock, status check/cross/info, arrows, carets, run/delete/etc. — as crisp,
  `currentColor` line icons across all pages, replacing the previous emoji.

## [0.10.0] — image/audio generation audits, embeddings/rerank in the web UI

### Added

- **Image & audio (TTS) generation audits (`zing image` / `zing audio`).** Two more
  non-chat surfaces. `image` (POST `/v1/images/generations`) checks the returned bytes
  are a valid, decodable image and that the **decoded dimensions match the requested
  size and the claimed model's native sizes** (a downscale/wrong-size is the headline
  货不对板 signal), plus distinctness (two prompts → different images, catching a fixed
  placeholder), count, and the echoed model. `audio` (POST `/v1/audio/speech`) checks
  the bytes are valid audio of the requested container, non-trivial (WAV duration > 0
  and scales with input length), format-honored, and distinct. All decoding is pure
  stdlib (PNG/JPEG/GIF/WebP header parsing; the `wave` module) — no Pillow/numpy. KB
  gained `image_sizes` / `audio_voices` and profiles for OpenAI DALL·E 2/3, gpt-image-1,
  tts-1/tts-1-hd/gpt-4o-mini-tts, plus Qwen image/TTS.
- **Embeddings & rerank in the web UI (`/tools`).** `zing serve` gains a 工具箱 / Tools
  page (linked from the nav) wrapping the existing embedding/rerank auditors: `POST
  /api/embed` and `POST /api/rerank`. Enter a relay + model and get a localized risk
  badge, score, and findings table; the dimension mismatch is surfaced as the headline
  signal (the expected dimension is resolved from the KB when left blank). Rerank uses a
  built-in known-answer probe by default, with an advanced panel for a custom query/docs.
  Keys stay local and are never echoed back to the browser. Verified live against Aliyun
  text-embedding-v4.

### Fixed

- **Flaky embedding test.** `tests/test_embed.py`'s mock seeded vectors with the builtin
  `hash()` (salted by `PYTHONHASHSEED`), so two distinct inputs could collide mod 1000
  and collapse the distinctness check, failing intermittently in CI. The mock now derives
  a process-stable key via `hashlib` and uses a per-input spike vector, so distinct
  inputs are reliably near-orthogonal — deterministic across all hash seeds.

## [0.9.0] — embedding/rerank audits, web-UI monitoring, CI Action

### Added

- **Embedding & rerank audits (`zing embed` / `zing rerank`).** A focused auditor for
  the non-chat surface, separate from the 9-dimension chat pipeline. `embed` checks
  connectivity, **dimension match** (returned vector length vs the claimed model's
  native dimension — the headline 货不对板 signal; e.g. a relay claiming 3072-d
  `text-embedding-3-large` but returning 1024-d is flagged HIGH), determinism (same
  input → cosine ≈ 1), distinctness (unrelated inputs → cosine well below 1), and the
  echoed `model` field. `rerank` runs a known-answer probe (the obviously-relevant
  document must rank first). Both support `--json` and `--fail-on-risk`. KB gained an
  `embedding_dimensions` field and profiles for OpenAI `text-embedding-3-small`/`-large`/
  `ada-002` and Qwen `text-embedding-v3`/`-v4`. Verified live against Aliyun
  text-embedding-v4 (honest → 100/100; sold as `-3-large` → HIGH dimension mismatch).
- **Monitoring in the web UI (`/watches`).** `zing serve` now has a built-in monitor:
  add a watch (target + suite + interval + alert threshold + webhook URLs) and an
  in-process background scheduler re-runs each enabled watch on its interval, persists
  every run to history, and POSTs a Chinese alert to your webhooks when risk crosses
  the threshold or regresses. Run-now / pause / delete from the page. API keys are
  stored only in `~/.zing` and never returned to the browser or shown in the listing.
  Vision findings are now localized to Chinese in the report.
- **GitHub CI Action.** A bundled composite action (`uses: cenbonew/zing@vX.Y.Z`) gates
  any workflow on a relay audit: runs `zing check --compact --fail-on-risk`, exposes
  `risk`/`score`/`rating` outputs, writes a run summary, and fails the job when the gate
  trips. The relay key is passed via a secret and never echoed. See `docs/CI.md` and the
  example workflow.

## [0.8.0] — Responses API, vision audit, monitoring

### Added

- **OpenAI Responses API (`/v1/responses`).** A third wire protocol behind the same
  detector interface: `--api responses` (auto-detected when the base_url path ends in
  `/responses`). Translates to/from `input`/`instructions`/`output` + `input_tokens`/
  `output_tokens` usage; handles streaming and tool calls.
- **Multimodal (vision) detector.** When a model claims vision, zing sends a
  known-answer generated image (a solid-color PNG built with the stdlib) and checks
  the model actually "sees" it — catching a relay that claims vision but routes to a
  text-only substitute. Builds the image part per protocol (OpenAI / Anthropic /
  Responses). Verified live against `qwen3-vl-plus`.
- **Monitoring: `zing watch` + webhook alerts.** Re-audits a relay on a schedule
  (`--interval`, or `--once` for cron), persists each run to history, compares against
  the previous run, and POSTs a concise alert to `--webhook` when risk crosses
  `--alert-on` or regresses. `zing/notify.py` formats alerts for Slack, Feishu (飞书),
  DingTalk (钉钉), or a generic JSON webhook (auto-detected from the URL).
- Web console now supports **compare against a baseline** (the form sends a baseline
  endpoint; the server runs `compare` mode for a corroborated verdict).

## [0.7.0] — web: Chinese findings, history/trends, advanced console

### Added

- **Findings localized to Chinese (web UI).** A new `zing/web/static/i18n.js` catalog
  maps every finding `id` (~65) to a zh title + a zh summary template filled from the
  finding's evidence (falling back to the English summary when a key is absent). The
  report and the live feed now show findings in Chinese.
- **Audit history & trends.** `zing serve` persists every audit to a local SQLite DB
  (`$ZING_DATA_DIR` or `~/.zing/history.db`, stdlib only — no new dep). New endpoints
  (`/api/history`, `/api/history/{id}`, `/api/history/trend`, DELETE) and a `/history`
  page that lists past audits grouped by target+model with a score sparkline; click a
  row to view that saved report. History never leaves your machine.
- **Advanced console view (`/console`).** A dark, power-user UI (ported from the
  console prototype) wired to the same live SSE: terminal-style detector log with
  click-to-expand evidence, dimension bars, and a verdict ring. Linked from the
  default report view; the report view links to history.

## [0.6.0] — web compare + live evidence

### Added

- **Web UI: `compare` against a trusted baseline.** The form has an optional baseline
  section (base_url / key / model / protocol); when filled, the audit runs in
  **compare** mode so the verdict gets baseline corroboration (quality_judge and
  integrity can escalate). The report shows the baseline and `mode: compare`.
- **Web UI: live evidence feed.** The scan now streams each detector's findings and
  evidence as it completes (the `detector_done` SSE event carries a compact, bounded
  findings list), so notable findings appear in real time — e.g. *"Self-identifies as
  a rival brand — self-id said: I'm Doubao, by ByteDance"* — instead of just status
  dots. `run_audit`'s `on_event` callback now includes per-detector findings.

## [0.5.0] — local web UI (`zing serve`)

### Added

- **`zing serve` — a local web UI.** A point-and-click front end for `zing check`:
  enter a relay + the model it claims, watch the audit stream **live** (a radar scan
  with per-detector progress over SSE), then get a shareable verdict report (grade,
  per-dimension breakdown, plain-language findings, downloadable JSON). Runs entirely
  on your machine — keys typed in the browser reach only your local server and the
  target relay, never a third party. New optional extra: `pip install 'zing-audit[web]'`
  (fastapi + uvicorn). `run_audit` gained an `on_event` progress callback that powers
  the live stream.

## [0.4.0] — agent/LLM ergonomics

Make zing pleasant to drive from another program or model.

### Added

- **`--compact`** (`check`/`compare`) — a lean, agent-facing JSON verdict on stdout:
  verdict + per-dimension status + a flat findings list, *without* the bulky
  per-finding evidence. ~66% smaller than `--json` (a standard report drops from
  ~5.2k to ~1.8k tokens).
- **`--dry-run`** (`check`/`compare`) — print the detectors that would run and an
  estimated API-call count (honoring `--reliability-requests`) **without making any
  requests**, so an agent can budget cost first. Each detector now carries a
  `cost_hint`.
- **`kb --json`** and **`models --json`** — machine-readable discovery of the bundled
  knowledge base and of an endpoint's advertised model list.
- **Structured errors in machine mode.** In `--json`/`--compact` mode a config/usage
  error now prints `{"error": {...}}` to stdout (exit 2) instead of a human message,
  so a pipeline can parse failures uniformly.
- Top-level `--help` now documents the agent flags.

## [0.3.0] — accuracy pass on real relays (DeepSeek / Doubao)

Validated against live endpoints (DeepSeek official + Aliyun, Volcengine, …): honest
DeepSeek relays now read CLEAN, and Doubao models passed off as DeepSeek are caught HIGH.

### Added

- **`--claimed-model`** — audit an endpoint's *real* model id against a *different*
  claimed model's profile (e.g. request `doubao-seed-...` but verify it against the
  `deepseek-v4-flash` profile). Lets you confirm a suspected substitution end-to-end.

### Fixed

- **Billing false positives on reasoning models / non-OpenAI tokenizers.** A reasoning
  model's `completion_tokens` legitimately includes hidden reasoning tokens the
  visible-text estimate can't see, and heuristic (non-tiktoken) estimates are
  imprecise — these no longer produce a "token inflation" HIGH. Prompt-token thresholds
  widen for heuristic tokenizers, and prompt-padding is still checked when a reasoning
  model returns empty visible content. (DeepSeek official went MEDIUM → CLEAN.)
- **Substitution false negatives.** Model-identity now flags ANY known vendor brand
  that isn't the model's own — including Doubao/ByteDance, Kimi, GLM, Hunyuan, Ernie,
  MiniMax (with Chinese names) — so a substitute the per-model KB list never enumerated
  is still caught. (A "I'm Doubao, by ByteDance" relay sold as DeepSeek now reads HIGH.)
- KB: added DeepSeek's native brand name (深度求索) to the deepseek profiles so a
  genuine model using it isn't mis-flagged.

## [0.2.1]

### Fixed

- `zing --version` now reports the actual installed version. It was hardcoded in
  `zing/__init__.py` and reported `0.1.0` for the 0.2.0 release; the version is now
  single-sourced from package metadata (`importlib.metadata`) so it can never drift
  from `pyproject.toml`.

## [0.2.0] — Anthropic support & roadmap security detectors

### Added

- **Anthropic Messages API support.** zing now audits Anthropic-native relays
  (`/v1/messages`) as well as OpenAI Chat Completions, behind one detector
  interface. The protocol is auto-detected from the base_url/model or forced with
  `--api openai|anthropic` (and `--target-api` / `--baseline-api` for `compare`).
- **Three new `deep`-suite security detectors** (formerly roadmap):
  - `injected_prompt` — detects a hidden, silently-prepended system prompt from a
    large *fixed* input-token overhead (measured across two message sizes) plus a
    leak probe; needs both signals to warn.
  - `integrity` — known-answer URL/package canaries catch in-flight response/tool-call
    tampering (value substituted, structure preserved). CRITICAL only when a trusted
    baseline returns the canary intact; otherwise MEDIUM.
  - `prompt_cache` — flags prompt-prefix caching by TTFT timing (informational; states
    that cross-user cache sharing is not provable from a single key).
- Automated PyPI publishing via GitHub Actions + Trusted Publishing
  (`.github/workflows/release.yml`); see `docs/PUBLISHING.md`.

## [0.1.0] — first public alpha

First public release. A local-first CLI that audits whether an OpenAI-compatible
API relay (中转站 / reseller / proxy) actually serves the model it claims to —
or quietly substitutes a cheaper one, truncates the context window, fakes
streaming, or inflates token billing (货不对板检测).

### Added

- `zing check` — audit one relay endpoint against what it claims (model id +
  optional provider hint).
- `zing compare` — audit a relay against a trusted baseline of the same declared
  model (the strongest downgrade evidence).
- `zing models` — probe an endpoint's `GET /v1/models` list.
- `zing kb` — inspect the bundled knowledge base.
- `zing init` — write a starter `zing.yaml` config.
- Eleven detectors across nine scored dimensions: model identity & downgrade
  fingerprinting, real context window & truncation, capability claims, token/usage
  billing, streaming authenticity, OpenAI-protocol conformance, determinism/cache
  correctness, concurrent reliability, transport/secret-handling security, plus
  connectivity and an optional LLM-judged quality assessment (`--judge`).
- Bundled knowledge base of **85 native model profiles across 7 platforms**
  (OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM, Moonshot), editable as
  YAML and overridable via `--kb-dir` / `ZING_KB_DIR`.
- Two detection modes: pure-code deterministic probes (default) and a code+LLM
  hybrid that consults a separate trusted judge model.
- JSON, Markdown, and HTML reports; `--json` for machine/agent consumption.
- Evidence-first verdicts (CLEAN / LOW / MEDIUM / HIGH / INCONCLUSIVE) with
  confidence, designed to avoid false accusations of honest relays.
- Secret hygiene: API keys are fingerprinted (never stored) and relay-controlled
  text is redacted before it reaches any report (JSON/Markdown/HTML).
- `--fail-under` / `--fail-on-risk` exit-code gates for CI use.

[Unreleased]: https://github.com/cenbonew/zing/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/cenbonew/zing/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/cenbonew/zing/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/cenbonew/zing/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/cenbonew/zing/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/cenbonew/zing/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/cenbonew/zing/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/cenbonew/zing/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/cenbonew/zing/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/cenbonew/zing/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/cenbonew/zing/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/cenbonew/zing/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/cenbonew/zing/releases/tag/v0.1.0
