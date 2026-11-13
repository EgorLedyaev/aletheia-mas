"""Routing must work with no LLM at all, and must not invent entities."""
from aletheia.agents.planner import _find_entities, _steps_for, rule_based_plan


def test_rule_based_routing_without_an_llm():
    p = rule_based_plan("Dock erlotinib into EGFR structure 1M17 and validate by redocking")
    assert "docking" in p["intents"]
    assert "1M17" in p["targets"] or "EGFR" in p["targets"]


def test_entity_extraction_rejects_accessions_as_molecules():
    """A UniProt accession in parentheses must not be parsed as a SMILES string."""
    e = _find_entities("Analyse the structure of EGFR (P00533) and find the binding site")
    assert e["molecules"] == []
    assert "P00533" in e["accessions"]


def test_entity_extraction_accepts_real_smiles():
    e = _find_entities("Profile CC(=O)Oc1ccccc1C(=O)O please")
    assert any("CC(=O)Oc1ccccc1C(=O)O" in m for m in e["molecules"])


def test_expensive_oracle_depends_on_the_cheap_gate():
    """Funnel ordering: QSAR must not score candidates the cheap filters have not seen."""
    steps = _steps_for(["generate_analogs", "rank_candidates"], ["EGFR"], [], [])
    by_id = {s.step_id: s for s in steps}
    qsar = next(s for s in steps if s.agent == "qsar_agent")
    gate = next(s for s in steps if s.agent == "property_agent"
                and s.action == "profile_candidates")
    assert gate.step_id in qsar.depends_on
    ranker = next(s for s in steps if s.agent == "ranker")
    assert qsar.step_id in ranker.depends_on
    assert all(d in by_id for s in steps for d in s.depends_on)


def test_every_plan_ends_with_the_critic():
    steps = _steps_for(["target_brief"], ["EGFR"], [], [])
    assert steps[-1].agent == "critic"
