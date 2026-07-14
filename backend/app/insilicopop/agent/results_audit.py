from __future__ import annotations

from pathlib import Path
from typing import Any


ALLOWED_ARTIFACT_TYPES = {
    "pca_eigenvec",
    "pca_eigenval",
    "admixture_q",
    "admixture_p",
    "admixture_cv_log",
    "plink_log",
    "plink_summary",
    "method_notes",
    "manuscript_claims",
    "unknown_result_artifact",
}

PCA_CONTEXT = [
    "sample metadata availability",
    "population labels provenance",
    "QC method summary",
    "LD pruning method",
    "reference panel used",
    "PCA method/tool",
    "explained variance/eigenvalue context",
]

ADMIXTURE_CONTEXT = [
    "K values tested",
    "CV/error reporting",
    "LD pruning status",
    "sample/population metadata",
    "random seed/replicate information if available",
    "clear statement that components are model components, not literal ancestry",
]

PLINK_CONTEXT = [
    "tool version",
    "input declaration",
    "filters/QC thresholds",
    "sample and variant counts if available",
]

CLAIMS_CONTEXT = [
    "method provenance",
    "sample provenance",
    "ethics/consent context if human data is discussed",
    "limitations/caveats",
    "blocked interpretation categories",
]

UNSAFE_CLAIM_CHECKS = [
    "clinical diagnosis",
    "treatment recommendation",
    "consumer ancestry claim",
    "caste/community/religion inference",
    "genetic purity/superiority language",
    "literal ancestry from ADMIXTURE components",
    "PCA cluster identity claims",
    "unsupported selection claims",
    "unsupported endogamy claims",
]


def build_results_audit(
    *,
    workflow_selection: dict[str, Any],
    selected_recipe: dict[str, Any] | None,
    uploaded_files: dict[str, str],
    claim_audit: dict[str, Any],
    query: str | None,
) -> dict[str, Any] | None:
    workflow_family = str(workflow_selection.get("workflow_family") or "")
    if workflow_family != "results_only_audit":
        return None

    selected_recipe = selected_recipe or {}
    artifacts = [
        _declared_result_artifact(index, field_name, filename)
        for index, (field_name, filename) in enumerate(sorted(uploaded_files.items()), start=1)
        if _is_declared_result(field_name, filename)
    ]
    if _query_mentions_claim_document(query) and not any(item["artifact_type"] == "manuscript_claims" for item in artifacts):
        artifacts.append(_claim_text_artifact(len(artifacts) + 1))

    missing_context = _merge_unique(*(artifact["missing_context"] for artifact in artifacts))
    unsafe_claim_checks = _merge_unique(UNSAFE_CLAIM_CHECKS, _string_list(claim_audit.get("blocked_interpretations", [])))
    human_review_flags = _merge_unique(
        [
            "Human expert review is required before using any declared result artifact in a report or manuscript.",
            "Declared result files were inventoried only; raw files were not read and result contents were not deeply parsed.",
            "Do not treat PCA clusters, ADMIXTURE components, PLINK summaries, FST, ROH, or selection outputs as identity, ancestry, clinical, purity, or superiority conclusions.",
        ],
        _string_list(claim_audit.get("human_review_flags", [])),
    )

    return {
        "workflow_family": "results_only_audit",
        "selected_recipe_id": selected_recipe.get("recipe_id"),
        "dry_run_only": True,
        "human_review_required": True,
        "external_tools_executed": False,
        "raw_genomic_files_parsed": False,
        "deep_result_files_parsed": False,
        "results_audit_summary": {
            "declared_result_artifact_count": len(artifacts),
            "missing_context_count": len(missing_context),
            "unsafe_claim_check_count": len(unsafe_claim_checks),
            "note": "Declared existing result artifacts are inventoried by field/name only; contents are not parsed in v0.22.",
        },
        "declared_result_artifacts": artifacts,
        "missing_result_context": missing_context,
        "method_provenance_checks": _method_provenance_checks(artifacts),
        "unsafe_claim_checks": unsafe_claim_checks,
        "human_review_flags": human_review_flags,
    }


def _declared_result_artifact(index: int, field_name: str, filename: str) -> dict[str, Any]:
    artifact_type = _artifact_type(field_name, filename)
    required_context = _required_context(artifact_type)
    return {
        "artifact_id": f"result_artifact_{index:03d}",
        "artifact_type": artifact_type,
        "declared_path_or_name": filename,
        "declared_format": _declared_format(filename),
        "associated_method": _associated_method(artifact_type),
        "parsed": False,
        "parse_status": "not_parsed_schema_only",
        "raw_file_read": False,
        "required_context": required_context,
        "missing_context": required_context,
        "audit_notes": _audit_notes(artifact_type),
        "human_review_required": True,
    }


def _claim_text_artifact(index: int) -> dict[str, Any]:
    return {
        "artifact_id": f"result_artifact_{index:03d}",
        "artifact_type": "manuscript_claims",
        "declared_path_or_name": "research_goal_or_query_claims",
        "declared_format": "query_text",
        "associated_method": "claim review",
        "parsed": False,
        "parse_status": "not_parsed_schema_only",
        "raw_file_read": False,
        "required_context": CLAIMS_CONTEXT,
        "missing_context": CLAIMS_CONTEXT,
        "audit_notes": [
            "Audit manuscript/report claims against method provenance, sample provenance, ethics context, caveats, and blocked interpretations.",
            "Do not convert declared claims into biological, clinical, ancestry, caste/community/religion, purity, superiority, or identity conclusions.",
        ],
        "human_review_required": True,
    }


def _is_declared_result(field_name: str, filename: str) -> bool:
    artifact_type = _artifact_type(field_name, filename)
    return artifact_type in ALLOWED_ARTIFACT_TYPES and artifact_type != "unknown_result_artifact" or _looks_like_unknown_result(field_name, filename)


def _artifact_type(field_name: str, filename: str) -> str:
    lowered = f"{field_name} {filename}".lower()
    suffixes = _suffixes(filename)
    if ".evec" in suffixes or "eigenvec" in lowered or "smartpca_evec" in lowered:
        return "pca_eigenvec"
    if ".eval" in suffixes or "eigenval" in lowered or "smartpca_eval" in lowered:
        return "pca_eigenval"
    if ".q" in suffixes or "admixture_q" in lowered:
        return "admixture_q"
    if ".p" in suffixes or "admixture_p" in lowered:
        return "admixture_p"
    if "admixture" in lowered and ("cv" in lowered or "log" in lowered):
        return "admixture_cv_log"
    if "plink" in lowered and "log" in lowered:
        return "plink_log"
    if "plink" in lowered or ".hom" in suffixes or "roh" in lowered or "fst" in lowered or "selection" in lowered:
        return "plink_summary"
    if "method" in lowered or "notes" in lowered:
        return "method_notes"
    if "manuscript" in lowered or "claim" in lowered or "report" in lowered:
        return "manuscript_claims"
    return "unknown_result_artifact"


def _looks_like_unknown_result(field_name: str, filename: str) -> bool:
    lowered = f"{field_name} {filename}".lower()
    return any(marker in lowered for marker in ["result", "output", "summary", "audit"])


def _required_context(artifact_type: str) -> list[str]:
    if artifact_type in {"pca_eigenvec", "pca_eigenval"}:
        return list(PCA_CONTEXT)
    if artifact_type in {"admixture_q", "admixture_p", "admixture_cv_log"}:
        return list(ADMIXTURE_CONTEXT)
    if artifact_type in {"plink_log", "plink_summary"}:
        return list(PLINK_CONTEXT)
    if artifact_type == "manuscript_claims":
        return list(CLAIMS_CONTEXT)
    if artifact_type == "method_notes":
        return ["method provenance", "sample provenance", "limitations/caveats"]
    return ["method provenance", "sample provenance", "limitations/caveats", "human review notes"]


def _associated_method(artifact_type: str) -> str:
    if artifact_type in {"pca_eigenvec", "pca_eigenval"}:
        return "PCA/smartpca-style result"
    if artifact_type in {"admixture_q", "admixture_p", "admixture_cv_log"}:
        return "ADMIXTURE-style result"
    if artifact_type in {"plink_log", "plink_summary"}:
        return "PLINK/result summary"
    if artifact_type == "manuscript_claims":
        return "claim review"
    if artifact_type == "method_notes":
        return "method notes"
    return "unknown result artifact"


def _audit_notes(artifact_type: str) -> list[str]:
    common = [
        "Schema-only audit: declared artifact was not parsed and raw file contents were not read.",
        "Human expert review is required before interpretation or reporting.",
    ]
    if artifact_type in {"pca_eigenvec", "pca_eigenval"}:
        return common + ["PCA coordinates/eigenvalues cannot be used as identity conclusions."]
    if artifact_type in {"admixture_q", "admixture_p", "admixture_cv_log"}:
        return common + ["ADMIXTURE components are model components, not literal ancestry."]
    if artifact_type in {"plink_log", "plink_summary"}:
        return common + ["PLINK summaries require version, input, threshold, and count context."]
    if artifact_type == "manuscript_claims":
        return common + ["Manuscript/report claims must preserve blocked interpretation categories and caveats."]
    return common


def _method_provenance_checks(artifacts: list[dict[str, Any]]) -> list[str]:
    checks = []
    for artifact in artifacts:
        for context in artifact.get("required_context", []):
            checks.append(f"{artifact['artifact_id']} requires {context}")
    return _merge_unique(checks)


def _declared_format(filename: str) -> str:
    suffixes = Path(filename.lower()).suffixes
    if not suffixes:
        return "unknown"
    if len(suffixes) >= 2 and suffixes[-2:] == [".vcf", ".gz"]:
        return ".vcf.gz"
    return suffixes[-1]


def _suffixes(filename: str) -> set[str]:
    lowered = filename.lower()
    return set(Path(lowered).suffixes)


def _query_mentions_claim_document(query: str | None) -> bool:
    lowered = (query or "").lower()
    return any(marker in lowered for marker in ["manuscript", "claim", "report"])


def _merge_unique(*groups: list[str]) -> list[str]:
    seen = set()
    merged = []
    for group in groups:
        for item in group:
            value = str(item).strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(value)
    return merged


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]
