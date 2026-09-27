/* zing web UI v2 — the audit report view, shared by the audit and history pages.
 *
 *   <link rel="stylesheet" href="/v2/static/report.css" />
 *   <script src="/v2/static/report.js"></script>   (after lang.js, i18n.js, icons.js,
 *                                                   and perf.js if performance is shown)
 *
 *   ZingReport.render(el, report, {
 *     actions: [{ zh: "再测一个", en: "Test another", primary: false, onClick: fn }, …],
 *   })
 *     renders `report` (the /api/audit/stream "report" event, or a history row's
 *     report) into `el`, wires its interactions, and re-renders it in place when
 *     the UI language changes (expanded evidence stays open).
 *   ZingReport.wire(el)    (re)attach the interactions after external re-rendering.
 *
 * All text goes through T(zh, en) / ZING_LANG.server() / ZING_I18N like the
 * rest of the UI; colours only through the tokens of zing.css.
 */
(function () {
  "use strict";

  function T(zh, en) {
    return window.ZING_LANG ? window.ZING_LANG.t(zh, en) : en;
  }
  function srv(s) {
    return window.ZING_LANG ? window.ZING_LANG.server(s) : s;
  }
  function ico(name, opts) {
    return window.zingIcon ? window.zingIcon(name, opts || {}) : "";
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // risk level -> token family + plain-language pill text
  var RISK = {
    clean: { c: "good", t: ["大概率是真货", "Most likely genuine"] },
    low: { c: "sky", t: ["基本可信，小瑕疵", "Mostly trustworthy, minor issues"] },
    medium: { c: "warn", t: ["有偏离，建议核实", "Deviations, verify"] },
    high: { c: "bad", t: ["货不对板", "Bait-and-switch"] },
    inconclusive: { c: "grey", t: ["信号不足", "Insufficient signal"] },
  };
  var STATC = { pass: "good", warn: "warn", fail: "bad", info: "sky", inconclusive: "grey", not_run: "grey", error: "bad" };
  var SEVC = { info: "sky", low: "warn", medium: "warn", high: "bad", critical: "bad" };
  var ICON_NAME = { pass: "check", warn: "warning", fail: "x", info: "info", inconclusive: "info", not_run: "info", error: "x" };
  var DIMNAME = {
    model_identity: ["模型身份", "它是不是它自称的那个？"],
    context_window: ["上下文窗口", "长文是否真能记住？"],
    capability: ["能力声明", "工具/JSON 是否真支持？"],
    billing: ["计费用量", "token 有没有虚报？"],
    protocol: ["协议兼容", "接口是否规范？"],
    connectivity: ["连通性", "稳定可达？"],
    reliability: ["并发可靠", "压力下稳不稳？"],
    streaming: ["流式真实", "真流式还是假装？"],
    security: ["传输安全", "密钥是否安全？"],
  };
  var DIMNAME_EN = {
    model_identity: ["Model identity", "Is it the model it claims to be?"],
    context_window: ["Context window", "Does it really remember long input?"],
    capability: ["Capability claims", "Are tools/JSON really supported?"],
    billing: ["Billing & usage", "Is token usage inflated?"],
    protocol: ["Protocol compliance", "Is the API spec-compliant?"],
    connectivity: ["Connectivity", "Reliably reachable?"],
    reliability: ["Concurrency reliability", "Stable under load?"],
    streaming: ["Streaming authenticity", "Real streaming or faked?"],
    security: ["Transport security", "Are keys handled safely?"],
  };

  function isZh() {
    return window.ZING_LANG && window.ZING_LANG.isZh();
  }
  function dimName(k) {
    if (isZh()) return DIMNAME[k];
    var e = DIMNAME_EN[k];
    return e && e.map(function (s) {
      return window.ZING_LANG ? window.ZING_LANG.tr(s) : s;
    });
  }
  function scoreC(v) {
    return v == null ? "grey" : v >= 85 ? "good" : v >= 70 ? "warn" : "bad";
  }
  function sevRank(s) {
    return { critical: 5, high: 4, medium: 3, low: 2, info: 1 }[s] || 0;
  }
  function riskGlyph(r) {
    return ico(r === "high" ? "x" : r === "clean" ? "check" : r === "inconclusive" ? "info" : "warning");
  }
  function conf(c) {
    var m = { high: ["高", "High"], medium: ["中", "Medium"], low: ["低", "Low"] }[c];
    return m ? T(m[0], m[1]) : c || "—";
  }
  function head(v) {
    var m = {
      clean: ["行为与所声称的模型一致", "Behavior is consistent with the claimed model"],
      low: ["基本一致，存在少量小问题", "Mostly consistent, with a few minor issues"],
      medium: ["部分行为与所声称的模型不符 —— 建议核实", "Some behavior does not match the claimed model — verify"],
      high: ["它给的并不是你所声称的模型", "It is not serving the model it claims"],
      inconclusive: ["信号不足，无法判定（连通或覆盖不够）", "Insufficient signal to decide (connectivity or coverage too low)"],
    }[v.risk_level];
    return m ? T(m[0], m[1]) : srv(v.headline) || "";
  }
  function loc(f) {
    if (window.ZING_I18N && window.ZING_I18N.localizeFinding)
      return window.ZING_I18N.localizeFinding(f.id, f.summary, f.evidence, f.title, f.status);
    return { title: srv(f.title), summary: srv(f.summary || "") };
  }
  function fmt(x) {
    if (x == null) return "null";
    if (typeof x === "object") return JSON.stringify(x).slice(0, 200);
    return String(x).slice(0, 240);
  }
  function evText(e) {
    if (!e || typeof e !== "object") return "";
    return Object.keys(e)
      .slice(0, 6)
      .map(function (k) {
        return k + ": " + fmt(e[k]);
      })
      .join("\n");
  }

  var uid = 0;

  function dimRow(d) {
    var n = dimName(d.dimension) || [d.dimension, ""];
    var c = scoreC(d.score);
    var sc = d.score == null ? "—" : Math.round(d.score * 10) / 10;
    var st = STATC[d.status] || "grey";
    return (
      '<div class="zr-dim"><div class="nm">' + esc(n[0]) + "<small>" + esc(n[1]) + "</small></div>" +
      '<div class="bar"><i data-w="' + (d.score == null ? 15 : d.score) + '" class="' + (d.score == null ? "grey" : c) + '"></i></div>' +
      '<span class="badge ' + st + '">' + sc + "</span></div>"
    );
  }

  function findRow(f) {
    var c = SEVC[f.severity] || "grey";
    var ev = evText(f.evidence);
    var L = loc(f);
    var id = "zr-ev-" + ++uid;
    return (
      '<div class="zr-find"><div class="dot ' + c + '">' + ico(ICON_NAME[f.status] || "info") + "</div>" +
      '<div class="body"><div class="ft">' + esc(L.title) + "</div>" +
      '<div class="fs">' + esc(L.summary) +
      (f.recommendation ? ' <span class="rec">· ' + T("建议：", "Recommendation: ") + esc(srv(f.recommendation)) + "</span>" : "") +
      "</div>" +
      (ev
        ? '<button type="button" class="linkbtn more" aria-expanded="false" aria-controls="' + id + '">' +
          T("查看证据", "Show evidence") + "</button>" +
          '<pre class="ev" id="' + id + '" hidden>' + esc(ev) + "</pre>"
        : "") +
      "</div></div>"
    );
  }

  function html(r, opts) {
    var v = r.verdict || {};
    var risk = RISK[v.risk_level] || RISK.inconclusive;
    var sc = v.overall_score;
    var t = r.target || {};
    var dims = (r.dimensions || []).filter(function (d) {
      return d.status !== "not_run";
    });
    var findings = [];
    (r.detectors || []).forEach(function (det) {
      (det.findings || []).forEach(function (f) {
        if (["fail", "warn", "error"].indexOf(f.status) >= 0) findings.push(f);
      });
    });
    findings.sort(function (a, b) {
      return sevRank(b.severity) - sevRank(a.severity);
    });
    var code = function (s) {
      return "<code>" + esc(s) + "</code>";
    };
    var meta = [
      T("目标", "Target") + " " + code(t.base_url || ""),
      T("声称", "Claimed") + " " + code(t.claimed_model || t.model || ""),
    ];
    if (t.claimed_model && t.claimed_model !== t.model) meta.push(T("实测 id", "Tested id") + " " + code(t.model));
    if (r.baseline) meta.push(T("对照基线", "Baseline") + " " + code(r.baseline.model || "") + " @ " + code(r.baseline.base_url || ""));
    meta.push(T("模式", "Mode") + " " + code(r.mode || "check"));
    meta.push(T("套件", "Suite") + " " + code(r.suite || ""));
    if ((r.prompt_languages || []).length)
      meta.push(T("探测语言", "Probe languages") + " " + code(r.prompt_languages.map(function (c) {
        return c.toUpperCase();
      }).join(" · ")));
    meta.push("zing v" + esc(r.tool_version || ""));

    var actions = (opts.actions || [])
      .map(function (a, i) {
        return '<button type="button" class="btn' + (a.primary ? " pri" : "") + '" data-action="' + i + '">' + esc(T(a.zh, a.en)) + "</button>";
      })
      .join("");

    return (
      '<article class="zr card ' + risk.c + '">' +
      '<div class="ribbon"></div>' +
      '<div class="vhero"><div class="grade">' + esc(v.rating || "–") + "</div>" +
      '<div class="vmeta"><span class="badge ' + risk.c + ' vpill">' + riskGlyph(v.risk_level) + " " + esc(T(risk.t[0], risk.t[1])) + "</span>" +
      "<h2>" + esc(head(v)) + "</h2>" +
      "<p>" + esc(srv(v.summary || "")) + "</p>" +
      '<div class="vscores"><div>' + T("综合健康分", "Overall health score") + ' <b class="' + scoreC(sc) + '">' + (sc == null ? "—" : sc) + "</b>/100</div>" +
      "<div>" + T("结论置信度", "Verdict confidence") + " <b>" + esc(conf(v.confidence)) + "</b></div></div>" +
      "</div></div>" +
      '<div class="meta-strip">' + meta.map(function (m) {
        return "<span>" + m + "</span>";
      }).join("") + "</div>" +
      '<section class="sect"><h3>' + T("逐项体检", "Per-dimension checks") + "</h3>" + dims.map(dimRow).join("") + "</section>" +
      '<section class="sect"><h3>' + T("关注点", "Findings") + "</h3>" +
      (findings.length
        ? findings.map(findRow).join("")
        : '<p class="none">' + T("未发现警告或失败项 —— 各维度表现与所声称模型一致。", "No warnings or failures — every dimension is consistent with the claimed model.") + "</p>") +
      "</section>" +
      (r.performance && window.ZingPerf
        ? '<section class="sect perf-sect"><h3>' + T("性能", "Performance") + "</h3>" + window.ZingPerf.section(r.performance) + "</section>"
        : "") +
      '<div class="disc">' +
      T(
        "zing 出具的是<strong>行为偏离与风险的可复现证据</strong>，不是欺诈的法律/密码学证明。中转站可能按概率路由；请结合样本量、计费设置与当地法律自行判断，切勿仅凭单次结果公开指控厂商。",
        "zing provides <strong>reproducible evidence of behavioral deviation and risk</strong>, not legal or cryptographic proof of fraud. Relays may route probabilistically; weigh sample size, billing settings and local law yourself, and never publicly accuse a vendor based on a single run."
      ) +
      "</div>" +
      (actions ? '<div class="actions">' + actions + "</div>" : "") +
      "</article>"
    );
  }

  function wire(el) {
    var st = el.__zingReport || {};
    var bars = el.querySelectorAll(".zr-dim .bar i");
    requestAnimationFrame(function () {
      for (var i = 0; i < bars.length; i++) bars[i].style.width = bars[i].getAttribute("data-w") + "%";
    });
    var more = el.querySelectorAll(".zr-find .more");
    for (var j = 0; j < more.length; j++)
      more[j].onclick = function () {
        var btn = this,
          ev = document.getElementById(btn.getAttribute("aria-controls"));
        var open = ev.hidden;
        ev.hidden = !open;
        btn.setAttribute("aria-expanded", String(open));
        btn.textContent = open ? T("收起证据", "Hide evidence") : T("查看证据", "Show evidence");
      };
    var acts = el.querySelectorAll("[data-action]");
    for (var k = 0; k < acts.length; k++)
      acts[k].onclick = function () {
        var a = (st.opts.actions || [])[+this.getAttribute("data-action")];
        if (a && a.onClick) a.onClick(st.report);
      };
    var perf = el.querySelector(".perf-sect");
    if (perf && window.ZingPerf && st.report && st.report.performance) window.ZingPerf.wireSection(perf, st.report.performance);
  }

  function render(el, report, opts) {
    opts = opts || {};
    el.__zingReport = { report: report, opts: opts };
    el.innerHTML = html(report, opts);
    wire(el);
  }

  // Re-render every mounted report in the new language, keeping open evidence.
  window.addEventListener("zing:lang", function () {
    var els = document.querySelectorAll(".zr");
    for (var i = 0; i < els.length; i++) {
      var host = els[i].parentNode;
      var st = host && host.__zingReport;
      if (!st) continue;
      var open = [].map.call(host.querySelectorAll(".zr-find .ev"), function (e) {
        return !e.hidden;
      });
      render(host, st.report, st.opts);
      [].forEach.call(host.querySelectorAll(".zr-find .ev"), function (e, n) {
        if (!open[n]) return;
        e.hidden = false;
        var b = host.querySelector('[aria-controls="' + e.id + '"]');
        if (b) {
          b.setAttribute("aria-expanded", "true");
          b.textContent = T("收起证据", "Hide evidence");
        }
      });
    }
  });

  window.ZingReport = { render: render, wire: wire };
})();
