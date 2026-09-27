"""Core data contracts shared across zing.

Everything that crosses a module boundary — config, a single API call's outcome,
a detector's findings, the scored report — is defined here as a pydantic model so
the JSON report is well-typed and detectors compose cleanly. Detector authors
should treat these types as the stable interface.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Status(str, Enum):
    """Outcome of a check, finding, or dimension."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    NOT_RUN = "not_run"
    INFO = "info"
    ERROR = "error"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Dimension(str, Enum):
    """Scoring dimensions. Each detector contributes to exactly one."""

    CONNECTIVITY = "connectivity"
    PROTOCOL = "protocol"
    CONTEXT_WINDOW = "context_window"
    MODEL_IDENTITY = "model_identity"
    CAPABILITY = "capability"
    STREAMING = "streaming"
    BILLING = "billing"
    RELIABILITY = "reliability"
    SECURITY = "security"


class RiskLevel(str, Enum):
    """Headline 货不对板 risk classification."""

    CLEAN = "clean"          # consistent with the claimed model
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"            # strong evidence of mismatch / downgrade
    INCONCLUSIVE = "inconclusive"


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
class TargetConfig(BaseModel):
    """A relay endpoint under audit (or a trusted baseline)."""

    model_config = ConfigDict(extra="forbid")

    name: str = "target"
    kind: str = "target"  # "target" | "baseline"
    base_url: str
    api_key: str = ""
    model: str  # the model id actually sent in requests
    # The model the relay CLAIMS to serve (for KB lookup / comparison). Defaults to
    # `model`. Set it to audit an endpoint's real model id against a different claim
    # — e.g. request `doubao-...` but verify it against the `deepseek-v4-flash` profile.
    claimed_model: str | None = None
    # Wire protocol: "auto" infers from the base_url/model, or force "openai"
    # (Chat Completions) / "anthropic" (Messages API).
    api: str = "auto"

    @property
    def claimed(self) -> str:
        return self.claimed_model or self.model
    # Optional declared metadata used to pick the right knowledge-base profile and
    # to compare claims vs reality. If absent, zing infers from the model id.
    declared_provider: str | None = None
    declared_context_window: int | None = None
    declared_max_output: int | None = None
    timeout_sec: float = 60.0
    headers: dict[str, str] = Field(default_factory=dict)
    max_retries: int = 0


class RequestSpec(BaseModel):
    """A single chat-completion request the client should issue."""

    model_config = ConfigDict(extra="forbid")

    messages: list[dict[str, Any]]
    temperature: float | None = 0.0
    max_tokens: int | None = None
    top_p: float | None = None
    stop: str | list[str] | None = None
    seed: int | None = None
    response_format: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    stream: bool = False
    extra_body: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Raw call outcome
# --------------------------------------------------------------------------- #
class CompletionOutcome(BaseModel):
    """Raw evidence from one API call. Detectors interpret these."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = False
    status_code: int | None = None
    content: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    model_returned: str | None = None

    # Timing
    duration_ms: float | None = None
    ttft_ms: float | None = None  # time to first streamed token
    # Per-event arrival offsets (ms from request start), for fake-stream analysis.
    chunk_timings_ms: list[float] = Field(default_factory=list)
    chunk_count: int = 0

    # Transport / error evidence (redacted before it ever reaches here).
    headers: dict[str, str] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    raw_error: dict[str, Any] | None = None

    def has_content(self) -> bool:
        return bool(self.content and self.content.strip())


# --------------------------------------------------------------------------- #
# Detector output
# --------------------------------------------------------------------------- #
class Finding(BaseModel):
    """A single evidence-bearing observation produced by a detector."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    status: Status
    severity: Severity = Severity.INFO
    summary: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    recommendation: str | None = None


class DetectorResult(BaseModel):
    """The result of running one detector."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    dimension: Dimension
    status: Status = Status.NOT_RUN
    # 0-100 quality/health score for this detector, or None if not scorable.
    score: float | None = None
    findings: list[Finding] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float | None = None
    error: str | None = None
    # True when this detector required an LLM judge to produce its verdict.
    used_judge: bool = False

    def worst_severity(self) -> Severity:
        order = [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        worst = Severity.INFO
        for finding in self.findings:
            if order.index(finding.severity) > order.index(worst):
                worst = finding.severity
        return worst


# --------------------------------------------------------------------------- #
# Scoring & verdict
# --------------------------------------------------------------------------- #
class DimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: Dimension
    score: float | None = None
    weight: float = 0.0
    status: Status = Status.NOT_RUN
    reason: str = ""


class ReliabilitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: int = 0
    successes: int = 0
    success_rate: float = 0.0
    # HTTP 429s — the relay correctly throttling a concurrency burst, an honest
    # behavior. Tracked apart from `errors` so it doesn't tank the success rate.
    rate_limited: int = 0
    latency_ms: dict[str, float | None] = Field(default_factory=dict)
    errors: dict[str, int] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Performance
# --------------------------------------------------------------------------- #
class RequestRecord(BaseModel):
    """Timing and token evidence for one API call made during an audit.

    Numbers only — never prompt or response text. ``phase`` says why the call was
    made: ``passive`` (an ordinary detector request), ``probe`` / ``probe_concurrent``
    (the dedicated performance probe), ``warmup`` (the probe's cold-start request,
    kept out of the stats) or ``ping`` (a ``GET /models`` round-trip measurement).
    """

    model_config = ConfigDict(extra="forbid")

    seq: int
    endpoint: str = "target"  # "target" | "baseline"
    detector: str | None = None
    phase: str = "passive"
    op: str = "complete"  # "complete" | "list_models"
    stream: bool = False
    start_ms: float = 0.0  # offset from the start of the audit

    ok: bool = False
    status_code: int | None = None
    error_type: str | None = None
    timeout: bool = False
    rate_limited: bool = False

    duration_ms: float | None = None
    ttft_ms: float | None = None
    chunk_count: int = 0
    # Gaps between streamed content chunks (a chunk may carry several tokens).
    itl_mean_ms: float | None = None
    itl_p50_ms: float | None = None
    itl_p95_ms: float | None = None
    itl_jitter_ms: float | None = None  # stdev of the gaps

    input_tokens_reported: int | None = None
    output_tokens_reported: int | None = None
    input_tokens_local: int | None = None
    output_tokens_local: int | None = None
    tokens_exact: bool = False  # local count used an exact tokenizer
    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None

    # Output tokens per second: decode = after the first token, e2e = whole call.
    decode_tps_reported: float | None = None
    decode_tps_local: float | None = None
    e2e_tps_reported: float | None = None
    e2e_tps_local: float | None = None

    # Transport breakdown from httpx trace hooks (None on a reused connection).
    connect_ms: float | None = None  # TCP connect, including DNS
    tls_ms: float | None = None
    headers_ms: float | None = None  # request start -> response headers
    # Request fully sent -> response headers (a stream: -> first token).
    server_ms: float | None = None
    # Upstream processing time a relay reports in its own headers (untrusted).
    relay_processing_ms: float | None = None

    # A cache served (part of) this request; it is excluded from the stats.
    cached: bool = False


class PerfStats(BaseModel):
    """Distribution of one metric. A percentile is None below its sample floor."""

    model_config = ConfigDict(extra="forbid")

    count: int = 0
    min: float | None = None
    mean: float | None = None
    p50: float | None = None
    p75: float | None = None
    p90: float | None = None
    p95: float | None = None
    p99: float | None = None
    max: float | None = None
    stdev: float | None = None


class ConcurrencyPerformance(BaseModel):
    """The probe's burst at the configured concurrency."""

    model_config = ConfigDict(extra="forbid")

    concurrency: int = 0
    requests: int = 0
    successes: int = 0
    wall_ms: float | None = None
    # Summed output tokens of all successful requests / wall-clock time.
    aggregate_tps_reported: float | None = None
    aggregate_tps_local: float | None = None
    latency_ms: PerfStats = Field(default_factory=PerfStats)
    ttft_ms: PerfStats = Field(default_factory=PerfStats)


class InputSizeBucket(BaseModel):
    """TTFT / latency for requests of a given prompt size (local token count)."""

    model_config = ConfigDict(extra="forbid")

    label: str
    min_tokens: int
    max_tokens: int | None = None
    count: int = 0
    ttft_p50_ms: float | None = None
    latency_p50_ms: float | None = None


class EndpointPerformance(BaseModel):
    """Headline performance of one endpoint (target or baseline)."""

    model_config = ConfigDict(extra="forbid")

    endpoint: str = "target"
    source: str = "passive"  # "probe" | "passive" — where the headline stats come from
    requests: int = 0
    successes: int = 0
    errors: int = 0
    timeouts: int = 0
    rate_limited: int = 0
    cached_excluded: int = 0
    error_rate: float | None = None
    timeout_rate: float | None = None
    rate_limited_rate: float | None = None

    latency_ms: PerfStats = Field(default_factory=PerfStats)
    ttft_ms: PerfStats = Field(default_factory=PerfStats)
    decode_tps_reported: PerfStats = Field(default_factory=PerfStats)
    decode_tps_local: PerfStats = Field(default_factory=PerfStats)
    e2e_tps_reported: PerfStats = Field(default_factory=PerfStats)
    e2e_tps_local: PerfStats = Field(default_factory=PerfStats)
    itl_ms: PerfStats = Field(default_factory=PerfStats)
    itl_jitter_ms: PerfStats = Field(default_factory=PerfStats)
    connect_ms: PerfStats = Field(default_factory=PerfStats)
    tls_ms: PerfStats = Field(default_factory=PerfStats)
    server_ms: PerfStats = Field(default_factory=PerfStats)
    relay_processing_ms: PerfStats = Field(default_factory=PerfStats)
    network_rtt_ms: PerfStats = Field(default_factory=PerfStats)  # GET /models pings

    cold_start_ms: float | None = None
    cold_start_ttft_ms: float | None = None
    concurrency: ConcurrencyPerformance | None = None
    ttft_by_input: list[InputSizeBucket] = Field(default_factory=list)
    reasoning_tokens_seen: bool = False


class PerformanceComparison(BaseModel):
    """One target-vs-baseline metric (compare mode)."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    unit: str
    target: float | None = None
    baseline: float | None = None
    delta: float | None = None  # target - baseline
    ratio: float | None = None  # target / baseline
    higher_is_better: bool = False  # e.g. tokens/s; latencies and error rates are lower-is-better

    @property
    def target_better(self) -> bool | None:
        """True / False when the target is better / worse than the baseline;
        None when they are within 2% of each other or a side is missing."""
        if self.delta is None or self.target is None or self.baseline is None:
            return None
        scale = max(abs(self.target), abs(self.baseline))
        if scale == 0 or abs(self.delta) / scale < 0.02:
            return None
        return (self.delta > 0) == self.higher_is_better


class PerformanceModeReport(BaseModel):
    """Probe results for a second request mode (the full suite measures both
    streaming and non-streaming)."""

    model_config = ConfigDict(extra="forbid")

    mode: str  # "stream" | "non_stream"
    target: EndpointPerformance = Field(default_factory=EndpointPerformance)
    baseline: EndpointPerformance | None = None
    comparison: list[PerformanceComparison] = Field(default_factory=list)


class ProbeCost(BaseModel):
    """What the dedicated performance probe cost (tokens summed over endpoints)."""

    model_config = ConfigDict(extra="forbid")

    requests: int = 0
    input_tokens_reported: int = 0
    output_tokens_reported: int = 0
    input_tokens_local: int = 0
    output_tokens_local: int = 0


class PerformanceReport(BaseModel):
    """Latency / TTFT / throughput of the audited endpoint(s). Informational — it
    never feeds the score or the verdict."""

    model_config = ConfigDict(extra="forbid")

    source: str = "passive"  # "probe" | "passive"
    # Request mode of the headline stats: "stream" / "non_stream" (probe) or
    # "mixed" (passive). ``modes`` holds any further probed mode.
    mode: str = "mixed"
    probe_requests: int = 0  # per endpoint and mode; 0 when the probe did not run
    probe_max_tokens: int | None = None
    tokenizer: str | None = None
    tokens_exact: bool = False
    target: EndpointPerformance = Field(default_factory=EndpointPerformance)
    baseline: EndpointPerformance | None = None
    comparison: list[PerformanceComparison] = Field(default_factory=list)
    modes: list[PerformanceModeReport] = Field(default_factory=list)
    probe_cost: ProbeCost | None = None
    requests: list[RequestRecord] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    """The headline judgement a user reads first."""

    model_config = ConfigDict(extra="forbid")

    overall_score: float | None = None
    rating: str | None = None  # A-F
    risk_level: RiskLevel = RiskLevel.INCONCLUSIVE
    headline: str = ""
    confidence: str = "low"  # low | medium | high
    summary: str = ""
    key_findings: list[str] = Field(default_factory=list)


class RedactedTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str
    base_url: str
    model: str
    claimed_model: str | None = None
    declared_provider: str | None = None
    api_key_fingerprint: str | None = None


# --------------------------------------------------------------------------- #
# Top-level report
# --------------------------------------------------------------------------- #
class AuditReport(BaseModel):
    """The serializable artifact zing produces. JSON form is the LLM-facing API."""

    model_config = ConfigDict(extra="forbid")

    tool_version: str
    mode: str  # "check" | "compare"
    generated_at: str | None = None  # ISO timestamp, stamped by the runner
    command: str | None = None
    suite: str

    target: RedactedTarget
    baseline: RedactedTarget | None = None

    verdict: Verdict
    dimensions: list[DimensionScore] = Field(default_factory=list)
    detectors: list[DetectorResult] = Field(default_factory=list)
    baseline_detectors: list[DetectorResult] = Field(default_factory=list)
    reliability: ReliabilitySummary | None = None
    performance: PerformanceReport | None = None

    judge_used: bool = False
    judge_model: str | None = None

    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # Languages of the prompts sent to the audited endpoint: the English prompt
    # library (zing/prompts/en.json) plus any language-bound knowledge-base
    # fingerprints (e.g. "zh" for the Chinese fluency probes of China-native
    # models). Independent of the UI and alert language.
    prompt_languages: list[str] = Field(default_factory=list)
