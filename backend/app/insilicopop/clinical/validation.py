from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

from pydantic import BaseModel

from app.insilicopop.clinical.models import (
    ClinicalCaseIntake,
    ClinicalIntakeIssue,
    ClinicalPolicyBlock,
    HypothesisType,
)


EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PATIENT_NAME_PATTERN = re.compile(
    r"\b(?:patient|proband|subject)\s*(?:full\s*)?name\s*[:#-]\s*[^\r\n,;]{2,100}",
    re.IGNORECASE,
)
CLINICAL_ID_PATTERN = re.compile(
    r"\b(?P<label>uhid|mrn|medical\s+record(?:\s+number)?|hospital\s+(?:id|number|registration(?:\s+(?:id|number|no\.?))?)|registration\s+(?:id|number|no\.?)|patient\s+id)"
    r"\s*(?:[:#=-]\s*|\s+)[A-Z0-9][A-Z0-9./-]{3,}\b",
    re.IGNORECASE,
)
AADHAAR_PATTERN = re.compile(
    r"\b(?:aadhaar|aadhar|uidai)(?:\s+(?:id|number|no\.?))?\s*[:#-]?\s*\d{4}[ -]?\d{4}[ -]?\d{4}\b",
    re.IGNORECASE,
)
PASSPORT_PATTERN = re.compile(r"\bpassport(?:\s+(?:id|number|no\.?))?\s*[:#-]?\s*[A-Z][0-9]{7}\b", re.IGNORECASE)
INSURANCE_PATTERN = re.compile(
    r"\b(?:insurance|member|beneficiary)(?:\s+(?:member))?\s*(?:id|number|no\.?)\s*[:#-]?\s*[A-Z0-9][A-Z0-9./-]{4,}\b",
    re.IGNORECASE,
)
PHONE_LABEL_PATTERN = re.compile(
    r"\b(?:patient\s+)?(?:phone|mobile|telephone|tel|contact|whatsapp)(?:\s+(?:number|no\.?))?\s*[:#-]\s*(?:\+?\d[\d ()-]{7,}\d)",
    re.IGNORECASE,
)
INTERNATIONAL_PHONE_PATTERN = re.compile(r"(?<![A-Z0-9_])\+\d{1,3}[ ()-]+\d[\d ()-]{6,}\d\b", re.IGNORECASE)
FORMATTED_PHONE_PATTERN = re.compile(r"(?<![A-Z0-9_])(?:\(?\d{2,4}\)?[ -]){2,}\d{3,5}\b")
ADDRESS_LABEL_PATTERN = re.compile(r"\b(?:patient|home|postal|residential|mailing)?\s*address\s*[:#-]", re.IGNORECASE)
STREET_ADDRESS_PATTERN = re.compile(
    r"\b(?:flat|house|plot|door|room)?\s*[A-Z0-9/-]{1,8}[, ]+(?:[A-Z0-9.'’-]+[ ,]+){1,8}"
    r"(?:street|st|road|rd|avenue|ave|lane|ln|marg|nagar|colony|sector|block)\b",
    re.IGNORECASE,
)
POSTAL_LINE_PATTERN = re.compile(r"\b(?:pin|pincode|postal\s+code|zip)\s*[:#-]?\s*[A-Z0-9 -]{4,10}\b", re.IGNORECASE)

# Retained as a narrow compatibility export. Field-aware validation below is
# authoritative and deliberately does not contain a catch-all numeric rule.
DIRECT_IDENTIFIER_RULES = (
    ("email_address", EMAIL_PATTERN),
    ("patient_name", PATIENT_NAME_PATTERN),
    ("medical_record_number", CLINICAL_ID_PATTERN),
    ("aadhaar_number", AADHAAR_PATTERN),
    ("passport_number", PASSPORT_PATTERN),
    ("insurance_member_number", INSURANCE_PATTERN),
    ("phone_number", PHONE_LABEL_PATTERN),
    ("street_address", STREET_ADDRESS_PATTERN),
)

SCIENTIFIC_FIELD_MARKERS = (
    "variant",
    "hgvs",
    "spdi",
    "chromosome",
    "position",
    "coordinate",
    "interval",
    "transcript",
    "accession",
    "genome_build",
    "notation",
    "report_date",
    "pmid",
    "doi",
    "digest",
    "hash",
    "source_id",
    "claim_id",
    "sample_id",
    "model",
    "assay",
    "sequencing_method",
    "test_identifier",
    "test_type",
    "sample_type",
    "platform_identifier",
)

SCIENTIFIC_VALUE_PATTERNS = (
    re.compile(r"^(?:chr)?(?:[0-9]{1,2}|X|Y|MT):\d+(?:-\d+)?(?:\s+[ACGTN-]+>[ACGTN-]+)?$", re.IGNORECASE),
    re.compile(r"^[A-Z]{1,8}_[0-9]+(?:\.[0-9]+)?:\d+:[A-Z-]*:[A-Z-]*$", re.IGNORECASE),
    re.compile(r"^[A-Z]{1,8}_[0-9]+(?:\.[0-9]+)?:[cgmnpr]\.\S+$", re.IGNORECASE),
    re.compile(r"^(?:PMID\s*:\s*)?\d{1,9}$", re.IGNORECASE),
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^(?:HP|MONDO|ORPHA):\d+$", re.IGNORECASE),
    re.compile(r"^[A-Z]{1,10}_?\d{3,}(?:\.\d+)?$", re.IGNORECASE),
    re.compile(r"^(?:sha(?:1|224|256|384|512)\s*:\s*)?[A-F0-9]{32,}$", re.IGNORECASE),
    re.compile(r"^doi\s*:\s*10\.\d{4,9}/\S+$", re.IGNORECASE),
)

POLICY_RULES = (
    ("diagnosis_request", "diagnosis", ("diagnos", "confirm disease")),
    ("treatment_request", "treatment", ("treatment recommendation", "recommend treatment", "prescribe", "therapy recommendation")),
    ("final_classification_request", "classification", ("final acmg", "acmg classification", "classify pathogenic", "classify benign", "pathogenic conclusion", "benign conclusion")),
    ("clinical_sign_out_request", "clinical_sign_out", ("clinical sign-out", "sign out this case", "signout")),
    ("test_order_request", "test_order", ("order a genetic test", "order genetic test", "order this test", "place a test order", "automatically order")),
    ("test_recommendation_request", "test_strategy", ("recommend wes", "recommend wgs", "recommend a genetic test", "which genetic test", "select a genetic test")),
    ("patient_return_request", "patient_return", ("return results to patient", "patient-facing result", "send result to patient")),
    ("secondary_findings_return_request", "secondary_findings", ("return secondary findings", "secondary findings return")),
    ("external_raw_data_request", "external_data", ("send raw genomic", "upload vcf externally", "send unredacted", "external llm", "external api")),
    ("consumer_ancestry_request", "social_identity", ("consumer ancestry", "infer ancestry")),
    ("caste_community_religion_request", "social_identity", ("infer caste", "infer community", "infer religion", "caste", "religion inference")),
    ("purity_superiority_request", "social_identity", ("genetic purity", "superior population", "infer purity", "racial superiority")),
    ("pca_admixture_identity_request", "population_identity", ("pca proves identity", "admixture proves ancestry", "literal ancestry from admixture")),
    ("paternity_inference_request", "family_identity", ("infer paternity", "prove paternity", "hidden paternity", "non-paternity event")),
    ("sample_identity_inference_request", "sample_identity", ("infer sample swap", "identify a sample swap", "prove sample identity")),
    ("automatic_locale_inference_request", "locale", ("infer locale", "guess locale", "infer country from genetics", "infer nationality")),
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
        ("pretest_investigation", [item.investigation_id for item in case.pre_test_assessment.previous_investigations] if case.pre_test_assessment else []),
        ("pretest_family_report", [item.family_report_id for item in case.pre_test_assessment.known_family_reports] if case.pre_test_assessment else []),
        ("pretest_missing_request", [item.request_id for item in case.pre_test_assessment.supplied_missing_information_requests] if case.pre_test_assessment else []),
        ("pretest_checkpoint", [item.checkpoint_id for item in case.pre_test_assessment.clinician_checkpoints] if case.pre_test_assessment else []),
        ("pretest_history_item", [item.item_id for item in case.pre_test_assessment.clinical_history.items] if case.pre_test_assessment and case.pre_test_assessment.clinical_history else []),
        ("test_strategy_rule_input", [item.rule_input_id for item in case.test_strategy_workspace.rule_inputs] if case.test_strategy_workspace else []),
        ("test_strategy_fact", [fact.fact_id for item in case.test_strategy_workspace.rule_inputs for fact in item.trigger_facts] if case.test_strategy_workspace else []),
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
    if case.global_intake_context:
        text_fields.extend(_global_intake_text_fields(case.global_intake_context))
        language = case.global_intake_context.language_context
        if language and language.translation_status.value == "machine_translated":
            warnings.append(
                _issue(
                    "machine_translation_requires_expert_review",
                    "global_intake_context.language_context",
                    "Machine-translated clinical wording is preserved separately and requires human review before research use.",
                )
            )
        for laboratory in case.global_intake_context.laboratory_contexts:
            if laboratory.accreditation_wording_exact:
                warnings.append(
                    _issue(
                        "laboratory_accreditation_not_independently_verified",
                        "global_intake_context.laboratory_contexts.accreditation_wording_exact",
                        "Supplied laboratory accreditation wording was preserved but not independently verified.",
                        laboratory.laboratory_source_id,
                    )
                )
            if laboratory.genome_build_exact or laboratory.transcript_exact or laboratory.variant_notation_exact:
                warnings.append(
                    _issue(
                        "laboratory_notation_not_validated",
                        "global_intake_context.laboratory_contexts",
                        "Supplied build, transcript, and variant notation are preserved exactly and were not normalized or validated.",
                        laboratory.laboratory_source_id,
                    )
                )
        profile = case.global_intake_context.locale_profile
        if profile and profile.profile_type == "india" and profile.consanguinity_status.value == "reported":
            warnings.append(
                _issue(
                    "reported_relationship_context_requires_expert_review",
                    "global_intake_context.locale_profile.consanguinity_status",
                    "Reported family relationship context is descriptive only; no paternity, identity, or inheritance conclusion was inferred.",
                )
            )
    # Scan every bounded string field, including nested provenance and future
    # optional extensions. Field-aware rules preserve recognized science.
    text_fields.extend(_global_intake_text_fields(case, root_path="clinical_case_intake"))
    for field, value, record_id in text_fields:
        for rule_code in detect_direct_identifiers(value, field):
            blocks.append(
                ClinicalPolicyBlock(
                    code=rule_code,
                    category="direct_identifier",
                    message=f"Bounded direct-identifier rule matched {field}; source values and record identifiers are not reproduced.",
                )
            )

    for rule_code in detect_direct_identifiers(request_text, "request_text"):
        blocks.append(
            ClinicalPolicyBlock(
                code=rule_code,
                category="direct_identifier",
                message="Bounded direct-identifier rule matched request_text; the source value was removed before persistent state creation.",
            )
        )

    policy_text = " ".join([*(case.requested_actions or []), request_text or ""]).lower()
    for code, category, terms in POLICY_RULES:
        if any(term in policy_text for term in terms):
            blocks.append(ClinicalPolicyBlock(code=code, category=category, message="Requested action is outside clinical genetics research-curation scope."))

    return errors, warnings, missing, _deduplicate_blocks(blocks)


def sanitized_global_intake_context(case: ClinicalCaseIntake) -> dict[str, Any] | None:
    """Return persistence-safe v0.31 context without mutating exact in-memory source text."""

    if case.global_intake_context is None:
        return None
    return _sanitize_value(case.global_intake_context.model_dump(mode="json"), "global_intake_context")


def sanitized_clinical_case(case: ClinicalCaseIntake) -> ClinicalCaseIntake:
    """Return a recursively sanitized case for every downstream computation."""

    sanitized = _sanitize_value(case.model_dump(mode="json"), "clinical_case_intake")
    return ClinicalCaseIntake.model_validate(sanitized)


def sanitized_clinical_free_text(value: str | None, field_path: str = "clinical_free_text") -> str | None:
    """Remove an identifier-bearing free-text value before it can enter persistent state."""

    if value is None or not detect_direct_identifiers(value, field_path):
        return value
    return "[REDACTED_DIRECT_IDENTIFIER]"


def detect_direct_identifiers(value: str | None, field_path: str = "") -> list[str]:
    """Detect labelled identifiers while preserving recognized scientific forms."""

    if not value:
        return []
    matches: list[str] = []
    for code, pattern in (
        ("email_address", EMAIL_PATTERN),
        ("patient_name", PATIENT_NAME_PATTERN),
        ("medical_record_number", CLINICAL_ID_PATTERN),
        ("aadhaar_number", AADHAAR_PATTERN),
        ("passport_number", PASSPORT_PATTERN),
        ("insurance_member_number", INSURANCE_PATTERN),
    ):
        if pattern.search(value):
            matches.append(code)
    if _looks_like_address(value):
        matches.append("street_address")
    # Explicitly labelled contact data is governed regardless of the containing
    # field. The scientific-context exception applies only to ambiguous,
    # unlabelled numeric forms such as bounded assay identifiers.
    if PHONE_LABEL_PATTERN.search(value):
        matches.append("phone_number")
    elif not _is_scientific_context(field_path, value):
        if INTERNATIONAL_PHONE_PATTERN.search(value) or FORMATTED_PHONE_PATTERN.search(value):
            matches.append("phone_number")
    return list(dict.fromkeys(matches))


def contains_direct_identifier(value: Any, field_path: str = "") -> bool:
    if isinstance(value, dict):
        return any(contains_direct_identifier(item, f"{field_path}.{key}" if field_path else str(key)) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_direct_identifier(item, f"{field_path}.{index}" if field_path else str(index)) for index, item in enumerate(value))
    return isinstance(value, str) and bool(detect_direct_identifiers(value, field_path))


def _issue(code: str, field: str, message: str, record_id: str | None = None) -> ClinicalIntakeIssue:
    safe_record_id = (
        "REDACTED_RECORD_ID"
        if record_id and detect_direct_identifiers(record_id, "validation_issue.record_id")
        else record_id
    )
    return ClinicalIntakeIssue(code=code, field=field, record_id=safe_record_id, message=message)


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


def _global_intake_text_fields(
    context: BaseModel,
    *,
    root_path: str = "global_intake_context",
) -> list[tuple[str, str | None, str | None]]:
    fields: list[tuple[str, str | None, str | None]] = []

    def visit(value: Any, path: str, record_id: str | None = None) -> None:
        if isinstance(value, BaseModel):
            local_record_id = getattr(value, "laboratory_source_id", None) or getattr(value, "family_member_id", None) or record_id
            for name in type(value).model_fields:
                visit(getattr(value, name), f"{path}.{name}" if path else name, local_record_id)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}.{index}", record_id)
        elif isinstance(value, str):
            fields.append((path, value, record_id))

    visit(context, root_path)
    return fields


def _sanitize_value(value: Any, path: str = "") -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_value(item, f"{path}.{key}" if path else str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item, f"{path}.{index}" if path else str(index)) for index, item in enumerate(value)]
    if isinstance(value, str) and detect_direct_identifiers(value, path):
        return _redacted_value_for_path(path)
    return value


def _is_scientific_context(field_path: str, value: str) -> bool:
    lowered_path = field_path.lower()
    if any(marker in lowered_path for marker in SCIENTIFIC_FIELD_MARKERS):
        return True
    stripped = value.strip()
    return any(pattern.fullmatch(stripped) for pattern in SCIENTIFIC_VALUE_PATTERNS)


def _looks_like_address(value: str) -> bool:
    if STREET_ADDRESS_PATTERN.search(value) or POSTAL_LINE_PATTERN.search(value):
        return True
    if not ADDRESS_LABEL_PATTERN.search(value):
        return False
    following = value[ADDRESS_LABEL_PATTERN.search(value).end() :]
    lines = [line.strip() for line in following.splitlines() if line.strip()]
    if len(lines) >= 2:
        return True
    return bool(lines and (re.search(r"\b\d{5,6}\b", lines[0]) or STREET_ADDRESS_PATTERN.search(lines[0])))


def _redacted_value_for_path(path: str) -> str:
    final_name = path.rsplit(".", 1)[-1].lower()
    if final_name.endswith("_id") or final_name in {
        "pseudonymous_case_id",
        "observation_id",
        "candidate_id",
        "family_member_id",
        "hypothesis_id",
        "snippet_id",
    }:
        suffix = hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]
        return f"REDACTED-ID-{suffix}"
    return "[REDACTED_DIRECT_IDENTIFIER]"
