# zing — 大模型中转站「货不对板」检测工具

> [🇬🇧 English](README.md) · **🇨🇳 中文** · [🇫🇷 Français](README.fr.md) · [🇪🇸 Español](README.es.md) · [🇵🇹 Português](README.pt.md) · [🇮🇹 Italiano](README.it.md) · [🇩🇪 Deutsch](README.de.md)

[![CI](https://github.com/cenbonew/zing/actions/workflows/ci.yml/badge.svg)](https://github.com/cenbonew/zing/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**zing** 是一个本地优先（local-first）的命令行工具，用于检测一个 API 中转站 / 代理 /
转售商提供的，**是否真的是它声称的那个模型**——还是悄悄换成了更便宜的模型、截断了上下文窗口、
伪造了流式输出，或者虚报了 token 计费（即「**货不对板**」）。它同时支持
**OpenAI Chat Completions**、**Anthropic Messages API** 和 **OpenAI Responses API**
（`/v1/responses`）——自动识别，也可用 `--api openai|anthropic|responses` 强制指定。

你只需告诉 zing 中转站的接口地址和它声称的模型，zing 就会运行一整套黑盒探测，
把观测到的行为与内置的**覆盖 7 大平台、85 个原生模型画像**的知识库逐项比对，
最后给出一个清晰、有证据支撑的结论——既适合人看，也能输出 JSON 给其它程序或大模型直接消费。

> zing 给出的是**「行为差异与风险」的黑盒证据，而非欺诈的密码学证明**。
> 请阅读 [负责任使用](#负责任使用)。

---

## 为什么需要它

中转 key 市场充斥着「GPT-4o 一折价」的报价。很多是诚实的，但有些不是——而且作弊手法肉眼很难识别：

- 你点名要 `gpt-4o`，实际被悄悄换成 `gpt-4o-mini` 或某个开源模型；
- 宣传 1M token 上下文，实际悄悄截断到 32K；
- 所谓「流式」其实是把整段回复缓存后再切片下发，毫无首字延迟优势；
- 上报的 `usage` token 数被夸大，你的余额烧得比应有的更快；
- 本该支持工具调用 / JSON 模式的模型，实际并不支持。

zing 把「感觉不太对」变成一份可复现的报告。

## 安装

需要 Python 3.10+。以下任一方式都会提供 `zing` 命令。

### 使用 pip

```bash
# 从 PyPI 安装
pip install zing-audit

# 或从源码安装
git clone https://github.com/cenbonew/zing
cd zing
pip install -e .
```

### 使用 [uv](https://docs.astral.sh/uv/)

```bash
# 从 PyPI 安装为独立工具，加入 PATH
uv tool install zing-audit

# 或不安装、直接运行一次
uvx --from zing-audit zing --help

# 或从源码安装到项目本地的虚拟环境
git clone https://github.com/cenbonew/zing
cd zing
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows：.venv\Scripts\activate
```

也可以不克隆，直接从 Git 仓库安装：
`uv tool install git+https://github.com/cenbonew/zing`。

（维护者：发布流程见 [docs/PUBLISHING.md](docs/PUBLISHING.md)。）

### 可选附加项

- `tokenizers`——让账单审计对 OpenAI 系模型做精确 token 计数。
- `web`——本地 Web 界面（`zing serve`）。

```bash
pip install 'zing-audit[tokenizers,web]'          # pip，从 PyPI
pip install -e '.[tokenizers,web]'                # pip，从源码
uv tool install 'zing-audit[tokenizers,web]'      # uv，从 PyPI
uv pip install -e '.[tokenizers,web]'             # uv，从源码
```

## 快速开始

```bash
# 1) 按中转站声称的模型审计它（模型 id + 平台提示）
export ZING_API_KEY=sk-你的中转key
zing check \
  --base-url https://relay.example.com/v1 \
  --api-key env:ZING_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) 最强检测：与同款模型的可信基线对比
export OPENAI_API_KEY=sk-你的官方key
zing compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:ZING_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) 审计 Anthropic 原生（Messages API）中转——协议根据 base_url/model 自动识别，
#    也可用 --api anthropic 强制指定
zing check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:ZING_API_KEY --api anthropic

# 4) 确认疑似替换：用中转的「真实」模型 id 对照它被宣传成的模型画像来审计
#    （此例：一个豆包模型被当作 deepseek-v4-flash 出售）
zing check --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) 查看内置知识库
zing kb            # 全部 85 个模型
zing kb deepseek   # 单个平台

# 6) 生成可提交的配置文件
zing init          # 生成 zing.yaml
zing check -c zing.yaml
```

### 作为给大模型 / Agent 使用的工具

zing 专为被其它程序或模型驱动而设计。所有输出都以 JSON 打到标准输出（错误也不例外），
退出码即门禁。

```bash
# 精简、适合 Agent 的结论（比 --json 小约 5 倍：不含大体量证据）
zing check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# 需要每条发现的证据时，输出完整结构化报告
zing check --base-url ... --model gpt-4o --json

# 先算预算：会运行哪些检测器 + 预估 API 调用次数，且「不」发出任何请求
zing check --base-url ... --model gpt-4o --suite deep --dry-run --json

# 以退出码做门禁（风险 >= medium 时退出码为 1）；配置/用法错误以 JSON 输出并退出码 2
zing check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# 机器可读的发现能力
zing kb --json                 # 整个知识库
zing models --base-url ... --json   # 某个端点宣称提供的模型
```

在 `--json`/`--compact` 模式下，错误的配置会输出 `{"error": {...}}`（退出码 2），
而非面向人的提示信息，便于流水线统一解析失败。

## Web 界面（`zing serve`）

更喜欢点鼠标？本地 Web 界面封装了同一套引擎——无需命令行。

```bash
pip install 'zing-audit[web]'     # 或：uv tool install 'zing-audit[web]'
zing serve            # 打开 http://localhost:8000
```

输入中转站和它声称的模型，即可**实时**观看检测过程（通过 SSE 逐个检测器显示进度），
随后阅读一份可分享的结论报告（评级、各维度明细、通俗易懂的发现、可下载的 JSON）。
一切都在你的机器上运行——在浏览器里输入的 key 只会到达你的本地服务和被测中转站，
绝不会发给第三方。默认只绑定 `127.0.0.1`。

每个页面顶部的语言下拉框可在 **🇬🇧 英语**（默认）、**🇨🇳 中文**（界面原始语言）、
**🇫🇷 法语**、**🇪🇸 西班牙语**、**🇵🇹 葡萄牙语**、**🇮🇹 意大利语** 和 **🇩🇪 德语**
之间切换界面；选择按浏览器记住。从界面下载的报告（**下载报告 (JSON)**）同样跟随所选语言：
JSON 键、枚举值（`risk_level`、`status`、`severity` 等）、id 和证据与命令行报告完全一致
（仍是合法的 zing 报告），而面向人阅读的值（结论标题/摘要、发现标题/摘要、建议、检测器名称、
备注）会被翻译，文件名也会带上语言（`zing-report.zh.json`）。命令行自身的
`--format json|md|html` 报告始终为英文。

**发往被测端点的提示词不跟随界面语言。** zing 发给 LLM API 的每一段文本——对话探测、
LLM 裁判的提示词、工具 schema、embedding / rerank / 图像 / 音频输入——都集中在同一个提示词库
`zing/prompts/en.json` 中，且均为英文，这样无论谁来读报告，同一个中转站都会得到同样的结论
（答案校验和 token 估算都针对这些确切文本校准过）。唯一的例外是那些「语言本身就是测量对象」的
知识库指纹——例如中国原生模型的中文流畅度、分词器和自我身份识别探测——它们在
`zing/knowledge/data/*.yaml` 中声明了 `prompt_lang` 和 `language_bound` 理由。
每份报告都会记录实际使用的探测语言（`prompt_languages`，例如 `["en", "zh"]`）。

翻译是数据，由 Web 界面和 Webhook 告警共用：`zing/i18n/locales/<code>.json`，每种语言一个文件。
要新增一种语言，只需新增一个文件（复制 `de.json`）；下拉框、页面和告警都会自动识别。
`tests/test_web_locales.py` 会一直失败，直到每条界面文案和每条发现都已翻译，
且占位符与标记完好无损。

## 检测了什么

zing 对十个维度评分。其中最直接揭示「货不对板」的三项（模型身份、真实上下文窗口、能力声明）权重最高。

| 维度 | 能抓到什么 |
|---|---|
| **model_identity 模型身份** | 静默降级 / 替换——自我身份识别、知识截止、分词器指纹、回包里的 `model` 字段 |
| **context_window 上下文窗口** | 静默截断（宣称 1M，32K 就召回失败）、廉价 RAG/摘要垫片导致的「中段遗忘」；用大海捞针 + 二分搜索实测 |
| **capability 能力声明** | 工具调用 / JSON 模式 / json-schema / 最大输出等声称的能力是否真的兑现（或「过度兑现」，反向暗示是替身模型）；以及**视觉**——向声称支持图像输入的模型发送一张答案已知的生成图，确认它真的「看得见」 |
| **billing 计费** | 通过独立分词估算，发现 token/usage 虚高，以及缺失/无法核验的用量统计 |
| **streaming 流式** | 通过分片数量与分片间隔时序，识别伪流式（缓存后切片）|
| **protocol 协议兼容** | OpenAI 兼容性一致性：多轮、停止序列、响应结构、错误结构；并含一项「确定性」子检查，识别忽略 temperature/seed 的响应缓存 |
| **reliability 可靠性** | 并发成功率与延迟（HTTP 429 限流单独计列，不计入失败）|
| **performance 性能表现** | 延迟、首 token 时间与吞吐是否*稳定*、探测失败率、并发负载下的变慢程度；速度本身只与参考值对比 |
| **connectivity 连通性** | 端点可达性与声称的 `/v1/models` 列表 |
| **security 安全** | 传输（HTTPS）、响应头卫生、密钥回显；隐藏注入的系统提示词（固定的输入 token 开销 + 泄露）、借助答案已知的金丝雀探测传输途中对响应/工具调用的篡改（URL/包名替换），以及提示词前缀缓存（时序）|

每项检测背后的技术、对应的中转作弊手法、以及误报注意事项，详见
[docs/METHODOLOGY.md](docs/METHODOLOGY.md)。

### 性能

每份报告还包含一个 **performance（性能）** 部分：延迟、首 token 时间（TTFT）、解码与端到端
tokens/s、分片间延迟与抖动、错误/超时/429 比率、网络拆解（TCP 连接、TLS、一次
`GET /models` 往返、服务端耗时）以及冷启动，每项都给出
count / min / mean / p50 / p75 / p90 / p95 / p99 / max / stdev。运行专用探测时，它为 **performance（性能表现）** 维度评分（权重 6）——依据的是延迟、TTFT 与吞吐的*稳定性*、失败率以及负载下的表现，而不是绝对速度：慢但稳定的模型（如本地部署）不会被扣分。速度本身只在与参考值（基线，或知识库中公布的区间）对比时计入。这些发现最高为低严重度，从不改变风险结论。

- **standard** 从检测自身的请求中收集。
- **deep / full** 额外运行一个专用探测：100 个不可缓存、输出 128 token 的请求
  （每个提示词以随机请求 id 开头，不发送任何缓存或推理参数），外加一次按 `--concurrency`
  并发的突发请求。可用 `--performance-requests`（0 表示关闭）和 `--performance-max-tokens` 调整。
- 探测默认使用流式；`--performance-non-streaming`（或 Web 界面中的开关）用于测量不支持流式的中转。
  **full** 会交替测量两种模式并并排展示。
- **compare** 在两个端点上交替发请求运行探测，并附加一张「目标 vs 基线」对比表
  （`standard` 下每侧 5 个请求）：目标更好的差异标绿 ✓，更差的标红 ✗。
  生成速度比基线快 2 倍以上的目标会被标记为一条低严重度提示。

token 会计数两次：来自中转的 `usage`，以及本地计数，因此即使缺少 `usage` 也能测出吞吐。
只有样本足够时才显示分位数（p90 需 10 个、p95 需 20 个、p99 需 100 个）。
JSON 报告保留每个请求的耗时（只有数字，不含文本）；HTML 报告和 Web 界面会按检测时间线绘制图表。

## 两种检测模式

- **纯代码（默认）**：所有可确定性判定的探测——指纹、上下文扫描、账单计算、流式时序。
  无需第二个模型，完全可复现。
- **代码 + LLM 融合（`--judge`）**：在此基础上，额外调用一个**可信的**裁判模型
  （单独配置，绝不用被测中转站本身）来评估纯代码无法判定的模糊信号，
  如回答质量、推理深度。`quality_judge` 检测器即由此驱动。

```bash
zing check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

## 持续监控（`zing watch`）

中转站可能今天提供真模型，下周就悄悄换掉。`zing watch` 按计划定期重新检测，把每次运行记入历史，
并在风险越过阈值或相比上次**恶化**时向 Webhook 告警。

```bash
zing watch --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang zh                                     # 或用 --once 配合 cron
```

告警会针对 **Slack / 飞书 / 钉钉 / 通用 JSON** 进行格式化（根据 Webhook URL 自动识别），
并以告警语言撰写——默认英文；`--alert-lang en|zh|fr|es|pt|it|de`。通用 JSON 载荷的键和机器值
（`risk_level`、`score` 等）保持与语言无关，翻译面向人阅读的字段（`text`、`headline`、
`key_findings`），并注明 `language`。

更喜欢界面操作？`zing serve` 在 **`/watches`**（🔔 监控）内置了监控页：在浏览器里添加一个监控，
进程内的后台调度器会按间隔重新运行它，把每次运行持久化到历史，并在越过阈值或恶化时触发同样的
Webhook 告警。每个监控都有自己的告警语言（在表单中选择，默认为界面语言，也可在监控卡片上修改）。
可在页面上立即运行 / 暂停 / 删除。key 只存放在 `~/.zing` 中，绝不会返回给浏览器。

## Embedding 与 rerank 检测

Embedding 和 rerank 不属于对话接口，因此 zing 用一个专门的独立检测器来审计它们，
而不走九维度的对话检测流水线。

```bash
# 期望的向量维度会根据声称的模型从内置知识库中解析。
zing embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# 或直接指定期望维度：
zing embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank：内置一个答案已知的探测——真正的 reranker 必须把明显相关的文档排在第一。
zing rerank --base-url https://relay.example.com/v1 --model my-rerank
```

`embed` 检查连通性、**维度匹配**（返回的向量长度 vs 声称模型的原生维度——这是最核心的
「货不对板」信号；声称是 3072 维的 `text-embedding-3-large` 却返回 1024 维，说明模型被替换了）、
确定性（相同输入 → 余弦 ≈ 1）、区分度（无关输入 → 余弦明显小于 1），以及回包里的 `model` 字段。
内置知识库画像：OpenAI `text-embedding-3-small`（1536）、`text-embedding-3-large`（3072）、
`text-embedding-ada-002`（1536），通义千问 `text-embedding-v3`/`-v4`（1024）。

两者也都在 Web 界面中——`zing serve` 在 `/tools` 提供 **工具箱** 页面（导航栏有链接），
其中的 embed/rerank 表单会呈现同样的本地化结论。

## 图像与音频（TTS）生成检测

另外两个非对话接口：图像生成（`POST /v1/images/generations`）和文本转语音
（`POST /v1/audio/speech`）。所有解码都只用标准库——从文件头字节读取图像尺寸
（PNG/JPEG/GIF/WebP），用 `wave` 模块读取 WAV 时长。

```bash
# 声称是 DALL·E 3 的中转真的返回了所请求的 1792x1024 吗？被缩小 / 尺寸错误的图像
# （或尺寸不在声称模型的原生尺寸范围内，按知识库解析）就是最核心的「货不对板」信号。
zing image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# 声称是 tts-1-hd 的中转返回的是时长随输入增长的真实音频吗
# （而不是固定的占位音频，也不是伪装成音频的 HTML/JSON）？
zing audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --format wav --save clip.wav
```

`image` 检查：连通性、格式合法/可解码、**尺寸匹配**（解码出的宽x高 vs 请求尺寸及声称模型的
原生尺寸——不匹配即 FAIL/HIGH）、区分度（两个提示词 → 不同图像，识别固定占位图）、数量、model 字段。
`audio` 检查：连通性、容器/格式合法性、是否遵循所请求的格式、非平凡时长（随输入长度增长）、
区分度、model 字段。知识库内置 OpenAI DALL·E 2/3、gpt-image-1、tts-1/tts-1-hd/gpt-4o-mini-tts，
以及通义千问的图像/TTS 画像。

## 在 CI 中使用（GitHub Action）

用内置的 composite action，让任意工作流以中转检测结果为门禁。它运行
`zing check --compact --fail-on-risk`，把 `risk` / `score` / `rating` 作为输出暴露出来，
在运行页写入摘要，并在风险门禁触发时让任务失败。

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: zing
        uses: cenbonew/zing@v0.9.0          # 固定到某个发布 tag
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # 调用方的 secret；绝不回显
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.zing.outputs.risk }} score=${{ steps.zing.outputs.score }}"
```

中转 key 通过环境变量传入（`--api-key env:…`），因此绝不会出现在命令行上。
完整的输入/输出表和部署门禁示例见 [docs/CI.md](docs/CI.md)。

## 套件（suite）

| 套件 | 包含检测器 | 成本 |
|---|---|---|
| `smoke` | connectivity, security | 极低 |
| `standard` | + protocol, model_identity, capability, streaming, billing, reliability | 低–中 |
| `deep` | + context_window, determinism, injected_prompt, integrity, performance, prompt_cache, quality_judge（加 `--judge` 时）| 较高（长上下文与时序探测消耗 token）|
| `full` | 全部 | 最高 |
| `custom` | 仅所选维度，按 `deep` 深度 | 取决于所选 |

**自定义套件：** `zing check ... -D protocol -D performance`（或 `--suite custom --dimension billing,streaming`；配置文件中为 `run.dimensions`）只运行所选维度。综合得分仅为这些维度的加权平均；若未选择任何核心维度（模型身份、上下文窗口、能力声明），风险结论为「无法判定」。Web 界面提供同样的选择。

上下文窗口探测受 `--max-context-tokens`（默认 200K）约束，因此审计 1M 上下文的模型也能控制花费。

## 结论示例

```text
╭─ ✗ HIGH RISK — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · confidence medium                             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • 在 gpt-4o 名义下自我标识为竞品品牌（anthropic）
  • 真实上下文窗口约 8000 << 声称的 128000（疑似静默截断）
  • 上报的 prompt token 数远超独立估算
```

报告以 JSON、Markdown、HTML 三种格式写入 `reports/`。

## 知识库

平台画像位于 [`zing/knowledge/data/`](zing/knowledge/data)，是可编辑的 YAML——
每个平台一个文件（OpenAI、Anthropic、Google Gemini、DeepSeek、通义千问 Qwen、智谱 GLM、月之暗面 Moonshot）。
每个模型都带有原生上下文窗口、最大输出、分词器、能力标志、身份关键词与行为指纹。
无需 fork 即可新增或覆盖画像：

```bash
zing check --kb-dir ./my-profiles ...     # 或设置 ZING_KB_DIR
```

## 负责任使用

zing 是黑盒审计的辅助工具。它**无法证明**：

- 服务方是否存储或用于训练你的 prompt；
- 它是否始终路由到某个确切的模型（中转可能做概率性路由）；
- 超出独立 token 估算所能暗示范围之外的计费欺诈。

请将报告用于你自己的尽职调查。**不要仅凭单次运行就公开指控某个服务商**，
应先评估样本量、成本设置与当地法律。在得出强结论前，请先用 `zing compare`
与可信基线对比。

## 许可证

[Apache-2.0](LICENSE)
