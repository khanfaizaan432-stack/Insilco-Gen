from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from app.insilicopop.clinical.models import (
    ClinicalCaseIntake,
    ClinicalCaseIntakeResult,
    ClinicalHypothesisSummary,
    ClinicalIntakeIssue,
    PhenotypeState,
)
from app.insilicopop.clinical.validation import (
    detect_direct_identifiers,
    sanitized_clinical_case,
    sanitized_global_intake_context,
    validate_clinical_case,
)
from app.insilicopop.clinical.hpo_models import PhenotypeHpoCurationResult
from app.insilicopop.clinical.phenotype_curation import build_phenotype_hpo_curation
from app.insilicopop.clinical.inheritance_audit import build_pedigree_inheritance_audit
from app.insilicopop.clinical.pedigree_models import PedigreeInheritanceAuditResult
from app.insilicopop.clinical.variant_models import VariantIntelligenceResult
from app.insilicopop.clinical.variant_service import build_variant_intelligence
from app.insilicopop.clinical.pretest_assessment import build_pretest_assessment
from app.insilicopop.clinical.pretest_models import PreTestAssessmentResult
from app.insilicopop.clinical.test_strategy import build_test_strategy_workspace
from app.insilicopop.clinical.test_strategy_models import TestStrategyWorkspaceResult
from app.insilicopop.clinical.result_evidence import build_result_evidence_workspace
from app.insilicopop.clinical.result_evidence_models import ResultEvidenceWorkspaceResult


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
    intake, curation, inheritance_audit, _ = build_clinical_case_extended_bundle(payload, request_text=request_text)
    return intake, curation, inheritance_audit


def build_clinical_case_extended_bundle(
    payload: dict[str, Any], *, request_text: str | None = None
) -> tuple[
    ClinicalCaseIntakeResult,
    PhenotypeHpoCurationResult | None,
    PedigreeInheritanceAuditResult | None,
    VariantIntelligenceResult | None,
]:
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
        return _invalid_result(payload, issues), None, None, None

    errors, warnings, missing, blocks = validate_clinical_case(case, request_text=request_text)
    safe_case = sanitized_clinical_case(case)
    completeness = "blocked" if blocks else "incomplete" if errors or warnings or missing else "complete"
    counts = {state.value: 0 for state in PhenotypeState}
    for observation in safe_case.phenotypes:
        counts[observation.state.value] += 1
    result = ClinicalCaseIntakeResult(
        pseudonymous_case_id=safe_case.pseudonymous_case_id,
        intended_use=safe_case.intended_use,
        redaction_declared=safe_case.redaction_declared is True,
        intake_completeness=completeness,
        phenotype_state_counts=counts,
        phenotype_observation_ids=[item.observation_id for item in safe_case.phenotypes],
        candidate_variant_count=len(safe_case.candidate_variants),
        candidate_variant_ids=[item.candidate_id for item in safe_case.candidate_variants],
        supplied_candidate_variants=sorted(safe_case.candidate_variants, key=lambda item: item.candidate_id),
        pedigree_record_count=len(safe_case.pedigree),
        pedigree_member_ids=[item.family_member_id for item in safe_case.pedigree],
        supplied_hypotheses=[
            ClinicalHypothesisSummary(
                hypothesis_id=item.hypothesis_id,
                hypothesis_type=item.hypothesis_type.value,
                inheritance_candidate=item.inheritance_candidate.value if item.inheritance_candidate else None,
                source=item.source,
                review_state=item.review_state.value,
            )
            for item in safe_case.hypotheses
        ],
        validation_errors=errors,
        validation_warnings=warnings,
        missing_information=missing,
        policy_blocks=blocks,
        reviewer_status=safe_case.reviewer_status.value,
        global_intake_context=sanitized_global_intake_context(safe_case),
    )
    curation = build_phenotype_hpo_curation(
        safe_case,
        validation_errors=errors,
        validation_warnings=warnings,
        missing_information=missing,
        policy_blocks=blocks,
    )
    inheritance_audit = build_pedigree_inheritance_audit(
        safe_case,
        validation_errors=errors,
        validation_warnings=warnings,
        missing_information=missing,
        policy_blocks=blocks,
    )
    variant_intelligence = build_variant_intelligence(safe_case)
    return result, curation, inheritance_audit, variant_intelligence


def build_clinical_case_full_bundle(
    payload: dict[str, Any], *, request_text: str | None = None
) -> tuple[
    ClinicalCaseIntakeResult,
    PhenotypeHpoCurationResult | None,
    PedigreeInheritanceAuditResult | None,
    VariantIntelligenceResult | None,
    PreTestAssessmentResult | None,
]:
    intake, curation, inheritance_audit, variant_intelligence = build_clinical_case_extended_bundle(
        payload, request_text=request_text
    )
    try:
        case = ClinicalCaseIntake.model_validate(payload)
    except ValidationError:
        return intake, curation, inheritance_audit, variant_intelligence, None
    errors, warnings, missing, blocks = validate_clinical_case(case, request_text=request_text)
    safe_case = sanitized_clinical_case(case)
    pretest_assessment = build_pretest_assessment(
        safe_case,
        validation_errors=errors,
        validation_warnings=warnings,
        validation_missing_information=missing,
        policy_blocks=blocks,
        phenotype_curation=curation,
        pedigree_audit=inheritance_audit,
    )
    return intake, curation, inheritance_audit, variant_intelligence, pretest_assessment


def build_clinical_case_strategy_bundle(
    payload: dict[str, Any], *, request_text: str | None = None
) -> tuple[
    ClinicalCaseIntakeResult,
    PhenotypeHpoCurationResult | None,
    PedigreeInheritanceAuditResult | None,
    VariantIntelligenceResult | None,
    PreTestAssessmentResult | None,
    TestStrategyWorkspaceResult | None,
]:
    intake, curation, inheritance_audit, variant_intelligence, pretest_assessment = build_clinical_case_full_bundle(
        payload, request_text=request_text
    )
    try:
        case = ClinicalCaseIntake.model_validate(payload)
    except ValidationError:
        return intake, curation, inheritance_audit, variant_intelligence, pretest_assessment, None
    safe_case = sanitized_clinical_case(case)
    strategy_workspace = build_test_strategy_workspace(
        safe_case,
        pretest_assessment=pretest_assessment,
        phenotype_curation=curation,
        pedigree_audit=inheritance_audit,
    )
    return intake, curation, inheritance_audit, variant_intelligence, pretest_assessment, strategy_workspace


def build_clinical_case_result_evidence_bundle(
    payload: dict[str, Any], *, request_text: str | None = None
) -> tuple[
    ClinicalCaseIntakeResult,
    PhenotypeHpoCurationResult | None,
    PedigreeInheritanceAuditResult | None,
    VariantIntelligenceResult | None,
    PreTestAssessmentResult | None,
    TestStrategyWorkspaceResult | None,
    ResultEvidenceWorkspaceResult | None,
]:
    (
        intake,
        curation,
        inheritance_audit,
        variant_intelligence,
        pretest_assessment,
        strategy_workspace,
    ) = build_clinical_case_strategy_bundle(payload, request_text=request_text)
    try:
        case = ClinicalCaseIntake.model_validate(payload)
    except ValidationError:
        return (
            intake,
            curation,
            inheritance_audit,
            variant_intelligence,
            pretest_assessment,
            strategy_workspace,
            None,
        )
    safe_case = sanitized_clinical_case(case)
    result_evidence_workspace = build_result_evidence_workspace(
        safe_case,
        pretest_assessment=pretest_assessment,
        test_strategy_workspace=strategy_workspace,
    )
    return (
        intake,
        curation,
        inheritance_audit,
        variant_intelligence,
        pretest_assessment,
        strategy_workspace,
        result_evidence_workspace,
    )


def _invalid_result(payload: dict[str, Any], issues: list[ClinicalIntakeIssue]) -> ClinicalCaseIntakeResult:
    raw_id = payload.get("pseudonymous_case_id")
    raw_id_text = str(raw_id) if isinstance(raw_id, (str, int)) else ""
    case_id = (
        raw_id_text[:80]
        if raw_id_text
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", raw_id_text)
        and not detect_direct_identifiers(raw_id_text, "pseudonymous_case_id")
        else "invalid_case_id"
    )
    return ClinicalCaseIntakeResult(
        pseudonymous_case_id=case_id,
        intended_use=(
            "clinical_genetics_research_curation"
            if payload.get("intended_use") == "clinical_genetics_research_curation"
            else "invalid"
        ),
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
