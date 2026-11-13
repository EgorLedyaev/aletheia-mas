"""W3: per-receptor retrospective docking validation with measured inactives, Vina vs Vinardo.

Design (pre-registered in docs/preregistration.md):
  * actives   = ChEMBL activities against the receptor's target with pChEMBL >= 7.0
  * decoys    = MEASURED INACTIVES: ChEMBL activities against the SAME target with pChEMBL <= 5.0,
                property-matched to the actives on MW and cLogP. Absence of a measurement is not
                inactivity, so presumed-inactive decoys are used only to top up and are counted
                separately in the output.
  * >= 30 per class per receptor, >= 3 receptors, at least one non-kinase.
  * every ligand is docked twice into the same box: --scoring vina and --scoring vinardo.
  * metrics: ROC AUC (+ 2000x bootstrap CI), EF1/5/10%, score gap; and the paired bootstrap
    interval for AUC(vinardo) - AUC(vina).

Resumable: every (receptor, scoring, ligand) result is cached in eval/docking_bench_cache.json.

    python scripts/bench_docking.py --n 35 --workers 12
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import random
import re
import statistics
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aletheia.core.config import load_config                       # noqa: E402
from aletheia.core.registry import ToolRegistry                    # noqa: E402
from aletheia.tools import register_all                            # noqa: E402
from aletheia.tools.docking import _vina_bin                       # noqa: E402
from aletheia.tools.http import get_json                           # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, "eval", "docking_bench_cache.json")
LOCK = threading.Lock()

RECEPTORS = [
    {"pdb": "8A27", "chain": None, "accession": "P00533", "target": "CHEMBL203",
     "label": "EGFR kinase domain (8A27, 1.07 A)", "family": "kinase"},
    {"pdb": "1M17", "chain": "A", "accession": "P00533", "target": "CHEMBL203",
     "label": "EGFR kinase domain (1M17, erlotinib co-crystal)", "family": "kinase"},
    {"pdb": "1OYT", "chain": "H", "accession": "P00734", "target": "CHEMBL204",
     "label": "Thrombin (1OYT, non-kinase serine protease)", "family": "serine protease",
     "ligand_file": "eval/pubchem_thrombin.json"},
]


def load_cache():
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)
    os.replace(tmp, CACHE)


def chembl_activities(target, limit=1000, lo=None, hi=None):
    """Live ChEMBL activities with an explicit pChEMBL window."""
    params = {"target_chembl_id": target, "limit": 1000, "offset": 0}
    if lo is not None:
        params["pchembl_value__gte"] = lo
    if hi is not None:
        params["pchembl_value__lte"] = hi
    out, seen = [], set()
    while len(out) < limit:
        d = get_json("https://www.ebi.ac.uk/chembl/api/data/activity.json", dict(params))
        acts = d.get("activities", [])
        if not acts:
            break
        for a in acts:
            cid, smi = a.get("molecule_chembl_id"), a.get("canonical_smiles")
            if not cid or not smi or cid in seen:
                continue
            seen.add(cid)
            out.append({"molecule_chembl_id": cid, "smiles": smi,
                        "pchembl_value": float(a["pchembl_value"]),
                        "standard_type": a.get("standard_type")})
        if not d.get("page_meta", {}).get("next"):
            break
        params["offset"] += 1000
    return out


def cached_activities(target):
    """Activities for a target from this system's own tool cache.

    Used when the ChEMBL web API is unavailable. Per molecule the MAXIMUM pChEMBL across cached
    records is taken (pre-registered), so a molecule with any potent measurement can never be
    drawn as a decoy. Every record keeps its molecule_chembl_id, so the provenance of each ligand
    is still a ChEMBL accession.
    """
    import glob as _glob
    best = {}
    n_files, n_records = 0, 0
    for fp in _glob.glob(os.path.join(HERE, "cache", "tools", "chembl_activities", "*")):
        try:
            with open(fp, encoding="utf-8") as fh:
                blob = json.load(fh)
        except Exception:
            continue
        data = blob.get("data", blob)
        acts = data.get("activities") if isinstance(data, dict) else None
        if not acts:
            continue
        used = False
        for a in acts:
            if a.get("target_chembl_id") != target:
                continue
            cid = a.get("molecule_chembl_id")
            smi = a.get("canonical_smiles") or a.get("smiles")
            val = a.get("pchembl_value")
            if not (cid and smi and val is not None):
                continue
            used = True
            n_records += 1
            val = float(val)
            if cid not in best or val > best[cid]["pchembl_value"]:
                best[cid] = {"molecule_chembl_id": cid, "smiles": smi, "pchembl_value": val,
                             "standard_type": a.get("standard_type")}
        n_files += int(used)
    return list(best.values()), {"cache_files": n_files, "cached_records": n_records}


def split_actives_inactives(records, active_cut=7.0, inactive_cut=5.0):
    act = [r for r in records if r["pchembl_value"] >= active_cut]
    ina = [r for r in records if r["pchembl_value"] <= inactive_cut]
    return act, ina


def props(smiles):
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Crippen, Descriptors
    RDLogger.DisableLog("rdApp.*")
    m = Chem.MolFromSmiles(smiles)
    if m is None or m.GetNumHeavyAtoms() < 12 or Descriptors.MolWt(m) > 700:
        return None
    return {"mw": Descriptors.MolWt(m), "clogp": Crippen.MolLogP(m),
            "heavy": m.GetNumHeavyAtoms()}


def property_match(actives, pool, n, seed=42):
    """Greedy nearest match on (MW, cLogP); each decoy used once."""
    rng = random.Random(seed)
    pool = list(pool)
    rng.shuffle(pool)
    picked, used = [], set()
    for a in actives[:n]:
        best = None
        for c in pool:
            if c["molecule_chembl_id"] in used:
                continue
            d = abs(c["mw"] - a["mw"]) / 50.0 + abs(c["clogp"] - a["clogp"]) / 1.5
            if best is None or d < best[0]:
                best = (d, c)
        if best is not None:
            used.add(best[1]["molecule_chembl_id"])
            picked.append(best[1])
    return picked


def dock_one(vina, receptor_pdbqt, ligand_pdbqt, box, scoring, seed=42, exhaustiveness=8):
    cmd = [vina, "--receptor", receptor_pdbqt, "--ligand", ligand_pdbqt,
           "--center_x", str(box["center"][0]), "--center_y", str(box["center"][1]),
           "--center_z", str(box["center"][2]),
           "--size_x", str(box["size"][0]), "--size_y", str(box["size"][1]),
           "--size_z", str(box["size"][2]),
           "--exhaustiveness", str(exhaustiveness), "--num_modes", "9",
           "--seed", str(seed), "--cpu", "1", "--scoring", scoring]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if p.returncode != 0:
        return None, (p.stderr or p.stdout)[-200:]
    best = None
    for line in p.stdout.splitlines():
        m = re.match(r"\s*1\s+(-?\d+\.\d+)\s", line)
        if m:
            best = float(m.group(1))
            break
    return (best, None) if best is not None else (None, "no score parsed")


def roc_auc(labels, scores):
    """Scores: more negative is better."""
    pos = sum(labels)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return None
    pairs = sorted(zip(scores, labels))
    ranks, i = {}, 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    rank_sum = sum(ranks[k] for k, (_, l) in enumerate(pairs) if l == 1)
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def ef(labels, scores, frac):
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    n_top = max(1, int(round(len(scores) * frac)))
    top = order[:n_top]
    base = sum(labels) / len(labels)
    return (sum(labels[i] for i in top) / n_top) / base if base else None


def boot_auc(labels, scores, n=2000, seed=42):
    rng = random.Random(seed)
    pos = [i for i, l in enumerate(labels) if l == 1]
    neg = [i for i, l in enumerate(labels) if l == 0]
    vals = []
    for _ in range(n):
        idx = [rng.choice(pos) for _ in pos] + [rng.choice(neg) for _ in neg]
        a = roc_auc([labels[i] for i in idx], [scores[i] for i in idx])
        if a is not None:
            vals.append(a)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]


def boot_delta(labels, s_a, s_b, n=2000, seed=42):
    """Paired bootstrap of AUC(b) - AUC(a) over the same ligands."""
    rng = random.Random(seed)
    pos = [i for i, l in enumerate(labels) if l == 1]
    neg = [i for i, l in enumerate(labels) if l == 0]
    vals = []
    for _ in range(n):
        idx = [rng.choice(pos) for _ in pos] + [rng.choice(neg) for _ in neg]
        lab = [labels[i] for i in idx]
        aa = roc_auc(lab, [s_a[i] for i in idx])
        bb = roc_auc(lab, [s_b[i] for i in idx])
        if aa is not None and bb is not None:
            vals.append(bb - aa)
    vals.sort()
    return (statistics.fmean(vals), vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=35, help="ligands per class per receptor")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--exhaustiveness", type=int, default=8)
    ap.add_argument("--only", default=None, help="comma-separated PDB ids")
    ap.add_argument("--source", default="cache", choices=["cache", "api"],
                    help="where ligand activity records come from")
    ap.add_argument("--out", default="eval/docking_benchmark.json")
    args = ap.parse_args()

    cfg = load_config()
    reg = ToolRegistry(cfg)
    register_all(reg, cfg)
    vina = _vina_bin()
    cache = load_cache()
    t0 = time.time()
    receptors = [r for r in RECEPTORS
                 if args.only is None or r["pdb"] in args.only.upper().split(",")]
    results = []

    for rc in receptors:
        print(f"\n=== {rc['label']} ===", flush=True)
        dl = reg.call("pdb.download", entry_id=rc["pdb"])
        if not dl.ok:
            print(f"  SKIP: download failed {dl.error}", flush=True)
            continue
        lg = reg.call("pdb.ligands", pdb_path=dl.data["path"])
        big = lg.data["largest"]
        chain = rc["chain"] or big["chain"]
        rec_pdb = f"cache/docking/bench_{rc['pdb']}_rec.pdb"
        reg.call("pdb.extract_receptor", pdb_path=dl.data["path"], out_path=rec_pdb, chain=chain)
        pr = reg.call("docking.prepare_receptor", pdb_path=rec_pdb,
                      out_pdbqt=f"cache/docking/bench_{rc['pdb']}_rec.pdbqt")
        lig_pdb = f"cache/docking/bench_{rc['pdb']}_{big['resname']}.pdb"
        reg.call("pdb.extract_ligand", pdb_path=dl.data["path"], resname=big["resname"],
                 out_path=lig_pdb, chain=big["chain"])
        bx = reg.call("docking.box_from_ligand_pdb", ligand_pdb=lig_pdb, pad=5.0)
        if not (pr.ok and bx.ok):
            print(f"  SKIP: receptor prep failed -> prepare_receptor: {pr.error}; "
                  f"box: {bx.error}", flush=True)
            continue
        box = {"center": bx.data["center"], "size": bx.data["size"]}
        print(f"  receptor chain {chain}, box from co-crystal {big['resname']} "
              f"center={[round(c, 2) for c in box['center']]}", flush=True)

        if rc.get("ligand_file"):
            with open(os.path.join(HERE, rc["ligand_file"]), encoding="utf-8") as fh:
                blob = json.load(fh)
            raw_act, raw_inact = split_actives_inactives(blob["records"])
            ligand_source = (f"{blob['source']}, retrieved {blob['retrieved_at']}; "
                             f"{blob['n_assays_scanned']} assays scanned; {blob['rule']}")
        elif args.source == "cache":
            records, meta = cached_activities(rc["target"])
            raw_act, raw_inact = split_actives_inactives(records)
            ligand_source = (f"ChEMBL via this system's local tool cache "
                             f"({meta['cached_records']} records in {meta['cache_files']} cached "
                             f"responses); the ChEMBL web API was returning HTTP 500 at run time")
        else:
            raw_act = chembl_activities(rc["target"], limit=600, lo=7.0)
            raw_inact = chembl_activities(rc["target"], limit=1200, hi=5.0)
            ligand_source = "ChEMBL web API (live)"
        actives, inactives = [], []
        for src, dst in ((raw_act, actives), (raw_inact, inactives)):
            for r in src:
                pr_ = props(r["smiles"])
                if pr_:
                    dst.append({**r, **pr_})
        act_ids = {a["molecule_chembl_id"] for a in actives}
        inactives = [d for d in inactives if d["molecule_chembl_id"] not in act_ids]
        random.Random(42).shuffle(actives)
        actives = actives[: args.n]
        decoys = property_match(actives, inactives, args.n)
        print(f"  {len(actives)} actives (pChEMBL>=7), {len(decoys)} measured inactives "
              f"(pChEMBL<=5) matched from a pool of {len(inactives)}", flush=True)
        if len(actives) < 30 or len(decoys) < 30:
            print(f"  WARNING: fewer than 30 per class", flush=True)

        ligs = [{"label": 1, **a} for a in actives] + [{"label": 0, **d} for d in decoys]
        prepared = []
        for i, mol in enumerate(ligs):
            tag = hashlib.sha256(mol["smiles"].encode()).hexdigest()[:12]
            out = f"cache/docking/bench_lig_{tag}.pdbqt"
            if not os.path.exists(os.path.join(HERE, out)):
                lp = reg.call("docking.prepare_ligand", smiles=mol["smiles"], out_pdbqt=out,
                              seed=42)
                if not lp.ok:
                    if len(prepared) == 0 and i < 3:
                        print(f"    ligand prep failed: {lp.error}", flush=True)
                    continue
            prepared.append({**mol, "pdbqt": os.path.join(HERE, out), "tag": tag})
        print(f"  {len(prepared)}/{len(ligs)} ligands prepared", flush=True)

        jobs = [(scoring, m) for scoring in ("vina", "vinardo") for m in prepared]
        todo = [(s, m) for s, m in jobs
                if f"{rc['pdb']}|{s}|{m['tag']}" not in cache]
        print(f"  {len(jobs)} docking runs, {len(jobs) - len(todo)} already cached", flush=True)
        done = [0]

        def work(job):
            scoring, m = job
            key = f"{rc['pdb']}|{scoring}|{m['tag']}"
            score, err = dock_one(vina, os.path.join(HERE, pr.data["path"]), m["pdbqt"], box,
                                  scoring, exhaustiveness=args.exhaustiveness)
            with LOCK:
                cache[key] = {"score": score, "error": err}
                done[0] += 1
                if done[0] % 20 == 0:
                    save_cache(cache)
                    print(f"    {done[0]}/{len(todo)} ({time.time() - t0:.0f}s)", flush=True)
            return key

        if todo:
            with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
                list(ex.map(work, todo))
            save_cache(cache)

        rows, drop = [], 0
        for m in prepared:
            sv = cache.get(f"{rc['pdb']}|vina|{m['tag']}", {}).get("score")
            sd = cache.get(f"{rc['pdb']}|vinardo|{m['tag']}", {}).get("score")
            if sv is None or sd is None:
                drop += 1
                continue
            rows.append({"id": m["molecule_chembl_id"], "label": m["label"],
                         "pchembl": m["pchembl_value"], "vina": sv, "vinardo": sd})
        labels = [r["label"] for r in rows]
        sv = [r["vina"] for r in rows]
        sd = [r["vinardo"] for r in rows]
        entry = {"pdb": rc["pdb"], "label": rc["label"], "family": rc["family"],
                 "target": rc["target"], "accession": rc["accession"],
                 "chain": chain, "box": box, "cocrystal_ligand": big["resname"],
                 "n_actives": sum(labels), "n_decoys": len(labels) - sum(labels),
                 "n_failed_pairs": drop, "decoy_class": "measured inactive (pChEMBL <= 5)",
                 "ligand_source": ligand_source,
                 "exhaustiveness": args.exhaustiveness, "seed": 42, "scoring": {}}
        for name, sc in (("vina", sv), ("vinardo", sd)):
            if not sc:
                continue
            auc = roc_auc(labels, sc)
            lo, hi = boot_auc(labels, sc)
            a_s = [s for s, l in zip(sc, labels) if l == 1]
            d_s = [s for s, l in zip(sc, labels) if l == 0]
            entry["scoring"][name] = {
                "roc_auc": round(auc, 4), "auc_ci95": [round(lo, 4), round(hi, 4)],
                "ef_1pct": round(ef(labels, sc, 0.01), 3),
                "ef_5pct": round(ef(labels, sc, 0.05), 3),
                "ef_10pct": round(ef(labels, sc, 0.10), 3),
                "mean_active": round(statistics.fmean(a_s), 3),
                "mean_decoy": round(statistics.fmean(d_s), 3),
                "score_gap": round(statistics.fmean(d_s) - statistics.fmean(a_s), 3),
                "usable_for_ranking": bool(lo > 0.5)}
            print(f"  {name:8s} AUC {auc:.3f} [{lo:.3f}, {hi:.3f}]  "
                  f"EF10% {entry['scoring'][name]['ef_10pct']}  "
                  f"gap {entry['scoring'][name]['score_gap']:+.3f} kcal/mol", flush=True)
        if len(entry["scoring"]) == 2:
            mean, lo, hi = boot_delta(labels, sv, sd)
            entry["delta_auc_vinardo_minus_vina"] = {
                "mean": round(mean, 4), "ci95": [round(lo, 4), round(hi, 4)],
                "excludes_zero": bool(lo > 0 or hi < 0)}
            print(f"  delta AUC (vinardo - vina) {mean:+.3f} [{lo:+.3f}, {hi:+.3f}]", flush=True)
        entry["rows"] = rows
        results.append(entry)

    out = {"generated_by": "scripts/bench_docking.py",
           "vina_binary": os.path.basename(vina),
           "n_per_class_requested": args.n,
           "criterion": "docs/preregistration.md W3",
           "duration_s": round(time.time() - t0, 1),
           "receptors": results}
    path = os.path.join(HERE, args.out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(f"\nwrote {args.out} ({len(results)} receptors, {out['duration_s']}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
