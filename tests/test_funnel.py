"""The funnel must reconcile: one generated table, and every document must agree with it.

This test exists because the funnel was once quoted from two different runs plus one stale
mid-development capture, producing "5 survived" and "104 survived" in the same defence package.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLE = os.path.join(ROOT, "eval", "funnel_table.json")
MARKER = re.compile(r"(\d+(?:\.\d+)?)[\s*`]{0,6}<!--funnel:([A-Za-z0-9]+)\.([a-z0-9_]+)-->")
DOCS = ["docs/evaluation_report.md", "docs/negative_results.md", "docs/funnel_table.md", "docs/deck.md"]


def _load_script(name):
    path = os.path.join(ROOT, "scripts", name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def table():
    if not os.path.exists(TABLE):
        pytest.skip("run scripts/funnel_report.py first")
    with open(TABLE, encoding="utf-8") as fh:
        return json.load(fh)


def test_funnel_table_is_not_stale(table):
    """Rebuilding from the run logs must reproduce the stored table exactly."""
    fr = _load_script("funnel_report.py")
    for stored in table["funnels"]:
        fresh = fr.funnel_for_run(ROOT, stored["run_id"])
        assert fresh["counts"] == stored["counts"], (
            f"{stored['scenario']} ({stored['run_id']}): stored funnel differs from the run log; "
            "re-run scripts/funnel_report.py")


def test_funnel_arithmetic_is_internally_consistent(table):
    fr = _load_script("funnel_report.py")
    for f in table["funnels"]:
        assert fr.consistency(f) == [], f"{f['scenario']}: {fr.consistency(f)}"


def test_expensive_oracle_never_scores_more_than_the_gate_passed(table):
    """Funnel ordering: the cheap gate must precede the expensive oracle."""
    for f in table["funnels"]:
        c = f["counts"]
        if c["oracle_scored"] is not None and c["gate1_passed"] is not None:
            assert c["oracle_scored"] <= c["gate1_passed"], f["scenario"]


def test_every_document_marker_matches_the_table(table):
    """A number tagged <!--funnel:S08.gate1_passed--> must equal the generated value."""
    by = {f["scenario"]: f for f in table["funnels"]}
    checked = 0
    for rel in DOCS:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()
        for value, scen, key in MARKER.findall(text):
            assert scen in by, f"{rel}: marker names unknown run {scen}"
            expected = by[scen]["counts"].get(key)
            assert expected is not None, f"{rel}: {scen}.{key} is not a funnel stage"
            assert float(value) == float(expected), (
                f"{rel}: quotes {value} for {scen}.{key} but the generated table says {expected}")
            checked += 1
    assert checked >= 4, f"expected funnel markers in the documents, found {checked}"


def test_no_document_still_quotes_the_retracted_number(table):
    """The stale '5 survived' capture must not reappear in a funnel sentence."""
    bad = re.compile(r"(\d+)\s+unique generated structures entered the cheap-filter gate and\s+"
                     r"\*?\*?(\d+)\*?\*?\s+survived", re.S)
    by = {f["scenario"]: f for f in table["funnels"]}
    for rel in DOCS:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        for entering, survived in bad.findall(open(path, encoding="utf-8").read()):
            assert any(str(f["counts"]["after_hazard_gate"]) == entering
                       and str(f["counts"]["gate1_passed"]) == survived
                       for f in by.values()), (
                f"{rel}: '{entering} -> {survived}' matches no run in the generated table")


def test_generator_figure_data_matches_the_run_ledger():
    """Figure inputs must be derived from the run log, not carried forward by hand."""
    data_path = os.path.join(ROOT, "eval", "figure_data_s07.json")
    if not os.path.exists(data_path):
        pytest.skip("figure data not built")
    with open(data_path, encoding="utf-8") as fh:
        data = json.load(fh)
    mfd = _load_script("make_figure_data.py")
    fresh = mfd.build(ROOT, data["run_id"])
    assert fresh["generator_stats"] == data["generator_stats"], (
        "eval/figure_data_s07.json is stale; re-run scripts/make_figure_data.py")
    assert not fresh["missing_fields"], fresh["missing_fields"]


def test_no_document_states_a_generator_novelty_absent_from_the_run_log():
    """G2's novelty was once quoted as 0.00 from a stale capture; the run log says 0.075."""
    data_path = os.path.join(ROOT, "eval", "figure_data_s07.json")
    if not os.path.exists(data_path):
        pytest.skip("figure data not built")
    stats = json.load(open(data_path, encoding="utf-8"))["generator_stats"]
    allowed = {f"{v['frac_novel']:.3f}" for v in stats.values()}
    allowed |= {f"{v['frac_novel']:.2f}" for v in stats.values()}
    docs_dir = os.path.join(ROOT, "docs")
    for root, _, files in os.walk(docs_dir):
        for name in files:
            if not name.endswith(".md"):
                continue
            path = os.path.join(root, name)
            text = open(path, encoding="utf-8").read()
            for m in re.finditer(r"`?frac_novel`?\s*=\s*([0-9.]+)", text):
                assert m.group(1) in allowed, (
                    f"{os.path.relpath(path, ROOT)}: frac_novel = {m.group(1)} is not a value in "
                    f"the run log ({sorted(allowed)})")


def test_retracted_docking_numbers_carry_a_supersede_note():
    """The 10-vs-10 presumed-decoy enrichment and the Vina redock must not read as current."""
    path = os.path.join(ROOT, "docs", "evaluation_report.md")
    text = open(path, encoding="utf-8").read()
    if "ROC AUC 0.42" in text or "4.188" in text:
        assert "Superseded" in text, (
            "evaluation_report.md still quotes the retracted docking numbers without a "
            "supersede note pointing at the systematic validation")
        assert "section 9.1" in text
