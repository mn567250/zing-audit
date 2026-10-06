"""Tests for knowledge-base loading and model-id resolution."""

from __future__ import annotations

from zing.knowledge import KnowledgeBase, load_knowledge_base
from zing.knowledge.schema import (
    FingerprintProbe,
    ModelProfile,
    ProviderProfile,
    ResolvedProfile,
    _normalize,
)


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def test_c_yaml_loader_matches_pure_python_for_packaged_profiles():
    # The loader prefers libyaml's CSafeLoader; it must yield exactly the data
    # the pure-Python SafeLoader does for every shipped profile.
    from importlib import resources

    import pytest
    import yaml

    from zing.knowledge import loader

    if not hasattr(yaml, "CSafeLoader"):
        pytest.skip("PyYAML built without libyaml")
    assert loader._YAML_LOADER is yaml.CSafeLoader
    files = [e for e in resources.files("zing.knowledge.data").iterdir()
             if e.name.endswith((".yaml", ".yml"))]
    assert files
    for entry in files:
        text = entry.read_text(encoding="utf-8")
        assert yaml.load(text, Loader=yaml.CSafeLoader) == yaml.load(text, Loader=yaml.SafeLoader), entry.name


def test_cached_knowledge_base_is_a_private_copy():
    first = load_knowledge_base()
    first.providers["openai"].models.clear()
    first.providers["openai"].fingerprints.clear()
    first.warnings.append("mutated")
    del first.providers["anthropic"]
    second = load_knowledge_base()
    assert second is not first
    assert second.providers["openai"].models and "anthropic" in second.providers
    assert "mutated" not in second.warnings


def test_kb_dir_edit_invalidates_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("ZING_KB_DIR", raising=False)
    path = tmp_path / "acme.yaml"
    path.write_text("provider: acmeai\nmodels:\n- id: acme-one\n", encoding="utf-8")
    kb = load_knowledge_base([tmp_path])
    assert kb.resolve("acme-one") is not None
    path.write_text("provider: acmeai\nmodels:\n- id: acme-two-longer\n", encoding="utf-8")
    kb = load_knowledge_base([tmp_path])
    assert kb.resolve("acme-two-longer") is not None
    assert [m.id for m in kb.providers["acmeai"].models] == ["acme-two-longer"]
    path.unlink()
    assert "acmeai" not in load_knowledge_base([tmp_path]).providers
    monkeypatch.setenv("ZING_KB_DIR", str(tmp_path))
    (tmp_path / "beta.yaml").write_text("provider: betaai\nmodels: []\n", encoding="utf-8")
    assert "betaai" in load_knowledge_base().providers


def test_load_knowledge_base_has_providers(knowledge_base):
    assert isinstance(knowledge_base, KnowledgeBase)
    assert knowledge_base.providers, "expected packaged provider profiles"
    # Spot-check a couple of well-known providers ship with the package.
    assert "openai" in knowledge_base.providers
    assert "anthropic" in knowledge_base.providers


def test_load_knowledge_base_is_callable_fresh():
    kb = load_knowledge_base()
    assert kb.providers
    # all_models flattens (provider, model) pairs.
    pairs = kb.all_models()
    assert pairs
    assert all(isinstance(p, ProviderProfile) and isinstance(m, ModelProfile) for p, m in pairs)


# --------------------------------------------------------------------------- #
# _normalize
# --------------------------------------------------------------------------- #
def test_normalize_strips_separators_and_lowercases():
    assert _normalize("GPT-4o") == "gpt4o"
    assert _normalize("Claude 3.5 Sonnet") == "claude35sonnet"
    assert _normalize("deepseek_chat") == "deepseekchat"
    assert _normalize("") == ""


# --------------------------------------------------------------------------- #
# resolve — against a small synthetic KB (deterministic, independent of data) #
# --------------------------------------------------------------------------- #
def _synthetic_kb() -> KnowledgeBase:
    model = ModelProfile(
        id="acme-large",
        aliases=["acme-l", "acme-large-2024-01-01"],
        family="acme",
        context_window_tokens=128000,
        max_output_tokens=4096,
    )
    other = ModelProfile(id="acme-small", aliases=["acme-s"])
    provider = ProviderProfile(provider="acme", models=[model, other])
    return KnowledgeBase(providers={"acme": provider})


def test_resolve_exact_id():
    kb = _synthetic_kb()
    r = kb.resolve("acme-large")
    assert isinstance(r, ResolvedProfile)
    assert r.model.id == "acme-large"
    assert r.match_confidence == "exact"


def test_resolve_alias():
    kb = _synthetic_kb()
    r = kb.resolve("acme-l")
    assert r is not None
    assert r.model.id == "acme-large"
    assert r.match_confidence == "alias"


def test_resolve_normalized_exact_treated_as_alias():
    kb = _synthetic_kb()
    # Different casing/separators of an exact id resolve via the normalized path.
    r = kb.resolve("ACME_LARGE")
    assert r is not None
    assert r.model.id == "acme-large"
    assert r.match_confidence == "alias"


def test_resolve_fuzzy_substring():
    kb = _synthetic_kb()
    # A relay-decorated id that is a superset of the real id -> fuzzy match.
    r = kb.resolve("relay-acme-large-turbo")
    assert r is not None
    assert r.model.id == "acme-large"
    assert r.match_confidence == "fuzzy"


def test_resolve_unknown_returns_none():
    kb = _synthetic_kb()
    assert kb.resolve("totally-unrelated-xyz") is None


def test_resolve_empty_returns_none():
    kb = _synthetic_kb()
    assert kb.resolve("") is None


def test_resolve_provider_hint_narrows():
    other = ProviderProfile(
        provider="globex", models=[ModelProfile(id="acme-large", aliases=[])]
    )
    base = _synthetic_kb()
    base.providers["globex"] = other
    r = base.resolve("acme-large", provider_hint="globex")
    assert r is not None
    assert r.provider.provider == "globex"


# --------------------------------------------------------------------------- #
# resolve — against the real packaged KB
# --------------------------------------------------------------------------- #
def test_resolve_real_known_model(knowledge_base):
    r = knowledge_base.resolve("gpt-4o")
    assert r is not None
    assert r.model.id == "gpt-4o"
    assert r.provider.provider == "openai"
    assert r.match_confidence == "exact"
    # Native specs are populated for a known model.
    assert r.model.context_window_tokens > 0


# --------------------------------------------------------------------------- #
# ResolvedProfile.all_fingerprints
# --------------------------------------------------------------------------- #
def test_all_fingerprints_merges_provider_and_model():
    provider = ProviderProfile(
        provider="acme",
        fingerprints=[FingerprintProbe(id="p1", signal="s", prompt="q")],
        models=[
            ModelProfile(
                id="acme-large",
                fingerprints=[FingerprintProbe(id="m1", signal="s", prompt="q")],
            )
        ],
    )
    resolved = ResolvedProfile(provider=provider, model=provider.models[0])
    ids = [fp.id for fp in resolved.all_fingerprints()]
    assert ids == ["p1", "m1"]


def test_performance_reference_ranges():
    import pytest
    from pydantic import ValidationError

    from zing.knowledge.schema import ModelProfile, PerformanceReference

    ref = PerformanceReference(decode_tps=[40, 120], ttft_ms=[300, 1500], source="x")
    assert ref.decode_tps == (40.0, 120.0)
    assert ModelProfile(id="m", performance={"decode_tps": [10, 20]}).performance is not None
    assert ModelProfile(id="m").performance is None  # optional: old entries stay valid
    for bad in ([120, 40], [0, 10]):
        with pytest.raises(ValidationError):
            PerformanceReference(decode_tps=bad)


def test_bundled_performance_references_load():
    from zing.knowledge import load_knowledge_base

    kb = load_knowledge_base(None, include_user=False)
    refs = [m.performance for _, m in kb.all_models() if m.performance]
    assert refs and all(r.decode_tps and r.source for r in refs)
