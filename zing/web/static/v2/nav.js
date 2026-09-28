/* zing web UI v2 — the one shared header.
 *
 * Every v2 page has, as the first thing in <div class="wrap">:
 *   <header class="znav" data-page="audit|tools|history|monitors|kb|console"></header>
 * and loads, right after /icons.js and before its own page script:
 *   <script src="/v2/static/nav.js"></script>
 * Optional: data-trust on the header adds the "runs locally" line under it.
 *
 * The markup follows the i18n convention of the whole UI (Chinese inline,
 * English in data-en), so lang.js translates it at boot and on every switch;
 * the language <select class="lang-sel"> is filled by lang.js too. The theme
 * <select class="theme-sel"> is driven by theme.js (loaded in <head>). The
 * "Classic UI" link goes back to the classic page (?ui=v1 — see server.py).
 */
(function () {
  "use strict";

  var LINKS = [
    // [page id, href, icon, zh, en]
    ["audit", "/v2/", "bolt", "检测", "Audit"],
    ["tools", "/v2/tools", "toolbox", "工具", "Tools"],
    ["history", "/v2/history", "chart", "检测历史", "History"],
    ["monitors", "/v2/watches", "bell", "监控", "Monitors"],
    ["kb", "/v2/kb", "book", "模型库", "Models"],
    ["console", "/v2/console", "terminal", "控制台", "Console"],
  ];

  function ico(name, opts) {
    return window.zingIcon ? window.zingIcon(name, opts || {}) : "";
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function render(header) {
    var page = header.getAttribute("data-page") || "";
    var links = LINKS.map(function (l) {
      var cur = l[0] === page ? ' aria-current="page"' : "";
      return (
        '<a href="' + l[1] + '"' + cur + ">" + ico(l[2]) +
        '<span data-en="' + esc(l[4]) + '">' + l[3] + "</span></a>"
      );
    }).join("");
    header.innerHTML =
      '<a class="logo" href="/v2/" aria-label="zing"><span class="b">' + ico("bolt", { size: 16 }) +
      "</span><span>zing<b>.</b></span></a>" +
      '<nav class="links" aria-label="主导航" data-en-aria-label="Main navigation">' + links + "</nav>" +
      '<div class="tail">' +
      '<a class="classic" href="?ui=v1" data-en="Classic UI">经典界面</a>' +
      '<select class="theme-sel" aria-label="主题" title="主题" data-en-aria-label="Theme" data-en-title="Theme">' +
      '<option value="system" data-en="Auto theme">跟随系统</option>' +
      '<option value="light" data-en="Light">浅色</option>' +
      '<option value="dark" data-en="Dark">深色</option></select>' +
      '<select class="lang-sel" aria-label="语言" title="语言" data-en-aria-label="Language" data-en-title="Language"></select>' +
      "</div>";
    if (header.hasAttribute("data-trust")) {
      var p = document.createElement("p");
      p.className = "trust";
      p.innerHTML =
        ico("lock") +
        ' <span data-en="Runs locally · keys <b>never leave</b>">本地运行 · 密钥<b>不经手</b></span>';
      header.parentNode.insertBefore(p, header.nextSibling);
    }
    var ts = header.querySelector("select.theme-sel");
    if (window.ZING_THEME) {
      ts.value = window.ZING_THEME.get();
      ts.addEventListener("change", function () { window.ZING_THEME.set(ts.value); });
    } else {
      ts.remove(); // page without theme.js
    }
    // keep the active tab visible when the link row scrolls (phones)
    var active = header.querySelector('[aria-current="page"]');
    if (active && active.scrollIntoView) {
      try {
        active.scrollIntoView({ block: "nearest", inline: "center" });
      } catch (e) {}
    }
  }

  var headers = document.querySelectorAll("header.znav");
  for (var i = 0; i < headers.length; i++) render(headers[i]);
  // If lang.js already booted (script loaded late), translate the new markup.
  if (window.ZING_LANG && document.readyState !== "loading") window.ZING_LANG.apply(document);
})();
