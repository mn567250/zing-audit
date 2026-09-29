# zing — verificação da realidade de relays de LLM

> [🇬🇧 English](README.md) · [🇨🇳 中文](README.zh-CN.md) · [🇫🇷 Français](README.fr.md) · [🇪🇸 Español](README.es.md) · **🇵🇹 Português** · [🇮🇹 Italiano](README.it.md) · [🇩🇪 Deutsch](README.de.md)

[![CI](https://github.com/cenbonew/zing/actions/workflows/ci.yml/badge.svg)](https://github.com/cenbonew/zing/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**zing** é uma ferramenta de linha de comandos local-first que audita se um relay de API
(revendedor / proxy) serve realmente o modelo que anuncia — ou se o substitui
discretamente por um mais barato, trunca a sua janela de contexto, simula o streaming ou
inflaciona a faturação de tokens. Em suma: recebe aquilo por que paga? Fala **OpenAI
Chat Completions**, a **API Anthropic Messages** e a **API OpenAI Responses**
(`/v1/responses`) — com deteção automática, ou forçado com
`--api openai|anthropic|responses`.

Indica-lhe o endpoint de um relay e o modelo que anuncia; o zing executa uma bateria de
sondas de caixa-preta, compara o comportamento observado com uma base de conhecimento
integrada de **85 perfis de modelos nativos em 7 plataformas** e apresenta um veredicto
claro e sustentado em evidências — para uma pessoa, ou em JSON para outra ferramenta /
LLM ler.

> O zing fornece **evidências de caixa-preta de divergências e riscos, não uma prova
> criptográfica de fraude.** Consulte [Utilização responsável](#utilização-responsável).

---

## Porquê

O mercado de chaves de relay está cheio de ofertas de «GPT-4o por um décimo do preço».
Muitas são honestas. Algumas não — e as desonestas são difíceis de detetar a olho nu:

- Pede `gpt-4o`; recebe discretamente `gpt-4o-mini` ou um modelo aberto.
- O relay anuncia um contexto de 1M de tokens mas trunca-o silenciosamente para 32K.
- O «streaming» é a resposta completa guardada em buffer e novamente fragmentada, sem ganho de latência.
- Os tokens de `usage` reportados estão inflacionados, pelo que o seu saldo se esgota mais depressa do que devia.
- Um modelo que deveria suportar chamadas de ferramentas / modo JSON discretamente não o faz.

O zing transforma «há aqui algo que não bate certo» num relatório reproduzível.

## Instalação

Requer Python 3.10+. Cada uma das opções abaixo fornece o comando `zing`.

### Com pip

```bash
# a partir do PyPI
pip install zing-audit

# ou a partir do código-fonte
git clone https://github.com/cenbonew/zing
cd zing
pip install -e .
```

### Com [uv](https://docs.astral.sh/uv/)

```bash
# a partir do PyPI, como ferramenta independente no seu PATH
uv tool install zing-audit

# ou executá-lo uma vez sem instalar
uvx --from zing-audit zing --help

# ou a partir do código-fonte, num ambiente virtual local ao projeto
git clone https://github.com/cenbonew/zing
cd zing
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

Também pode instalar diretamente a partir do repositório Git sem o clonar:
`uv tool install git+https://github.com/cenbonew/zing`.

(Mantenedores: consultem [docs/PUBLISHING.md](docs/PUBLISHING.md) para o processo de publicação.)

### Extras opcionais

- `tokenizers` — contagem precisa de tokens da família OpenAI na auditoria de faturação.
- `web` — a interface web local (`zing serve`).

```bash
pip install 'zing-audit[tokenizers,web]'          # pip, a partir do PyPI
pip install -e '.[tokenizers,web]'                # pip, a partir do código-fonte
uv tool install 'zing-audit[tokenizers,web]'      # uv, a partir do PyPI
uv pip install -e '.[tokenizers,web]'             # uv, a partir do código-fonte
```

## Início rápido

```bash
# 1) auditar um relay face ao que anuncia (id do modelo + indicação do fornecedor)
export ZING_API_KEY=sk-a-sua-chave-do-relay
zing check \
  --base-url https://relay.example.com/v1 \
  --api-key env:ZING_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) a verificação mais forte: comparar com uma referência de confiança do mesmo modelo
export OPENAI_API_KEY=sk-a-sua-chave-openai
zing compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:ZING_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) auditar um relay nativo da Anthropic (API Messages) — o protocolo é detetado
#    automaticamente a partir de base_url/model, ou forçado com --api anthropic
zing check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:ZING_API_KEY --api anthropic

# 4) confirmar uma substituição suspeita: auditar o id REAL do modelo do relay face ao
#    perfil com que é vendido (aqui: um modelo Doubao vendido como deepseek-v4-flash)
zing check --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) consultar a base de conhecimento integrada
zing kb            # os 85 modelos
zing kb deepseek   # um fornecedor

# 6) gerar uma configuração que pode versionar
zing init          # escreve zing.yaml
zing check -c zing.yaml
```

### Como ferramenta para um LLM / agente

O zing foi concebido para ser controlado por outro programa ou modelo. Tudo vai para o
stdout em JSON, incluindo erros, e o código de saída funciona como barreira.

```bash
# veredicto leve, adequado a agentes (~5x mais pequeno do que --json: sem as evidências volumosas)
zing check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# relatório estruturado completo quando precisa das evidências de cada constatação
zing check --base-url ... --model gpt-4o --json

# primeiro o orçamento: que detetores correm + chamadas de API estimadas, SEM fazer nenhuma
zing check --base-url ... --model gpt-4o --suite deep --dry-run --json

# barreira pelo código de saída (1 se risco >= medium); erros de config/utilização saem com 2, em JSON
zing check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# descoberta legível por máquina
zing kb --json                 # toda a base de conhecimento
zing models --base-url ... --json   # o que um endpoint anuncia
```

No modo `--json`/`--compact`, uma configuração inválida imprime `{"error": {...}}`
(código 2) em vez de uma mensagem para pessoas, para que um pipeline possa analisar as
falhas de forma uniforme.

## Interface web (`zing serve`)

Prefere clicar? Uma interface web local envolve o mesmo motor — sem necessidade da
linha de comandos.

```bash
pip install 'zing-audit[web]'     # ou: uv tool install 'zing-audit[web]'
zing serve            # abre http://localhost:8000
```

Introduza um relay e o modelo que anuncia; acompanhe a auditoria **em direto**
(progresso por detetor via SSE) e depois leia um relatório de veredicto partilhável
(nota, detalhe por dimensão, constatações em linguagem clara, JSON transferível). Tudo
corre na sua máquina — uma chave escrita no navegador só chega ao seu servidor local e
ao relay auditado, nunca a terceiros. Por omissão, fica apenas em `127.0.0.1`.

Um menu de idioma no cabeçalho de cada página alterna a interface entre
**🇬🇧 inglês** (por omissão), **🇨🇳 chinês** (a interface original), **🇫🇷 francês**,
**🇪🇸 espanhol**, **🇵🇹 português**, **🇮🇹 italiano** e **🇩🇪 alemão**; a escolha é
memorizada por navegador. Os relatórios transferidos a partir da interface
(**Transferir relatório (JSON)**) também seguem o idioma escolhido: as chaves JSON, os
valores de enumeração (`risk_level`, `status`, `severity`, …), os identificadores e as
evidências mantêm-se exatamente como no relatório da CLI (continua a ser um relatório
zing válido), enquanto os valores legíveis por pessoas (título/resumo do veredicto,
títulos/resumos das constatações, recomendações, nomes dos detetores, notas) são
traduzidos, e o nome do ficheiro inclui o idioma (`zing-report.pt.json`). Os relatórios
`--format json|md|html` da CLI permanecem em inglês.

**Os prompts enviados ao endpoint auditado não seguem o idioma da interface.** Todo o
texto que o zing envia a uma API de LLM — sondas de chat, o prompt do juiz LLM, esquemas
de ferramentas, entradas de embedding / rerank / imagem / áudio — está numa única
biblioteca de prompts, `zing/prompts/en.json`, e é em inglês, para que o mesmo relay
obtenha o mesmo veredicto independentemente de quem lê o relatório (as verificações de
respostas e as estimativas de tokens estão calibradas para estes textos exatos). As
únicas exceções são as impressões digitais da base de conhecimento cujo idioma *é* a
medição — p. ex. as sondas de fluência em chinês, de tokenizer e de autoidentificação dos
modelos nativos da China — que declaram `prompt_lang` e um motivo `language_bound` em
`zing/knowledge/data/*.yaml`. Cada relatório regista os idiomas de sonda efetivamente
usados (`prompt_languages`, p. ex. `["en", "zh"]`).

As traduções são dados, partilhados pela interface web e pelos alertas de webhook:
`zing/i18n/locales/<code>.json`, um ficheiro por idioma. Para adicionar um idioma,
adicione um ficheiro (copie `de.json`); o menu, as páginas e os alertas passam a
usá-lo. `tests/test_web_locales.py` falha até que cada texto da interface e cada
constatação estejam traduzidos com os seus marcadores de posição e a sua marcação
intactos.

## O que verifica

O zing pontua dez dimensões. As três que revelam mais diretamente um «gato por lebre»
(identidade do modelo, janela de contexto real, capacidades anunciadas) são as que mais
pesam.

| Dimensão | O que deteta |
|---|---|
| **model_identity** | Despromoção/substituição silenciosa do modelo — autoidentificação, data-limite do conhecimento, impressões digitais do tokenizer, o campo `model` devolvido |
| **context_window** | Truncagem silenciosa do contexto (anuncia 1M, a recuperação falha aos 32K) e «perda no meio» causada por camadas baratas de RAG/resumo, através de agulha num palheiro + pesquisa binária |
| **capability** | Capacidades anunciadas de chamadas de ferramentas / modo JSON / json-schema / saída máxima que não são realmente cumpridas (ou são *sobre*cumpridas, sinal de um substituto); e **visão** — um modelo que anuncia entrada de imagens recebe uma imagem gerada de resposta conhecida para confirmar que realmente «vê» |
| **billing** | Inflação de tokens/utilização e contabilização de utilização em falta/não verificável, através de uma estimativa independente por tokenizer |
| **streaming** | Streaming falso (buffer e depois fragmentação) detetado pelo número de fragmentos e pelo intervalo entre fragmentos |
| **protocol** | Conformidade com a compatibilidade OpenAI: várias interações, sequências de paragem, forma da resposta, esquema de erros — e uma subverificação de determinismo para caches de resposta que ignoram temperature/seed |
| **reliability** | Taxa de sucesso em concorrência e latência (a limitação HTTP 429 é contabilizada à parte) |
| **performance** | Quão *constantes* são a latência, o tempo até o primeiro token e a vazão, a taxa de falhas da sonda e a lentidão sob carga; a velocidade só face a uma referência |
| **connectivity** | Acessibilidade do endpoint e a lista `/v1/models` anunciada |
| **security** | Transporte (HTTPS), higiene dos cabeçalhos, eco de segredos; prompt de sistema injetado e oculto (sobrecarga fixa de tokens de entrada + fuga), adulteração em trânsito de respostas/chamadas de ferramentas através de canários de resposta conhecida (substituição de URL/pacote) e cache de prefixo de prompt (tempos) |

Consulte [docs/METHODOLOGY.md](docs/METHODOLOGY.md) para a técnica por detrás de cada
verificação, o truque de relay a que corresponde e as suas ressalvas sobre falsos
positivos.

### Desempenho

Cada relatório inclui também uma secção de **performance**: latência, tempo até ao
primeiro token (TTFT), tokens/s de descodificação e de ponta a ponta, latência e jitter
entre fragmentos, taxas de erro/timeout/429, uma decomposição de rede (ligação TCP, TLS,
uma ida e volta `GET /models`, tempo do servidor) e arranque a frio, cada um como
count / min / mean / p50 / p75 / p90 / p95 / p99 / max / stdev. Quando a sonda dedicada é executada, ela pontua a dimensão **performance** (peso 6) pela *constância* de latência, TTFT e vazão, pela taxa de falhas e pelo comportamento sob carga, não pela velocidade bruta: um modelo lento mas constante (ex.: local) não é penalizado. A velocidade só conta face a uma referência (a linha de base ou o intervalo publicado na base de conhecimento). As constatações são no máximo de severidade baixa e nunca mudam o veredito de risco.

- **standard** recolhe-a a partir dos próprios pedidos da auditoria.
- **deep / full** acrescentam uma sonda dedicada: 100 pedidos não armazenáveis em cache
  de 128 tokens de saída (um id de pedido aleatório abre cada prompt, não são enviados
  parâmetros de cache nem de raciocínio) mais uma rajada a `--concurrency`. Ajustável com
  `--performance-requests` (0 desativa) e `--performance-max-tokens`.
- A sonda usa streaming por omissão; `--performance-non-streaming` (ou o interruptor na
  interface web) mede relays que não suportam streaming. **full** mede ambos os modos,
  intercalados, e apresenta-os lado a lado.
- **compare** executa a sonda nos dois endpoints, alternando pedidos, e acrescenta uma
  tabela alvo-vs-referência (5 pedidos por lado em `standard`) cujas diferenças são
  assinaladas a verde ✓ quando o alvo é melhor e a vermelho ✗ quando é pior. Um alvo que
  gera mais de 2x mais depressa do que a referência é assinalado como um indício de baixa
  gravidade.

Os tokens são contados duas vezes: a partir do `usage` do relay e localmente, para que o
débito seja mensurável mesmo quando falta `usage`. Um percentil só é mostrado com
amostras suficientes (p90 a partir de 10, p95 a partir de 20, p99 a partir de 100). O
relatório JSON guarda os tempos de cada pedido (apenas números, sem texto); o relatório
HTML e a interface web representam-nos ao longo da cronologia da auditoria.

## Dois modos de deteção

- **Código puro (por omissão):** todas as sondas determinísticas — impressões digitais,
  varrimento do contexto, cálculos de faturação, tempos de streaming. Não é necessário
  um segundo modelo; totalmente reproduzível.
- **Híbrido código + LLM (`--judge`):** consulta adicionalmente um modelo juiz *de
  confiança* (configurado à parte, nunca o alvo) para avaliar sinais difusos como a
  qualidade e a profundidade de raciocínio, que o código puro não consegue decidir.
  Alimenta o detetor `quality_judge`.

```bash
zing check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

## Monitorização (`zing watch`)

Um relay pode servir o modelo verdadeiro hoje e trocá-lo discretamente na próxima
semana. O `zing watch` repete a auditoria segundo um agendamento, regista cada execução
no histórico e alerta um webhook quando o risco ultrapassa um limiar ou **regride** em
relação à execução anterior.

```bash
zing watch --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang pt                                     # ou --once para cron
```

Os alertas são formatados para **Slack / Feishu / DingTalk / JSON genérico**, detetado
automaticamente a partir do URL do webhook, e escritos no idioma de alerta — inglês por
omissão; `--alert-lang en|zh|fr|es|pt|it|de`. A carga JSON genérica mantém as suas
chaves e valores de máquina (`risk_level`, `score`, …) independentes do idioma, traduz os
legíveis por pessoas (`text`, `headline`, `key_findings`) e indica o `language`.

Prefere uma interface? O `zing serve` inclui um monitor em **`/watches`**
(🔔 Monitores): adicione um monitor no navegador e um agendador em segundo plano, no
mesmo processo, volta a executá-lo no seu intervalo, guarda cada execução no histórico e
dispara os mesmos alertas de webhook quando um limiar é ultrapassado ou há regressão.
Cada monitor tem o seu próprio idioma de alerta (escolhido no formulário, por omissão o
da interface, e alterável no respetivo cartão). Executar agora / pausar / eliminar a
partir da página. As chaves são guardadas apenas em `~/.zing` e nunca são devolvidas ao
navegador.

## Auditorias de embedding e rerank

Os embeddings e o rerank são uma superfície fora do chat, pelo que o zing os audita com
um auditor independente dedicado em vez do pipeline de chat de 9 dimensões.

```bash
# A dimensão de vetor esperada é resolvida a partir da base integrada para o modelo anunciado.
zing embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Ou definir diretamente a dimensão esperada:
zing embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: uma sonda integrada de resposta conhecida — um reranker genuíno tem de
# colocar primeiro o documento obviamente relevante.
zing rerank --base-url https://relay.example.com/v1 --model my-rerank
```

O `embed` verifica a conectividade, a **correspondência de dimensão** (comprimento do
vetor devolvido face à dimensão nativa do modelo anunciado — o principal sinal de «gato
por lebre»; um relay que anuncia `text-embedding-3-large` de 3072-d mas devolve 1024-d
serve um modelo substituto), o determinismo (mesma entrada → cosseno ≈ 1), a distinção
(entradas não relacionadas → cosseno bem abaixo de 1) e o campo `model` devolvido.
Perfis integrados: OpenAI `text-embedding-3-small` (1536), `text-embedding-3-large`
(3072), `text-embedding-ada-002` (1536), Qwen `text-embedding-v3`/`-v4` (1024).

Ambos estão também na interface web — o `zing serve` tem uma página **Ferramentas** em
`/tools` (acessível a partir da navegação) com formulários de embed/rerank que mostram o
mesmo veredicto localizado.

## Auditorias de geração de imagem e áudio (TTS)

Mais duas superfícies fora do chat: geração de imagens (`POST /v1/images/generations`) e
síntese de voz (`POST /v1/audio/speech`). Toda a descodificação é feita com a stdlib pura
— dimensões da imagem a partir dos bytes do cabeçalho (PNG/JPEG/GIF/WebP), duração WAV
através do módulo `wave`.

```bash
# Um relay que anuncia DALL·E 3 devolve mesmo o 1792x1024 pedido? Uma imagem reduzida /
# de tamanho errado (ou um tamanho fora dos tamanhos nativos do modelo anunciado,
# resolvidos a partir da base) é o principal sinal de «gato por lebre».
zing image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Um relay que anuncia tts-1-hd devolve áudio real cuja duração acompanha a entrada
# (não um marcador fixo, não HTML/JSON disfarçado de áudio)?
zing audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --format wav --save clip.wav
```

O `image` verifica: conectividade, formato válido/descodificável, **correspondência de
tamanho** (LxA descodificado face ao pedido e aos tamanhos nativos do modelo anunciado —
FAIL/HIGH em caso de discrepância), distinção (dois prompts → imagens diferentes, para
apanhar um marcador fixo), quantidade, campo model. O `audio` verifica: conectividade,
validade do contentor/formato, cumprimento do formato, duração não trivial
(proporcional ao comprimento da entrada), distinção, campo model. A base inclui OpenAI
DALL·E 2/3, gpt-image-1, tts-1/tts-1-hd/gpt-4o-mini-tts e perfis de imagem/TTS da Qwen.

## Utilização em CI (GitHub Action)

Condicione qualquer workflow a uma auditoria de relay com a ação composta incluída. Ela
executa `zing check --compact --fail-on-risk`, expõe `risk` / `score` / `rating` como
saídas, escreve um resumo na execução e faz falhar o job quando a barreira de risco é
acionada.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: zing
        uses: cenbonew/zing@v0.9.0          # fixar numa tag de release
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # segredo do chamador; nunca é mostrado
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.zing.outputs.risk }} score=${{ steps.zing.outputs.score }}"
```

A chave do relay é passada através de uma variável de ambiente (`--api-key env:…`),
pelo que nunca aparece numa linha de comandos. Consulte [docs/CI.md](docs/CI.md) para a
tabela completa de entradas/saídas e um exemplo de barreira de implementação.

## Suites

| Suite | Detetores | Custo |
|---|---|---|
| `smoke` | connectivity, security | muito baixo |
| `standard` | + protocol, model_identity, capability, streaming, billing, reliability | baixo–médio |
| `deep` | + context_window, determinism, injected_prompt, integrity, performance, prompt_cache, quality_judge (com `--judge`) | mais alto (as sondas de contexto longo e de tempos consomem tokens) |
| `full` | tudo | o mais alto |
| `custom` | só as dimensões escolhidas, com profundidade `deep` | depende da seleção |

**Suite personalizada:** `zing check ... -D protocol -D performance` (ou `--suite custom --dimension billing,streaming`; no arquivo de configuração `run.dimensions`) executa só as dimensões escolhidas. A pontuação geral é a média ponderada apenas dessas dimensões; sem nenhuma dimensão central (identidade do modelo, janela de contexto, capacidades) o veredito de risco é *inconclusivo*. A interface web oferece a mesma escolha.

A sonda de janela de contexto é limitada por `--max-context-tokens` (200K por omissão),
para que auditar um modelo de 1M de tokens continue a ser acessível.

## Exemplo de veredicto

```text
╭─ ✗ HIGH RISK — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · confidence medium                             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • Identifica-se como uma marca rival (anthropic) sob o id de modelo anunciado gpt-4o
  • Janela de contexto real ~8000 << 128000 declarados (suspeita de truncagem silenciosa)
  • Os tokens de prompt reportados excedem largamente a estimativa independente
```

Os relatórios são escritos em `reports/` como JSON, Markdown e HTML.

## Base de conhecimento

Os perfis estão em [`zing/knowledge/data/`](zing/knowledge/data) como YAML editável —
um por fornecedor (OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM, Moonshot).
Cada modelo inclui a sua janela de contexto nativa, saída máxima, tokenizer, indicadores
de capacidades, palavras-chave de identidade e impressões digitais comportamentais.
Adicione ou substitua perfis sem fazer fork:

```bash
zing check --kb-dir ./my-profiles ...     # ou defina ZING_KB_DIR
```

## Utilização responsável

O zing é uma ajuda para auditorias de caixa-preta. **Não consegue provar**:

- que um fornecedor armazena os seus prompts ou treina com eles,
- que encaminha sempre para um único modelo exato (um relay pode encaminhar de forma probabilística),
- fraude de faturação para além do que a estimativa independente de tokens consegue sugerir.

Use os relatórios para a sua própria diligência. **Não acuse publicamente um
fornecedor** com base numa única execução sem rever a dimensão da amostra, as
definições de custo e a legislação local. Execute `zing compare` contra uma referência
de confiança antes de tirar conclusões fortes.

## Licença

[Apache-2.0](LICENSE)
