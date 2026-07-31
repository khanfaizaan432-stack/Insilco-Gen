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
    EVIDENCE_ELIGIBILITY_RULE_VERSION,
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
    EligibilityDecisionKind,
    EligibilityReasonCode,
    EvidenceEligibilityDecision,
    EvidenceLifecycleState,
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
    ("missing_information", "Missing-information plan"),
    ("pretest_readiness", "Pre-test readiness"),
    ("test_strategy", "Staged test-strategy record"),
    ("result_normalization", "Supplied result and normalization record"),
    ("evidence_ledger", "Reviewed evidence ledger"),
    ("specialist_outputs", "Eligible reviewed specialist outputs"),
    ("candidate_acmg", "Candidate ACMG evidence"),
    ("disagreements", "Disagreements"),
    ("limitations", "Limitations and evidence lifecycle history"),
    ("jarvis_briefing", "JARVIS bounded case briefing"),
    ("scientific_synthesis", "Scientific synthesis"),
    ("critic_findings", "Critic findings"),
    ("cited_draft_narrative", "Cited draft narrative"),
    ("human_review_history", "Human-review status and history"),
)

_FORBIDDEN_CONCLUSION_PATTERNS = {
    "diagnosis": re.compile(
        r"(?i)\b(?:we diagnose|is diagnosed with|diagnosis is|diagnostic of)\b"
    ),
    "treatment": re.compile(
        r"(?i)\b(?:we recommend treatment|recommend treatment|treatment recommendation|"
        r"start medication|prescribe[ds]?|treatment is indicated)\b"
    ),
    "test_ordering": re.compile(
        r"(?i)\b(?:we order|test has been ordered|order the test|order this test)\b"
    ),
    "causal_certainty": re.compile(
        r"(?i)\b(?:causative(?: variant)?|proves? causality|confirms?|confirmed|"
        r"rules? out|ruled out)\b"
    ),
    "final_classification": re.compile(
        r"(?i)\b(?:final (?:acmg(?:/amp)? )?classification|"
        r"(?:is|are|was|were|deemed|classified as)\s+(?:pathogenic|benign)|"
        r"criterion (?:is )?satisfied)\b"
    ),
    "pathogenicity_certainty": re.compile(r"(?i)\b(?:pathogenic|benign)\b"),
    "clinical_approval": re.compile(r"(?i)\b(?:clinically approved report|clinical sign[- ]out complete)\b"),
}
_EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")
_DIRECT_IDENTIFIER_PATTERN = re.compile(
    r"(?i)\b(?:medical record number|hospital number|patient name|date of birth|"
    r"family member name|relative name)\s*[:=]"
)
_PROHIBITED_PRIVACY_INFERENCE_PATTERN = re.compile(
    r"(?i)\b(?:paternity|non[- ]paternity|hidden biological relationship|"
    r"sample[- ]swap(?:ped)?|caste|tribe|religion|race|ethnicity|ancestry|"
    r"community|genetic purity|racial purity|genetic superiority|racial superiority)\b"
)


def _evidence_lifecycle_decisions(
    workspace: ResultEvidenceWorkspaceResult | None,
) -> tuple[list[EvidenceEligibilityDecision], dict[str, EvidenceEligibilityDecision]]:
    decisions: list[EvidenceEligibilityDecision] = []
    for entry in workspace.ledger_entries if workspace else []:
        marker_text = " ".join(
            [
                entry.applicability_status or "",
                str(entry.structured_observation.get("lifecycle_state", "")),
                str(entry.structured_observation.get("status", "")),
            ]
        ).lower()
        successor_id = entry.superseded_by
        if entry.human_review_status == HumanReviewStatus.REJECTED:
            kind = EligibilityDecisionKind.EXCLUDED
            reason = EligibilityReasonCode.REJECTED_RECORD
            lifecycle = EvidenceLifecycleState.EXCLUDED
        elif entry.human_review_status not in {
            HumanReviewStatus.ACCEPTED_INTO_WORKSPACE,
            HumanReviewStatus.EDITED,
        }:
            kind = EligibilityDecisionKind.EXCLUDED
            reason = EligibilityReasonCode.INELIGIBLE_REVIEW_STATUS
            lifecycle = EvidenceLifecycleState.EXCLUDED
        elif "invalid" in marker_text:
            kind = EligibilityDecisionKind.EXCLUDED
            reason = EligibilityReasonCode.INVALID_RECORD
            lifecycle = EvidenceLifecycleState.INVALID
        elif "retract" in marker_text:
            kind = EligibilityDecisionKind.QUARANTINED
            reason = EligibilityReasonCode.RETRACTED_RECORD
            lifecycle = EvidenceLifecycleState.RETRACTED
        elif entry.superseded_by or "supersed" in marker_text:
            kind = EligibilityDecisionKind.QUARANTINED
            reason = EligibilityReasonCode.SUPERSEDED_RECORD
            lifecycle = EvidenceLifecycleState.SUPERSEDED
        elif "correct" in marker_text:
            kind = EligibilityDecisionKind.CONTEXT_ONLY
            reason = EligibilityReasonCode.CORRECTED_RECORD_CONTEXT_ONLY
            lifecycle = EvidenceLifecycleState.CORRECTED
        elif "stale" in marker_text:
            kind = EligibilityDecisionKind.CONTEXT_ONLY
            reason = EligibilityReasonCode.STALE_RECORD_CONTEXT_ONLY
            lifecycle = EvidenceLifecycleState.STALE
        elif entry.withdrawn_or_updated or "withdraw" in marker_text:
            kind = EligibilityDecisionKind.QUARANTINED
            reason = EligibilityReasonCode.WITHDRAWN_RECORD
            lifecycle = EvidenceLifecycleState.WITHDRAWN
        elif "context_only" in marker_text or "context only" in marker_text:
            kind = EligibilityDecisionKind.CONTEXT_ONLY
            reason = EligibilityReasonCode.STALE_RECORD_CONTEXT_ONLY
            lifecycle = EvidenceLifecycleState.CONTEXT_ONLY
        else:
            kind = EligibilityDecisionKind.ELIGIBLE
            reason = EligibilityReasonCode.ELIGIBLE_REVIEWED_RECORD
            lifecycle = EvidenceLifecycleState.ACTIVE
        payload = {
            "artifact_type": "evidence_ledger_entry",
            "artifact_id": entry.ledger_entry_id,
            "decision": kind.value,
            "reason": reason.value,
            "lifecycle": lifecycle.value,
            "successor": successor_id,
            "rule": EVIDENCE_ELIGIBILITY_RULE_VERSION,
        }
        decisions.append(
            EvidenceEligibilityDecision(
                decision_id=_stable_id("ELIGIBILITY", payload),
                input_artifact_type="evidence_ledger_entry",
                input_artifact_id=entry.ledger_entry_id,
                decision=kind,
                reason_code=reason,
                lifecycle_state=lifecycle,
                linked_successor_id=successor_id,
                source_fact_paths=[
                    f"result_evidence_workspace.ledger_entries.{entry.ledger_entry_id}"
                ],
            )
        )
    decisions.sort(key=lambda item: (item.input_artifact_type, item.input_artifact_id))
    return decisions, {item.input_artifact_id: item for item in decisions}


def _evidence_role(entry: Any) -> str:
    stance = str(entry.structured_observation.get("stance", "")).lower()
    if stance in {"supportive", "supporting", "supports"}:
        return "supporting"
    if stance in {"contradictory", "contradicting", "opposing", "refuting"}:
        return "contradicting"
    return "unresolved"


def _controlled_artifact_decisions(
    claims: list[SynthesisClaim],
) -> list[EvidenceEligibilityDecision]:
    records: set[tuple[str, str, EligibilityReasonCode]] = set()
    for claim in claims:
        records.update(
            ("case_fact_path", item, EligibilityReasonCode.ELIGIBLE_CONTROLLED_FACT)
            for item in claim.source_fact_paths
        )
        records.update(
            (
                "external_acmg_assessment",
                item.rsplit(".", 1)[-1],
                EligibilityReasonCode.EXTERNAL_ASSESSMENT_ATTRIBUTION_REQUIRED,
            )
            for item in claim.source_fact_paths
            if ".external_acmg_assessments." in item
        )
        records.update(
            (
                "specialist_output",
                item,
                EligibilityReasonCode.ELIGIBLE_REVIEWED_RECORD,
            )
            for item in claim.source_specialist_output_ids
        )
        records.update(
            (
                "candidate_acmg_record",
                item,
                EligibilityReasonCode.ELIGIBLE_BOUNDED_CANDIDATE_RECORD,
            )
            for item in claim.source_candidate_criterion_ids
        )
        records.update(
            (
                "human_decision",
                item,
                EligibilityReasonCode.ELIGIBLE_HUMAN_DECISION,
            )
            for item in claim.source_human_decision_ids
        )
    decisions = []
    for artifact_type, artifact_id, reason in sorted(
        records, key=lambda item: (item[0], item[1])
    ):
        payload = {
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "reason": reason.value,
            "rule": EVIDENCE_ELIGIBILITY_RULE_VERSION,
        }
        decisions.append(
            EvidenceEligibilityDecision(
                decision_id=_stable_id("ELIGIBILITY", payload),
                input_artifact_type=artifact_type,
                input_artifact_id=artifact_id,
                decision=EligibilityDecisionKind.ELIGIBLE,
                reason_code=reason,
                lifecycle_state=EvidenceLifecycleState.ACTIVE,
                source_fact_paths=(
                    [artifact_id] if artifact_type == "case_fact_path" else []
                ),
            )
        )
    return decisions


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

    lifecycle_decisions, lifecycle_by_id = _evidence_lifecycle_decisions(
        result_evidence_workspace
    )
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
        eligibility_by_evidence_id=lifecycle_by_id,
    )
    excluded_claims, proposal_decisions = _assess_proposed_claims(
        request.proposed_claims,
        available_fact_paths=available_fact_paths,
        result_evidence_workspace=result_evidence_workspace,
        specialist_agent_workspace=specialist_agent_workspace,
        eligibility_by_evidence_id=lifecycle_by_id,
    )
    controlled_decisions = _controlled_artifact_decisions(claims)
    controlled_by_key = {
        (item.input_artifact_type, item.input_artifact_id): item
        for item in controlled_decisions
    }
    claims = [
        item.model_copy(
            update={
                "eligibility_decision_ids": sorted(
                    {
                        *item.eligibility_decision_ids,
                        *[
                            controlled_by_key[key].decision_id
                            for key in (
                                *[
                                    ("case_fact_path", value)
                                    for value in item.source_fact_paths
                                ],
                                *[
                                    ("specialist_output", value)
                                    for value in item.source_specialist_output_ids
                                ],
                                *[
                                    ("candidate_acmg_record", value)
                                    for value in item.source_candidate_criterion_ids
                                ],
                                *[
                                    ("human_decision", value)
                                    for value in item.source_human_decision_ids
                                ],
                                *[
                                    (
                                        "external_acmg_assessment",
                                        value.rsplit(".", 1)[-1],
                                    )
                                    for value in item.source_fact_paths
                                    if ".external_acmg_assessments." in value
                                ],
                            )
                            if key in controlled_by_key
                        ],
                    }
                )
            }
        )
        for item in claims
    ]
    eligibility_decisions = sorted(
        lifecycle_decisions
        + controlled_decisions
        + proposal_decisions,
        key=lambda item: (item.input_artifact_type, item.input_artifact_id),
    )
    claims_by_id = {item.claim_id: item for item in claims}
    briefing = _build_briefing(
        case,
        intake=intake,
        pretest_assessment=pretest_assessment,
        test_strategy_workspace=test_strategy_workspace,
        result_evidence_workspace=result_evidence_workspace,
        specialist_agent_workspace=specialist_agent_workspace,
        eligibility_by_evidence_id=lifecycle_by_id,
    )
    sections = _build_report_sections(claims_by_id, section_claim_ids)
    sections = _attach_briefing_section(sections, briefing)
    critic_runs, critic_findings = _run_critics(
        case_id=case.pseudonymous_case_id,
        claims=claims,
        excluded_claims=excluded_claims,
        sections=sections,
        result_evidence_workspace=result_evidence_workspace,
        specialist_agent_workspace=specialist_agent_workspace,
        eligibility_decisions=eligibility_decisions,
    )
    sections = _attach_critic_findings_section(sections, critic_findings)
    sections, applied_actions, action_results = _apply_report_review_actions(
        sections,
        request.review_actions,
        claims_by_id=claims_by_id,
        all_claim_ids={item.claim_id for item in claims},
    )
    sections = _attach_review_history_section(sections, action_results)
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
        "eligibility_decisions": [
            item.model_dump(mode="json") for item in eligibility_decisions
        ],
        "eligibility_rule_version": EVIDENCE_ELIGIBILITY_RULE_VERSION,
        "generation_mode": "deterministic",
        "deterministic_fallback_used": True,
        "provider_context": {
            "provider": "deterministic",
            "model": "bounded-template-synthesis",
            "external_provider_called": False,
        },
        "budget_context": {
            "external_call_budget": 0,
            "external_token_budget": 0,
            "external_cost_budget": 0,
        },
    }
    reproducibility = JarvisReportReproducibility(
        source_artifact_versions=source_versions,
        source_artifact_hashes=source_hashes,
        eligible_input_ids=[
            f"{item.input_artifact_type}:{item.input_artifact_id}"
            for item in eligibility_decisions
            if item.decision == EligibilityDecisionKind.ELIGIBLE
        ],
        context_only_input_ids=[
            f"{item.input_artifact_type}:{item.input_artifact_id}"
            for item in eligibility_decisions
            if item.decision == EligibilityDecisionKind.CONTEXT_ONLY
        ],
        excluded_input_ids=[
            f"{item.input_artifact_type}:{item.input_artifact_id}"
            for item in eligibility_decisions
            if item.decision
            in {EligibilityDecisionKind.QUARANTINED, EligibilityDecisionKind.EXCLUDED}
        ],
        eligibility_decisions=eligibility_decisions,
        exclusion_reason_codes=sorted(
            {
                item.reason_code
                for item in eligibility_decisions
                if item.decision != EligibilityDecisionKind.ELIGIBLE
            },
            key=lambda item: item.value,
        ),
        evidence_role_mappings={
            item.claim_id: {
                "supporting": item.supporting_evidence_ids,
                "contradicting": item.contradicting_evidence_ids,
                "unresolved": item.unresolved_evidence_ids,
            }
            for item in claims
        },
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
        provider_context={
            "provider": "deterministic",
            "model": "bounded-template-synthesis",
            "external_provider_called": False,
        },
        budget_context={
            "external_call_budget": 0,
            "external_token_budget": 0,
            "external_cost_budget": 0,
        },
        workspace_hash=_hash_payload(reproducibility_payload),
    )
    return JarvisSynthesisReportWorkspaceResult(
        pseudonymous_case_id=case.pseudonymous_case_id,
        briefing=briefing,
        synthesis_claims=claims,
        excluded_proposed_claims=excluded_claims,
        eligibility_decisions=eligibility_decisions,
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
    eligibility_by_evidence_id: dict[str, EvidenceEligibilityDecision],
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
        supporting_evidence_ids: Iterable[str] = (),
        contradicting_evidence_ids: Iterable[str] = (),
        unresolved_evidence_ids: Iterable[str] = (),
        output_ids: Iterable[str] = (),
        candidate_ids: Iterable[str] = (),
        decision_ids: Iterable[str] = (),
        uncertainty: str,
        eligible: bool = True,
    ) -> None:
        source_fact_paths = sorted(set(fact_paths))
        legacy_evidence_ids = sorted(set(evidence_ids))
        supporting_ids = sorted(
            set(supporting_evidence_ids)
            | (
                set(legacy_evidence_ids)
                if support == ClaimSupportStatus.SUPPORTED
                else set()
            )
        )
        contradicting_ids = sorted(
            set(contradicting_evidence_ids)
            | (
                set(legacy_evidence_ids)
                if support == ClaimSupportStatus.CONTRADICTED
                else set()
            )
        )
        unresolved_ids = sorted(
            set(unresolved_evidence_ids)
            | (
                set(legacy_evidence_ids)
                if support
                in {ClaimSupportStatus.UNRESOLVED, ClaimSupportStatus.CONFLICTING}
                else set()
            )
        )
        all_evidence_ids = sorted(
            set(supporting_ids) | set(contradicting_ids) | set(unresolved_ids)
        )
        evidence_decisions = [
            eligibility_by_evidence_id[item]
            for item in all_evidence_ids
            if item in eligibility_by_evidence_id
        ]
        disallowed_decisions = [
            item
            for item in evidence_decisions
            if item.decision != EligibilityDecisionKind.ELIGIBLE
        ]
        has_unknown_evidence = any(
            item not in eligibility_by_evidence_id for item in all_evidence_ids
        )
        factual_eligible = (
            eligible
            and support != ClaimSupportStatus.UNSUPPORTED
            and not disallowed_decisions
            and not has_unknown_evidence
        )
        source_output_ids = sorted(set(output_ids))
        source_candidate_ids = sorted(set(candidate_ids))
        source_decision_ids = sorted(set(decision_ids))
        available_fact_paths.update(source_fact_paths)
        payload = {
            "section": section,
            "statement": statement,
            "origin": origin.value,
            "fact_paths": source_fact_paths,
            "supporting_evidence_ids": supporting_ids,
            "contradicting_evidence_ids": contradicting_ids,
            "unresolved_evidence_ids": unresolved_ids,
            "output_ids": source_output_ids,
            "candidate_ids": source_candidate_ids,
            "decision_ids": source_decision_ids,
        }
        claim = SynthesisClaim(
            claim_id=_stable_id("SYNTH-CLAIM", payload),
            statement=statement,
            claim_category=section,
            origin_category=origin,
            support_status=support,
            uncertainty_language=uncertainty,
            source_fact_paths=source_fact_paths,
            supporting_evidence_ids=supporting_ids,
            contradicting_evidence_ids=contradicting_ids,
            unresolved_evidence_ids=unresolved_ids,
            source_specialist_output_ids=source_output_ids,
            source_candidate_criterion_ids=source_candidate_ids,
            source_human_decision_ids=source_decision_ids,
            eligibility_decision_ids=sorted(
                item.decision_id for item in evidence_decisions
            ),
            exclusion_reason_codes=sorted(
                {item.reason_code for item in disallowed_decisions},
                key=lambda item: item.value,
            ),
            report_use=(
                "factual"
                if factual_eligible
                else "context_only"
                if all_evidence_ids and (disallowed_decisions or has_unknown_evidence)
                else "excluded"
            ),
            provenance_status=(
                "complete"
                if (
                    source_fact_paths
                    or all_evidence_ids
                    or source_output_ids
                    or source_candidate_ids
                    or source_decision_ids
                )
                else "incomplete"
            ),
            citation_support_status=(
                "complete"
                if factual_eligible
                else "excluded"
                if not eligible or support == ClaimSupportStatus.UNSUPPORTED
                else "incomplete"
            ),
            eligible_for_report=factual_eligible,
        )
        if claim.claim_id not in {item.claim_id for item in claims}:
            claims.append(claim)
            section_claim_ids[
                "limitations" if claim.report_use == "context_only" else section
            ].append(claim.claim_id)

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
            "pretest_readiness",
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
                    "missing_information",
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
            decision = eligibility_by_evidence_id[entry.ledger_entry_id]
            role = _evidence_role(entry)
            support = {
                "supporting": ClaimSupportStatus.SUPPORTED,
                "contradicting": ClaimSupportStatus.CONTRADICTED,
                "unresolved": ClaimSupportStatus.UNRESOLVED,
            }[role]
            if entry.conflict_detected:
                support = ClaimSupportStatus.CONFLICTING
            evidence_kwargs = {
                f"{role}_evidence_ids": (entry.ledger_entry_id,),
            }
            add(
                (
                    "evidence_ledger"
                    if decision.decision == EligibilityDecisionKind.ELIGIBLE
                    else "limitations"
                ),
                (
                    f"Reviewed external source '{entry.source_title}' reports: "
                    f"{entry.source_statement}"
                    + (
                        ""
                        if decision.decision == EligibilityDecisionKind.ELIGIBLE
                        else (
                            f" [lifecycle:{decision.lifecycle_state.value}; "
                            f"eligibility:{decision.decision.value}; "
                            f"reason:{decision.reason_code.value}]"
                        )
                    )
                ),
                ClaimOriginCategory.RETRIEVED_SOURCE_CLAIM,
                support,
                **evidence_kwargs,
                uncertainty=(
                    "This is a reviewed source claim attributed to the external source; "
                    "it is not an InSilicoPop classification. "
                    f"Lifecycle handling is {decision.decision.value}."
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
                supporting_evidence_ids=candidate.source_ledger_entry_ids,
                contradicting_evidence_ids=candidate.contradicting_ledger_entry_ids,
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
            "spawn_request": "disagreements",
            "external_acmg_assessment": "candidate_acmg",
        }
        for action in specialist_agent_workspace.applied_review_actions:
            add(
                section_for_target.get(
                    action.target_type, "disagreements"
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
                "disagreements",
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
            "limitations",
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
    eligibility_by_evidence_id: dict[str, EvidenceEligibilityDecision],
) -> tuple[list[SynthesisClaim], list[EvidenceEligibilityDecision]]:
    ledger_ids = {
        item.ledger_entry_id
        for item in (result_evidence_workspace.ledger_entries if result_evidence_workspace else [])
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
    decisions = []
    for proposal in sorted(proposals, key=lambda item: item.proposal_id):
        supporting_ids = sorted(
            set(proposal.supporting_evidence_ids)
            | set(proposal.source_evidence_ids)
        )
        contradicting_ids = sorted(set(proposal.contradicting_evidence_ids))
        unresolved_ids = sorted(set(proposal.unresolved_evidence_ids))
        all_evidence_ids = set(supporting_ids + contradicting_ids + unresolved_ids)
        unknown_evidence = all_evidence_ids - ledger_ids
        ineligible_evidence = {
            item
            for item in all_evidence_ids
            if item in eligibility_by_evidence_id
            and eligibility_by_evidence_id[item].decision
            != EligibilityDecisionKind.ELIGIBLE
        }
        dangling_fact = set(proposal.source_fact_paths) - available_fact_paths
        ineligible_outputs = (
            set(proposal.source_specialist_output_ids) - reviewed_output_ids
        )
        unknown_candidates = set(proposal.source_candidate_criterion_ids) - candidate_ids
        if unknown_evidence:
            reason = EligibilityReasonCode.UNKNOWN_REFERENCE
        elif dangling_fact or unknown_candidates:
            reason = EligibilityReasonCode.DANGLING_REFERENCE
        elif ineligible_evidence:
            reason = EligibilityReasonCode.EXCLUDED_RECORD_REUSE_ATTEMPT
        elif ineligible_outputs:
            reason = EligibilityReasonCode.INELIGIBLE_REVIEW_STATUS
        else:
            reason = EligibilityReasonCode.UNSUPPORTED_CLAIM
        decision_payload = {
            "proposal_id": proposal.proposal_id,
            "reason": reason.value,
            "supporting": supporting_ids,
            "contradicting": contradicting_ids,
            "unresolved": unresolved_ids,
            "fact_paths": sorted(set(proposal.source_fact_paths)),
        }
        decision = EvidenceEligibilityDecision(
            decision_id=_stable_id("ELIGIBILITY", decision_payload),
            input_artifact_type="proposed_synthesis_claim",
            input_artifact_id=proposal.proposal_id,
            decision=EligibilityDecisionKind.EXCLUDED,
            reason_code=reason,
            lifecycle_state=EvidenceLifecycleState.EXCLUDED,
            source_fact_paths=sorted(set(proposal.source_fact_paths)),
        )
        decisions.append(decision)
        assessed.append(
            SynthesisClaim(
                claim_id=_stable_id(
                    "EXCLUDED-CLAIM",
                    proposal.model_dump(mode="json"),
                ),
                statement=proposal.statement,
                claim_category="proposed_claim",
                origin_category=ClaimOriginCategory.SPECIALIST_AGENT_PROPOSAL,
                support_status=ClaimSupportStatus.UNSUPPORTED,
                uncertainty_language=proposal.uncertainty_language,
                source_fact_paths=sorted(set(proposal.source_fact_paths)),
                supporting_evidence_ids=supporting_ids,
                contradicting_evidence_ids=contradicting_ids,
                unresolved_evidence_ids=unresolved_ids,
                source_specialist_output_ids=sorted(
                    set(proposal.source_specialist_output_ids)
                ),
                source_candidate_criterion_ids=sorted(
                    set(proposal.source_candidate_criterion_ids)
                ),
                eligibility_decision_ids=[decision.decision_id],
                exclusion_reason_codes=[reason],
                report_use="excluded",
                citation_support_status="excluded",
                eligible_for_report=False,
            )
        )
    return assessed, decisions


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
        elif section_type in {
            "critic_findings",
            "jarvis_briefing",
            "human_review_history",
        }:
            claim_ids = []
        elif section_type == "limitations":
            claim_ids = sorted(
                {
                    *section_claim_ids.get(section_type, []),
                    *[
                        item.claim_id
                        for item in claims_by_id.values()
                        if item.report_use == "context_only"
                    ],
                }
            )
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
                    claims_by_id[claim_id].supporting_evidence_ids
                    + claims_by_id[claim_id].contradicting_evidence_ids
                    + claims_by_id[claim_id].unresolved_evidence_ids
                    + claims_by_id[claim_id].source_fact_paths
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


def _attach_briefing_section(
    sections: list[DraftReportSection], briefing: JarvisCaseBriefing
) -> list[DraftReportSection]:
    narrative = "\n".join(
        (
            f"{item.statement} [briefing:{item.briefing_item_id}; "
            f"category:{item.category}; human_review:required; "
            "draft:draft_not_clinically_approved]"
        )
        for item in briefing.items
    )
    return [
        section.model_copy(update={"narrative": narrative})
        if section.section_type == "jarvis_briefing"
        else section
        for section in sections
    ]


def _attach_review_history_section(
    sections: list[DraftReportSection],
    results: list[ReportReviewActionResult],
) -> list[DraftReportSection]:
    narrative = (
        "\n".join(
            (
                f"Review action {item.action_id}: {item.result_status.value}; "
                f"action:{item.action.value}; target:{item.target_id}; "
                f"rejection_reason:{item.rejection_reason.value if item.rejection_reason else 'none'}; "
                "draft:draft_not_clinically_approved."
            )
            for item in results
        )
        if results
        else (
            "No report review action has been applied. Human review remains required; "
            "draft:draft_not_clinically_approved."
        )
    )
    return [
        section.model_copy(update={"narrative": narrative})
        if section.section_type == "human_review_history"
        else section
        for section in sections
    ]


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
    lines = []
    for claim_id in claim_ids:
        claim = claims_by_id[claim_id]
        conflict = claim.support_status in {
            ClaimSupportStatus.CONFLICTING,
            ClaimSupportStatus.CONTRADICTED,
        }
        lines.append(
            (
                f"{claim.statement} [claim:{claim_id}; support:{claim.support_status.value}; "
                f"uncertainty:{claim.uncertainty_language}; "
                f"origin:{claim.origin_category.value}; "
                f"supporting:{','.join(claim.supporting_evidence_ids) or 'none'}; "
                f"contradicting:{','.join(claim.contradicting_evidence_ids) or 'none'}; "
                f"unresolved:{','.join(claim.unresolved_evidence_ids) or 'none'}; "
                f"conflict:{str(conflict).lower()}; "
                f"use:{claim.report_use}; "
                f"eligibility:{','.join(claim.eligibility_decision_ids) or 'none'}; "
                f"exclusions:{','.join(item.value for item in claim.exclusion_reason_codes) or 'none'}; "
                f"human_review:{claim.human_review_status.value}; "
                "draft:draft_not_clinically_approved]"
            )
        )
    return "\n".join(lines)


def _build_briefing(
    case: ClinicalCaseIntake,
    *,
    intake: ClinicalCaseIntakeResult,
    pretest_assessment: PreTestAssessmentResult | None,
    test_strategy_workspace: TestStrategyWorkspaceResult | None,
    result_evidence_workspace: ResultEvidenceWorkspaceResult | None,
    specialist_agent_workspace: SpecialistAgentWorkspaceResult | None,
    eligibility_by_evidence_id: dict[str, EvidenceEligibilityDecision],
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
            if eligibility_by_evidence_id[item.ledger_entry_id].decision
            == EligibilityDecisionKind.ELIGIBLE
        ]
        reviewed.sort(key=lambda item: item.ledger_entry_id)
        contextual = [
            item
            for item in result_evidence_workspace.ledger_entries
            if eligibility_by_evidence_id[item.ledger_entry_id].decision
            != EligibilityDecisionKind.ELIGIBLE
        ]
        contextual.sort(key=lambda item: item.ledger_entry_id)
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
        for entry in contextual:
            decision = eligibility_by_evidence_id[entry.ledger_entry_id]
            raw_items.append(
                (
                    "limitation",
                    (
                        f"Evidence {entry.ledger_entry_id} is {decision.decision.value} "
                        f"({decision.reason_code.value}) and is not current factual support."
                    ),
                    decision.source_fact_paths,
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
    eligibility_decisions: list[EvidenceEligibilityDecision],
) -> tuple[list[CriticRun], list[CriticFinding]]:
    findings: list[CriticFinding] = []
    ledger_ids = {
        item.ledger_entry_id
        for item in (result_evidence_workspace.ledger_entries if result_evidence_workspace else [])
    }
    eligibility_by_id = {
        item.input_artifact_id: item
        for item in eligibility_decisions
        if item.input_artifact_type == "evidence_ledger_entry"
    }
    candidate_by_id = {
        item.candidate_criterion_id: item
        for item in (
            specialist_agent_workspace.candidate_criteria
            if specialist_agent_workspace
            else []
        )
    }

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
        evidence_ids = set(
            claim.supporting_evidence_ids
            + claim.contradicting_evidence_ids
            + claim.unresolved_evidence_ids
        )
        if claim.eligible_for_report and not (
            claim.source_fact_paths
            or evidence_ids
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
        dangling = evidence_ids - ledger_ids
        if dangling:
            finding(
                CriticType.CITATION_SUPPORT,
                CriticSeverity.BLOCKING,
                "CITATION-DANGLING",
                "A claim references an unknown evidence-ledger identifier.",
                "synthesis_claim",
                claim.claim_id,
                source_ids=dangling,
                correction="Remove the dangling reference or resolve it to a controlled ledger entry.",
            )
        role_overlap = (
            set(claim.supporting_evidence_ids)
            & (
                set(claim.contradicting_evidence_ids)
                | set(claim.unresolved_evidence_ids)
            )
        ) | (
            set(claim.contradicting_evidence_ids)
            & set(claim.unresolved_evidence_ids)
        )
        if role_overlap:
            finding(
                CriticType.CITATION_SUPPORT,
                CriticSeverity.BLOCKING,
                "CITATION-ROLE-MISMATCH",
                "An evidence identifier is assigned to more than one evidence role.",
                "synthesis_claim",
                claim.claim_id,
                source_ids=role_overlap,
                correction="Assign each evidence identifier one explicit role.",
            )
        reused = {
            item
            for item in evidence_ids
            if item in eligibility_by_id
            and eligibility_by_id[item].decision != EligibilityDecisionKind.ELIGIBLE
        }
        if claim.eligible_for_report and reused:
            finding(
                CriticType.CITATION_SUPPORT,
                CriticSeverity.BLOCKING,
                "CITATION-EXCLUDED-REUSE",
                "A factual claim attempts to reuse quarantined or excluded evidence.",
                "synthesis_claim",
                claim.claim_id,
                source_ids=reused,
                correction="Quarantine the claim and retain the source only as lifecycle context.",
            )
        omitted_contradiction = {
            evidence_id
            for candidate_id in claim.source_candidate_criterion_ids
            for evidence_id in (
                candidate_by_id[candidate_id].contradicting_ledger_entry_ids
                if candidate_id in candidate_by_id
                else []
            )
            if evidence_id not in claim.contradicting_evidence_ids
        }
        if omitted_contradiction:
            finding(
                CriticType.CITATION_SUPPORT,
                CriticSeverity.BLOCKING,
                "CITATION-OMITTED-CONTRADICTION",
                "A candidate-linked claim omits controlled contradicting evidence.",
                "synthesis_claim",
                claim.claim_id,
                source_ids=omitted_contradiction,
                correction="Restore the contradicting evidence role without resolving it.",
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
                source_ids=evidence_ids,
                correction="Preserve conflict language and require explicit human resolution.",
            )
        if claim.supporting_evidence_ids and claim.contradicting_evidence_ids:
            finding(
                CriticType.SCIENTIFIC_CONSISTENCY,
                CriticSeverity.WARNING,
                "SCIENCE-CONTROLLED-CONTRADICTION",
                "Controlled supporting and contradicting records coexist; no conclusion was selected.",
                "synthesis_claim",
                claim.claim_id,
                source_ids=evidence_ids,
                correction="Keep both roles visible and require human adjudication.",
            )
        if (
            claim.claim_category
            in {
                "phenotype_hpo",
                "pedigree_inheritance",
                "result_normalization",
                "evidence_ledger",
                "candidate_acmg",
            }
            and (
                claim.contradicting_evidence_ids
                or claim.support_status
                in {ClaimSupportStatus.CONFLICTING, ClaimSupportStatus.CONTRADICTED}
            )
        ):
            finding(
                CriticType.SCIENTIFIC_CONSISTENCY,
                CriticSeverity.WARNING,
                "SCIENCE-DOMAIN-INCONSISTENCY",
                (
                    f"Controlled {claim.claim_category} material contains an unresolved "
                    "contradiction; no diagnostic inference was made."
                ),
                "synthesis_claim",
                claim.claim_id,
                source_ids=evidence_ids,
                correction="Preserve the domain inconsistency for human review.",
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
            source_ids=(
                claim.supporting_evidence_ids
                + claim.contradicting_evidence_ids
                + claim.unresolved_evidence_ids
            ),
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
            decision = eligibility_by_id.get(entry.ledger_entry_id)
            if decision and decision.lifecycle_state != EvidenceLifecycleState.ACTIVE:
                finding(
                    CriticType.EVIDENCE_CONFLICT,
                    CriticSeverity.WARNING,
                    "CONFLICT-LIFECYCLE",
                    (
                        f"Evidence lifecycle state '{decision.lifecycle_state.value}' "
                        f"is preserved as {decision.decision.value}."
                    ),
                    "evidence_conflict",
                    entry.ledger_entry_id,
                    source_ids=(entry.ledger_entry_id,),
                    correction="Retain lifecycle history and do not use the record as current support.",
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
        rejected_ids = {
            item.action_id
            for item in specialist_agent_workspace.review_action_results
            if item.result_status.value == "rejected"
        }
        applied_ids = {
            item.action_id
            for item in specialist_agent_workspace.applied_review_actions
        }
        if rejected_ids & applied_ids:
            finding(
                CriticType.PROVENANCE,
                CriticSeverity.BLOCKING,
                "PROVENANCE-REJECTED-AS-APPLIED",
                "A rejected specialist review action is also presented as applied.",
                "workspace",
                case_id,
                source_ids=rejected_ids & applied_ids,
                correction="Remove the rejected action from applied provenance.",
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
        if _PROHIBITED_PRIVACY_INFERENCE_PATTERN.search(text):
            finding(
                CriticType.PRIVACY,
                CriticSeverity.BLOCKING,
                "PRIVACY-BOUNDARY",
                "Potential prohibited relationship, sample, or identity inference was detected.",
                target_type,
                target_id,
                correction="Remove the inference and retain only explicitly supplied bounded facts.",
            )
    for section in sections:
        if section.section_type in {
            "critic_findings",
            "jarvis_briefing",
            "human_review_history",
        }:
            continue
        expected_citations = {
            reference
            for claim_id in section.claim_ids
            for reference in (
                next(
                    item for item in claims if item.claim_id == claim_id
                ).supporting_evidence_ids
                + next(
                    item for item in claims if item.claim_id == claim_id
                ).contradicting_evidence_ids
                + next(
                    item for item in claims if item.claim_id == claim_id
                ).unresolved_evidence_ids
                + next(item for item in claims if item.claim_id == claim_id).source_fact_paths
            )
        }
        if set(section.citation_ids) != expected_citations:
            finding(
                CriticType.CITATION_SUPPORT,
                CriticSeverity.BLOCKING,
                "CITATION-MISMATCH",
                "Report-section citations do not exactly match its controlled claims.",
                "report_section",
                section.section_id,
                source_ids=set(section.citation_ids) ^ expected_citations,
                correction="Rebuild citations deterministically from the section claim set.",
            )
    for claim in claims:
        evidence_ids = (
            claim.supporting_evidence_ids
            + claim.contradicting_evidence_ids
            + claim.unresolved_evidence_ids
        )
        provenance_complete = bool(
            claim.source_fact_paths
            or evidence_ids
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
        if evidence_ids and not claim.eligibility_decision_ids:
            finding(
                CriticType.PROVENANCE,
                CriticSeverity.BLOCKING,
                "PROVENANCE-ELIGIBILITY-MISSING",
                "Evidence-bearing claim lacks a serialized eligibility decision.",
                "synthesis_claim",
                claim.claim_id,
                source_ids=evidence_ids,
                correction="Serialize the deterministic eligibility decisions for every evidence input.",
            )
        if (
            claim.generation_mode == "deterministic"
            and claim.provider_context.get("provider") != "deterministic"
        ):
            finding(
                CriticType.PROVENANCE,
                CriticSeverity.BLOCKING,
                "PROVENANCE-PROVIDER-MISLABEL",
                "Provider-generated text is labelled deterministic.",
                "synthesis_claim",
                claim.claim_id,
                correction="Use provider generation mode and preserve provider and budget context.",
            )
        if (
            claim.origin_category == ClaimOriginCategory.HUMAN_DECISION
            and not claim.source_human_decision_ids
        ):
            finding(
                CriticType.PROVENANCE,
                CriticSeverity.BLOCKING,
                "PROVENANCE-HUMAN-DECISION",
                "A human decision claim lacks an authoritative human decision identifier.",
                "synthesis_claim",
                claim.claim_id,
                correction="Remove the claim or link the recorded human decision.",
            )
        if (
            "acmg" in claim.statement.lower()
            and "external" in claim.statement.lower()
            and "not assigned by insilicopop" not in claim.statement.lower()
        ):
            finding(
                CriticType.PROVENANCE,
                CriticSeverity.BLOCKING,
                "PROVENANCE-EXTERNAL-ASSESSMENT",
                "An external ACMG assessment lacks explicit InSilicoPop non-assignment wording.",
                "synthesis_claim",
                claim.claim_id,
                correction="Restore external attribution and non-assignment wording.",
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
        if section.section_type == "human_review_history":
            results.append(
                _rejected_action(
                    action,
                    ReportReviewRejectionReason.INVALID_TRANSITION,
                    "The generated review-history section is audit-only.",
                    _section_snapshot(section),
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
        transition_matrix = {
            ReportHumanReviewStatus.PENDING: {
                ReportReviewActionType.ACCEPT,
                ReportReviewActionType.EDIT,
                ReportReviewActionType.REJECT,
                ReportReviewActionType.DEFER,
                ReportReviewActionType.REQUEST_MORE_INFORMATION,
            },
            ReportHumanReviewStatus.MORE_INFORMATION_REQUESTED: {
                ReportReviewActionType.ACCEPT,
                ReportReviewActionType.REJECT,
                ReportReviewActionType.DEFER,
                ReportReviewActionType.REQUEST_MORE_INFORMATION,
            },
            ReportHumanReviewStatus.ACCEPTED: set(),
            ReportHumanReviewStatus.EDITED: set(),
            ReportHumanReviewStatus.REJECTED: set(),
            ReportHumanReviewStatus.DEFERRED: set(),
        }
        if action.action not in transition_matrix[section.human_review_status]:
            results.append(
                _rejected_action(
                    action,
                    ReportReviewRejectionReason.INVALID_TRANSITION,
                    (
                        f"Action '{action.action.value}' is not permitted from "
                        f"'{section.human_review_status.value}'."
                    ),
                    authoritative_before,
                )
            )
            continue
        expected_status = {
            ReportReviewActionType.ACCEPT: ReportHumanReviewStatus.ACCEPTED,
            ReportReviewActionType.REJECT: ReportHumanReviewStatus.REJECTED,
            ReportReviewActionType.DEFER: ReportHumanReviewStatus.DEFERRED,
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
            if (
                _forbidden_matches(reviewable_edit_text)
                or _contains_direct_identifier(reviewable_edit_text)
                or _PROHIBITED_PRIVACY_INFERENCE_PATTERN.search(reviewable_edit_text)
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
            if section.section_type in {
                "critic_findings",
                "jarvis_briefing",
                "human_review_history",
            }:
                expected_citations = section.citation_ids
                expected_narrative = section.narrative
            else:
                expected_citations = sorted(
                    {
                        reference
                        for claim_id in updated.claim_ids
                        for reference in (
                            claims_by_id[claim_id].supporting_evidence_ids
                            + claims_by_id[claim_id].contradicting_evidence_ids
                            + claims_by_id[claim_id].unresolved_evidence_ids
                            + claims_by_id[claim_id].source_fact_paths
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
    evidence_ids = (
        claim.supporting_evidence_ids
        + claim.contradicting_evidence_ids
        + claim.unresolved_evidence_ids
    )
    provenance_complete = bool(
        claim.source_fact_paths
        or evidence_ids
        or claim.source_specialist_output_ids
        or claim.source_candidate_criterion_ids
        or claim.source_human_decision_ids
    )
    return ClaimEvidenceDrillDown(
        claim_id=claim.claim_id,
        source_fact_paths=claim.source_fact_paths,
        supporting_evidence_ids=claim.supporting_evidence_ids,
        contradicting_evidence_ids=claim.contradicting_evidence_ids,
        unresolved_evidence_ids=claim.unresolved_evidence_ids,
        specialist_output_ids=claim.source_specialist_output_ids,
        candidate_criterion_ids=claim.source_candidate_criterion_ids,
        human_decision_ids=claim.source_human_decision_ids,
        eligibility_decision_ids=claim.eligibility_decision_ids,
        exclusion_reason_codes=claim.exclusion_reason_codes,
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
    hashes = {}
    for name, value in sorted(artifacts.items()):
        if value is None:
            continue
        payload = value.model_dump(mode="json")
        if name == "result_evidence_workspace":
            payload["ledger_entries"] = sorted(
                payload.get("ledger_entries", []),
                key=lambda item: item.get("ledger_entry_id", ""),
            )
        hashes[name] = _hash_payload(payload)
    return hashes


def _forbidden_matches(text: str) -> list[str]:
    lowered = text.lower()
    explicitly_external = (
        ("external source" in lowered or "externally supplied" in lowered)
        and "not assigned by insilicopop" in lowered
    )
    bounded_negation = any(
        marker in lowered
        for marker in (
            "must not be made",
            "does not diagnose",
            "no diagnosis",
            "not a diagnosis",
            "does not confirm",
            "not clinically approved",
            "potentially prohibited clinical-conclusion language",
        )
    )
    if explicitly_external or bounded_negation:
        return []
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
