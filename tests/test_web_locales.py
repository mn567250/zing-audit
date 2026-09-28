"""Completeness of the web UI translations and of the downloaded report.

Evaluates the UI's plain-browser JS (zing/web/static) under node, so it is
skipped when node isn't installed. Adding a language to LANG_LIST in lang.js
without a full zing/i18n/locales/<code>.json fails here, and so does a
downloaded report that changes the JSON schema or leaves text untranslated.
"""

from __future__ import annotations

import ast
import json
import re
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
  if (!s || !f) { problems.push(c + ": no zing/i18n/locales/" + c + ".json"); continue; }
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


def _ui_js(tmp_path: Path) -> Path:
    """The UI's i18n scripts as the browser gets them (/locales.js carries the
    JSON data from zing/i18n/locales/ in front of the lookup logic)."""
    from zing.i18n import locales_script

    static = Path(__file__).resolve().parent.parent / "zing" / "web" / "static"
    (tmp_path / "locales.js").write_text(locales_script(), encoding="utf-8")
    for name in ("lang.js", "i18n.js"):
        shutil.copy(static / name, tmp_path / name)
    return tmp_path


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_every_ui_language_is_complete(tmp_path):
    # Every language in lang.js's LANG_LIST (besides EN, the key language, and
    # CN, the original markup) must translate every UI string and finding,
    # keeping placeholders and inline markup intact.
    out = subprocess.run(
        ["node", "-e", _LOCALE_CHECK_JS, str(_ui_js(tmp_path))],
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
// A published scoring scale: its outcome labels are fixed backend sentences.
report.detectors[0].scoring = { method: "mean_of_checks", outcomes: [
  { check: "protocol.stop", outcome: "ignored", score: 60, status: "warn", severity: "low",
    label: "Text after the stop sequence was returned." },
  { check: "protocol.stop", outcome: "no_content", score: null, status: "inconclusive", severity: "low",
    label: "No usable response to judge by." }] };
// The performance section's notes are fixed backend sentences.
report.performance = { source: "passive", notes: [
  "Local token counts are estimates (about ±15-20%): no exact tokenizer is available for this model family.",
  "Some requests were served fully or partly from a cache and are left out of the statistics."] };
const TEXT = /^(verdict\.(headline|summary|key_findings\.\d+)|dimensions\.\d+\.reason|(performance\.)?notes\.\d+|(baseline_)?detectors\.\d+\.(name|findings\.\d+\.(title|summary|recommendation)|scoring\.(outcomes\.\d+\.label|titles\..+)))$/;
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
def test_downloaded_report_is_translated_with_english_keys(tmp_path):
    # The web UI's "Download report (JSON)" exports this: same keys, enums,
    # ids and evidence as the server's report; human-readable values in the
    # selected language; and still a valid zing AuditReport.
    from zing.models import AuditReport

    here = Path(__file__).resolve().parent
    out = subprocess.run(
        ["node", "-e", _EXPORT_JS, str(_ui_js(tmp_path)), str(here / "fixtures" / "web_report.json")],
        capture_output=True, text=True, check=True,
    ).stdout
    result = json.loads(out)
    assert set(result) == {"en", "zh", "fr", "es", "pt", "it", "de"}
    for lang, res in result.items():
        assert res["problems"] == [], lang
        AuditReport.model_validate(res["report"])


def test_locale_fragments_extend_every_language(tmp_path, monkeypatch):
    # zing/i18n/locales/fragments/<feature>/<code>.json adds strings to a
    # language; an en fragment extends the canonical key list.
    import zing.i18n as i18n

    base = Path(i18n.__file__).resolve().parent / "locales"
    for f in base.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    frag = tmp_path / "fragments" / "demo"
    frag.mkdir(parents=True)
    (frag / "en.json").write_text(json.dumps({"strings": {"Hello v2": "Hello v2"}}), encoding="utf-8")
    (frag / "de.json").write_text(json.dumps({"strings": {"Hello v2": "Hallo v2"}}), encoding="utf-8")
    monkeypatch.setattr(i18n, "_DIR", tmp_path)
    i18n._load.cache_clear()
    try:
        assert i18n.ui("de", "Hello v2") == "Hallo v2"
        assert "Hello v2" in i18n.bundle()["locales"]["en"]["strings"]
        assert i18n.ui("de", "History") == i18n._load()["de"]["strings"]["History"]  # base kept
        (frag / "xx.json").write_text("{}", encoding="utf-8")
        i18n._load.cache_clear()
        with pytest.raises(ValueError):
            i18n._load()
    finally:
        i18n._load.cache_clear()


def _backend_sentences() -> list[str]:
    """Fixed English sentences the backend puts in a report: detector names,
    recommendations, scoring-scale labels, verdict headlines, report notes and
    performance notes."""
    root = Path(__file__).resolve().parent.parent / "zing"
    out: list[str] = []

    def lit(node: ast.AST) -> str | None:
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            # recommendation="…" wherever a finding is built; label="…" of a
            # scoring-scale outcome
            if isinstance(node, ast.keyword) and node.arg in ("recommendation", "label"):
                # a literal, or either literal branch of `"…" if cond else None`
                values = [node.value.body, node.value.orelse] if isinstance(node.value, ast.IfExp) else [node.value]
                out += [s for s in map(lit, values) if s]
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                continue
            target = node.targets[0].id
            if rel.startswith("detectors/") and target == "name" and lit(node.value):
                out.append(lit(node.value))  # a detector's display name
            if rel.startswith("detectors/") and target == "_NO_RESPONSE" and lit(node.value):
                out.append(lit(node.value))  # a shared scoring-scale label
            if rel == "perf/summary.py" and target.startswith("NOTE_") and lit(node.value):
                out.append(lit(node.value))  # performance notes
            if rel == "runner.py" and target == "notes" and isinstance(node.value, ast.List):
                out += [s for s in map(lit, node.value.elts) if s]  # report notes
            if rel == "scoring.py" and target == "table" and isinstance(node.value, ast.Dict):
                out += [s for s in map(lit, node.value.values) if s]  # verdict headlines
    return sorted(set(out))


def test_zh_translates_every_backend_sentence():
    # The UI shows backend text translated in CN too (ZING_LANG.server), so
    # zh.json must carry every fixed backend sentence.
    from zing import i18n

    sentences = _backend_sentences()
    assert len(sentences) > 40
    assert [s for s in sentences if i18n.backend("zh", s) == s] == []


_SERVER_ZH_JS = r"""
const path = require("path"), fs = require("fs");
const dir = process.argv[1], report = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
global.window = {};
global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete",
                    querySelectorAll: () => [], addEventListener() {} };
global.localStorage = { getItem: () => "zh", setItem() {} };
for (const m of ["locales.js", "lang.js"]) require(path.join(dir, m));
const texts = [report.verdict.headline, report.verdict.summary].concat(JSON.parse(process.argv[3]));
for (const k of ["detectors", "baseline_detectors"])
  for (const d of report[k] || []) {
    texts.push(d.name);
    for (const f of d.findings || []) if (f.recommendation) texts.push(f.recommendation);
  }
console.log(JSON.stringify(texts.map(t => [t, window.ZING_LANG.server(t)])));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_server_text_is_chinese_in_zh(tmp_path):
    # Recommendations, detector names and the verdict headline/summary come
    # from the backend in English; in CN the UI must show them in Chinese.
    here = Path(__file__).resolve().parent
    fixture = here / "fixtures" / "web_report.json"
    extra = _backend_sentences()
    out = subprocess.run(
        ["node", "-e", _SERVER_ZH_JS, str(_ui_js(tmp_path)), str(fixture), json.dumps(extra)],
        capture_output=True, text=True, check=True,
    ).stdout
    pairs = json.loads(out)
    cjk = re.compile(r"[㐀-鿿]")
    assert [en for en, zh in pairs if not cjk.search(zh or "")] == []
    summary = dict(pairs)[json.loads(fixture.read_text(encoding="utf-8"))["verdict"]["summary"]]
    # Chinese sentences are joined without spaces; no English sentence is left.
    assert "。 " not in summary and "Findings" not in summary and "health score" not in summary


def test_language_labels_are_endonyms():
    # The switcher names languages, not countries (no flags).
    from zing import i18n

    labels = {m["code"]: m["label"] for m in i18n.languages()}
    assert labels == {
        "en": "English", "zh": "中文", "fr": "Français", "es": "Español",
        "pt": "Português", "it": "Italiano", "de": "Deutsch",
    }
    assert i18n.codes()[:2] == ["en", "zh"]


_VISIBILITY_JS = r"""
const path = require("path");
const dir = process.argv[1];
const run = (lang, fire) => {
  delete require.cache[require.resolve(path.join(dir, "lang.js"))];
  const timers = [], handlers = {}, dcl = [];
  global.setTimeout = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };
  global.clearTimeout = id => { if (timers[id - 1]) timers[id - 1].fn = null; };
  global.window = {
    ZING_LOCALES: { languages: [{ code: "en", label: "English", html: "en", locale: "en-US" },
                                { code: "zh", label: "中文", html: "zh-CN", locale: "zh-CN" },
                                { code: "fr", label: "Français", html: "fr", locale: "fr-FR" }] },
    addEventListener(t, fn) { handlers[t] = fn; },
    removeEventListener(t, fn) { if (handlers[t] === fn) delete handlers[t]; },
  };
  // The document is still "loading"; lang.js's own boot (the last
  // DOMContentLoaded listener) is never called, as if it had failed.
  global.document = { documentElement: { style: {}, lang: "" }, readyState: "loading",
                      querySelectorAll: () => [], addEventListener(t, fn) { if (t === "DOMContentLoaded") dcl.push(fn); } };
  global.localStorage = { getItem: () => lang, setItem() {} };
  require(path.join(dir, "lang.js"));
  const st = document.documentElement.style, before = st.visibility || "";
  const fireTimers = () => timers.slice().forEach(t => t.fn && t.fn());
  if (fire === "cap") fireTimers();
  if (fire === "parsed") { document.readyState = "interactive"; dcl.slice(0, -1).forEach(f => f()); }
  const mid = st.visibility || "";
  if (fire === "parsed") fireTimers();
  if (fire === "error-loading") handlers.error({});
  if (fire === "error-parsed") { document.readyState = "interactive"; handlers.error({}); }
  return { before, mid, after: st.visibility || "", delays: timers.map(t => t.ms) };
};
const r = {};
for (const f of ["cap", "parsed", "error-loading", "error-parsed"]) r[f] = run("fr", f);
r.zh = run("zh", "none");
console.log(JSON.stringify(r));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_hidden_page_is_revealed_if_boot_never_runs(tmp_path):
    # lang.js hides the page until the markup is translated; if boot never
    # runs (e.g. a later script throws), a timer or the first error reveals it.
    static = Path(__file__).resolve().parent.parent / "zing" / "web" / "static"
    shutil.copy(static / "lang.js", tmp_path / "lang.js")
    out = subprocess.run(
        ["node", "-e", _VISIBILITY_JS, str(tmp_path)], capture_output=True, text=True, check=True,
    ).stdout
    r = json.loads(out)
    for case in ("cap", "parsed", "error-loading", "error-parsed"):
        assert r[case]["before"] == "hidden", case
    # A cap reveals the page even if DOMContentLoaded never fires …
    assert r["cap"]["after"] == "" and max(r["cap"]["delays"]) <= 10000
    # … and ~1.5 s after the HTML is parsed if boot didn't reveal it.
    assert r["parsed"]["mid"] == "hidden" and r["parsed"]["after"] == ""
    assert 1000 <= min(r["parsed"]["delays"]) <= 2000
    # A script error reveals it at once, but not while the HTML is still
    # loading (boot is still to come; revealing would flash the Chinese).
    assert r["error-loading"]["after"] == "hidden"
    assert r["error-parsed"]["after"] == ""
    assert r["zh"]["before"] == "" and r["zh"]["delays"] == []  # CN is the markup itself
