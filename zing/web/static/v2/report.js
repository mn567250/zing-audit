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
 *     the UI language changes (expanded evidence and keyboard focus are kept).
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
  // T() with {placeholders} filled in after translation
  function Tf(zh, en, vals) {
    return T(zh, en).replace(/\{(\w+)\}/g, function (m, k) {
      return Object.prototype.hasOwnProperty.call(vals, k) ? vals[k] : m;
    });
  }
  function isZh() {
    return !!(window.ZING_LANG && window.ZING_LANG.isZh());
  }
  // Backend (English) text in the UI language. CN translates the known
  // backend sentences too, so the summary never shows English inside Chinese.
  function srv(s) {
    var L = window.ZING_LANG;
    if (!L) return s;
    return isZh() && L.exportText ? L.exportText(s) : L.server(s);
  }
  function ico(name, opts) {
    return window.zingIcon ? window.zingIcon(name, opts || {}) : "";
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function reEsc(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  function label(kind, key) {
    return window.ZING_I18N ? window.ZING_I18N.label(kind, key) : key;
  }
  function locale() {
    return window.ZING_LANG && window.ZING_LANG.locale ? window.ZING_LANG.locale() : undefined;
  }
  function num(v, digits) {
    try {
      return Number(v).toLocaleString(locale(), { maximumFractionDigits: digits });
    } catch (e) {
      return String(Math.round(v * Math.pow(10, digits)) / Math.pow(10, digits));
    }
  }

  // risk level -> token family + glyph (the pill text is ZING_I18N.label)
  var RISK = {
    clean: { c: "good", g: "check" },
    low: { c: "sky", g: "warning" },
    medium: { c: "warn", g: "warning" },
    high: { c: "bad", g: "x" },
    inconclusive: { c: "grey", g: "info" },
  };
  var STATC = { pass: "good", warn: "warn", fail: "bad", info: "sky", inconclusive: "grey", not_run: "grey", error: "bad" };
  // severity -> colour AND glyph, one source (never colour by one field and glyph by another)
  var SEV = {
    critical: { c: "bad", g: "x", r: 5 },
    high: { c: "bad", g: "x", r: 4 },
    medium: { c: "warn", g: "warning", r: 3 },
    low: { c: "warn", g: "warning", r: 2 },
    info: { c: "sky", g: "info", r: 1 },
  };
  var SEV_NONE = { c: "grey", g: "info", r: 0 };
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

  function dimName(k) {
    if (isZh()) return DIMNAME[k];
    var e = DIMNAME_EN[k];
    return (
      e &&
      e.map(function (s) {
        return window.ZING_LANG ? window.ZING_LANG.tr(s) : s;
      })
    );
  }
  function scoreC(v) {
    return v == null ? "grey" : v >= 85 ? "good" : v >= 70 ? "warn" : "bad";
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

  // The backend summary (zing/scoring.py::_summary) opens with the score line
  // and closes with the disclaimer; the card shows both elsewhere, so drop
  // them — in English (the backend) and in any translated form (a report that
  // went through ZING_I18N.exportReport and came back via history/import).
  var SCORE_EN = "Overall health score {1}/100.";
  var DISC_EN = "zing reports black-box evidence of divergence and risk, not proof of fraud.";
  function summaryRest(s) {
    s = String(s || "");
    var forms = [[SCORE_EN, DISC_EN]];
    var strings = (window.ZING_LOCALES && window.ZING_LOCALES.strings) || {};
    Object.keys(strings).forEach(function (code) {
      var d = strings[code] || {};
      forms.push([d[SCORE_EN], d[DISC_EN]]);
    });
    forms.forEach(function (f) {
      if (f[0]) s = s.replace(new RegExp("\\s*" + reEsc(f[0]).replace("\\{1\\}", "[\\d.,]+"), "g"), " ");
      if (f[1]) s = s.split(f[1]).join(" ");
    });
    return s.replace(/\s{2,}/g, " ").trim();
  }

  function langName(c) {
    try {
      var dn = new Intl.DisplayNames([locale() || "en"], { type: "language" });
      return dn.of(c) || c;
    } catch (e) {
      return c;
    }
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
  function loc(f) {
    if (window.ZING_I18N && window.ZING_I18N.localizeFinding)
      return window.ZING_I18N.localizeFinding(f.id, f.summary, f.evidence, f.title, f.status);
    return { title: srv(f.title), summary: srv(f.summary || "") };
  }
  function count(n, one, many) {
    // one = [zh, en] for n === 1, many = [zh, en] otherwise; both carry {n}
    var p = n === 1 ? one : many;
    return Tf(p[0], p[1], { n: num(n, 0) });
  }
  function showEvidence(open) {
    return open ? T("收起证据", "Hide evidence") : T("查看证据", "Show evidence");
  }

  var uid = 0;

  function dimRow(d) {
    var n = dimName(d.dimension) || [d.dimension, ""];
    var c = STATC[d.status] || scoreC(d.score);
    var hasScore = d.score != null && isFinite(d.score);
    var v = hasScore ? Math.max(0, Math.min(100, Math.round(d.score))) : null;
    var st = label("STATUS", d.status);
    var id = "zr-dn-" + ++uid;
    var valText = hasScore
      ? num(v, 0) + "/100 · " + st
      : T("未评分", "Not scored") + " · " + st;
    return (
      '<div class="zr-dim"><div class="nm" id="' + id + '">' + esc(n[0]) + "<small>" + esc(n[1]) + "</small></div>" +
      (hasScore
        ? '<div class="bar" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + v +
          '" aria-valuetext="' + esc(valText) + '" aria-labelledby="' + id + '"><i data-w="' + v + '" class="' + c + '"></i></div>'
        : '<div class="bar none"><i data-w="0" class="grey"></i><span class="sr-only">' + esc(valText) + "</span></div>") +
      '<span class="badge ' + c + '" aria-hidden="true">' + (hasScore ? esc(num(v, 0)) : "—") + "</span></div>"
    );
  }

  function findRow(f) {
    var s = SEV[f.severity] || SEV_NONE;
    var ev = evText(f.evidence);
    var L = loc(f);
    var id = "zr-ev-" + ++uid;
    return (
      '<li class="zr-find"><span class="dot ' + s.c + '" aria-hidden="true">' + ico(s.g) + "</span>" +
      '<div class="body"><div class="ft"><span class="sr-only">' +
      esc(Tf("严重程度：{s}。", "Severity: {s}.", { s: label("SEVERITY", f.severity) })) + " </span>" + esc(L.title) + "</div>" +
      '<div class="fs">' + esc(L.summary) +
      (f.recommendation ? ' <span class="rec">· ' + esc(T("建议：", "Recommendation: ")) + esc(srv(f.recommendation)) + "</span>" : "") +
      "</div>" +
      (ev
        ? '<button type="button" class="linkbtn more" aria-expanded="false" aria-controls="' + id + '">' +
          esc(showEvidence(false)) + "</button>" +
          '<pre class="ev" id="' + id + '" hidden>' + esc(ev) + "</pre>"
        : "") +
      "</div></li>"
    );
  }

  function findingGroups(findings) {
    var order = ["critical", "high", "medium", "low", "info"];
    var by = {};
    findings.forEach(function (f) {
      var k = SEV[f.severity] ? f.severity : "other";
      (by[k] = by[k] || []).push(f);
    });
    return order
      .concat(["other"])
      .filter(function (k) {
        return by[k];
      })
      .map(function (k) {
        var s = SEV[k] || SEV_NONE;
        var name = k === "other" ? T("其他", "Other") : label("SEVERITY", k);
        var gid = "zr-sg-" + ++uid;
        return (
          '<div class="zr-grp"><h4 class="zr-gh" id="' + gid + '"><span class="badge ' + s.c + '">' + ico(s.g) + " " + esc(name) +
          '</span><span class="n">' + esc(count(by[k].length, ["{n} 项", "{n} finding"], ["{n} 项", "{n} findings"])) + "</span></h4>" +
          '<ul class="zr-list" aria-labelledby="' + gid + '">' + by[k].map(findRow).join("") + "</ul></div>"
        );
      })
      .join("");
  }

  // The knowledge-base profile the run audited against, and where it came from
  // (packaged:<file> | kb_dir:<path> | kb.db:entry/<id>).
  function kbMeta(k, code) {
    if (!k.matched) return esc(T("无匹配资料", "No matching profile"));
    var src = String(k.model_source || "");
    var from = src.indexOf("kb.db:entry/") === 0
      ? Tf("你的条目 #{id}", "your entry #{id}", { id: src.slice(12) })
      : src.indexOf("kb_dir:") === 0
        ? "ZING_KB_DIR"
        : T("内置", "Packaged");
    var parts = [from];
    if (k.pinned) parts.push(T("监控固定", "pinned by the monitor"));
    if (k.user_kb === false) parts.push(T("未使用你的条目", "your entries left out"));
    return code(k.provider + "/" + k.model_id) + " · " + esc(parts.join(" · ")) +
      (k.profile_hash ? ' <span class="sr-only">' + esc(k.profile_hash) + "</span>" : "");
  }

  function html(r, opts) {
    var v = r.verdict || {};
    var risk = RISK[v.risk_level] || RISK.inconclusive;
    var riskKey = RISK[v.risk_level] ? v.risk_level : "inconclusive";
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
      return (SEV[b.severity] || SEV_NONE).r - (SEV[a.severity] || SEV_NONE).r;
    });
    var code = function (s) {
      return "<code>" + esc(s) + "</code>";
    };
    var item = function (k, val) {
      return '<div class="mi"><dt>' + esc(k) + "</dt><dd>" + val + "</dd></div>";
    };
    var meta = [
      item(T("目标", "Target"), code(t.base_url || "—")),
      item(T("声称的模型", "Claimed model"), code(t.claimed_model || t.model || "—")),
    ];
    if (t.claimed_model && t.model && t.claimed_model !== t.model) meta.push(item(T("请求的模型", "Model to request"), code(t.model)));
    if (r.baseline)
      meta.push(item(T("对照基线", "Baseline"), code(r.baseline.model || "—") + " @ " + code(r.baseline.base_url || "—")));
    meta.push(item(T("模式", "Mode"), code(r.mode || "check")));
    if (r.suite) meta.push(item(T("套件", "Suite"), code(r.suite)));
    if ((r.prompt_languages || []).length)
      meta.push(item(T("探测语言", "Probe languages"), esc(r.prompt_languages.map(langName).join(" · "))));
    if (r.knowledge) meta.push(item(T("知识库资料", "Knowledge profile"), kbMeta(r.knowledge, code)));
    if (r.generated_at) {
      var dt = new Date(r.generated_at);
      if (!isNaN(dt))
        meta.push(item(T("时间", "Time"), esc(dt.toLocaleString(locale(), { dateStyle: "medium", timeStyle: "short" }))));
    }
    meta.push(item(T("版本", "Version"), code("zing v" + (r.tool_version || "?"))));

    var actions = (opts.actions || [])
      .map(function (a, i) {
        return '<button type="button" class="btn' + (a.primary ? " pri" : "") + '" data-action="' + i + '">' + esc(T(a.zh, a.en)) + "</button>";
      })
      .join("");

    var rest = srv(summaryRest(v.summary));
    var hid = "zr-h-" + ++uid;
    var scoreTxt = sc == null || !isFinite(sc) ? "—" : num(sc, 1);

    return (
      '<article class="zr card ' + risk.c + '" aria-labelledby="' + hid + '">' +
      '<div class="ribbon" aria-hidden="true"></div>' +
      '<div class="vhero"><div class="grade" aria-hidden="true">' + esc(v.rating || "–") + "</div>" +
      '<div class="vmeta"><span class="badge ' + risk.c + ' vpill">' + ico(risk.g) + " " + esc(label("RISK_LEVEL", riskKey)) + "</span>" +
      '<h2 id="' + hid + '">' + esc(head(v)) + "</h2>" +
      (rest ? '<p class="sum">' + esc(rest) + "</p>" : "") +
      '<div class="vscores"><div>' + esc(T("综合健康分", "Overall health score")) + ' <b class="' + scoreC(sc) + '">' + esc(scoreTxt) + "</b>/100" +
      (v.rating ? ' <span class="sr-only">(' + esc(Tf("评级 {r}", "Rating {r}", { r: v.rating })) + ")</span>" : "") + "</div>" +
      "<div>" + esc(T("结论置信度", "Verdict confidence")) + " <b>" + esc(v.confidence ? label("CONFIDENCE", v.confidence) : "—") + "</b></div></div>" +
      "</div></div>" +
      '<dl class="meta-strip">' + meta.join("") + "</dl>" +
      '<section class="sect"><h3>' + esc(T("逐项体检", "Per-dimension checks")) +
      ' <span class="count">' + esc(count(dims.length, ["{n} 个维度", "{n} dimension"], ["{n} 个维度", "{n} dimensions"])) + "</span></h3>" +
      dims.map(dimRow).join("") + "</section>" +
      '<section class="sect"><h3>' + esc(T("关注点", "Findings")) +
      (findings.length
        ? ' <span class="count">' + esc(count(findings.length, ["{n} 项", "{n} finding"], ["{n} 项", "{n} findings"])) + "</span>"
        : "") +
      "</h3>" +
      (findings.length
        ? findingGroups(findings)
        : '<p class="none">' +
          esc(T("未发现警告或失败项 —— 各维度表现与所声称模型一致。", "No warnings or failures — every dimension is consistent with the claimed model.")) +
          "</p>") +
      "</section>" +
      (r.performance && window.ZingPerf
        ? '<section class="sect perf-sect"><h3>' + esc(T("性能", "Performance")) + "</h3>" + window.ZingPerf.section(r.performance) + "</section>"
        : "") +
      '<footer class="zr-foot"><p class="disc">' +
      T(
        "zing 出具的是<strong>行为偏离与风险的可复现证据</strong>，不是欺诈的法律/密码学证明。中转站可能按概率路由；请结合样本量、计费设置与当地法律自行判断，切勿仅凭单次结果公开指控厂商。",
        "zing provides <strong>reproducible evidence of behavioral deviation and risk</strong>, not legal or cryptographic proof of fraud. Relays may route probabilistically; weigh sample size, billing settings and local law yourself, and never publicly accuse a vendor based on a single run."
      ) +
      "</p>" +
      (actions ? '<div class="actions">' + actions + "</div>" : "") +
      "</footer></article>"
    );
  }

  function wire(el) {
    var st = el.__zingReport || {};
    var bars = el.querySelectorAll(".zr-dim .bar i");
    var fill = function () {
      for (var i = 0; i < bars.length; i++) bars[i].style.width = bars[i].getAttribute("data-w") + "%";
    };
    // animate the bars on first show only; a language re-render keeps them still
    if (st.still || typeof requestAnimationFrame !== "function") fill();
    else requestAnimationFrame(fill);
    var more = el.querySelectorAll(".zr-find .more");
    for (var j = 0; j < more.length; j++)
      more[j].onclick = function () {
        var btn = this,
          ev = document.getElementById(btn.getAttribute("aria-controls"));
        if (!ev) return;
        var open = ev.hidden;
        ev.hidden = !open;
        btn.setAttribute("aria-expanded", String(open));
        btn.textContent = showEvidence(open);
      };
    var acts = el.querySelectorAll("[data-action]");
    for (var k = 0; k < acts.length; k++)
      acts[k].onclick = function () {
        var a = ((st.opts || {}).actions || [])[+this.getAttribute("data-action")];
        if (a && a.onClick) a.onClick(st.report);
      };
    var perf = el.querySelector(".perf-sect");
    if (perf && window.ZingPerf && st.report && st.report.performance) window.ZingPerf.wireSection(perf, st.report.performance);
  }

  function mount(el, report, opts, still) {
    opts = opts || {};
    el.__zingReport = { report: report, opts: opts, still: !!still };
    el.innerHTML = html(report || {}, opts);
    wire(el);
  }
  function render(el, report, opts) {
    mount(el, report, opts, false);
  }

  // Re-render every mounted report in the new language, keeping open evidence
  // and the focused control.
  window.addEventListener("zing:lang", function () {
    var els = document.querySelectorAll(".zr");
    for (var i = 0; i < els.length; i++) {
      var host = els[i].parentNode;
      var st = host && host.__zingReport;
      if (!st) continue;
      var open = [].map.call(host.querySelectorAll(".zr-find .ev"), function (e) {
        return !e.hidden;
      });
      var btns = host.querySelectorAll("button");
      var focused = [].indexOf.call(btns, document.activeElement);
      mount(host, st.report, st.opts, true);
      [].forEach.call(host.querySelectorAll(".zr-find .ev"), function (e, n) {
        if (!open[n]) return;
        e.hidden = false;
        var b = host.querySelector('[aria-controls="' + e.id + '"]');
        if (b) {
          b.setAttribute("aria-expanded", "true");
          b.textContent = showEvidence(true);
        }
      });
      if (focused >= 0) {
        var nb = host.querySelectorAll("button")[focused];
        if (nb) nb.focus();
      }
    }
  });

  window.ZingReport = { render: render, wire: wire };
})();
