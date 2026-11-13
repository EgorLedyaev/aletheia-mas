"""Docking tools built on AutoDock Vina 1.2.7 (Apache-2.0) + Open Babel for file preparation.

Design notes
------------
* Scores are COMPUTED (a real binary ran) but they are *not* binding affinities: the module
  always reports them as Vina scores in kcal/mol together with a redocking RMSD for the same
  receptor, so a reader can judge how much the ranking is worth.
* Pose RMSD is computed by optimal element-matched atom assignment (Hungarian) with no
  re-superposition, because docked and crystal poses already share a coordinate frame. This
  handles topological symmetry without needing bond perception on a PDBQT file.
* Contacts are plain geometric criteria (distance cut-offs), not a PLIP-grade interaction
  model; the output says so.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

VERSION = "vina-1.2.7+obabel"
LICENSE = "Apache-2.0 (Vina); GPL-2.0 (Open Babel)"
_CFG: Dict[str, Any] = {}

# PDBQT stores AutoDock atom *types* in the element column (A = aromatic carbon,
# NA/OA/SA = hydrogen-bond-accepting N/O/S, HD = polar hydrogen). They must be mapped back to
# chemical elements before any geometric comparison against a PDB file.
AD_TYPE_TO_ELEMENT = {
    "A": "C", "C": "C", "CA": "C", "CD": "C",
    "N": "N", "NA": "N", "NS": "N", "NX": "N",
    "O": "O", "OA": "O", "OS": "O", "OX": "O",
    "S": "S", "SA": "S",
    "H": "H", "HD": "H", "HS": "H",
    "P": "P", "F": "F", "CL": "Cl", "BR": "Br", "I": "I", "SI": "Si", "B": "B", "SE": "Se",
    "FE": "Fe", "ZN": "Zn", "MG": "Mg", "MN": "Mn", "CU": "Cu", "NI": "Ni", "CO": "Co",
    "K": "K", "LI": "Li", "W": "W",
}


def _element(tok: str) -> str:
    """Normalise a PDB element symbol or an AutoDock atom type to a chemical element."""
    t = (tok or "").strip().upper()
    if not t:
        return ""
    if t in AD_TYPE_TO_ELEMENT:
        return AD_TYPE_TO_ELEMENT[t]
    return t.capitalize() if len(t) > 1 else t


def _vina_bin() -> str:
    b = _CFG.get("vina_bin") or os.environ.get("VINA_BIN") or "tools/vina/vina_1.2.7_win.exe"
    if not os.path.exists(b):
        alt = shutil.which("vina") or shutil.which("vina.exe")
        if alt:
            return alt
        raise FileNotFoundError(
            f"AutoDock Vina binary not found at {b!r}. Run `make setup` (downloads the official "
            "release binary) or set VINA_BIN.")
    return b


def _obabel() -> str:
    """Locate obabel. PATH first, then the directories a conda environment installs it into.

    A background shell that does not inherit the environment's Library\\bin would otherwise fail
    every ligand preparation silently, which is how one benchmark run lost 64 of 70 ligands.
    """
    exe = shutil.which("obabel") or shutil.which("obabel.exe")
    if exe:
        return exe
    import sys as _sys
    roots = [os.path.join(_sys.prefix, "Library", "bin"), os.path.join(_sys.prefix, "bin"),
             os.path.join(os.path.dirname(_sys.executable), "Library", "bin")]
    for root in roots:
        for name in ("obabel.exe", "obabel"):
            cand = os.path.join(root, name)
            if os.path.exists(cand):
                return cand
    raise FileNotFoundError("Open Babel (obabel) not found on PATH or in the interpreter's "
                            "environment; it prepares PDBQT files.")


def _run(cmd: List[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def vina_version() -> Dict[str, Any]:
    """Report the exact Vina build and its hash -- recorded with every docking claim."""
    b = _vina_bin()
    out = _run([b, "--version"]).stdout.strip()
    return {"binary": b.replace("\\", "/"), "version": out.splitlines()[0] if out else None,
            "sha256": hashlib.sha256(open(b, "rb").read()).hexdigest()}


def prepare_receptor(pdb_path: str, out_pdbqt: str, ph: float = 7.4) -> Dict[str, Any]:
    """Protein PDB -> rigid receptor PDBQT (Open Babel, hydrogens added at the given pH)."""
    os.makedirs(os.path.dirname(out_pdbqt) or ".", exist_ok=True)
    r = _run([_obabel(), pdb_path, "-O", out_pdbqt, "-xr", "-p", str(ph)])
    if not os.path.exists(out_pdbqt) or os.path.getsize(out_pdbqt) == 0:
        raise RuntimeError(f"obabel failed to write receptor PDBQT: {(r.stderr or r.stdout)[:300]}")
    n = sum(1 for ln in open(out_pdbqt, encoding="utf-8", errors="ignore")
            if ln.startswith(("ATOM", "HETATM")))
    return {"path": out_pdbqt.replace("\\", "/"), "n_atoms": n, "ph": ph,
            "sha256": hashlib.sha256(open(out_pdbqt, "rb").read()).hexdigest(),
            "obabel_stderr": (r.stderr or "").strip()[:200]}


def prepare_ligand(smiles: str, out_pdbqt: str, seed: int = 42, ph: float = 7.4,
                   n_confs: int = 1, max_iters: int = 500) -> Dict[str, Any]:
    """SMILES -> 3D, MMFF-minimised ligand PDBQT (RDKit embedding, Open Babel conversion)."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    os.makedirs(os.path.dirname(out_pdbqt) or ".", exist_ok=True)
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        raise ValueError(f"invalid SMILES: {smiles!r}")
    m = Chem.AddHs(m)
    ps = AllChem.ETKDGv3()
    ps.randomSeed = seed
    cids = AllChem.EmbedMultipleConfs(m, numConfs=n_confs, params=ps)
    if len(cids) == 0:
        raise RuntimeError(f"3D embedding failed for {smiles!r}")
    energies = []
    try:
        res = AllChem.MMFFOptimizeMoleculeConfs(m, maxIters=max_iters)
        energies = [float(e) for _, e in res]
        best = int(min(range(len(energies)), key=lambda i: energies[i]))
        ff_used = "MMFF94"
    except Exception:
        best, ff_used = 0, "none"
    sdf = os.path.splitext(out_pdbqt)[0] + ".sdf"
    wr = Chem.SDWriter(sdf)
    wr.write(m, confId=int(cids[best]))
    wr.close()
    r = _run([_obabel(), sdf, "-O", out_pdbqt, "-p", str(ph)])
    if not os.path.exists(out_pdbqt) or os.path.getsize(out_pdbqt) == 0:
        raise RuntimeError(f"obabel failed to write ligand PDBQT: {(r.stderr or r.stdout)[:300]}")
    return {"path": out_pdbqt.replace("\\", "/"), "sdf_path": sdf.replace("\\", "/"),
            "smiles": smiles, "n_confs": len(cids), "forcefield": ff_used,
            "mmff_energy": round(energies[best], 3) if energies else None,
            "n_heavy_atoms": Chem.RemoveHs(m).GetNumHeavyAtoms(), "seed": seed,
            "n_rotatable": sum(1 for ln in open(out_pdbqt, encoding="utf-8", errors="ignore")
                               if ln.startswith("BRANCH"))}


def box_from_points(points: List[List[float]], pad: float = 5.0,
                    min_size: float = 18.0) -> Dict[str, Any]:
    """Docking box covering a set of coordinates (typically a co-crystal ligand)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    center = [round(sum(xs) / len(xs), 3), round(sum(ys) / len(ys), 3), round(sum(zs) / len(zs), 3)]
    size = [round(max(max(a) - min(a) + 2 * pad, min_size), 2) for a in (xs, ys, zs)]
    return {"center": center, "size": size, "pad": pad, "n_points": len(points)}


def box_from_ligand_pdb(ligand_pdb: str, pad: float = 5.0, min_size: float = 18.0) -> Dict[str, Any]:
    """Docking box derived from a co-crystal ligand PDB file."""
    pts = []
    for ln in open(ligand_pdb, encoding="utf-8", errors="ignore"):
        if ln.startswith(("ATOM", "HETATM")) and ln[76:78].strip().upper() != "H":
            pts.append([float(ln[30:38]), float(ln[38:46]), float(ln[46:54])])
    if not pts:
        raise ValueError(f"no heavy atoms in {ligand_pdb}")
    out = box_from_points(pts, pad=pad, min_size=min_size)
    out["source"] = os.path.basename(ligand_pdb)
    return out


def _parse_pdbqt_models(path: str) -> List[Dict[str, Any]]:
    models, cur = [], None
    for ln in open(path, encoding="utf-8", errors="ignore"):
        if ln.startswith("MODEL"):
            cur = {"atoms": [], "affinity": None, "rmsd_lb": None, "rmsd_ub": None}
        elif ln.startswith("REMARK VINA RESULT") and cur is not None:
            parts = ln.split()
            try:
                cur["affinity"] = float(parts[3])
                cur["rmsd_lb"] = float(parts[4])
                cur["rmsd_ub"] = float(parts[5])
            except (IndexError, ValueError):
                pass
        elif ln.startswith(("ATOM", "HETATM")) and cur is not None:
            el = _element(ln[76:79])
            if el == "H":
                continue
            cur["atoms"].append({"element": el, "name": ln[12:16].strip(),
                                 "xyz": [float(ln[30:38]), float(ln[38:46]), float(ln[46:54])]})
        elif ln.startswith("ENDMDL") and cur is not None:
            models.append(cur)
            cur = None
    return models


def vina_dock(receptor_pdbqt: str, ligand_pdbqt: str, center: List[float], size: List[float],
              out_pdbqt: Optional[str] = None, exhaustiveness: int = 8, num_modes: int = 9,
              seed: int = 42, cpu: int = 4, timeout_s: int = 1200,
              scoring: str = "vina") -> Dict[str, Any]:
    """Run AutoDock Vina and return every pose's score. Deterministic for a fixed seed.

    `scoring` selects the scoring function inside the same binary: "vina" or "vinardo". They are
    different oracles and their retrospective enrichment differs per receptor
    (`eval/docking_benchmark.json`), so the choice is an argument rather than a constant.
    """
    if scoring not in ("vina", "vinardo"):
        raise ValueError(f"scoring must be 'vina' or 'vinardo', got {scoring!r}")
    b = _vina_bin()
    out_pdbqt = out_pdbqt or os.path.splitext(ligand_pdbqt)[0] + "_out.pdbqt"
    os.makedirs(os.path.dirname(out_pdbqt) or ".", exist_ok=True)
    cmd = [b, "--receptor", receptor_pdbqt, "--ligand", ligand_pdbqt,
           "--center_x", str(center[0]), "--center_y", str(center[1]), "--center_z", str(center[2]),
           "--size_x", str(size[0]), "--size_y", str(size[1]), "--size_z", str(size[2]),
           "--exhaustiveness", str(exhaustiveness), "--num_modes", str(num_modes),
           "--seed", str(seed), "--cpu", str(cpu), "--scoring", scoring, "--out", out_pdbqt]
    r = _run(cmd, timeout=timeout_s)
    if not os.path.exists(out_pdbqt):
        raise RuntimeError(f"vina produced no output: {(r.stderr or r.stdout)[-400:]}")
    models = _parse_pdbqt_models(out_pdbqt)
    scores = [m["affinity"] for m in models if m["affinity"] is not None]
    if not scores:
        raise RuntimeError(f"no scored poses in {out_pdbqt}")
    return {"best_score_kcal_per_mol": min(scores), "scores": scores, "n_poses": len(models),
            "out_pdbqt": out_pdbqt.replace("\\", "/"), "center": center, "size": size,
            "exhaustiveness": exhaustiveness, "num_modes": num_modes, "seed": seed,
            "scoring_function": scoring,
            "vina_version": _run([b, "--version"]).stdout.strip().splitlines()[0],
            "command": " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd)),
            "stdout_tail": (r.stdout or "")[-600:],
            "score_units": f"kcal/mol ({scoring} scoring function; a docking score, not a "
                           f"measured affinity)"}


def pose_rmsd(reference_pdb: str, pose_pdbqt: str, model_index: int = 0) -> Dict[str, Any]:
    """Heavy-atom RMSD between a docked pose and a reference (crystal) ligand.

    Optimal element-matched assignment, no re-superposition.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    ref = []
    for ln in open(reference_pdb, encoding="utf-8", errors="ignore"):
        if ln.startswith(("ATOM", "HETATM")):
            el = _element(ln[76:78])
            if el == "H":
                continue
            ref.append((el, [float(ln[30:38]), float(ln[38:46]), float(ln[46:54])]))
    models = _parse_pdbqt_models(pose_pdbqt)
    if model_index >= len(models):
        raise IndexError(f"pose {model_index} not in {pose_pdbqt} ({len(models)} models)")
    pose = [(a["element"], a["xyz"]) for a in models[model_index]["atoms"]]
    if not ref or not pose:
        raise ValueError("empty reference or pose atom set")
    A = np.array([p[1] for p in ref])
    B = np.array([p[1] for p in pose])
    ea = [p[0].upper() for p in ref]
    eb = [p[0].upper() for p in pose]
    big = 1e6
    cost = np.full((len(A), len(B)), big)
    for i in range(len(A)):
        for j in range(len(B)):
            if ea[i] == eb[j]:
                cost[i, j] = float(np.sum((A[i] - B[j]) ** 2))
    ri, ci = linear_sum_assignment(cost)
    pairs = [(int(i), int(j)) for i, j in zip(ri, ci) if cost[i, j] < big]
    if not pairs:
        raise ValueError("no element-matched atom pairs between reference and pose")
    sq = float(np.mean([cost[i, j] for i, j in pairs]))
    return {"rmsd_A": round(sq ** 0.5, 3), "n_matched_atoms": len(pairs),
            "n_reference_heavy": len(A), "n_pose_heavy": len(B),
            "model_index": model_index, "pose_score": models[model_index]["affinity"],
            "method": "element-matched optimal assignment (Hungarian), no realignment",
            "success_threshold_A": 2.0}


def pose_rmsd_all_models(reference_pdb: str, pose_pdbqt: str) -> Dict[str, Any]:
    """RMSD of every docked pose to the reference, decomposing sampling from scoring.

    A single top-1 RMSD conflates two different failures. If a near-native pose exists among the
    generated modes but is not ranked first, the search *sampled* the crystal pose and the
    *scoring function* mis-ranked it; if no mode is near-native, sampling failed. Reporting both
    numbers is standard redocking practice and is what this function returns.
    """
    models = _parse_pdbqt_models(pose_pdbqt)
    rows = []
    for i in range(len(models)):
        r = pose_rmsd(reference_pdb, pose_pdbqt, model_index=i)
        rows.append({"model_index": i, "rank": i + 1, "rmsd_A": r["rmsd_A"],
                     "score_kcal_per_mol": models[i]["affinity"],
                     "n_matched_atoms": r["n_matched_atoms"]})
    if not rows:
        raise ValueError(f"no poses in {pose_pdbqt}")
    best = min(rows, key=lambda r: r["rmsd_A"])
    top1 = rows[0]
    return {"n_poses": len(rows), "poses": rows,
            "top1_rmsd_A": top1["rmsd_A"], "top1_score": top1["score_kcal_per_mol"],
            "best_rmsd_A": best["rmsd_A"], "best_rmsd_rank": best["rank"],
            "best_rmsd_score": best["score_kcal_per_mol"],
            "success_threshold_A": 2.0,
            "top1_success": top1["rmsd_A"] <= 2.0,
            "sampled_near_native": best["rmsd_A"] <= 2.0,
            "diagnosis": ("top-ranked pose reproduces the crystal pose"
                          if top1["rmsd_A"] <= 2.0 else
                          ("near-native pose was sampled but not ranked first: a scoring-function "
                           "failure, not a search failure" if best["rmsd_A"] <= 2.0 else
                           "no near-native pose among the generated modes: the search did not "
                           "reproduce the crystal pose for this input conformer")),
            "method": "element-matched optimal assignment per pose, no realignment"}


def contacts(receptor_pdb: str, pose_pdbqt: str, model_index: int = 0,
             polar_cut: float = 3.5, hydrophobic_cut: float = 4.5) -> Dict[str, Any]:
    """Geometric protein-ligand contacts (distance criteria only, not a PLIP-grade model)."""
    import numpy as np
    rec = []
    for ln in open(receptor_pdb, encoding="utf-8", errors="ignore"):
        if ln.startswith("ATOM"):
            el = _element(ln[76:78]) or ln[12:16].strip()[0]
            if el == "H":
                continue
            rec.append({"element": el, "name": ln[12:16].strip(), "resname": ln[17:20].strip(),
                        "chain": ln[21].strip(), "resseq": ln[22:26].strip(),
                        "xyz": [float(ln[30:38]), float(ln[38:46]), float(ln[46:54])]})
    models = _parse_pdbqt_models(pose_pdbqt)
    pose = models[model_index]["atoms"]
    R = np.array([a["xyz"] for a in rec])
    P = np.array([a["xyz"] for a in pose])
    d = np.linalg.norm(R[:, None, :] - P[None, :, :], axis=-1)
    polar, hydrophobic, residues = [], [], {}
    for i, j in zip(*np.where(d <= max(polar_cut, hydrophobic_cut))):
        re_, pe = rec[i]["element"].upper(), pose[j]["element"].upper()
        dist = float(d[i, j])
        key = f"{rec[i]['resname']}{rec[i]['resseq']}:{rec[i]['chain']}"
        residues[key] = min(residues.get(key, 99.0), round(dist, 2))
        if re_ in ("N", "O") and pe in ("N", "O") and dist <= polar_cut:
            polar.append({"residue": key, "protein_atom": rec[i]["name"],
                          "ligand_atom": pose[j]["name"], "distance_A": round(dist, 2)})
        elif re_ == "C" and pe == "C" and dist <= hydrophobic_cut:
            hydrophobic.append({"residue": key, "distance_A": round(dist, 2)})
    hyd_res = sorted({h["residue"] for h in hydrophobic})
    return {"n_polar_contacts": len(polar), "polar_contacts": polar[:25],
            "n_hydrophobic_contacts": len(hydrophobic),
            "hydrophobic_residues": hyd_res[:25],
            "contact_residues": sorted(residues, key=lambda k: residues[k])[:25],
            "n_contact_residues": len(residues),
            "criteria": {"polar_NO_NO_max_A": polar_cut, "hydrophobic_CC_max_A": hydrophobic_cut},
            "method": "distance-threshold geometric contacts (no angle terms, no protonation model)",
            "model_index": model_index, "pose_score": models[model_index]["affinity"]}


def pose_to_sdf(pose_pdbqt: str, out_sdf: Optional[str] = None,
                model_index: int = 1) -> Dict[str, Any]:
    """Convert one docked pose to SDF/PDB for viewing (Open Babel)."""
    out_sdf = out_sdf or os.path.splitext(pose_pdbqt)[0] + f"_pose{model_index}.sdf"
    r = _run([_obabel(), pose_pdbqt, "-O", out_sdf, "-f", str(model_index), "-l", str(model_index)])
    if not os.path.exists(out_sdf):
        raise RuntimeError(f"obabel conversion failed: {(r.stderr or r.stdout)[:200]}")
    return {"path": out_sdf.replace("\\", "/"), "model_index": model_index}


def register(registry, config):
    _CFG.update((config or {}).get("tools", {}))
    t = registry.tool
    t("docking.vina_version", VERSION, license=LICENSE, default_tag="COMPUTED")(vina_version)
    t("docking.prepare_receptor", VERSION, license=LICENSE, default_tag="COMPUTED",
      schema={"pdb_path": "str", "out_pdbqt": "str"})(prepare_receptor)
    t("docking.prepare_ligand", VERSION, license=LICENSE, default_tag="COMPUTED",
      schema={"smiles": "str", "out_pdbqt": "str"})(prepare_ligand)
    t("docking.box_from_ligand_pdb", VERSION, license=LICENSE, default_tag="COMPUTED",
      schema={"ligand_pdb": "str", "pad": "float"})(box_from_ligand_pdb)
    t("docking.vina_dock", VERSION, license=LICENSE, default_tag="COMPUTED", cost_hint="expensive",
      schema={"receptor_pdbqt": "str", "ligand_pdbqt": "str", "center": "list[float]",
              "size": "list[float]", "scoring": "str"})(vina_dock)
    t("docking.pose_rmsd", VERSION, license=LICENSE, default_tag="COMPUTED",
      schema={"reference_pdb": "str", "pose_pdbqt": "str"})(pose_rmsd)
    t("docking.pose_rmsd_all_models", VERSION, license=LICENSE, default_tag="COMPUTED",
      schema={"reference_pdb": "str", "pose_pdbqt": "str"})(pose_rmsd_all_models)
    t("docking.contacts", VERSION, license=LICENSE, default_tag="COMPUTED",
      schema={"receptor_pdb": "str", "pose_pdbqt": "str"})(contacts)
    t("docking.pose_to_sdf", VERSION, license=LICENSE, default_tag="COMPUTED",
      schema={"pose_pdbqt": "str"})(pose_to_sdf)
    return registry
