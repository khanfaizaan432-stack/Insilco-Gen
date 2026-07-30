from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Iterable

from pydantic import ValidationError

from app.insilicopop.clinical.hpo_models import PhenotypeHpoCurationResult
from app.insilicopop.clinical.jarvis_report_models import (
    CRITIC_SUITE_VERSION,
    JARVIS_BRIEFING_VERSION,
    REPORT_STUDIO_VERSION,
    SYNTHESIS_VERSION,
    ClaimEvidenceDrillDown,
    ClaimOriginCategory,
    ClaimSupportStatus,
    CriticFinding,
    CriticRun,
    CriticSeverity,
    CriticType,
    DraftReportSection,
    JarvisBriefingItem,
    JarvisCaseBriefing,
    JarvisReportReproducibility,
    JarvisSynthesisReportWorkspaceResult,
    ProposedSynthesisClaim,
    ReportHumanReviewAction,
    ReportHumanReviewStatus,
    ReportReviewActionResult,
    ReportReviewActionResultStatus,
    ReportReviewActionType,
    ReportReviewRejectionReason,
    SynthesisClaim,
)
from app.insilicopop.clinical.models import ClinicalCaseIntake, ClinicalCaseIntakeResult
from app.insilicopop.clinical.pedigree_models import PedigreeInheritanceAuditResult
from app.insilicopop.clinical.pretest_models import PreTestAssessmentResult
from app.insilicopop.clinical.result_evidence_models import (
    HumanReviewStatus,
    ResultEvidenceWorkspaceResult,
)
from app.insilicopop.clinical.specialist_agent_models import (
    CandidateStatus,
    SpecialistAgentWorkspaceResult,
    SpecialistReviewStatus,
)
from app.insilicopop.clinical.test_strategy_models import TestStrategyWorkspaceResult
from app.insilicopop.clinical.variant_models import VariantIntelligenceResult


_REPORT_SECTION_DEFINITIONS = (
    ("referral_summary", "Referral summary"),
    ("clinical_history", "Clinical history"),
    ("phenotype_hpo", "Phenotype and HPO findings"),
    ("pedigree_inheritance", "Pedigree and inheritance review"),
    ("previous_investigations", "Previous investigations"),
    ("missing_information_readiness", "Missing information and readiness"),
    ("test_strategy", "Test-strategy record"),
    ("result_normalization", "Supplied result and normalization record"),
    ("evidence_ledger", "Reviewed evidence ledger"),
    ("specialist_outputs", "Eligible reviewed specialist outputs"),
    ("candidate_acmg", "Candidate ACMG evidence"),
    ("disagreements_limitations", "Disagreements and limitations"),
    ("scientific_synthesis", "Scientific synthesis"),
    ("critic_findings", "Critic findings"),
    ("cited_draft_narrative", "Cited draft narrative"),
)

_FORBIDDEN_CONCLUSION_PATTERNS = {
    "diagnosis": re.compile(r"(?i)\b(?:we diagnose|is diagnosed with|diagnosis is)\b"),
    "treatment": re.compile(
        r"(?i)\b(?:we recommend treatment|start medication|prescribe[ds]?|treatment is indicated)\b"
    ),
    "test_ordering": re.compile(r"(?i)\b(?:we order|test has been ordered|order the test)\b"),
    "causal_certainty": re.compile(r"(?i)\b(?:causative variant|proves? causality)\b"),
    "final_classification": re.compile(
        r"(?i)\b(?:final acmg(?:/amp)? classification|criterion (?:is )?satisfied)\b"
    ),
    "clinical_approval": re.compile(r"(?i)\b(?:clinically approved report|clinical sign[- ]out complete)\b"),
}
_EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")
_DIRECT_IDENTIFIER_PATTERN = re.compile(
    r"(?i)\b(?:medical record number|hospital number|patient name|date of birth)\s*[:=]"
)


def build_jarvis_synthesis_report_workspace(
    case: ClinicalCaseIntake,
    *,
    intake: ClinicalCaseIntakeResult,
    phenotype_curation: PhenotypeHpoCurationResult | None,
    pedigree_audit: PedigreeInheritanceAuditResult | None,
    variant_intelligence: VariantIntelligenceResult | None,
    pretest_assessment: PreTestAssessmentResult | None,
    test_strategy_workspace: TestStrategyWorkspaceResult | None,
    result_evidence_workspace: ResultEvidenceWorkspaceResult | None,
    specialist_agent_workspace: SpecialistAgentWorkspaceResult | None,
) -> JarvisSynthesisReportWorkspaceResult | None:
    request = case.jarvis_synthesis_report_workspace
    if request is None:
        return None

    claims, section_claim_ids, available_fact_paths = _build_controlled_claims(
        case=case,
        intake=intake,
        phenotype_curation=phenotype_curation,
        pedigree_audit=pedigree_audit,
        variant_intelligence=variant_intelligence,
        pretest_assessment=pretest_assessment,
        test_strategy_workspace=test_strategy_workspace,
        result_evidence_workspace=result_evidence_workspace,
        specialist_agent_workspace=specialist_agent_workspace,
    )
    excluded_claims = _assess_proposed_claims(
        request.proposed_claims,
        available_fact_paths=available_fact_paths,
        result_evidence_workspace=result_evidence_workspace,
        specialist_agent_workspace=specialist_agent_workspace,
    )
    claims_by_id = {item.claim_id: item for item in claims}
    sections = _build_report_sections(claims_by_id, section_claim_ids)
    briefing = _build_briefing(
        case,
        intake=intake,
        pretest_assessment=pretest_assessment,
        test_strategy_workspace=test_strategy_workspace,
        result_evidence_workspace=result_evidence_workspace,
        specialist_agent_workspace=specialist_agent_workspace,
    )
    critic_runs, critic_findings = _run_critics(
        case_id=case.pseudonymous_case_id,
        claims=claims,
        excluded_claims=excluded_claims,
        sections=sections,
        result_evidence_workspace=result_evidence_workspace,
        specialist_agent_workspace=specialist_agent_workspace,
    )
    sections = _attach_critic_findings_section(sections, critic_findings)
    sections, applied_actions, action_results = _apply_report_review_actions(
        sections,
        request.review_actions,
        claims_by_id=claims_by_id,
        all_claim_ids={item.claim_id for item in claims},
    )
    drill_down = [_drill_down(item) for item in claims]
    pending_ids = _pending_human_decision_ids(
        sections,
        result_evidence_workspace=result_evidence_workspace,
        specialist_agent_workspace=specialist_agent_workspace,
    )
    source_versions = _source_versions(
        intake=intake,
        phenotype_curation=phenotype_curation,
        pedigree_audit=pedigree_audit,
        variant_intelligence=variant_intelligence,
        pretest_assessment=pretest_assessment,
        test_strategy_workspace=test_strategy_workspace,
        result_evidence_workspace=result_evidence_workspace,
        specialist_agent_workspace=specialist_agent_workspace,
    )
    source_hashes = _source_hashes(
        intake=intake,
        phenotype_curation=phenotype_curation,
        pedigree_audit=pedigree_audit,
        variant_intelligence=variant_intelligence,
        pretest_assessment=pretest_assessment,
        test_strategy_workspace=test_strategy_workspace,
        result_evidence_workspace=result_evidence_workspace,
        specialist_agent_workspace=specialist_agent_workspace,
    )
    reproducibility_payload = {
        "case_id": case.pseudonymous_case_id,
        "source_artifact_hashes": source_hashes,
        "claims": [item.model_dump(mode="json") for item in claims],
        "excluded_claims": [
            item.model_dump(mode="json") for item in excluded_claims
        ],
        "sections": [item.model_dump(mode="json") for item in sections],
        "critic_findings": [
            item.model_dump(mode="json") for item in critic_findings
        ],
        "action_results": [
            item.model_dump(mode="json") for item in action_results
        ],
    }
    reproducibility = JarvisReportReproducibility(
        source_artifact_versions=source_versions,
        source_artifact_hashes=source_hashes,
        synthesis_claim_ids=[item.claim_id for item in claims],
        report_section_ids=[item.section_id for item in sections],
        critic_run_ids=[item.critic_run_id for item in critic_runs],
        critic_finding_ids=[item.critic_finding_id for item in critic_findings],
        requested_review_actions=[
            item.model_dump(mode="json") for item in request.review_actions
        ],
        applied_review_actions=[
            item.model_dump(mode="json") for item in applied_actions
        ],
        review_action_results=[
            item.model_dump(mode="json") for item in action_results
        ],
        workspace_hash=_hash_payload(reproducibility_payload),
    )
    return JarvisSynthesisReportWorkspaceResult(
        pseudonymous_case_id=case.pseudonymous_case_id,
        briefing=briefing,
        synthesis_claims=claims,
        excluded_proposed_claims=excluded_claims,
        claim_evidence_drill_down=drill_down,
        critic_runs=critic_runs,
        critic_findings=critic_findings,
        report_sections=sections,
        cited_draft_narrative_section_id="REPORT-SECTION-CITED-DRAFT",
        pending_human_decision_ids=pending_ids,
        requested_review_actions=sorted(
            request.review_actions, key=lambda item: (item.timestamp, item.action_id)
        ),
        applied_review_actions=applied_actions,
        review_action_results=action_results,
        reproducibility=reproducibility,
    )


def _build_controlled_claims(
    *,
    case: ClinicalCaseIntake,
    intake: ClinicalCaseIntakeResult,
    phenotype_curation: PhenotypeHpoCurationResult | None,
    pedigree_audit: PedigreeInheritanceAuditResult | None,
    variant_intelligence: VariantIntelligenceResult | None,
    pretest_assessment: PreTestAssessmentResult | None,
    test_strategy_workspace: TestStrategyWorkspaceResult | None,
    result_evidence_workspace: ResultEvidenceWorkspaceResult | None,
    specialist_agent_workspace: SpecialistAgentWorkspaceResult | None,
) -> tuple[list[SynthesisClaim], dict[str, list[str]], set[str]]:
    claims: list[SynthesisClaim] = []
    section_claim_ids: dict[str, list[str]] = defaultdict(list)
    available_fact_paths: set[str] = set()

    def add(
        section: str,
        statement: str,
        origin: ClaimOriginCategory,
        support: ClaimSupportStatus,
        *,
        fact_paths: Iterable[str] = (),
        evidence_ids: Iterable[str] = (),
        output_ids: Iterable[str] = (),
        candidate_ids: Iterable[str] = (),
        decision_ids: Iterable[str] = (),
        uncertainty: str,
        eligible: bool = True,
    ) -> None:
        source_fact_paths = sorted(set(fact_paths))
        source_evidence_ids = sorted(set(evidence_ids))
        source_output_ids = sorted(set(output_ids))
        source_candidate_ids = sorted(set(candidate_ids))
        source_decision_ids = sorted(set(decision_ids))
        available_fact_paths.update(source_fact_paths)
        payload = {
            "section": section,
            "statement": statement,
            "origin": origin.value,
            "fact_paths": source_fact_paths,
            "evidence_ids": source_evidence_ids,
            "output_ids": source_output_ids,
            "candidate_ids": source_candidate_ids,
            "decision_ids": source_decision_ids,
        }
        claim = SynthesisClaim(
            claim_id=_stable_id("SYNTH-CLAIM", payload),
            statement=statement,
            origin_category=origin,
            support_status=support,
            uncertainty_language=uncertainty,
            source_fact_paths=source_fact_paths,
            source_evidence_ids=source_evidence_ids,
            source_specialist_output_ids=source_output_ids,
            source_candidate_criterion_ids=source_candidate_ids,
            source_human_decision_ids=source_decision_ids,
            eligible_for_report=eligible
            and support != ClaimSupportStatus.UNSUPPORTED,
        )
        if claim.claim_id not in {item.claim_id for item in claims}:
            claims.append(claim)
            section_claim_ids[section].append(claim.claim_id)

    if pretest_assessment and pretest_assessment.referral_packet:
        referral = pretest_assessment.referral_packet
        add(
            "referral_summary",
            (
                f"The supplied referral record identifies source "
                f"'{referral.source.value}'"
                + (
                    f" and records the reason as: {referral.reason_exact}"
                    if referral.reason_exact
                    else "."
                )
            ),
            ClaimOriginCategory.SUPPLIED_FACT,
            ClaimSupportStatus.SUPPORTED,
            fact_paths=("pre_test_assessment.referral_packet",),
            uncertainty="This restates a supplied referral record; it is not a diagnosis.",
        )
    else:
        add(
            "referral_summary",
            "A structured referral packet was not available in the controlled case artifacts.",
            ClaimOriginCategory.DETERMINISTIC_FINDING,
            ClaimSupportStatus.UNRESOLVED,
            fact_paths=("clinical_case_intake.intake_completeness",),
            uncertainty="Referral context remains incomplete.",
        )

    if pretest_assessment and pretest_assessment.clinical_history:
        history = pretest_assessment.clinical_history
        if history.summary_exact:
            add(
                "clinical_history",
                f"The supplied clinical-history summary states: {history.summary_exact}",
                ClaimOriginCategory.SUPPLIED_FACT,
                ClaimSupportStatus.SUPPORTED,
                fact_paths=("pre_test_assessment.clinical_history.summary_exact",),
                uncertainty="This is supplied history wording and remains subject to human review.",
            )
        for item in history.items:
            add(
                "clinical_history",
                f"Supplied history item '{item.category}' records: {item.exact_supplied_text}",
                ClaimOriginCategory.SUPPLIED_FACT,
                ClaimSupportStatus.SUPPORTED,
                fact_paths=(
                    f"pre_test_assessment.clinical_history.items.{item.item_id}",
                ),
                uncertainty="This restates a supplied structured history item.",
            )

    for observation in case.phenotypes:
        add(
            "phenotype_hpo",
            (
                f"Supplied phenotype observation {observation.observation_id} records "
                f"'{observation.supplied_term}' with state '{observation.state.value}'."
            ),
            ClaimOriginCategory.SUPPLIED_FACT,
            ClaimSupportStatus.SUPPORTED,
            fact_paths=(f"clinical_case_intake.phenotypes.{observation.observation_id}",),
            uncertainty="The observation is supplied and does not establish a diagnosis.",
        )
    if phenotype_curation:
        for item in phenotype_curation.promoted_observations:
            add(
                "phenotype_hpo",
                (
                    f"Human-confirmed phenotype curation links '{item.supplied_term}' "
                    f"to {item.hpo_id} with state '{item.state}'."
                ),
                ClaimOriginCategory.HUMAN_DECISION,
                ClaimSupportStatus.SUPPORTED,
                fact_paths=(
                    f"phenotype_hpo_curation.promoted_observations.{item.observation_id}",
                ),
                decision_ids=(item.observation_id,),
                uncertainty="This reflects a recorded curation decision, not a clinical conclusion.",
            )

    if pedigree_audit:
        for audit in pedigree_audit.inheritance_audits:
            add(
                "pedigree_inheritance",
                (
                    f"Deterministic inheritance audit {audit.audit_id} has status "
                    f"'{audit.status.value}': {audit.bounded_explanation}"
                ),
                ClaimOriginCategory.DETERMINISTIC_FINDING,
                (
                    ClaimSupportStatus.CONFLICTING
                    if audit.mendelian_inconsistency_ids
                    else ClaimSupportStatus.UNRESOLVED
                ),
                fact_paths=(f"pedigree_inheritance_audit.inheritance_audits.{audit.audit_id}",),
                uncertainty="This is a bounded consistency audit and does not establish inheritance clinically.",
            )

    if pretest_assessment:
        for item in pretest_assessment.previous_investigation_timeline:
            add(
                "previous_investigations",
                (
                    f"Previous investigation '{item.test_or_assessment_exact}'"
                    + (
                        f" records: {item.result_summary_exact}"
                        if item.result_summary_exact
                        else " has no supplied result summary."
                    )
                ),
                ClaimOriginCategory.SUPPLIED_FACT,
                ClaimSupportStatus.SUPPORTED,
                fact_paths=(
                    f"pre_test_assessment.previous_investigation_timeline.{item.investigation_id}",
                ),
                uncertainty="This is supplied prior-investigation information.",
            )
        add(
            "missing_information_readiness",
            (
                f"Deterministic pre-test assessment outcome is "
                f"'{pretest_assessment.assessment_outcome.value}', with "
                f"{pretest_assessment.open_missing_information_count} open information item(s)."
            ),
            ClaimOriginCategory.DETERMINISTIC_FINDING,
            ClaimSupportStatus.UNRESOLVED,
            fact_paths=("pre_test_assessment.assessment_outcome",),
            uncertainty="Readiness is a workflow state and does not approve or order testing.",
        )
        for item in pretest_assessment.missing_information_plan:
            if item.status.value == "open":
                add(
                    "missing_information_readiness",
                    f"Open information need {item.request_id}: {item.information_needed}",
                    ClaimOriginCategory.DETERMINISTIC_FINDING,
                    ClaimSupportStatus.UNRESOLVED,
                    fact_paths=(
                        f"pre_test_assessment.missing_information_plan.{item.request_id}",
                    ),
                    uncertainty="The information need remains unresolved.",
                )

    if test_strategy_workspace:
        for option in test_strategy_workspace.options:
            add(
                "test_strategy",
                (
                    f"Test-strategy option '{option.display_name}' is recorded as "
                    f"'{option.status}' with feasibility '{option.feasibility_status.value}'."
                ),
                ClaimOriginCategory.DETERMINISTIC_FINDING,
                ClaimSupportStatus.UNRESOLVED,
                fact_paths=(f"test_strategy_workspace.options.{option.option_id}",),
                uncertainty="The option is proposed, not approved, selected, or ordered.",
            )

    if result_evidence_workspace:
        for finding in result_evidence_workspace.normalized_findings:
            add(
                "result_normalization",
                (
                    f"Finding {finding.finding_id} has bounded normalization status "
                    f"'{finding.normalization_status.value}' under rule "
                    f"{finding.normalization_rule_id}."
                ),
                ClaimOriginCategory.NORMALIZED_FACT,
                (
                    ClaimSupportStatus.SUPPORTED
                    if finding.normalization_status.value == "normalized"
                    else ClaimSupportStatus.UNRESOLVED
                ),
                fact_paths=(
                    f"result_evidence_workspace.normalized_findings.{finding.finding_id}",
                ),
                uncertainty="Normalization does not provide pathogenicity or causal interpretation.",
            )
        for entry in result_evidence_workspace.ledger_entries:
            if entry.human_review_status not in {
                HumanReviewStatus.ACCEPTED_INTO_WORKSPACE,
                HumanReviewStatus.EDITED,
            }:
                continue
            support = (
                ClaimSupportStatus.CONFLICTING
                if entry.conflict_detected
                else ClaimSupportStatus.UNRESOLVED
                if entry.withdrawn_or_updated
                else ClaimSupportStatus.SUPPORTED
            )
            add(
                "evidence_ledger",
                (
                    f"Reviewed external source '{entry.source_title}' reports: "
                    f"{entry.source_statement}"
                ),
                ClaimOriginCategory.RETRIEVED_SOURCE_CLAIM,
                support,
                evidence_ids=(entry.ledger_entry_id,),
                decision_ids=(entry.ledger_entry_id,),
                uncertainty=(
                    "This is a reviewed source claim attributed to the external source; "
                    "it is not an InSilicoPop classification."
                ),
            )

    if specialist_agent_workspace:
        eligible_output_ids = set(specialist_agent_workspace.review_ready_output_ids)
        for output in specialist_agent_workspace.agent_outputs:
            if (
                output.agent_output_id not in eligible_output_ids
                or output.human_review_status
                not in {
                    SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
                    SpecialistReviewStatus.EDITED,
                }
            ):
                continue
            add(
                "specialist_outputs",
                (
                    f"Human-reviewed specialist output {output.agent_output_id} proposes: "
                    f"{output.human_reviewed_summary or output.summary}"
                ),
                ClaimOriginCategory.SPECIALIST_AGENT_PROPOSAL,
                (
                    ClaimSupportStatus.CONFLICTING
                    if output.contradictions
                    else ClaimSupportStatus.UNRESOLVED
                ),
                evidence_ids=output.source_ledger_entry_ids,
                output_ids=(output.agent_output_id,),
                decision_ids=(output.agent_output_id,),
                uncertainty="Accepted for discussion does not make the proposal an approved conclusion.",
            )
        for candidate in specialist_agent_workspace.candidate_criteria:
            support = (
                ClaimSupportStatus.CONFLICTING
                if candidate.candidate_status == CandidateStatus.CONFLICTING_SUPPORT
                or candidate.human_review_status == SpecialistReviewStatus.CONFLICTING
                else ClaimSupportStatus.UNRESOLVED
            )
            add(
                "candidate_acmg",
                (
                    f"Candidate ACMG evidence record {candidate.candidate_criterion_id} "
                    f"lists code {candidate.criterion_code.value} with candidate status "
                    f"'{candidate.candidate_status.value}'."
                ),
                ClaimOriginCategory.SPECIALIST_AGENT_PROPOSAL,
                support,
                evidence_ids=(
                    list(candidate.source_ledger_entry_ids)
                    + list(candidate.contradicting_ledger_entry_ids)
                ),
                output_ids=(candidate.agent_output_id,),
                candidate_ids=(candidate.candidate_criterion_id,),
                uncertainty=(
                    "Candidate evidence is uncombined, unscored, non-classifying, "
                    "and remains proposed_not_approved."
                ),
            )
        for assessment in specialist_agent_workspace.external_acmg_assessments:
            add(
                "candidate_acmg",
                (
                    f"External source '{assessment.external_source}' reports an ACMG "
                    "assessment"
                    + (
                        f" with classification '{assessment.external_classification_as_reported}'."
                        if assessment.external_classification_as_reported
                        else "."
                    )
                    + " This assessment was not assigned by InSilicoPop."
                ),
                ClaimOriginCategory.SUPPLIED_FACT,
                ClaimSupportStatus.UNRESOLVED,
                fact_paths=(
                    "specialist_agent_workspace.external_acmg_assessments."
                    f"{assessment.external_assessment_id}",
                ),
                uncertainty=(
                    "External ACMG assessment recorded; not assigned by InSilicoPop."
                ),
            )
        section_for_target = {
            "agent_output": "specialist_outputs",
            "candidate_criterion": "candidate_acmg",
            "spawn_request": "disagreements_limitations",
            "external_acmg_assessment": "candidate_acmg",
        }
        for action in specialist_agent_workspace.applied_review_actions:
            add(
                section_for_target.get(
                    action.target_type, "disagreements_limitations"
                ),
                (
                    f"Human review action {action.action_id} recorded "
                    f"'{action.action.value}' for {action.target_type} "
                    f"{action.target_id}."
                ),
                ClaimOriginCategory.HUMAN_DECISION,
                ClaimSupportStatus.SUPPORTED,
                fact_paths=(
                    f"specialist_agent_workspace.applied_review_actions.{action.action_id}",
                ),
                decision_ids=(action.action_id,),
                uncertainty=(
                    "This records a bounded human workflow decision and does not "
                    "create diagnosis, classification, or clinical approval."
                ),
            )
        for group in specialist_agent_workspace.disagreement_groups:
            add(
                "disagreements_limitations",
                (
                    f"Specialist disagreement {group.disagreement_group_id} remains "
                    "visible and requires human review."
                ),
                ClaimOriginCategory.DETERMINISTIC_FINDING,
                ClaimSupportStatus.CONFLICTING,
                evidence_ids=group.supporting_source_ids,
                output_ids=group.agent_output_ids,
                uncertainty="No majority vote or automatic dispute settlement was used.",
            )

    for item in intake.validation_errors + intake.validation_warnings:
        add(
            "disagreements_limitations",
            f"Intake limitation '{item.code}': {item.message}",
            ClaimOriginCategory.DETERMINISTIC_FINDING,
            ClaimSupportStatus.UNRESOLVED,
            fact_paths=("clinical_case_intake.validation",),
            uncertainty="The limitation remains subject to human review.",
        )
    claims.sort(key=lambda item: item.claim_id)
    for key in section_claim_ids:
        section_claim_ids[key] = sorted(set(section_claim_ids[key]))
    return claims, section_claim_ids, available_fact_paths


def _assess_proposed_claims(
    proposals: list[ProposedSynthesisClaim],
    *,
    available_fact_paths: set[str],
    result_evidence_workspace: ResultEvidenceWorkspaceResult | None,
    specialist_agent_workspace: SpecialistAgentWorkspaceResult | None,
) -> list[SynthesisClaim]:
    reviewed_ledger_ids = {
        item.ledger_entry_id
        for item in (
            result_evidence_workspace.ledger_entries
            if result_evidence_workspace
            else []
        )
        if item.human_review_status
        in {HumanReviewStatus.ACCEPTED_INTO_WORKSPACE, HumanReviewStatus.EDITED}
    }
    reviewed_output_ids = {
        item.agent_output_id
        for item in (
            specialist_agent_workspace.agent_outputs
            if specialist_agent_workspace
            else []
        )
        if item.agent_output_id
        in set(specialist_agent_workspace.review_ready_output_ids)
        and item.human_review_status
        in {
            SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
            SpecialistReviewStatus.EDITED,
        }
    } if specialist_agent_workspace else set()
    candidate_ids = {
        item.candidate_criterion_id
        for item in (
            specialist_agent_workspace.candidate_criteria
            if specialist_agent_workspace
            else []
        )
    }
    assessed = []
    for proposal in sorted(proposals, key=lambda item: item.proposal_id):
        references_valid = (
            set(proposal.source_fact_paths) <= available_fact_paths
            and set(proposal.source_evidence_ids) <= reviewed_ledger_ids
            and set(proposal.source_specialist_output_ids) <= reviewed_output_ids
            and set(proposal.source_candidate_criterion_ids) <= candidate_ids
            and bool(
                proposal.source_fact_paths
                or proposal.source_evidence_ids
                or proposal.source_specialist_output_ids
                or proposal.source_candidate_criterion_ids
            )
        )
        assessed.append(
            SynthesisClaim(
                claim_id=_stable_id(
                    "EXCLUDED-CLAIM",
                    proposal.model_dump(mode="json"),
                ),
                statement=proposal.statement,
                origin_category=ClaimOriginCategory.SPECIALIST_AGENT_PROPOSAL,
                support_status=(
                    ClaimSupportStatus.UNRESOLVED
                    if references_valid
                    else ClaimSupportStatus.UNSUPPORTED
                ),
                uncertainty_language=proposal.uncertainty_language,
                source_fact_paths=sorted(set(proposal.source_fact_paths)),
                source_evidence_ids=sorted(set(proposal.source_evidence_ids)),
                source_specialist_output_ids=sorted(
                    set(proposal.source_specialist_output_ids)
                ),
                source_candidate_criterion_ids=sorted(
                    set(proposal.source_candidate_criterion_ids)
                ),
                eligible_for_report=False,
            )
        )
    return assessed


def _build_report_sections(
    claims_by_id: dict[str, SynthesisClaim],
    section_claim_ids: dict[str, list[str]],
) -> list[DraftReportSection]:
    all_eligible_ids = sorted(
        item.claim_id for item in claims_by_id.values() if item.eligible_for_report
    )
    sections = []
    for section_type, title in _REPORT_SECTION_DEFINITIONS:
        if section_type in {"scientific_synthesis", "cited_draft_narrative"}:
            claim_ids = all_eligible_ids
        elif section_type == "critic_findings":
            claim_ids = []
        else:
            claim_ids = [
                claim_id
                for claim_id in section_claim_ids.get(section_type, [])
                if claims_by_id[claim_id].eligible_for_report
            ]
        narrative = _section_narrative(title, claim_ids, claims_by_id)
        section_id = (
            "REPORT-SECTION-CITED-DRAFT"
            if section_type == "cited_draft_narrative"
            else f"REPORT-SECTION-{section_type.upper().replace('_', '-')}"
        )
        citation_ids = sorted(
            {
                reference
                for claim_id in claim_ids
                for reference in (
                    claims_by_id[claim_id].source_evidence_ids
                    or claims_by_id[claim_id].source_fact_paths
                )
            }
        )
        sections.append(
            DraftReportSection(
                section_id=section_id,
                section_type=section_type,
                title=title,
                narrative=narrative,
                claim_ids=claim_ids,
                citation_ids=citation_ids,
            )
        )
    return sections


def _attach_critic_findings_section(
    sections: list[DraftReportSection],
    findings: list[CriticFinding],
) -> list[DraftReportSection]:
    updated = []
    for section in sections:
        if section.section_type != "critic_findings":
            updated.append(section)
            continue
        narrative = (
            "\n".join(
                (
                    f"{item.critic_type.value} critic {item.critic_finding_id} "
                    f"({item.severity.value}, {item.code}): {item.message}"
                )
                for item in findings
            )
            if findings
            else (
                "Critic findings: no bounded critic finding was recorded. "
                "This draft section requires human review."
            )
        )
        updated.append(
            section.model_copy(
                update={
                    "narrative": narrative,
                    "citation_ids": sorted(
                        {
                            source_id
                            for item in findings
                            for source_id in item.source_ids
                        }
                    ),
                }
            )
        )
    return updated


def _section_narrative(
    title: str,
    claim_ids: list[str],
    claims_by_id: dict[str, SynthesisClaim],
) -> str:
    if not claim_ids:
        return (
            f"{title}: no eligible controlled claim is available. "
            "This draft section requires human review."
        )
    return "\n".join(
        f"{claims_by_id[claim_id].statement} [claim:{claim_id}]"
        for claim_id in claim_ids
    )


def _build_briefing(
    case: ClinicalCaseIntake,
    *,
    intake: ClinicalCaseIntakeResult,
    pretest_assessment: PreTestAssessmentResult | None,
    test_strategy_workspace: TestStrategyWorkspaceResult | None,
    result_evidence_workspace: ResultEvidenceWorkspaceResult | None,
    specialist_agent_workspace: SpecialistAgentWorkspaceResult | None,
) -> JarvisCaseBriefing:
    raw_items: list[tuple[str, str, list[str], list[str]]] = [
        (
            "current_case_state",
            (
                f"Case {case.pseudonymous_case_id} intake state is "
                f"'{intake.intake_completeness}'."
            ),
            ["clinical_case_intake.intake_completeness"],
            [],
        )
    ]
    if pretest_assessment:
        raw_items.extend(
            [
                (
                    "missing_information",
                    (
                        f"{pretest_assessment.open_missing_information_count} open "
                        "missing-information item(s) remain."
                    ),
                    ["pre_test_assessment.missing_information_plan"],
                    [],
                ),
                (
                    "readiness_and_strategy",
                    (
                        f"Pre-test workflow state is "
                        f"'{pretest_assessment.assessment_outcome.value}'."
                    ),
                    ["pre_test_assessment.assessment_outcome"],
                    [],
                ),
            ]
        )
    if test_strategy_workspace:
        raw_items.append(
            (
                "readiness_and_strategy",
                (
                    f"{test_strategy_workspace.proposed_option_count} test-strategy "
                    "option(s) are proposed_not_approved."
                ),
                ["test_strategy_workspace.options"],
                [],
            )
        )
    if result_evidence_workspace:
        reviewed = [
            item
            for item in result_evidence_workspace.ledger_entries
            if item.human_review_status
            in {HumanReviewStatus.ACCEPTED_INTO_WORKSPACE, HumanReviewStatus.EDITED}
        ]
        raw_items.append(
            (
                "result_and_evidence",
                (
                    f"{len(result_evidence_workspace.normalized_findings)} normalized "
                    f"finding record(s) and {len(reviewed)} reviewed ledger entry or entries "
                    "are available."
                ),
                ["result_evidence_workspace.normalized_findings"],
                [item.ledger_entry_id for item in reviewed],
            )
        )
        for entry in reviewed:
            if entry.conflict_detected:
                raw_items.append(
                    (
                        "unresolved_conflict",
                        f"Evidence conflict {entry.conflict_group_id or entry.ledger_entry_id} remains unresolved.",
                        [],
                        [entry.ledger_entry_id],
                    )
                )
    if specialist_agent_workspace:
        for group in specialist_agent_workspace.disagreement_groups:
            raw_items.append(
                (
                    "specialist_disagreement",
                    f"Specialist disagreement {group.disagreement_group_id} requires human review.",
                    [],
                    list(group.supporting_source_ids),
                )
            )
    checkpoints = _next_checkpoints(
        pretest_assessment,
        result_evidence_workspace,
        specialist_agent_workspace,
    )
    raw_items.extend(
        ("next_workflow_checkpoint", item, [], []) for item in checkpoints
    )
    items = [
        JarvisBriefingItem(
            briefing_item_id=_stable_id(
                "JARVIS-ITEM",
                {
                    "category": category,
                    "statement": statement,
                    "fact_paths": fact_paths,
                    "evidence_ids": evidence_ids,
                },
            ),
            category=category,  # type: ignore[arg-type]
            statement=statement,
            source_fact_paths=fact_paths,
            source_evidence_ids=evidence_ids,
        )
        for category, statement, fact_paths, evidence_ids in raw_items
    ]
    pending_count = sum(
        1
        for item in items
        if item.category
        in {
            "missing_information",
            "specialist_disagreement",
            "unresolved_conflict",
        }
    )
    return JarvisCaseBriefing(
        briefing_id=_stable_id(
            "JARVIS-BRIEFING",
            [item.model_dump(mode="json") for item in items],
        ),
        items=items,
        missing_information_count=(
            pretest_assessment.open_missing_information_count
            if pretest_assessment
            else 0
        ),
        unresolved_conflict_count=sum(
            item.category == "unresolved_conflict" for item in items
        ),
        pending_human_decision_count=pending_count,
        next_workflow_checkpoints=checkpoints,
    )


def _next_checkpoints(
    pretest: PreTestAssessmentResult | None,
    evidence: ResultEvidenceWorkspaceResult | None,
    specialists: SpecialistAgentWorkspaceResult | None,
) -> list[str]:
    checkpoints = []
    if pretest and pretest.open_missing_information_count:
        checkpoints.append("Resolve or explicitly defer open missing-information items.")
    if evidence and any(
        item.human_review_status
        not in {HumanReviewStatus.ACCEPTED_INTO_WORKSPACE, HumanReviewStatus.EDITED}
        for item in evidence.ledger_entries
    ):
        checkpoints.append("Complete human review of pending evidence-ledger entries.")
    if specialists and any(
        item.human_review_status
        not in {
            SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
            SpecialistReviewStatus.EDITED,
            SpecialistReviewStatus.REJECTED,
        }
        for item in specialists.agent_outputs
    ):
        checkpoints.append("Review eligible specialist proposals and disagreements.")
    checkpoints.append("Review every draft report section before any external use.")
    return checkpoints


def _run_critics(
    *,
    case_id: str,
    claims: list[SynthesisClaim],
    excluded_claims: list[SynthesisClaim],
    sections: list[DraftReportSection],
    result_evidence_workspace: ResultEvidenceWorkspaceResult | None,
    specialist_agent_workspace: SpecialistAgentWorkspaceResult | None,
) -> tuple[list[CriticRun], list[CriticFinding]]:
    findings: list[CriticFinding] = []

    def finding(
        critic: CriticType,
        severity: CriticSeverity,
        code: str,
        message: str,
        target_type: str,
        target_id: str,
        *,
        source_ids: Iterable[str] = (),
        correction: str | None = None,
    ) -> None:
        payload = {
            "critic": critic.value,
            "code": code,
            "target_type": target_type,
            "target_id": target_id,
            "source_ids": sorted(set(source_ids)),
        }
        findings.append(
            CriticFinding(
                critic_finding_id=_stable_id("CRITIC-FINDING", payload),
                critic_type=critic,
                severity=severity,
                code=code,
                message=message,
                target_type=target_type,  # type: ignore[arg-type]
                target_id=target_id,
                source_ids=sorted(set(source_ids)),
                proposed_correction=correction,
            )
        )

    for claim in claims:
        if claim.eligible_for_report and not (
            claim.source_fact_paths
            or claim.source_evidence_ids
            or claim.source_specialist_output_ids
            or claim.source_candidate_criterion_ids
            or claim.source_human_decision_ids
        ):
            finding(
                CriticType.CITATION_SUPPORT,
                CriticSeverity.BLOCKING,
                "CITATION-001",
                "An eligible claim has no controlled source link.",
                "synthesis_claim",
                claim.claim_id,
                correction="Add a controlled source link or exclude the claim from report drafting.",
            )
        if claim.support_status in {
            ClaimSupportStatus.CONFLICTING,
            ClaimSupportStatus.CONTRADICTED,
        }:
            finding(
                CriticType.SCIENTIFIC_CONSISTENCY,
                CriticSeverity.WARNING,
                "SCIENCE-001",
                "The claim carries conflicting or contradicting support and must remain qualified.",
                "synthesis_claim",
                claim.claim_id,
                source_ids=claim.source_evidence_ids,
                correction="Preserve conflict language and require explicit human resolution.",
            )
    for claim in excluded_claims:
        finding(
            CriticType.CITATION_SUPPORT,
            (
                CriticSeverity.BLOCKING
                if claim.support_status == ClaimSupportStatus.UNSUPPORTED
                else CriticSeverity.WARNING
            ),
            (
                "CITATION-UNSUPPORTED"
                if claim.support_status == ClaimSupportStatus.UNSUPPORTED
                else "CITATION-PROPOSAL"
            ),
            "A user-supplied proposed claim was excluded from factual report conclusions.",
            "synthesis_claim",
            claim.claim_id,
            source_ids=claim.source_evidence_ids,
            correction="Verify the claim against controlled artifacts and add it only through human-reviewed structured evidence.",
        )
    if result_evidence_workspace:
        for entry in result_evidence_workspace.ledger_entries:
            if entry.conflict_detected:
                finding(
                    CriticType.EVIDENCE_CONFLICT,
                    CriticSeverity.WARNING,
                    "CONFLICT-001",
                    "A reviewed evidence-ledger conflict remains visible and unresolved.",
                    "evidence_conflict",
                    entry.conflict_group_id or entry.ledger_entry_id,
                    source_ids=(entry.ledger_entry_id,),
                    correction="Retain both positions and request human adjudication.",
                )
    if specialist_agent_workspace:
        for group in specialist_agent_workspace.disagreement_groups:
            finding(
                CriticType.EVIDENCE_CONFLICT,
                CriticSeverity.WARNING,
                "CONFLICT-002",
                "A specialist disagreement remains unresolved; no majority decision was applied.",
                "evidence_conflict",
                group.disagreement_group_id,
                source_ids=group.supporting_source_ids,
                correction="Preserve the disagreement for human review.",
            )
    for target_type, target_id, text in [
        *[
            ("synthesis_claim", item.claim_id, item.statement)
            for item in claims + excluded_claims
        ],
        *[
            ("report_section", item.section_id, item.narrative)
            for item in sections
        ],
    ]:
        matches = _forbidden_matches(text)
        if matches:
            finding(
                CriticType.SAFETY_LANGUAGE,
                CriticSeverity.BLOCKING,
                "SAFETY-001",
                f"Potentially prohibited clinical-conclusion language detected: {', '.join(matches)}.",
                target_type,
                target_id,
                correction="Rewrite as bounded source attribution with uncertainty and human-review language.",
            )
        if _contains_direct_identifier(text):
            finding(
                CriticType.PRIVACY,
                CriticSeverity.BLOCKING,
                "PRIVACY-001",
                "Potential direct identifier pattern detected; the value is not repeated here.",
                target_type,
                target_id,
                correction="Remove the identifier and use only pseudonymous structured records.",
            )
    for claim in claims:
        provenance_complete = bool(
            claim.source_fact_paths
            or claim.source_evidence_ids
            or claim.source_specialist_output_ids
            or claim.source_candidate_criterion_ids
            or claim.source_human_decision_ids
        )
        if not provenance_complete:
            finding(
                CriticType.PROVENANCE,
                CriticSeverity.BLOCKING,
                "PROVENANCE-001",
                "Claim provenance is incomplete.",
                "synthesis_claim",
                claim.claim_id,
                correction="Link the claim to an authoritative structured artifact.",
            )
    if not any(item.critic_type == CriticType.PRIVACY for item in findings):
        finding(
            CriticType.PRIVACY,
            CriticSeverity.INFORMATION,
            "PRIVACY-PASS",
            "No direct-identifier pattern was detected in generated synthesis or report text.",
            "workspace",
            case_id,
        )
    if not any(item.critic_type == CriticType.SAFETY_LANGUAGE for item in findings):
        finding(
            CriticType.SAFETY_LANGUAGE,
            CriticSeverity.INFORMATION,
            "SAFETY-PASS",
            "No prohibited autonomous clinical-conclusion language was detected.",
            "workspace",
            case_id,
        )
    if not any(item.critic_type == CriticType.PROVENANCE for item in findings):
        finding(
            CriticType.PROVENANCE,
            CriticSeverity.INFORMATION,
            "PROVENANCE-PASS",
            "Generated factual claims retain controlled source links.",
            "workspace",
            case_id,
        )
    findings.sort(key=lambda item: item.critic_finding_id)
    runs = []
    for critic_type in CriticType:
        ids = [
            item.critic_finding_id
            for item in findings
            if item.critic_type == critic_type
        ]
        runs.append(
            CriticRun(
                critic_run_id=_stable_id(
                    "CRITIC-RUN",
                    {
                        "case_id": case_id,
                        "critic_type": critic_type.value,
                        "suite_version": CRITIC_SUITE_VERSION,
                    },
                ),
                critic_type=critic_type,
                finding_ids=ids,
            )
        )
    return runs, findings


def _apply_report_review_actions(
    sections: list[DraftReportSection],
    actions: list[ReportHumanReviewAction],
    *,
    claims_by_id: dict[str, SynthesisClaim],
    all_claim_ids: set[str],
) -> tuple[
    list[DraftReportSection],
    list[ReportHumanReviewAction],
    list[ReportReviewActionResult],
]:
    by_id = {item.section_id: item for item in sections}
    applied: list[ReportHumanReviewAction] = []
    results: list[ReportReviewActionResult] = []
    for action in sorted(actions, key=lambda item: (item.timestamp, item.action_id)):
        section = by_id.get(action.target_id)
        if section is None:
            results.append(
                _rejected_action(
                    action,
                    (
                        ReportReviewRejectionReason.TARGET_TYPE_MISMATCH
                        if action.target_id in all_claim_ids
                        else ReportReviewRejectionReason.TARGET_NOT_FOUND
                    ),
                    "The authoritative report section target was not found.",
                    None,
                )
            )
            continue
        authoritative_before = _section_snapshot(section)
        if action.before_value is None:
            results.append(
                _rejected_action(
                    action,
                    ReportReviewRejectionReason.BEFORE_VALUE_REQUIRED,
                    "A complete before-state snapshot is required.",
                    authoritative_before,
                )
            )
            continue
        if _canonical_json(action.before_value) != _canonical_json(
            authoritative_before
        ):
            results.append(
                _rejected_action(
                    action,
                    ReportReviewRejectionReason.BEFORE_VALUE_MISMATCH,
                    "The before-state is stale or incomplete.",
                    authoritative_before,
                )
            )
            continue
        expected_status = {
            ReportReviewActionType.ACCEPT: ReportHumanReviewStatus.ACCEPTED,
            ReportReviewActionType.REJECT: ReportHumanReviewStatus.REJECTED,
            ReportReviewActionType.REQUEST_MORE_INFORMATION: (
                ReportHumanReviewStatus.MORE_INFORMATION_REQUESTED
            ),
        }.get(action.action)
        if action.action == ReportReviewActionType.EDIT:
            if not isinstance(action.after_value, dict):
                results.append(
                    _rejected_action(
                        action,
                        ReportReviewRejectionReason.AFTER_VALUE_REQUIRED,
                        "Edit actions require a complete typed after-state.",
                        authoritative_before,
                    )
                )
                continue
            try:
                updated = DraftReportSection.model_validate(action.after_value)
            except ValidationError:
                results.append(
                    _rejected_action(
                        action,
                        ReportReviewRejectionReason.INVALID_EDIT_PAYLOAD,
                        "The edited report section failed typed validation.",
                        authoritative_before,
                    )
                )
                continue
            if (
                updated.section_id != section.section_id
                or updated.section_type != section.section_type
                or updated.narrative_status != "draft_not_clinically_approved"
                or updated.clinically_approved
                or updated.human_review_status != ReportHumanReviewStatus.EDITED
            ):
                results.append(
                    _rejected_action(
                        action,
                        ReportReviewRejectionReason.INVALID_EDIT_PAYLOAD,
                        "Immutable identity and draft-safety fields cannot be changed.",
                        authoritative_before,
                    )
                )
                continue
            if not set(updated.claim_ids) <= {
                claim_id
                for claim_id, claim in claims_by_id.items()
                if claim.eligible_for_report
            }:
                results.append(
                    _rejected_action(
                        action,
                        ReportReviewRejectionReason.UNSUPPORTED_CLAIM_REFERENCE,
                        "The edit references a claim that is not eligible for report use.",
                        authoritative_before,
                    )
                )
                continue
            reviewable_edit_text = "\n".join(
                value
                for value in (updated.title, updated.narrative, updated.reviewer_notes)
                if value
            )
            if _forbidden_matches(reviewable_edit_text) or _contains_direct_identifier(
                reviewable_edit_text
            ):
                results.append(
                    _rejected_action(
                        action,
                        ReportReviewRejectionReason.FORBIDDEN_EDIT,
                        "The edited narrative contains prohibited safety or privacy language.",
                        authoritative_before,
                    )
                )
                continue
            if section.section_type == "critic_findings":
                expected_citations = section.citation_ids
                expected_narrative = section.narrative
            else:
                expected_citations = sorted(
                    {
                        reference
                        for claim_id in updated.claim_ids
                        for reference in (
                            claims_by_id[claim_id].source_evidence_ids
                            or claims_by_id[claim_id].source_fact_paths
                        )
                    }
                )
                expected_narrative = _section_narrative(
                    updated.title, updated.claim_ids, claims_by_id
                )
            if (
                updated.citation_ids != expected_citations
                or updated.narrative != expected_narrative
            ):
                results.append(
                    _rejected_action(
                        action,
                        ReportReviewRejectionReason.INVALID_EDIT_PAYLOAD,
                        (
                            "Edited narrative and citations must be reconstructed "
                            "only from eligible controlled claims."
                        ),
                        authoritative_before,
                    )
                )
                continue
        else:
            if expected_status is None:
                results.append(
                    _rejected_action(
                        action,
                        ReportReviewRejectionReason.INVALID_TRANSITION,
                        "Unsupported report review transition.",
                        authoritative_before,
                    )
                )
                continue
            updated = section.model_copy(
                update={
                    "human_review_status": expected_status,
                    "reviewer_notes": action.notes,
                }
            )
            expected_after = _section_snapshot(updated)
            if action.after_value is None:
                results.append(
                    _rejected_action(
                        action,
                        ReportReviewRejectionReason.AFTER_VALUE_REQUIRED,
                        "A complete expected after-state snapshot is required.",
                        authoritative_before,
                    )
                )
                continue
            if _canonical_json(action.after_value) != _canonical_json(
                expected_after
            ):
                results.append(
                    _rejected_action(
                        action,
                        ReportReviewRejectionReason.AFTER_VALUE_MISMATCH,
                        "The expected after-state is incomplete or invalid.",
                        authoritative_before,
                    )
                )
                continue
        by_id[section.section_id] = updated
        applied.append(action)
        results.append(
            ReportReviewActionResult(
                action_id=action.action_id,
                action=action.action,
                target_type=action.target_type,
                target_id=action.target_id,
                result_status=ReportReviewActionResultStatus.APPLIED,
                message="The bounded report review action was applied.",
                authoritative_before=authoritative_before,
                validated_after=_section_snapshot(updated),
                reviewer_role=action.reviewer_role,
                reviewer_id=action.reviewer_id,
                timestamp=action.timestamp,
            )
        )
    return (
        [by_id[item.section_id] for item in sections],
        applied,
        results,
    )


def _rejected_action(
    action: ReportHumanReviewAction,
    reason: ReportReviewRejectionReason,
    message: str,
    authoritative_before: dict[str, Any] | None,
) -> ReportReviewActionResult:
    return ReportReviewActionResult(
        action_id=action.action_id,
        action=action.action,
        target_type=action.target_type,
        target_id=action.target_id,
        result_status=ReportReviewActionResultStatus.REJECTED,
        rejection_reason=reason,
        message=message,
        authoritative_before=authoritative_before,
        validated_after=None,
        reviewer_role=action.reviewer_role,
        reviewer_id=action.reviewer_id,
        timestamp=action.timestamp,
    )


def _section_snapshot(section: DraftReportSection) -> dict[str, Any]:
    return section.model_dump(mode="json")


def _drill_down(claim: SynthesisClaim) -> ClaimEvidenceDrillDown:
    provenance_complete = bool(
        claim.source_fact_paths
        or claim.source_evidence_ids
        or claim.source_specialist_output_ids
        or claim.source_candidate_criterion_ids
        or claim.source_human_decision_ids
    )
    return ClaimEvidenceDrillDown(
        claim_id=claim.claim_id,
        source_fact_paths=claim.source_fact_paths,
        evidence_ledger_entry_ids=claim.source_evidence_ids,
        specialist_output_ids=claim.source_specialist_output_ids,
        candidate_criterion_ids=claim.source_candidate_criterion_ids,
        human_decision_ids=claim.source_human_decision_ids,
        support_status=claim.support_status,
        conflict_visible=claim.support_status
        in {
            ClaimSupportStatus.CONFLICTING,
            ClaimSupportStatus.CONTRADICTED,
        },
        provenance_complete=provenance_complete,
    )


def _pending_human_decision_ids(
    sections: list[DraftReportSection],
    *,
    result_evidence_workspace: ResultEvidenceWorkspaceResult | None,
    specialist_agent_workspace: SpecialistAgentWorkspaceResult | None,
) -> list[str]:
    pending = {
        item.section_id
        for item in sections
        if item.human_review_status
        in {
            ReportHumanReviewStatus.PENDING,
            ReportHumanReviewStatus.MORE_INFORMATION_REQUESTED,
        }
    }
    if result_evidence_workspace:
        pending.update(
            item.ledger_entry_id
            for item in result_evidence_workspace.ledger_entries
            if item.human_review_status
            not in {
                HumanReviewStatus.ACCEPTED_INTO_WORKSPACE,
                HumanReviewStatus.EDITED,
                HumanReviewStatus.REJECTED,
            }
        )
    if specialist_agent_workspace:
        pending.update(
            item.agent_output_id
            for item in specialist_agent_workspace.agent_outputs
            if item.human_review_status
            not in {
                SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
                SpecialistReviewStatus.EDITED,
                SpecialistReviewStatus.REJECTED,
            }
        )
        pending.update(
            item.candidate_criterion_id
            for item in specialist_agent_workspace.candidate_criteria
            if item.human_review_status
            in {
                SpecialistReviewStatus.PENDING,
                SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
            }
        )
    return sorted(pending)


def _source_versions(**artifacts: Any) -> dict[str, str]:
    versions = {}
    for name, value in artifacts.items():
        if value is None:
            continue
        for attribute in (
            "schema_version",
            "algorithm_version",
            "registry_version",
            "ledger_version",
            "controller_version",
        ):
            version = getattr(value, attribute, None)
            if version:
                versions[f"{name}.{attribute}"] = str(version)
    versions.update(
        {
            "jarvis_briefing": JARVIS_BRIEFING_VERSION,
            "scientific_synthesis": SYNTHESIS_VERSION,
            "critic_suite": CRITIC_SUITE_VERSION,
            "report_studio": REPORT_STUDIO_VERSION,
        }
    )
    return dict(sorted(versions.items()))


def _source_hashes(**artifacts: Any) -> dict[str, str]:
    return {
        name: _hash_payload(value.model_dump(mode="json"))
        for name, value in sorted(artifacts.items())
        if value is not None
    }


def _forbidden_matches(text: str) -> list[str]:
    return sorted(
        label
        for label, pattern in _FORBIDDEN_CONCLUSION_PATTERNS.items()
        if pattern.search(text)
    )


def _contains_direct_identifier(text: str) -> bool:
    return bool(
        _EMAIL_PATTERN.search(text)
        or _PHONE_PATTERN.search(text)
        or _DIRECT_IDENTIFIER_PATTERN.search(text)
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_hash_payload(value)[:20]}"
