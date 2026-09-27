"""Translations shared by the web UI and the Python side (webhook alerts).

The single source is ``zing/i18n/locales/<code>.json``, one file per language:

* ``meta``     — ``code``, dropdown ``label``, ``html`` lang, date ``locale`` and
  menu ``order``;
* ``strings``  — English string -> translation (``en.json`` is the identity map
  and so the canonical list of translatable strings);
* ``findings`` — finding id -> ``[title, summary template]`` (``zh.json`` holds
  the original Chinese catalog; ``en`` needs none — the backend is English).

The browser gets the same data through ``/locales.js`` (see :func:`locales_script`);
this module gives Python code (``zing.notify``) the lookups it needs. Adding a
language means adding one JSON file here — nothing else.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent / "locales"
_STATIC_LOCALES_JS = Path(__file__).resolve().parent.parent / "web" / "static" / "locales.js"

DEFAULT = "en"

# Chinese terms the (otherwise English) backend embeds in its sentences.
_GLOSSARY = (("货不对板", "bait-and-switch"), ("中转站", "relay"))
_HEADLINE = re.compile(r"^(?P<sentence>.*?)\s*\(confidence: (?P<conf>low|medium|high)\)$")


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out[data["meta"]["code"]] = data
    return out


def languages() -> list[dict[str, Any]]:
    """Language metadata (code, label, html, locale) in menu order."""
    return sorted((d["meta"] for d in _load().values()), key=lambda m: m.get("order", 99))


def codes() -> list[str]:
    return [m["code"] for m in languages()]


def normalize(lang: str | None) -> str:
    """A supported language code; anything unknown or empty becomes English."""
    lang = (lang or "").strip().lower()
    return lang if lang in _load() else DEFAULT


def ui(lang: str, en: str) -> str:
    """English string -> ``lang`` (falls back to the English string)."""
    lang = normalize(lang)
    if lang == DEFAULT:
        return en
    return _load()[lang].get("strings", {}).get(en, en)


def finding_title(lang: str, finding_id: str | None, english_title: str) -> str:
    """A finding's title in ``lang``: its catalog title, else the English one."""
    lang = normalize(lang)
    if lang == DEFAULT:
        return backend(lang, english_title)
    cat = _load()[lang].get("findings", {})
    entry = None
    if finding_id:
        entry = cat.get(finding_id)
        if entry is None and finding_id.startswith("model_identity.fp."):
            entry = cat.get("model_identity.fp.*")
    return entry[0] if entry else backend(lang, english_title)


def backend(lang: str, text: str | None) -> str:
    """Translate a known backend sentence (exact match or verdict headline).

    Unknown text stays English, minus the Chinese terms it may embed (except
    for ``zh``, where they are kept).
    """
    lang = normalize(lang)
    s = text or ""
    if lang != "zh":
        for zh, en in _GLOSSARY:
            s = s.replace(zh, en)
    if lang == DEFAULT:
        return s
    exact = ui(lang, s)
    if exact != s:
        return exact
    m = _HEADLINE.match(s)
    if m:
        conf = ui(lang, m["conf"].capitalize())
        conf = conf if lang == "zh" else conf.lower()
        suffix = ui(lang, "(confidence: {1})").replace("{1}", conf)
        return ui(lang, m["sentence"]) + ("" if lang == "zh" else " ") + suffix
    return s


def bundle() -> dict[str, Any]:
    """Everything the browser needs: language list + per-language data."""
    data = _load()
    return {
        "languages": languages(),
        "locales": {code: {"strings": d.get("strings", {}), "findings": d.get("findings", {})} for code, d in data.items()},
    }


def locales_script() -> str:
    """The JS served at ``/locales.js``: the JSON data, then the lookup logic."""
    data = json.dumps(bundle(), ensure_ascii=False, separators=(",", ":"))
    return f"window.ZING_I18N_DATA = {data};\n" + _STATIC_LOCALES_JS.read_text(encoding="utf-8")
