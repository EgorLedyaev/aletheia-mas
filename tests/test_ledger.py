"""The claims ledger is the project's central promise; these tests are its contract."""
import pytest

from aletheia.core.contracts import AnswerBlock
from aletheia.core.ledger import AnswerVerifier, ClaimsLedger, LedgerViolation
from aletheia.core.provenance import Applicability, Evidence, EvidenceTag, Uncertainty


def _ledger():
    return ClaimsLedger("test-run")


def test_computed_requires_reproducibility_fields():
    L = _ledger()
    with pytest.raises(ValueError):
        L.register(tag="COMPUTED", key="MolWt", value=180.16)          # no tool/version/hash
    ev = L.register(tag="COMPUTED", key="MolWt", value=180.16, tool="rdkit.descriptors",
                    tool_version="2026.09.2", params_hash="abc123")
    assert ev.claim_id == "E-0001"


def test_retrieved_requires_accession_and_date():
    L = _ledger()
    with pytest.raises(ValueError):
        L.register(tag="RETRIEVED", key="protein_name", value="EGFR")
    L.register(tag="RETRIEVED", key="protein_name", value="EGFR", source_id="P00533",
               retrieved_at="2026-11-11T00:00:00+00:00")


def test_predicted_requires_uncertainty_or_explicit_absence():
    L = _ledger()
    with pytest.raises(ValueError):
        L.register(tag="PREDICTED", key="pIC50", value=7.5, tool="qsar", tool_version="1.0",
                   applicability=Applicability.IN_DOMAIN)
    L.register(tag="PREDICTED", key="pIC50", value=7.5, tool="qsar", tool_version="1.0",
               applicability=Applicability.IN_DOMAIN,
               uncertainty=Uncertainty(kind="conformal", lower=6.0, upper=9.0, level=0.9))
    L.register(tag="PREDICTED", key="logS", value=-4.2, tool="esol", tool_version="1.0",
               applicability=Applicability.NOT_ASSESSED,
               note="uncertainty_unavailable: literature equation")


def test_hypothesis_may_not_carry_a_number():
    """The anti-fabrication rule: LLM reasoning cannot emit a numeric result."""
    L = _ledger()
    with pytest.raises(ValueError):
        L.register(tag="HYPOTHESIS", key="likely_ic50_nM", value=12.5, note="it feels potent")
    L.register(tag="HYPOTHESIS", key="mechanism", value="probably ATP-competitive",
               note="based on the retrieved scaffold class")


def test_verifier_blocks_an_untraceable_number():
    L = _ledger()
    ev = L.register(tag="COMPUTED", key="MolWt", value=180.16, tool="rdkit.descriptors",
                    tool_version="2026.09.2", params_hash="abc123")
    v = AnswerVerifier(L)
    ok = v.verify([AnswerBlock(title="t", text=f"MW is 180.16 [{ev.claim_id}]",
                               claim_ids=[ev.claim_id])])
    assert ok.ok and ok.numeric_coverage == 1.0

    bad = v.verify([AnswerBlock(title="t", text=f"MW is 180.16 and the IC50 is 42 nM "
                                                f"[{ev.claim_id}]", claim_ids=[ev.claim_id])])
    assert not bad.ok
    assert any(x.kind == "UNTRACEABLE_NUMBER" and x.token == "42" for x in bad.violations)
    with pytest.raises(LedgerViolation):
        v.enforce([AnswerBlock(title="t", text="the IC50 is 42 nM", claim_ids=[ev.claim_id])])


def test_verifier_accepts_display_rounding():
    """f"{0.3385:.3f}" prints 0.339; a tolerance-only comparison rejects it by 5e-19."""
    L = _ledger()
    ev = L.register(tag="COMPUTED", key="spearman", value=0.3385, tool="qsar.fit",
                    tool_version="1.0", params_hash="h")
    rep = AnswerVerifier(L).verify([AnswerBlock(title="t", text=f"rho 0.339 [{ev.claim_id}]",
                                                claim_ids=[ev.claim_id])])
    assert rep.ok, [v.detail for v in rep.violations]


def test_verifier_ignores_provenance_metadata_digits():
    """Tool versions, accessions, dates and unit labels are not claims."""
    L = _ledger()
    ev = L.register(tag="COMPUTED", key="volume", value=445.0, units="A^3",
                    tool="pocket.detect", tool_version="ligsite-like-1.0", params_hash="h")
    ev2 = L.register(tag="RETRIEVED", key="name", value="EGFR", source_id="P00533",
                     retrieved_at="2026-11-11T12:00:00+00:00")
    text = (f"volume 445 A^3 [{ev.claim_id}] — COMPUTED | pocket.detect ligsite-like-1.0; "
            f"name EGFR [{ev2.claim_id}] — RETRIEVED | P00533 @ 2026-11-11")
    rep = AnswerVerifier(L).verify([AnswerBlock(title="t", text=text,
                                                claim_ids=[ev.claim_id, ev2.claim_id])])
    assert rep.ok, [v.detail for v in rep.violations]


def test_verifier_flags_overclaiming_language():
    L = _ledger()
    ev = L.register(tag="COMPUTED", key="x", value=1.0, tool="t", tool_version="1", params_hash="h")
    rep = AnswerVerifier(L).verify([AnswerBlock(title="t", text=f"This is a proven hit [{ev.claim_id}]",
                                                claim_ids=[ev.claim_id])])
    assert any(v.kind == "OVERCLAIM" for v in rep.violations)
