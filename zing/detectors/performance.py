"""Performance probe — controlled latency / TTFT / throughput measurement.

The audit's own requests mix prompt and output sizes, so their timings describe
nothing in particular. This probe sends N uniform streaming requests per
endpoint instead, and every one is uncacheable: a random request id opens the
prompt (prompt caches key on the prefix, response caches on the whole request),
the topic rotates, no cache controls are sent, and the prompt stays far below
the 1024-token automatic-caching minimum. A response that still comes back
cached, or repeats an earlier one verbatim, is flagged and left out of the stats.

Order of work, per endpoint (target and baseline alternate in compare mode so
network drift during the run hits both equally):

1. three ``GET /models`` pings (``Cache-Control: no-cache``) — network round trip
2. one warm-up request — reported as cold start, excluded from the stats
3. N probe requests per request mode
4. (deep/full) a burst at the reliability concurrency — throughput under load

Requests stream by default; ``performance_streaming=False`` measures relays that
cannot stream. The full suite measures both modes, interleaved.

No reasoning-effort parameter is sent: the modes a relay accepts are unknown, so
a reasoning model thinks at its default effort (the report says so).

The probe is informational — its score is always None. Runs on deep/full, and
with 5 requests on the standard suite in compare mode.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Sequence

from zing import prompts
from zing.clients import Client
from zing.config import AuditOptions
from zing.context import AuditContext
from zing.detectors.base import SUITE_ORDER, Detector, register
from zing.detectors.scale import Scale, outcome
from zing.models import (
    CompletionOutcome,
    DetectorResult,
    Dimension,
    EndpointPerformance,
    RequestRecord,
    RequestSpec,
    Severity,
    Status,
)
from zing.perf import RequestRecorder, phase_scope, summarize_endpoint
from zing.perf.recorder import last_record
from zing.perf.summary import hidden_reasoning

PINGS = 3
# Probe size on the standard suite, where it only runs in compare mode.
STANDARD_COMPARE_REQUESTS = 5
# Burst size: a few rounds at the configured concurrency.
_BURST_ROUNDS = 4
_MIN_BURST = 8
# Decode throughput this far above the baseline suggests a smaller model.
_FAST_RATIO = 2.0
# Minimum clean samples per side before comparing throughput.
_MIN_COMPARE_SAMPLES = 5
_ERROR_RATE_WARN = 0.1

# 4xx texts meaning "this model wants max_completion_tokens" (reasoning models).
_PARAM_REJECTION_HINTS = (
    "max_tokens",
    "max_completion_tokens",
    "unsupported parameter",
    "unsupported value",
)


def _deep(suite: str) -> bool:
    return suite in SUITE_ORDER and SUITE_ORDER.index(suite) >= SUITE_ORDER.index("deep")


def planned_probe_requests(options: AuditOptions, *, has_baseline: bool) -> int:
    """Probe requests per endpoint for this run (0 = the probe does not run)."""
    n = options.performance_requests
    if n <= 0:
        return 0
    if _deep(options.suite):
        return n
    if options.suite == "standard" and has_baseline:
        return min(STANDARD_COMPARE_REQUESTS, n)
    return 0


def probe_modes(options: AuditOptions) -> list[bool]:
    """Request modes to probe (True = streaming), headline mode first."""
    if options.suite == "full":
        return [True, False]
    return [options.performance_streaming]


def burst_size(options: AuditOptions, probe_requests: int) -> int:
    """Requests in the concurrency burst (deep/full only)."""
    if not _deep(options.suite) or probe_requests <= 0:
        return 0
    conc = max(1, options.reliability_concurrency)
    return min(probe_requests, max(conc * _BURST_ROUNDS, _MIN_BURST))


def estimated_calls(options: AuditOptions, *, has_baseline: bool) -> int:
    """API calls the probe makes across all endpoints — for ``--dry-run``."""
    n = planned_probe_requests(options, has_baseline=has_baseline)
    if n == 0:
        return 0
    per_endpoint = PINGS + 1 + (n + burst_size(options, n)) * len(probe_modes(options))
    return per_endpoint * (2 if has_baseline else 1)


def _is_param_rejection(outcome: CompletionOutcome) -> bool:
    if outcome.ok or outcome.status_code is None or not 400 <= outcome.status_code < 500:
        return False
    msg = (outcome.error_message or "").lower()
    return any(hint in msg for hint in _PARAM_REJECTION_HINTS)


class _Endpoint:
    """One side of the probe and its per-endpoint state."""

    def __init__(self, label: str, client: Client) -> None:
        self.label = label
        self.client = client
        self.use_completion_tokens = False
        self.seen: set[str] = set()


# Informational: no outcome is counted, so the probe never has a score.
SCALE = Scale(
    outcome("performance.summary", "measured", None, Status.INFO,
            label="Latency, TTFT and throughput were measured (informational)."),
    outcome("performance.summary", "no_success", None, Status.INCONCLUSIVE,
            label="None of the probe requests succeeded."),
    outcome("performance.errors", "failed", None, Status.WARN, Severity.LOW,
            label="Many probe requests failed or timed out (informational)."),
    outcome("performance.cache_hit", "cached", None, Status.WARN, Severity.LOW,
            label="Unique probe prompts came back from a cache (left out of the statistics)."),
    outcome("performance.reasoning", "hidden_reasoning", None, Status.INFO,
            label="The model spends hidden reasoning tokens; TTFT includes thinking."),
    outcome("performance.relay_overhead", "compared", None, Status.INFO,
            label="Latency compared with the trusted baseline (informational)."),
    outcome("performance.throughput_mismatch", "faster", None, Status.WARN, Severity.LOW,
            label="The target decodes much faster than the baseline (consistent with a smaller model)."),
    outcome("performance.skipped", "disabled", None, Status.INFO,
            label="The performance probe was disabled."),
)

@register
class PerformanceDetector(Detector):
    id = "performance"
    name = "Performance probe"
    # Informational only (score None): it sits with reliability so it adds no
    # scoring dimension and never moves the verdict.
    dimension = Dimension.RELIABILITY
    min_suite = "standard"
    cost_hint = 120

    @classmethod
    def applies(cls, suite: str, *, has_baseline: bool) -> bool:
        return _deep(suite) or (suite == "standard" and has_baseline)

    def __init__(self) -> None:
        self._counter = 0

    # -- request building --------------------------------------------------- #
    def _spec(self, max_tokens: int, *, stream: bool, use_completion_tokens: bool) -> RequestSpec:
        topics: list[str] = prompts.get("performance.topics")
        topic = topics[self._counter % len(topics)]
        self._counter += 1
        content = prompts.text("performance.probe", nonce=secrets.token_hex(8), topic=topic)
        messages = [{"role": "user", "content": content}]
        if use_completion_tokens:
            return RequestSpec(
                messages=messages,
                temperature=None,
                max_tokens=None,
                stream=stream,
                extra_body={"max_completion_tokens": max_tokens},
            )
        return RequestSpec(
            messages=messages, temperature=None, max_tokens=max_tokens, stream=stream
        )

    async def _call(self, ep: _Endpoint, max_tokens: int, stream: bool) -> RequestRecord | None:
        outcome = await ep.client.complete(
            self._spec(max_tokens, stream=stream, use_completion_tokens=ep.use_completion_tokens)
        )
        if not ep.use_completion_tokens and _is_param_rejection(outcome):
            # Likely a reasoning model that wants max_completion_tokens: keep the
            # rejected call out of the stats and retry the way it asks.
            rejected = last_record()
            if rejected is not None:
                rejected.phase = "param_retry"
            ep.use_completion_tokens = True
            outcome = await ep.client.complete(
                self._spec(max_tokens, stream=stream, use_completion_tokens=True)
            )
        record = last_record()
        if record is None:
            return None
        # A verbatim repeat of an earlier answer to a unique prompt is a cache hit.
        text = (outcome.content or "").strip()
        if outcome.ok and text:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if digest in ep.seen:
                record.cached = True
            ep.seen.add(digest)
        return record

    async def _burst(
        self, ep: _Endpoint, size: int, conc: int, max_tokens: int, stream: bool
    ) -> None:
        sem = asyncio.Semaphore(conc)

        async def one() -> None:
            async with sem:
                await self._call(ep, max_tokens, stream)

        await asyncio.gather(*(one() for _ in range(size)))

    # -- run ---------------------------------------------------------------- #
    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        result.score = None
        opts = ctx.options
        n = planned_probe_requests(opts, has_baseline=ctx.has_baseline)
        if n <= 0:
            result.status = Status.NOT_RUN
            result.findings.append(
                SCALE.finding(
                    "performance.skipped",
                    "disabled",
                    title="Performance probe disabled",
                    summary="performance_requests <= 0; no probe requests were sent.",
                    evidence={"performance_requests": opts.performance_requests},
                )
            )
            return result

        endpoints = [_Endpoint("target", ctx.client)]
        if ctx.baseline_client is not None:
            endpoints.append(_Endpoint("baseline", ctx.baseline_client))

        # Standalone use (no runner): record into a private recorder.
        recorder = ctx.recorder
        attached: list[Client] = []
        if recorder is None:
            recorder = RequestRecorder(ctx.tokenizer_hint())
            for ep in endpoints:
                if ep.client.recorder is None:
                    ep.client.recorder, ep.client.endpoint = recorder, ep.label
                    attached.append(ep.client)
        first = len(recorder.records)
        max_tokens = max(1, opts.performance_max_tokens)
        conc = max(1, opts.reliability_concurrency)
        burst = burst_size(opts, n)
        modes = probe_modes(opts)

        try:
            with phase_scope("ping"):
                for _ in range(PINGS):
                    for ep in endpoints:
                        await ep.client.list_models(no_cache=True)
            with phase_scope("warmup"):
                for ep in endpoints:
                    await self._call(ep, max_tokens, modes[0])
            with phase_scope("probe"):
                for i in range(n):
                    for stream in modes:
                        # Alternate who goes first so neither side always follows the other.
                        for ep in endpoints if i % 2 == 0 else endpoints[::-1]:
                            await self._call(ep, max_tokens, stream)
            if burst:
                with phase_scope("probe_concurrent"):
                    for stream in modes:
                        for ep in endpoints:
                            await self._burst(ep, burst, conc, max_tokens, stream)
        finally:
            for client in attached:
                client.recorder = None

        records = recorder.records[first:]
        # Findings describe the headline mode (streaming when it was probed).
        summaries = {
            ep.label: summarize_endpoint(records, ep.label, concurrency=conc, stream=modes[0])
            for ep in endpoints
        }
        result.evidence["performance_probe"] = {
            "requests_per_endpoint": n,
            "max_tokens": max_tokens,
            "burst": burst,
            "modes": ["stream" if m else "non_stream" for m in modes],
            "concurrency": conc,
            "max_completion_tokens": {ep.label: ep.use_completion_tokens for ep in endpoints},
        }
        self._findings(result, records, summaries, n, stream=modes[0])

        # Always INFO: the probe shares the reliability dimension but must never
        # change its status (the summary finding says when nothing succeeded).
        result.status = Status.INFO
        return result

    # -- findings ----------------------------------------------------------- #
    @staticmethod
    def _headline(ep: EndpointPerformance) -> dict[str, float | int | str | None]:
        return {
            "requests": ep.requests,
            "successes": ep.successes,
            "latency_p50_ms": _r(ep.latency_ms.p50),
            "latency_p95_ms": _r(ep.latency_ms.p95),
            "ttft_p50_ms": _r(ep.ttft_ms.p50),
            "decode_tps_p50": _r(ep.decode_tps_local.p50),
            "network_rtt_p50_ms": _r(ep.network_rtt_ms.p50),
        }

    def _findings(
        self,
        result: DetectorResult,
        records: Sequence[RequestRecord],
        summaries: dict[str, EndpointPerformance],
        n: int,
        *,
        stream: bool = True,
    ) -> None:
        target = summaries["target"]
        baseline = summaries.get("baseline")
        head = self._headline(target)
        head["mode"] = "stream" if stream else "non_stream"
        if target.successes and stream:
            summary = (
                f"{target.successes} of {target.requests} probe requests succeeded; "
                f"p50 latency {_fmt(target.latency_ms.p50, 'ms')}, "
                f"p50 TTFT {_fmt(target.ttft_ms.p50, 'ms')}, "
                f"p50 decode {_fmt(target.decode_tps_local.p50, 'tok/s')}."
            )
        elif target.successes:
            summary = (
                f"{target.successes} of {target.requests} non-streaming probe requests "
                f"succeeded; p50 latency {_fmt(target.latency_ms.p50, 'ms')}, "
                f"p50 end-to-end {_fmt(target.e2e_tps_local.p50, 'tok/s')}."
            )
        else:
            summary = f"None of the {target.requests} probe requests succeeded."
        result.findings.append(
            SCALE.finding(
                "performance.summary",
                "measured" if target.successes else "no_success",
                title="Performance probe results",
                summary=summary,
                evidence=head,
            )
        )

        for ep in summaries.values():
            if ep.error_rate is not None and ep.error_rate > _ERROR_RATE_WARN:
                result.findings.append(
                    SCALE.finding(
                        "performance.errors",
                        "failed",
                        title="Performance probe requests failed",
                        summary=f"{ep.errors + ep.timeouts} of {ep.requests} {ep.endpoint} probe "
                        f"requests failed ({ep.timeouts} timed out, {ep.rate_limited} rate-limited).",
                        evidence={
                            "endpoint": ep.endpoint,
                            "requests": ep.requests,
                            "errors": ep.errors,
                            "timeouts": ep.timeouts,
                            "rate_limited": ep.rate_limited,
                        },
                    )
                )

        for label in summaries:
            cached = [
                r for r in records
                if r.endpoint == label and r.phase in ("probe", "probe_concurrent") and r.cached
            ]
            if cached:
                result.findings.append(
                    SCALE.finding(
                        "performance.cache_hit",
                        "cached",
                        title="Unique probe prompts were served from a cache",
                        summary=f"{len(cached)} {label} probe request(s) reported cached input "
                        "tokens or repeated an earlier answer verbatim, although every prompt "
                        "was unique. They were left out of the statistics.",
                        evidence={"endpoint": label, "cached": len(cached)},
                        recommendation="A relay that caches unique prompts may be serving "
                        "stored answers; compare with a trusted baseline.",
                    )
                )

        probe_records = [r for r in records if r.op == "complete"]
        if hidden_reasoning(probe_records):
            result.findings.append(
                SCALE.finding(
                    "performance.reasoning",
                    "hidden_reasoning",
                    title="Reasoning tokens in the probe",
                    summary="The model spends hidden reasoning tokens: TTFT is the time to the "
                    "first visible token and includes thinking. zing sets no reasoning "
                    "effort, so the model thinks at its default effort.",
                    evidence={
                        "reasoning_tokens": sum(r.reasoning_tokens or 0 for r in probe_records),
                    },
                )
            )

        if baseline is None:
            return
        lat_t, lat_b = target.latency_ms.p50, baseline.latency_ms.p50
        ttft_t, ttft_b = target.ttft_ms.p50, baseline.ttft_ms.p50
        if lat_t is not None and lat_b is not None:
            result.findings.append(
                SCALE.finding(
                    "performance.relay_overhead",
                    "compared",
                    title="Latency versus the baseline",
                    summary=f"Target p50 latency {_fmt(lat_t, 'ms')} vs baseline "
                    f"{_fmt(lat_b, 'ms')} ({_signed(lat_t - lat_b)} ms)"
                    + (
                        f"; p50 TTFT {_fmt(ttft_t, 'ms')} vs {_fmt(ttft_b, 'ms')} "
                        f"({_signed(ttft_t - ttft_b)} ms)."
                        if ttft_t is not None and ttft_b is not None
                        else "."
                    ),
                    evidence={
                        "target_latency_p50_ms": _r(lat_t),
                        "baseline_latency_p50_ms": _r(lat_b),
                        "latency_p50_delta_ms": _r(lat_t - lat_b),
                        "ttft_p50_delta_ms": _r(ttft_t - ttft_b)
                        if ttft_t is not None and ttft_b is not None
                        else None,
                        "target": head,
                        "baseline": self._headline(baseline),
                    },
                )
            )

        # Non-streamed calls have no first token: compare end-to-end speed.
        if stream:
            tps_t, tps_b = target.decode_tps_local, baseline.decode_tps_local
        else:
            tps_t, tps_b = target.e2e_tps_local, baseline.e2e_tps_local
        if (
            tps_t.count >= _MIN_COMPARE_SAMPLES
            and tps_b.count >= _MIN_COMPARE_SAMPLES
            and tps_t.p50
            and tps_b.p50
            and tps_t.p50 / tps_b.p50 >= _FAST_RATIO
        ):
            ratio = tps_t.p50 / tps_b.p50
            result.findings.append(
                SCALE.finding(
                    "performance.throughput_mismatch",
                    "faster",
                    title="Target generates much faster than the baseline",
                    summary=f"Target decodes at {_fmt(tps_t.p50, 'tok/s')} vs baseline "
                    f"{_fmt(tps_b.p50, 'tok/s')} ({ratio:.1f}x). The same model normally "
                    "decodes at a similar speed; a much faster target is consistent with a "
                    "smaller model.",
                    evidence={
                        "target_decode_tps_p50": _r(tps_t.p50),
                        "baseline_decode_tps_p50": _r(tps_b.p50),
                        "ratio": round(ratio, 2),
                        "metric": "decode" if stream else "end_to_end",
                        "samples": min(tps_t.count, tps_b.count),
                    },
                    recommendation="Weigh this together with the model-identity findings; "
                    "speed alone is not proof of substitution.",
                )
            )


def _r(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def _fmt(value: float | None, unit: str) -> str:
    return "n/a" if value is None else f"{value:.0f} {unit}"


def _signed(value: float) -> str:
    return f"{value:+.0f}"
