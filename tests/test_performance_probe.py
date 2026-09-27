"""The dedicated performance probe: suite gating, uncacheable requests, findings."""

from __future__ import annotations

import re

import httpx
import pytest
from conftest import BASE_URL, DEFAULT_MODEL, MockServer

from zing.clients import OpenAICompatibleClient
from zing.config import AuditOptions
from zing.context import AuditContext
from zing.detectors.base import select_detectors
from zing.detectors.performance import (
    PerformanceDetector,
    burst_size,
    estimated_calls,
    planned_probe_requests,
)
from zing.models import DetectorResult, Dimension, RequestRecord, Status, TargetConfig
from zing.perf import RequestRecorder, build_performance, summarize_endpoint
from zing.runner import run_audit

_NONCE = re.compile(r"^Request ([0-9a-f]{16})\. ")


class UniqueReplyServer(MockServer):
    """Answers each probe differently (as a real model would)."""

    def _reply_for(self, body: dict) -> str:
        content = body["messages"][0]["content"]
        m = _NONCE.match(content)
        if m:
            return f"Answer {m.group(1)} " + "word " * 40
        return super()._reply_for(body)


def _ids(suite: str, has_baseline: bool) -> set[str]:
    return {
        d.id
        for d in select_detectors(
            suite, has_judge=False, has_baseline=has_baseline, enabled=lambda _: True
        )
    }


def test_probe_runs_on_deep_full_and_standard_compare_only():
    assert "performance" not in _ids("smoke", False)
    assert "performance" not in _ids("standard", False)
    assert "performance" in _ids("standard", True)
    assert "performance" in _ids("deep", False)
    assert "performance" in _ids("full", True)


def test_planned_requests_and_burst():
    deep = AuditOptions(suite="deep")
    assert planned_probe_requests(deep, has_baseline=False) == 100
    assert burst_size(deep, 100) == 12  # 3 concurrency x 4 rounds
    std = AuditOptions(suite="standard")
    assert planned_probe_requests(std, has_baseline=True) == 5
    assert planned_probe_requests(std, has_baseline=False) == 0
    assert burst_size(std, 5) == 0
    assert planned_probe_requests(AuditOptions(suite="full", performance_requests=0), has_baseline=True) == 0
    # pings + warm-up + probe + burst, per endpoint
    assert estimated_calls(deep, has_baseline=True) == 2 * (3 + 1 + 100 + 12)


async def _run_probe(server: MockServer, *, suite="deep", n=6, baseline=False, knowledge_base=None,
                     streaming=True):
    rec = RequestRecorder()
    tcfg = TargetConfig(name="t", kind="target", base_url=BASE_URL, model=DEFAULT_MODEL)
    client = OpenAICompatibleClient(tcfg, transport=server.transport)
    client.recorder, client.endpoint = rec, "target"
    bclient = None
    if baseline:
        bcfg = TargetConfig(name="b", kind="baseline", base_url=BASE_URL, model=DEFAULT_MODEL)
        bclient = OpenAICompatibleClient(bcfg, transport=server.transport)
        bclient.recorder, bclient.endpoint = rec, "baseline"
    ctx = AuditContext(
        target=tcfg,
        client=client,
        options=AuditOptions(suite=suite, performance_requests=n, performance_streaming=streaming),
        kb=knowledge_base,
        baseline=bclient.config if bclient else None,
        baseline_client=bclient,
        recorder=rec,
    )
    result = await PerformanceDetector().run(ctx)
    return result, rec


async def test_probe_sends_uncacheable_uniform_requests(knowledge_base):
    server = UniqueReplyServer()
    result, rec = await _run_probe(server, knowledge_base=knowledge_base)

    phases = [r.phase for r in rec.records]
    assert phases.count("ping") == 3
    assert phases.count("warmup") == 1
    assert phases.count("probe") == 6
    assert phases.count("probe_concurrent") == 6  # min(n, max(3*4, 8))

    bodies = server.requests
    prompts = [b["messages"][0]["content"] for b in bodies]
    nonces = [_NONCE.match(p).group(1) for p in prompts]
    assert len(set(nonces)) == len(nonces)  # every request is unique…
    assert all(p.startswith("Request ") for p in prompts)  # …from the very first token
    assert len({p.split(". ", 1)[1] for p in prompts}) > 1  # wording rotates too
    for b in bodies:
        assert b["stream"] is True and b["max_tokens"] == 128
        # no sampling, cache or reasoning knobs
        for key in ("temperature", "seed", "reasoning_effort", "reasoning",
                    "prompt_cache_key", "cache_control"):
            assert key not in b

    assert result.status == Status.INFO and result.score is None
    ids = [f.id for f in result.findings]
    assert "performance.summary" in ids and "performance.cache_hit" not in ids
    assert not any(r.cached for r in rec.records)


async def test_repeated_answers_are_flagged_as_cache_hits(knowledge_base):
    server = MockServer(reply_text="the same canned answer every time")
    result, rec = await _run_probe(server, n=4, suite="standard", baseline=True,
                                   knowledge_base=knowledge_base)
    cached = [r for r in rec.records if r.cached]
    # warm-up + 4 probes per side; only the first answer per endpoint is new
    assert len(cached) == 2 * 4
    assert any(f.id == "performance.cache_hit" for f in result.findings)
    summary = summarize_endpoint(rec.records)
    assert summary.cached_excluded == 4 and summary.latency_ms.count == 0


async def test_compare_mode_alternates_endpoints(knowledge_base):
    server = UniqueReplyServer()
    result, rec = await _run_probe(server, n=4, suite="standard", baseline=True,
                                   knowledge_base=knowledge_base)
    order = [r.endpoint for r in rec.records if r.phase == "probe"]
    assert order == ["target", "baseline", "baseline", "target"] * 2
    assert [r.endpoint for r in rec.records if r.phase == "ping"] == ["target", "baseline"] * 3
    assert not any(r.phase == "probe_concurrent" for r in rec.records)  # no burst on standard
    assert any(f.id == "performance.relay_overhead" for f in result.findings)


async def test_max_tokens_rejection_switches_to_completion_tokens(knowledge_base):
    server = UniqueReplyServer()
    base = server.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and b'"max_tokens"' in request.content:
            return httpx.Response(
                400,
                json={"error": {"message": "Unsupported parameter: 'max_tokens'. "
                                           "Use 'max_completion_tokens' instead."}},
            )
        return base(request)

    server.handler = handler  # type: ignore[method-assign]
    result, rec = await _run_probe(server, n=3, suite="deep", knowledge_base=knowledge_base)
    assert [r.phase for r in rec.records].count("param_retry") == 1
    probe = [r for r in rec.records if r.phase == "probe"]
    assert len(probe) == 3 and all(r.ok for r in probe)
    assert result.evidence["performance_probe"]["max_completion_tokens"]["target"] is True
    assert summarize_endpoint(rec.records).errors == 0


async def test_disabled_probe_is_not_run(knowledge_base):
    result, rec = await _run_probe(MockServer(), n=0, knowledge_base=knowledge_base)
    assert result.status == Status.NOT_RUN and rec.records == []


def _probe_rec(seq: int, endpoint: str, tps: float) -> RequestRecord:
    return RequestRecord(
        seq=seq, endpoint=endpoint, phase="probe", ok=True, stream=True,
        duration_ms=1000.0, ttft_ms=200.0, decode_tps_local=tps, decode_tps_reported=tps,
    )


def test_throughput_mismatch_finding():
    recs = [_probe_rec(i, "target", 240.0) for i in range(6)]
    recs += [_probe_rec(10 + i, "baseline", 80.0) for i in range(6)]
    summaries = {ep: summarize_endpoint(recs, ep) for ep in ("target", "baseline")}
    result = DetectorResult(id="performance", name="p", dimension=Dimension.RELIABILITY)
    PerformanceDetector()._findings(result, recs, summaries, 6)
    mismatch = [f for f in result.findings if f.id == "performance.throughput_mismatch"]
    assert mismatch and mismatch[0].evidence["ratio"] == 3.0
    assert mismatch[0].severity.value == "low"  # evidence, never an accusation

    even = [_probe_rec(i, "target", 90.0) for i in range(6)]
    even += [_probe_rec(10 + i, "baseline", 80.0) for i in range(6)]
    summaries = {ep: summarize_endpoint(even, ep) for ep in ("target", "baseline")}
    result = DetectorResult(id="performance", name="p", dimension=Dimension.RELIABILITY)
    PerformanceDetector()._findings(result, even, summaries, 6)
    assert not any(f.id == "performance.throughput_mismatch" for f in result.findings)


@pytest.fixture
def patched_make_client(monkeypatch):
    server = UniqueReplyServer()
    from zing.clients import make_client as real

    monkeypatch.setattr(
        "zing.runner.make_client", lambda config, **_: real(config, transport=server.transport)
    )
    return server


async def test_compare_audit_on_standard_has_probe_and_comparison(patched_make_client):
    target = TargetConfig(name="t", kind="target", base_url=BASE_URL, model=DEFAULT_MODEL)
    baseline = TargetConfig(name="b", kind="baseline", base_url=BASE_URL, model=DEFAULT_MODEL)
    events: list[dict] = []
    report = await run_audit(
        target, AuditOptions(suite="standard"), baseline=baseline, mode="compare",
        on_event=events.append,
    )
    perf = report.performance
    assert perf is not None and perf.source == "probe" and perf.probe_requests == 5
    assert perf.baseline is not None and perf.baseline.source == "probe"
    assert perf.comparison and perf.probe_cost is not None
    start = next(e for e in events if e["type"] == "start")
    assert start["probe_requests"] == 5
    # informational only: the probe never scores
    det = next(d for d in report.detectors if d.id == "performance")
    assert det.score is None


async def test_non_streaming_probe(knowledge_base):
    server = UniqueReplyServer()
    result, rec = await _run_probe(server, n=4, streaming=False, knowledge_base=knowledge_base)
    assert all(b["stream"] is False for b in server.requests)
    probe = [r for r in rec.records if r.phase == "probe"]
    assert len(probe) == 4 and all(r.ttft_ms is None for r in probe)
    summary = next(f for f in result.findings if f.id == "performance.summary")
    assert summary.evidence["mode"] == "non_stream"
    assert "non-streaming" in summary.summary
    report = build_performance(rec.records)
    assert report is not None and report.mode == "non_stream" and report.modes == []
    assert report.target.e2e_tps_local.count == 4 and report.target.ttft_ms.count == 0


async def test_full_suite_measures_both_modes_interleaved(knowledge_base):
    server = UniqueReplyServer()
    result, rec = await _run_probe(server, n=3, suite="full", baseline=True,
                                   knowledge_base=knowledge_base)
    probe = [(r.stream, r.endpoint) for r in rec.records if r.phase == "probe"]
    assert probe[:4] == [(True, "target"), (True, "baseline"), (False, "target"), (False, "baseline")]
    assert sum(1 for s, _ in probe if s) == sum(1 for s, _ in probe if not s) == 6
    burst = [r.stream for r in rec.records if r.phase == "probe_concurrent"]
    assert burst.count(True) == burst.count(False) == 6  # min(n=3, ...) per side and mode
    assert result.evidence["performance_probe"]["modes"] == ["stream", "non_stream"]

    report = build_performance(rec.records, has_baseline=True)
    assert report is not None and report.mode == "stream" and report.probe_requests == 3
    assert [m.mode for m in report.modes] == ["non_stream"]
    ns = report.modes[0]
    assert ns.target.requests == 3 and ns.target.ttft_ms.count == 0
    assert ns.baseline is not None and ns.comparison
    assert report.target.ttft_ms.count == 3
    assert planned_probe_requests(AuditOptions(suite="full"), has_baseline=False) == 100
    assert estimated_calls(AuditOptions(suite="full"), has_baseline=False) == 3 + 1 + (100 + 12) * 2


def test_comparison_direction():
    from zing.models import PerformanceComparison

    lat = PerformanceComparison(metric="latency_p50", unit="ms", target=900, baseline=1000, delta=-100)
    assert lat.target_better is True
    tps = PerformanceComparison(metric="decode", unit="tok/s", target=40, baseline=80, delta=-40,
                                higher_is_better=True)
    assert tps.target_better is False
    even = PerformanceComparison(metric="latency_p50", unit="ms", target=1005, baseline=1000, delta=5)
    assert even.target_better is None
