from __future__ import annotations

from typing import Any


def build_ihs_plan(input_prefix: str = "input", out: str = "ihs") -> dict[str, Any]:
    return {
        "tool": "selection_scan",
        "command": f"selscan --ihs --vcf {input_prefix}.vcf.gz --out {out}",
        "assumptions": ["Phased variants are available.", "Dry run only; command is not executed."],
        "expected_outputs": [f"{out}.ihs.out", f"{out}.ihs.norm"],
        "blocked_if": ["No demographic null model", "No multiple-testing correction plan"],
    }


def build_xpehh_plan(input_prefix: str = "input", ref_pop: str = "ref.txt", target_pop: str = "target.txt", out: str = "xpehh") -> dict[str, Any]:
    return {
        "tool": "selection_scan",
        "command": f"selscan --xpehh --vcf {input_prefix}.vcf.gz --ref {ref_pop} --target {target_pop} --out {out}",
        "assumptions": ["Reference and target population sample lists are local placeholders.", "Dry run only; command is not executed."],
        "expected_outputs": [f"{out}.xpehh.out", f"{out}.xpehh.norm"],
        "blocked_if": ["Population labels are missing", "No demographic null model", "No multiple-testing correction plan"],
    }
