from __future__ import annotations

from typing import Any


def build_orchestration_prompt(*, compact_memory: dict[str, Any], audit_summary: dict[str, Any], query: str | None) -> dict[str, Any]:
    return {
        "system": "InSilicoPop orchestration prompt. Use redacted compact memory and audit summary only.",
        "query": query,
        "researcher_goal": query,
        "input_inventory": audit_summary.get("input_inventory", []),
        "allowed_actions": [
            "dry_run_plink_qc",
            "dry_run_ld_pruning",
            "dry_run_pca",
            "run_admixture",
            "dry_run_fst",
            "dry_run_roh",
            "dry_run_selection_scan",
            "interpret_results",
            "generate_report",
        ],
        "guardrails": [
            "No clinical claims.",
            "No caste, religion, community identity inference from genetic clusters.",
            "No purity or superiority claims.",
            "Selection, PCA, ADMIXTURE, FST, and ROH interpretations must pass deterministic validation.",
            "External tool execution is disabled; only dry-run command planning is allowed.",
        ],
        "compact_memory": _compact_view(compact_memory),
        "audit_summary": {
            "reliability_score": audit_summary.get("reliability_score"),
            "risk_codes": [flag.get("code") for flag in audit_summary.get("risk_flags", []) if isinstance(flag, dict)],
        },
        "redaction_policy": {
            "raw_genomic_files_included": False,
            "raw_sample_level_sensitive_metadata_included": False,
            "full_genotype_matrices_included": False,
            "payload_contains_only": [
                "researcher goal",
                "input inventory",
                "audit summaries",
                "carried memory",
                "allowed actions",
                "guardrails",
            ],
        },
        "raw_files_included": False,
    }


def _compact_view(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "facts": memory.get("facts", []),
        "critical_facts": memory.get("critical_facts", []),
        "dependency_capsules": memory.get("dependency_capsules", []),
        "downstream_dependencies": memory.get("downstream_dependencies", []),
        "blocked_interpretations": memory.get("blocked_interpretations", []),
    }
