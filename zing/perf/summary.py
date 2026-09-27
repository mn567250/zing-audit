"""Turn recorded requests into the report's performance section.

Headline stats per endpoint come from the dedicated probe when it ran (uniform,
uncacheable requests), otherwise from the audit's own ("passive") requests.
Cached responses and the probe's warm-up request never enter the stats; errors,
timeouts and 429s are counted over every request so a relay that fails its slow
calls cannot look fast.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from zing.models import (
    ConcurrencyPerformance,
    EndpointPerformance,
    InputSizeBucket,
    PerformanceComparison,
    PerformanceReport,
    PerfStats,
    ProbeCost,
    RequestRecord,
)
from zing.utils.stats import PERCENTILE_MIN_SAMPLES, describe, percentile

PROBE_PHASES = ("probe", "probe_concurrent", "warmup")

# Prompt-size buckets (local token count) for the TTFT-vs-input-size view.
_INPUT_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("<1K", 0, 1_000),
    ("1K-8K", 1_000, 8_000),
    ("8K-32K", 8_000, 32_000),
    ("32K-128K", 32_000, 128_000),
    ("≥128K", 128_000, None),
)

# Reported output far above the visible text: hidden reasoning tokens.
_HIDDEN_REASONING_RATIO = 1.5
_HIDDEN_REASONING_MIN_EXTRA = 20

NOTE_PASSIVE = (
    "Headline numbers come from the audit's own requests, which mix prompt and "
    "output sizes; the deep and full suites add a controlled, uncacheable probe."
)
NOTE_REASONING = (
    "Reasoning tokens detected: TTFT is the time to the first visible token and "
    "includes hidden thinking, and usage-based throughput counts thinking tokens. "
    "zing does not set a reasoning effort (the modes a relay accepts are unknown), "
    "so the model thinks at its default effort."
)
NOTE_ESTIMATED = (
    "Local token counts are estimates (about ±15-20%): no exact tokenizer is "
    "available for this model family."
)
NOTE_PERCENTILES = (
    "Percentiles need enough samples: p75 from 4, p90 from 10, p95 from 20, "
    "p99 from 100 requests."
)
NOTE_RELAY_HEADERS = (
    "Relay processing times come from the relay's own response headers and are unverified."
)


def note_cached(n: int) -> str:
    return (
        f"{n} request(s) were served fully or partly from a cache and are left out "
        "of the statistics."
    )


def _stats(values: Sequence[float | None]) -> PerfStats:
    return PerfStats.model_validate(describe([float(v) for v in values if v is not None]))


def _field(records: Sequence[RequestRecord], get: Callable[[RequestRecord], float | None]) -> PerfStats:
    return _stats([get(r) for r in records])


def _completes(records: Sequence[RequestRecord], endpoint: str) -> list[RequestRecord]:
    return [r for r in records if r.endpoint == endpoint and r.op == "complete"]


def hidden_reasoning(records: Sequence[RequestRecord]) -> bool:
    """True when usage reports reasoning tokens, or reported output tokens run far
    above the visible text (a reasoning model that does not itemize them)."""
    if any(r.reasoning_tokens for r in records):
        return True
    ratios = [
        r.output_tokens_reported / r.output_tokens_local
        for r in records
        if r.ok
        and r.output_tokens_reported is not None
        and r.output_tokens_local
        and r.output_tokens_reported - r.output_tokens_local >= _HIDDEN_REASONING_MIN_EXTRA
    ]
    good = [
        r for r in records if r.ok and r.output_tokens_reported is not None and r.output_tokens_local
    ]
    if not good or len(ratios) * 2 < len(good):
        return False
    median = percentile(ratios, 50)
    return median is not None and median >= _HIDDEN_REASONING_RATIO


def _concurrency(records: Sequence[RequestRecord], level: int) -> ConcurrencyPerformance | None:
    burst = [r for r in records if r.phase == "probe_concurrent"]
    if not burst:
        return None
    good = [r for r in burst if r.ok and not r.cached]
    wall: float | None = None
    agg_rep: float | None = None
    agg_loc: float | None = None
    ends = [r.start_ms + r.duration_ms for r in burst if r.duration_ms is not None]
    if ends:
        wall = max(ends) - min(r.start_ms for r in burst)
    if wall and wall > 0:
        rep = [r.output_tokens_reported for r in good if r.output_tokens_reported is not None]
        loc = [r.output_tokens_local for r in good if r.output_tokens_local is not None]
        agg_rep = sum(rep) / (wall / 1000) if rep else None
        agg_loc = sum(loc) / (wall / 1000) if loc else None
    return ConcurrencyPerformance(
        concurrency=level,
        requests=len(burst),
        successes=sum(1 for r in burst if r.ok),
        wall_ms=wall,
        aggregate_tps_reported=agg_rep,
        aggregate_tps_local=agg_loc,
        latency_ms=_field(good, lambda r: r.duration_ms),
        ttft_ms=_field([r for r in good if r.stream], lambda r: r.ttft_ms),
    )


def _input_buckets(records: Sequence[RequestRecord]) -> list[InputSizeBucket]:
    good = [
        r for r in records
        if r.ok and not r.cached and r.phase != "warmup" and r.input_tokens_local is not None
    ]
    out: list[InputSizeBucket] = []
    for label, lo, hi in _INPUT_BUCKETS:
        members = [
            r for r in good
            if r.input_tokens_local is not None
            and r.input_tokens_local >= lo
            and (hi is None or r.input_tokens_local < hi)
        ]
        if not members:
            continue
        ttfts = [r.ttft_ms for r in members if r.stream and r.ttft_ms is not None]
        lats = [r.duration_ms for r in members if r.duration_ms is not None]
        out.append(
            InputSizeBucket(
                label=label,
                min_tokens=lo,
                max_tokens=hi,
                count=len(members),
                ttft_p50_ms=percentile(ttfts, 50),
                latency_p50_ms=percentile(lats, 50),
            )
        )
    return out


def summarize_endpoint(
    records: Sequence[RequestRecord], endpoint: str = "target", *, concurrency: int = 0
) -> EndpointPerformance:
    """Headline performance of one endpoint from its recorded requests."""
    mine = [r for r in records if r.endpoint == endpoint]
    completes = _completes(records, endpoint)
    probe = [r for r in completes if r.phase == "probe"]
    source = "probe" if probe else "passive"
    pool = probe or [r for r in completes if r.phase == "passive"]
    good = [r for r in pool if r.ok and not r.cached]
    streamed = [r for r in good if r.stream]
    n = len(pool)
    errors = sum(1 for r in pool if not r.ok and not r.rate_limited)
    timeouts = sum(1 for r in pool if r.timeout)
    limited = sum(1 for r in pool if r.rate_limited)

    pings = [r for r in mine if r.op == "list_models" and r.phase == "ping" and r.ok]
    warmups = [r for r in completes if r.phase == "warmup"]
    cold = warmups[0] if warmups else None

    return EndpointPerformance(
        endpoint=endpoint,
        source=source,
        requests=n,
        successes=sum(1 for r in pool if r.ok),
        errors=errors,
        timeouts=timeouts,
        rate_limited=limited,
        cached_excluded=sum(1 for r in pool if r.ok and r.cached),
        error_rate=errors / n if n else None,
        timeout_rate=timeouts / n if n else None,
        rate_limited_rate=limited / n if n else None,
        latency_ms=_field(good, lambda r: r.duration_ms),
        ttft_ms=_field(streamed, lambda r: r.ttft_ms),
        decode_tps_reported=_field(streamed, lambda r: r.decode_tps_reported),
        decode_tps_local=_field(streamed, lambda r: r.decode_tps_local),
        e2e_tps_reported=_field(good, lambda r: r.e2e_tps_reported),
        e2e_tps_local=_field(good, lambda r: r.e2e_tps_local),
        itl_ms=_field(streamed, lambda r: r.itl_mean_ms),
        itl_jitter_ms=_field(streamed, lambda r: r.itl_jitter_ms),
        # Connection setup is rare with a pooled client, so use every request.
        connect_ms=_field(mine, lambda r: r.connect_ms),
        tls_ms=_field(mine, lambda r: r.tls_ms),
        server_ms=_field(good, lambda r: r.server_ms),
        relay_processing_ms=_field(good, lambda r: r.relay_processing_ms),
        network_rtt_ms=_field(pings, lambda r: r.duration_ms),
        cold_start_ms=cold.duration_ms if cold and cold.ok else None,
        cold_start_ttft_ms=cold.ttft_ms if cold and cold.ok else None,
        concurrency=_concurrency(completes, concurrency),
        ttft_by_input=_input_buckets(completes),
        reasoning_tokens_seen=hidden_reasoning(completes),
    )


# (metric id, unit, getter) for the target-vs-baseline table.
_COMPARE: tuple[tuple[str, str, Callable[[EndpointPerformance], float | None]], ...] = (
    ("latency_p50", "ms", lambda e: e.latency_ms.p50),
    ("latency_p90", "ms", lambda e: e.latency_ms.p90),
    ("ttft_p50", "ms", lambda e: e.ttft_ms.p50),
    ("ttft_p90", "ms", lambda e: e.ttft_ms.p90),
    ("decode_tps_reported_p50", "tok/s", lambda e: e.decode_tps_reported.p50),
    ("decode_tps_local_p50", "tok/s", lambda e: e.decode_tps_local.p50),
    ("e2e_tps_local_p50", "tok/s", lambda e: e.e2e_tps_local.p50),
    ("itl_p50", "ms", lambda e: e.itl_ms.p50),
    ("server_p50", "ms", lambda e: e.server_ms.p50),
    ("network_rtt_p50", "ms", lambda e: e.network_rtt_ms.p50),
    ("error_rate", "ratio", lambda e: e.error_rate),
)


def compare_endpoints(
    target: EndpointPerformance, baseline: EndpointPerformance
) -> list[PerformanceComparison]:
    rows: list[PerformanceComparison] = []
    for metric, unit, get in _COMPARE:
        t, b = get(target), get(baseline)
        if t is None and b is None:
            continue
        rows.append(
            PerformanceComparison(
                metric=metric,
                unit=unit,
                target=t,
                baseline=b,
                delta=(t - b) if t is not None and b is not None else None,
                ratio=(t / b) if t is not None and b else None,
            )
        )
    return rows


def _probe_cost(records: Sequence[RequestRecord]) -> ProbeCost | None:
    probe = [r for r in records if r.op == "complete" and r.phase in PROBE_PHASES]
    if not probe:
        return None
    return ProbeCost(
        requests=len(probe),
        input_tokens_reported=sum(r.input_tokens_reported or 0 for r in probe),
        output_tokens_reported=sum(r.output_tokens_reported or 0 for r in probe),
        input_tokens_local=sum(r.input_tokens_local or 0 for r in probe),
        output_tokens_local=sum(r.output_tokens_local or 0 for r in probe),
    )


def build_performance(
    records: Sequence[RequestRecord],
    *,
    tokenizer: str | None = None,
    tokens_exact: bool = False,
    has_baseline: bool = False,
    probe_max_tokens: int | None = None,
    concurrency: int = 0,
) -> PerformanceReport | None:
    """The report's performance section, or None when nothing was recorded."""
    if not any(r.op == "complete" for r in records):
        return None
    target = summarize_endpoint(records, "target", concurrency=concurrency)
    baseline = (
        summarize_endpoint(records, "baseline", concurrency=concurrency) if has_baseline else None
    )
    probe_n = sum(1 for r in records if r.endpoint == "target" and r.phase == "probe")

    notes: list[str] = []
    if target.source == "passive":
        notes.append(NOTE_PASSIVE)
    completes = [r for r in records if r.op == "complete"]
    if hidden_reasoning(completes):
        notes.append(NOTE_REASONING)
    cached = sum(1 for r in completes if r.ok and r.cached)
    if cached:
        notes.append(note_cached(cached))
    if not tokens_exact:
        notes.append(NOTE_ESTIMATED)
    floor = PERCENTILE_MIN_SAMPLES["p99"]
    if any(e.latency_ms.count < floor for e in (target, baseline) if e is not None):
        notes.append(NOTE_PERCENTILES)
    if any(r.relay_processing_ms is not None for r in records):
        notes.append(NOTE_RELAY_HEADERS)

    return PerformanceReport(
        source=target.source,
        probe_requests=probe_n,
        probe_max_tokens=probe_max_tokens if probe_n else None,
        tokenizer=tokenizer,
        tokens_exact=tokens_exact,
        target=target,
        baseline=baseline,
        comparison=compare_endpoints(target, baseline) if baseline is not None else [],
        probe_cost=_probe_cost(records),
        requests=list(records),
        notes=notes,
    )
