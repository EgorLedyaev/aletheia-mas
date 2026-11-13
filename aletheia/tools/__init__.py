"""Tool implementations. `register_all` wires every tool into a ToolRegistry."""
from __future__ import annotations

from typing import Any, Dict

from ..core.registry import ToolRegistry


def register_all(registry: ToolRegistry, config: Dict[str, Any]) -> ToolRegistry:
    from . import (rdkit_tools, chembl, pubchem, uniprot, pdb_rcsb, alphafold, docking,
                   hazard, pocket, generators, admet, qsar_tools, ranking)
    for mod in (rdkit_tools, chembl, pubchem, uniprot, pdb_rcsb, alphafold, docking,
                hazard, pocket, generators, admet, qsar_tools, ranking):
        mod.register(registry, config)
    return registry
