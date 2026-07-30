from __future__ import annotations

import copy

from app.insilicopop.clinical import (
    build_clinical_case_result_evidence_bundle,
    build_clinical_case_specialist_agent_bundle,
    load_specialist_agent_registry,
)
from app.insilicopop.clinical.specialist_agent_models import (
    AgentExecutionStatus,
    CandidateStatus,
    SpecialistReviewStatus,
)
from app.insilicopop.clinical.specialist_agents import validate_agent_output
from backend.tests.test_result_evidence_workspace_v032 import (
    fixture_adapter,
    fixture_record,
    workspace_payload,
)


def _ledger_ids(payload: dict) -> list[str]:
    workspace = build_clinical_case_result_evidence_bundle(payload)[6]
    return [item.ledger_entry_id for item in workspace.ledger_entries]


def _reviewed_payload(records=None, *, source_type="variant_database_record") -> tuple[dict, list[str]]:
    records = records if records is not None else [fixture_record()]
    payload = workspace_payload(
        adapters=[fixture_adapter(records, source_type=source_type)],
        summaries=[],
    )
    ids = _ledger_ids(payload)
    for index, ledger_id in enumerate(ids, 1):
        payload["result_evidence_workspace"]["review_actions"].append(
            {
                "action_id": f"ACCEPT-LEDGER-{index}",
                "action": "accept_ledger_entry",
                "target_type": "ledger_entry",
                "target_id": ledger_id,
                "reviewer_role": "clinical_research_reviewer",
                "reviewer_id": "reviewer",
                "timestamp": f"2026-01-{index + 5:02d}T00:00:00Z",
                "before_value": {"status": "unreviewed"},
                "after_value": {"status": "accepted_into_workspace"},
            }
        )
    return payload, ids


def _spawn(
    *,
    request_id: str,
    agent_id: str,
    task_type: str,
    ledger_ids=None,
    finding_ids=None,
    conflict_ids=None,
    structured_ids=None,
    status="approved",
    requested_by="human_reviewer",
    budget=None,
    provider=None,
) -> dict:
    return {
        "spawn_request_id": request_id,
        "case_id": "CASE-V032",
        "requested_agent_id": agent_id,
        "requested_task_type": task_type,
        "requested_by": requested_by,
        "request_reason": "Synthetic bounded specialist review.",
        "structured_input_ids": structured_ids or [],
        "ledger_entry_ids": ledger_ids or [],
        "finding_ids": finding_ids or ["FIND-SEQ-1"],
        "strategy_option_ids": [],
        "conflict_group_ids": conflict_ids or [],
        "human_review_status": status,
        "budget_profile": budget
        or {
            "profile_id": "test",
            "maximum_steps": 4,
            "maximum_calls": 1,
            "maximum_tokens": 2000,
            "maximum_cost": 0,
            "maximum_runtime_seconds": 10,
        },
        "provider_policy": provider
        or {
            "provider": "mock",
            "model": "deterministic-specialist-fixture",
            "external_llm_use_approved": False,
            "session_valid": False,
            "session_stale": False,
            "provider_available": True,
        },
        "created_at": "2026-01-10T00:00:00Z",
    }


def _run(payload: dict):
    return build_clinical_case_specialist_agent_bundle(payload)[7]


def test_registry_is_fixed_versioned_non_recursive_and_complete():
    registry = load_specialist_agent_registry()
    assert len(registry) == 8
    assert all(item.enabled for item in registry)
    assert all(item.may_spawn_agents is False for item in registry)
    assert all(item.registry_version == "insilicopop-specialist-agent-registry-0.33.0" for item in registry)
    assert {item.display_name for item in registry} == {
        "Pre-Test Strategy Review Agent",
        "Gene–Disease Evidence Agent",
        "Variant-Database Evidence Agent",
        "Literature Evidence Agent",
        "Population-Frequency Evidence Agent",
        "Candidate ACMG Evidence Agent",
        "Evidence Conflict Reviewer",
        "Safety and Provenance Auditor",
    }


def test_unknown_dynamic_role_and_recursive_spawn_are_blocked():
    payload, ids = _reviewed_payload()
    payload["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-UNKNOWN",
                agent_id="invented_agent_role",
                task_type="review_variant_database_evidence",
                ledger_ids=ids,
            ),
            _spawn(
                request_id="SPAWN-RECURSIVE",
                agent_id="variant_database_evidence_agent",
                task_type="review_variant_database_evidence",
                ledger_ids=ids,
                requested_by="specialist_agent",
            ),
        ],
        "human_review_required": True,
    }
    result = _run(payload)
    decisions = {item.spawn_request_id: item for item in result.spawn_decisions}
    assert decisions["SPAWN-UNKNOWN"].status == AgentExecutionStatus.BLOCKED_BY_POLICY
    assert decisions["SPAWN-UNKNOWN"].rule_ids == ["AGENT-001"]
    assert decisions["SPAWN-RECURSIVE"].status == AgentExecutionStatus.BLOCKED_BY_POLICY
    assert decisions["SPAWN-RECURSIVE"].rule_ids == ["AGENT-002"]
    assert result.recursive_spawning_used is False
    assert result.dynamic_roles_created is False


def test_task_approval_disallowed_task_missing_review_and_budget_are_enforced():
    payload, ids = _reviewed_payload()
    excessive = {
        "profile_id": "too-large",
        "maximum_steps": 5,
        "maximum_calls": 1,
        "maximum_tokens": 2000,
        "maximum_cost": 0,
        "maximum_runtime_seconds": 10,
    }
    payload["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-PENDING",
                agent_id="variant_database_evidence_agent",
                task_type="review_variant_database_evidence",
                ledger_ids=ids,
                status="pending",
            ),
            _spawn(
                request_id="SPAWN-WRONG-TASK",
                agent_id="variant_database_evidence_agent",
                task_type="review_literature_evidence",
                ledger_ids=ids,
            ),
            _spawn(
                request_id="SPAWN-BUDGET",
                agent_id="variant_database_evidence_agent",
                task_type="review_variant_database_evidence",
                ledger_ids=ids,
                budget=excessive,
            ),
        ],
        "human_review_required": True,
    }
    result = _run(payload)
    decisions = {item.spawn_request_id: item for item in result.spawn_decisions}
    assert decisions["SPAWN-PENDING"].status == AgentExecutionStatus.NOT_STARTED
    assert decisions["SPAWN-WRONG-TASK"].status == AgentExecutionStatus.BLOCKED_BY_POLICY
    assert decisions["SPAWN-BUDGET"].rule_ids == ["AGENT-005"]

    unreviewed = workspace_payload(summaries=[])
    raw_ids = _ledger_ids(unreviewed)
    unreviewed["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-UNREVIEWED",
                agent_id="variant_database_evidence_agent",
                task_type="review_variant_database_evidence",
                ledger_ids=raw_ids,
            )
        ],
        "human_review_required": True,
    }
    decision = _run(unreviewed).spawn_decisions[0]
    assert decision.status == AgentExecutionStatus.REQUIRES_RULE_REVIEW
    assert decision.rule_ids == ["AGENT-003"]


def test_human_action_can_approve_task_and_prohibited_intent_is_blocked():
    payload, ids = _reviewed_payload()
    payload["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-ACTION-APPROVAL",
                agent_id="variant_database_evidence_agent",
                task_type="review_variant_database_evidence",
                ledger_ids=ids,
                status="pending",
            ),
            {
                **_spawn(
                    request_id="SPAWN-DIAGNOSIS",
                    agent_id="variant_database_evidence_agent",
                    task_type="review_variant_database_evidence",
                    ledger_ids=ids,
                ),
                "request_reason": "Diagnose the case and assign a final ACMG classification.",
            },
        ],
        "review_actions": [
            {
                "action_id": "APPROVE-TASK-1",
                "action": "approve_agent_task",
                "target_type": "spawn_request",
                "target_id": "SPAWN-ACTION-APPROVAL",
                "reviewer_role": "clinical_research_reviewer",
                "reviewer_id": "reviewer",
                "timestamp": "2026-01-10T01:00:00Z",
                "before_value": {"human_review_status": "pending"},
                "after_value": {"human_review_status": "approved"},
            }
        ],
        "human_review_required": True,
    }
    result = _run(payload)
    decisions = {item.spawn_request_id: item for item in result.spawn_decisions}
    assert decisions["SPAWN-ACTION-APPROVAL"].status == AgentExecutionStatus.READY
    assert decisions["SPAWN-DIAGNOSIS"].status == AgentExecutionStatus.BLOCKED_BY_POLICY
    assert decisions["SPAWN-DIAGNOSIS"].rule_ids == ["AGENT-007"]


def test_task_review_actions_are_target_typed_and_preserve_terminal_decisions():
    payload, ids = _reviewed_payload()
    base_spawn = _spawn(
        request_id="SPAWN-REVIEW-TARGET",
        agent_id="variant_database_evidence_agent",
        task_type="review_variant_database_evidence",
        ledger_ids=ids,
        status="pending",
    )
    action_expectations = {
        "reject_agent_task": ("pending", "rejected", AgentExecutionStatus.CANCELLED),
        "cancel_agent_task": ("pending", "cancelled", AgentExecutionStatus.CANCELLED),
        "rerun_with_same_inputs": ("rejected", "approved", AgentExecutionStatus.READY),
        "rerun_with_edited_inputs": ("cancelled", "approved", AgentExecutionStatus.READY),
    }
    for index, (action_name, expectation) in enumerate(
        action_expectations.items(), 1
    ):
        before_status, after_status, expected_status = expectation
        reviewed = copy.deepcopy(payload)
        reviewed_spawn = copy.deepcopy(base_spawn)
        reviewed_spawn["human_review_status"] = before_status
        reviewed["specialist_agent_workspace"] = {
            "schema_version": "0.33",
            "spawn_requests": [reviewed_spawn],
            "review_actions": [
                {
                    "action_id": f"TASK-ACTION-{index}",
                    "action": action_name,
                    "target_type": "spawn_request",
                    "target_id": "SPAWN-REVIEW-TARGET",
                    "reviewer_role": "clinical_research_reviewer",
                    "timestamp": f"2026-01-{index + 12:02d}T00:00:00Z",
                    "before_value": {"human_review_status": before_status},
                    "after_value": {"human_review_status": after_status},
                }
            ],
            "human_review_required": True,
        }
        assert _run(reviewed).spawn_decisions[0].status == expected_status

    wrong_target = copy.deepcopy(payload)
    wrong_target["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [base_spawn],
        "review_actions": [
            {
                "action_id": "WRONG-TARGET-TYPE",
                "action": "approve_agent_task",
                "target_type": "agent_output",
                "target_id": "SPAWN-REVIEW-TARGET",
                "reviewer_role": "clinical_research_reviewer",
                "timestamp": "2026-01-18T00:00:00Z",
            }
        ],
        "human_review_required": True,
    }
    assert (
        _run(wrong_target).spawn_decisions[0].status
        == AgentExecutionStatus.NOT_STARTED
    )


def test_pretest_and_safety_agents_run_without_recursive_delegation():
    payload = workspace_payload(adapters=[], queries=[], summaries=[])
    payload["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-PRETEST",
                agent_id="pre_test_strategy_review_agent",
                task_type="review_pre_test_strategy",
                ledger_ids=[],
                structured_ids=["PH-1"],
            ),
            _spawn(
                request_id="SPAWN-SAFETY",
                agent_id="safety_provenance_auditor",
                task_type="audit_agent_output",
                ledger_ids=[],
                finding_ids=[],
            ),
        ],
        "human_review_required": True,
    }
    result = _run(payload)
    assert len(result.agent_outputs) == 2
    assert all(item.status in {AgentExecutionStatus.COMPLETED, AgentExecutionStatus.COMPLETED_WITH_WARNINGS} for item in result.agent_outputs)
    assert all(item.suggested_follow_up_agent_id is None for item in result.agent_outputs)
    assert result.recursive_spawning_used is False


def test_provider_failure_and_stale_session_remain_failures():
    payload, ids = _reviewed_payload()
    payload["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-PROVIDER-DOWN",
                agent_id="variant_database_evidence_agent",
                task_type="review_variant_database_evidence",
                ledger_ids=ids,
                provider={
                    "provider": "mock",
                    "model": "deterministic-specialist-fixture",
                    "provider_available": False,
                },
            ),
            _spawn(
                request_id="SPAWN-STALE",
                agent_id="variant_database_evidence_agent",
                task_type="review_variant_database_evidence",
                ledger_ids=ids,
                provider={
                    "provider": "openai_compatible",
                    "model": "external-model",
                    "external_llm_use_approved": True,
                    "session_valid": False,
                    "session_stale": True,
                    "provider_available": True,
                },
            ),
        ],
        "human_review_required": True,
    }
    result = _run(payload)
    assert all(item.status == AgentExecutionStatus.PROVIDER_UNAVAILABLE for item in result.spawn_decisions)
    assert result.agent_outputs == []
    assert result.external_llm_called is False


def test_mock_variant_agent_receives_only_allowlisted_ids_and_discloses_usage():
    payload, ids = _reviewed_payload()
    payload["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-VARIANT",
                agent_id="variant_database_evidence_agent",
                task_type="review_variant_database_evidence",
                ledger_ids=ids,
                structured_ids=["PH-1"],
            )
        ],
        "human_review_required": True,
    }
    result = _run(payload)
    envelope = result.task_envelopes[0]
    output = result.agent_outputs[0]
    assert envelope.allowed_fact_ids == ["PH-1"]
    assert envelope.allowed_finding_ids == ["FIND-SEQ-1"]
    assert envelope.allowed_ledger_entry_ids == ids
    assert envelope.structured_case_snapshot["raw_case_narrative_included"] is False
    assert envelope.structured_case_snapshot["raw_source_documents_included"] is False
    assert output.status == AgentExecutionStatus.COMPLETED
    assert output.proposal_status == "proposed_not_approved"
    assert output.human_review_required is True
    assert output.external_llm_called is False
    assert output.external_tools_executed is False
    assert output.provider == "mock"
    assert output.call_count == 0
    assert output.step_count == 1
    assert output.safety_review.passed is True
    assert result.review_ready_output_ids == [output.agent_output_id]


def test_gene_disease_literature_and_population_agents_preserve_boundaries():
    gene_records = [
        fixture_record(
            "REC-GENE-1",
            evidence_domain="gene_disease_validity",
            source_statement="The reviewed source reports supportive gene–disease validity evidence.",
            structured_observation={"stance": "supportive"},
        )
    ]
    gene_payload, gene_ids = _reviewed_payload(
        gene_records,
        source_type="gene_disease_validity_record",
    )
    gene_payload["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-GENE",
                agent_id="gene_disease_evidence_agent",
                task_type="review_gene_disease_evidence",
                ledger_ids=gene_ids,
            )
        ],
        "human_review_required": True,
    }
    gene_output = _run(gene_payload).agent_outputs[0]
    assert "without claiming that a gene explains the case" in gene_output.summary

    literature_records = [
        fixture_record(
            "REC-LIT-1",
            evidence_domain="functional_assay",
            source_statement="A synthetic functional observation was reported.",
            structured_observation={"study_type": "functional_study", "stance": "supportive"},
        )
    ]
    lit_payload, lit_ids = _reviewed_payload(
        literature_records,
        source_type="peer_reviewed_publication",
    )
    lit_payload["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-LIT",
                agent_id="literature_evidence_agent",
                task_type="review_literature_evidence",
                ledger_ids=lit_ids,
            )
        ],
        "human_review_required": True,
    }
    assert _run(lit_payload).agent_outputs[0].source_ledger_entry_ids == lit_ids

    no_records = workspace_payload(
        adapters=[
            fixture_adapter(
                [],
                source_type="population_frequency_record",
                source_name="PopulationFixture",
            )
        ],
        summaries=[],
    )
    no_records["result_evidence_workspace"]["retrieval_queries"][0]["evidence_source_selection"] = [
        "PopulationFixture"
    ]
    no_records["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-POP-NONE",
                agent_id="population_frequency_evidence_agent",
                task_type="review_population_frequency_evidence",
                ledger_ids=[],
            )
        ],
        "human_review_required": True,
    }
    population = _run(no_records).agent_outputs[0]
    assert population.status == AgentExecutionStatus.COMPLETED_WITH_WARNINGS
    assert "does not prove absence or rarity" in population.structured_observations[0].statement


def test_non_population_no_records_state_does_not_authorize_population_review():
    no_records = workspace_payload(
        adapters=[
            fixture_adapter(
                [],
                source_type="variant_database_record",
                source_name="VariantFixture",
            )
        ],
        summaries=[],
    )
    no_records["result_evidence_workspace"]["retrieval_queries"][0][
        "evidence_source_selection"
    ] = ["VariantFixture"]
    no_records["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-POP-WRONG-SOURCE",
                agent_id="population_frequency_evidence_agent",
                task_type="review_population_frequency_evidence",
                ledger_ids=[],
            )
        ],
        "human_review_required": True,
    }
    decision = _run(no_records).spawn_decisions[0]
    assert decision.status == AgentExecutionStatus.REQUIRES_RULE_REVIEW
    assert decision.rule_ids == ["AGENT-003"]


def test_ambiguous_normalization_blocks_candidate_task():
    payload = workspace_payload(summaries=[])
    payload["result_evidence_workspace"]["results"][0]["findings"][0]["sequence_variant"][
        "representations_equivalent"
    ] = False
    payload["result_evidence_workspace"]["results"][0]["findings"][0]["sequence_variant"][
        "alternate_source_representations"
    ] = ["NM_000001.2:c.10A>G", "NM_000001.2:c.11A>G"]
    payload["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-AMBIGUOUS",
                agent_id="candidate_acmg_evidence_agent",
                task_type="propose_candidate_acmg_evidence",
                ledger_ids=[],
            )
        ],
        "human_review_required": True,
    }
    decision = _run(payload).spawn_decisions[0]
    assert decision.status in {
        AgentExecutionStatus.BLOCKED_BY_POLICY,
        AgentExecutionStatus.REQUIRES_RULE_REVIEW,
    }
    assert "AGENT-004" in decision.rule_ids or "AGENT-003" in decision.rule_ids


def test_candidate_task_requires_explicit_requests_bounded_to_spawn_inputs():
    payload, ids = _reviewed_payload(
        [
            fixture_record(
                "REC-CAND-BOUND",
                evidence_domain="functional_assay",
                structured_observation={"stance": "supportive"},
            )
        ],
        source_type="functional_evidence_record",
    )
    spawn = _spawn(
        request_id="SPAWN-CAND-BOUND",
        agent_id="candidate_acmg_evidence_agent",
        task_type="propose_candidate_acmg_evidence",
        ledger_ids=ids,
    )
    payload["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [spawn],
        "human_review_required": True,
    }
    missing = _run(payload).spawn_decisions[0]
    assert missing.status == AgentExecutionStatus.REQUIRES_RULE_REVIEW
    assert missing.rule_ids == ["AGENT-INPUT-004"]

    payload["specialist_agent_workspace"]["candidate_requests"] = [
        {
            "candidate_request_id": "CAND-OUTSIDE-SPAWN",
            "spawn_request_id": "SPAWN-CAND-BOUND",
            "finding_id": "FIND-OUTSIDE-SPAWN",
            "criterion_code": "PS3",
            "criterion_family": "functional",
            "candidate_rule_id": "ACMG-CAND-BOUND",
            "candidate_rule_version": "0.33.0",
            "source_ledger_entry_ids": ids,
        }
    ]
    outside = _run(payload).spawn_decisions[0]
    assert outside.status == AgentExecutionStatus.REQUIRES_RULE_REVIEW
    assert outside.rule_ids == ["AGENT-INPUT-005"]


def _candidate_payload(*, missing=None, contradict=False) -> tuple[dict, list[str]]:
    records = [
        fixture_record(
            "REC-CAND-1",
            evidence_domain="functional_assay",
            source_statement="Synthetic source-supported functional observation.",
            structured_observation={"stance": "supportive"},
        )
    ]
    if contradict:
        records.append(
            fixture_record(
                "REC-CAND-2",
                source_identifier="SYNTHETIC:2",
                evidence_domain="functional_assay",
                source_statement="Synthetic source reports a contradictory functional observation.",
                structured_observation={"stance": "contradictory"},
                conflict_group_id="CG-CAND",
            )
        )
    payload, ids = _reviewed_payload(records, source_type="functional_evidence_record")
    payload["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-CAND",
                agent_id="candidate_acmg_evidence_agent",
                task_type="propose_candidate_acmg_evidence",
                ledger_ids=ids,
            )
        ],
        "candidate_requests": [
            {
                "candidate_request_id": "CAND-REQ-1",
                "spawn_request_id": "SPAWN-CAND",
                "finding_id": "FIND-SEQ-1",
                "criterion_code": "PS3",
                "criterion_family": "functional",
                "proposed_strength": "organizational_default_only",
                "candidate_rule_id": "ACMG-CAND-001",
                "candidate_rule_version": "0.33.0",
                "source_ledger_entry_ids": [ids[0]],
                "contradicting_ledger_entry_ids": [ids[1]] if contradict else [],
                "supporting_observations": ["Reviewed source-linked functional observation."],
                "missing_prerequisites": missing or [],
                "applicability_notes": ["Gene- and assay-specific review remains required."],
                "technical_limitations": ["Synthetic fixture only."],
            }
        ],
        "human_review_required": True,
    }
    return payload, ids


def test_candidate_acmg_items_remain_separate_candidate_only_and_source_linked():
    payload, ids = _candidate_payload()
    result = _run(payload)
    candidate = result.candidate_criteria[0]
    assert candidate.candidate_status == CandidateStatus.CANDIDATE_ONLY
    assert candidate.proposal_status == "proposed_not_approved"
    assert candidate.source_ledger_entry_ids == [ids[0]]
    assert candidate.human_review_required is True
    serialized = candidate.model_dump(mode="json")
    assert "pathogenicity_score" not in serialized
    assert "final_acmg_classification" not in serialized
    assert result.automatic_criterion_combination_used is False
    assert result.pathogenicity_score_calculated is False
    assert result.causality_claim_made is False


def test_candidate_missing_prerequisites_and_conflicting_support_are_conservative():
    insufficient_payload, _ = _candidate_payload(missing=["Validated assay context is missing."])
    insufficient = _run(insufficient_payload).candidate_criteria[0]
    assert insufficient.candidate_status == CandidateStatus.INSUFFICIENT_SUPPORT
    assert "Validated assay context is missing." in insufficient.missing_prerequisites

    conflicting_payload, _ = _candidate_payload(contradict=True)
    conflicting = _run(conflicting_payload).candidate_criteria[0]
    assert conflicting.candidate_status == CandidateStatus.CONFLICTING_SUPPORT
    assert conflicting.contradicting_ledger_entry_ids


def test_external_classification_alone_is_not_recreated_as_candidate():
    payload = workspace_payload(adapters=[], queries=[], summaries=[])
    payload["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-EXTERNAL-ONLY",
                agent_id="candidate_acmg_evidence_agent",
                task_type="propose_candidate_acmg_evidence",
                ledger_ids=[],
            )
        ],
        "candidate_requests": [
            {
                "candidate_request_id": "CAND-EXT",
                "spawn_request_id": "SPAWN-EXTERNAL-ONLY",
                "finding_id": "FIND-SEQ-1",
                "criterion_code": "PP5",
                "criterion_family": "external_assertion",
                "candidate_rule_id": "ACMG-CAND-004",
                "candidate_rule_version": "0.33.0",
                "source_ledger_entry_ids": [],
                "technical_limitations": ["External classification only."],
            }
        ],
        "human_review_required": True,
    }
    result = _run(payload)
    assert result.spawn_decisions[0].status == AgentExecutionStatus.REQUIRES_RULE_REVIEW
    assert result.candidate_criteria == []


def test_output_validator_rejects_unknown_sources_and_forbidden_conclusions():
    payload, _ = _candidate_payload()
    result = _run(payload)
    output = result.agent_outputs[0]
    envelope = result.task_envelopes[0]
    definition = next(item for item in result.approved_registry if item.agent_id == output.agent_id)
    workspace = build_clinical_case_result_evidence_bundle(payload)[6]
    ledger_by_id = {item.ledger_entry_id: item for item in workspace.ledger_entries}

    invalid_source = output.model_copy(
        update={"source_ledger_entry_ids": [*output.source_ledger_entry_ids, "LEDGER-NOT-FOUND"]}
    )
    checked = validate_agent_output(
        invalid_source,
        definition=definition,
        envelope=envelope,
        ledger_by_id=ledger_by_id,
    )
    assert checked.status == AgentExecutionStatus.INVALID_OUTPUT
    assert checked.safety_review.unsupported_source_references == ["LEDGER-NOT-FOUND"]

    forbidden = output.model_copy(update={"summary": "The final ACMG classification is pathogenic."})
    checked = validate_agent_output(
        forbidden,
        definition=definition,
        envelope=envelope,
        ledger_by_id=ledger_by_id,
    )
    assert checked.status == AgentExecutionStatus.BLOCKED_BY_POLICY
    assert "final_classification" in checked.safety_review.forbidden_language_matches


def test_output_validator_enforces_call_token_cost_step_and_runtime_limits():
    payload, _ = _candidate_payload()
    result = _run(payload)
    output = result.agent_outputs[0]
    envelope = result.task_envelopes[0]
    definition = next(item for item in result.approved_registry if item.agent_id == output.agent_id)
    workspace = build_clinical_case_result_evidence_bundle(payload)[6]
    ledger_by_id = {item.ledger_entry_id: item for item in workspace.ledger_entries}
    overages = (
        {"call_count": envelope.budget.maximum_calls + 1},
        {"token_usage": envelope.budget.maximum_tokens + 1},
        {"cost": envelope.budget.maximum_cost + 0.01},
        {"step_count": envelope.budget.maximum_steps + 1},
        {"runtime_seconds": envelope.budget.maximum_runtime_seconds + 0.01},
    )
    statuses = []
    for update in overages:
        checked = validate_agent_output(
            output.model_copy(update=update),
            definition=definition,
            envelope=envelope,
            ledger_by_id=ledger_by_id,
        )
        statuses.append(checked.status)
        assert checked.safety_review.budget_compliant is False
        assert "AGENT-005" in checked.safety_review.policy_rule_ids
    assert statuses[:4] == [AgentExecutionStatus.BUDGET_EXHAUSTED] * 4
    assert statuses[4] == AgentExecutionStatus.TIMED_OUT


def test_disagreement_preserves_outputs_without_majority_vote():
    records = [
        fixture_record(
            "REC-CONFLICT-A",
            source_identifier="SYNTHETIC:A",
            source_statement="Source A reports interpretation A.",
            structured_observation={"classification": "A"},
            conflict_group_id="CG-AGENT",
        ),
        fixture_record(
            "REC-CONFLICT-B",
            source_identifier="SYNTHETIC:B",
            source_statement="Source B reports interpretation B.",
            structured_observation={"classification": "B"},
            conflict_group_id="CG-AGENT",
        ),
    ]
    payload, ids = _reviewed_payload(records)
    interim = build_clinical_case_result_evidence_bundle(payload)[6]
    conflict_id = interim.ledger_entries[0].conflict_group_id
    payload["specialist_agent_workspace"] = {
        "schema_version": "0.33",
        "spawn_requests": [
            _spawn(
                request_id="SPAWN-CONFLICT-A",
                agent_id="variant_database_evidence_agent",
                task_type="review_variant_database_evidence",
                ledger_ids=[ids[0]],
            ),
            _spawn(
                request_id="SPAWN-CONFLICT-B",
                agent_id="evidence_conflict_reviewer",
                task_type="review_evidence_conflict",
                ledger_ids=[ids[1]],
                conflict_ids=[conflict_id],
            ),
        ],
        "human_review_required": True,
    }
    result = _run(payload)
    assert len(result.agent_outputs) == 2
    assert len(result.disagreement_groups) == 1
    group = result.disagreement_groups[0]
    assert group.majority_vote_used is False
    assert group.winning_agent_selected is False
    assert result.majority_vote_used is False


def test_human_review_actions_are_auditable_and_acceptance_is_discussion_only():
    payload, _ = _candidate_payload()
    first = _run(payload)
    candidate_id = first.candidate_criteria[0].candidate_criterion_id
    output_id = first.agent_outputs[0].agent_output_id
    reviewed = copy.deepcopy(payload)
    reviewed["specialist_agent_workspace"]["review_actions"] = [
        {
            "action_id": "REVIEW-OUTPUT",
            "action": "edit_agent_output",
            "target_type": "agent_output",
            "target_id": output_id,
            "reviewer_role": "clinical_research_reviewer",
            "reviewer_id": "reviewer",
            "timestamp": "2026-01-11T00:00:00Z",
            "before_value": {
                "summary": first.agent_outputs[0].summary,
                "human_review_status": "pending",
            },
            "after_value": {"summary": "Human-edited discussion summary."},
            "notes": "Edited for discussion.",
        },
        {
            "action_id": "REVIEW-CANDIDATE",
            "action": "accept_candidate_for_discussion",
            "target_type": "candidate_criterion",
            "target_id": candidate_id,
            "reviewer_role": "clinical_research_reviewer",
            "reviewer_id": "reviewer",
            "timestamp": "2026-01-12T00:00:00Z",
            "before_value": {
                "candidate_status": "candidate_only",
                "human_review_status": "pending",
            },
            "after_value": {
                "candidate_status": "accepted_for_discussion",
                "human_review_status": "accepted_for_discussion",
            },
        },
    ]
    result = _run(reviewed)
    output = result.agent_outputs[0]
    candidate = result.candidate_criteria[0]
    assert output.human_review_status == SpecialistReviewStatus.EDITED
    assert output.human_reviewed_summary == "Human-edited discussion summary."
    assert candidate.candidate_status == CandidateStatus.ACCEPTED_FOR_DISCUSSION
    assert candidate.proposal_status == "proposed_not_approved"
    assert len(result.reproducibility.human_review_actions) == 2
    assert result.review_actions[0].before_value
    assert result.review_actions[0].after_value


def test_output_and_candidate_review_transitions_remain_non_final_and_auditable():
    payload, _ = _candidate_payload()
    first = _run(payload)
    output_id = first.agent_outputs[0].agent_output_id
    candidate_id = first.candidate_criteria[0].candidate_criterion_id

    output_expectations = {
        "accept_agent_output_for_discussion": SpecialistReviewStatus.ACCEPTED_FOR_DISCUSSION,
        "defer_agent_output": SpecialistReviewStatus.DEFERRED,
        "request_more_information": SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
    }
    for index, (action_name, expected_status) in enumerate(
        output_expectations.items(), 1
    ):
        reviewed = copy.deepcopy(payload)
        reviewed["specialist_agent_workspace"]["review_actions"] = [
            {
                "action_id": f"OUTPUT-TRANSITION-{index}",
                "action": action_name,
                "target_type": "agent_output",
                "target_id": output_id,
                "reviewer_role": "clinical_research_reviewer",
                "timestamp": f"2026-02-{index:02d}T00:00:00Z",
                "before_value": {"human_review_status": "pending"},
                "after_value": {"human_review_status": expected_status.value},
            }
        ]
        result = _run(reviewed)
        assert result.agent_outputs[0].human_review_status == expected_status
        assert result.agent_outputs[0].proposal_status == "proposed_not_approved"
        if expected_status in {
            SpecialistReviewStatus.DEFERRED,
            SpecialistReviewStatus.MORE_INFORMATION_REQUESTED,
        }:
            assert result.review_ready_output_ids == []
            assert result.candidate_criteria == []

    rejected = copy.deepcopy(payload)
    rejected["specialist_agent_workspace"]["review_actions"] = [
        {
            "action_id": "OUTPUT-REJECTED",
            "action": "reject_agent_output",
            "target_type": "agent_output",
            "target_id": output_id,
            "reviewer_role": "clinical_research_reviewer",
            "timestamp": "2026-02-04T00:00:00Z",
            "before_value": {"human_review_status": "pending"},
            "after_value": {"human_review_status": "rejected"},
        }
    ]
    rejected_result = _run(rejected)
    assert rejected_result.agent_outputs[0].human_review_status == SpecialistReviewStatus.REJECTED
    assert rejected_result.review_ready_output_ids == []
    assert rejected_result.candidate_criteria == []
    assert rejected_result.reproducibility.human_review_actions

    candidate_expectations = {
        "edit_candidate": (CandidateStatus.CANDIDATE_ONLY, SpecialistReviewStatus.EDITED),
        "reject_candidate": (CandidateStatus.REJECTED_BY_REVIEWER, SpecialistReviewStatus.REJECTED),
        "mark_candidate_not_applicable": (CandidateStatus.NOT_APPLICABLE, SpecialistReviewStatus.NOT_APPLICABLE),
        "mark_candidate_conflicting": (CandidateStatus.CONFLICTING_SUPPORT, SpecialistReviewStatus.CONFLICTING),
        "defer_candidate": (CandidateStatus.DEFERRED, SpecialistReviewStatus.DEFERRED),
    }
    for index, (action_name, expected) in enumerate(candidate_expectations.items(), 5):
        reviewed = copy.deepcopy(payload)
        action = {
            "action_id": f"CANDIDATE-TRANSITION-{index}",
            "action": action_name,
            "target_type": "candidate_criterion",
            "target_id": candidate_id,
            "reviewer_role": "clinical_research_reviewer",
            "timestamp": f"2026-02-{index:02d}T00:00:00Z",
            "before_value": {
                "candidate_status": "candidate_only",
                "human_review_status": "pending",
            },
            "after_value": {
                "candidate_status": expected[0].value,
                "human_review_status": expected[1].value,
            },
        }
        if action_name == "edit_candidate":
            action["before_value"] = {
                "applicability_notes": first.candidate_criteria[0].applicability_notes,
                "human_review_status": "pending",
            }
            action["after_value"] = {
                "applicability_notes": ["Human-edited discussion note."]
            }
        reviewed["specialist_agent_workspace"]["review_actions"] = [action]
        result = _run(reviewed)
        candidate = result.candidate_criteria[0]
        assert (candidate.candidate_status, candidate.human_review_status) == expected
        assert candidate.proposal_status == "proposed_not_approved"


def test_external_acmg_assessment_remains_external():
    payload, _ = _candidate_payload()
    payload["specialist_agent_workspace"]["external_acmg_assessments"] = [
        {
            "external_assessment_id": "EXT-ACMG-1",
            "finding_id": "FIND-SEQ-1",
            "external_acmg_assessment_recorded": True,
            "external_source": "Synthetic external laboratory",
            "external_assessment_date": "2026-01-09",
            "external_criteria_as_reported": ["PS3"],
            "external_classification_as_reported": "uncertain significance",
            "verification_status": "unreviewed",
            "source_document_id": "DOC-1",
            "reviewer_notes": "Transcribed for review.",
        }
    ]
    assessment = _run(payload).external_acmg_assessments[0]
    assert assessment.required_wording == "External ACMG assessment recorded; not assigned by InSilicoPop."
    assert assessment.external_classification_as_reported == "uncertain significance"
