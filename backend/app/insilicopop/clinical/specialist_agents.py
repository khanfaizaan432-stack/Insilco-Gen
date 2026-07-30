from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

from pydantic import ValidationError

from app.insilicopop.clinical.models import ClinicalCaseIntake
from app.insilicopop.clinical.pretest_models import PreTestAssessmentResult
from app.insilicopop.clinical.result_evidence_models import (
    EvidenceDomain,
    EvidenceLedgerEntry,
    EvidenceSourceType,
    HumanReviewStatus,
    NormalizationOutcome,
    ResultEvidenceWorkspaceResult,
    RetrievalState,
    ReviewActionType,
)
from app.insilicopop.clinical.specialist_agent_models import (
    AGENT_OUTPUT_VALIDATOR_VERSION,
    AGENT_REGISTRY_VERSION,
    AGENT_SAFETY_POLICY_VERSION,
    CANDIDATE_RULESET_VERSION,
    AgentBudgetRemaining,
    AgentExecutionStatus,
    AgentRole,
    AgentSafetyReview,
    AgentSpawnRequest,
    AgentStructuredObservation,
    AgentTaskEnvelope,
    AgentTaskType,
    BudgetProfile,
    CandidateCriterionRecord,
    CandidateCriterionRequest,
    CandidateStatus,
    DisagreementGroup,
    ProviderPolicy,
    SafetyPolicy,
    SpawnDecision,
    SpawnRequestedBy,
    SpecialistAgentDefinition,
    SpecialistAgentOutput,
    SpecialistAgentWorkspaceResult,
    SpecialistExecutionTraceEvent,
    SpecialistHumanReviewAction,
    SpecialistReproducibility,
    SpecialistReviewActionType,
    SpecialistReviewActionResult,
    SpecialistReviewActionResultStatus,
    SpecialistReviewRejectionReason,
    SpecialistReviewStatus,
    TaskApprovalStatus,
    ToolPolicy,
)
from app.insilicopop.clinical.test_strategy_models import TestStrategyWorkspaceResult


_AGENT_VERSION = "0.33.0"
_OUTPUT_SCHEMA = "insilicopop-specialist-agent-output-0.33.0"
_DEFAULT_BUDGET = {
    "maximum_steps": 4,
    "maximum_calls": 1,
    "maximum_tokens": 2000,
    "maximum_cost": 0.0,
    "maximum_runtime_seconds": 10.0,
}
_EVIDENCE_TASKS = {
    AgentTaskType.REVIEW_GENE_DISEASE_EVIDENCE,
    AgentTaskType.REVIEW_VARIANT_DATABASE_EVIDENCE,
    AgentTaskType.REVIEW_LITERATURE_EVIDENCE,
    AgentTaskType.REVIEW_POPULATION_FREQUENCY_EVIDENCE,
    AgentTaskType.PROPOSE_CANDIDATE_ACMG_EVIDENCE,
    AgentTaskType.REVIEW_EVIDENCE_CONFLICT,
}
_ACTION_TARGET_ALLOWLIST = {
    "spawn_request": {
        SpecialistReviewActionType.APPROVE_AGENT_TASK,
        SpecialistReviewActionType.REJECT_AGENT_TASK,
        SpecialistReviewActionType.CANCEL_AGENT_TASK,
        SpecialistReviewActionType.RERUN_WITH_SAME_INPUTS,
        SpecialistReviewActionType.RERUN_WITH_EDITED_INPUTS,
        SpecialistReviewActionType.REQUEST_MORE_INFORMATION,
    },
    "agent_output": {
        SpecialistReviewActionType.ACCEPT_AGENT_OUTPUT_FOR_DISCUSSION,
        SpecialistReviewActionType.EDIT_AGENT_OUTPUT,
        SpecialistReviewActionType.REJECT_AGENT_OUTPUT,
        SpecialistReviewActionType.DEFER_AGENT_OUTPUT,
        SpecialistReviewActionType.REQUEST_MORE_INFORMATION,
    },
    "candidate_criterion": {
        SpecialistReviewActionType.ACCEPT_CANDIDATE_FOR_DISCUSSION,
        SpecialistReviewActionType.EDIT_CANDIDATE,
        SpecialistReviewActionType.REJECT_CANDIDATE,
        SpecialistReviewActionType.MARK_CANDIDATE_NOT_APPLICABLE,
        SpecialistReviewActionType.MARK_CANDIDATE_CONFLICTING,
        SpecialistReviewActionType.DEFER_CANDIDATE,
        SpecialistReviewActionType.REQUEST_MORE_INFORMATION,
    },
    "external_acmg_assessment": {
        SpecialistReviewActionType.RECORD_EXTERNAL_ACMG_ASSESSMENT,
        SpecialistReviewActionType.RECORD_EXTERNAL_CLASSIFICATION,
    },
}
_FORBIDDEN_OUTPUT_PATTERNS = {
    "diagnosis": re.compile(r"(?i)\b(?:diagnosis\s+(?:is|confirmed)|diagnosed\s+with)\b"),
    "treatment": re.compile(r"(?i)\b(?:recommend(?:ed)?\s+treatment|treatment\s+recommendation)\b"),
    "test_order": re.compile(r"(?i)\b(?:order(?:ed)?\s+(?:the\s+)?(?:genetic\s+)?test|test\s+has\s+been\s+ordered)\b"),
    "final_classification": re.compile(
        r"(?i)\b(?:final\s+(?:acmg|amp|pathogenicity)\s+classification|"
        r"(?:variant|finding)\s+is\s+(?:pathogenic|likely pathogenic|benign|likely benign))\b"
    ),
    "recurrence_risk": re.compile(r"(?i)\brecurrence\s+risk\s+(?:is|equals|of)\b"),
    "penetrance": re.compile(r"(?i)\bpenetrance\s+(?:is|equals|of)\b"),
    "hidden_relationship": re.compile(
        r"(?i)\b(?:biological\s+parentage\s+(?:is|confirmed)|hidden\s+family\s+relationship)\b"
    ),
    "protected_attribute": re.compile(
        r"(?i)\b(?:caste|religion|tribe|ethnicity|ancestry|community)\s+(?:is|inferred|confirmed)\b"
    ),
    "causality": re.compile(
        r"(?i)\b(?:variant\s+explains\s+the\s+referral|gene\s+causes\s+the\s+case|causative\s+variant)\b"
    ),
}
_FORBIDDEN_REQUEST_PATTERN = re.compile(
    r"(?i)\b(?:diagnos(?:e|is)|prescrib(?:e|ing)|treatment|order(?:ing)?\s+(?:a\s+)?test|"
    r"approve\s+(?:a\s+)?test|authoriz(?:e|ing)\s+(?:a\s+)?test|sign[- ]?out|"
    r"final\s+(?:acmg|amp|pathogenicity)\s+classification|recurrence\s+risk|penetrance|"
    r"biological\s+parentage|hidden\s+(?:family\s+)?relationship|caste|religion|tribe|"
    r"ethnicity|ancestry|community|causative\s+variant)\b"
)


def load_specialist_agent_registry() -> tuple[SpecialistAgentDefinition, ...]:
    shared = {
        **_DEFAULT_BUDGET,
        "agent_version": _AGENT_VERSION,
        "enabled": True,
        "allowed_tools": [],
        "may_use_external_llm": False,
        "may_use_local_retrieval": False,
        "may_spawn_agents": False,
        "required_output_schema": _OUTPUT_SCHEMA,
        "fallback_policy": "No fabricated success. Preserve provider, tool, policy, validation, and budget failures.",
    }
    definitions = [
        SpecialistAgentDefinition(
            agent_id="pre_test_strategy_review_agent",
            display_name="Pre-Test Strategy Review Agent",
            agent_role=AgentRole.PRE_TEST_STRATEGY_REVIEW,
            description="Reviews verified pre-test facts and existing staged strategy options without approving or ordering a test.",
            allowed_task_types=[AgentTaskType.REVIEW_PRE_TEST_STRATEGY],
            allowed_input_types=["structured_case_fact", "pre_test_assessment", "test_strategy_option"],
            allowed_evidence_domains=[],
            allowed_source_types=[],
            **shared,
        ),
        SpecialistAgentDefinition(
            agent_id="gene_disease_evidence_agent",
            display_name="Gene–Disease Evidence Agent",
            agent_role=AgentRole.GENE_DISEASE_EVIDENCE,
            description="Organizes reviewed gene–disease validity and mechanism ledger records without claiming case causality.",
            allowed_task_types=[AgentTaskType.REVIEW_GENE_DISEASE_EVIDENCE],
            allowed_input_types=["normalized_finding", "reviewed_ledger_entry"],
            allowed_evidence_domains=[
                EvidenceDomain.GENE_DISEASE_VALIDITY.value,
                EvidenceDomain.MECHANISM.value,
            ],
            allowed_source_types=[EvidenceSourceType.GENE_DISEASE_VALIDITY_RECORD.value],
            **shared,
        ),
        SpecialistAgentDefinition(
            agent_id="variant_database_evidence_agent",
            display_name="Variant-Database Evidence Agent",
            agent_role=AgentRole.VARIANT_DATABASE_EVIDENCE,
            description="Compares reviewed source assertions, dates, updates, withdrawals, and conflicts without selecting a classification.",
            allowed_task_types=[AgentTaskType.REVIEW_VARIANT_DATABASE_EVIDENCE],
            allowed_input_types=["normalized_finding", "reviewed_ledger_entry"],
            allowed_evidence_domains=[
                EvidenceDomain.CASE_OBSERVATION.value,
                EvidenceDomain.ALLELIC_DATA.value,
                EvidenceDomain.CONFLICTING_INTERPRETATION.value,
            ],
            allowed_source_types=[EvidenceSourceType.VARIANT_DATABASE_RECORD.value],
            **shared,
        ),
        SpecialistAgentDefinition(
            agent_id="literature_evidence_agent",
            display_name="Literature Evidence Agent",
            agent_role=AgentRole.LITERATURE_EVIDENCE,
            description="Organizes reviewed publication records and their applicability limits without unrestricted browsing.",
            allowed_task_types=[AgentTaskType.REVIEW_LITERATURE_EVIDENCE],
            allowed_input_types=["normalized_finding", "reviewed_ledger_entry"],
            allowed_evidence_domains=[
                EvidenceDomain.CASE_OBSERVATION.value,
                EvidenceDomain.SEGREGATION.value,
                EvidenceDomain.FUNCTIONAL_ASSAY.value,
                EvidenceDomain.GUIDELINE_STATEMENT.value,
                EvidenceDomain.CONFLICTING_INTERPRETATION.value,
            ],
            allowed_source_types=[
                EvidenceSourceType.PEER_REVIEWED_PUBLICATION.value,
                EvidenceSourceType.FUNCTIONAL_EVIDENCE_RECORD.value,
                EvidenceSourceType.SEGREGATION_EVIDENCE_RECORD.value,
                EvidenceSourceType.CLINICAL_GUIDELINE_OR_CONSENSUS.value,
            ],
            **shared,
        ),
        SpecialistAgentDefinition(
            agent_id="population_frequency_evidence_agent",
            display_name="Population-Frequency Evidence Agent",
            agent_role=AgentRole.POPULATION_FREQUENCY_EVIDENCE,
            description="Reviews bounded population-frequency records and no-record states without ancestry inference or rarity claims.",
            allowed_task_types=[AgentTaskType.REVIEW_POPULATION_FREQUENCY_EVIDENCE],
            allowed_input_types=["normalized_finding", "reviewed_ledger_entry", "retrieval_status"],
            allowed_evidence_domains=[EvidenceDomain.POPULATION_FREQUENCY.value],
            allowed_source_types=[EvidenceSourceType.POPULATION_FREQUENCY_RECORD.value],
            **shared,
        ),
        SpecialistAgentDefinition(
            agent_id="candidate_acmg_evidence_agent",
            display_name="Candidate ACMG Evidence Agent",
            agent_role=AgentRole.CANDIDATE_ACMG_EVIDENCE,
            description="Organizes explicit candidate ACMG/AMP evidence considerations linked to reviewed ledger entries; it does not classify.",
            allowed_task_types=[AgentTaskType.PROPOSE_CANDIDATE_ACMG_EVIDENCE],
            allowed_input_types=["normalized_finding", "reviewed_ledger_entry", "candidate_criterion_request"],
            allowed_evidence_domains=[item.value for item in EvidenceDomain],
            allowed_source_types=[item.value for item in EvidenceSourceType],
            **shared,
        ),
        SpecialistAgentDefinition(
            agent_id="evidence_conflict_reviewer",
            display_name="Evidence Conflict Reviewer",
            agent_role=AgentRole.EVIDENCE_CONFLICT_REVIEWER,
            description="Explains preserved evidence conflicts and routes them to human review without selecting a winner.",
            allowed_task_types=[AgentTaskType.REVIEW_EVIDENCE_CONFLICT],
            allowed_input_types=["normalized_finding", "reviewed_ledger_entry", "conflict_group"],
            allowed_evidence_domains=[item.value for item in EvidenceDomain],
            allowed_source_types=[item.value for item in EvidenceSourceType],
            **shared,
        ),
        SpecialistAgentDefinition(
            agent_id="safety_provenance_auditor",
            display_name="Safety and Provenance Auditor",
            agent_role=AgentRole.SAFETY_PROVENANCE_AUDITOR,
            description="Checks source linkage, forbidden conclusions, disclosure, budgets, and stop conditions; it cannot create a clinical conclusion.",
            allowed_task_types=[AgentTaskType.AUDIT_AGENT_OUTPUT],
            allowed_input_types=["agent_output", "task_envelope", "execution_trace"],
            allowed_evidence_domains=[],
            allowed_source_types=[],
            **shared,
        ),
    ]
    return tuple(sorted(definitions, key=lambda item: item.agent_id))


def build_specialist_agent_workspace(
    case: ClinicalCaseIntake,
    *,
    pretest_assessment: PreTestAssessmentResult | None,
    test_strategy_workspace: TestStrategyWorkspaceResult | None,
    result_evidence_workspace: ResultEvidenceWorkspaceResult | None,
) -> SpecialistAgentWorkspaceResult | None:
    request = case.specialist_agent_workspace
    if request is None:
        return None

    registry = load_specialist_agent_registry()
    registry_by_id = {item.agent_id: item for item in registry}
    workspace = result_evidence_workspace
    finding_by_id = {
        item.finding_id: item for item in (workspace.normalized_findings if workspace else [])
    }
    ledger_by_id = {
        item.ledger_entry_id: item for item in (workspace.ledger_entries if workspace else [])
    }
    reviewed_ledger_ids = _reviewed_ledger_ids(workspace)
    strategy_by_id = {
        item.option_id: item for item in (test_strategy_workspace.options if test_strategy_workspace else [])
    }
    available_fact_ids = _available_fact_ids(case, pretest_assessment, test_strategy_workspace)
    actions = sorted(request.review_actions, key=lambda item: (item.timestamp, item.action_id))
    actions_by_target: dict[
        tuple[str, str], list[SpecialistHumanReviewAction]
    ] = defaultdict(list)
    for action in actions:
        actions_by_target[(action.target_type, action.target_id)].append(action)

    decisions: list[SpawnDecision] = []
    envelopes: list[AgentTaskEnvelope] = []
    outputs: list[SpecialistAgentOutput] = []
    candidates: list[CandidateCriterionRecord] = []
    applied_actions: list[SpecialistHumanReviewAction] = []
    action_results: list[SpecialistReviewActionResult] = []
    processed_action_ids: set[str] = set()
    trace: list[SpecialistExecutionTraceEvent] = []
    candidate_requests_by_spawn: dict[str, list[CandidateCriterionRequest]] = defaultdict(list)
    for item in request.candidate_requests:
        candidate_requests_by_spawn[item.spawn_request_id].append(item)

    for spawn in sorted(request.spawn_requests, key=lambda item: item.spawn_request_id):
        trace.append(_trace("spawn_request", spawn, status=spawn.human_review_status.value))
        definition = registry_by_id.get(spawn.requested_agent_id)
        if definition:
            trace.append(
                _trace(
                    "registry_entry",
                    spawn,
                    status="approved_registry",
                    details={
                        "agent_id": definition.agent_id,
                        "agent_version": definition.agent_version,
                        "may_spawn_agents": definition.may_spawn_agents,
                    },
                )
            )
        approval, spawn_applied, spawn_results = _apply_spawn_review_actions(
            spawn,
            actions_by_target.get(
                ("spawn_request", spawn.spawn_request_id), []
            ),
        )
        decision, envelope = _evaluate_spawn_request(
            case=case,
            spawn=spawn,
            definition=definition,
            approval=approval,
            finding_by_id=finding_by_id,
            ledger_by_id=ledger_by_id,
            reviewed_ledger_ids=reviewed_ledger_ids,
            strategy_by_id=strategy_by_id,
            available_fact_ids=available_fact_ids,
            pretest_assessment=pretest_assessment,
            test_strategy_workspace=test_strategy_workspace,
            result_evidence_workspace=workspace,
            candidate_requests=candidate_requests_by_spawn.get(spawn.spawn_request_id, []),
        )
        applied_actions.extend(spawn_applied)
        action_results.extend(spawn_results)
        processed_action_ids.update(item.action_id for item in spawn_results)
        decisions.append(decision)
        if envelope is None:
            trace.append(
                _trace(
                    "stop_reason",
                    spawn,
                    status=decision.status.value,
                    details={"rule_ids": decision.rule_ids, "message": decision.message},
                )
            )
            continue
        envelopes.append(envelope)
        trace.extend(
            [
                _trace(
                    "task_envelope",
                    spawn,
                    task_id=envelope.agent_task_id,
                    status="ready",
                    details={
                        "allowed_fact_ids": envelope.allowed_fact_ids,
                        "allowed_finding_ids": envelope.allowed_finding_ids,
                        "allowed_strategy_option_ids": envelope.allowed_strategy_option_ids,
                        "allowed_ledger_entry_ids": envelope.allowed_ledger_entry_ids,
                        "allowed_conflict_group_ids": envelope.allowed_conflict_group_ids,
                    },
                ),
                _trace(
                    "input_hash",
                    spawn,
                    task_id=envelope.agent_task_id,
                    status="recorded",
                    details={"input_hash": envelope.input_hash},
                ),
                _trace("agent_start", spawn, task_id=envelope.agent_task_id, status="running"),
            ]
        )
        output = _execute_deterministic_agent(
            definition=definition,
            envelope=envelope,
            ledger_by_id=ledger_by_id,
            result_evidence_workspace=workspace,
            candidate_requests=candidate_requests_by_spawn.get(spawn.spawn_request_id, []),
        )
        output = validate_agent_output(
            output,
            definition=definition,
            envelope=envelope,
            ledger_by_id=ledger_by_id,
        )
        output, output_applied, output_results = _apply_output_review_actions(
            output,
            actions_by_target.get(("agent_output", output.agent_output_id), []),
            definition=definition,
            envelope=envelope,
            ledger_by_id=ledger_by_id,
        )
        applied_actions.extend(output_applied)
        action_results.extend(output_results)
        processed_action_ids.update(item.action_id for item in output_results)
        outputs.append(output)
        trace.extend(_output_trace(spawn, envelope, output))
        if (
            _output_is_review_ready(output)
            and spawn.requested_task_type == AgentTaskType.PROPOSE_CANDIDATE_ACMG_EVIDENCE
        ):
            new_candidates = [
                _candidate_record(
                    case=case,
                    candidate_request=item,
                    output=output,
                    finding_by_id=finding_by_id,
                    ledger_by_id=ledger_by_id,
                    reviewed_ledger_ids=reviewed_ledger_ids,
                    created_at=spawn.created_at,
                )
                for item in sorted(
                    candidate_requests_by_spawn.get(spawn.spawn_request_id, []),
                    key=lambda candidate: candidate.candidate_request_id,
                )
            ]
            candidates.extend(new_candidates)
            trace.append(
                _trace(
                    "candidate_acmg_proposals",
                    spawn,
                    task_id=envelope.agent_task_id,
                    output_id=output.agent_output_id,
                    status="candidate_only",
                    details={
                        "candidate_criterion_ids": [
                            item.candidate_criterion_id for item in new_candidates
                        ]
                    },
                )
            )

    reviewed_candidates: list[CandidateCriterionRecord] = []
    for item in candidates:
        candidate, candidate_applied, candidate_results = (
            _apply_candidate_review_actions(
                item,
                actions_by_target.get(
                    ("candidate_criterion", item.candidate_criterion_id), []
                ),
            )
        )
        reviewed_candidates.append(candidate)
        applied_actions.extend(candidate_applied)
        action_results.extend(candidate_results)
        processed_action_ids.update(item.action_id for item in candidate_results)
    candidates = reviewed_candidates
    external_by_id = {
        item.external_assessment_id: item
        for item in request.external_acmg_assessments
    }
    external_ids = set(external_by_id)
    for external_id in sorted(external_ids):
        for action in actions_by_target.get(
            ("external_acmg_assessment", external_id), []
        ):
            result = _apply_external_review_action(
                action, external_by_id[external_id]
            )
            action_results.append(result)
            processed_action_ids.add(action.action_id)
            if result.result_status == SpecialistReviewActionResultStatus.APPLIED:
                applied_actions.append(action)
    target_ids_by_type = {
        "spawn_request": {item.spawn_request_id for item in request.spawn_requests},
        "agent_output": {item.agent_output_id for item in outputs},
        "candidate_criterion": {
            item.candidate_criterion_id for item in candidates
        },
        "external_acmg_assessment": external_ids,
    }
    for action in actions:
        if action.action_id in processed_action_ids:
            continue
        exists_elsewhere = any(
            action.target_id in identifiers
            for target_type, identifiers in target_ids_by_type.items()
            if target_type != action.target_type
        )
        action_results.append(
            _rejected_action_result(
                action,
                reason=(
                    SpecialistReviewRejectionReason.TARGET_TYPE_MISMATCH
                    if exists_elsewhere
                    else SpecialistReviewRejectionReason.TARGET_NOT_FOUND
                ),
                message=(
                    "The declared target type does not match the authoritative object collection."
                    if exists_elsewhere
                    else "The declared target does not exist in the authoritative workspace collection."
                ),
            )
        )
    action_results.sort(key=lambda item: (item.timestamp, item.action_id))
    applied_actions.sort(key=lambda item: (item.timestamp, item.action_id))
    disagreements = _build_disagreement_groups(case.pseudonymous_case_id, outputs)
    trace.extend(
        [
            SpecialistExecutionTraceEvent(
                event="human_review_actions",
                status="recorded",
                details={
                    "requested_action_ids": [item.action_id for item in actions],
                    "requested_action_count": len(actions),
                    "applied_action_ids": [
                        item.action_id for item in applied_actions
                    ],
                    "applied_action_count": len(applied_actions),
                    "rejected_action_ids": [
                        item.action_id
                        for item in action_results
                        if item.result_status
                        == SpecialistReviewActionResultStatus.REJECTED
                    ],
                    "rejected_action_count": sum(
                        item.result_status
                        == SpecialistReviewActionResultStatus.REJECTED
                        for item in action_results
                    ),
                    "action_results": [
                        item.model_dump(mode="json") for item in action_results
                    ],
                },
            ),
            SpecialistExecutionTraceEvent(
                event="disagreement_groups",
                status="requires_human_review" if disagreements else "none",
                details={
                    "disagreement_group_ids": [
                        item.disagreement_group_id for item in disagreements
                    ],
                    "majority_vote_used": False,
                },
            ),
        ]
    )
    review_ready_output_ids = sorted(
        item.agent_output_id
        for item in outputs
        if _output_is_review_ready(item)
    )
    reproducibility = SpecialistReproducibility(
        agent_registry_version=AGENT_REGISTRY_VERSION,
        agent_versions={item.agent_id: item.agent_version for item in registry},
        agent_task_ids=sorted(item.agent_task_id for item in envelopes),
        agent_input_hashes={
            item.agent_task_id: item.input_hash for item in sorted(envelopes, key=lambda value: value.agent_task_id)
        },
        allowed_ledger_entry_ids=sorted(
            {ledger_id for item in envelopes for ledger_id in item.allowed_ledger_entry_ids}
        ),
        provider="mock",
        model="deterministic-specialist-fixture",
        external_llm_called=any(item.external_llm_called for item in outputs),
        external_tools_executed=any(item.external_tools_executed for item in outputs),
        token_usage=sum(item.token_usage for item in outputs),
        cost=round(sum(item.cost for item in outputs), 8),
        step_count=sum(item.step_count for item in outputs),
        budget_profiles=[item.budget.model_dump(mode="json") for item in envelopes],
        output_hashes={item.agent_output_id: item.output_hash for item in outputs},
        candidate_rule_versions=sorted({item.candidate_rule_version for item in candidates}),
        candidate_criterion_ids=sorted(item.candidate_criterion_id for item in candidates),
        human_review_actions=[item.model_dump(mode="json") for item in actions],
        applied_human_review_actions=[
            item.model_dump(mode="json") for item in applied_actions
        ],
        human_review_action_results=[
            item.model_dump(mode="json") for item in action_results
        ],
        safety_policy_version=AGENT_SAFETY_POLICY_VERSION,
    )
    return SpecialistAgentWorkspaceResult(
        pseudonymous_case_id=case.pseudonymous_case_id,
        approved_registry=list(registry),
        spawn_requests=sorted(request.spawn_requests, key=lambda item: item.spawn_request_id),
        spawn_decisions=sorted(decisions, key=lambda item: item.spawn_request_id),
        task_envelopes=sorted(envelopes, key=lambda item: item.agent_task_id),
        agent_outputs=sorted(outputs, key=lambda item: item.agent_output_id),
        review_ready_output_ids=review_ready_output_ids,
        candidate_criteria=sorted(candidates, key=lambda item: item.candidate_criterion_id),
        disagreement_groups=sorted(disagreements, key=lambda item: item.disagreement_group_id),
        review_actions=actions,
        requested_review_actions=actions,
        applied_review_actions=applied_actions,
        review_action_results=action_results,
        external_acmg_assessments=sorted(
            request.external_acmg_assessments,
            key=lambda item: item.external_assessment_id,
        ),
        execution_trace=trace,
        reproducibility=reproducibility,
        external_llm_called=any(item.external_llm_called for item in outputs),
        external_tools_executed=any(item.external_tools_executed for item in outputs),
    )


def validate_agent_output(
    output: SpecialistAgentOutput,
    *,
    definition: SpecialistAgentDefinition,
    envelope: AgentTaskEnvelope,
    ledger_by_id: dict[str, EvidenceLedgerEntry],
) -> SpecialistAgentOutput:
    unsupported = {
            ledger_id
            for ledger_id in (
                list(output.source_ledger_entry_ids)
                + [
                    nested_id
                    for observation in output.structured_observations
                    for nested_id in observation.source_ledger_entry_ids
                ]
            )
            if ledger_id not in ledger_by_id
            or ledger_id not in envelope.allowed_ledger_entry_ids
            or ledger_by_id[ledger_id].case_id != envelope.case_id
            or (
                envelope.allowed_finding_ids
                and ledger_by_id[ledger_id].finding_id not in envelope.allowed_finding_ids
            )
        }
    reviewable_text = "\n".join(
        value
        for value in (output.summary, output.human_reviewed_summary)
        if value
    )
    summary_ledger_ids = set(
        re.findall(
            r"(?i)\b(?:ledger-[a-f0-9]{8,64}|LEDGER-[A-Za-z0-9_.:-]+)\b",
            reviewable_text,
        )
    )
    unsupported.update(summary_ledger_ids - set(envelope.allowed_ledger_entry_ids))
    referenced_facts = set(output.source_fact_ids)
    referenced_findings = set(output.source_finding_ids)
    referenced_strategies = set(output.source_strategy_option_ids)
    referenced_conflicts = set(output.source_conflict_group_ids)
    for observation in output.structured_observations:
        referenced_facts.update(observation.source_fact_ids)
        referenced_findings.update(observation.source_finding_ids)
        referenced_strategies.update(observation.source_strategy_option_ids)
        referenced_conflicts.update(observation.source_conflict_group_ids)
    unsupported.update(
        f"fact:{item}" for item in referenced_facts - set(envelope.allowed_fact_ids)
    )
    unsupported.update(
        f"finding:{item}"
        for item in referenced_findings - set(envelope.allowed_finding_ids)
    )
    unsupported.update(
        f"strategy:{item}"
        for item in referenced_strategies - set(envelope.allowed_strategy_option_ids)
    )
    unsupported.update(
        f"conflict:{item}"
        for item in referenced_conflicts - set(envelope.allowed_conflict_group_ids)
    )
    unsupported = sorted(unsupported)
    forbidden = sorted(
        {
            label
            for label, pattern in _FORBIDDEN_OUTPUT_PATTERNS.items()
            if pattern.search(reviewable_text)
            or any(
                pattern.search(item.statement)
                for item in output.structured_observations
                if item.observation_type != "source_reported"
            )
        }
    )
    provider_valid = output.external_llm_called == (
        output.provider != "mock"
    ) and (
        output.external_llm_called
        or output.provider == envelope.provider_policy.provider == "mock"
    )
    tool_valid = output.external_tools_executed is False and not envelope.tool_policy.allowed_tools
    budget_valid = (
        output.token_usage <= envelope.budget.maximum_tokens
        and output.cost <= envelope.budget.maximum_cost
        and output.call_count <= envelope.budget.maximum_calls
        and output.step_count <= envelope.budget.maximum_steps
        and output.runtime_seconds <= envelope.budget.maximum_runtime_seconds
    )
    policy_rules = []
    if unsupported:
        policy_rules.append("AGENT-006")
    if forbidden:
        policy_rules.append("AGENT-007")
    if not budget_valid:
        policy_rules.append("AGENT-005")
    if not provider_valid:
        policy_rules.append("AGENT-PROVIDER-001")
    if not tool_valid:
        policy_rules.append("AGENT-TOOL-001")
    valid_registry = (
        output.agent_id == definition.agent_id
        and output.agent_version == definition.agent_version
        and envelope.task_type in definition.allowed_task_types
    )
    if not valid_registry:
        policy_rules.append("AGENT-001")
    invalid_reference = bool(unsupported)
    blocked_policy = bool(forbidden or not provider_valid or not tool_valid or not valid_registry)
    status = output.status
    review_status: str = "review_ready"
    if invalid_reference:
        status = AgentExecutionStatus.INVALID_OUTPUT
        review_status = "invalid_output"
    elif blocked_policy:
        status = AgentExecutionStatus.BLOCKED_BY_POLICY
        review_status = "blocked_by_policy"
    elif not budget_valid:
        status = (
            AgentExecutionStatus.TIMED_OUT
            if output.runtime_seconds > envelope.budget.maximum_runtime_seconds
            else AgentExecutionStatus.BUDGET_EXHAUSTED
        )
        review_status = "invalid_output"
    passed = not policy_rules
    safety = AgentSafetyReview(
        passed=passed,
        review_status=review_status,  # type: ignore[arg-type]
        unsupported_source_references=unsupported,
        forbidden_language_matches=forbidden,
        policy_rule_ids=sorted(set(policy_rules)),
        provider_disclosure_valid=provider_valid,
        tool_disclosure_valid=tool_valid,
        budget_compliant=budget_valid,
    )
    updated = output.model_copy(update={"status": status, "safety_review": safety})
    return updated.model_copy(update={"output_hash": _agent_output_hash(updated)})


def _evaluate_spawn_request(
    *,
    case: ClinicalCaseIntake,
    spawn: AgentSpawnRequest,
    definition: SpecialistAgentDefinition | None,
    approval: TaskApprovalStatus,
    finding_by_id: dict[str, Any],
    ledger_by_id: dict[str, EvidenceLedgerEntry],
    reviewed_ledger_ids: set[str],
    strategy_by_id: dict[str, Any],
    available_fact_ids: set[str],
    pretest_assessment: PreTestAssessmentResult | None,
    test_strategy_workspace: TestStrategyWorkspaceResult | None,
    result_evidence_workspace: ResultEvidenceWorkspaceResult | None,
    candidate_requests: list[CandidateCriterionRequest],
) -> tuple[SpawnDecision, AgentTaskEnvelope | None]:
    if definition is None or not definition.enabled:
        return _blocked(spawn, AgentExecutionStatus.BLOCKED_BY_POLICY, "AGENT-001", "Requested agent is not in the approved registry.")
    if spawn.requested_by == SpawnRequestedBy.SPECIALIST_AGENT:
        return _blocked(spawn, AgentExecutionStatus.BLOCKED_BY_POLICY, "AGENT-002", "Specialist agents cannot spawn agents recursively.")
    if _FORBIDDEN_REQUEST_PATTERN.search(spawn.request_reason):
        return _blocked(spawn, AgentExecutionStatus.BLOCKED_BY_POLICY, "AGENT-007", "Requested task asks for a prohibited clinical conclusion or action.")
    if spawn.requested_task_type not in definition.allowed_task_types:
        return _blocked(spawn, AgentExecutionStatus.BLOCKED_BY_POLICY, "AGENT-TASK-001", "Requested task type is not permitted for this agent.")
    if approval == TaskApprovalStatus.REJECTED or approval == TaskApprovalStatus.CANCELLED:
        return _blocked(spawn, AgentExecutionStatus.CANCELLED, "AGENT-REVIEW-002", "Human reviewer rejected or cancelled the bounded task.")
    if approval != TaskApprovalStatus.APPROVED:
        return _blocked(spawn, AgentExecutionStatus.NOT_STARTED, "AGENT-REVIEW-001", "Human approval is required before the bounded task can run.")
    if spawn.case_id != case.pseudonymous_case_id:
        return _blocked(spawn, AgentExecutionStatus.REQUIRES_RULE_REVIEW, "AGENT-INPUT-001", "Spawn request case ID does not match the active pseudonymous case.")
    if _budget_exceeds_definition(spawn.budget_profile, definition):
        return _blocked(spawn, AgentExecutionStatus.BLOCKED_BY_POLICY, "AGENT-005", "Requested budget exceeds the approved registry limit.")
    provider_issue = _provider_issue(spawn.provider_policy, definition)
    if provider_issue:
        return _blocked(spawn, provider_issue[0], provider_issue[1], provider_issue[2])
    unknown_facts = sorted(set(spawn.structured_input_ids) - available_fact_ids)
    unknown_findings = sorted(set(spawn.finding_ids) - set(finding_by_id))
    unknown_strategies = sorted(set(spawn.strategy_option_ids) - set(strategy_by_id))
    unknown_ledger = sorted(set(spawn.ledger_entry_ids) - set(ledger_by_id))
    if unknown_facts or unknown_findings or unknown_strategies or unknown_ledger:
        return _blocked(
            spawn,
            AgentExecutionStatus.REQUIRES_RULE_REVIEW,
            "AGENT-INPUT-002",
            "One or more requested structured inputs cannot be resolved.",
        )
    if spawn.requested_task_type == AgentTaskType.REVIEW_PRE_TEST_STRATEGY and not (
        spawn.structured_input_ids or spawn.strategy_option_ids
    ):
        return _blocked(spawn, AgentExecutionStatus.REQUIRES_RULE_REVIEW, "AGENT-INPUT-003", "Pre-test strategy review requires explicit structured facts or strategy option IDs.")
    if spawn.requested_task_type == AgentTaskType.PROPOSE_CANDIDATE_ACMG_EVIDENCE:
        ambiguous = [
            finding_id
            for finding_id in spawn.finding_ids
            if finding_by_id[finding_id].normalization_status
            == NormalizationOutcome.REQUIRES_RULE_REVIEW
        ]
        if ambiguous:
            return _blocked(spawn, AgentExecutionStatus.BLOCKED_BY_POLICY, "AGENT-004", "Ambiguous normalized findings block candidate ACMG execution.")
        if not candidate_requests:
            return _blocked(spawn, AgentExecutionStatus.REQUIRES_RULE_REVIEW, "AGENT-INPUT-004", "Candidate ACMG task requires an explicit candidate criterion request.")
        if any(
            item.finding_id not in spawn.finding_ids
            or not set(item.source_ledger_entry_ids).issubset(spawn.ledger_entry_ids)
            or not set(item.contradicting_ledger_entry_ids).issubset(spawn.ledger_entry_ids)
            for item in candidate_requests
        ):
            return _blocked(spawn, AgentExecutionStatus.REQUIRES_RULE_REVIEW, "AGENT-INPUT-005", "Candidate criterion request references inputs outside the bounded spawn request.")
    if spawn.requested_task_type in _EVIDENCE_TASKS:
        unreviewed = sorted(set(spawn.ledger_entry_ids) - reviewed_ledger_ids)
        if unreviewed:
            return _blocked(spawn, AgentExecutionStatus.REQUIRES_RULE_REVIEW, "AGENT-003", "External evidence has not passed the required human-review gate.")
        no_record_population_review = (
            spawn.requested_task_type == AgentTaskType.REVIEW_POPULATION_FREQUENCY_EVIDENCE
            and _has_no_records_state(result_evidence_workspace, spawn.finding_ids)
        )
        if not spawn.ledger_entry_ids and not no_record_population_review:
            return _blocked(spawn, AgentExecutionStatus.REQUIRES_RULE_REVIEW, "AGENT-003", "Task requires reviewed evidence-ledger inputs.")
        if spawn.ledger_entry_ids and spawn.requested_task_type not in {
            AgentTaskType.PROPOSE_CANDIDATE_ACMG_EVIDENCE,
            AgentTaskType.REVIEW_EVIDENCE_CONFLICT,
        }:
            disallowed_entries = [
                ledger_id
                for ledger_id in spawn.ledger_entry_ids
                if (
                    definition.allowed_evidence_domains
                    and ledger_by_id[ledger_id].evidence_domain.value
                    not in definition.allowed_evidence_domains
                )
                or (
                    definition.allowed_source_types
                    and ledger_by_id[ledger_id].source_type.value
                    not in definition.allowed_source_types
                )
            ]
            if disallowed_entries:
                return _blocked(
                    spawn,
                    AgentExecutionStatus.BLOCKED_BY_POLICY,
                    "AGENT-EVIDENCE-001",
                    "One or more reviewed ledger entries are outside the specialist agent's approved evidence scope.",
                )
    if spawn.requested_task_type == AgentTaskType.REVIEW_EVIDENCE_CONFLICT:
        known_conflicts = {
            item.conflict_group_id
            for item in ledger_by_id.values()
            if item.conflict_group_id
        }
        if not spawn.conflict_group_ids or not set(spawn.conflict_group_ids).issubset(known_conflicts):
            return _blocked(spawn, AgentExecutionStatus.REQUIRES_RULE_REVIEW, "AGENT-CONFLICT-001", "Conflict review requires resolved conflict-group IDs.")

    allowed_ledger_ids = sorted(set(spawn.ledger_entry_ids))
    allowed_conflict_ids = sorted(
        set(spawn.conflict_group_ids)
        | {
            ledger_by_id[ledger_id].conflict_group_id
            for ledger_id in allowed_ledger_ids
            if ledger_by_id[ledger_id].conflict_group_id
        }
    )
    snapshot = _structured_snapshot(
        case=case,
        spawn=spawn,
        pretest_assessment=pretest_assessment,
        test_strategy_workspace=test_strategy_workspace,
        result_evidence_workspace=result_evidence_workspace,
        reviewed_ledger_ids=reviewed_ledger_ids,
    )
    input_hash = _hash_payload(snapshot)
    task_id = _stable_id("agent-task", {"spawn_request_id": spawn.spawn_request_id, "input_hash": input_hash})
    envelope = AgentTaskEnvelope(
        agent_task_id=task_id,
        case_id=case.pseudonymous_case_id,
        agent_id=definition.agent_id,
        agent_version=definition.agent_version,
        task_type=spawn.requested_task_type,
        structured_case_snapshot=snapshot,
        allowed_fact_ids=sorted(set(spawn.structured_input_ids)),
        allowed_finding_ids=sorted(set(spawn.finding_ids)),
        allowed_strategy_option_ids=sorted(set(spawn.strategy_option_ids)),
        allowed_ledger_entry_ids=allowed_ledger_ids,
        allowed_conflict_group_ids=allowed_conflict_ids,
        input_hash=input_hash,
        budget=spawn.budget_profile,
        tool_policy=ToolPolicy(
            allowed_tools=[],
            local_retrieval_allowed=False,
        ),
        provider_policy=spawn.provider_policy,
        safety_policy=SafetyPolicy(),
        requested_at=spawn.created_at,
    )
    return (
        SpawnDecision(
            spawn_request_id=spawn.spawn_request_id,
            agent_task_id=task_id,
            status=AgentExecutionStatus.READY,
            rule_ids=[],
            message="Bounded task approved and ready for deterministic execution.",
            review_ready=False,
        ),
        envelope,
    )


def _execute_deterministic_agent(
    *,
    definition: SpecialistAgentDefinition,
    envelope: AgentTaskEnvelope,
    ledger_by_id: dict[str, EvidenceLedgerEntry],
    result_evidence_workspace: ResultEvidenceWorkspaceResult | None,
    candidate_requests: list[CandidateCriterionRequest],
) -> SpecialistAgentOutput:
    entries = [ledger_by_id[item] for item in envelope.allowed_ledger_entry_ids]
    observations: list[AgentStructuredObservation] = []
    contradictions: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    limitations = [
        "Only explicit structured inputs and reviewed evidence-ledger entries in the task envelope were inspected.",
        "This proposed output requires human review and does not diagnose, recommend treatment, order testing, establish causality, or assign a classification.",
    ]
    if envelope.task_type == AgentTaskType.REVIEW_PRE_TEST_STRATEGY:
        for option in envelope.structured_case_snapshot.get("strategy_options", []):
            observations.append(
                AgentStructuredObservation(
                    observation_id=_stable_id("observation", {"task": envelope.agent_task_id, "option": option["option_id"]}),
                    observation_type="structured_strategy_option",
                    statement=(
                        f"Existing strategy option {option['option_id']} is retained as "
                        f"{option.get('status', 'proposed_not_approved')} with explicit prerequisites for review."
                    ),
                    source_fact_ids=option.get("trigger_fact_ids", []),
                    source_strategy_option_ids=[option["option_id"]],
                )
            )
        summary = "Existing pre-test strategy options and their explicit structured prerequisites were organized for specialist review."
    elif envelope.task_type == AgentTaskType.REVIEW_POPULATION_FREQUENCY_EVIDENCE and not entries:
        no_records = envelope.structured_case_snapshot.get("no_record_retrievals", [])
        for retrieval in no_records:
            observations.append(
                AgentStructuredObservation(
                    observation_id=_stable_id("observation", {"task": envelope.agent_task_id, "retrieval": retrieval["retrieval_id"]}),
                    observation_type="no_records_returned",
                    statement=(
                        f"{retrieval['no_records_wording']} This selected-source result does not prove absence or rarity."
                    ),
                    source_finding_ids=[retrieval["finding_id"]],
                )
            )
        warnings.append("No population-frequency ledger record was available; no rarity conclusion was generated.")
        summary = "Selected-source no-record states were retained with coverage and absence limitations."
    elif envelope.task_type == AgentTaskType.AUDIT_AGENT_OUTPUT:
        summary = "The bounded safety and provenance review request was recorded; central deterministic validation remains authoritative."
        warnings.append("No separate clinical conclusion was generated by the safety auditor.")
    else:
        for entry in entries:
            position = _entry_position(entry)
            observations.append(
                AgentStructuredObservation(
                    observation_id=_stable_id("observation", {"task": envelope.agent_task_id, "ledger": entry.ledger_entry_id}),
                    observation_type="source_reported",
                    statement=f"Source-reported observation from {entry.source_title}: {entry.source_statement}",
                    source_finding_ids=[entry.finding_id],
                    source_ledger_entry_ids=[entry.ledger_entry_id],
                    source_conflict_group_ids=[entry.conflict_group_id] if entry.conflict_group_id else [],
                    position=position,
                )
            )
            if entry.conflict_detected:
                contradictions.append(
                    f"Ledger conflict group {entry.conflict_group_id} remains unresolved; no source was selected as a winner."
                )
            if entry.withdrawn_or_updated:
                warnings.append(
                    f"Ledger entry {entry.ledger_entry_id} is marked withdrawn or updated and requires source-date review."
                )
        summary = _role_summary(definition.agent_role, len(entries), bool(contradictions))
    if envelope.task_type == AgentTaskType.PROPOSE_CANDIDATE_ACMG_EVIDENCE:
        if not candidate_requests:
            missing.append("No explicit candidate criterion request was supplied.")
        summary = (
            f"{len(candidate_requests)} explicit candidate ACMG evidence consideration(s) were organized from reviewed ledger inputs. "
            "Each remains candidate only and separate; no strength change, combination, score, or classification was produced."
        )
    token_usage = max(1, len(summary.split()) + sum(len(item.statement.split()) for item in observations))
    runtime_seconds = 0.001
    status = (
        AgentExecutionStatus.COMPLETED_WITH_WARNINGS
        if warnings or missing or contradictions
        else AgentExecutionStatus.COMPLETED
    )
    if token_usage > envelope.budget.maximum_tokens:
        status = AgentExecutionStatus.BUDGET_EXHAUSTED
        warnings.append("Configured token budget was exhausted; the output is not review-ready.")
    if runtime_seconds > envelope.budget.maximum_runtime_seconds:
        status = AgentExecutionStatus.TIMED_OUT
        warnings.append("Configured runtime budget was exhausted; the output is not review-ready.")
    remaining = AgentBudgetRemaining(
        calls=max(0, envelope.budget.maximum_calls),
        tokens=max(0, envelope.budget.maximum_tokens - token_usage),
        cost=envelope.budget.maximum_cost,
        steps=max(0, envelope.budget.maximum_steps - 1),
        runtime_seconds=max(0.0, envelope.budget.maximum_runtime_seconds - 0.001),
    )
    source_ledger_ids = sorted(
        {
            ledger_id
            for item in observations
            for ledger_id in item.source_ledger_entry_ids
        }
    )
    output_id = _stable_id("agent-output", {"task": envelope.agent_task_id, "input_hash": envelope.input_hash})
    safety = AgentSafetyReview(
        passed=True,
        review_status="review_ready",
    )
    output = SpecialistAgentOutput(
        agent_output_id=output_id,
        agent_task_id=envelope.agent_task_id,
        agent_id=definition.agent_id,
        agent_version=definition.agent_version,
        status=status,
        summary=summary,
        structured_observations=observations,
        source_fact_ids=envelope.allowed_fact_ids,
        source_finding_ids=envelope.allowed_finding_ids,
        source_strategy_option_ids=envelope.allowed_strategy_option_ids,
        source_ledger_entry_ids=source_ledger_ids,
        source_conflict_group_ids=envelope.allowed_conflict_group_ids,
        missing_information=sorted(set(missing)),
        contradictions=sorted(set(contradictions)),
        limitations=limitations,
        warnings=sorted(set(warnings)),
        external_llm_called=False,
        external_tools_executed=False,
        provider="mock",
        model="deterministic-specialist-fixture",
        token_usage=token_usage,
        cost=0.0,
        runtime_seconds=runtime_seconds,
        call_count=0,
        step_count=1,
        budget_remaining=remaining,
        started_at=envelope.requested_at,
        completed_at=envelope.requested_at,
        output_hash="pending",
        safety_review=safety,
    )
    return output.model_copy(update={"output_hash": _agent_output_hash(output)})


def _candidate_record(
    *,
    case: ClinicalCaseIntake,
    candidate_request: CandidateCriterionRequest,
    output: SpecialistAgentOutput,
    finding_by_id: dict[str, Any],
    ledger_by_id: dict[str, EvidenceLedgerEntry],
    reviewed_ledger_ids: set[str],
    created_at: str,
) -> CandidateCriterionRecord:
    source_ids = sorted(set(candidate_request.source_ledger_entry_ids))
    contradicting_ids = sorted(set(candidate_request.contradicting_ledger_entry_ids))
    all_ids = set(source_ids) | set(contradicting_ids)
    unknown_or_unreviewed = sorted(
        ledger_id
        for ledger_id in all_ids
        if ledger_id not in ledger_by_id or ledger_id not in reviewed_ledger_ids
    )
    missing = list(candidate_request.missing_prerequisites)
    if candidate_request.finding_id not in finding_by_id:
        missing.append("Normalized or source-preserved finding is unresolved.")
    status = CandidateStatus.CANDIDATE_ONLY
    applicability = list(candidate_request.applicability_notes)
    if unknown_or_unreviewed:
        status = CandidateStatus.REQUIRES_RULE_REVIEW
        missing.append("One or more evidence references are unresolved or have not passed human review.")
    elif not source_ids:
        if _finding_has_external_classification(finding_by_id.get(candidate_request.finding_id)):
            status = CandidateStatus.REQUIRES_RULE_REVIEW
            applicability.append(
                "External classification alone is insufficient; InSilicoPop did not recreate or adopt it."
            )
        else:
            status = CandidateStatus.INSUFFICIENT_SUPPORT
            missing.append("Available ledger evidence is insufficient to support this candidate consideration.")
    elif _external_classification_only(source_ids, ledger_by_id):
        status = CandidateStatus.REQUIRES_RULE_REVIEW
        applicability.append(
            "External classification alone is insufficient; InSilicoPop did not recreate or adopt it."
        )
    elif contradicting_ids:
        status = CandidateStatus.CONFLICTING_SUPPORT
    elif missing:
        status = CandidateStatus.INSUFFICIENT_SUPPORT
    criterion_id = _stable_id(
        "candidate-criterion",
        {
            "case_id": case.pseudonymous_case_id,
            "request_id": candidate_request.candidate_request_id,
            "output_id": output.agent_output_id,
            "rule_id": candidate_request.candidate_rule_id,
            "rule_version": candidate_request.candidate_rule_version,
        },
    )
    supporting_observations = list(candidate_request.supporting_observations)
    if status == CandidateStatus.INSUFFICIENT_SUPPORT and not supporting_observations:
        supporting_observations.append(
            "Available ledger evidence is insufficient to support this candidate consideration."
        )
    return CandidateCriterionRecord(
        candidate_criterion_id=criterion_id,
        case_id=case.pseudonymous_case_id,
        finding_id=candidate_request.finding_id,
        criterion_code=candidate_request.criterion_code,
        criterion_family=candidate_request.criterion_family,
        candidate_status=status,
        proposed_strength=candidate_request.proposed_strength,
        source_ledger_entry_ids=source_ids,
        supporting_observations=supporting_observations,
        contradicting_ledger_entry_ids=contradicting_ids,
        missing_prerequisites=sorted(set(missing)),
        applicability_notes=sorted(set(applicability)),
        gene_disease_context=candidate_request.gene_disease_context,
        mechanism_context=candidate_request.mechanism_context,
        inheritance_context=candidate_request.inheritance_context,
        phenotype_context=candidate_request.phenotype_context,
        technical_limitations=candidate_request.technical_limitations,
        candidate_rule_id=candidate_request.candidate_rule_id,
        candidate_rule_version=candidate_request.candidate_rule_version,
        agent_output_id=output.agent_output_id,
        created_at=created_at,
        updated_at=created_at,
    )


def _apply_output_review_actions(
    output: SpecialistAgentOutput,
    actions: list[SpecialistHumanReviewAction],
    *,
    definition: SpecialistAgentDefinition,
    envelope: AgentTaskEnvelope,
    ledger_by_id: dict[str, EvidenceLedgerEntry],
) -> tuple[
    SpecialistAgentOutput,
    list[SpecialistHumanReviewAction],
    list[SpecialistReviewActionResult],
]:
    applied: list[SpecialistHumanReviewAction] = []
    results: list[SpecialistReviewActionResult] = []
    transitions = {
        SpecialistReviewActionType.ACCEPT_AGENT_OUTPUT_FOR_DISCUSSION: (
            {
                SpecialistReviewStatus.PENDING,
                SpecialistReviewStatus.EDITED,
            },
            SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
        ),
        SpecialistReviewActionType.REJECT_AGENT_OUTPUT: (
            {
                SpecialistReviewStatus.PENDING,
                SpecialistReviewStatus.EDITED,
                SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
                SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
            },
            SpecialistReviewStatus.REJECTED,
        ),
        SpecialistReviewActionType.DEFER_AGENT_OUTPUT: (
            {
                SpecialistReviewStatus.PENDING,
                SpecialistReviewStatus.EDITED,
                SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
                SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
            },
            SpecialistReviewStatus.DEFERRED,
        ),
        SpecialistReviewActionType.REQUEST_MORE_INFORMATION: (
            {
                SpecialistReviewStatus.PENDING,
                SpecialistReviewStatus.EDITED,
                SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
            },
            SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
        ),
    }
    for action in sorted(actions, key=lambda item: (item.timestamp, item.action_id)):
        before = _output_review_snapshot(output)
        if action.action not in _ACTION_TARGET_ALLOWLIST["agent_output"]:
            results.append(
                _rejected_action_result(
                    action,
                    SpecialistReviewRejectionReason.ACTION_TARGET_MISMATCH,
                    "The requested action is not allowed for a specialist output.",
                    before=before,
                )
            )
            continue
        required_before = (
            {"summary", "human_review_status"}
            if action.action == SpecialistReviewActionType.EDIT_AGENT_OUTPUT
            else {"human_review_status"}
        )
        rejection = _validate_before_value(action, before, required_before)
        if rejection:
            results.append(rejection)
            continue
        if action.action == SpecialistReviewActionType.EDIT_AGENT_OUTPUT:
            if output.human_review_status not in {
                SpecialistReviewStatus.PENDING,
                SpecialistReviewStatus.EDITED,
                SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
                SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
            }:
                results.append(
                    _invalid_transition_result(action, before)
                )
                continue
            if not isinstance(action.after_value, dict):
                results.append(_after_value_required_result(action, before))
                continue
            if set(action.after_value) != {"summary"}:
                results.append(
                    _rejected_action_result(
                        action,
                        SpecialistReviewRejectionReason.INVALID_EDIT_PAYLOAD,
                        "Output edits support only one bounded human-reviewed summary field.",
                        before=before,
                        validation_categories=["unsupported_edit_field"],
                    )
                )
                continue
            payload = output.model_dump(mode="json")
            payload.update(
                {
                    "human_review_status": SpecialistReviewStatus.EDITED.value,
                    "human_reviewed_summary": action.after_value["summary"],
                    "reviewer_notes": action.notes or output.reviewer_notes,
                }
            )
            try:
                edited = SpecialistAgentOutput.model_validate(payload)
            except ValidationError as exc:
                results.append(
                    _validation_rejection(action, before, exc)
                )
                continue
            edited = validate_agent_output(
                edited,
                definition=definition,
                envelope=envelope,
                ledger_by_id=ledger_by_id,
            )
            if not edited.safety_review.passed:
                reason = (
                    SpecialistReviewRejectionReason.FORBIDDEN_EDIT
                    if edited.safety_review.forbidden_language_matches
                    else SpecialistReviewRejectionReason.INVALID_EDIT_PAYLOAD
                )
                categories = sorted(
                    set(
                        edited.safety_review.forbidden_language_matches
                        + (
                            ["unsupported_source_reference"]
                            if edited.safety_review.unsupported_source_references
                            else []
                        )
                    )
                )
                results.append(
                    _rejected_action_result(
                        action,
                        reason,
                        "The edited output failed specialist output safety validation.",
                        before=before,
                        validation_categories=categories,
                    )
                )
                continue
            output = edited
        else:
            allowed_states, next_state = transitions[action.action]
            if output.human_review_status not in allowed_states:
                results.append(_invalid_transition_result(action, before))
                continue
            expected_after = {"human_review_status": next_state.value}
            rejection = _validate_after_value(action, expected_after, before)
            if rejection:
                results.append(rejection)
                continue
            payload = output.model_dump(mode="json")
            payload["human_review_status"] = next_state.value
            if action.notes:
                payload["reviewer_notes"] = action.notes
            output = SpecialistAgentOutput.model_validate(payload)
        after = _output_review_snapshot(output)
        applied.append(action)
        results.append(_applied_action_result(action, before, after))
    return output, applied, results


def _apply_candidate_review_actions(
    candidate: CandidateCriterionRecord,
    actions: list[SpecialistHumanReviewAction],
) -> tuple[
    CandidateCriterionRecord,
    list[SpecialistHumanReviewAction],
    list[SpecialistReviewActionResult],
]:
    applied: list[SpecialistHumanReviewAction] = []
    results: list[SpecialistReviewActionResult] = []
    editable = {
        "proposed_strength",
        "supporting_observations",
        "missing_prerequisites",
        "applicability_notes",
        "gene_disease_context",
        "mechanism_context",
        "inheritance_context",
        "phenotype_context",
        "technical_limitations",
    }
    transitions = {
        SpecialistReviewActionType.ACCEPT_CANDIDATE_FOR_DISCUSSION: (
            {
                SpecialistReviewStatus.PENDING,
                SpecialistReviewStatus.EDITED,
                SpecialistReviewStatus.CONFLICTING,
            },
            CandidateStatus.ACCEPTED_FOR_DISCUSSION,
            SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
        ),
        SpecialistReviewActionType.REJECT_CANDIDATE: (
            {
                SpecialistReviewStatus.PENDING,
                SpecialistReviewStatus.EDITED,
                SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
                SpecialistReviewStatus.CONFLICTING,
                SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
            },
            CandidateStatus.REJECTED_BY_REVIEWER,
            SpecialistReviewStatus.REJECTED,
        ),
        SpecialistReviewActionType.MARK_CANDIDATE_NOT_APPLICABLE: (
            {
                SpecialistReviewStatus.PENDING,
                SpecialistReviewStatus.EDITED,
                SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
                SpecialistReviewStatus.CONFLICTING,
                SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
            },
            CandidateStatus.NOT_APPLICABLE,
            SpecialistReviewStatus.NOT_APPLICABLE,
        ),
        SpecialistReviewActionType.MARK_CANDIDATE_CONFLICTING: (
            {
                SpecialistReviewStatus.PENDING,
                SpecialistReviewStatus.EDITED,
                SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
                SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
            },
            CandidateStatus.CONFLICTING_SUPPORT,
            SpecialistReviewStatus.CONFLICTING,
        ),
        SpecialistReviewActionType.DEFER_CANDIDATE: (
            {
                SpecialistReviewStatus.PENDING,
                SpecialistReviewStatus.EDITED,
                SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
                SpecialistReviewStatus.CONFLICTING,
                SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
            },
            CandidateStatus.DEFERRED,
            SpecialistReviewStatus.DEFERRED,
        ),
        SpecialistReviewActionType.REQUEST_MORE_INFORMATION: (
            {
                SpecialistReviewStatus.PENDING,
                SpecialistReviewStatus.EDITED,
                SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
                SpecialistReviewStatus.CONFLICTING,
            },
            None,
            SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
        ),
    }
    for action in sorted(actions, key=lambda item: (item.timestamp, item.action_id)):
        before = _candidate_review_snapshot(candidate)
        if action.action not in _ACTION_TARGET_ALLOWLIST["candidate_criterion"]:
            results.append(
                _rejected_action_result(
                    action,
                    SpecialistReviewRejectionReason.ACTION_TARGET_MISMATCH,
                    "The requested action is not allowed for a candidate criterion.",
                    before=before,
                )
            )
            continue
        if action.action == SpecialistReviewActionType.EDIT_CANDIDATE:
            if candidate.human_review_status not in {
                SpecialistReviewStatus.PENDING,
                SpecialistReviewStatus.EDITED,
                SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
                SpecialistReviewStatus.CONFLICTING,
                SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
            }:
                results.append(_invalid_transition_result(action, before))
                continue
            if not isinstance(action.after_value, dict) or not action.after_value:
                results.append(_after_value_required_result(action, before))
                continue
            edit_fields = set(action.after_value)
            if not edit_fields.issubset(editable):
                results.append(
                    _rejected_action_result(
                        action,
                        SpecialistReviewRejectionReason.INVALID_EDIT_PAYLOAD,
                        "The candidate edit contains one or more unsupported fields.",
                        before=before,
                        validation_categories=["unsupported_edit_field"],
                    )
                )
                continue
            rejection = _validate_before_value(
                action, before, edit_fields | {"human_review_status"}
            )
            if rejection:
                results.append(rejection)
                continue
            if _contains_forbidden_review_text(action.after_value):
                results.append(
                    _rejected_action_result(
                        action,
                        SpecialistReviewRejectionReason.FORBIDDEN_EDIT,
                        "The candidate edit contains prohibited clinical conclusion wording.",
                        before=before,
                        validation_categories=["forbidden_clinical_conclusion"],
                    )
                )
                continue
            payload = candidate.model_dump(mode="json")
            payload.update(action.after_value)
            payload.update(
                {
                    "human_review_status": SpecialistReviewStatus.EDITED.value,
                    "reviewer_notes": action.notes or candidate.reviewer_notes,
                    "updated_at": action.timestamp,
                }
            )
            try:
                candidate = CandidateCriterionRecord.model_validate(payload)
            except ValidationError as exc:
                results.append(_validation_rejection(action, before, exc))
                continue
        else:
            rejection = _validate_before_value(
                action, before, {"candidate_status"}
            )
            if rejection:
                results.append(rejection)
                continue
            allowed_states, candidate_status, review_status = transitions[action.action]
            if candidate.human_review_status not in allowed_states:
                results.append(_invalid_transition_result(action, before))
                continue
            expected_after = {
                "candidate_status": (
                    candidate_status.value
                    if candidate_status is not None
                    else candidate.candidate_status.value
                ),
                "human_review_status": review_status.value,
            }
            rejection = _validate_after_value(
                action,
                expected_after,
                before,
                required_keys={"candidate_status"},
            )
            if rejection:
                results.append(rejection)
                continue
            payload = candidate.model_dump(mode="json")
            if candidate_status is not None:
                payload["candidate_status"] = candidate_status.value
            payload["human_review_status"] = review_status.value
            payload["updated_at"] = action.timestamp
            if action.notes:
                payload["reviewer_notes"] = action.notes
            candidate = CandidateCriterionRecord.model_validate(payload)
        after = _candidate_review_snapshot(candidate)
        applied.append(action)
        results.append(_applied_action_result(action, before, after))
    return candidate, applied, results


def _output_is_review_ready(output: SpecialistAgentOutput) -> bool:
    return (
        output.status
        in {AgentExecutionStatus.COMPLETED, AgentExecutionStatus.COMPLETED_WITH_WARNINGS}
        and output.safety_review.passed
        and output.human_review_status
        not in {
            SpecialistReviewStatus.REJECTED,
            SpecialistReviewStatus.DEFERRED,
            SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
        }
    )


def _build_disagreement_groups(
    case_id: str,
    outputs: list[SpecialistAgentOutput],
) -> list[DisagreementGroup]:
    by_conflict: dict[str, list[tuple[SpecialistAgentOutput, AgentStructuredObservation]]] = defaultdict(list)
    for output in outputs:
        if not output.safety_review.passed:
            continue
        for observation in output.structured_observations:
            for conflict_id in observation.source_conflict_group_ids:
                by_conflict[conflict_id].append((output, observation))
    groups = []
    for conflict_id, values in sorted(by_conflict.items()):
        output_ids = sorted({output.agent_output_id for output, _ in values})
        positions = {observation.position or observation.statement for _, observation in values}
        if len(output_ids) < 2 or len(positions) < 2:
            continue
        finding_ids = sorted(
            {
                finding_id
                for _, observation in values
                for finding_id in observation.source_finding_ids
            }
        )
        statements = sorted({observation.statement for _, observation in values})
        source_ids = sorted(
            {
                ledger_id
                for _, observation in values
                for ledger_id in observation.source_ledger_entry_ids
            }
        )
        groups.append(
            DisagreementGroup(
                disagreement_group_id=_stable_id(
                    "agent-disagreement",
                    {"case_id": case_id, "conflict_id": conflict_id, "outputs": output_ids},
                ),
                case_id=case_id,
                finding_id=finding_ids[0] if len(finding_ids) == 1 else None,
                agent_output_ids=output_ids,
                conflicting_statements=statements,
                supporting_source_ids=source_ids,
                source_conflict_group_ids=[conflict_id],
            )
        )
    return groups


def _structured_snapshot(
    *,
    case: ClinicalCaseIntake,
    spawn: AgentSpawnRequest,
    pretest_assessment: PreTestAssessmentResult | None,
    test_strategy_workspace: TestStrategyWorkspaceResult | None,
    result_evidence_workspace: ResultEvidenceWorkspaceResult | None,
    reviewed_ledger_ids: set[str],
) -> dict[str, Any]:
    fact_ids = set(spawn.structured_input_ids)
    finding_ids = set(spawn.finding_ids)
    strategy_ids = set(spawn.strategy_option_ids)
    ledger_ids = set(spawn.ledger_entry_ids)
    phenotype_facts = [
        {
            "fact_id": item.observation_id,
            "state": item.state.value,
            "hpo_id": item.hpo_id,
            "review_state": item.review_state.value,
        }
        for item in case.phenotypes
        if item.observation_id in fact_ids
    ]
    strategy_options = [
        {
            "option_id": item.option_id,
            "test_class": item.test_class.value,
            "display_name": item.display_name,
            "status": item.status,
            "trigger_fact_ids": [
                fact.fact_id for fact in item.trigger_facts if fact.fact_id in fact_ids
            ],
            "prerequisites": item.prerequisites,
            "reasons_to_defer": item.reasons_to_defer,
            "feasibility_status": item.feasibility_status.value,
        }
        for item in (test_strategy_workspace.options if test_strategy_workspace else [])
        if item.option_id in strategy_ids
    ]
    findings = [
        {
            "finding_id": item.finding_id,
            "category": item.category.value,
            "normalization_status": item.normalization_status.value,
            "normalized_value": item.normalized_value,
            "human_review_status": item.human_review_status.value,
        }
        for item in (result_evidence_workspace.normalized_findings if result_evidence_workspace else [])
        if item.finding_id in finding_ids
    ]
    ledger_entries = [
        {
            **item.model_dump(mode="json"),
            "ledger_verified": item.ledger_entry_id in reviewed_ledger_ids,
        }
        for item in (result_evidence_workspace.ledger_entries if result_evidence_workspace else [])
        if item.ledger_entry_id in ledger_ids
    ]
    no_record_retrievals = [
        {
            "retrieval_id": item.retrieval_id,
            "finding_id": item.finding_id,
            "source_name": item.source_name,
            "source_version": item.source_version,
            "state": item.state.value,
            "no_records_wording": item.no_records_wording,
        }
        for item in (result_evidence_workspace.retrieval_records if result_evidence_workspace else [])
        if item.finding_id in finding_ids
        and item.state == RetrievalState.NO_RECORDS_FOUND
        and item.source_type == EvidenceSourceType.POPULATION_FREQUENCY_RECORD
    ]
    return {
        "case_id": case.pseudonymous_case_id,
        "clinical_schema_version": case.schema_version,
        "pretest_outcome": pretest_assessment.assessment_outcome.value if pretest_assessment else None,
        "phenotype_facts": phenotype_facts,
        "strategy_options": strategy_options,
        "findings": findings,
        "reviewed_ledger_entries": ledger_entries,
        "no_record_retrievals": no_record_retrievals,
        "selected_input_ids": {
            "fact_ids": sorted(fact_ids),
            "finding_ids": sorted(finding_ids),
            "strategy_option_ids": sorted(strategy_ids),
            "ledger_entry_ids": sorted(ledger_ids),
            "conflict_group_ids": sorted(set(spawn.conflict_group_ids)),
        },
        "raw_case_narrative_included": False,
        "raw_source_documents_included": False,
    }


def _available_fact_ids(
    case: ClinicalCaseIntake,
    pretest_assessment: PreTestAssessmentResult | None,
    test_strategy_workspace: TestStrategyWorkspaceResult | None,
) -> set[str]:
    fact_ids = {item.observation_id for item in case.phenotypes}
    fact_ids.update(item.family_member_id for item in case.pedigree)
    if pretest_assessment:
        fact_ids.update(item.request_id for item in pretest_assessment.missing_information_plan)
        fact_ids.update(item.checkpoint_id for item in pretest_assessment.clinician_decisions)
    if test_strategy_workspace:
        fact_ids.update(
            fact.fact_id for option in test_strategy_workspace.options for fact in option.trigger_facts
        )
    return fact_ids


def _reviewed_ledger_ids(workspace: ResultEvidenceWorkspaceResult | None) -> set[str]:
    if workspace is None:
        return set()
    reviewed = {
        item.ledger_entry_id
        for item in workspace.ledger_entries
        if item.human_review_status
        in {HumanReviewStatus.ACCEPTED_INTO_WORKSPACE, HumanReviewStatus.EDITED}
    }
    reviewed.update(
        action.target_id
        for action in workspace.review_actions
        if action.action in {ReviewActionType.ACCEPT_LEDGER_ENTRY, ReviewActionType.ANNOTATE_LEDGER_ENTRY}
        and action.target_type == "ledger_entry"
    )
    return reviewed


def _apply_spawn_review_actions(
    spawn: AgentSpawnRequest,
    actions: list[SpecialistHumanReviewAction],
) -> tuple[
    TaskApprovalStatus,
    list[SpecialistHumanReviewAction],
    list[SpecialistReviewActionResult],
]:
    status = spawn.human_review_status
    applied: list[SpecialistHumanReviewAction] = []
    results: list[SpecialistReviewActionResult] = []
    transitions = {
        SpecialistReviewActionType.APPROVE_AGENT_TASK: (
            {TaskApprovalStatus.PENDING, TaskApprovalStatus.REQUIRES_REVIEW},
            TaskApprovalStatus.APPROVED,
        ),
        SpecialistReviewActionType.REJECT_AGENT_TASK: (
            {
                TaskApprovalStatus.PENDING,
                TaskApprovalStatus.APPROVED,
                TaskApprovalStatus.REQUIRES_REVIEW,
            },
            TaskApprovalStatus.REJECTED,
        ),
        SpecialistReviewActionType.CANCEL_AGENT_TASK: (
            {
                TaskApprovalStatus.PENDING,
                TaskApprovalStatus.APPROVED,
                TaskApprovalStatus.REQUIRES_REVIEW,
            },
            TaskApprovalStatus.CANCELLED,
        ),
        SpecialistReviewActionType.RERUN_WITH_SAME_INPUTS: (
            {
                TaskApprovalStatus.REJECTED,
                TaskApprovalStatus.CANCELLED,
                TaskApprovalStatus.REQUIRES_REVIEW,
            },
            TaskApprovalStatus.APPROVED,
        ),
        SpecialistReviewActionType.RERUN_WITH_EDITED_INPUTS: (
            {
                TaskApprovalStatus.REJECTED,
                TaskApprovalStatus.CANCELLED,
                TaskApprovalStatus.REQUIRES_REVIEW,
            },
            TaskApprovalStatus.APPROVED,
        ),
        SpecialistReviewActionType.REQUEST_MORE_INFORMATION: (
            {TaskApprovalStatus.PENDING, TaskApprovalStatus.APPROVED},
            TaskApprovalStatus.REQUIRES_REVIEW,
        ),
    }
    for action in sorted(actions, key=lambda item: (item.timestamp, item.action_id)):
        before = {"human_review_status": status.value}
        if action.action not in _ACTION_TARGET_ALLOWLIST["spawn_request"]:
            results.append(
                _rejected_action_result(
                    action,
                    SpecialistReviewRejectionReason.ACTION_TARGET_MISMATCH,
                    "The requested action is not allowed for a spawn request.",
                    before=before,
                )
            )
            continue
        rejection = _validate_before_value(
            action, before, {"human_review_status"}
        )
        if rejection:
            results.append(rejection)
            continue
        allowed_states, next_state = transitions[action.action]
        if status not in allowed_states:
            results.append(_invalid_transition_result(action, before))
            continue
        expected_after = {"human_review_status": next_state.value}
        rejection = _validate_after_value(action, expected_after, before)
        if rejection:
            results.append(rejection)
            continue
        status = next_state
        applied.append(action)
        results.append(
            _applied_action_result(
                action,
                before,
                {"human_review_status": status.value},
            )
        )
    return status, applied, results


def _apply_external_review_action(
    action: SpecialistHumanReviewAction,
    assessment: Any,
) -> SpecialistReviewActionResult:
    before = {
        "external_acmg_assessment_recorded": bool(
            assessment.external_acmg_assessment_recorded
        ),
        "verification_status": assessment.verification_status.value,
    }
    if action.action not in _ACTION_TARGET_ALLOWLIST["external_acmg_assessment"]:
        return _rejected_action_result(
            action,
            SpecialistReviewRejectionReason.ACTION_TARGET_MISMATCH,
            "The requested action is not allowed for an external ACMG assessment.",
            before=before,
        )
    if action.after_value is not None:
        return _rejected_action_result(
            action,
            SpecialistReviewRejectionReason.INVALID_EDIT_PAYLOAD,
            "External assessment record actions do not accept a mutation payload.",
            before=before,
            validation_categories=["unsupported_edit_payload"],
        )
    if action.before_value is not None:
        rejection = _validate_before_value(action, before, set())
        if rejection:
            return rejection
    return _applied_action_result(action, before, before)


def _output_review_snapshot(output: SpecialistAgentOutput) -> dict[str, Any]:
    return {
        "human_review_status": output.human_review_status.value,
        "summary": output.human_reviewed_summary or output.summary,
    }


def _candidate_review_snapshot(
    candidate: CandidateCriterionRecord,
) -> dict[str, Any]:
    payload = candidate.model_dump(mode="json")
    return {
        key: payload[key]
        for key in (
            "candidate_status",
            "human_review_status",
            "proposed_strength",
            "supporting_observations",
            "missing_prerequisites",
            "applicability_notes",
            "gene_disease_context",
            "mechanism_context",
            "inheritance_context",
            "phenotype_context",
            "technical_limitations",
        )
    }


def _validate_before_value(
    action: SpecialistHumanReviewAction,
    authoritative: dict[str, Any],
    required_keys: set[str],
) -> SpecialistReviewActionResult | None:
    if action.before_value is None:
        return _rejected_action_result(
            action,
            SpecialistReviewRejectionReason.BEFORE_VALUE_REQUIRED,
            "The review action requires an authoritative before value.",
            before=authoritative,
        )
    if not isinstance(action.before_value, dict) or not required_keys.issubset(
        action.before_value
    ):
        return _rejected_action_result(
            action,
            SpecialistReviewRejectionReason.BEFORE_VALUE_REQUIRED,
            "The review action is missing one or more required before fields.",
            before=authoritative,
        )
    if any(
        key not in authoritative
        or _canonical_json(value) != _canonical_json(authoritative[key])
        for key, value in action.before_value.items()
    ):
        return _rejected_action_result(
            action,
            SpecialistReviewRejectionReason.BEFORE_VALUE_MISMATCH,
            "The supplied before value is stale or does not match authoritative state.",
            before=authoritative,
        )
    return None


def _validate_after_value(
    action: SpecialistHumanReviewAction,
    expected: dict[str, Any],
    before: dict[str, Any],
    *,
    required_keys: set[str] | None = None,
) -> SpecialistReviewActionResult | None:
    required = required_keys if required_keys is not None else set(expected)
    if not isinstance(action.after_value, dict) or not required.issubset(
        action.after_value
    ):
        return _after_value_required_result(action, before)
    if any(
        key not in expected
        or _canonical_json(value) != _canonical_json(expected[key])
        for key, value in action.after_value.items()
    ):
        return _rejected_action_result(
            action,
            SpecialistReviewRejectionReason.AFTER_VALUE_MISMATCH,
            "The supplied after value does not match the allowed transition.",
            before=before,
        )
    return None


def _after_value_required_result(
    action: SpecialistHumanReviewAction,
    before: dict[str, Any],
) -> SpecialistReviewActionResult:
    return _rejected_action_result(
        action,
        SpecialistReviewRejectionReason.AFTER_VALUE_REQUIRED,
        "The review action requires a bounded after value.",
        before=before,
    )


def _invalid_transition_result(
    action: SpecialistHumanReviewAction,
    before: dict[str, Any],
) -> SpecialistReviewActionResult:
    return _rejected_action_result(
        action,
        SpecialistReviewRejectionReason.INVALID_TRANSITION,
        "The requested action is not allowed from the current authoritative state.",
        before=before,
    )


def _validation_rejection(
    action: SpecialistHumanReviewAction,
    before: dict[str, Any],
    error: ValidationError,
) -> SpecialistReviewActionResult:
    return _rejected_action_result(
        action,
        SpecialistReviewRejectionReason.INVALID_EDIT_PAYLOAD,
        "The edit failed full typed model validation.",
        before=before,
        validation_categories=sorted(
            {str(item.get("type", "validation_error")) for item in error.errors()}
        ),
    )


def _applied_action_result(
    action: SpecialistHumanReviewAction,
    before: dict[str, Any],
    after: dict[str, Any],
) -> SpecialistReviewActionResult:
    return SpecialistReviewActionResult(
        action_id=action.action_id,
        action=action.action,
        target_type=action.target_type,
        target_id=action.target_id,
        result_status=SpecialistReviewActionResultStatus.APPLIED,
        message="The review action was validated and applied.",
        authoritative_before=before,
        validated_after=after,
        reviewer_role=action.reviewer_role,
        reviewer_id=action.reviewer_id,
        timestamp=action.timestamp,
    )


def _rejected_action_result(
    action: SpecialistHumanReviewAction,
    reason: SpecialistReviewRejectionReason,
    message: str,
    *,
    before: dict[str, Any] | None = None,
    validation_categories: list[str] | None = None,
) -> SpecialistReviewActionResult:
    return SpecialistReviewActionResult(
        action_id=action.action_id,
        action=action.action,
        target_type=action.target_type,
        target_id=action.target_id,
        result_status=SpecialistReviewActionResultStatus.REJECTED,
        rejection_reason=reason,
        message=message,
        authoritative_before=before,
        validated_after=None,
        validation_categories=validation_categories or [],
        reviewer_role=action.reviewer_role,
        reviewer_id=action.reviewer_id,
        timestamp=action.timestamp,
    )


def _contains_forbidden_review_text(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _FORBIDDEN_OUTPUT_PATTERNS.values())
    if isinstance(value, dict):
        return any(_contains_forbidden_review_text(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_review_text(item) for item in value)
    return False


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _budget_exceeds_definition(
    budget: BudgetProfile,
    definition: SpecialistAgentDefinition,
) -> bool:
    return (
        budget.maximum_steps > definition.maximum_steps
        or budget.maximum_calls > definition.maximum_calls
        or budget.maximum_tokens > definition.maximum_tokens
        or budget.maximum_cost > definition.maximum_cost
        or budget.maximum_runtime_seconds > definition.maximum_runtime_seconds
    )


def _provider_issue(
    policy: ProviderPolicy,
    definition: SpecialistAgentDefinition,
) -> tuple[AgentExecutionStatus, str, str] | None:
    if not policy.provider_available:
        return (
            AgentExecutionStatus.PROVIDER_UNAVAILABLE,
            "AGENT-PROVIDER-002",
            "Configured provider is unavailable; no successful output was fabricated.",
        )
    if policy.provider == "openai_compatible":
        if policy.session_stale or not policy.session_valid:
            return (
                AgentExecutionStatus.PROVIDER_UNAVAILABLE,
                "AGENT-PROVIDER-003",
                "External provider session is stale or invalid.",
            )
        if not policy.external_llm_use_approved or not definition.may_use_external_llm:
            return (
                AgentExecutionStatus.BLOCKED_BY_POLICY,
                "AGENT-PROVIDER-001",
                "External LLM use is not approved for this bounded specialist agent.",
            )
    return None


def _blocked(
    spawn: AgentSpawnRequest,
    status: AgentExecutionStatus,
    rule_id: str,
    message: str,
) -> tuple[SpawnDecision, None]:
    return (
        SpawnDecision(
            spawn_request_id=spawn.spawn_request_id,
            status=status,
            rule_ids=[rule_id],
            message=message,
            review_ready=False,
        ),
        None,
    )


def _has_no_records_state(
    workspace: ResultEvidenceWorkspaceResult | None,
    finding_ids: list[str],
) -> bool:
    return bool(
        workspace
        and any(
            item.finding_id in finding_ids
            and item.state == RetrievalState.NO_RECORDS_FOUND
            and item.source_type == EvidenceSourceType.POPULATION_FREQUENCY_RECORD
            for item in workspace.retrieval_records
        )
    )


def _role_summary(role: AgentRole, record_count: int, conflicts: bool) -> str:
    suffix = " Conflicting records remain unresolved and require human review." if conflicts else ""
    summaries = {
        AgentRole.GENE_DISEASE_EVIDENCE: f"{record_count} reviewed gene–disease or mechanism ledger record(s) were organized without claiming that a gene explains the case.",
        AgentRole.VARIANT_DATABASE_EVIDENCE: f"{record_count} reviewed variant-database assertion(s) were compared without selecting an external classification as correct.",
        AgentRole.LITERATURE_EVIDENCE: f"{record_count} reviewed publication-linked record(s) were organized with source type and applicability limits preserved.",
        AgentRole.POPULATION_FREQUENCY_EVIDENCE: f"{record_count} reviewed population-frequency record(s) were organized without ancestry inference or an automatic frequency criterion.",
        AgentRole.CANDIDATE_ACMG_EVIDENCE: f"{record_count} reviewed ledger record(s) were retained for explicit candidate-only organization.",
        AgentRole.EVIDENCE_CONFLICT_REVIEWER: f"{record_count} reviewed conflict-linked record(s) were preserved without voting, averaging, or selecting a winner.",
        AgentRole.SAFETY_PROVENANCE_AUDITOR: "Safety and provenance inputs were checked without generating a clinical conclusion.",
        AgentRole.PRE_TEST_STRATEGY_REVIEW: "Existing pre-test strategy inputs were organized without approving or ordering testing.",
    }
    return summaries[role] + suffix


def _entry_position(entry: EvidenceLedgerEntry) -> str:
    for key in ("stance", "interpretation", "classification", "direction", "result"):
        value = entry.structured_observation.get(key)
        if value is not None:
            return str(value)
    return _hash_payload(entry.source_statement)[:16]


def _finding_has_external_classification(finding: Any) -> bool:
    if finding is None:
        return False
    snapshot = finding.reported_finding_snapshot
    return snapshot.external_laboratory_classification is not None


def _external_classification_only(
    source_ids: list[str],
    ledger_by_id: dict[str, EvidenceLedgerEntry],
) -> bool:
    if not source_ids:
        return False
    for source_id in source_ids:
        entry = ledger_by_id[source_id]
        keys = {str(key).lower() for key in entry.structured_observation}
        classification_like = (
            entry.source_type == EvidenceSourceType.LABORATORY_OR_ASSAY_DOCUMENTATION
            and any("classif" in key for key in keys)
        )
        if not classification_like:
            return False
    return True


def _output_trace(
    spawn: AgentSpawnRequest,
    envelope: AgentTaskEnvelope,
    output: SpecialistAgentOutput,
) -> list[SpecialistExecutionTraceEvent]:
    common = {
        "spawn": spawn,
        "task_id": envelope.agent_task_id,
        "output_id": output.agent_output_id,
    }
    return [
        _trace("agent_steps", status=output.status.value, details={"step_count": output.step_count}, **common),
        _trace("tool_calls", status="recorded", details={"external_tools_executed": output.external_tools_executed, "tool_count": 0}, **common),
        _trace("provider_calls", status="recorded", details={"provider": output.provider, "model": output.model, "external_llm_called": output.external_llm_called, "call_count": output.call_count}, **common),
        _trace("budget_events", status="compliant" if output.safety_review.budget_compliant else "exceeded", details={"token_usage": output.token_usage, "cost": output.cost, "runtime_seconds": output.runtime_seconds, "budget_remaining": output.budget_remaining.model_dump(mode="json")}, **common),
        _trace("output_validation", status=output.status.value, details={"validator_version": output.validator_version, "unsupported_source_references": output.safety_review.unsupported_source_references}, **common),
        _trace("safety_validation", status=output.safety_review.review_status, details={"policy_rule_ids": output.safety_review.policy_rule_ids, "forbidden_language_matches": output.safety_review.forbidden_language_matches}, **common),
        _trace("agent_output", status=output.status.value, details={"output_hash": output.output_hash, "proposal_status": output.proposal_status}, **common),
        _trace("stop_reason", status=output.status.value, details={"review_ready": output.safety_review.passed}, **common),
    ]


def _trace(
    event: str,
    spawn: AgentSpawnRequest | None = None,
    *,
    task_id: str | None = None,
    output_id: str | None = None,
    status: str | None = None,
    details: dict[str, Any] | None = None,
) -> SpecialistExecutionTraceEvent:
    return SpecialistExecutionTraceEvent(
        event=event,  # type: ignore[arg-type]
        spawn_request_id=spawn.spawn_request_id if spawn else None,
        agent_task_id=task_id,
        agent_output_id=output_id,
        status=status,
        details=details or {},
    )


def _agent_output_hash(output: SpecialistAgentOutput) -> str:
    payload = output.model_dump(mode="json")
    payload.pop("output_hash", None)
    payload.pop("safety_review", None)
    payload.pop("human_review_status", None)
    payload.pop("human_reviewed_summary", None)
    payload.pop("reviewer_notes", None)
    return _hash_payload(payload)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}-{_hash_payload(payload)[:16]}"
