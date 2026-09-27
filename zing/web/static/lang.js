/* zing web UI — language switch (CN ⇄ EN).
 *
 * Plain browser global, no modules. Load it in <head> (before any page
 * script) so the current language is known while the page renders.
 * Exposes window.ZING_LANG with:
 *   - get()            -> "zh" | "en"
 *   - set(lang)        persist + re-translate static markup + fire "zing:lang"
 *   - t(zh, en)        pick the string for the current language
 *   - server(text)     EN-mode clean-up for free text coming from the backend
 *   - stripCJK(text)   drop CJK runs (e.g. "Moonshot AI (月之暗面 / Kimi)")
 *   - apply(root)      (re)translate static markup under root
 * and a global shorthand T(zh, en).
 *
 * The Chinese text in the HTML is the original and stays the source of truth:
 * elements carry their English text in data attributes and the Chinese is
 * remembered on first switch, so CN always shows exactly what shipped.
 *   data-en="…"              innerHTML in EN (only text/inline markup inside!)
 *   data-en-placeholder="…"  / data-en-title / data-en-aria-label  attributes
 * A <select class="lang-sel"> anywhere on the page becomes the switcher.
 */
(function () {
  "use strict";

  var KEY = "zing.lang";
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
      if (v === "en" || v === "zh") return v;
    } catch (e) {}
    return "zh"; // the UI's original language
  }

  var lang = read();

  function t(zh, en) {
    return lang === "en" ? en : zh;
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

  function server(text) {
    if (text == null || lang !== "en") return text;
    var s = String(text);
    GLOSSARY.forEach(function (g) {
      s = s.split(g[0]).join(g[1]);
    });
    return s;
  }

  function applyEl(el) {
    if (el.hasAttribute("data-en")) {
      if (el.__zingZh == null) el.__zingZh = el.innerHTML;
      var html = lang === "en" ? el.getAttribute("data-en") : el.__zingZh;
      if (el.tagName === "TITLE") el.textContent = html;
      else if (el.innerHTML !== html) el.innerHTML = html;
    }
    ATTRS.forEach(function (a) {
      var enA = "data-en-" + a;
      if (!el.hasAttribute(enA)) return;
      el.__zingZhAttr = el.__zingZhAttr || {};
      if (!(a in el.__zingZhAttr)) el.__zingZhAttr[a] = el.getAttribute(a);
      var v = lang === "en" ? el.getAttribute(enA) : el.__zingZhAttr[a];
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
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    var sw = document.querySelectorAll("select.lang-sel");
    for (var j = 0; j < sw.length; j++) sw[j].value = lang;
  }

  function set(next) {
    next = next === "en" ? "en" : "zh";
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
      sw[i].value = lang;
      sw[i].addEventListener("change", function (ev) {
        set(ev.target.value);
      });
    }
  }

  // Keep the page hidden until the static markup is in the chosen language,
  // so an EN user never sees a flash of the Chinese original.
  if (lang === "en") document.documentElement.style.visibility = "hidden";
  document.documentElement.lang = lang === "en" ? "en" : "zh-CN";

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
    set: set,
    t: t,
    server: server,
    stripCJK: stripCJK,
    apply: apply,
  };
  window.T = t;
})();
