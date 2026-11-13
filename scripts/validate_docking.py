"""Decoy-enrichment validation of the docking setup (slow, cached, run once per receptor).

What it does: docks N known actives for the target and N property-matched presumed-inactive
molecules into the same prepared receptor and reports ROC AUC and enrichment factors over the
pooled ranking.

Honest limitation, printed with the result: the decoys are *presumed* inactive because they have
no measured activity against this target in ChEMBL -- they are not measured inactives. Enrichment
computed this way is a sanity check on the docking setup, not a benchmark result.

    python scripts/validate_docking.py --pdb 1M17 --accession P00533 --n 10
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aletheia.core.config import load_config                      # noqa: E402
from aletheia.core.registry import ToolRegistry                   # noqa: E402
from aletheia.tools import register_all                           # noqa: E402
from aletheia.tools.http import get_json                           # noqa: E402


def property_matched_decoys(actives, n, seed=42, pool_size=600):
    """Draw molecules with no measured activity on the target, matched on MW and cLogP."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Crippen, Descriptors
    RDLogger.DisableLog("rdApp.*")
    rng = random.Random(seed)
    act_props = []
    for a in actives:
        m = Chem.MolFromSmiles(a["smiles"])
        if m:
            act_props.append((Descriptors.MolWt(m), Crippen.MolLogP(m)))
    lo_mw = min(p[0] for p in act_props) - 50
    hi_mw = max(p[0] for p in act_props) + 50
    d = get_json("https://www.ebi.ac.uk/chembl/api/data/molecule.json",
                 {"molecule_properties__full_mwt__gte": int(lo_mw),
                  "molecule_properties__full_mwt__lte": int(hi_mw),
                  "molecule_type": "Small molecule", "limit": pool_size})
    active_keys = {a["molecule_chembl_id"] for a in actives}
    pool = []
    for mol in d.get("molecules", []):
        st = mol.get("molecule_structures") or {}
        smi = st.get("canonical_smiles")
        if not smi or mol.get("molecule_chembl_id") in active_keys:
            continue
        m = Chem.MolFromSmiles(smi)
        if m is None or m.GetNumHeavyAtoms() < 15:
            continue
        pool.append({"molecule_chembl_id": mol["molecule_chembl_id"], "smiles": smi,
                     "mw": Descriptors.MolWt(m), "clogp": Crippen.MolLogP(m)})
    rng.shuffle(pool)
    picked, used = [], set()
    for mw, lp in act_props[:n]:
        best = None
        for c in pool:
            if c["molecule_chembl_id"] in used:
                continue
            dist = abs(c["mw"] - mw) / 50.0 + abs(c["clogp"] - lp) / 1.5
            if best is None or dist < best[0]:
                best = (dist, c)
        if best:
            used.add(best[1]["molecule_chembl_id"])
            picked.append(best[1])
    return picked, {"pool_size": len(pool), "mw_window": [round(lo_mw, 1), round(hi_mw, 1)]}


def roc_auc(labels, scores):
    """AUC with more-negative-is-better scores (Vina convention)."""
    pairs = sorted(zip(scores, labels))
    pos = sum(labels)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return None
    rank_sum, i = 0.0, 0
    ranks = {}
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg_rank
        i = j + 1
    for k, (s, l) in enumerate(pairs):
        if l == 1:
            rank_sum += ranks[k]
    return round((rank_sum - pos * (pos + 1) / 2.0) / (pos * neg), 4)


def enrichment_factor(labels, scores, frac):
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    n_top = max(1, int(round(len(scores) * frac)))
    top = order[:n_top]
    hit_rate_top = sum(labels[i] for i in top) / n_top
    hit_rate_all = sum(labels) / len(labels)
    return round(hit_rate_top / hit_rate_all, 3) if hit_rate_all else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdb", default="1M17")
    ap.add_argument("--accession", default="P00533")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--exhaustiveness", type=int, default=8)
    ap.add_argument("--out", default="eval/docking_validation.json")
    args = ap.parse_args()

    cfg = load_config()
    reg = ToolRegistry(cfg)
    register_all(reg, cfg)
    t0 = time.time()

    dl = reg.call("pdb.download", entry_id=args.pdb)
    lg = reg.call("pdb.ligands", pdb_path=dl.data["path"])
    big = lg.data["largest"]
    rec_pdb = f"cache/docking/{args.pdb}_val_rec.pdb"
    reg.call("pdb.extract_receptor", pdb_path=dl.data["path"], out_path=rec_pdb, chain=big["chain"])
    pr = reg.call("docking.prepare_receptor", pdb_path=rec_pdb,
                  out_pdbqt=f"cache/docking/{args.pdb}_val_rec.pdbqt")
    lig_pdb = f"cache/docking/{args.pdb}_val_{big['resname']}.pdb"
    reg.call("pdb.extract_ligand", pdb_path=dl.data["path"], resname=big["resname"],
             out_path=lig_pdb, chain=big["chain"])
    bx = reg.call("docking.box_from_ligand_pdb", ligand_pdb=lig_pdb, pad=5.0)

    def need(res, what):
        if not res.ok:
            print(f"FATAL: {what} failed -> {res.error}", flush=True)
            raise SystemExit(2)
        return res

    need(dl, "pdb.download")
    need(pr, "docking.prepare_receptor")
    need(bx, "docking.box_from_ligand_pdb")
    tg = need(reg.call("chembl.target_by_accession", accession=args.accession),
              "chembl.target_by_accession")
    ac = need(reg.call("chembl.activities",
                       target_chembl_id=tg.data["preferred"]["target_chembl_id"], limit=400),
              "chembl.activities")
    actives = [a for a in ac.data["activities"] if a["pchembl_value"] >= 7.0][: args.n]
    decoys, decoy_meta = property_matched_decoys(actives, args.n)
    print(f"{len(actives)} actives (pChEMBL>=7), {len(decoys)} property-matched decoys "
          f"from a pool of {decoy_meta['pool_size']}", flush=True)

    rows = []
    for label, group in ((1, actives), (0, decoys)):
        for i, mol in enumerate(group):
            tag = f"{'act' if label else 'dec'}{i:02d}"
            lp = reg.call("docking.prepare_ligand", smiles=mol["smiles"],
                          out_pdbqt=f"cache/docking/val_{args.pdb}_{tag}.pdbqt", seed=42)
            if not lp.ok:
                print(f"  {tag}: ligand prep failed ({lp.error})", flush=True)
                continue
            dk = reg.call("docking.vina_dock", receptor_pdbqt=pr.data["path"],
                          ligand_pdbqt=lp.data["path"], center=bx.data["center"],
                          size=bx.data["size"],
                          out_pdbqt=f"cache/docking/val_{args.pdb}_{tag}_out.pdbqt",
                          exhaustiveness=args.exhaustiveness, num_modes=9, seed=42)
            if not dk.ok:
                print(f"  {tag}: docking failed ({dk.error})", flush=True)
                continue
            rows.append({"id": mol.get("molecule_chembl_id"), "label": label, "tag": tag,
                         "smiles": mol["smiles"],
                         "score": dk.data["best_score_kcal_per_mol"],
                         "pchembl": mol.get("pchembl_value"),
                         "cached": dk.cached})
            print(f"  {tag} {mol.get('molecule_chembl_id')}: "
                  f"{dk.data['best_score_kcal_per_mol']:.2f} kcal/mol"
                  f"{' (cached)' if dk.cached else ''}", flush=True)

    labels = [r["label"] for r in rows]
    scores = [r["score"] for r in rows]
    act_scores = [r["score"] for r in rows if r["label"] == 1]
    dec_scores = [r["score"] for r in rows if r["label"] == 0]
    result = {
        "pdb_id": args.pdb, "accession": args.accession,
        "n_actives": sum(labels), "n_decoys": len(labels) - sum(labels),
        "roc_auc": roc_auc(labels, scores),
        "ef_10pct": enrichment_factor(labels, scores, 0.10),
        "ef_20pct": enrichment_factor(labels, scores, 0.20),
        "mean_score_actives": round(statistics.fmean(act_scores), 3) if act_scores else None,
        "mean_score_decoys": round(statistics.fmean(dec_scores), 3) if dec_scores else None,
        "score_gap": round(statistics.fmean(dec_scores) - statistics.fmean(act_scores), 3)
        if act_scores and dec_scores else None,
        "exhaustiveness": args.exhaustiveness, "seed": 42,
        "box": {"center": bx.data["center"], "size": bx.data["size"],
                "origin": f"co-crystal ligand {big['resname']}"},
        "decoy_selection": {"method": "property-matched (MW, cLogP) ChEMBL small molecules with "
                                      "no measured activity against this target",
                            **decoy_meta},
        "limitation": "decoys are PRESUMED inactive (absence of a ChEMBL measurement), not "
                      "measured inactives; this is a setup sanity check, not a benchmark",
        "duration_s": round(time.time() - t0, 1),
        "rows": rows,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
