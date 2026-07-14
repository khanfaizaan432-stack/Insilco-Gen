from __future__ import annotations

from typing import Any


def build_fst_command(vcf: str = "input.vcf.gz", pop1: str = "pop1.txt", pop2: str = "pop2.txt", out: str = "fst") -> dict[str, Any]:
    return {
        "tool": "vcftools",
        "command": f"vcftools --gzvcf {vcf} --weir-fst-pop {pop1} --weir-fst-pop {pop2} --out {out}",
        "assumptions": ["Population files contain sample IDs matching metadata.", "Dry run only; command is not executed."],
        "expected_outputs": [f"{out}.weir.fst"],
        "blocked_if": ["Population labels are missing", "Population groups are too small"],
    }


def build_windowed_fst_command(vcf: str = "input.vcf.gz", pop1: str = "pop1.txt", pop2: str = "pop2.txt", out: str = "windowed_fst") -> dict[str, Any]:
    return {
        "tool": "vcftools",
        "command": f"vcftools --gzvcf {vcf} --weir-fst-pop {pop1} --weir-fst-pop {pop2} --fst-window-size 50000 --out {out}",
        "assumptions": ["Window size is a deterministic placeholder.", "Dry run only; command is not executed."],
        "expected_outputs": [f"{out}.windowed.weir.fst"],
        "blocked_if": ["Population labels are missing", "Population groups are too small"],
    }
