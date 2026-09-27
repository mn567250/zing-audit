/* zing web UI — language switch (EN · CN · FR · ES · PT · IT).
 *
 * Plain browser global, no modules. Load it in <head> after /locales.js and
 * before any page script, so the current language is known while the page
 * renders. Exposes window.ZING_LANG with:
 *   - get()            -> a code from LANGS below ("en", "zh", "fr", …)
 *   - langs()          the registry: [{ code, label, html, locale }] in menu order
 *   - isZh()           true when the original Chinese UI is shown
 *   - set(lang)        persist + re-translate static markup + fire "zing:lang"
 *   - t(zh, en)        CN -> zh; otherwise the English text translated via tr()
 *   - tr(en)           English string -> current language (from ZING_LOCALES)
 *   - locale()         BCP 47 locale for dates/numbers ("fr-FR", …)
 *   - code(v)          uppercase enum code ("HIGH", "FAIL") in the UI language
 *   - server(text)     clean-up / translation of free text from the backend
 *   - stripCJK(text)   drop CJK runs (e.g. "Moonshot AI (月之暗面 / Kimi)")
 *   - apply(root)      (re)translate static markup under root
 * and a global shorthand T(zh, en).
 *
 * The Chinese text in the HTML is the original and stays untouched: elements
 * carry their English text in data attributes (the English doubles as the
 * lookup key for FR/ES/PT/IT) and the Chinese is remembered on first switch,
 * so CN always shows exactly what shipped.
 *   data-en="…"              innerHTML outside CN (only text/inline markup inside!)
 *   data-en-placeholder="…"  / data-en-title / data-en-aria-label  attributes
 * A <select class="lang-sel"> anywhere on the page becomes the switcher; its
 * options are generated from LANGS, the single list of supported languages.
 *
 * Adding a language:
 *   1. add one entry to LANGS below (flag + code label, <html lang>, locale);
 *   2. add its translations in /locales.js with ZING_LOCALES.add(code, …).
 * Nothing else changes: pages, T(zh, en) call sites and data-en markup stay as
 * they are, and any string missing from a translation falls back to English.
 */
(function () {
  "use strict";

  var KEY = "zing.lang";
  var DEFAULT = "en";
  // The supported languages, in dropdown order. "en" and "zh" need no
  // translations (English is the key language, CN is the original markup).
  var LANG_LIST = [
    { code: "en", label: "🇬🇧 EN", html: "en", locale: "en-US" },
    { code: "zh", label: "🇨🇳 CN", html: "zh-CN", locale: "zh-CN" },
    { code: "fr", label: "🇫🇷 FR", html: "fr", locale: "fr-FR" },
    { code: "es", label: "🇪🇸 ES", html: "es", locale: "es-ES" },
    { code: "pt", label: "🇵🇹 PT", html: "pt", locale: "pt-PT" },
    { code: "it", label: "🇮🇹 IT", html: "it", locale: "it-IT" },
    { code: "de", label: "🇩🇪 DE", html: "de", locale: "de-DE" },
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

  // Backend text is English. CN shows it verbatim (as it always did); every
  // other language drops the embedded Chinese terms, then translates exact
  // known strings (detector names, …) and known sentence patterns (the
  // verdict summary) from ZING_LOCALES; anything unknown stays English.
  function server(text) {
    if (text == null || lang === "zh") return text;
    var s = String(text);
    GLOSSARY.forEach(function (g) {
      s = s.split(g[0]).join(g[1]);
    });
    if (lang === "en") return s;
    var exact = tr(s);
    if (exact !== s) return exact;
    (locales().patterns || []).forEach(function (p) {
      s = s.replace(new RegExp(p[0], "g"), function () {
        var groups = arguments;
        return tr(p[1]).replace(/\{(\d)\}/g, function (_m, i) {
          var g = groups[+i];
          return g == null ? "" : p[2] && p[2][i] ? p[2][i](g, tr) : g;
        });
      });
    });
    return s;
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
  if (lang !== "zh") document.documentElement.style.visibility = "hidden";
  document.documentElement.lang = LANGS[lang].html;

  function boot() {
    apply(document);
    wireSwitchers();
    document.documentElement.style.visibility = "";
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
    code: code,
    server: server,
    stripCJK: stripCJK,
    apply: apply,
  };
  window.T = t;
})();
