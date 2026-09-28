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
 *     the UI language changes (expanded dimensions, evidence and keyboard focus
 *     are kept).
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
  // a check's own status -> colour + glyph (the dimension details list passed
  // checks too, so these read by outcome, not by severity)
  var STATG = {
    pass: { c: "good", g: "check" },
    info: { c: "sky", g: "info" },
    warn: { c: "warn", g: "warning" },
    fail: { c: "bad", g: "x" },
    error: { c: "bad", g: "x" },
    inconclusive: { c: "grey", g: "info" },
  };
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

  function dimRow(d, r) {
    var n = dimName(d.dimension) || [d.dimension, ""];
    var c = STATC[d.status] || scoreC(d.score);
    var hasScore = d.score != null && isFinite(d.score);
    var v = hasScore ? Math.max(0, Math.min(100, Math.round(d.score))) : null;
    var st = label("STATUS", d.status);
    var id = "zr-dn-" + ++uid;
    var did = "zr-dd-" + uid;
    var valText = hasScore
      ? num(v, 0) + "/100 · " + st
      : T("未评分", "Not scored") + " · " + st;
    return (
      '<div class="zr-dimw"><div class="zr-dim"><div class="nm" id="' + id + '">' +
      '<button type="button" class="dtog" aria-expanded="false" aria-controls="' + did + '">' +
      '<span class="chev" aria-hidden="true">' + ico("chevronDown") + "</span>" + esc(n[0]) + "</button>" +
      "<small>" + esc(n[1]) + "</small></div>" +
      (hasScore
        ? '<div class="bar" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + v +
          '" aria-valuetext="' + esc(valText) + '" aria-labelledby="' + id + '"><i data-w="' + v + '" class="' + c + '"></i></div>'
        : '<div class="bar none"><i data-w="0" class="grey"></i><span class="sr-only">' + esc(valText) + "</span></div>") +
      '<span class="badge ' + c + '" aria-hidden="true">' + (hasScore ? esc(num(v, 0)) : "—") + "</span></div>" +
      '<div class="zr-dd" id="' + did + '" role="region" aria-labelledby="' + id + '" hidden>' + dimDetails(d, r) + "</div></div>"
    );
  }

  // ---- Dimension details: how the score and status came about, and every
  // check behind them (passed ones included). Reads DimensionScore.breakdown
  // and DetectorResult.scoring; reports from before those existed fall back to
  // the dimension's detectors and their findings.
  function pts(p) {
    return p == null ? T("不计分", "Not counted") : Tf("{p} 分", "{p} pts", { p: num(p, 1) });
  }
  function dimDetails(d, r) {
    var members = (r.detectors || []).filter(function (det) {
      return det.dimension === d.dimension;
    });
    var byId = {};
    members.forEach(function (det) {
      byId[det.id] = det;
    });
    var dname = function (i) {
      return byId[i] ? srv(byId[i].name) : i;
    };
    var b = d.breakdown;
    var parts = b
      ? b.detectors.map(function (x) {
          return { id: x.detector, score: x.score, counted: x.counted };
        })
      : members.map(function (det) {
          return { id: det.id, score: det.score, counted: det.score != null };
        });
    var counted = parts.filter(function (x) {
      return x.counted;
    });
    var skipped = parts.filter(function (x) {
      return !x.counted;
    });
    var how = !counted.length
      ? T("没有检测器给出数值分数。", "No detector produced a numeric score.")
      : counted.length === 1
        ? T("得分来自一个检测器。", "Score from one detector.")
        : Tf("得分为 {n} 个检测器的平均值（权重相同）。", "Score: mean of {n} detectors, equal weight.", { n: num(counted.length, 0) });
    if (skipped.length)
      how += " " + Tf("未计入（无数值分数）：{list}。", "Not counted (no numeric score): {list}.", {
        list: skipped.map(function (x) {
          return dname(x.id);
        }).join(", "),
      });
    var o = b && b.status_override;
    var why = o
      ? Tf(
          "状态由 {from} 调整为 {to}，原因是严重程度为「{sev}」的发现：{list}。严重的发现无论分数如何都会拉低该维度。",
          "Status raised from {from} to {to} by findings of severity {sev}: {list}. A serious finding pulls a dimension down whatever its score.",
          {
            from: label("STATUS", o.from_status),
            to: label("STATUS", o.to_status),
            sev: label("SEVERITY", o.severity),
            list: o.findings.map(function (fid) {
              var f = null;
              members.forEach(function (det) {
                (det.findings || []).forEach(function (x) {
                  if (!f && x.id === fid) f = x;
                });
              });
              return f ? loc(f).title : fid;
            }).join(", "),
          }
        )
      : b
        ? T("状态取其检测器得出的最差结论。", "Status: the worst status its detectors concluded.")
        : "";
    return (
      '<p class="how">' + esc(how) + "</p>" +
      (why ? '<p class="how">' + esc(why) + "</p>" : "") +
      members.map(detDetails).join("")
    );
  }
  function detDetails(det) {
    var sc = det.scoring;
    var scale = {}; // check id -> its outcomes, in scale order
    ((sc && sc.outcomes) || []).forEach(function (o) {
      (scale[o.check] = scale[o.check] || []).push(o);
    });
    var hasScore = det.score != null && isFinite(det.score);
    var hid = "zr-dh-" + ++uid;
    // Subjects of one parametrized check (e.g. every response attribute) share
    // one row; everything else is a row of its own.
    var items = [];
    var groups = {};
    (det.findings || []).forEach(function (f) {
      if (!(f.subject && f.check)) return items.push(f);
      if (!groups[f.check]) items.push((groups[f.check] = [f.check]));
      groups[f.check].push(f);
    });
    var rows = items.map(function (x) {
      if (Array.isArray(x)) return groupRow(x[0], x.slice(1), sc, sc ? scale[x[0]] : null);
      return checkRow(x, sc ? pts(x.score) : null, sc ? scale[x.check || x.id] : null);
    });
    return (
      '<div class="zr-det"><h4 class="zr-dh" id="' + hid + '">' + esc(srv(det.name)) +
      ' <span class="badge ' + scoreC(det.score) + '">' +
      esc(hasScore ? Tf("{s} 分", "Score {s}", { s: num(det.score, 1) }) : T("未评分", "Not scored")) + "</span></h4>" +
      (sc && sc.method === "mean_of_checks"
        ? '<p class="how">' + esc(T("检测器得分为计分检查项的平均分。", "Detector score: mean of the counted checks' points.")) + "</p>"
        : "") +
      (rows.length
        ? '<ul class="zr-list" aria-labelledby="' + hid + '">' + rows.join("") + "</ul>"
        : '<p class="how">' + esc(T("没有发现。", "No findings.")) + "</p>") +
      "</div>"
    );
  }
  // One check: its status, what happened, and the points it scored — with
  // an info tip next to the points listing every outcome the check could
  // have had (its published scale), this run's marked.
  function checkRow(f, points, outcomes) {
    var s = STATG[f.status] || SEV_NONE;
    var ev = evText(f.evidence);
    var L = loc(f);
    var id = "zr-ev-" + ++uid;
    return (
      '<li class="zr-find zr-chk"><span class="dot ' + s.c + '" aria-hidden="true">' + ico(s.g) + "</span>" +
      '<div class="body"><div class="ft"><span class="sr-only">' +
      esc(Tf("结果：{s}。", "Result: {s}.", { s: label("STATUS", f.status) })) + " </span>" + esc(L.title) +
      (points != null ? ' <span class="pts">' + esc(points) + "</span>" : "") +
      (outcomes && outcomes.length ? scaleTip(hitsOf([f]), outcomes) : "") + "</div>" +
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
  // outcome -> how often the findings hit it
  function hitsOf(fs) {
    var h = {};
    fs.forEach(function (f) {
      if (f.outcome != null) h[f.outcome] = (h[f.outcome] || 0) + 1;
    });
    return h;
  }
  var STATUS_RANK = { pass: 0, info: 1, inconclusive: 2, warn: 3, error: 4, fail: 5 };
  function worstStatus(fs) {
    return fs.reduce(function (w, f) {
      return (STATUS_RANK[f.status] || 0) > (STATUS_RANK[w] || 0) ? f.status : w;
    }, "pass");
  }
  function observed(f) {
    var e = f.evidence || {};
    if (e.observed != null) return fmt(e.observed);
    if (e.status_code != null) return "HTTP " + e.status_code;
    return "—";
  }
  // One parametrized check: a summary line, its non-passing subjects listed
  // inline (problems are never hidden), and every subject with its outcome
  // and points in a table behind a disclosure — so the mean stays reproducible.
  function groupRow(check, fs, sc, outcomes) {
    var s = STATG[worstStatus(fs)] || SEV_NONE;
    var byKey = {};
    (outcomes || []).forEach(function (o) {
      byKey[o.outcome] = o;
    });
    var what = function (f) {
      var o = byKey[f.outcome];
      return o && o.label ? srv(o.label) : loc(f).summary;
    };
    var title = (sc && sc.titles && sc.titles[check]) || check;
    var ok = fs.filter(function (f) {
      return f.status === "pass";
    });
    var counted = fs.filter(function (f) {
      return f.score != null;
    });
    var mean = counted.length
      ? counted.reduce(function (a, f) {
          return a + f.score;
        }, 0) / counted.length
      : null;
    var bad = fs.filter(function (f) {
      return f.status !== "pass";
    });
    var id = "zr-ga-" + ++uid;
    var subDot = function (f) {
      var g = STATG[f.status] || SEV_NONE;
      return '<span class="dot sm ' + g.c + '" aria-hidden="true">' + ico(g.g) + "</span>" +
        '<span class="sr-only">' + esc(label("STATUS", f.status)) + " </span>";
    };
    var showAll = Tf("显示全部 {n} 项", "Show all {n}", { n: num(fs.length, 0) });
    return (
      '<li class="zr-find zr-chk zr-grp"><span class="dot ' + s.c + '" aria-hidden="true">' + ico(s.g) + "</span>" +
      '<div class="body"><div class="ft"><span class="sr-only">' +
      esc(Tf("结果：{s}。", "Result: {s}.", { s: label("STATUS", worstStatus(fs)) })) + " </span>" + esc(srv(title)) +
      (sc && mean != null ? ' <span class="pts">' + esc(Tf("平均 {p} 分", "avg {p} pts", { p: num(mean, 1) })) + "</span>" : "") +
      (outcomes && outcomes.length ? scaleTip(hitsOf(fs), outcomes) : "") + "</div>" +
      '<div class="fs">' + esc(Tf("{ok}/{n} 项正常", "{ok} of {n} OK", { ok: num(ok.length, 0), n: num(fs.length, 0) })) + "</div>" +
      (bad.length
        ? '<ul class="zr-sub">' +
          bad.map(function (f) {
            return "<li>" + subDot(f) + "<code>" + esc(f.subject) + "</code> — " + esc(what(f)) +
              (sc ? ' <span class="pts">' + esc(pts(f.score)) + "</span>" : "") + "</li>";
          }).join("") + "</ul>"
        : "") +
      '<button type="button" class="linkbtn more" aria-expanded="false" aria-controls="' + id + '" data-l0="' +
      esc(showAll) + '" data-l1="' + esc(T("收起", "Show fewer")) + '">' + esc(showAll) + "</button>" +
      '<div class="zr-at" id="' + id + '" hidden><table><thead><tr>' +
      "<th>" + esc(T("属性", "Attribute")) + "</th><th>" + esc(T("实际值", "Observed")) + "</th><th>" +
      esc(T("结果", "Result")) + '</th><th class="num">' + esc(T("分数", "Points")) + "</th></tr></thead><tbody>" +
      fs.map(function (f) {
        return "<tr><td>" + subDot(f) + "<code>" + esc(f.subject) + "</code></td><td><code>" + esc(observed(f)) +
          "</code></td><td>" + esc(what(f)) + '</td><td class="num">' + esc(sc ? pts(f.score) : "—") + "</td></tr>";
      }).join("") +
      "</tbody></table></div></div></li>"
    );
  }
  // Toggletip: shown on hover/focus, pinned open by a click (touch). ``hits``
  // marks the outcomes this run had (with a count when several subjects did).
  function scaleTip(hits, outcomes) {
    var id = "zr-tip-" + ++uid;
    return (
      '<span class="zr-tip"><button type="button" class="tipb" aria-expanded="false" aria-describedby="' + id + '" aria-label="' +
      esc(T("计分标准", "Scoring scale")) + '">' + ico("info") + "</button>" +
      '<span class="bubble" role="tooltip" id="' + id + '">' +
      outcomes.map(function (o) {
        var n = hits[o.outcome] || 0;
        var badge = n > 1 ? Tf("本次结果 ×{n}", "This run ×{n}", { n: num(n, 0) }) : T("本次结果", "This run");
        return (
          '<span class="row' + (n ? " hit" : "") + '"><span class="p">' + esc(pts(o.score)) + "</span><span>" + esc(srv(o.label)) +
          (n ? ' <span class="badge sky">' + esc(badge) + "</span>" : "") + "</span></span>"
        );
      }).join("") +
      "</span></span>"
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
      dims.map(function (d) {
        return dimRow(d, r);
      }).join("") + "</section>" +
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
    // disclosure buttons: evidence, dimension details
    var toggles = el.querySelectorAll(TOGGLES);
    for (var j = 0; j < toggles.length; j++)
      toggles[j].onclick = function () {
        toggle(this, null);
      };
    var tips = el.querySelectorAll(".zr-tip .tipb");
    for (var t = 0; t < tips.length; t++) {
      tips[t].onclick = function () {
        this.setAttribute("aria-expanded", String(this.getAttribute("aria-expanded") !== "true"));
      };
      tips[t].onkeydown = function (e) {
        if (e.key === "Escape") this.setAttribute("aria-expanded", "false");
      };
      tips[t].onblur = function () {
        this.setAttribute("aria-expanded", "false");
      };
    }
    var acts = el.querySelectorAll("[data-action]");
    for (var k = 0; k < acts.length; k++)
      acts[k].onclick = function () {
        var a = ((st.opts || {}).actions || [])[+this.getAttribute("data-action")];
        if (a && a.onClick) a.onClick(st.report);
      };
    var perf = el.querySelector(".perf-sect");
    if (perf && window.ZingPerf && st.report && st.report.performance) window.ZingPerf.wireSection(perf, st.report.performance);
  }

  var TOGGLES = ".zr-find .more, .zr-dim .dtog";
  // Open/close the panel a disclosure button controls (open: null = flip).
  function toggle(btn, open) {
    var panel = document.getElementById(btn.getAttribute("aria-controls"));
    if (!panel) return;
    if (open == null) open = panel.hidden;
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    if (btn.hasAttribute("data-l0")) btn.textContent = btn.getAttribute(open ? "data-l1" : "data-l0");
    else if (/\bmore\b/.test(btn.className)) btn.textContent = showEvidence(open);
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

  // Re-render every mounted report in the new language, keeping open panels
  // (evidence, dimension details) and the focused control.
  window.addEventListener("zing:lang", function () {
    var els = document.querySelectorAll(".zr");
    for (var i = 0; i < els.length; i++) {
      var host = els[i].parentNode;
      var st = host && host.__zingReport;
      if (!st) continue;
      var open = [].map.call(host.querySelectorAll(TOGGLES), function (b) {
        return b.getAttribute("aria-expanded") === "true";
      });
      var btns = host.querySelectorAll("button");
      var focused = [].indexOf.call(btns, document.activeElement);
      mount(host, st.report, st.opts, true);
      [].forEach.call(host.querySelectorAll(TOGGLES), function (b, n) {
        if (open[n]) toggle(b, true);
      });
      if (focused >= 0) {
        var nb = host.querySelectorAll("button")[focused];
        if (nb) nb.focus();
      }
    }
  });

  window.ZingReport = { render: render, wire: wire };
})();
