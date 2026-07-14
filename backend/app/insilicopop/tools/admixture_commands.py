from __future__ import annotations

from typing import Any


def build_admixture_k_sweep_commands(prefix: str = "input", k_min: int = 2, k_max: int = 10, seeds: list[int] | None = None) -> list[dict[str, Any]]:
    seeds = seeds or [1, 2, 3]
    commands: list[dict[str, Any]] = []
    for k in range(k_min, k_max + 1):
        for seed in seeds:
            commands.append(
                {
                    "tool": "admixture",
                    "command": f"admixture --cv -s {seed} {prefix}.bed {k}",
                    "assumptions": ["Input prefix has matching .bed/.bim/.fam files.", "Dry run only; command is not executed."],
                    "expected_outputs": [f"{prefix}.{k}.Q", f"{prefix}.{k}.P", f"CV error (K={k}) log line"],
                    "blocked_if": ["LD pruning has not been run", "Genotype QC has not been completed"],
                }
            )
    return commands


def build_admixture_cv_command(prefix: str = "input", k: int = 3, seed: int = 1) -> dict[str, Any]:
    return build_admixture_k_sweep_commands(prefix, k, k, [seed])[0]
