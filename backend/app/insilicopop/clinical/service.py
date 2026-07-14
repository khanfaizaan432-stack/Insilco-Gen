from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.insilicopop.clinical.models import (
    ClinicalCaseIntake,
    ClinicalCaseIntakeResult,
    ClinicalHypothesisSummary,
    ClinicalIntakeIssue,
    PhenotypeState,
)
from app.insilicopop.clinical.validation import validate_clinical_case
from app.insilicopop.clinical.hpo_models import PhenotypeHpoCurationResult
from app.insilicopop.clinical.phenotype_curation import build_phenotype_hpo_curation
from app.insilicopop.clinical.inheritance_audit import build_pedigree_inheritance_audit
from app.insilicopop.clinical.pedigree_models import PedigreeInheritanceAuditResult


def build_clinical_case_intake(payload: dict[str, Any], *, request_text: str | None = None) -> ClinicalCaseIntakeResult:
    result, _ = build_clinical_case_with_curation(payload, request_text=request_text)
    return result


def build_clinical_case_with_curation(
    payload: dict[str, Any], *, request_text: str | None = None
) -> tuple[ClinicalCaseIntakeResult, PhenotypeHpoCurationResult | None]:
    intake, curation, _ = build_clinical_case_bundle(payload, request_text=request_text)
    return intake, curation


def build_clinical_case_bundle(
    payload: dict[str, Any], *, request_text: str | None = None
) -> tuple[ClinicalCaseIntakeResult, PhenotypeHpoCurationResult | None, PedigreeInheritanceAuditResult | None]:
    try:
        case = ClinicalCaseIntake.model_validate(payload)
    except ValidationError as exc:
        issues = [
            ClinicalIntakeIssue(
                code="schema_validation_error",
                field=".".join(str(part) for part in error.get("loc", ())) or None,
                message=str(error.get("msg", "Invalid clinical intake field.")),
            )
            for error in exc.errors(include_url=False, include_input=False)
        ]
        return _invalid_result(payload, issues), None, None

    errors, warnings, missing, blocks = validate_clinical_case(case, request_text=request_text)
    completeness = "blocked" if blocks else "incomplete" if errors or warnings or missing else "complete"
    counts = {state.value: 0 for state in PhenotypeState}
    for observation in case.phenotypes:
        counts[observation.state.value] += 1
    result = ClinicalCaseIntakeResult(
        pseudonymous_case_id=case.pseudonymous_case_id,
        intended_use=case.intended_use,
        redaction_declared=case.redaction_declared is True,
        intake_completeness=completeness,
        phenotype_state_counts=counts,
        phenotype_observation_ids=[item.observation_id for item in case.phenotypes],
        candidate_variant_count=len(case.candidate_variants),
        candidate_variant_ids=[item.candidate_id for item in case.candidate_variants],
        supplied_candidate_variants=sorted(case.candidate_variants, key=lambda item: item.candidate_id),
        pedigree_record_count=len(case.pedigree),
        pedigree_member_ids=[item.family_member_id for item in case.pedigree],
        supplied_hypotheses=[
            ClinicalHypothesisSummary(
                hypothesis_id=item.hypothesis_id,
                hypothesis_type=item.hypothesis_type.value,
                inheritance_candidate=item.inheritance_candidate.value if item.inheritance_candidate else None,
                source=item.source,
                review_state=item.review_state.value,
            )
            for item in case.hypotheses
        ],
        validation_errors=errors,
        validation_warnings=warnings,
        missing_information=missing,
        policy_blocks=blocks,
        reviewer_status=case.reviewer_status.value,
    )
    curation = build_phenotype_hpo_curation(
        case,
        validation_errors=errors,
        validation_warnings=warnings,
        missing_information=missing,
        policy_blocks=blocks,
    )
    inheritance_audit = build_pedigree_inheritance_audit(
        case,
        validation_errors=errors,
        validation_warnings=warnings,
        missing_information=missing,
        policy_blocks=blocks,
    )
    return result, curation, inheritance_audit


def _invalid_result(payload: dict[str, Any], issues: list[ClinicalIntakeIssue]) -> ClinicalCaseIntakeResult:
    raw_id = payload.get("pseudonymous_case_id")
    case_id = str(raw_id)[:80] if isinstance(raw_id, (str, int)) and str(raw_id).strip() else "invalid_case_id"
    return ClinicalCaseIntakeResult(
        pseudonymous_case_id=case_id,
        intended_use=str(payload.get("intended_use") or "invalid"),
        redaction_declared=payload.get("redaction_declared") is True,
        intake_completeness="invalid",
        phenotype_state_counts={state.value: 0 for state in PhenotypeState},
        phenotype_observation_ids=[],
        candidate_variant_count=0,
        candidate_variant_ids=[],
        pedigree_record_count=0,
        pedigree_member_ids=[],
        supplied_hypotheses=[],
        validation_errors=issues,
        validation_warnings=[],
        missing_information=[],
        policy_blocks=[],
        reviewer_status="invalid",
    )
