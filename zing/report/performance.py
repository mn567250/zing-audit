"""The performance section of the Markdown, HTML and compact reports.

Pure functions of :class:`~zing.models.PerformanceReport`. The HTML view draws
its charts as inline SVG (no scripts, no external assets) so the report stays a
single self-contained file: one timeline per metric, switched with CSS-only
tabs, with a native tooltip on every point.
"""

from __future__ import annotations

import html
import math
from collections.abc import Callable

from zing.models import (
    EndpointPerformance,
    PerformanceReport,
    PerfStats,
    RequestRecord,
)

# (label, unit, getter) — the stat table rows, in reading order.
STAT_ROWS: tuple[tuple[str, str, Callable[[EndpointPerformance], PerfStats]], ...] = (
    ("Latency", "ms", lambda e: e.latency_ms),
    ("Time to first token", "ms", lambda e: e.ttft_ms),
    ("Decode speed (usage)", "tok/s", lambda e: e.decode_tps_reported),
    ("Decode speed (local count)", "tok/s", lambda e: e.decode_tps_local),
    ("End-to-end speed (usage)", "tok/s", lambda e: e.e2e_tps_reported),
    ("End-to-end speed (local count)", "tok/s", lambda e: e.e2e_tps_local),
    ("Inter-chunk latency", "ms", lambda e: e.itl_ms),
    ("Inter-chunk jitter", "ms", lambda e: e.itl_jitter_ms),
    ("Server time (sent → first output)", "ms", lambda e: e.server_ms),
    ("Relay-reported processing", "ms", lambda e: e.relay_processing_ms),
    ("Network round trip (GET /models)", "ms", lambda e: e.network_rtt_ms),
    ("TCP connect", "ms", lambda e: e.connect_ms),
    ("TLS handshake", "ms", lambda e: e.tls_ms),
)
STAT_COLUMNS = ("count", "min", "mean", "p50", "p75", "p90", "p95", "p99", "max", "stdev")

COMPARE_LABELS = {
    "latency_p50": "Latency p50",
    "latency_p90": "Latency p90",
    "ttft_p50": "TTFT p50",
    "ttft_p90": "TTFT p90",
    "decode_tps_reported_p50": "Decode speed p50 (usage)",
    "decode_tps_local_p50": "Decode speed p50 (local)",
    "e2e_tps_local_p50": "End-to-end speed p50 (local)",
    "itl_p50": "Inter-chunk latency p50",
    "server_p50": "Server time p50",
    "network_rtt_p50": "Network round trip p50",
    "error_rate": "Error rate",
}


def _tps(r: RequestRecord) -> float | None:
    return r.decode_tps_local if r.decode_tps_local is not None else r.decode_tps_reported


# (id, label, unit, getter) — the chart metrics.
CHART_METRICS: tuple[tuple[str, str, str, Callable[[RequestRecord], float | None]], ...] = (
    ("latency", "Latency", "ms", lambda r: r.duration_ms),
    ("ttft", "TTFT", "ms", lambda r: r.ttft_ms),
    ("tps", "Decode speed", "tok/s", _tps),
    ("itl", "Inter-chunk latency", "ms", lambda r: r.itl_mean_ms),
)


def fmt_num(value: float | int | None, unit: str = "") -> str:
    if value is None:
        return "—"
    if unit == "ratio":
        return f"{value * 100:.1f}%"
    if isinstance(value, int) or value == 0 or abs(value) >= 100:
        text = f"{value:,.0f}"
    elif abs(value) >= 10:
        text = f"{value:.1f}"
    else:
        text = f"{value:.2f}"
    return text


def _signed(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "ratio":
        return f"{value * 100:+.1f} pp"
    return ("+" if value > 0 else "") + fmt_num(value)


def _source_line(perf: PerformanceReport) -> str:
    if perf.source == "probe":
        return (
            f"Source: dedicated probe — {perf.probe_requests} uncacheable streaming "
            f"requests per endpoint, {perf.probe_max_tokens or '?'} output tokens each."
        )
    return "Source: the audit's own requests (no dedicated probe in this suite)."


def _endpoints(perf: PerformanceReport) -> list[EndpointPerformance]:
    return [e for e in (perf.target, perf.baseline) if e is not None]


def _visible_rows(perf: PerformanceReport):
    """Stat rows with data for at least one endpoint."""
    eps = _endpoints(perf)
    return [row for row in STAT_ROWS if any(row[2](e).count for e in eps)]


def _reliability_line(e: EndpointPerformance) -> str:
    return (
        f"{e.successes}/{e.requests} succeeded · errors {fmt_num(e.error_rate, 'ratio')} · "
        f"timeouts {fmt_num(e.timeout_rate, 'ratio')} · 429 {fmt_num(e.rate_limited_rate, 'ratio')}"
        + (f" · {e.cached_excluded} cached (excluded)" if e.cached_excluded else "")
    )


def _extras(e: EndpointPerformance) -> list[str]:
    out: list[str] = []
    if e.cold_start_ms is not None:
        out.append(
            f"Cold start (first request): {fmt_num(e.cold_start_ms)} ms"
            + (f", TTFT {fmt_num(e.cold_start_ttft_ms)} ms" if e.cold_start_ttft_ms else "")
        )
    c = e.concurrency
    if c is not None:
        out.append(
            f"Under load ({c.requests} requests at concurrency {c.concurrency}): "
            f"{c.successes} succeeded, aggregate {fmt_num(c.aggregate_tps_local)} tok/s "
            f"(local) / {fmt_num(c.aggregate_tps_reported)} tok/s (usage), "
            f"latency p50 {fmt_num(c.latency_ms.p50)} ms"
        )
    return out


# --------------------------------------------------------------------------- #
# compact JSON
# --------------------------------------------------------------------------- #
def compact_performance(perf: PerformanceReport | None) -> dict | None:
    """Headline numbers for the agent-facing compact report."""
    if perf is None:
        return None

    def r(value: float | None, digits: int = 1) -> float | None:
        return round(value, digits) if value is not None else None

    def ep(e: EndpointPerformance) -> dict:
        tps = e.decode_tps_local.p50
        return {
            "requests": e.requests,
            "error_rate": r(e.error_rate, 4),
            "latency_p50_ms": r(e.latency_ms.p50),
            "latency_p95_ms": r(e.latency_ms.p95),
            "ttft_p50_ms": r(e.ttft_ms.p50),
            "decode_tps_p50": r(tps if tps is not None else e.decode_tps_reported.p50),
            "network_rtt_p50_ms": r(e.network_rtt_ms.p50),
        }

    out: dict = {"source": perf.source, "target": ep(perf.target)}
    if perf.baseline is not None:
        out["baseline"] = ep(perf.baseline)
        out["comparison"] = {
            c.metric: {"delta": r(c.delta, 4), "ratio": r(c.ratio, 3)} for c in perf.comparison
        }
    return out


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def markdown_section(perf: PerformanceReport | None) -> list[str]:
    if perf is None:
        return []
    lines = ["## Performance", "", f"_{_source_line(perf)} Informational — not scored._", ""]
    eps = _endpoints(perf)
    for e in eps:
        if len(eps) > 1:
            lines += [f"### {e.endpoint.capitalize()}", ""]
        lines.append(f"- Requests: {_reliability_line(e)}")
        lines += [f"- {x}" for x in _extras(e)]
        lines.append("")
        rows = [r for r in _visible_rows(perf) if r[2](e).count]
        if rows:
            lines.append("| Metric | " + " | ".join(STAT_COLUMNS) + " |")
            lines.append("| --- | " + " | ".join("---:" for _ in STAT_COLUMNS) + " |")
            for label, unit, get in rows:
                s = get(e)
                cells = [str(s.count)] + [fmt_num(getattr(s, c)) for c in STAT_COLUMNS[1:]]
                lines.append(f"| {label} ({unit}) | " + " | ".join(cells) + " |")
            lines.append("")
        if e.ttft_by_input:
            lines.append("| Prompt size | Requests | TTFT p50 (ms) | Latency p50 (ms) |")
            lines.append("| --- | ---: | ---: | ---: |")
            for b in e.ttft_by_input:
                lines.append(
                    f"| {b.label} | {b.count} | {fmt_num(b.ttft_p50_ms)} | {fmt_num(b.latency_p50_ms)} |"
                )
            lines.append("")
    if perf.comparison:
        lines += ["### Target vs baseline", ""]
        lines.append("| Metric | Target | Baseline | Δ | Ratio |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for c in perf.comparison:
            lines.append(
                f"| {COMPARE_LABELS.get(c.metric, c.metric)} ({c.unit}) | "
                f"{fmt_num(c.target, c.unit)} | {fmt_num(c.baseline, c.unit)} | "
                f"{_signed(c.delta, c.unit)} | "
                f"{'—' if c.ratio is None else f'{c.ratio:.2f}x'} |"
            )
        lines.append("")
    if perf.probe_cost is not None:
        pc = perf.probe_cost
        lines.append(
            f"Probe cost: {pc.requests} requests, {pc.input_tokens_reported:,} input + "
            f"{pc.output_tokens_reported:,} output tokens (usage); "
            f"{pc.input_tokens_local:,} + {pc.output_tokens_local:,} (local count)."
        )
        lines.append("")
    for note in perf.notes:
        lines.append(f"- {note}")
    if perf.notes:
        lines.append("")
    return lines


# --------------------------------------------------------------------------- #
# HTML + SVG
# --------------------------------------------------------------------------- #
def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def nice_ceiling(value: float) -> float:
    """Round up to 1, 2, 2.5 or 5 x 10^n so the axis ticks are clean numbers."""
    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    base = 10**exp
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * base:
            return step * base
    return 10 * base


_W, _H = 860, 260
_ML, _MR, _MT, _MB = 56, 16, 12, 34


def timeline_svg(
    records: list[RequestRecord],
    metric: tuple[str, str, str, Callable[[RequestRecord], float | None]],
) -> str:
    """Scatter of ``metric`` per request over the audit's timeline."""
    _, label, unit, get = metric
    calls = [r for r in records if r.op == "complete"]
    plotted: list[tuple[RequestRecord, float]] = []
    for r in calls:
        value = get(r)
        if r.ok and value is not None:
            plotted.append((r, value))
    failed = [r for r in calls if not r.ok]
    if not plotted:
        return f'<p class="muted">No {_esc(label)} samples.</p>'

    end_s = max((r.start_ms + (r.duration_ms or 0)) / 1000 for r in calls) or 1.0
    x_max = nice_ceiling(end_s)
    y_max = nice_ceiling(max(v for _, v in plotted) * 1.05)
    pw, ph = _W - _ML - _MR, _H - _MT - _MB

    def x(sec: float) -> float:
        return _ML + sec / x_max * pw

    def y(val: float) -> float:
        return _MT + ph - val / y_max * ph

    out = [
        f'<svg class="perf-chart" viewBox="0 0 {_W} {_H}" role="img" '
        f'aria-label="{_esc(label)} per request over the audit">'
    ]
    for i in range(5):
        v = y_max * i / 4
        yy = y(v)
        out.append(f'<line class="grid" x1="{_ML}" x2="{_W - _MR}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        out.append(
            f'<text class="tick" x="{_ML - 6}" y="{yy + 4:.1f}" text-anchor="end">{fmt_num(v)}</text>'
        )
    for i in range(5):
        s = x_max * i / 4
        anchor = "start" if i == 0 else "end" if i == 4 else "middle"
        out.append(
            f'<text class="tick" x="{x(s):.1f}" y="{_H - _MB + 16}" text-anchor="{anchor}">{fmt_num(s)}s</text>'
        )
    out.append(
        f'<text class="tick" x="{_ML}" y="{_H - 2}">seconds since audit start · {_esc(unit)}</text>'
    )
    for r, v in plotted:
        cls = f"pt {r.endpoint}" + (" passive" if r.phase == "passive" else "") + (
            " cached" if r.cached else ""
        )
        tip = (
            f"#{r.seq} {r.endpoint} · {r.detector or '—'} · {r.phase}"
            f"{' · cached (excluded)' if r.cached else ''}\n{label}: {fmt_num(v)} {unit}"
        )
        out.append(
            f'<circle class="{cls}" cx="{x(r.start_ms / 1000):.1f}" cy="{y(v):.1f}" r="4">'
            f"<title>{_esc(tip)}</title></circle>"
        )
    base_y = _MT + ph
    for r in failed:
        cx = x(r.start_ms / 1000)
        tip = f"#{r.seq} {r.endpoint} · {r.detector or '—'} · failed ({r.status_code or r.error_type})"
        out.append(
            f'<path class="fail-mark" d="M{cx - 4:.1f},{base_y - 4:.1f}l8,8m0,-8l-8,8">'
            f"<title>{_esc(tip)}</title></path>"
        )
    out.append("</svg>")
    return "".join(out)


def _legend(has_baseline: bool, has_passive: bool, has_failed: bool) -> str:
    items = ['<span><i class="key target"></i>target</span>']
    if has_baseline:
        items.append('<span><i class="key baseline"></i>baseline</span>')
    if has_passive:
        items.append('<span><i class="key target passive"></i>audit request (lighter)</span>')
    if has_failed:
        items.append('<span><i class="key fail">×</i>failed request</span>')
    return f'<div class="perf-legend">{"".join(items)}</div>'


def _stat_table(perf: PerformanceReport, e: EndpointPerformance) -> str:
    rows = [r for r in _visible_rows(perf) if r[2](e).count]
    if not rows:
        return '<p class="muted">No successful requests to summarize.</p>'
    out = ['<div class="scroll"><table class="perf"><thead><tr><th>Metric</th>']
    out += [f'<th class="num">{c}</th>' for c in STAT_COLUMNS]
    out.append("</tr></thead><tbody>")
    for label, unit, get in rows:
        s = get(e)
        out.append(f"<tr><td>{_esc(label)} <span class=\"muted\">{_esc(unit)}</span></td>")
        out.append(f'<td class="num">{s.count}</td>')
        out += [f'<td class="num">{fmt_num(getattr(s, c))}</td>' for c in STAT_COLUMNS[1:]]
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def html_section(perf: PerformanceReport | None) -> str:
    if perf is None:
        return ""
    out = ['<section class="card perf-card"><h2>Performance</h2>']
    out.append(f'<p class="muted">{_esc(_source_line(perf))} Informational — not scored.</p>')

    records = perf.requests
    charts = [(m, timeline_svg(records, m)) for m in CHART_METRICS]
    charts = [(m, svg) for m, svg in charts if not svg.startswith("<p")]
    if charts:
        out.append('<div class="perf-tabs">')
        for i, (m, _svg) in enumerate(charts):
            mid = m[0]
            checked = " checked" if i == 0 else ""
            out.append(
                f'<input type="radio" name="perf-metric" id="perf-{mid}"{checked}>'
                f'<label for="perf-{mid}">{_esc(m[1])}</label>'
            )
        for m, svg in charts:
            out.append(f'<div class="perf-panel" id="panel-{m[0]}">{svg}</div>')
        out.append("</div>")
        calls = [r for r in records if r.op == "complete"]
        out.append(
            _legend(
                perf.baseline is not None,
                any(r.phase == "passive" for r in calls) and perf.source == "probe",
                any(not r.ok for r in calls),
            )
        )

    eps = _endpoints(perf)
    for e in eps:
        if len(eps) > 1:
            out.append(f"<h3>{_esc(e.endpoint.capitalize())}</h3>")
        out.append(f'<p class="meta">{_esc(_reliability_line(e))}</p>')
        extras = _extras(e)
        if extras:
            out.append("<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in extras) + "</ul>")
        out.append(_stat_table(perf, e))
        if e.ttft_by_input:
            out.append(
                '<table class="perf small"><thead><tr><th>Prompt size</th>'
                '<th class="num">Requests</th><th class="num">TTFT p50 ms</th>'
                '<th class="num">Latency p50 ms</th></tr></thead><tbody>'
            )
            for b in e.ttft_by_input:
                out.append(
                    f"<tr><td>{_esc(b.label)}</td><td class=\"num\">{b.count}</td>"
                    f'<td class="num">{fmt_num(b.ttft_p50_ms)}</td>'
                    f'<td class="num">{fmt_num(b.latency_p50_ms)}</td></tr>'
                )
            out.append("</tbody></table>")

    if perf.comparison:
        out.append(
            '<h3>Target vs baseline</h3><table class="perf"><thead><tr><th>Metric</th>'
            '<th class="num">Target</th><th class="num">Baseline</th>'
            '<th class="num">Δ</th><th class="num">Ratio</th></tr></thead><tbody>'
        )
        for c in perf.comparison:
            ratio = "—" if c.ratio is None else f"{c.ratio:.2f}x"
            out.append(
                f"<tr><td>{_esc(COMPARE_LABELS.get(c.metric, c.metric))} "
                f'<span class="muted">{_esc(c.unit)}</span></td>'
                f'<td class="num">{fmt_num(c.target, c.unit)}</td>'
                f'<td class="num">{fmt_num(c.baseline, c.unit)}</td>'
                f'<td class="num">{_signed(c.delta, c.unit)}</td>'
                f'<td class="num">{ratio}</td></tr>'
            )
        out.append("</tbody></table>")

    if perf.probe_cost is not None:
        pc = perf.probe_cost
        out.append(
            f'<p class="meta">Probe cost: {pc.requests} requests, '
            f"{pc.input_tokens_reported:,} input + {pc.output_tokens_reported:,} output tokens "
            f"(usage); {pc.input_tokens_local:,} + {pc.output_tokens_local:,} (local count).</p>"
        )
    if perf.notes:
        out.append("<ul class=\"perf-notes\">" + "".join(f"<li>{_esc(n)}</li>" for n in perf.notes) + "</ul>")
    out.append("</section>")
    return "".join(out)


PERF_CSS = """
.perf-card { --series-target: #2a78d6; --series-baseline: #eb6834; --status-critical: #d03b3b;
  --chart-surface: #ffffff; --grid: #eaeef2; }
.perf-tabs { display: flex; flex-wrap: wrap; gap: .25rem .5rem; margin: .5rem 0; }
.perf-tabs input { position: absolute; opacity: 0; pointer-events: none; }
.perf-tabs label { font-size: .85rem; padding: .2rem .7rem; border: 1px solid #d0d7de;
  border-radius: 999px; cursor: pointer; color: #57606a; }
.perf-tabs input:checked + label { background: #1f2328; border-color: #1f2328; color: #fff; }
.perf-tabs input:focus-visible + label { outline: 2px solid #0969da; outline-offset: 2px; }
.perf-panel { display: none; width: 100%; order: 99; }
#perf-latency:checked ~ #panel-latency, #perf-ttft:checked ~ #panel-ttft,
#perf-tps:checked ~ #panel-tps, #perf-itl:checked ~ #panel-itl { display: block; }
.perf-chart { width: 100%; height: auto; display: block; }
.perf-chart .grid { stroke: var(--grid); stroke-width: 1; }
.perf-chart .tick { fill: #57606a; font-size: 11px; font-variant-numeric: tabular-nums; }
.perf-chart .pt { stroke: var(--chart-surface); stroke-width: 2; }
.perf-chart .pt.target { fill: var(--series-target); }
.perf-chart .pt.baseline { fill: var(--series-baseline); }
.perf-chart .pt.passive { fill-opacity: .45; }
.perf-chart .pt.cached { fill: #8c959f; fill-opacity: .6; }
.perf-chart .fail-mark { stroke: var(--status-critical); stroke-width: 2; stroke-linecap: round; }
.perf-legend { display: flex; flex-wrap: wrap; gap: 1rem; font-size: .8rem; color: #57606a;
  margin: .25rem 0 .75rem; }
.perf-legend .key { display: inline-block; width: 10px; height: 10px; border-radius: 50%;
  margin-right: .35rem; vertical-align: -1px; font-style: normal; }
.perf-legend .key.target { background: var(--series-target); }
.perf-legend .key.baseline { background: var(--series-baseline); }
.perf-legend .key.passive { opacity: .45; }
.perf-legend .key.fail { color: var(--status-critical); width: auto; height: auto;
  font-weight: 700; border-radius: 0; }
.scroll { overflow-x: auto; }
table.perf { font-size: .82rem; margin: .5rem 0 1rem; }
table.perf td, table.perf th { padding: .3rem .45rem; white-space: nowrap; }
table.perf.small { width: auto; }
.perf-notes { font-size: .85rem; color: #57606a; }
@media (prefers-color-scheme: dark) {
  .perf-card { --series-target: #3987e5; --series-baseline: #d95926; --chart-surface: #161b22;
    --grid: #21262d; }
  .perf-chart .tick, .perf-legend, .perf-notes { fill: #8b949e; color: #8b949e; }
  .perf-tabs label { border-color: #30363d; color: #8b949e; }
  .perf-tabs input:checked + label { background: #e6edf3; border-color: #e6edf3; color: #0d1117; }
}
"""
