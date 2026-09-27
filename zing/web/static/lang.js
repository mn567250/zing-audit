/* zing web UI — language switch (English · 中文 · Français · Español ·
 * Português · Italiano · Deutsch; the list comes from zing/i18n/locales/).
 *
 * Plain browser global, no modules. Load it in <head> after /locales.js and
 * before any page script, so the current language is known while the page
 * renders. Exposes window.ZING_LANG with:
 *   - get()            -> a code from LANGS below ("en", "zh", "fr", …)
 *   - langs()          the registry: [{ code, label, html, locale }] in menu order
 *                      (label is the language's own name: "English", "中文", …)
 *   - isZh()           true when the original Chinese UI is shown
 *   - set(lang)        persist + re-translate static markup + fire "zing:lang"
 *   - t(zh, en)        CN -> zh; otherwise the English text translated via tr()
 *   - tr(en)           English string -> current language (from ZING_LOCALES)
 *   - trFor(lang, en)  English string -> the given language
 *   - locale()         BCP 47 locale for dates/numbers ("fr-FR", …)
 *   - code(v)          uppercase enum code ("HIGH", "FAIL") in the UI language
 *   - server(text)     translation of free text from the backend (detector
 *                      names, recommendations, verdict sentences, notes) into
 *                      the UI language, CN included; unknown text stays English
 *   - exportText(text) same, for downloaded files
 *   - stripCJK(text)   drop CJK runs (e.g. "Moonshot AI (月之暗面 / Kimi)")
 *   - apply(root)      (re)translate static markup under root
 * and a global shorthand T(zh, en).
 *
 * The Chinese text in the HTML is the original and stays untouched: elements
 * carry their English text in data attributes (the English doubles as the
 * lookup key for the other languages) and the Chinese is remembered on first
 * switch, so CN always shows exactly what shipped.
 *   data-en="…"              innerHTML outside CN (only text/inline markup inside!)
 *   data-en-placeholder="…"  / data-en-title / data-en-aria-label  attributes
 * A <select class="lang-sel"> anywhere on the page becomes the switcher; its
 * options are generated from LANGS, the single list of supported languages.
 *
 * Adding a language: add zing/i18n/locales/<code>.json (its "meta" gives the
 * menu label — the language's own name, not a flag — <html lang>, locale and
 * menu order). Nothing else changes: pages, T(zh, en) call sites and data-en
 * markup stay as they are, and any string missing from a translation falls
 * back to English. Feature work may ship its strings as fragments,
 * zing/i18n/locales/fragments/<feature>/<code>.json ({"strings": {…}}), which
 * zing/i18n merges into that language's strings before serving /locales.js.
 *
 * Outside CN the page is hidden (html visibility) until the static markup is
 * translated. So a failure never leaves it blank, it is shown anyway ~1.5 s
 * after DOMContentLoaded (8 s at most after this script ran) or on a window
 * "error" once the HTML is parsed (e.g. a later script throws, or boot never
 * runs). Pages may also add
 *   <noscript><style>html{visibility:visible!important}</style></noscript>
 * for browsers with JavaScript disabled.
 */
(function () {
  "use strict";

  var KEY = "zing.lang";
  var DEFAULT = "en";
  // The supported languages in dropdown order, from zing/i18n/locales/*.json
  // (via /locales.js). EN and CN are always available: English is the key
  // language and CN the original markup.
  var LANG_LIST = ((window.ZING_LOCALES || {}).languages || []).slice();
  if (!LANG_LIST.length)
    LANG_LIST = [
      { code: "en", label: "English", html: "en", locale: "en-US" },
      { code: "zh", label: "中文", html: "zh-CN", locale: "zh-CN" },
    ];
  var LANGS = {};
  LANG_LIST.forEach(function (l) {
    LANGS[l.code] = l;
  });
  var ATTRS = ["placeholder", "title", "aria-label"];
  var CJK = /[⺀-⿿　-〿぀-ヿ㄀-ㇿ㐀-䶿一-鿿豈-﫿＀-￯]/;
  var CJK_RUN = /[⺀-⿿　-〿぀-ヿ㄀-ㇿ㐀-䶿一-鿿豈-﫿＀-￯]+/g;

  // Chinese terms the (otherwise English) backend embeds in its sentences.
  var GLOSSARY = [
    ["货不对板", "bait-and-switch"],
    ["中转站", "relay"],
  ];

  function read() {
    try {
      var v = localStorage.getItem(KEY);
      if (v && LANGS[v]) return v;
    } catch (e) {}
    return DEFAULT;
  }

  var lang = read();

  function locales() {
    return window.ZING_LOCALES || {};
  }

  function tr(en) {
    if (en == null || lang === "en" || lang === "zh") return en;
    var d = (locales().strings || {})[lang] || {};
    return Object.prototype.hasOwnProperty.call(d, en) ? d[en] : en;
  }

  // Uppercase enum codes shown as-is in CN/EN (e.g. "HIGH", "FAIL");
  // other languages look up the uppercase code itself.
  function code(v) {
    var c = String(v == null ? "" : v).toUpperCase();
    return lang === "en" || lang === "zh" ? c : tr(c);
  }

  function t(zh, en) {
    return lang === "zh" ? zh : tr(en);
  }

  function stripCJK(s) {
    s = String(s == null ? "" : s);
    if (!CJK.test(s)) return s;
    return s
      .replace(CJK_RUN, "")
      .replace(/\(\s*[\/·,，]?\s*/g, "(")
      .replace(/\s*[\/·,，]?\s*\)/g, ")")
      .replace(/\(\s*\)/g, "")
      .replace(/\s+\/\s+(?=[\/)]|$)/g, "")
      .replace(/\s*\/\s*(?=\()/g, " ")
      .replace(/\s{2,}/g, " ")
      .trim();
  }

  // English string -> language `l` (no current-language shortcut; "zh"
  // only knows the backend strings registered for exports).
  function trIn(l, en) {
    if (en == null || l === "en") return en;
    var d = (locales().strings || {})[l] || {};
    return Object.prototype.hasOwnProperty.call(d, en) ? d[en] : en;
  }

  // Backend text (always English) -> language `l`: drop the embedded Chinese
  // terms (not for zh), then translate exact known strings (detector names,
  // recommendations, …) and known sentence patterns (verdict summary and
  // headline) from ZING_LOCALES; anything unknown stays English.
  function backendIn(l, text) {
    if (text == null) return text;
    var s = String(text);
    if (l !== "zh")
      GLOSSARY.forEach(function (g) {
        s = s.split(g[0]).join(g[1]);
      });
    if (l === "en") return s;
    var exact = trIn(l, s);
    if (exact !== s) return exact;
    var t = function (en) {
      return trIn(l, en);
    };
    (locales().patterns || []).forEach(function (p) {
      s = s.replace(new RegExp(p[0], "g"), function () {
        var groups = arguments;
        return t(p[1]).replace(/\{(\d)\}/g, function (_m, i) {
          var g = groups[+i];
          return g == null ? "" : p[2] && p[2][i] ? p[2][i](g, t) : g;
        });
      });
    });
    // Chinese sentences are not separated by spaces.
    if (l === "zh") s = s.replace(/([。）])\s+(?=\S)/g, "$1");
    return s;
  }

  // Backend text in the UI, in the UI language (CN included: zh.json carries
  // the backend's sentences too).
  function server(text) {
    return backendIn(lang, text);
  }

  // Backend text in a downloaded artefact: the same translation, so the file
  // is in the chosen language throughout.
  function exportText(text) {
    return backendIn(lang, text);
  }

  function applyEl(el) {
    if (el.hasAttribute("data-en")) {
      if (el.__zingZh == null) el.__zingZh = el.innerHTML;
      var html = lang === "zh" ? el.__zingZh : tr(el.getAttribute("data-en"));
      if (el.tagName === "TITLE") el.textContent = html;
      else if (el.innerHTML !== html) el.innerHTML = html;
    }
    ATTRS.forEach(function (a) {
      var enA = "data-en-" + a;
      if (!el.hasAttribute(enA)) return;
      el.__zingZhAttr = el.__zingZhAttr || {};
      if (!(a in el.__zingZhAttr)) el.__zingZhAttr[a] = el.getAttribute(a);
      var v = lang === "zh" ? el.__zingZhAttr[a] : tr(el.getAttribute(enA));
      if (v == null) el.removeAttribute(a);
      else el.setAttribute(a, v);
    });
  }

  function apply(root) {
    root = root || document;
    var sel = "[data-en],[data-en-placeholder],[data-en-title],[data-en-aria-label]";
    if (root.nodeType === 1 && root.matches && root.matches(sel)) applyEl(root);
    var els = root.querySelectorAll(sel);
    for (var i = 0; i < els.length; i++) applyEl(els[i]);
    document.documentElement.lang = LANGS[lang].html;
    var sw = document.querySelectorAll("select.lang-sel");
    for (var j = 0; j < sw.length; j++) sw[j].value = lang;
  }

  function set(next) {
    next = LANGS[next] ? next : DEFAULT;
    if (next === lang) return;
    lang = next;
    try {
      localStorage.setItem(KEY, lang);
    } catch (e) {}
    apply(document);
    try {
      window.dispatchEvent(new CustomEvent("zing:lang", { detail: { lang: lang } }));
    } catch (e) {}
  }

  function wireSwitchers() {
    var sw = document.querySelectorAll("select.lang-sel");
    for (var i = 0; i < sw.length; i++) {
      if (sw[i].__zingWired) continue;
      sw[i].__zingWired = true;
      sw[i].innerHTML = "";
      LANG_LIST.forEach(function (l) {
        var o = document.createElement("option");
        o.value = l.code;
        o.textContent = l.label;
        sw[i].appendChild(o);
      });
      sw[i].value = lang;
      sw[i].addEventListener("change", function (ev) {
        set(ev.target.value);
      });
    }
  }

  // Keep the page hidden until the static markup is in the chosen language,
  // so a non-CN user never sees a flash of the Chinese original.
  // Never leave it blank, though: if boot doesn't run or a script fails,
  // show the page anyway. The 1.5 s grace starts once the HTML is parsed (a
  // slow download must not flash the Chinese original); a script error after
  // that reveals at once, and a cap covers a DOMContentLoaded that never comes.
  var timers = [];
  function reveal() {
    timers.forEach(function (id) {
      clearTimeout(id);
    });
    timers = [];
    try {
      window.removeEventListener("error", onError);
    } catch (e) {}
    document.documentElement.style.visibility = "";
  }
  function onError() {
    // Before DOMContentLoaded boot is still to come and will reveal the page.
    if (document.readyState !== "loading") reveal();
  }
  function arm() {
    timers.push(setTimeout(reveal, 1500));
  }
  if (lang !== "zh") {
    document.documentElement.style.visibility = "hidden";
    try {
      window.addEventListener("error", onError);
      timers.push(setTimeout(reveal, 8000));
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arm);
      else arm();
    } catch (e) {
      reveal();
    }
  }
  document.documentElement.lang = LANGS[lang].html;

  function boot() {
    try {
      apply(document);
      wireSwitchers();
    } finally {
      reveal();
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  window.ZING_LANG = {
    get: function () {
      return lang;
    },
    langs: function () {
      return LANG_LIST.slice();
    },
    isZh: function () {
      return lang === "zh";
    },
    locale: function () {
      return LANGS[lang].locale;
    },
    set: set,
    t: t,
    tr: tr,
    trFor: trIn,
    code: code,
    server: server,
    exportText: exportText,
    stripCJK: stripCJK,
    apply: apply,
  };
  window.T = t;
})();
