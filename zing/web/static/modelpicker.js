/* zing web UI — reusable, page-agnostic claimed-model picker.
 *
 * Plain browser global, no modules, no external deps. Exposes:
 *   window.ZingModelPicker.enhance({ claimedInput, providerInput, label })
 *
 * Turns an EXISTING claimed-model text <input> into a compact two-step picker:
 *   供应商 (provider) <select>  →  模型 (model) <select>
 * The original input stays in the DOM as the canonical value holder (hidden in
 * select mode), so any form-submit code that reads `input.value` keeps working.
 * Selecting a model writes its id into the input and fires input+change events.
 *
 * A "自定义输入" / "← 选择模型" ("Custom input" / "← Pick a model" in EN) text toggle flips to free-text mode, which simply
 * re-shows the original input for manual typing, and back. On init: if the input
 * already holds a value that is NOT a known model id, it starts in custom mode
 * showing that value; otherwise it starts in select mode.
 *
 * Data: GET /api/kb (cached at module scope as a single shared promise). If the
 * fetch fails, enhance() is a no-op and the page keeps its plain text input.
 *
 * Custom provider: when the page passes `urlInput` (and optionally `keyInput`),
 * the provider list gains "Custom (from relay)". Selecting it shows a "Fetch
 * models" button that POSTs /api/models, which lists the relay's own /models —
 * instant connection feedback plus the exact ids it accepts. The API key is
 * optional (self-hosted Ollama / LM Studio need none). A fetched id is written
 * into `modelInput` (the requested model; defaults to `claimedInput`). `api` is
 * an optional function returning the page's protocol choice ("auto" default).
 *
 * Styling: keyed off the page CSS vars (--line, --teal, --ink, --ink2, --sans,
 * #fbfdfa input bg) so it visually matches the .in / select look on every page.
 *
 * Usage (per-page agent copy):
 *   ZingModelPicker.enhance({ claimedInput: "#e-claimed", providerInput: "#e-provider" });
 */
(function () {
  "use strict";

  var _kbPromise = null; // shared across every enhance() call on the page
  var CUSTOM = "__custom__"; // provider-select value of the relay-fetched list

  // UI language (lang.js): CN keeps the original strings, others translate.
  function isEn() {
    return !!(window.ZING_LANG && !window.ZING_LANG.isZh());
  }
  function tr(zh, en) {
    return window.ZING_LANG ? window.ZING_LANG.t(zh, en) : zh;
  }
  // KB display names / aliases may contain Chinese brand names; drop them
  // in every language but CN.
  function enText(s) {
    return isEn() ? window.ZING_LANG.stripCJK(s) : s;
  }

  function loadKb() {
    if (_kbPromise == null) {
      _kbPromise = fetch("/api/kb")
        .then(function (r) {
          if (!r.ok) throw new Error("kb http " + r.status);
          return r.json();
        })
        .then(function (data) {
          var providers = (data && data.providers) || [];
          return Array.isArray(providers) ? providers : [];
        });
    }
    return _kbPromise;
  }

  function resolveEl(ref) {
    if (ref == null) return null;
    if (typeof ref === "string") return document.querySelector(ref);
    return ref; // assume an element
  }

  // Set of every known model id across all providers (for init mode detection).
  function knownIds(providers) {
    var ids = Object.create(null);
    providers.forEach(function (p) {
      (p.models || []).forEach(function (m) {
        if (m && m.id) ids[m.id] = true;
      });
    });
    return ids;
  }

  // Minimal inline styles keyed off the page's CSS vars so the picker matches
  // the local .in / select look without needing the page to ship extra CSS.
  function styleSelect(sel) {
    sel.style.width = "100%";
    sel.style.border = "1.5px solid var(--line, #e7ece5)";
    sel.style.background = "#fbfdfa";
    sel.style.borderRadius = "13px";
    sel.style.fontFamily = "var(--sans, system-ui, sans-serif)";
    sel.style.fontWeight = "500";
    sel.style.fontSize = "15.5px";
    sel.style.color = "var(--ink, #0c211e)";
    sel.style.padding = "12px 13px";
    sel.style.outline = "none";
    sel.style.cursor = "pointer";
    sel.addEventListener("focus", function () {
      sel.style.borderColor = "var(--teal, #0f6f5f)";
      sel.style.boxShadow = "0 0 0 4px rgba(15,111,95,.12)";
    });
    sel.addEventListener("blur", function () {
      sel.style.borderColor = "var(--line, #e7ece5)";
      sel.style.boxShadow = "none";
    });
  }

  function opt(value, text) {
    var o = document.createElement("option");
    o.value = value;
    o.textContent = text;
    return o;
  }

  function enhance(opts) {
    opts = opts || {};
    var claimedInput = resolveEl(opts.claimedInput);
    if (!claimedInput) return; // nothing to enhance
    var providerInput = resolveEl(opts.providerInput); // optional
    var relay = {
      urlInput: resolveEl(opts.urlInput), // optional: enables the custom provider
      keyInput: resolveEl(opts.keyInput),
      modelInput: resolveEl(opts.modelInput) || claimedInput,
      api: typeof opts.api === "function" ? opts.api : null,
    };

    loadKb()
      .then(function (providers) {
        if (!providers.length && !relay.urlInput) return; // nothing to offer
        build(claimedInput, providerInput, providers, opts.label, relay);
      })
      .catch(function () {
        // Defensive: any failure leaves the original input untouched.
      });
  }

  function build(claimedInput, providerInput, providers, label, relay) {
    var ids = knownIds(providers);

    // Container inserted right before the original input; the input is moved
    // inside it so "free-text mode" can re-show it in place.
    var wrap = document.createElement("div");
    wrap.className = "zmp";
    wrap.style.display = "flex";
    wrap.style.flexDirection = "column";
    wrap.style.gap = "8px";

    var parent = claimedInput.parentNode;
    parent.insertBefore(wrap, claimedInput);

    // The two selects live in their own row container so we can hide/show them
    // as a unit when toggling to custom mode.
    var selectRow = document.createElement("div");
    selectRow.style.display = "flex";
    selectRow.style.flexDirection = "column";
    selectRow.style.gap = "8px";

    var provSel = document.createElement("select");
    var modelSel = document.createElement("select");
    styleSelect(provSel);
    styleSelect(modelSel);

    function paintLabels() {
      var lbl = typeof label === "function" ? label() : label;
      if (lbl) {
        provSel.setAttribute("aria-label", lbl + tr(" 供应商", " provider"));
        modelSel.setAttribute("aria-label", lbl + tr(" 模型", " model"));
      }
    }
    paintLabels();

    function fillProviders() {
      var keep = provSel.value;
      provSel.innerHTML = "";
      provSel.appendChild(opt("", tr("选择供应商…", "Select provider…")));
      providers.forEach(function (p) {
        provSel.appendChild(opt(p.provider, enText(p.display_name || p.provider) || p.provider));
      });
      if (relay.urlInput) {
        provSel.appendChild(opt(CUSTOM, tr("自定义（从中转站获取）", "Custom (from relay)")));
      }
      provSel.value = keep;
    }
    fillProviders();
    modelSel.appendChild(opt("", tr("选择模型…", "Select model…")));
    modelSel.disabled = true;

    selectRow.appendChild(provSel);

    // Custom provider: "Fetch models" button + status line, shown only while
    // the custom entry is selected (it lives in selectRow, so custom-input
    // mode hides it too).
    var fetchRow = document.createElement("div");
    fetchRow.style.display = "none";
    fetchRow.style.alignItems = "center";
    fetchRow.style.flexWrap = "wrap";
    fetchRow.style.gap = "10px";
    var fetchBtn = document.createElement("button");
    fetchBtn.type = "button";
    fetchBtn.style.font = "inherit";
    fetchBtn.style.fontSize = "13px";
    fetchBtn.style.fontWeight = "700";
    fetchBtn.style.fontFamily = "var(--sans, system-ui, sans-serif)";
    fetchBtn.style.color = "#fff";
    fetchBtn.style.background = "var(--teal, #0f6f5f)";
    fetchBtn.style.border = "0";
    fetchBtn.style.borderRadius = "10px";
    fetchBtn.style.padding = "8px 14px";
    fetchBtn.style.cursor = "pointer";
    var fetchStatus = document.createElement("span");
    fetchStatus.style.fontSize = "12.5px";
    fetchStatus.style.fontFamily = "var(--sans, system-ui, sans-serif)";
    fetchStatus.style.color = "var(--ink2, #4a5d59)";
    fetchStatus.style.wordBreak = "break-word";
    fetchRow.appendChild(fetchBtn);
    fetchRow.appendChild(fetchStatus);
    selectRow.appendChild(fetchRow);

    selectRow.appendChild(modelSel);

    // Toggle link between select mode and free-text (custom) mode.
    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.style.alignSelf = "flex-start";
    toggle.style.font = "inherit";
    toggle.style.fontSize = "12px";
    toggle.style.fontWeight = "700";
    toggle.style.fontFamily = "var(--sans, system-ui, sans-serif)";
    toggle.style.color = "var(--teal, #0f6f5f)";
    toggle.style.background = "none";
    toggle.style.border = "0";
    toggle.style.padding = "0";
    toggle.style.cursor = "pointer";

    wrap.appendChild(selectRow);
    // Move the original input into the wrap so it shows in custom mode in place.
    wrap.appendChild(claimedInput);
    wrap.appendChild(toggle);

    // ---- Custom provider: models fetched from the relay ----------------- //
    var fetched = []; // ids from the last successful fetch
    var fetchState = null; // null | "loading" | {ok, count} | {error}

    function isCustom() {
      return provSel.value === CUSTOM;
    }

    function paintFetch() {
      fetchRow.style.display = isCustom() ? "flex" : "none";
      var hasUrl = !!(relay.urlInput && relay.urlInput.value.trim());
      var loading = fetchState === "loading";
      fetchBtn.disabled = !hasUrl || loading;
      fetchBtn.style.opacity = fetchBtn.disabled ? "0.5" : "1";
      fetchBtn.style.cursor = fetchBtn.disabled ? "not-allowed" : "pointer";
      fetchBtn.textContent = tr("获取模型列表", "Fetch models");
      fetchBtn.title = hasUrl ? "" : tr("请先填写 base_url", "Enter the base_url first");
      var st = fetchState;
      if (st === "loading") {
        fetchStatus.style.color = "var(--ink2, #4a5d59)";
        fetchStatus.textContent = tr("正在获取模型…", "Fetching models…");
      } else if (st && st.error) {
        fetchStatus.style.color = "var(--red, #b3261e)";
        fetchStatus.textContent = "✗ " + tr("连接失败", "Connection failed") + " — " + st.error;
      } else if (st && st.count === 0) {
        fetchStatus.style.color = "var(--amber, #9a6700)";
        fetchStatus.textContent = "⚠ " + tr("中转站未返回任何模型", "The relay returned no models");
      } else if (st) {
        fetchStatus.style.color = "var(--teal, #0f6f5f)";
        fetchStatus.textContent = "✓ " + tr("已找到模型：", "Models found:") + " " + st.count;
      } else {
        fetchStatus.textContent = "";
      }
    }

    function fillFetched() {
      modelSel.innerHTML = "";
      modelSel.appendChild(
        opt("", fetched.length ? tr("选择模型…", "Select model…") : tr("请先获取模型…", "Fetch models first…"))
      );
      fetched.forEach(function (id) {
        modelSel.appendChild(opt(id, id));
      });
      modelSel.disabled = fetched.length === 0;
      var cur = (relay.modelInput.value || "").trim();
      if (cur && fetched.indexOf(cur) !== -1) modelSel.value = cur;
    }

    function fetchModels() {
      var url = relay.urlInput ? relay.urlInput.value.trim() : "";
      if (!url) return;
      fetchState = "loading";
      paintFetch();
      fetch("/api/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: url,
          api_key: relay.keyInput ? relay.keyInput.value.trim() : "",
          api: relay.api ? relay.api() || "auto" : "auto",
        }),
      })
        .then(function (r) {
          return r.json().catch(function () {
            return { error: "HTTP " + r.status };
          });
        })
        .then(function (data) {
          if (data && data.ok) {
            fetched = Array.isArray(data.models) ? data.models : [];
            fetchState = { ok: true, count: fetched.length };
          } else {
            fetched = [];
            var msg = (data && data.error) || "";
            if (data && data.status_code) msg = "HTTP " + data.status_code + (msg ? ": " + msg : "");
            fetchState = { error: msg || "?" };
          }
        })
        .catch(function (e) {
          fetched = [];
          fetchState = { error: String((e && e.message) || e) };
        })
        .then(function () {
          if (isCustom()) fillFetched();
          paintFetch();
        });
    }

    fetchBtn.addEventListener("click", fetchModels);
    if (relay.urlInput) relay.urlInput.addEventListener("input", paintFetch);

    function fillModels(providerId) {
      if (providerId === CUSTOM) {
        fillFetched();
        return null;
      }
      modelSel.innerHTML = "";
      modelSel.appendChild(opt("", tr("选择模型…", "Select model…")));
      var prov = null;
      for (var i = 0; i < providers.length; i++) {
        if (providers[i].provider === providerId) {
          prov = providers[i];
          break;
        }
      }
      var models = (prov && prov.models) || [];
      models.forEach(function (m) {
        if (!m || !m.id) return;
        var aliases = (m.aliases || []).filter(function (a) {
          return !isEn() || (a && window.ZING_LANG.stripCJK(a) === a);
        });
        var alias = aliases.length ? aliases[0] : "";
        // Show id, with a short alias hint when it differs from the id.
        var text =
          alias && alias.toLowerCase() !== m.id.toLowerCase()
            ? m.id + " · " + alias
            : m.id;
        modelSel.appendChild(opt(m.id, text));
      });
      modelSel.disabled = models.length === 0;
      return prov;
    }

    function setClaimed(value) {
      claimedInput.value = value;
      claimedInput.dispatchEvent(new Event("input", { bubbles: true }));
      claimedInput.dispatchEvent(new Event("change", { bubbles: true }));
    }

    provSel.addEventListener("change", function () {
      var pid = provSel.value;
      fillModels(pid);
      paintFetch();
      if (providerInput && pid && pid !== CUSTOM) {
        providerInput.value = pid;
        providerInput.dispatchEvent(new Event("input", { bubbles: true }));
        providerInput.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });

    modelSel.addEventListener("change", function () {
      if (!modelSel.value) return;
      if (isCustom()) {
        // A relay-listed id is what the relay accepts: the requested model.
        relay.modelInput.value = modelSel.value;
        relay.modelInput.dispatchEvent(new Event("input", { bubbles: true }));
        relay.modelInput.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        setClaimed(modelSel.value);
      }
    });

    // ---- Mode switching ------------------------------------------------- //
    var custom = false;

    function applyMode() {
      if (custom) {
        selectRow.style.display = "none";
        claimedInput.style.display = "";
        toggle.textContent = tr("← 选择模型", "← Pick a model");
      } else {
        selectRow.style.display = "";
        claimedInput.style.display = "none";
        toggle.textContent = tr("自定义输入", "Custom input");
      }
    }

    toggle.addEventListener("click", function () {
      custom = !custom;
      applyMode();
      if (custom) claimedInput.focus();
    });

    // ---- Initial mode --------------------------------------------------- //
    var current = (claimedInput.value || "").trim();
    if (current && !ids[current]) {
      // Existing value isn't a known model id → free-text mode showing it.
      custom = true;
    } else if (current && ids[current]) {
      // Pre-select the matching provider + model in the selects.
      for (var i = 0; i < providers.length; i++) {
        var p = providers[i];
        var hit = (p.models || []).some(function (m) {
          return m && m.id === current;
        });
        if (hit) {
          provSel.value = p.provider;
          fillModels(p.provider);
          modelSel.value = current;
          if (providerInput && !providerInput.value) providerInput.value = p.provider;
          break;
        }
      }
    }
    paintFetch();
    applyMode();

    // Re-label everything in place when the UI language changes.
    window.addEventListener("zing:lang", function () {
      var keepModel = modelSel.value;
      paintLabels();
      fillProviders();
      if (provSel.value) {
        fillModels(provSel.value);
        modelSel.value = keepModel;
      } else {
        modelSel.options[0].textContent = tr("选择模型…", "Select model…");
      }
      paintFetch();
      applyMode();
    });
  }

  window.ZingModelPicker = { enhance: enhance };
})();
