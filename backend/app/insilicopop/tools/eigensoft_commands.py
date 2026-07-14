from __future__ import annotations

from typing import Any


def build_smartpca_command_preview(genotype_prefix: str = "input", out: str = "smartpca") -> dict[str, Any]:
    return {
        "tool": "eigensoft",
        "command": f"smartpca -p {out}.par",
        "assumptions": [
            f"{genotype_prefix} has been LD-pruned and related samples were handled.",
            "A smartpca parameter file would be generated locally.",
            "Dry run only; command is not executed.",
        ],
        "expected_outputs": [f"{out}.evec", f"{out}.eval", f"{out}.log"],
        "blocked_if": ["LD pruning is unknown", "Relatedness removal is unknown"],
    }
