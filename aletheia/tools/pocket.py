"""Apo binding-site detection: a LIGSITE-style buriedness grid, implemented here.

Why implemented rather than wrapped: fpocket and P2Rank have no pip/conda build for this
Windows host, so instead of claiming a pocket finder we do not have, Aletheia ships a small,
documented re-implementation of the LIGSITE protein-solvent-protein (PSP) grid criterion
(Hendlich et al. 1997 describe the original method) and *validates it on a co-crystal case*:
the distance from the top-ranked pocket centre to the crystallographic ligand centroid is
reported with every detection, so the reader can see how well it localises a known site.

Output is COMPUTED (deterministic geometry), never PREDICTED.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

VERSION = "ligsite-like-1.0"

# 7 scan directions (3 axes + 4 body diagonals), each used in both senses.
DIRECTIONS = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1), (1, 1, -1), (1, -1, 1), (-1, 1, 1)]


def _load_protein_atoms(pdb_path: str) -> np.ndarray:
    pts = []
    for ln in open(pdb_path, "r", encoding="utf-8", errors="ignore"):
        if ln.startswith("ATOM"):
            el = ln[76:78].strip().upper()
            if el == "H":
                continue
            try:
                pts.append([float(ln[30:38]), float(ln[38:46]), float(ln[46:54])])
            except ValueError:
                continue
    if not pts:
        raise ValueError(f"no protein ATOM records in {pdb_path}")
    return np.asarray(pts, dtype=np.float32)


def detect(pdb_path: str, spacing: float = 1.0, probe: float = 3.2, psp_min: int = 5,
           min_cluster_points: int = 30, top_n: int = 5,
           reference_point: Optional[List[float]] = None) -> Dict[str, Any]:
    """Detect buried cavities on a protein surface.

    spacing   grid step in A
    probe     distance from a heavy atom below which a grid point counts as occupied
    psp_min   minimum number of protein-solvent-protein events (out of 7 axes) to call a point buried
    """
    from scipy import ndimage

    atoms = _load_protein_atoms(pdb_path)
    lo = atoms.min(0) - 4.0
    hi = atoms.max(0) + 4.0
    dims = np.ceil((hi - lo) / spacing).astype(int) + 1
    if int(np.prod(dims)) > 40_000_000:
        raise MemoryError(f"grid too large ({dims.tolist()}); increase spacing")

    # occupancy by binary dilation of atom centres (cheap distance transform)
    occ = np.zeros(dims, dtype=bool)
    idx = np.floor((atoms - lo) / spacing).astype(int)
    idx = np.clip(idx, 0, dims - 1)
    occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    r = int(np.ceil(probe / spacing))
    zz, yy, xx = np.mgrid[-r:r + 1, -r:r + 1, -r:r + 1]
    ball = (zz ** 2 + yy ** 2 + xx ** 2) * spacing ** 2 <= probe ** 2
    occupied = ndimage.binary_dilation(occ, structure=ball)

    free = ~occupied
    psp = np.zeros(dims, dtype=np.uint8)
    for d in DIRECTIONS:
        # a free point is "enclosed" along d if occupied grid exists in both senses
        fwd = np.zeros(dims, dtype=bool)
        bwd = np.zeros(dims, dtype=bool)
        cur_f = occupied.copy()
        cur_b = occupied.copy()
        for _ in range(int(14 / spacing)):          # look up to ~14 A along the ray
            cur_f = _shift(cur_f, d)
            cur_b = _shift(cur_b, tuple(-x for x in d))
            fwd |= cur_f
            bwd |= cur_b
        psp += (fwd & bwd & free).astype(np.uint8)

    buried = (psp >= psp_min) & free
    labels, n = ndimage.label(buried)
    out: List[Dict[str, Any]] = []
    pocket_coords: List[np.ndarray] = []
    if n:
        sizes = ndimage.sum(buried, labels, index=np.arange(1, n + 1))
        order = np.argsort(sizes)[::-1]
        for k in order[: top_n * 3]:
            size = int(sizes[k])
            if size < min_cluster_points:
                continue
            mask = labels == (k + 1)
            coords = np.argwhere(mask).astype(np.float32) * spacing + lo
            centre = coords.mean(0)
            ext = coords.max(0) - coords.min(0)
            pocket_coords.append(coords)
            out.append({"rank": len(out) + 1, "n_grid_points": size,
                        "volume_A3": round(size * spacing ** 3, 1),
                        "center": [round(float(c), 3) for c in centre],
                        "extent_A": [round(float(e), 2) for e in ext],
                        "mean_buriedness": round(float(psp[mask].mean()), 2)})
            if len(out) >= top_n:
                break
    res: Dict[str, Any] = {"pdb_path": pdb_path, "n_pockets": len(out), "pockets": out,
                           "top_pocket": out[0] if out else None,
                           "params": {"spacing_A": spacing, "probe_A": probe, "psp_min": psp_min,
                                      "min_cluster_points": min_cluster_points},
                           "grid_dims": dims.tolist(), "n_protein_atoms": int(len(atoms)),
                           "method": "LIGSITE-style protein-solvent-protein buriedness grid "
                                     "(re-implementation; see aletheia/tools/pocket.py)"}
    if reference_point is not None and out:
        ref = np.asarray(reference_point, dtype=np.float32)
        centre_d = [float(np.linalg.norm(np.asarray(p["center"], dtype=np.float32) - ref))
                    for p in out]
        # the informative quantity is whether the cavity *reaches* the reference point, so we
        # report the distance to the nearest grid point of each cavity as well as centroid distance
        near_d = [float(np.min(np.linalg.norm(c - ref, axis=1))) for c in pocket_coords]
        best = int(np.argmin(near_d))
        res["validation"] = {
            "reference_point": [round(float(x), 3) for x in ref],
            "top_pocket_centroid_distance_A": round(centre_d[0], 2),
            "top_pocket_nearest_point_distance_A": round(near_d[0], 2),
            "best_pocket_rank": best + 1,
            "best_pocket_nearest_point_distance_A": round(near_d[best], 2),
            "hit_within_5A": bool(min(near_d) <= 5.0),
            "criterion": "distance from the crystallographic ligand centroid to the nearest grid "
                         "point of the detected cavity",
        }
    return res


def _shift(arr: np.ndarray, d) -> np.ndarray:
    out = np.zeros_like(arr)
    sl_src, sl_dst = [], []
    for ax in range(3):
        s = d[ax]
        if s == 0:
            sl_src.append(slice(None)); sl_dst.append(slice(None))
        elif s > 0:
            sl_src.append(slice(0, -s)); sl_dst.append(slice(s, None))
        else:
            sl_src.append(slice(-s, None)); sl_dst.append(slice(0, s))
    out[tuple(sl_dst)] = arr[tuple(sl_src)]
    return out


def register(registry, config):
    registry.tool("pocket.detect", VERSION, license="BSD-3-Clause (this implementation)",
                  default_tag="COMPUTED", cost_hint="medium",
                  schema={"pdb_path": "str", "spacing": "float"})(detect)
    return registry
