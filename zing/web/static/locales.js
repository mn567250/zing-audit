/* zing web UI — translation lookups for every language but EN.
 *
 * The translations themselves are data: zing/i18n/locales/<code>.json, shared
 * with the Python side (webhook alerts). The server serves /locales.js as
 * `window.ZING_I18N_DATA = {languages, locales}` followed by this file, so
 * the data is in place before the code below runs. Load it before /lang.js.
 *
 * Exposes window.ZING_LOCALES = { strings, findings, patterns, add, keys, languages }:
 *   - strings[lang][english]   UI text; the English string (a `data-en`
 *                              attribute or the 2nd argument of T(zh, en)) is
 *                              the key. Missing keys fall back to English.
 *   - findings[lang][id]       { title, tpl } per audit finding, same
 *                              placeholder rules as i18n.js ("zh" is the
 *                              original Chinese catalog).
 *   - patterns                 [regex, english template, {group: fn}] used by
 *                              ZING_LANG.server() to translate known backend
 *                              sentences (verdict summary and headline).
 *   - add(code, strings, findings)   register a language at runtime.
 *   - keys                     { strings: every translatable English string,
 *                                findings: every finding id }.
 *   - languages                [{ code, label, html, locale, order }] in menu order.
 *
 * Adding a language: add zing/i18n/locales/<code>.json (copy de.json).
 */
(function () {
  "use strict";

  var DATA = window.ZING_I18N_DATA || { languages: [], locales: {} };

  function esc(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  // Sentences of the backend verdict summary (zing/scoring.py::_summary).
  var P = [
    ["Overall health score ([\\d.]+)/100\\.", "Overall health score {1}/100."],
    [
      "Findings: ((?:\\d+ (?:critical|high|medium)(?:, )?)+)\\.",
      "Findings: {1}.",
      {
        1: function (g, tr) {
          // "4 high, 5 medium": translate the words and the list separator
          return g
            .split(", ")
            .map(function (part) {
              return part.replace(/\b(critical|high|medium)\b/g, function (w) {
                return tr(w);
              });
            })
            .join(tr(", "));
        },
      },
    ],
  ];
  P.push([
    "\\(confidence: (low|medium|high)\\)",
    "(confidence: {1})",
    {
      1: function (g, tr) {
        return tr(g.charAt(0).toUpperCase() + g.slice(1)).toLowerCase();
      },
    },
  ]);
  [
    "Behavior is consistent with the claimed model.",
    "Mostly consistent with the claimed model; minor concerns.",
    "Some behavior diverges from the claimed model — investigate.",
    "Strong evidence the relay does not deliver the claimed model as advertised.",
    "Not enough signal to judge — connectivity or coverage was insufficient.",
    "No significant divergence findings.",
    "The claimed model was not found in the knowledge base, so identity/capability checks are limited — pass --declared-provider or add a KB profile.",
    "Run `zing compare` against a trusted baseline to strengthen the verdict.",
    "zing reports black-box evidence of divergence and risk, not proof of fraud.",
  ].forEach(function (s) {
    P.push([esc(s), s]);
  });

  var strings = {};
  var findings = {};

  // Register a language. `s` maps English UI string -> translation; `f` maps
  // finding id -> [title, summary template]. Missing entries fall back to
  // English at runtime.
  function add(code, s, f) {
    strings[code] = s || {};
    var d = (findings[code] = {});
    Object.keys(f || {}).forEach(function (id) {
      d[id] = { title: f[id][0], tpl: f[id][1] };
    });
  }

  Object.keys(DATA.locales).forEach(function (code) {
    if (code === "en") return; // English is the key language
    add(code, DATA.locales[code].strings, DATA.locales[code].findings);
  });

  var en = DATA.locales.en || {};
  var zh = DATA.locales.zh || {};
  window.ZING_LOCALES = {
    strings: strings,
    findings: findings,
    patterns: P,
    add: add,
    keys: { strings: Object.keys(en.strings || {}), findings: Object.keys(zh.findings || {}) },
    languages: DATA.languages || [],
  };
})();
