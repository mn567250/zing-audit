/* zing web UI — the performance panel (live during an audit, and in reports).
 *
 * Plain browser global, no modules; load after /lang.js. Exposes
 * window.ZingPerf with:
 *   - Live(host)              live panel fed by the audit stream:
 *                               .reset({probeTotal, hasBaseline})
 *                               .add(records)   RequestRecord dicts (numbers only)
 *                               .render()       re-draw (e.g. after a language switch)
 *   - section(performance)    HTML for a report's `performance` block ("" if none)
 *   - wireSection(root, perf) hook up its metric tabs + tooltips inside `root`
 *   - chart(records, metric)  the timeline SVG (x = seconds since audit start)
 *
 * Colors follow the categorical order validated for the reports: target is
 * slot 1 (blue), baseline slot 2 (orange); a failed request is a red cross
 * with its own legend entry, so identity is never carried by color alone.
 */
(function () {
  "use strict";

  var T = function (zh, en) {
    return window.ZING_LANG ? window.ZING_LANG.t(zh, en) : en;
  };
  // Backend notes are fixed English sentences with translations in every
  // language, CN included (exportText translates in CN too; server() doesn't).
  var note = function (s) {
    return window.ZING_LANG ? window.ZING_LANG.exportText(s) : s;
  };
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function num(v, unit) {
    if (v == null || isNaN(v)) return "—";
    if (unit === "ratio") return (v * 100).toFixed(1) + "%";
    var a = Math.abs(v);
    var loc = window.ZING_LANG && window.ZING_LANG.locale ? window.ZING_LANG.locale() : undefined;
    if (v === 0 || a >= 100) return Math.round(v).toLocaleString(loc);
    return a >= 10 ? v.toFixed(1) : v.toFixed(2);
  }

  var METRICS = [
    { id: "latency", zh: "延迟", en: "Latency", unit: "ms", get: function (r) { return r.duration_ms; } },
    { id: "ttft", zh: "首 token 时间", en: "TTFT", unit: "ms", get: function (r) { return r.ttft_ms; } },
    {
      id: "tps", zh: "解码速度", en: "Decode speed", unit: "tok/s",
      get: function (r) { return r.decode_tps_local != null ? r.decode_tps_local : r.decode_tps_reported; },
    },
    { id: "itl", zh: "块间延迟", en: "Inter-chunk latency", unit: "ms", get: function (r) { return r.itl_mean_ms; } },
  ];
  function metric(id) {
    for (var i = 0; i < METRICS.length; i++) if (METRICS[i].id === id) return METRICS[i];
    return METRICS[0];
  }

  // Stat rows of a report endpoint block: [key, zh, en, unit].
  var ROWS = [
    ["latency_ms", "延迟", "Latency", "ms"],
    ["ttft_ms", "首 token 时间", "Time to first token", "ms"],
    ["decode_tps_reported", "解码速度（usage）", "Decode speed (usage)", "tok/s"],
    ["decode_tps_local", "解码速度（本地计数）", "Decode speed (local count)", "tok/s"],
    ["e2e_tps_reported", "端到端速度（usage）", "End-to-end speed (usage)", "tok/s"],
    ["e2e_tps_local", "端到端速度（本地计数）", "End-to-end speed (local count)", "tok/s"],
    ["itl_ms", "块间延迟", "Inter-chunk latency", "ms"],
    ["itl_jitter_ms", "块间抖动", "Inter-chunk jitter", "ms"],
    ["server_ms", "服务端时间（发送→首个输出）", "Server time (sent → first output)", "ms"],
    ["relay_processing_ms", "中转站自报处理时间", "Relay-reported processing", "ms"],
    ["network_rtt_ms", "网络往返（GET /models）", "Network round trip (GET /models)", "ms"],
    ["connect_ms", "TCP 连接", "TCP connect", "ms"],
    ["tls_ms", "TLS 握手", "TLS handshake", "ms"],
  ];
  var COLS = ["count", "min", "mean", "p50", "p75", "p90", "p95", "p99", "max", "stdev"];
  var COMPARE = {
    latency_p50: ["延迟 p50", "Latency p50"],
    latency_p90: ["延迟 p90", "Latency p90"],
    ttft_p50: ["TTFT p50", "TTFT p50"],
    ttft_p90: ["TTFT p90", "TTFT p90"],
    decode_tps_reported_p50: ["解码速度 p50（usage）", "Decode speed p50 (usage)"],
    decode_tps_local_p50: ["解码速度 p50（本地）", "Decode speed p50 (local)"],
    e2e_tps_local_p50: ["端到端速度 p50（本地）", "End-to-end speed p50 (local)"],
    itl_p50: ["块间延迟 p50", "Inter-chunk latency p50"],
    server_p50: ["服务端时间 p50", "Server time p50"],
    network_rtt_p50: ["网络往返 p50", "Network round trip p50"],
    error_rate: ["错误率", "Error rate"],
  };

  // Same floors as zing/utils/stats.py: a percentile needs this many samples.
  var FLOOR = { p50: 1, p75: 4, p90: 10, p95: 20, p99: 100 };
  function pct(sorted, p) {
    if (!sorted.length) return null;
    var rank = (p / 100) * (sorted.length - 1), lo = Math.floor(rank), hi = Math.ceil(rank);
    return lo === hi ? sorted[lo] : sorted[lo] * (1 - (rank - lo)) + sorted[hi] * (rank - lo);
  }
  function p50(values) {
    var s = values.filter(function (v) { return v != null; }).sort(function (a, b) { return a - b; });
    return pct(s, 50);
  }

  function niceCeil(v) {
    if (!(v > 0)) return 1;
    var base = Math.pow(10, Math.floor(Math.log10(v)));
    var steps = [1, 2, 2.5, 5, 10];
    for (var i = 0; i < steps.length; i++) if (v <= steps[i] * base) return steps[i] * base;
    return 10 * base;
  }

  // ---- timeline chart ------------------------------------------------- //
  var W = 720, H = 230, ML = 52, MR = 12, MT = 10, MB = 30;
  function chart(records, metricId) {
    var m = metric(metricId);
    var calls = (records || []).filter(function (r) { return r.op === "complete"; });
    var pts = calls.filter(function (r) { return r.ok && m.get(r) != null; });
    var failed = calls.filter(function (r) { return !r.ok; });
    if (!pts.length && !failed.length)
      return '<div class="zp-empty">' + esc(T("暂无数据", "No samples yet")) + "</div>";
    var end = 1;
    calls.forEach(function (r) { end = Math.max(end, (r.start_ms + (r.duration_ms || 0)) / 1000); });
    var xMax = niceCeil(end);
    var yMax = niceCeil(Math.max.apply(null, pts.map(m.get).concat([1])) * 1.05);
    var pw = W - ML - MR, ph = H - MT - MB;
    var x = function (s) { return ML + (s / xMax) * pw; };
    var y = function (v) { return MT + ph - (v / yMax) * ph; };
    var o = ['<svg class="zp-chart" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' +
      esc(T(m.zh, m.en)) + '">'];
    for (var i = 0; i <= 4; i++) {
      var v = (yMax * i) / 4, yy = y(v).toFixed(1);
      o.push('<line class="zp-grid" x1="' + ML + '" x2="' + (W - MR) + '" y1="' + yy + '" y2="' + yy + '"/>');
      o.push('<text class="zp-tick" x="' + (ML - 6) + '" y="' + (+yy + 4) + '" text-anchor="end">' + num(v) + "</text>");
      var s = (xMax * i) / 4;
      o.push('<text class="zp-tick" x="' + x(s).toFixed(1) + '" y="' + (H - MB + 16) +
        '" text-anchor="' + (i === 0 ? "start" : i === 4 ? "end" : "middle") + '">' + num(s) + "s</text>");
    }
    pts.forEach(function (r) {
      var cls = "zp-pt " + (r.endpoint === "baseline" ? "b" : "t") +
        (r.phase === "passive" ? " passive" : r.stream ? "" : " hollow") + (r.cached ? " cached" : "");
      o.push('<circle class="' + cls + '" cx="' + x(r.start_ms / 1000).toFixed(1) + '" cy="' +
        y(m.get(r)).toFixed(1) + '" r="4" data-tip="' + esc(tip(r, m)) + '"/>');
    });
    var by = MT + ph;
    failed.forEach(function (r) {
      var cx = x(r.start_ms / 1000);
      o.push('<path class="zp-fail" d="M' + (cx - 4).toFixed(1) + "," + (by - 4) + "l8,8m0,-8l-8,8" +
        '" data-tip="' + esc(tip(r, null)) + '"/>');
    });
    o.push("</svg>");
    return o.join("");
  }
  function tip(r, m) {
    var head = "#" + r.seq + " · " + (r.endpoint === "baseline" ? T("基线", "baseline") : T("目标", "target")) +
      " · " + (r.detector || "—") + " · " + r.phase + (r.stream ? "" : " · " + T("非流式", "non-streaming"));
    if (!m) return head + "\n" + T("失败", "failed") + " (" + (r.status_code || r.error_type || "?") + ")";
    var lines = [head, T(m.zh, m.en) + ": " + num(m.get(r)) + " " + m.unit];
    if (m.id !== "latency" && r.duration_ms != null) lines.push(T("延迟", "Latency") + ": " + num(r.duration_ms) + " ms");
    if (m.id !== "ttft" && r.ttft_ms != null) lines.push("TTFT: " + num(r.ttft_ms) + " ms");
    if (r.cached) lines.push(T("缓存命中（不计入统计）", "cached (excluded)"));
    return lines.join("\n");
  }

  function legend(records, hasBaseline) {
    var calls = (records || []).filter(function (r) { return r.op === "complete"; });
    var probe = calls.some(function (r) { return r.phase !== "passive"; });
    var items = ['<span><i class="zp-key t"></i>' + esc(T("目标", "target")) + "</span>"];
    if (hasBaseline) items.push('<span><i class="zp-key b"></i>' + esc(T("基线", "baseline")) + "</span>");
    if (probe && calls.some(function (r) { return r.phase === "passive"; }))
      items.push('<span><i class="zp-key t passive"></i>' + esc(T("常规检测请求（浅色）", "audit request (lighter)")) + "</span>");
    if (calls.some(function (r) { return r.phase !== "passive" && !r.stream; }))
      items.push('<span><i class="zp-key t hollow"></i>' + esc(T("非流式请求（空心）", "non-streaming request (hollow)")) + "</span>");
    if (calls.some(function (r) { return !r.ok; }))
      items.push('<span><i class="zp-key x">×</i>' + esc(T("失败请求", "failed request")) + "</span>");
    return '<div class="zp-legend">' + items.join("") + "</div>";
  }

  function tabs(active) {
    return '<div class="zp-tabs" role="tablist">' + METRICS.map(function (m) {
      return '<button type="button" role="tab" data-metric="' + m.id + '" aria-selected="' +
        (m.id === active) + '"' + (m.id === active ? ' class="on"' : "") + ">" + esc(T(m.zh, m.en)) + "</button>";
    }).join("") + "</div>";
  }

  // ---- tooltip + tabs wiring ------------------------------------------ //
  var tipEl = null;
  function showTip(evt, text) {
    if (!tipEl) {
      tipEl = document.createElement("div");
      tipEl.className = "zp-tip";
      document.body.appendChild(tipEl);
    }
    tipEl.textContent = text;
    tipEl.style.display = "block";
    var pad = 14, w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    var left = evt.clientX + pad, top = evt.clientY + pad;
    if (left + w > window.innerWidth - 8) left = evt.clientX - w - pad;
    if (top + h > window.innerHeight - 8) top = evt.clientY - h - pad;
    tipEl.style.left = left + "px";
    tipEl.style.top = top + "px";
  }
  function hideTip() {
    if (tipEl) tipEl.style.display = "none";
  }
  function wire(root, onMetric) {
    if (!root) return;
    root.querySelectorAll(".zp-tabs button").forEach(function (b) {
      b.onclick = function (e) {
        e.stopPropagation();
        onMetric(b.dataset.metric);
      };
    });
    root.querySelectorAll("[data-tip]").forEach(function (el) {
      el.addEventListener("mousemove", function (e) { showTip(e, el.getAttribute("data-tip")); });
      el.addEventListener("mouseleave", hideTip);
    });
  }

  // ---- report section --------------------------------------------------- //
  function statTable(ep) {
    var rows = ROWS.filter(function (r) { return ep[r[0]] && ep[r[0]].count; });
    if (!rows.length) return '<p class="zp-muted">' + esc(T("没有可统计的成功请求。", "No successful requests to summarize.")) + "</p>";
    return '<div class="zp-scroll"><table class="zp-table"><thead><tr><th>' + esc(T("指标", "Metric")) + "</th>" +
      COLS.map(function (c) { return '<th class="r">' + c + "</th>"; }).join("") + "</tr></thead><tbody>" +
      rows.map(function (r) {
        var s = ep[r[0]];
        return "<tr><td>" + esc(T(r[1], r[2])) + ' <span class="zp-unit">' + r[3] + "</span></td>" +
          COLS.map(function (c) { return '<td class="r">' + (c === "count" ? s.count : num(s[c])) + "</td>"; }).join("") +
          "</tr>";
      }).join("") + "</tbody></table></div>";
  }
  function p50of(stats) {
    return stats && stats.p50 != null ? stats.p50 : null;
  }
  function tiles(ep) {
    var streamed = ep.ttft_ms && ep.ttft_ms.count;
    var tps = p50of(ep.decode_tps_local);
    if (tps == null) tps = p50of(ep.decode_tps_reported);
    var t = [[T("延迟 p50", "Latency p50"), num(p50of(ep.latency_ms)), "ms"]];
    if (streamed) {
      t.push(["TTFT p50", num(p50of(ep.ttft_ms)), "ms"]);
      t.push([T("解码速度 p50", "Decode speed p50"), num(tps), "tok/s"]);
    } else {
      // Non-streamed calls have no first token: end-to-end speed instead.
      t.push([T("端到端速度 p50", "End-to-end speed p50"), num(p50of(ep.e2e_tps_local)), "tok/s"]);
    }
    t.push([T("错误率", "Error rate"), num(ep.error_rate, "ratio"), ""]);
    return '<div class="zp-tiles">' + t.map(function (x) {
      return '<div class="zp-tile"><div class="zp-tl">' + esc(x[0]) + '</div><div class="zp-tv">' + esc(x[1]) +
        (x[2] ? ' <small>' + x[2] + "</small>" : "") + "</div></div>";
    }).join("") + "</div>";
  }
  function endpointBlock(ep, title) {
    var o = [];
    if (title) o.push('<h4 class="zp-h">' + esc(title) + "</h4>");
    o.push(tiles(ep));
    var line = ep.successes + "/" + ep.requests + " " + T("成功", "succeeded") + " · " +
      T("超时", "timeouts") + " " + num(ep.timeout_rate, "ratio") + " · 429 " + num(ep.rate_limited_rate, "ratio");
    if (ep.cached_excluded) line += " · " + ep.cached_excluded + " " + T("缓存命中（不计入统计）", "cached (excluded)");
    o.push('<p class="zp-muted">' + esc(line) + "</p>");
    var extra = [];
    if (ep.cold_start_ms != null)
      extra.push(T("冷启动（首个请求）", "Cold start (first request)") + ": " + num(ep.cold_start_ms) + " ms" +
        (ep.cold_start_ttft_ms != null ? ", TTFT " + num(ep.cold_start_ttft_ms) + " ms" : ""));
    var c = ep.concurrency;
    if (c)
      extra.push(T("并发负载", "Under load") + " (" + c.requests + " × " + c.concurrency + "): " +
        T("总吞吐", "aggregate") + " " + num(c.aggregate_tps_local) + " tok/s, " + T("延迟 p50", "Latency p50") + " " +
        num(c.latency_ms && c.latency_ms.p50) + " ms");
    if (extra.length) o.push('<ul class="zp-list">' + extra.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul>");
    o.push(statTable(ep));
    if ((ep.ttft_by_input || []).length > 1) {
      o.push('<table class="zp-table zp-small"><thead><tr><th>' + esc(T("提示词长度", "Prompt size")) + '</th><th class="r">n</th>' +
        '<th class="r">TTFT p50</th><th class="r">' + esc(T("延迟 p50", "Latency p50")) + "</th></tr></thead><tbody>" +
        ep.ttft_by_input.map(function (b) {
          return "<tr><td>" + esc(b.label) + '</td><td class="r">' + b.count + '</td><td class="r">' + num(b.ttft_p50_ms) +
            '</td><td class="r">' + num(b.latency_p50_ms) + "</td></tr>";
        }).join("") + "</tbody></table>");
    }
    return o.join("");
  }

  // Same rule as PerformanceComparison.target_better in zing/models.py: true /
  // false when the target is better / worse, null within 2% or with a side missing.
  function targetBetter(c) {
    if (c.delta == null || c.target == null || c.baseline == null) return null;
    var scale = Math.max(Math.abs(c.target), Math.abs(c.baseline));
    if (!scale || Math.abs(c.delta) / scale < 0.02) return null;
    return c.delta > 0 === !!c.higher_is_better;
  }
  function compareTable(rows) {
    return '<table class="zp-table"><thead><tr><th>' + esc(T("指标", "Metric")) + '</th><th class="r">' +
      esc(T("目标", "Target")) + '</th><th class="r">' + esc(T("基线", "Baseline")) + '</th><th class="r">Δ</th><th class="r">' +
      esc(T("比值", "Ratio")) + "</th></tr></thead><tbody>" + rows.map(function (c) {
        var lab = COMPARE[c.metric] ? T(COMPARE[c.metric][0], COMPARE[c.metric][1]) : c.metric;
        var d = c.delta == null ? "—" : c.unit === "ratio" ? (c.delta > 0 ? "+" : "") + (c.delta * 100).toFixed(1) + " pp" : (c.delta > 0 ? "+" : "") + num(c.delta);
        var b = targetBetter(c), cls = b === true ? " zp-better" : b === false ? " zp-worse" : "";
        var mark = b === true ? "✓ " : b === false ? "✗ " : "";
        return "<tr><td>" + esc(lab) + ' <span class="zp-unit">' + esc(c.unit) + '</span></td><td class="r">' +
          num(c.target, c.unit) + '</td><td class="r">' + num(c.baseline, c.unit) + '</td><td class="r' + cls + '">' + mark + d +
          '</td><td class="r">' + (c.ratio == null ? "—" : c.ratio.toFixed(2) + "x") + "</td></tr>";
      }).join("") + "</tbody></table>" +
      '<p class="zp-muted"><span class="zp-better">✓ ' + esc(T("目标更好", "target better")) + '</span> · <span class="zp-worse">✗ ' +
      esc(T("目标更差", "target worse")) + "</span> " + esc(T("（相差 2% 以内视为持平）", "(within 2% counts as even)")) + "</p>";
  }
  var MODE_TITLE = { stream: ["流式", "Streaming"], non_stream: ["非流式", "Non-streaming"] };
  function modeBlock(mode, target, baseline, comparison, titled) {
    var o = [];
    if (titled && MODE_TITLE[mode]) o.push('<h4 class="zp-h zp-mode">' + esc(T(MODE_TITLE[mode][0], MODE_TITLE[mode][1])) + "</h4>");
    o.push(endpointBlock(target, baseline ? T("目标", "Target") : ""));
    if (baseline) o.push(endpointBlock(baseline, T("基线", "Baseline")));
    if ((comparison || []).length) {
      o.push('<h4 class="zp-h">' + esc(T("目标 vs 基线", "Target vs baseline")) + "</h4>");
      o.push(compareTable(comparison));
    }
    return o.join("");
  }

  var sectionState = { metric: "latency" };
  function section(perf) {
    if (!perf || !perf.target) return "";
    var modes = perf.modes || [];
    var kind = [perf.mode].concat(modes.map(function (m) { return m.mode; }))
      .filter(function (m) { return MODE_TITLE[m]; })
      .map(function (m) { return T(MODE_TITLE[m][0], MODE_TITLE[m][1]); }).join(" + ");
    var src = perf.source === "probe"
      ? T("来源：专用性能探测", "Source: dedicated probe") + " — " + perf.probe_requests + " × " +
        (perf.probe_max_tokens || "?") + " tokens" + (kind ? " · " + kind : "")
      : T("来源：本次检测自身的请求", "Source: the audit's own requests");
    var hasB = !!perf.baseline;
    var o = ['<div class="zp-section">'];
    o.push('<p class="zp-muted">' + esc(src) + " · " + esc(T("仅供参考，不计分", "Informational — not scored")) + "</p>");
    o.push(tabs(sectionState.metric));
    o.push('<div class="zp-plot">' + chart(perf.requests, sectionState.metric) + "</div>");
    o.push(legend(perf.requests, hasB));
    o.push(modeBlock(perf.mode, perf.target, perf.baseline, perf.comparison, modes.length > 0));
    modes.forEach(function (m) {
      o.push(modeBlock(m.mode, m.target, m.baseline, m.comparison, true));
    });
    if (perf.probe_cost) {
      var pc = perf.probe_cost;
      o.push('<p class="zp-muted">' + esc(T("探测成本", "Probe cost")) + ": " + esc(T("请求数", "Requests")) + " " +
        pc.requests + " · " +
        num(pc.input_tokens_reported) + " + " + num(pc.output_tokens_reported) + " tokens (usage)</p>");
    }
    if ((perf.notes || []).length)
      o.push('<ul class="zp-list zp-notes">' + perf.notes.map(function (n) { return "<li>" + esc(note(n)) + "</li>"; }).join("") + "</ul>");
    o.push("</div>");
    return o.join("");
  }
  // Re-draw only the chart of a rendered section when its metric tab changes.
  function wireSection(root, perf) {
    wire(root, function (id) {
      sectionState.metric = id;
      var plot = root.querySelector(".zp-plot"), tabsEl = root.querySelector(".zp-tabs");
      if (plot) plot.innerHTML = chart(perf.requests, id);
      if (tabsEl) tabsEl.outerHTML = tabs(id);
      wireSection(root, perf);
    });
  }

  // ---- live panel -------------------------------------------------------- //
  function Live(host) {
    this.host = host;
    this.metric = "latency";
    this.reset({});
  }
  Live.prototype.reset = function (opts) {
    this.records = [];
    this.probeTotal = (opts && opts.probeTotal) || 0;
    this.hasBaseline = !!(opts && opts.hasBaseline);
    this.pending = false;
    if (this.host) this.host.innerHTML = "";
  };
  Live.prototype.add = function (records) {
    var self = this;
    (records || []).forEach(function (r) { self.records.push(r); });
    if (this.pending) return;
    this.pending = true;
    requestAnimationFrame(function () {
      self.pending = false;
      self.render();
    });
  };
  Live.prototype.render = function () {
    if (!this.host || !this.records.length) return;
    var self = this, recs = this.records;
    var calls = recs.filter(function (r) { return r.op === "complete"; });
    var target = calls.filter(function (r) { return r.endpoint !== "baseline" && r.ok && !r.cached; });
    var probeDone = calls.filter(function (r) { return r.endpoint !== "baseline" && r.phase === "probe"; }).length;
    var tps = target.map(function (r) { return r.decode_tps_local != null ? r.decode_tps_local : r.decode_tps_reported; });
    var head = [
      [T("请求数", "Requests"), String(calls.length)],
      [T("延迟 p50", "Latency p50"), num(p50(target.map(function (r) { return r.duration_ms; }))) + " ms"],
      ["TTFT p50", num(p50(target.map(function (r) { return r.ttft_ms; }))) + " ms"],
      [T("解码速度 p50", "Decode speed p50"), num(p50(tps)) + " tok/s"],
    ];
    var o = ['<div class="zp-live"><div class="zp-live-h">' + esc(T("性能 · 实时", "Performance · live")) + "</div>"];
    o.push('<div class="zp-tiles">' + head.map(function (x) {
      return '<div class="zp-tile"><div class="zp-tl">' + esc(x[0]) + '</div><div class="zp-tv">' + esc(x[1]) + "</div></div>";
    }).join("") + "</div>");
    if (this.probeTotal) {
      var pctDone = Math.min(100, Math.round((probeDone / this.probeTotal) * 100));
      o.push('<div class="zp-probe"><span>' + esc(T("性能探测", "Performance probe")) + " " + probeDone + "/" +
        this.probeTotal + '</span><div class="zp-bar"><i style="width:' + pctDone + '%"></i></div></div>');
    }
    o.push(tabs(this.metric));
    o.push('<div class="zp-plot">' + chart(recs, this.metric) + "</div>");
    o.push(legend(recs, this.hasBaseline));
    o.push("</div>");
    this.host.innerHTML = o.join("");
    wire(this.host, function (id) {
      self.metric = id;
      self.render();
    });
  };

  // ---- styles (injected once) ------------------------------------------- //
  var CSS =
    ".zp-section,.zp-live{--zp-t:#2a78d6;--zp-b:#eb6834;--zp-x:#d03b3b;--zp-surface:#fffefb;--zp-grid:#e7ece5;" +
    "--zp-ink:#0c211e;--zp-ink2:#566460;--zp-faint:#93a09b;text-align:left}" +
    ".zp-live{margin:18px auto 0;max-width:620px;background:#fff;border:1px solid var(--zp-grid);border-radius:14px;padding:12px 14px}" +
    ".zp-live-h{font-weight:700;font-size:13px;color:var(--zp-ink);margin-bottom:8px}" +
    ".zp-tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:4px 0 10px}" +
    "@media(max-width:520px){.zp-tiles{grid-template-columns:1fr 1fr}}" +
    ".zp-tile{background:#f5f8f4;border:1px solid var(--zp-grid);border-radius:10px;padding:7px 9px}" +
    ".zp-tl{font-size:11px;color:var(--zp-faint);font-weight:600}" +
    ".zp-tv{font-weight:700;font-size:16px;color:var(--zp-ink);font-variant-numeric:tabular-nums}" +
    ".zp-tv small{font-size:11px;color:var(--zp-ink2);font-weight:600}" +
    ".zp-probe{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--zp-ink2);margin:0 0 8px;font-family:var(--mono,monospace)}" +
    ".zp-bar{flex:1;height:5px;background:#e3ebe3;border-radius:3px;overflow:hidden}" +
    ".zp-bar i{display:block;height:100%;background:var(--zp-t);transition:width .3s}" +
    ".zp-tabs{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 6px}" +
    ".zp-tabs button{font:600 12px var(--sans,system-ui);color:var(--zp-ink2);background:#fbfdfa;border:1.5px solid var(--zp-grid);border-radius:999px;padding:4px 11px;cursor:pointer}" +
    ".zp-tabs button.on{color:#fff;background:var(--zp-ink);border-color:var(--zp-ink)}" +
    ".zp-chart{width:100%;height:auto;display:block}" +
    ".zp-grid{stroke:var(--zp-grid);stroke-width:1}" +
    ".zp-tick{fill:var(--zp-ink2);font-size:11px;font-variant-numeric:tabular-nums}" +
    ".zp-pt{stroke:var(--zp-surface);stroke-width:2}.zp-pt.t{fill:var(--zp-t)}.zp-pt.b{fill:var(--zp-b)}" +
    ".zp-pt.passive{fill-opacity:.45}.zp-pt.cached{fill:#8c959f;fill-opacity:.6}.zp-pt:hover{stroke:var(--zp-ink)}" +
    ".zp-pt.hollow{fill:var(--zp-surface)}.zp-pt.hollow.t{stroke:var(--zp-t)}.zp-pt.hollow.b{stroke:var(--zp-b)}" +
    ".zp-legend .zp-key.hollow{background:transparent;border:2px solid var(--zp-t);box-sizing:border-box}" +
    ".zp-better{color:#1a7f37;font-weight:700}.zp-worse{color:#cb3b2e;font-weight:700}" +
    ".zp-mode{border-top:1px solid var(--zp-grid);padding-top:14px;margin-top:20px;font-size:14.5px}" +
    ".zp-fail{stroke:var(--zp-x);stroke-width:2;stroke-linecap:round}" +
    ".zp-legend{display:flex;flex-wrap:wrap;gap:12px;font-size:11.5px;color:var(--zp-ink2);margin:2px 0 8px}" +
    ".zp-key{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;font-style:normal}" +
    ".zp-key.t{background:var(--zp-t)}.zp-key.b{background:var(--zp-b)}.zp-key.passive{opacity:.45}" +
    ".zp-key.x{width:auto;height:auto;border-radius:0;color:var(--zp-x);font-weight:800}" +
    ".zp-empty{font-size:12.5px;color:var(--zp-faint);padding:18px 0;text-align:center}" +
    ".zp-muted{font-size:12.5px;color:var(--zp-ink2);margin:6px 0;line-height:1.5}" +
    ".zp-h{font-size:13.5px;margin:16px 0 6px;color:var(--zp-ink)}" +
    ".zp-scroll{overflow-x:auto}" +
    ".zp-table{width:100%;border-collapse:collapse;font-size:12px;margin:6px 0 10px;font-variant-numeric:tabular-nums}" +
    ".zp-table th{font-size:10.5px;text-transform:uppercase;letter-spacing:.4px;color:var(--zp-faint);text-align:left;padding:5px 7px;border-bottom:1px solid var(--zp-grid)}" +
    ".zp-table td{padding:5px 7px;border-bottom:1px dotted var(--zp-grid);color:var(--zp-ink2);white-space:nowrap}" +
    ".zp-table .r{text-align:right}.zp-table.zp-small{width:auto}" +
    ".zp-unit{color:var(--zp-faint);font-size:10.5px}" +
    ".zp-list{font-size:12.5px;color:var(--zp-ink2);margin:6px 0;padding-left:18px;line-height:1.55}" +
    ".zp-tip{position:fixed;z-index:50;display:none;pointer-events:none;white-space:pre;background:#0c211e;color:#fff;" +
    "font:500 11.5px/1.45 var(--mono,monospace);padding:7px 9px;border-radius:8px;box-shadow:0 8px 24px -10px rgba(0,0,0,.5)}";
  (function inject() {
    if (typeof document === "undefined" || !document.head || document.getElementById("zp-css")) return;
    var st = document.createElement("style");
    st.id = "zp-css";
    st.textContent = CSS;
    document.head.appendChild(st);
  })();

  window.ZingPerf = {
    Live: Live,
    section: section,
    wireSection: wireSection,
    chart: chart,
  };
})();
