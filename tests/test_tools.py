"""Tool-level contracts: chemistry correctness and cache integrity."""
from aletheia.core.config import load_config
from aletheia.core.registry import ToolRegistry, _code_hash
from aletheia.tools import hazard, qsar_tools, rdkit_tools
from aletheia.tools.docking import AD_TYPE_TO_ELEMENT, _element


def test_descriptors_are_deterministic_and_correct():
    d = rdkit_tools.descriptors("CC(=O)Oc1ccccc1C(=O)O")        # aspirin
    assert abs(d["MolWt"] - 180.159) < 0.01
    assert d["HBD"] == 1 and d["HBA"] == 3
    assert 0 < d["QED"] < 1


def test_alerts_use_real_catalogs():
    a = rdkit_tools.alerts("CC(=O)Oc1ccccc1C(=O)O")
    assert a["catalog_sizes"]["PAINS"] > 100
    assert set(a["alerts"]) == {"PAINS", "BRENK", "NIH"}


def test_hazard_screen_classifies_severity():
    assert hazard.screen("CC(=O)Oc1ccccc1C(=O)O")["severity"] in ("CLEAR", "NOTE")
    # bis(2-chloroethyl) sulfide motif -> chemical-weapon class
    assert hazard.screen("ClCCSCCCl")["severity"] == "BLOCK"
    # 4-anilidopiperidine core -> controlled-substance class
    assert hazard.screen("O=C(CC)N(c1ccccc1)C1CCNCC1")["severity"] == "REVIEW"


def test_pdbqt_atom_types_map_to_elements():
    """PDBQT stores AutoDock types, not elements: A->C, NA->N, OA->O, HD->H."""
    assert _element("A") == "C" and _element("NA") == "N"
    assert _element("OA") == "O" and _element("HD") == "H"
    assert _element("CL") == "Cl" and _element("N") == "N"
    assert AD_TYPE_TO_ELEMENT["SA"] == "S"


def test_scaffold_split_holds_whole_scaffolds_out():
    smiles = ["c1ccccc1C(=O)O", "c1ccccc1C(=O)OC", "c1ccccc1C(=O)N",
              "C1CCNCC1", "C1CCNCC1C", "C1CCNCC1CC",
              "c1ccc2ccccc2c1", "c1ccc2ccccc2c1C", "CCCCCCO", "CCCCCCCO"]
    from rdkit import Chem
    from rdkit.Chem.Scaffolds import MurckoScaffold
    sp = qsar_tools.scaffold_split(smiles, test_frac=0.3, seed=1)

    def scaf(i):
        m = Chem.MolFromSmiles(smiles[i])
        return Chem.MolToSmiles(MurckoScaffold.GetScaffoldForMol(m))

    train = {scaf(i) for i in sp["train_idx"]}
    test = {scaf(i) for i in sp["test_idx"]}
    assert not (train & test), "a scaffold appears on both sides of the split"


def test_cache_key_changes_when_tool_code_changes():
    """A fixed tool must not keep serving pre-fix cached numbers."""
    def f(x):
        return {"v": x}

    def f2(x):
        return {"v": x + 1}

    assert _code_hash(f) != _code_hash(f2)


def test_registry_rejects_unknown_tool():
    cfg = load_config()
    reg = ToolRegistry(cfg)
    from aletheia.tools import register_all
    register_all(reg, cfg)
    assert "rdkit.descriptors" in reg.names()
    try:
        reg.call("does.not.exist")
    except Exception as exc:
        assert "not registered" in str(exc)
    else:                                            # pragma: no cover
        raise AssertionError("unknown tool did not raise")
