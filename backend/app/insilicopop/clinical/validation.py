from __future__ import annotations

import re
from collections import Counter

from app.insilicopop.clinical.models import (
    ClinicalCaseIntake,
    ClinicalIntakeIssue,
    ClinicalPolicyBlock,
    HypothesisType,
)


DIRECT_IDENTIFIER_RULES = (
    ("email_address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("phone_number", re.compile(r"\b(?:\+?\d[\d .()-]{7,}\d)\b")),
    ("medical_record_number", re.compile(r"\b(?:mrn|medical record|hospital id)\s*[:#-]?\s*[A-Z0-9-]{4,}\b", re.IGNORECASE)),
)

POLICY_RULES = (
    ("diagnosis_request", "diagnosis", ("diagnos", "confirm disease")),
    ("treatment_request", "treatment", ("treatment recommendation", "recommend treatment", "prescribe", "therapy recommendation")),
    ("final_classification_request", "classification", ("final acmg", "acmg classification", "classify pathogenic", "classify benign", "pathogenic conclusion", "benign conclusion")),
    ("clinical_sign_out_request", "clinical_sign_out", ("clinical sign-out", "sign out this case", "signout")),
    ("patient_return_request", "patient_return", ("return results to patient", "patient-facing result", "send result to patient")),
    ("secondary_findings_return_request", "secondary_findings", ("return secondary findings", "secondary findings return")),
    ("external_raw_data_request", "external_data", ("send raw genomic", "upload vcf externally", "send unredacted", "external llm", "external api")),
    ("consumer_ancestry_request", "social_identity", ("consumer ancestry", "infer ancestry")),
    ("caste_community_religion_request", "social_identity", ("infer caste", "infer community", "infer religion", "caste", "religion inference")),
    ("purity_superiority_request", "social_identity", ("genetic purity", "superior population", "infer purity", "racial superiority")),
    ("pca_admixture_identity_request", "population_identity", ("pca proves identity", "admixture proves ancestry", "literal ancestry from admixture")),
)


def validate_clinical_case(
    case: ClinicalCaseIntake,
    *,
    request_text: str | None = None,
) -> tuple[list[ClinicalIntakeIssue], list[ClinicalIntakeIssue], list[ClinicalIntakeIssue], list[ClinicalPolicyBlock]]:
    errors: list[ClinicalIntakeIssue] = []
    warnings: list[ClinicalIntakeIssue] = []
    missing: list[ClinicalIntakeIssue] = []
    blocks: list[ClinicalPolicyBlock] = []

    if case.redaction_declared is not True:
        errors.append(_issue("redaction_declaration_required", "redaction_declared", "An explicit true redaction declaration is required."))
    if not case.phenotypes:
        missing.append(_issue("phenotypes_not_supplied", "phenotypes", "No structured phenotype observations were supplied."))
    if not case.candidate_variants:
        missing.append(_issue("candidate_variants_not_supplied", "candidate_variants", "No candidate variant intake records were supplied."))
    if not case.provenance:
        missing.append(_issue("case_provenance_not_supplied", "provenance", "No case-level provenance was supplied."))
    if not case.genome_build:
        missing.append(_issue("genome_build_not_declared", "genome_build", "No case-level genome build was declared."))
    if case.phenotype_curation is not None and not case.phenotype_curation.snippets:
        missing.append(_issue("phenotype_snippets_not_supplied", "phenotype_curation.snippets", "No bounded redacted phenotype snippets were supplied for HPO curation."))

    for namespace, values in (
        ("phenotype", [item.observation_id for item in case.phenotypes]),
        ("candidate_variant", [item.candidate_id for item in case.candidate_variants]),
        ("pedigree", [item.family_member_id for item in case.pedigree]),
        ("hypothesis", [item.hypothesis_id for item in case.hypotheses]),
        ("phenotype_snippet", [item.snippet_id for item in case.phenotype_curation.snippets] if case.phenotype_curation else []),
    ):
        for identifier, count in sorted(Counter(values).items()):
            if count > 1:
                errors.append(_issue("duplicate_local_identifier", namespace, f"Duplicate {namespace} identifier.", identifier))

    for variant in case.candidate_variants:
        if not _has_content(variant.gene) and not any(_has_content(item) for item in variant.submitted_hgvs) and not (_has_content(variant.chromosome) and variant.position):
            warnings.append(_issue("candidate_variant_incomplete", "candidate_variants", "Candidate variant lacks gene, HGVS, or chromosome-position context.", variant.candidate_id))
        if (variant.ref is None) != (variant.alt is None):
            warnings.append(_issue("candidate_variant_ref_alt_incomplete", "candidate_variants", "REF and ALT should be supplied together when used.", variant.candidate_id))
        if variant.genome_build and case.genome_build and variant.genome_build != case.genome_build:
            warnings.append(_issue("candidate_variant_build_mismatch", "candidate_variants", "Candidate and case genome-build declarations differ.", variant.candidate_id))
        for field_name, value in _candidate_biological_strings(variant):
            if value != value.strip():
                warnings.append(
                    _issue(
                        "candidate_biological_string_formatting_anomaly",
                        f"candidate_variants.{field_name}",
                        "The exact supplied biological string is preserved; surrounding whitespace requires manual review and is not normalized for deterministic comparison.",
                        variant.candidate_id,
                    )
                )

    known_phenotypes = {item.observation_id for item in case.phenotypes}
    for member in case.pedigree:
        for reference in member.phenotype_references:
            if reference not in known_phenotypes:
                warnings.append(_issue("unknown_phenotype_reference", "pedigree", "Pedigree phenotype reference was not found in this intake.", member.family_member_id))

    for hypothesis in case.hypotheses:
        if hypothesis.hypothesis_type == HypothesisType.INHERITANCE and hypothesis.inheritance_candidate is None:
            warnings.append(_issue("inheritance_candidate_missing", "hypotheses", "Inheritance hypothesis has no typed candidate value.", hypothesis.hypothesis_id))

    text_fields: list[tuple[str, str | None, str | None]] = [("case_label", case.case_label, None)]
    for item in case.phenotypes:
        text_fields.extend((("phenotype.notes", item.notes, item.observation_id), ("phenotype.source_span", item.redacted_source_span, item.observation_id)))
    for item in case.pedigree:
        text_fields.append(("pedigree.notes", item.notes, item.family_member_id))
    if case.phenotype_curation:
        for snippet in case.phenotype_curation.snippets:
            if snippet.redaction_declared is not True:
                errors.append(_issue("snippet_redaction_declaration_required", "phenotype_curation.snippets.redaction_declared", "Each phenotype snippet requires an explicit true redaction declaration.", snippet.snippet_id))
            if not snippet.provenance:
                missing.append(_issue("snippet_provenance_not_supplied", "phenotype_curation.snippets.provenance", "Phenotype snippet provenance was not supplied.", snippet.snippet_id))
            text_fields.append(("phenotype_curation.snippet", snippet.redacted_text, snippet.snippet_id))
            text_fields.append(("phenotype_curation.source_label", snippet.source_label, snippet.snippet_id))
            text_fields.append(("phenotype_curation.supplied_onset", snippet.supplied_onset, snippet.snippet_id))
            text_fields.append(("phenotype_curation.supplied_temporal_context", snippet.supplied_temporal_context, snippet.snippet_id))
    for field, value, record_id in text_fields:
        for rule_code, pattern in DIRECT_IDENTIFIER_RULES:
            if value and pattern.search(value):
                blocks.append(ClinicalPolicyBlock(code=rule_code, category="direct_identifier", message=f"Bounded direct-identifier rule matched {field}{' for ' + record_id if record_id else ''}."))

    policy_text = " ".join([*(case.requested_actions or []), request_text or ""]).lower()
    for code, category, terms in POLICY_RULES:
        if any(term in policy_text for term in terms):
            blocks.append(ClinicalPolicyBlock(code=code, category=category, message="Requested action is outside clinical genetics research-curation scope."))

    return errors, warnings, missing, _deduplicate_blocks(blocks)


def _issue(code: str, field: str, message: str, record_id: str | None = None) -> ClinicalIntakeIssue:
    return ClinicalIntakeIssue(code=code, field=field, record_id=record_id, message=message)


def _deduplicate_blocks(blocks: list[ClinicalPolicyBlock]) -> list[ClinicalPolicyBlock]:
    unique = {(item.code, item.category): item for item in blocks}
    return [unique[key] for key in sorted(unique)]


def _has_content(value: str | None) -> bool:
    return bool(value and value.strip())


def _candidate_biological_strings(variant) -> list[tuple[str, str]]:
    values = [
        ("submitted_representation", variant.submitted_representation),
        ("gene", variant.gene),
        ("transcript", variant.transcript),
        ("genome_build", variant.genome_build),
        ("chromosome", variant.chromosome),
        ("ref", variant.ref),
        ("alt", variant.alt),
    ]
    values.extend((f"submitted_hgvs.{index}", value) for index, value in enumerate(variant.submitted_hgvs))
    values.extend((f"provenance.{index}.reference", item.reference) for index, item in enumerate(variant.provenance))
    return [(field, value) for field, value in values if value is not None]
