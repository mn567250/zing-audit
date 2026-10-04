"""The BITV conformance report: per-step results plugin and generator.

Pure Python (no browser): tests/a11y/results.py and tests/a11y/conformance.py.
"""

from __future__ import annotations

import datetime as dt
import json

from tests.a11y import conformance, results
from tests.a11y.bitv_map import CRITERIA, catalogue, criterion_of

CAT = catalogue()


def test_catalogue_is_the_wcag_21_a_aa_scope():
    steps = CAT["steps"]
    assert len(steps) == 50
    levels: dict[str, set[str]] = {}
    for s in steps:
        levels.setdefault(s["automation"], set()).add(s["wcag"])
        assert s["step"] == "9." + s["wcag"]
        assert s["title"] and s["how"] and s["level"] in ("A", "AA")
    assert levels["n/a"] == {"1.2.1", "1.2.2", "1.2.3", "1.2.4", "1.2.5", "1.4.2"}
    assert len(levels["auto"]) == 30 and len(levels["partial"]) == 14
    # bitv_map keeps its API and reads its titles from the catalogue
    assert CRITERIA["1.4.3"] == "Contrast (Minimum)" and criterion_of("wcag1410") == "1.4.10"


def _rule(rid, outcome, tags, help_="h"):
    return {"id": rid, "tags": tags, "outcome": outcome, "impact": "serious" if outcome == "violation" else None,
            "help": help_, "nodes": 1, "targets": ["#x"] if outcome == "violation" else []}


def test_axe_failure_fails_only_the_steps_of_the_violated_rule():
    axe = results._merge_axe([[
        _rule("color-contrast", "violation", ["wcag2aa", "wcag143"], "Contrast"),
        _rule("image-alt", "pass", ["wcag2a", "wcag111"]),
        _rule("meta-refresh", "inapplicable", ["wcag2a", "wcag221"]),
    ]])
    rec = {"steps": ["9.1.4.3", "9.1.1.1", "9.2.2.1"], "outcome": "failed", "when": "call", "axe": axe,
           "message": "1 accessibility rule(s) violated on kb [en, light] as loaded:"}
    out = results.step_outcomes(rec)
    assert out["9.1.4.3"]["outcome"] == "failed" and "color-contrast" in out["9.1.4.3"]["message"]
    assert out["9.1.1.1"]["outcome"] == "passed"
    assert out["9.2.2.1"]["outcome"] == "skipped"  # nothing was checked


def test_passing_axe_test_does_not_pass_steps_it_could_not_check():
    axe = results._merge_axe([[_rule("meta-refresh", "inapplicable", ["wcag2a", "wcag221"]),
                               _rule("image-alt", "pass", ["wcag2a", "wcag111"])]])
    out = results.step_outcomes({"steps": ["9.2.2.1", "9.1.1.1"], "outcome": "passed", "axe": axe})
    assert out["9.2.2.1"]["outcome"] == "skipped" and out["9.1.1.1"]["outcome"] == "passed"


def test_non_axe_failure_fails_every_marked_step():
    rec = {"steps": ["9.2.1.1", "9.2.1.2"], "outcome": "failed", "when": "call", "axe": None,
           "message": "1 keyboard issue(s) on kb [en]:\n  not reachable with Tab: <button>"}
    out = results.step_outcomes(rec)
    assert {o["outcome"] for o in out.values()} == {"failed"}


def test_best_practice_rules_map_to_steps():
    assert "9.1.3.1" in results.rule_steps("heading-order", ["cat.semantics", "best-practice"])
    assert results.rule_steps("color-contrast", ["wcag2aa", "wcag143"]) == ["9.1.4.3"]
    assert results.rule_steps("color-contrast-enhanced", ["wcag2aaa", "wcag146"]) == []  # AAA: out of scope


def _results():
    tests = {
        "tests/a11y/test_axe.py::test_wcag[kb-en]": {"steps": ["9.1.4.3", "9.1.1.1"], "outcome": "passed", "axe": None},
        "tests/a11y/test_visual.py::test_reflow[de-kb]": {"steps": ["9.1.4.10"], "outcome": "failed", "when": "call",
                                                          "message": "page scrolls horizontally", "axe": None},
        "tests/a11y/test_visual.py::test_forced[kb]": {"steps": ["11.7"], "outcome": "passed", "axe": None},
    }
    meta = {"langs": ["en", "de"], "themes": ["light"], "pages": {"kb": "/v2/kb"}, "axe_version": "4.13.0"}
    return results.build_results(tests, meta)


def test_report_statuses_totals_and_review_notes():
    llm = {"model": "x", "steps": {"1.1.1": {"verdict": "ok", "notes": ["alt texts fit"]}}}
    rep = conformance.build_report(_results(), llm, now=dt.datetime(2026, 10, 4, tzinfo=dt.timezone.utc), commit="abc")
    by = {s["step"]: s for s in rep["steps"]}
    assert by["9.1.4.3"]["status"] == "pass"                      # auto, passed
    assert by["9.1.1.1"]["status"] == "manual review pending"     # partial, automated part passed
    assert by["9.1.4.10"]["status"] == "fail"
    assert by["9.1.4.10"]["failures"] == ["test_reflow[de-kb]: page scrolls horizontally"]
    assert by["9.2.1.1"]["status"] == "not tested"
    assert by["9.1.2.1"]["status"] == "n/a"
    assert by["9.1.1.1"]["review"]["notes"] == "alt texts fit"
    assert rep["review"] == {"model": "x"}
    assert rep["beyond"][0]["step"] == "11.7" and rep["beyond"][0]["status"] == "pass"
    t = rep["totals"]
    assert t["applicable"] == 44 and t["automation"]["auto"]["count"] == 30
    assert t["automation"]["auto"]["percent"] == 68.2
    assert t["status"]["fail"]["count"] == 1
    assert t["tests"] == {"run": 3, "passed": 2, "failed": 1, "skipped": 0}
    assert rep["conformance"]["status"] == "partially conformant"
    assert rep["commit"] == "abc" and rep["axe_version"] == "4.13.0" and rep["tested"]["languages"] == ["en", "de"]
    json.dumps(rep)


def test_report_without_results_is_honest():
    rep = conformance.build_report(None)
    assert {s["status"] for s in rep["steps"]} == {"not tested", "n/a"}


def test_cli_writes_the_report(tmp_path):
    res = tmp_path / "res.json"
    res.write_text(json.dumps(_results()), encoding="utf-8")
    out = tmp_path / "bitv-report.json"
    assert conformance.main(["--results", str(res), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["totals"]["steps"] == 50


def test_docs_table_lists_every_step_and_marked_tests():
    marked = conformance.marked_tests()
    # the axe tests are marked through the AXE_WCAG_STEPS tuple
    assert "test_wcag_rules_as_loaded" in marked["9.1.4.3"]
    assert "test_reflow_at_320_css_px" in marked["9.1.4.10"]
    table = conformance.docs_table()
    assert all(f"| {s['step']} |" in table for s in CAT["steps"])
