"""Per-dimension details for the Markdown and HTML reports.

For every dimension that ran, this explains how its score and status came about
and lists every check behind it, passed and failed alike:

* the score — the equal-weight mean of the dimension's detector scores, with
  each detector's score and whether it was counted;
* the status — the worst status the detectors concluded, and, when a finding's
  severity overrode it, which findings did;
* per detector — each check's outcome and the points it scored. A detector that
  publishes a scoring scale (``DetectorResult.scoring``) also gets the full
  scale, i.e. every outcome each check could have had and its points.

Detectors without a scale still show all their findings, so every dimension is
covered and a detector gains the points/scale view by adopting
:class:`zing.detectors.scale.Scale` — nothing here has to change.
"""

from __future__ import annotations

import html

from zing.models import (
    AuditReport,
    DetectorResult,
    DimensionScore,
    Finding,
    ScoringOutcome,
    Status,
)

_STATUS_EMOJI: dict[Status, str] = {
    Status.PASS: "✅",
    Status.WARN: "⚠️",
    Status.FAIL: "❌",
    Status.INCONCLUSIVE: "❔",
    Status.NOT_RUN: "➖",
    Status.INFO: "ℹ️",
    Status.ERROR: "💥",
}
_STATUS_CLASS: dict[Status, str] = {
    Status.PASS: "pass",
    Status.WARN: "warn",
    Status.FAIL: "fail",
    Status.INCONCLUSIVE: "muted",
    Status.NOT_RUN: "muted",
    Status.INFO: "info",
    Status.ERROR: "fail",
}
_POSITIVE = (Status.PASS, Status.INFO)
_NOT_COUNTED = "not counted"


def _num(score: float | None) -> str:
    return "—" if score is None else f"{score:g}"


def _members(report: AuditReport, d: DimensionScore) -> list[DetectorResult]:
    return [det for det in report.detectors if det.dimension == d.dimension]


def score_explanation(d: DimensionScore, members: list[DetectorResult]) -> str:
    """One line: how the dimension score was computed."""
    names = {det.id: det.name for det in members}
    if d.breakdown is not None:
        parts = [(c.detector, c.score, c.counted) for c in d.breakdown.detectors]
    else:  # reports from before the breakdown existed
        parts = [(det.id, det.score, det.score is not None) for det in members]
    counted = [(i, s) for i, s, ok in parts if ok]
    skipped = [i for i, _, ok in parts if not ok]
    if not counted:
        line = "No detector produced a numeric score."
    elif len(counted) == 1:
        i, s = counted[0]
        line = f"Score of one detector: {names.get(i, i)} {_num(s)}."
    else:
        terms = ", ".join(f"{names.get(i, i)} {_num(s)}" for i, s in counted)
        line = f"Mean of {len(counted)} detectors, equal weight: {terms} → {_num(d.score)}."
    if skipped:
        line += " Not counted (no numeric score): " + ", ".join(names.get(i, i) for i in skipped) + "."
    return line


def status_explanation(d: DimensionScore) -> str:
    """One line: where the dimension status came from."""
    b = d.breakdown
    if b is None:
        return f"Status {d.status.value}."
    o = b.status_override
    if o is None:
        return f"Status {d.status.value}: the worst status its detectors concluded."
    n = len(o.findings)
    return (
        f"Status {o.to_status.value}: raised from {o.from_status.value} by "
        f"{n} {o.severity.value}-severity finding{'s' if n != 1 else ''} "
        f"({', '.join(o.findings)}); a serious finding always pulls a dimension down, "
        "whatever the score."
    )


def _labels(det: DetectorResult) -> dict[tuple[str, str], ScoringOutcome]:
    return {(o.check, o.outcome): o for o in (det.scoring.outcomes if det.scoring else [])}


def _check_titles(det: DetectorResult) -> dict[str, str]:
    titles: dict[str, str] = {}
    for f in det.findings:
        titles.setdefault(f.id, f.title)
    return titles


def _scale_by_check(det: DetectorResult) -> list[tuple[str, list[ScoringOutcome]]]:
    groups: dict[str, list[ScoringOutcome]] = {}
    for o in det.scoring.outcomes if det.scoring else []:
        groups.setdefault(o.check, []).append(o)
    return list(groups.items())


def _points(f: Finding) -> str:
    return _NOT_COUNTED if f.score is None else _num(f.score)


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def markdown_section(report: AuditReport, md) -> list[str]:
    """The "Dimension details" section; ``md`` escapes untrusted inline text."""
    dims = [d for d in report.dimensions if _members(report, d)]
    if not dims:
        return []
    lines = ["## Dimension details", ""]
    for d in dims:
        members = _members(report, d)
        emoji = _STATUS_EMOJI.get(d.status, "")
        lines.append(f"### {emoji} {d.dimension.value} — {_num(d.score)} ({d.status.value})")
        lines.append("")
        lines.append(f"- {md(score_explanation(d, members))}")
        lines.append(f"- {md(status_explanation(d))}")
        lines.append("")
        for det in members:
            lines.extend(_markdown_detector(det, md))
    return lines


def _markdown_detector(det: DetectorResult, md) -> list[str]:
    lines = [f"**{md(det.name)}** (`{det.id}`) — score {_num(det.score)}, {det.status.value}", ""]
    if det.error:
        lines += [f"> Detector error: {md(det.error)}", ""]
    if not det.findings:
        return lines + ["_No findings._", ""]
    labels = _labels(det)
    if det.scoring is not None:
        lines.append("| | Check | Outcome | Points |")
        lines.append("| --- | --- | --- | ---: |")
        for f in det.findings:
            o = labels.get((f.id, f.outcome or ""))
            outcome = o.label if o and o.label else f.summary
            lines.append(
                f"| {_STATUS_EMOJI.get(f.status, '')} | {md(f.title)} | {md(outcome)} | {_points(f)} |"
            )
        lines.append("")
        if det.scoring.method == "mean_of_checks":
            lines.append("_Detector score: mean of the counted checks' points._")
            lines.append("")
        titles = _check_titles(det)
        lines.append("<details><summary>Scoring scale</summary>")
        lines.append("")
        for check, outcomes in _scale_by_check(det):
            lines.append(f"- {md(titles.get(check, check))} (`{check}`)")
            for o in outcomes:
                lines.append(f"  - {_num(o.score) if o.score is not None else _NOT_COUNTED}: {md(o.label)}")
        lines.append("")
        lines.append("</details>")
        lines.append("")
        return lines
    passed = [f for f in det.findings if f.status in _POSITIVE]
    other = [f for f in det.findings if f.status not in _POSITIVE]
    for heading, group in (("Passed", passed), ("Issues and open points", other)):
        if not group:
            continue
        lines.append(f"_{heading}_")
        lines.append("")
        for f in group:
            lines.append(f"- {_STATUS_EMOJI.get(f.status, '')} {md(f.title)}")
        lines.append("")
    return lines


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _pill(status: Status) -> str:
    return f'<span class="pill {_STATUS_CLASS.get(status, "muted")}">{_esc(status.value)}</span>'


def html_section(report: AuditReport) -> str:
    dims = [d for d in report.dimensions if _members(report, d)]
    if not dims:
        return ""
    out = ['<section class="card"><h2>Dimension details</h2>']
    for d in dims:
        members = _members(report, d)
        out.append('<details class="dim">')
        out.append(
            f"<summary>{_pill(d.status)} <strong>{_esc(d.dimension.value)}</strong> "
            f'<span class="tag">score {_esc(_num(d.score))}</span></summary>'
        )
        out.append(f'<p class="muted">{_esc(score_explanation(d, members))}</p>')
        out.append(f'<p class="muted">{_esc(status_explanation(d))}</p>')
        for det in members:
            out.append(_html_detector(det))
        out.append("</details>")
    out.append("</section>")
    return "".join(out)


def _html_detector(det: DetectorResult) -> str:
    out = [
        '<div class="dim-det"><h3 class="det-title">'
        f"{_esc(det.name)} {_pill(det.status)} "
        f'<span class="tag">{_esc(det.id)}</span> '
        f'<span class="tag">score {_esc(_num(det.score))}</span></h3>'
    ]
    if det.error:
        out.append(f'<p class="fail">Detector error: {_esc(det.error)}</p>')
    if not det.findings:
        out.append('<p class="muted">No findings.</p></div>')
        return "".join(out)
    labels = _labels(det)
    if det.scoring is not None:
        out.append(
            '<table><thead><tr><th></th><th>Check</th><th>Outcome</th>'
            '<th class="num">Points</th></tr></thead><tbody>'
        )
        for f in det.findings:
            o = labels.get((f.id, f.outcome or ""))
            outcome = o.label if o and o.label else f.summary
            out.append(
                f"<tr><td>{_pill(f.status)}</td><td>{_esc(f.title)}</td>"
                f'<td>{_esc(outcome)}</td><td class="num">{_esc(_points(f))}</td></tr>'
            )
        out.append("</tbody></table>")
        if det.scoring.method == "mean_of_checks":
            out.append('<p class="muted">Detector score: mean of the counted checks\' points.</p>')
        titles = _check_titles(det)
        out.append('<details class="scale"><summary>Scoring scale</summary><ul>')
        for check, outcomes in _scale_by_check(det):
            out.append(f"<li>{_esc(titles.get(check, check))} <code>{_esc(check)}</code><ul>")
            for o in outcomes:
                pts = _num(o.score) if o.score is not None else _NOT_COUNTED
                out.append(f"<li><strong>{_esc(pts)}</strong> — {_esc(o.label)}</li>")
            out.append("</ul></li>")
        out.append("</ul></details></div>")
        return "".join(out)
    out.append('<ul class="checks">')
    for f in sorted(det.findings, key=lambda f: f.status not in _POSITIVE):
        out.append(f"<li>{_pill(f.status)} {_esc(f.title)}</li>")
    out.append("</ul></div>")
    return "".join(out)


DIM_CSS = """
details.dim { border-top: 1px solid #eaeef2; padding: .5rem 0; }
details.dim:first-of-type { border-top: 0; }
details.dim > summary { cursor: pointer; }
.dim-det { margin: .5rem 0 .75rem 1rem; }
details.scale { margin: .35rem 0; font-size: .88rem; }
details.scale > summary { cursor: pointer; color: #57606a; }
ul.checks { list-style: none; padding-left: 0; margin: .35rem 0; }
ul.checks li { margin: .2rem 0; }
@media (prefers-color-scheme: dark) {
  details.dim { border-color: #21262d; }
  details.scale > summary { color: #8b949e; }
}
"""
