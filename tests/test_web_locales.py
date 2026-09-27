"""Completeness of the web UI translations and of the downloaded report.

Evaluates the UI's plain-browser JS (zing/web/static) under node, so it is
skipped when node isn't installed. Adding a language to LANG_LIST in lang.js
without a full translation block in locales.js fails here, and so does a
downloaded report that changes the JSON schema or leaves text untranslated.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_LOCALE_CHECK_JS = r"""
const path = require("path");
const dir = process.argv[1];
global.window = {};
global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete",
                    querySelectorAll: () => [], addEventListener() {} };
global.localStorage = { getItem: () => null, setItem() {} };
require(path.join(dir, "locales.js"));
require(path.join(dir, "lang.js"));
require(path.join(dir, "i18n.js"));
const L = window.ZING_LOCALES, zh = window.ZING_I18N.FINDINGS;
const ph = s => (String(s).match(/\{\w+(?:\|\w+)?\}/g) || []).sort().join(",");
const tags = s => (String(s).match(/<\/?[a-z]+/gi) || []).sort().join(",");
const problems = [];
const codes = window.ZING_LANG.langs().map(l => l.code).filter(c => c !== "en" && c !== "zh");
for (const c of codes) {
  const s = L.strings[c], f = L.findings[c];
  if (!s || !f) { problems.push(c + ": not registered in locales.js"); continue; }
  for (const k of L.keys.strings) {
    if (!(k in s)) problems.push(c + ": missing string " + JSON.stringify(k));
    else if (ph(k) !== ph(s[k]) || tags(k) !== tags(s[k]))
      problems.push(c + ": placeholder/markup mismatch in " + JSON.stringify(k));
  }
  for (const id of L.keys.findings) {
    const e = f[id], src = id === "model_identity.fp.*" ? "{probe}" : (zh[id] || {}).tpl;
    if (!e || !e.title || !e.tpl) problems.push(c + ": missing finding " + id);
    else if (ph(src) !== ph(e.tpl)) problems.push(c + ": placeholder mismatch in finding " + id);
  }
}
for (const id of Object.keys(zh)) if (!L.keys.findings.includes(id)) problems.push("finding not translatable: " + id);
// Branch/generic summary templates are English keys every language, CN
// included, must translate (CN has no other use for the dictionary).
for (const t of window.ZING_I18N.TEMPLATES)
  for (const c of codes.concat(["zh"])) {
    const d = L.strings[c] || {};
    if (!(t in d)) problems.push(c + ": missing template " + JSON.stringify(t));
    else if (ph(t) !== ph(d[t])) problems.push(c + ": placeholder mismatch in template " + JSON.stringify(t));
  }
console.log(JSON.stringify({ codes, problems }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_every_ui_language_is_complete():
    # Every language in lang.js's LANG_LIST (besides EN, the key language, and
    # CN, the original markup) must translate every UI string and finding,
    # keeping placeholders and inline markup intact.
    static = Path(__file__).resolve().parent.parent / "zing" / "web" / "static"
    out = subprocess.run(
        ["node", "-e", _LOCALE_CHECK_JS, str(static)],
        capture_output=True, text=True, check=True,
    ).stdout
    result = json.loads(out)
    assert {"fr", "es", "pt", "it", "de"} <= set(result["codes"])
    assert result["problems"] == []


_EXPORT_JS = r"""
const path = require("path"), fs = require("fs");
const dir = process.argv[1], report = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
// Extra findings for detector branches the fixture run didn't hit.
const f = (id, status, evidence, title, summary) => ({ id, title, status, severity: "low", summary, evidence, recommendation: null });
report.detectors[0].findings.push(
  f("model_identity.self_id", "pass", { prompt: "self-id", target_answer: "I am GPT-4o." }, "Self-identification consistent", "Self-id mentions genuine brand words for gpt-4o."),
  f("model_identity.self_id", "warn", { prompt: "self-id", target_answer: "I am GPT, not Claude.", forbidden_hits: ["claude"] }, "Self-id names both the genuine and a rival brand", "Self-id mentions genuine brand words for gpt-4o but also a rival brand (claude)."),
  f("model_identity.self_id", "warn", { prompt: "self-id", target_answer: "I am an assistant." }, "Evasive self-identification", "Self-id response names neither the genuine brand nor a rival; treat as weak/evasive evidence."),
  f("security.headers", "pass", { header_count: 7 }, "No revealing headers", "Inspected 7 response headers; none expose upstream identity."),
  f("connectivity.chat", "fail", { status_code: 502, error_type: "upstream_error" }, "Basic chat failed", "Bad gateway."),
  f("embed.dimension", "info", { returned: 1536, claimed: 0 }, "Claimed dimension unknown", "No KB dimension for the claimed model; observed 1536-d."));
const TEXT = /^(verdict\.(headline|summary|key_findings\.\d+)|dimensions\.\d+\.reason|notes\.\d+|(baseline_)?detectors\.\d+\.(name|findings\.\d+\.(title|summary|recommendation)))$/;
const CJK = /[\u3400-\u9fff]/;
const flat = (o, p, out) => { if (o && typeof o === "object") for (const k of Object.keys(o)) flat(o[k], p ? p + "." + k : k, out); else out[p] = o; return out; };
const result = {};
for (const lang of ["en", "zh", "fr", "es", "pt", "it", "de"]) {
  for (const m of ["locales.js", "lang.js", "i18n.js"]) delete require.cache[require.resolve(path.join(dir, m))];
  global.window = {};
  global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete", querySelectorAll: () => [], addEventListener() {} };
  global.localStorage = { getItem: () => lang, setItem() {} };
  for (const m of ["locales.js", "lang.js", "i18n.js"]) require(path.join(dir, m));
  const ex = window.ZING_I18N.exportReport(report), a = flat(report, "", {}), b = flat(ex, "", {});
  const problems = [];
  const ka = Object.keys(a).sort().join("\n"), kb = Object.keys(b).sort().join("\n");
  if (ka !== kb) problems.push("JSON keys differ");
  for (const k of Object.keys(a)) {
    if (!TEXT.test(k)) { if (a[k] !== b[k]) problems.push("non-text value changed: " + k); continue; }
    if (typeof a[k] !== "string" || !a[k]) continue;
    if (lang !== "en" && a[k] === b[k]) problems.push("untranslated: " + k + " = " + a[k]);
    if (lang === "zh" && !CJK.test(b[k])) problems.push("no Chinese in: " + k + " = " + b[k]);
    if (lang !== "zh" && CJK.test(b[k])) problems.push("Chinese left in: " + k + " = " + b[k]);
  }
  result[lang] = { problems, report: ex };
}
console.log(JSON.stringify(result));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_downloaded_report_is_translated_with_english_keys():
    # The web UI's "Download report (JSON)" exports this: same keys, enums,
    # ids and evidence as the server's report; human-readable values in the
    # selected language; and still a valid zing AuditReport.
    from zing.models import AuditReport

    here = Path(__file__).resolve().parent
    static = here.parent / "zing" / "web" / "static"
    out = subprocess.run(
        ["node", "-e", _EXPORT_JS, str(static), str(here / "fixtures" / "web_report.json")],
        capture_output=True, text=True, check=True,
    ).stdout
    result = json.loads(out)
    assert set(result) == {"en", "zh", "fr", "es", "pt", "it", "de"}
    for lang, res in result.items():
        assert res["problems"] == [], lang
        AuditReport.model_validate(res["report"])
