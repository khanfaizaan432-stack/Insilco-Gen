from __future__ import annotations

from typing import Any


RESEARCH_LANES = {
    "population_genetics",
    "clinical_genetics_research_curation",
    "insufficient_inputs",
    "blocked_out_of_scope",
}

OUT_OF_SCOPE_RULES = [
    ("diagnosis_tool", ("diagnos", "diagnosis", "disease status", "patient has")),
    ("treatment_recommendation", ("treatment", "therapy", "medication", "prescribe")),
    ("consumer_ancestry", ("consumer ancestry", "ancestry report", "ethnicity estimate", "my ancestry")),
    ("caste_community_religion_inference", ("caste", "community", "religion", "religious")),
    ("genetic_purity_or_superiority", ("genetic purity", "pure population", "superior", "inferior")),
    ("final_acmg_classification", ("final acmg", "classify pathogenic", "classify benign", "automatic acmg", "make acmg classification")),
    ("wet_lab_sample_management", ("wet lab", "sample accession", "operate sequencer", "manage lab sample")),
    ("public_saas_sensitive_upload", ("public saas", "upload raw", "cloud upload", "external upload", "uncontrolled online")),
    ("autonomous_raw_genome_execution", ("execute raw genome", "run plink now", "run admixture now", "autonomous execution", "unattended execution")),
]

POPULATION_MARKERS = ("population", "pca", "admixture", "fst", "roh", "selection", "plink", "vcf", "genotype")
CLINICAL_CURATION_MARKERS = ("clinical curation", "hpo", "variant", "clinvar", "clingen", "gnomad", "acmg", "pedigree", "inheritance")


def build_metadata_registry_audit(
    *,
    query: str | None,
    uploaded_files: dict[str, str],
    workflow_selection: dict[str, Any],
    metadata_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = _normalise_registry(metadata_registry)
    text = _combined_text(query, uploaded_files, workflow_selection, registry)
    blocked_categories = _blocked_categories(text)
    research_lane = "blocked_out_of_scope" if blocked_categories else _classify_lane(text, uploaded_files, workflow_selection, registry)

    missing_required: list[str] = []
    caveats: list[str] = []
    if research_lane == "population_genetics":
        missing_required.extend(_population_missing(registry, text))
        caveats.extend(_population_caveats(registry, text))
    elif research_lane == "clinical_genetics_research_curation":
        missing_required.extend(_clinical_missing(registry))
        caveats.extend(_clinical_caveats(registry))
    elif research_lane == "insufficient_inputs":
        caveats.append("Insufficient declared metadata to classify a population genetics or clinical genetics research curation lane.")

    if missing_required:
        caveats.append("Missing metadata fields are caveated; no biological or clinical interpretation was made.")

    status = "blocked" if blocked_categories else "passed_with_caveats" if missing_required or caveats else "passed"
    return {
        "status": status,
        "missing_required_metadata": _merge_unique(missing_required),
        "caveats": _merge_unique(caveats),
        "blocked_out_of_scope_categories": blocked_categories,
        "human_review_required": True,
        "research_lane": research_lane,
        "metadata_registry": registry,
        "metadata_completeness_score": _metadata_completeness_score(registry, research_lane),
        "biological_interpretation_made": False,
        "clinical_decision_made": False,
        "dry_run_only": True,
        "external_tools_executed": False,
        "raw_genomic_files_parsed": False,
        "final_acmg_classification_made": False,
        "network_called": False,
        "raw_genomic_data_sent": False,
    }


def _normalise_registry(registry: dict[str, Any] | None) -> dict[str, Any]:
    registry = registry or {}
    return {
        "project_metadata": {
            "title": str(_get(registry, "project_metadata", "title", default="")),
            "study_description": str(_get(registry, "project_metadata", "study_description", default="")),
            "institution": str(_get(registry, "project_metadata", "institution", default="")),
            "pi_or_submitter_declared": _bool(_get(registry, "project_metadata", "pi_or_submitter_declared")),
            "orcid_declared": _bool(_get(registry, "project_metadata", "orcid_declared")),
            "ethics_approval_declared": _bool(_get(registry, "project_metadata", "ethics_approval_declared")),
            "data_access_level": _choice(str(_get(registry, "project_metadata", "data_access_level", default="unknown")), {"open", "managed", "no_access", "unknown"}, "unknown"),
            "population_frequency_source_declared": _bool(_get(registry, "project_metadata", "population_frequency_source_declared")),
            "clinvar_clingen_gnomad_or_indian_frequency_source_declared": _bool(
                _get(registry, "project_metadata", "clinvar_clingen_gnomad_or_indian_frequency_source_declared")
            ),
        },
        "sample_metadata": {
            "sample_count_declared": _bool(_get(registry, "sample_metadata", "sample_count_declared")),
            "cohort_labels_declared": _bool(_get(registry, "sample_metadata", "cohort_labels_declared")),
            "phenotype_metadata_declared": _bool(_get(registry, "sample_metadata", "phenotype_metadata_declared")),
            "geographic_resolution_declared": _bool(_get(registry, "sample_metadata", "geographic_resolution_declared")),
            "protected_or_isolated_population_declared": _bool(_get(registry, "sample_metadata", "protected_or_isolated_population_declared")),
        },
        "sequencing_metadata": {
            "sequencing_platform_declared": _bool(_get(registry, "sequencing_metadata", "sequencing_platform_declared")),
            "library_layout_declared": _bool(_get(registry, "sequencing_metadata", "library_layout_declared")),
            "target_coverage_declared": _bool(_get(registry, "sequencing_metadata", "target_coverage_declared")),
            "genome_build_declared": _bool(_get(registry, "sequencing_metadata", "genome_build_declared")),
            "batch_ids_declared": _bool(_get(registry, "sequencing_metadata", "batch_ids_declared")),
            "mixed_platform_or_batch_context_declared": _bool(_get(registry, "sequencing_metadata", "mixed_platform_or_batch_context_declared")),
        },
        "clinical_metadata": {
            "hpo_terms_declared": _bool(_get(registry, "clinical_metadata", "hpo_terms_declared")),
            "variant_list_declared": _bool(_get(registry, "clinical_metadata", "variant_list_declared")),
            "inheritance_model_declared": _bool(_get(registry, "clinical_metadata", "inheritance_model_declared")),
            "family_history_or_pedigree_declared": _bool(_get(registry, "clinical_metadata", "family_history_or_pedigree_declared")),
            "clinician_review_declared": _bool(_get(registry, "clinical_metadata", "clinician_review_declared")),
        },
        "population_genetics_metadata": {
            "population_labels_declared": _bool(_get(registry, "population_genetics_metadata", "population_labels_declared")),
            "qc_steps_declared": _bool(_get(registry, "population_genetics_metadata", "qc_steps_declared")),
            "ld_pruning_declared": _bool(_get(registry, "population_genetics_metadata", "ld_pruning_declared")),
            "batch_correction_declared": _bool(_get(registry, "population_genetics_metadata", "batch_correction_declared")),
            "sample_size_per_group_declared": _bool(_get(registry, "population_genetics_metadata", "sample_size_per_group_declared")),
        },
    }


def _population_missing(registry: dict[str, Any], text: str) -> list[str]:
    project = registry["project_metadata"]
    sample = registry["sample_metadata"]
    sequencing = registry["sequencing_metadata"]
    pop = registry["population_genetics_metadata"]
    missing = []
    checks = [
        ("sample_count_declared", sample["sample_count_declared"]),
        ("sample_size_per_group_declared", pop["sample_size_per_group_declared"]),
        ("cohort_labels_declared", sample["cohort_labels_declared"]),
        ("data_access_level", project["data_access_level"] != "unknown"),
        ("sequencing_platform_declared", sequencing["sequencing_platform_declared"]),
        ("genome_build_declared", sequencing["genome_build_declared"]),
        ("batch_ids_declared", sequencing["batch_ids_declared"]),
        ("qc_steps_declared", pop["qc_steps_declared"]),
    ]
    if _pca_or_admixture_context(text):
        checks.append(("ld_pruning_declared", pop["ld_pruning_declared"]))
    if sequencing["mixed_platform_or_batch_context_declared"]:
        checks.append(("batch_correction_declared", pop["batch_correction_declared"]))
    for name, present in checks:
        if not present:
            missing.append(name)
    return missing


def _population_caveats(registry: dict[str, Any], text: str) -> list[str]:
    caveats = ["Population genetics metadata is not machine-verified and requires human review."]
    if registry["sample_metadata"]["protected_or_isolated_population_declared"]:
        caveats.append("Protected, isolated, or founder population context was declared and requires explicit human review.")
    if "mixed platform" in text or registry["sequencing_metadata"]["mixed_platform_or_batch_context_declared"]:
        caveats.append("Mixed platform or batch context requires batch heterogeneity review.")
    return caveats


def _clinical_missing(registry: dict[str, Any]) -> list[str]:
    project = registry["project_metadata"]
    clinical = registry["clinical_metadata"]
    missing = []
    checks = [
        ("hpo_terms_declared", clinical["hpo_terms_declared"]),
        ("variant_list_declared", clinical["variant_list_declared"]),
        ("inheritance_model_declared", clinical["inheritance_model_declared"]),
        ("family_history_or_pedigree_declared", clinical["family_history_or_pedigree_declared"]),
        ("population_frequency_source_declared", project["population_frequency_source_declared"]),
        (
            "clinvar_clingen_gnomad_or_indian_frequency_source_declared",
            project["clinvar_clingen_gnomad_or_indian_frequency_source_declared"],
        ),
        ("clinician_review_declared", clinical["clinician_review_declared"]),
    ]
    for name, present in checks:
        if not present:
            missing.append(name)
    return missing


def _clinical_caveats(registry: dict[str, Any]) -> list[str]:
    caveats = ["Clinical genetics curation metadata is research-use only and not machine-verified."]
    if not registry["project_metadata"]["ethics_approval_declared"]:
        caveats.append("Ethics approval declaration is missing for clinical genetics research curation context.")
    caveats.append("No diagnosis, treatment recommendation, final ACMG classification, or clinical decision was made.")
    return caveats


def _classify_lane(text: str, uploaded_files: dict[str, str], workflow_selection: dict[str, Any], registry: dict[str, Any]) -> str:
    workflow_family = str(workflow_selection.get("workflow_family") or "")
    if _has_clinical_registry_signal(registry) or any(marker in text for marker in CLINICAL_CURATION_MARKERS):
        return "clinical_genetics_research_curation"
    if workflow_family and workflow_family != "insufficient_inputs":
        return "population_genetics"
    if uploaded_files or any(marker in text for marker in POPULATION_MARKERS):
        return "population_genetics"
    return "insufficient_inputs"


def _blocked_categories(text: str) -> list[str]:
    return [category for category, markers in OUT_OF_SCOPE_RULES if any(marker in text for marker in markers)]


def _combined_text(query: str | None, uploaded_files: dict[str, str], workflow_selection: dict[str, Any], registry: dict[str, Any]) -> str:
    fragments = [query or ""]
    fragments.extend(uploaded_files.keys())
    fragments.extend(uploaded_files.values())
    fragments.extend(str(workflow_selection.get(key, "")) for key in ("workflow_family", "rationale"))
    fragments.extend(_registry_text_values(registry))
    return " ".join(fragments).lower()


def _registry_text_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        values = []
        for child in value.values():
            values.extend(_registry_text_values(child))
        return values
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return []


def _metadata_completeness_score(registry: dict[str, Any], research_lane: str) -> float:
    if research_lane == "population_genetics":
        fields = [
            registry["sample_metadata"]["sample_count_declared"],
            registry["population_genetics_metadata"]["sample_size_per_group_declared"],
            registry["sample_metadata"]["cohort_labels_declared"],
            registry["project_metadata"]["data_access_level"] != "unknown",
            registry["sequencing_metadata"]["sequencing_platform_declared"],
            registry["sequencing_metadata"]["genome_build_declared"],
            registry["sequencing_metadata"]["batch_ids_declared"],
            registry["population_genetics_metadata"]["qc_steps_declared"],
            registry["population_genetics_metadata"]["ld_pruning_declared"],
        ]
    elif research_lane == "clinical_genetics_research_curation":
        fields = [
            registry["clinical_metadata"]["hpo_terms_declared"],
            registry["clinical_metadata"]["variant_list_declared"],
            registry["clinical_metadata"]["inheritance_model_declared"],
            registry["clinical_metadata"]["family_history_or_pedigree_declared"],
            registry["project_metadata"]["population_frequency_source_declared"],
            registry["project_metadata"]["clinvar_clingen_gnomad_or_indian_frequency_source_declared"],
            registry["clinical_metadata"]["clinician_review_declared"],
        ]
    else:
        return 0.0
    return round(sum(1 for item in fields if item) / len(fields), 3)


def _has_clinical_registry_signal(registry: dict[str, Any]) -> bool:
    return any(bool(value) for value in registry["clinical_metadata"].values())


def _pca_or_admixture_context(text: str) -> bool:
    return "pca" in text or "admixture" in text or "population structure" in text


def _get(registry: dict[str, Any], group: str, key: str, default: Any = False) -> Any:
    value = registry.get(group, {})
    if not isinstance(value, dict):
        return default
    return value.get(key, default)


def _choice(value: str, allowed: set[str], default: str) -> str:
    return value if value in allowed else default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _merge_unique(values: list[str]) -> list[str]:
    seen = set()
    merged = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(text)
    return merged
