"""Transparent scoring: published scales, dimension breakdowns, report details.

The protocol detector is the pilot of the pattern: each check scores points from
a published scale (``SCALE``), inconclusive checks are left out of the mean, and
the dimension records how its score and status were derived so the reports can
explain both — positive and negative findings alike.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from zing.detectors.protocol import SCALE, ProtocolDetector
from zing.detectors.scale import Scale, outcome
from zing.models import (
    AuditReport,
    CompletionOutcome,
    DetectorResult,
    Dimension,
    Finding,
    RedactedTarget,
    Severity,
    Status,
    Verdict,
)
from zing.report import compact_dict, render_html, render_markdown
from zing.scoring import build_dimensions

_BLUE = CompletionOutcome(ok=True, status_code=200, content="Your favorite color is blue.",
                          finish_reason="stop",
                          usage={"prompt_tokens": 9, "completion_tokens": 5, "total_tokens": 14})
_STOPPED = CompletionOutcome(ok=True, status_code=200, content="alpha ", finish_reason="stop")
_SHAPE = CompletionOutcome(ok=True, status_code=200, content="ok", finish_reason="stop",
                           usage={"prompt_tokens": 9, "completion_tokens": 1, "total_tokens": 10})
_REJECTED = CompletionOutcome(ok=False, status_code=400,
                              raw_error={"error": {"message": "messages is empty"}})
_TIMEOUT = CompletionOutcome(ok=False, error_type="timeout", error_message="Read timed out.")


async def _run(*outcomes: CompletionOutcome) -> DetectorResult:
    queue = list(outcomes)

    async def complete(_spec):
        return queue.pop(0)

    ctx = SimpleNamespace(client=SimpleNamespace(complete=complete))
    return await ProtocolDetector().run(ctx)  # type: ignore[arg-type]


def _finding(result: DetectorResult, fid: str) -> Finding:
    return next(f for f in result.findings if f.id == fid)


async def test_every_check_scores_from_the_published_scale():
    result = await _run(_BLUE, _STOPPED, _SHAPE, _REJECTED)
    assert result.score == 100.0 and result.status == Status.PASS
    assert result.scoring is not None and result.scoring.method == "mean_of_checks"
    assert len(result.scoring.outcomes) == len(SCALE.outcomes)
    for f in result.findings:
        o = SCALE.get(f.id, f.outcome or "")
        assert (f.score, f.status, f.severity) == (o.score, o.status, o.severity)
    assert [f.outcome for f in result.findings] == [
        "recalled", "truncated", "conformant", "rejected_openai_body",
    ]


async def test_inconclusive_checks_are_left_out_of_the_mean():
    # stop (no content) is not counted: (55 + 100 + 100) / 3, not / 4 with a 50
    forgotten = CompletionOutcome(ok=True, status_code=200, content="I don't know.")
    result = await _run(forgotten, _TIMEOUT, _SHAPE, _REJECTED)
    stop = _finding(result, "protocol.stop")
    assert stop.status == Status.INCONCLUSIVE and stop.outcome == "no_content"
    assert stop.score is None
    assert result.score == 85.0
    assert _finding(result, "protocol.multi_turn").score == 55.0


async def test_no_counted_check_means_no_score():
    result = await _run(_TIMEOUT, _TIMEOUT, _TIMEOUT, _REJECTED)
    assert result.score == 100.0  # error_schema still counts: a rejection is conclusive
    result = await _run(_TIMEOUT, _TIMEOUT, _TIMEOUT, _TIMEOUT)
    # a request that never got an HTTP response is still a (WARN) outcome
    assert _finding(result, "protocol.error_schema").outcome == "no_http_response"
    assert result.score == 55.0
    assert Scale.mean([f for f in result.findings if f.id != "protocol.error_schema"]) is None


def test_scale_rejects_duplicate_outcomes():
    with pytest.raises(ValueError):
        Scale(outcome("c", "a", 1.0, Status.PASS, label="x"), outcome("c", "a", 2.0, Status.PASS, label="y"))


def test_every_protocol_outcome_has_a_label():
    assert all(o.label for o in SCALE.outcomes)
    checks = {o.check for o in SCALE.outcomes}
    assert checks == {"protocol.multi_turn", "protocol.stop", "protocol.shape", "protocol.error_schema"}


def _det(id_: str, score: float | None, status: Status, *findings: Finding) -> DetectorResult:
    return DetectorResult(id=id_, name=id_.title(), dimension=Dimension.PROTOCOL,
                          score=score, status=status, findings=list(findings))


def test_dimension_breakdown_uses_equal_detector_weights():
    dims = build_dimensions(
        [_det("protocol", 80.0, Status.PASS), _det("determinism", 100.0, Status.PASS),
         _det("other", None, Status.INCONCLUSIVE)],
        None,
    )
    d = next(x for x in dims if x.dimension == Dimension.PROTOCOL)
    assert d.score == 90.0
    b = d.breakdown
    assert b is not None and b.method == "mean_of_detectors"
    assert [(c.detector, c.counted) for c in b.detectors] == [
        ("protocol", True), ("determinism", True), ("other", False),
    ]
    assert b.status_override is None and b.detector_status == Status.INCONCLUSIVE


def test_dimension_breakdown_explains_a_severity_override():
    medium = Finding(id="protocol.multi_turn", title="Multi-turn", status=Status.WARN,
                     severity=Severity.MEDIUM)
    dims = build_dimensions([_det("protocol", 88.8, Status.PASS, medium)], None)
    d = next(x for x in dims if x.dimension == Dimension.PROTOCOL)
    assert d.status == Status.WARN
    o = d.breakdown.status_override
    assert o is not None
    assert (o.from_status, o.to_status, o.severity) == (Status.PASS, Status.WARN, Severity.MEDIUM)
    assert o.findings == ["protocol.multi_turn"]
    # dimensions that did not run carry an empty breakdown
    assert next(x for x in dims if x.dimension == Dimension.BILLING).breakdown.detectors == []


async def _report() -> AuditReport:
    forgotten = CompletionOutcome(ok=True, status_code=200, content="I don't know.")
    protocol = await _run(forgotten, _TIMEOUT, _SHAPE, _REJECTED)
    legacy = _det("determinism", 100.0, Status.PASS,
                  Finding(id="determinism.temp1_variability", title="Output varies at temperature=1.0",
                          status=Status.PASS))
    detectors = [protocol, legacy]
    return AuditReport(
        tool_version="test", mode="check", suite="standard",
        target=RedactedTarget(name="t", kind="target", base_url="http://relay.test/v1", model="gpt-4o"),
        verdict=Verdict(), dimensions=build_dimensions(detectors, None), detectors=detectors,
    )


async def test_markdown_explains_scores_status_and_scale():
    md = render_markdown(await _report())
    details = md[md.index("## Dimension details"):md.index("## Findings")]
    assert "### ⚠️ protocol — 92.5 (warn)" in details
    assert "Mean of 2 detectors, equal weight: OpenAI-compatibility conformance 85, Determinism 100 → 92.5." in details
    assert "- Status warn: the worst status its detectors concluded." in details
    # every check with its outcome and points, positive and negative
    assert "| ⚠️ | Multi-turn conversation memory | The color from an earlier turn was not recalled. | 55 |" in details
    assert "| ✅ | Error response schema | Rejected with a 4xx and an OpenAI-style error body. | 100 |" in details
    assert "| not counted |" in details
    # the full scale, including outcomes that did not happen
    assert "  - 30: The invalid request was accepted (2xx)." in details
    # a detector without a scale still lists its findings
    assert "- ✅ Output varies at temperature=1.0" in details
    # dimensions that did not run are skipped
    assert "### ➖ billing" not in details


async def test_html_has_expandable_dimension_details():
    page = render_html(await _report())
    assert page.count('<details class="dim">') == 1
    assert "Scoring scale" in page and "not counted" in page
    assert "The invalid request was accepted (2xx)." in page


async def test_compact_carries_points():
    compact = compact_dict(await _report())
    points = {f["id"]: f.get("points") for f in compact["findings"]}
    assert points["protocol.multi_turn"] == 55.0 and points["protocol.stop"] is None


def test_markdown_explains_a_status_override():
    medium = Finding(id="protocol.multi_turn", title="Multi-turn", status=Status.WARN,
                     severity=Severity.MEDIUM)
    detectors = [_det("protocol", 88.8, Status.PASS, medium)]
    report = AuditReport(
        tool_version="test", mode="check", suite="standard",
        target=RedactedTarget(name="t", kind="target", base_url="u", model="m"),
        verdict=Verdict(), dimensions=build_dimensions(detectors, None), detectors=detectors,
    )
    md = render_markdown(report)
    assert "Score of one detector: Protocol 88.8." in md
    assert "Status warn: raised from pass by 1 medium-severity finding (protocol.multi\\_turn)" in md


def test_reports_without_breakdown_still_render():
    report = AuditReport.model_validate({
        "tool_version": "old", "mode": "check", "suite": "standard",
        "target": {"name": "t", "kind": "target", "base_url": "u", "model": "m"},
        "verdict": {},
        "dimensions": [{"dimension": "protocol", "score": 70.0, "weight": 8.0, "status": "warn"}],
        "detectors": [{"id": "protocol", "name": "P", "dimension": "protocol", "score": 70.0,
                       "status": "warn", "findings": [{"id": "protocol.stop", "title": "Stop",
                                                       "status": "warn"}]}],
    })
    md = render_markdown(report)
    assert "Score of one detector: P 70." in md and "- ⚠️ Stop" in md
