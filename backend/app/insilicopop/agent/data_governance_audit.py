from __future__ import annotations

from typing import Any


DATASET_SOURCES = {
    "GenomeIndia",
    "IBDC",
    "IndiGenomes",
    "TMC-SNPdb",
    "institutional_cohort",
    "public_reference",
    "other",
    "unknown",
}

CONSENT_TYPES = {"broad", "tiered", "specific", "dynamic", "unknown"}
CREDENTIAL_MODELS = {"researcher_provided", "shared_service_account", "unknown", "not_applicable"}

INDIA_GOVERNANCE_MARKERS = (
    "genomeindia",
    "ibdc",
    "indigenomes",
    "tmc-snpdb",
    "feed",
    "biotech-pride",
    "biorrap",
    "hmsc",
    "icmr",
)
MANAGED_ACCESS_MARKERS = ("managed access", "managed-access", "controlled access", "controlled-access", "restricted access", "dua")
REIDENTIFICATION_MARKERS = ("re-identification", "reidentify", "re-identify", "de-anonymize", "deanonymize", "identify individual")
CLINICAL_MARKERS = ("diagnos", "clinical diagnosis", "disease status", "patient diagnosis")
TREATMENT_MARKERS = ("treatment", "therapy", "medication", "prescribe")
IDENTITY_MARKERS = ("caste", "community", "religion", "religious")
PURITY_MARKERS = ("genetic purity", "purity", "pure population", "superior", "inferior")
NETWORK_EXPORT_MARKERS = (
    "upload raw",
    "upload vcf",
    "send raw",
    "send vcf",
    "network upload",
    "cloud upload",
    "external upload",
    "export raw genomic",
    "cross-border export",
    "cross border export",
)
VAGUE_APPROVED_USE = {"", "unknown", "not sure", "n/a", "na", "research", "analysis", "population genetics"}


def build_data_governance_audit(
    *,
    query: str | None,
    uploaded_files: dict[str, str],
    workflow_selection: dict[str, Any],
    selected_recipe: dict[str, Any] | None,
    data_use_agreement_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scope = _normalise_scope(data_use_agreement_scope)
    declared_scope_present = data_use_agreement_scope is not None
    text = _combined_text(query, uploaded_files, workflow_selection, selected_recipe, scope)
    managed_access_context = scope["managed_access"] or _mentions_any(text, MANAGED_ACCESS_MARKERS) or _mentions_india_controlled_context(text)
    approved_use_summary = str(scope["approved_use_summary"]).strip()
    credential_model = str(scope["data_access_credential_model"])

    blocked: list[str] = []
    caveats: list[str] = []

    if managed_access_context and not declared_scope_present:
        blocked.append("Managed-access human genomic dataset context was declared or implied, but no data_use_agreement_scope was provided.")
    if managed_access_context and credential_model == "shared_service_account":
        blocked.append("Managed-access human genomic data must not use a shared service account credential model.")
    if _mentions_any(text, REIDENTIFICATION_MARKERS):
        blocked.append("Re-identification or individual identification from genomic data is blocked by governance policy.")
    if _mentions_any(text, IDENTITY_MARKERS):
        blocked.append("Caste/community/religion inference from genetic data is blocked by governance policy.")
    if _mentions_any(text, PURITY_MARKERS):
        blocked.append("Genetic purity/superiority claims are blocked by governance policy.")
    if _mentions_any(text, CLINICAL_MARKERS):
        blocked.append("Clinical diagnosis from research-use genomic data is blocked by governance policy.")
    if _mentions_any(text, TREATMENT_MARKERS):
        blocked.append("Treatment recommendation from this research workflow is blocked by governance policy.")
    if _mentions_any(text, NETWORK_EXPORT_MARKERS):
        blocked.append("Raw genomic data network upload/export is blocked unless a future explicit offline execution policy permits it.")
    if scope["cross_border_export_declared"] and not _has_governance_metadata(scope):
        blocked.append("Cross-border/export use was declared without sufficient declared governance approval metadata.")
    if scope["commercial_or_third_party_use_declared"] and _is_vague(approved_use_summary):
        blocked.append("Commercial or third-party use was declared, but approved_use_summary is missing or unclear.")

    if declared_scope_present:
        caveats.append("Declared data-use scope is recorded but not machine-verified; human governance review is required.")
    if _is_vague(approved_use_summary):
        caveats.append("Approved use summary is vague or missing.")
    if scope["dataset_source"] == "unknown":
        caveats.append("Dataset source is unknown.")
    if scope["consent_type"] == "unknown":
        caveats.append("Consent type is unknown.")
    if not scope["ethics_approval_declared"]:
        caveats.append("Ethics approval declaration is missing.")
    if _mentions_india_controlled_context(text) and not scope["biorrap_id_declared"]:
        caveats.append("India-specific governance metadata such as BioRRAP or local approval identifier is missing.")
    if not scope["secondary_use_declared"]:
        caveats.append("Secondary-use status is unclear or not declared.")
    if _cohort_metadata_incomplete(uploaded_files):
        caveats.append("Cohort metadata is missing for platform, batch, sample-size, and access-level governance assessment.")
    if _mentions_india_controlled_context(text) and not declared_scope_present:
        caveats.append("Indian controlled-access context appears in declarations, but access terms are not declared.")
    if _mentions_any(text, ("isolated population", "protected population", "founder cohort", "tribal", "vulnerable population")):
        caveats.append("Protected, isolated, founder, or vulnerable population context requires explicit human governance review.")
    if scope["cross_border_export_declared"]:
        caveats.append("Cross-border transfer/export declaration requires human governance review.")

    status = "blocked" if blocked else "passed_with_caveats" if caveats else "passed"
    return {
        "status": status,
        "blocked": _merge_unique(blocked),
        "caveats": _merge_unique(caveats),
        "human_review_required": True,
        "declared_scope_present": declared_scope_present,
        "dataset_terms_verified": False,
        "raw_data_network_access_allowed": False,
        "shared_service_account_used": credential_model == "shared_service_account",
        "external_credential_used": credential_model == "researcher_provided",
        "data_use_agreement_scope": scope,
        "workflow_family": workflow_selection.get("workflow_family", "unknown"),
        "selected_recipe_id": (selected_recipe or {}).get("recipe_id"),
        "dry_run_only": True,
        "external_tools_executed": False,
        "raw_genomic_files_parsed": False,
        "legal_compliance_verified": False,
        "review_boundaries": [
            "Audit checks declared research-use scope, dataset access model, consent/DUA compatibility, credential model, and governance caveats.",
            "Audit does not verify legal compliance.",
            "Audit does not replace institutional ethics committee, data access committee, PI, clinician, data privacy officer, or legal review.",
        ],
    }


def _normalise_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    scope = scope or {}
    dataset_source = str(scope.get("dataset_source") or "unknown")
    consent_type = str(scope.get("consent_type") or "unknown")
    credential_model = str(scope.get("data_access_credential_model") or "unknown")
    return {
        "dataset_source": dataset_source if dataset_source in DATASET_SOURCES else "other",
        "managed_access": _bool_value(scope.get("managed_access", False)),
        "approved_use_summary": str(scope.get("approved_use_summary") or ""),
        "prohibited_uses": _string_list(scope.get("prohibited_uses", [])),
        "consent_type": consent_type if consent_type in CONSENT_TYPES else "unknown",
        "ethics_approval_declared": _bool_value(scope.get("ethics_approval_declared", False)),
        "biorrap_id_declared": _bool_value(scope.get("biorrap_id_declared", False)),
        "data_access_credential_model": credential_model if credential_model in CREDENTIAL_MODELS else "unknown",
        "cross_border_export_declared": _bool_value(scope.get("cross_border_export_declared", False)),
        "secondary_use_declared": _bool_value(scope.get("secondary_use_declared", False)),
        "commercial_or_third_party_use_declared": _bool_value(scope.get("commercial_or_third_party_use_declared", False)),
        "human_review_required": True,
    }


def _combined_text(
    query: str | None,
    uploaded_files: dict[str, str],
    workflow_selection: dict[str, Any],
    selected_recipe: dict[str, Any] | None,
    scope: dict[str, Any],
) -> str:
    fragments = [query or ""]
    fragments.extend(uploaded_files.keys())
    fragments.extend(uploaded_files.values())
    fragments.extend(str(item) for item in workflow_selection.values())
    if selected_recipe:
        fragments.extend(str(selected_recipe.get(key, "")) for key in ("recipe_id", "workflow_family", "intent_summary"))
    fragments.extend(
        str(value)
        for key, value in scope.items()
        if key not in {"prohibited_uses"}
    )
    return " ".join(fragments).lower()


def _mentions_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _mentions_india_controlled_context(text: str) -> bool:
    return any(marker in text for marker in INDIA_GOVERNANCE_MARKERS)


def _has_governance_metadata(scope: dict[str, Any]) -> bool:
    return bool(scope["approved_use_summary"] and (scope["ethics_approval_declared"] or scope["biorrap_id_declared"]))


def _is_vague(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered in VAGUE_APPROVED_USE or len(lowered) < 12


def _cohort_metadata_incomplete(uploaded_files: dict[str, str]) -> bool:
    lowered = " ".join([*uploaded_files.keys(), *uploaded_files.values()]).lower()
    return not any(marker in lowered for marker in ("metadata", "sample", "cohort", "platform", "batch"))


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item).strip()]


def _merge_unique(values: list[str]) -> list[str]:
    seen = set()
    merged = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(value)
    return merged
