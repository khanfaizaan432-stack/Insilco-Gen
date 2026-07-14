from __future__ import annotations

from typing import Any


def _preview(command: str, expected_outputs: list[str], blocked_if: list[str], assumptions: list[str] | None = None) -> dict[str, Any]:
    return {
        "tool": "plink",
        "command": command,
        "assumptions": assumptions or ["Input prefix is a local PLINK binary dataset placeholder.", "Dry run only; command is not executed."],
        "expected_outputs": expected_outputs,
        "blocked_if": blocked_if,
    }


def build_missingness_command(bfile: str = "input", out: str = "qc_missingness") -> dict[str, Any]:
    return _preview(
        f"plink --bfile {bfile} --missing --out {out}",
        [f"{out}.imiss", f"{out}.lmiss"],
        ["PLINK binary input is missing", "Sample IDs cannot be matched to metadata"],
    )


def build_hwe_command(bfile: str = "input", out: str = "qc_hwe") -> dict[str, Any]:
    return _preview(
        f"plink --bfile {bfile} --hardy --out {out}",
        [f"{out}.hwe"],
        ["Variant QC has not been run"],
    )


def build_ld_prune_command(bfile: str = "input", out: str = "prune") -> dict[str, Any]:
    return _preview(
        f"plink --bfile {bfile} --indep-pairwise 50 5 0.2 --out {out}",
        [f"{out}.prune.in", f"{out}.prune.out"],
        ["Missing genotype input", "Variant missingness/HWE QC not documented"],
    )


def build_relatedness_command(bfile: str = "input", out: str = "relatedness") -> dict[str, Any]:
    return _preview(
        f"plink --bfile {bfile} --genome --out {out}",
        [f"{out}.genome"],
        ["Missing genotype input", "Relatedness threshold is not specified"],
    )


def build_roh_command(bfile: str = "input", out: str = "roh") -> dict[str, Any]:
    return _preview(
        f"plink --bfile {bfile} --homozyg --out {out}",
        [f"{out}.hom"],
        ["Missing genotype input", "ROH thresholds are not documented"],
    )
