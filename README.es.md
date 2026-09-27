# zing — prueba de realidad para relays de LLM

> [🇬🇧 English](README.md) · [🇨🇳 中文](README.zh-CN.md) · [🇫🇷 Français](README.fr.md) · **🇪🇸 Español** · [🇵🇹 Português](README.pt.md) · [🇮🇹 Italiano](README.it.md) · [🇩🇪 Deutsch](README.de.md)

[![CI](https://github.com/cenbonew/zing/actions/workflows/ci.yml/badge.svg)](https://github.com/cenbonew/zing/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**zing** es una herramienta de línea de comandos local-first que audita si un relay de
API (revendedor / proxy) sirve realmente el modelo que anuncia — o si lo sustituye en
silencio por uno más barato, recorta tu ventana de contexto, simula el streaming o infla
la facturación de tokens. En resumen: ¿recibes lo que pagas? Habla **OpenAI Chat
Completions**, la **API Anthropic Messages** y la **API OpenAI Responses**
(`/v1/responses`) — con detección automática, o forzado con
`--api openai|anthropic|responses`.

Le indicas el endpoint de un relay y el modelo que anuncia; zing ejecuta una batería de
sondas de caja negra, compara el comportamiento observado con una base de conocimiento
integrada de **85 perfiles de modelos nativos en 7 plataformas** e imprime un veredicto
claro y respaldado por evidencias — para una persona, o en JSON para que otra
herramienta / LLM lo lea.

> zing aporta **evidencia de caja negra de divergencias y riesgos, no una prueba
> criptográfica de fraude.** Consulta [Uso responsable](#uso-responsable).

---

## Por qué

El mercado de claves de relay está lleno de ofertas de «GPT-4o a una décima parte del
precio». Muchas son honestas. Otras no — y las deshonestas son difíciles de detectar a
simple vista:

- Pides `gpt-4o`; en silencio te sirven `gpt-4o-mini` o un modelo abierto.
- El relay anuncia un contexto de 1M de tokens pero lo recorta en silencio a 32K.
- El «streaming» es la respuesta completa almacenada en búfer y vuelta a trocear, sin ganancia de latencia.
- Los tokens de `usage` reportados están inflados, así que tu saldo se agota más rápido de lo debido.
- Un modelo que debería admitir llamadas a herramientas / modo JSON en silencio no lo hace.

zing convierte «aquí algo no cuadra» en un informe reproducible.

## Instalación

Requiere Python 3.10+. Cada opción de abajo proporciona el comando `zing`.

### Con pip

```bash
# desde PyPI
pip install zing-audit

# o desde el código fuente
git clone https://github.com/cenbonew/zing
cd zing
pip install -e .
```

### Con [uv](https://docs.astral.sh/uv/)

```bash
# desde PyPI, como herramienta independiente en tu PATH
uv tool install zing-audit

# o ejecutarlo una vez sin instalar
uvx --from zing-audit zing --help

# o desde el código fuente, en un entorno virtual local del proyecto
git clone https://github.com/cenbonew/zing
cd zing
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

También puedes instalar directamente desde el repositorio Git sin clonarlo:
`uv tool install git+https://github.com/cenbonew/zing`.

(Mantenedores: consultad [docs/PUBLISHING.md](docs/PUBLISHING.md) para el proceso de publicación.)

### Extras opcionales

- `tokenizers` — conteo preciso de tokens de la familia OpenAI en la auditoría de facturación.
- `web` — la interfaz web local (`zing serve`).

```bash
pip install 'zing-audit[tokenizers,web]'          # pip, desde PyPI
pip install -e '.[tokenizers,web]'                # pip, desde el código fuente
uv tool install 'zing-audit[tokenizers,web]'      # uv, desde PyPI
uv pip install -e '.[tokenizers,web]'             # uv, desde el código fuente
```

## Inicio rápido

```bash
# 1) auditar un relay frente a lo que anuncia (id del modelo + pista de proveedor)
export ZING_API_KEY=sk-tu-clave-del-relay
zing check \
  --base-url https://relay.example.com/v1 \
  --api-key env:ZING_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) la comprobación más sólida: comparar con una referencia de confianza del mismo modelo
export OPENAI_API_KEY=sk-tu-clave-de-openai
zing compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:ZING_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) auditar un relay nativo de Anthropic (API Messages) — el protocolo se detecta
#    automáticamente a partir de base_url/model, o se fuerza con --api anthropic
zing check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:ZING_API_KEY --api anthropic

# 4) confirmar una sustitución sospechada: auditar el id REAL del modelo del relay frente
#    al perfil con el que se vende (aquí: un modelo Doubao vendido como deepseek-v4-flash)
zing check --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) inspeccionar la base de conocimiento integrada
zing kb            # los 85 modelos
zing kb deepseek   # un proveedor

# 6) generar una configuración que puedas versionar
zing init          # escribe zing.yaml
zing check -c zing.yaml
```

### Como herramienta para un LLM / agente

zing está pensado para ser controlado por otro programa o modelo. Todo sale por stdout
en JSON, incluidos los errores, y el código de salida actúa como compuerta.

```bash
# veredicto ligero, apto para agentes (~5x más pequeño que --json: sin la evidencia voluminosa)
zing check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# informe estructurado completo cuando necesitas la evidencia de cada hallazgo
zing check --base-url ... --model gpt-4o --json

# primero el presupuesto: qué detectores se ejecutan + llamadas de API estimadas, SIN hacer ninguna
zing check --base-url ... --model gpt-4o --suite deep --dry-run --json

# compuerta según el código de salida (1 si riesgo >= medium); los errores de config/uso salen con 2, en JSON
zing check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# descubrimiento legible por máquina
zing kb --json                 # toda la base de conocimiento
zing models --base-url ... --json   # lo que anuncia un endpoint
```

En modo `--json`/`--compact`, una configuración incorrecta imprime `{"error": {...}}`
(código 2) en lugar de un mensaje para personas, de modo que un pipeline pueda analizar
los fallos de forma uniforme.

## Interfaz web (`zing serve`)

¿Prefieres hacer clic? Una interfaz web local envuelve el mismo motor — sin necesidad de
la línea de comandos.

```bash
pip install 'zing-audit[web]'     # o: uv tool install 'zing-audit[web]'
zing serve            # abre http://localhost:8000
```

Introduce un relay y el modelo que anuncia; sigue la auditoría **en directo** (progreso
por detector mediante SSE) y luego lee un informe de veredicto que se puede compartir
(nota, desglose por dimensión, hallazgos en lenguaje claro, JSON descargable). Todo se
ejecuta en tu máquina — una clave escrita en el navegador solo llega a tu servidor local
y al relay auditado, nunca a un tercero. Por defecto escucha solo en `127.0.0.1`.

Un desplegable de idioma en la cabecera de cada página cambia la interfaz entre
**🇬🇧 inglés** (por defecto), **🇨🇳 chino** (la interfaz original), **🇫🇷 francés**,
**🇪🇸 español**, **🇵🇹 portugués**, **🇮🇹 italiano** y **🇩🇪 alemán**; la elección se
recuerda por navegador. Los informes descargados desde la interfaz (**Descargar informe
(JSON)**) también siguen el idioma elegido: las claves JSON, los valores de enumeración
(`risk_level`, `status`, `severity`, …), los identificadores y la evidencia se mantienen
exactamente como en el informe de la CLI (sigue siendo un informe zing válido), mientras
que los valores legibles por personas (titular/resumen del veredicto, títulos/resúmenes
de hallazgos, recomendaciones, nombres de detectores, notas) se traducen, y el nombre
del archivo lleva el idioma (`zing-report.es.json`). Los informes
`--format json|md|html` de la CLI siguen en inglés.

**Los prompts enviados al endpoint auditado no siguen el idioma de la interfaz.** Todo
texto que zing envía a una API de LLM — sondas de chat, el prompt del juez LLM, esquemas
de herramientas, entradas de embedding / rerank / imagen / audio — vive en una única
biblioteca de prompts, `zing/prompts/en.json`, y está en inglés, así el mismo relay
obtiene el mismo veredicto lea quien lea el informe (las comprobaciones de respuestas y
las estimaciones de tokens están calibradas con estos textos exactos). Las únicas
excepciones son las huellas de la base de conocimiento cuyo idioma *es* la medida — p. ej.
las sondas de fluidez en chino, de tokenizer y de autoidentificación de los modelos
nativos de China — que declaran `prompt_lang` y un motivo `language_bound` en
`zing/knowledge/data/*.yaml`. Cada informe registra los idiomas de sonda que realmente
usó (`prompt_languages`, p. ej. `["en", "zh"]`).

Las traducciones son datos, compartidos por la interfaz web y las alertas de webhook:
`zing/i18n/locales/<code>.json`, un archivo por idioma. Para añadir un idioma, añade un
archivo (copia `de.json`); el desplegable, las páginas y las alertas lo incorporan.
`tests/test_web_locales.py` falla hasta que cada texto de la interfaz y cada hallazgo
estén traducidos con sus marcadores de posición y su marcado intactos.

## Qué comprueba

zing puntúa nueve dimensiones. Las tres que revelan más directamente un «gato por
liebre» (identidad del modelo, ventana de contexto real, capacidades anunciadas) son las
que más pesan.

| Dimensión | Qué detecta |
|---|---|
| **model_identity** | Degradación/sustitución silenciosa del modelo — autoidentificación, fecha de corte del conocimiento, huellas del tokenizer, el campo `model` devuelto |
| **context_window** | Recorte silencioso del contexto (anuncia 1M, el recuerdo falla a 32K) y «pérdida en el medio» por capas baratas de RAG/resumen, mediante aguja en un pajar + búsqueda binaria |
| **capability** | Capacidades anunciadas de llamadas a herramientas / modo JSON / json-schema / salida máxima que no se cumplen realmente (o se *sobre*cumplen, señal de un sustituto); y **visión** — a un modelo que anuncia entrada de imágenes se le envía una imagen generada con respuesta conocida para confirmar que realmente «ve» |
| **billing** | Inflado de tokens/uso y contabilidad de uso ausente/inverificable, mediante una estimación independiente con tokenizer |
| **streaming** | Streaming falso (búfer y luego troceo) detectado por el número de fragmentos y el tiempo entre fragmentos |
| **protocol** | Conformidad con la compatibilidad OpenAI: multiturno, secuencias de parada, forma de la respuesta, esquema de errores — y una subcomprobación de determinismo para cachés de respuesta que ignoran temperature/seed |
| **reliability** | Tasa de éxito concurrente y latencia (la limitación HTTP 429 se contabiliza aparte) |
| **connectivity** | Accesibilidad del endpoint y la lista `/v1/models` anunciada |
| **security** | Transporte (HTTPS), higiene de cabeceras, eco de secretos; prompt de sistema inyectado oculto (sobrecoste fijo de tokens de entrada + filtración), manipulación en tránsito de respuestas/llamadas a herramientas mediante canarios de respuesta conocida (sustitución de URL/paquete) y caché de prefijo de prompt (tiempos) |

Consulta [docs/METHODOLOGY.md](docs/METHODOLOGY.md) para la técnica detrás de cada
comprobación, el truco de relay con el que se corresponde y sus advertencias sobre
falsos positivos.

### Rendimiento (informativo)

Cada informe incluye además una sección de **performance**: latencia, tiempo hasta el
primer token (TTFT), tokens/s de decodificación y de extremo a extremo, latencia y
jitter entre fragmentos, tasas de error/timeout/429, un desglose de red (conexión TCP,
TLS, un ida y vuelta `GET /models`, tiempo de servidor) y arranque en frío, cada uno como
count / min / mean / p50 / p75 / p90 / p95 / p99 / max / stdev. Nunca afecta a la
puntuación ni al veredicto.

- **standard** la recoge de las propias peticiones de la auditoría.
- **deep / full** añaden una sonda dedicada: 100 peticiones no cacheables de 128 tokens
  de salida (un id de petición aleatorio abre cada prompt, no se envían parámetros de
  caché ni de razonamiento) más una ráfaga a `--concurrency`. Ajustable con
  `--performance-requests` (0 la desactiva) y `--performance-max-tokens`.
- La sonda usa streaming por defecto; `--performance-non-streaming` (o el interruptor de
  la interfaz web) mide relays que no pueden hacer streaming. **full** mide ambos modos,
  intercalados, y los muestra uno junto al otro.
- **compare** ejecuta la sonda en ambos endpoints, alternando peticiones, y añade una
  tabla objetivo-vs-referencia (5 peticiones por lado en `standard`) cuyas diferencias
  se marcan en verde ✓ cuando el objetivo es mejor y en rojo ✗ cuando es peor. Un
  objetivo que genera más de 2x más rápido que la referencia se señala como un indicio
  de baja gravedad.

Los tokens se cuentan dos veces: a partir del `usage` del relay y localmente, de modo
que el rendimiento sea medible incluso cuando falta `usage`. Un percentil solo se
muestra con suficientes muestras (p90 desde 10, p95 desde 20, p99 desde 100). El informe
JSON conserva los tiempos de cada petición (solo números, sin texto); el informe HTML y
la interfaz web los representan a lo largo de la cronología de la auditoría.

## Dos modos de detección

- **Código puro (por defecto):** todas las sondas deterministas — huellas, barrido de
  contexto, cálculos de facturación, tiempos de streaming. No hace falta un segundo
  modelo; totalmente reproducible.
- **Híbrido código + LLM (`--judge`):** consulta además un modelo juez *de confianza*
  (configurado aparte, nunca el objetivo) para evaluar señales difusas como la calidad y
  la profundidad de razonamiento que el código puro no puede decidir. Alimenta el
  detector `quality_judge`.

```bash
zing check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

## Monitorización (`zing watch`)

Un relay puede servir el modelo real hoy y cambiarlo en silencio la semana que viene.
`zing watch` repite la auditoría según una programación, registra cada ejecución en el
historial y avisa a un webhook cuando el riesgo supera un umbral o **empeora** respecto
a la ejecución anterior.

```bash
zing watch --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang es                                     # o --once para cron
```

Las alertas se formatean para **Slack / Feishu / DingTalk / JSON genérico**, detectado
automáticamente a partir de la URL del webhook, y se redactan en el idioma de alerta —
inglés por defecto; `--alert-lang en|zh|fr|es|pt|it|de`. La carga JSON genérica mantiene
sus claves y valores de máquina (`risk_level`, `score`, …) independientes del idioma,
traduce los legibles por personas (`text`, `headline`, `key_findings`) e indica el
`language`.

¿Prefieres una interfaz? `zing serve` incluye un monitor en **`/watches`**
(🔔 Monitores): añade un monitor en el navegador y un planificador en segundo plano,
dentro del mismo proceso, lo vuelve a ejecutar en su intervalo, guarda cada ejecución en
el historial y dispara las mismas alertas de webhook al superar un umbral o empeorar.
Cada monitor tiene su propio idioma de alerta (elegido en el formulario, por defecto el
de la interfaz, y modificable en su tarjeta). Ejecutar ahora / pausar / eliminar desde la
página. Las claves se guardan solo en `~/.zing` y nunca se devuelven al navegador.

## Auditorías de embedding y rerank

Los embeddings y el rerank son una superficie ajena al chat, así que zing los audita con
un auditor independiente específico en lugar del pipeline de chat de 9 dimensiones.

```bash
# La dimensión de vector esperada se resuelve desde la base integrada para el modelo anunciado.
zing embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# O fijar directamente la dimensión esperada:
zing embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: una sonda integrada de respuesta conocida — un reranker auténtico debe
# colocar primero el documento obviamente relevante.
zing rerank --base-url https://relay.example.com/v1 --model my-rerank
```

`embed` comprueba la conectividad, la **coincidencia de dimensión** (longitud del vector
devuelto frente a la dimensión nativa del modelo anunciado — la señal principal de
«gato por liebre»; un relay que anuncia `text-embedding-3-large` de 3072-d pero devuelve
1024-d sirve un modelo sustituido), el determinismo (misma entrada → coseno ≈ 1), la
distinción (entradas no relacionadas → coseno muy por debajo de 1) y el campo `model`
devuelto. Perfiles integrados: OpenAI `text-embedding-3-small` (1536),
`text-embedding-3-large` (3072), `text-embedding-ada-002` (1536), Qwen
`text-embedding-v3`/`-v4` (1024).

Ambos están también en la interfaz web — `zing serve` tiene una página
**Herramientas** en `/tools` (enlazada desde la navegación) con formularios de
embed/rerank que muestran el mismo veredicto localizado.

## Auditorías de generación de imágenes y audio (TTS)

Dos superficies más ajenas al chat: la generación de imágenes
(`POST /v1/images/generations`) y la síntesis de voz (`POST /v1/audio/speech`). Toda la
decodificación es stdlib pura — dimensiones de imagen a partir de los bytes de cabecera
(PNG/JPEG/GIF/WebP), duración WAV mediante el módulo `wave`.

```bash
# ¿Un relay que anuncia DALL·E 3 devuelve realmente el 1792x1024 pedido? Una imagen
# reducida / de tamaño incorrecto (o un tamaño fuera de los nativos del modelo anunciado,
# resueltos desde la base) es la señal principal de «gato por liebre».
zing image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# ¿Un relay que anuncia tts-1-hd devuelve audio real cuya duración crece con la entrada
# (no un marcador fijo, no HTML/JSON disfrazado de audio)?
zing audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --format wav --save clip.wav
```

`image` comprueba: conectividad, formato válido/decodificable, **coincidencia de tamaño**
(AnchoxAlto decodificado frente a la petición y los tamaños nativos del modelo anunciado
— FAIL/HIGH si no coinciden), distinción (dos prompts → imágenes distintas, para detectar
un marcador fijo), cantidad, campo model. `audio` comprueba: conectividad, validez del
contenedor/formato, respeto del formato, duración no trivial (proporcional a la longitud
de la entrada), distinción, campo model. La base incluye OpenAI DALL·E 2/3, gpt-image-1,
tts-1/tts-1-hd/gpt-4o-mini-tts y perfiles de imagen/TTS de Qwen.

## Uso en CI (GitHub Action)

Condiciona cualquier workflow a una auditoría de relay con la acción compuesta incluida.
Ejecuta `zing check --compact --fail-on-risk`, expone `risk` / `score` / `rating` como
salidas, escribe un resumen en la ejecución y hace fallar el job cuando salta la
compuerta de riesgo.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: zing
        uses: cenbonew/zing@v0.9.0          # fijar a una etiqueta de release
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # secreto del llamante; nunca se muestra
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.zing.outputs.risk }} score=${{ steps.zing.outputs.score }}"
```

La clave del relay se pasa mediante una variable de entorno (`--api-key env:…`), por lo
que nunca aparece en una línea de comandos. Consulta [docs/CI.md](docs/CI.md) para la
tabla completa de entradas/salidas y un ejemplo de compuerta de despliegue.

## Suites

| Suite | Detectores | Coste |
|---|---|---|
| `smoke` | connectivity, security | muy bajo |
| `standard` | + protocol, model_identity, capability, streaming, billing, reliability | bajo–medio |
| `deep` | + context_window, determinism, injected_prompt, integrity, performance, prompt_cache, quality_judge (con `--judge`) | más alto (las sondas de contexto largo y de tiempos consumen tokens) |
| `full` | todo | el más alto |

La sonda de ventana de contexto está limitada por `--max-context-tokens` (200K por
defecto), así que auditar un modelo de 1M de tokens sigue siendo asequible.

## Ejemplo de veredicto

```text
╭─ ✗ HIGH RISK — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · confidence medium                             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • Se identifica como una marca rival (anthropic) bajo el id de modelo anunciado gpt-4o
  • Ventana de contexto real ~8000 << 128000 declarados (se sospecha recorte silencioso)
  • Los tokens de prompt reportados superan con creces la estimación independiente
```

Los informes se escriben en `reports/` como JSON, Markdown y HTML.

## Base de conocimiento

Los perfiles están en [`zing/knowledge/data/`](zing/knowledge/data) como YAML editable
— uno por proveedor (OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM, Moonshot).
Cada modelo incluye su ventana de contexto nativa, salida máxima, tokenizer, indicadores
de capacidades, palabras clave de identidad y huellas de comportamiento. Añade o
sobrescribe perfiles sin hacer un fork:

```bash
zing check --kb-dir ./my-profiles ...     # o define ZING_KB_DIR
```

## Uso responsable

zing es una ayuda para auditorías de caja negra. **No puede demostrar**:

- que un proveedor almacene tus prompts o entrene con ellos,
- que siempre enrute a un único modelo concreto (un relay puede enrutar de forma probabilística),
- fraude de facturación más allá de lo que la estimación independiente de tokens puede sugerir.

Usa los informes para tu propia diligencia debida. **No acuses públicamente a un
proveedor** basándote en una sola ejecución sin revisar el tamaño de la muestra, la
configuración de costes y la legislación local. Ejecuta `zing compare` contra una
referencia de confianza antes de sacar conclusiones firmes.

## Licencia

[Apache-2.0](LICENSE)
