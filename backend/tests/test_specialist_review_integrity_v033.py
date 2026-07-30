from __future__ import annotations

import copy
import hashlib
import json

import pytest

from app.insilicopop.clinical.specialist_agent_models import (
    CandidateStatus,
    SpecialistReviewStatus,
)
from backend.tests.test_specialist_agents_v033 import (
    _candidate_payload,
    _run,
)


def _action(
    *,
    action_id: str,
    action: str,
    target_type: str,
    target_id: str,
    before=None,
    after=None,
    timestamp: str = "2026-03-01T00:00:00Z",
) -> dict:
    return {
        "action_id": action_id,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "reviewer_role": "clinical_research_reviewer",
        "reviewer_id": "reviewer",
        "timestamp": timestamp,
        "before_value": before,
        "after_value": after,
    }


def _candidate_context():
    payload, _ = _candidate_payload()
    first = _run(payload)
    return (
        payload,
        first,
        first.agent_outputs[0].agent_output_id,
        first.candidate_criteria[0].candidate_criterion_id,
    )


@pytest.mark.parametrize(
    ("target_type", "action_name", "target_id", "before", "after"),
    [
        (
            "spawn_request",
            "approve_agent_task",
            "SPAWN-DOES-NOT-EXIST",
            {"human_review_status": "pending"},
            {"human_review_status": "approved"},
        ),
        (
            "agent_output",
            "accept_agent_output_for_discussion",
            "OUTPUT-DOES-NOT-EXIST",
            {"human_review_status": "pending"},
            {"human_review_status": "accepted_for_discussion"},
        ),
        (
            "candidate_criterion",
            "edit_candidate",
            "CANDIDATE-DOES-NOT-EXIST",
            {"supporting_observations": []},
            {"supporting_observations": ["Bounded note."]},
        ),
    ],
)
def test_unknown_targets_are_rejected_without_mutation(
    target_type, action_name, target_id, before, after
):
    payload, first, _, _ = _candidate_context()
    reviewed = copy.deepcopy(payload)
    reviewed["specialist_agent_workspace"]["review_actions"] = [
        _action(
            action_id=f"UNKNOWN-{target_type}",
            action=action_name,
            target_type=target_type,
            target_id=target_id,
            before=before,
            after=after,
        )
    ]

    result = _run(reviewed)

    assert result.applied_review_actions == []
    assert result.agent_outputs == first.agent_outputs
    assert result.candidate_criteria == first.candidate_criteria
    assert result.review_ready_output_ids == first.review_ready_output_ids
    audit = result.review_action_results[0]
    assert audit.result_status.value == "rejected"
    assert audit.rejection_reason.value == "target_not_found"
    assert audit.authoritative_before is None
    assert audit.validated_after is None


@pytest.mark.parametrize(
    ("action_name", "target_type", "target_selector"),
    [
        ("edit_candidate", "agent_output", "output"),
        ("accept_agent_output_for_discussion", "spawn_request", "spawn"),
        ("cancel_agent_task", "candidate_criterion", "candidate"),
    ],
)
def test_action_target_incompatibility_is_explicitly_rejected(
    action_name, target_type, target_selector
):
    payload, first, output_id, candidate_id = _candidate_context()
    target_id = {
        "output": output_id,
        "spawn": "SPAWN-CAND",
        "candidate": candidate_id,
    }[target_selector]
    reviewed = copy.deepcopy(payload)
    reviewed["specialist_agent_workspace"]["review_actions"] = [
        _action(
            action_id=f"INCOMPATIBLE-{target_selector}",
            action=action_name,
            target_type=target_type,
            target_id=target_id,
            before={"human_review_status": "pending"},
            after={"human_review_status": "edited"},
        )
    ]

    result = _run(reviewed)

    assert result.applied_review_actions == []
    assert result.agent_outputs == first.agent_outputs
    assert result.candidate_criteria == first.candidate_criteria
    assert (
        result.review_action_results[0].rejection_reason.value
        == "action_target_mismatch"
    )


def test_same_textual_id_across_target_types_is_collision_safe():
    payload, _ = _candidate_payload()
    payload["specialist_agent_workspace"]["external_acmg_assessments"] = [
        {
            "external_assessment_id": "SPAWN-CAND",
            "finding_id": "FIND-SEQ-1",
            "external_acmg_assessment_recorded": True,
            "external_source": "Synthetic external source",
            "verification_status": "unreviewed",
        }
    ]
    payload["specialist_agent_workspace"]["review_actions"] = [
        _action(
            action_id="COLLISION-EXTERNAL",
            action="record_external_acmg_assessment",
            target_type="external_acmg_assessment",
            target_id="SPAWN-CAND",
        )
    ]

    result = _run(payload)

    assert result.spawn_decisions[0].status.value == "ready"
    assert result.applied_review_actions[0].target_type == "external_acmg_assessment"
    assert result.review_action_results[0].result_status.value == "applied"


def test_external_assessment_record_action_rejects_mutation_payload():
    payload, _ = _candidate_payload()
    payload["specialist_agent_workspace"]["external_acmg_assessments"] = [
        {
            "external_assessment_id": "EXTERNAL-REVIEW-1",
            "finding_id": "FIND-SEQ-1",
            "external_acmg_assessment_recorded": True,
            "external_source": "Synthetic external source",
            "verification_status": "unreviewed",
        }
    ]
    payload["specialist_agent_workspace"]["review_actions"] = [
        _action(
            action_id="EXTERNAL-MUTATION-REJECTED",
            action="record_external_classification",
            target_type="external_acmg_assessment",
            target_id="EXTERNAL-REVIEW-1",
            after={"verification_status": "accepted_for_discussion"},
        )
    ]

    result = _run(payload)

    assert result.applied_review_actions == []
    audit = result.review_action_results[0]
    assert audit.rejection_reason.value == "invalid_edit_payload"
    assert audit.validation_categories == ["unsupported_edit_payload"]
    assert result.external_acmg_assessments[0].verification_status.value == "unreviewed"


def test_stale_and_invalid_output_transitions_preserve_current_state():
    payload, _, output_id, _ = _candidate_context()
    reviewed = copy.deepcopy(payload)
    reviewed["specialist_agent_workspace"]["review_actions"] = [
        _action(
            action_id="OUTPUT-MORE-INFO",
            action="request_more_information",
            target_type="agent_output",
            target_id=output_id,
            before={"human_review_status": "pending"},
            after={"human_review_status": "more_information_requested"},
            timestamp="2026-03-01T00:00:00Z",
        ),
        _action(
            action_id="OUTPUT-STALE-REJECT",
            action="reject_agent_output",
            target_type="agent_output",
            target_id=output_id,
            before={"human_review_status": "pending"},
            after={"human_review_status": "rejected"},
            timestamp="2026-03-02T00:00:00Z",
        ),
        _action(
            action_id="OUTPUT-INVALID-ACCEPT",
            action="accept_agent_output_for_discussion",
            target_type="agent_output",
            target_id=output_id,
            before={"human_review_status": "more_information_requested"},
            after={"human_review_status": "accepted_for_discussion"},
            timestamp="2026-03-03T00:00:00Z",
        ),
    ]

    result = _run(reviewed)

    assert (
        result.agent_outputs[0].human_review_status
        == SpecialistReviewStatus.MORE_INFORMATION_REQUESTED
    )
    assert result.review_ready_output_ids == []
    assert result.candidate_criteria == []
    assert [item.result_status.value for item in result.review_action_results] == [
        "applied",
        "rejected",
        "rejected",
    ]
    assert [
        item.rejection_reason.value if item.rejection_reason else None
        for item in result.review_action_results
    ] == [None, "before_value_mismatch", "invalid_transition"]


def test_repeated_terminal_transition_and_missing_before_are_rejected():
    payload, _, output_id, _ = _candidate_context()
    reviewed = copy.deepcopy(payload)
    reviewed["specialist_agent_workspace"]["review_actions"] = [
        _action(
            action_id="OUTPUT-REJECT-FIRST",
            action="reject_agent_output",
            target_type="agent_output",
            target_id=output_id,
            before={"human_review_status": "pending"},
            after={"human_review_status": "rejected"},
            timestamp="2026-03-01T00:00:00Z",
        ),
        _action(
            action_id="OUTPUT-REJECT-AGAIN",
            action="reject_agent_output",
            target_type="agent_output",
            target_id=output_id,
            before={"human_review_status": "rejected"},
            after={"human_review_status": "rejected"},
            timestamp="2026-03-02T00:00:00Z",
        ),
        _action(
            action_id="OUTPUT-MISSING-BEFORE",
            action="defer_agent_output",
            target_type="agent_output",
            target_id=output_id,
            after={"human_review_status": "deferred"},
            timestamp="2026-03-03T00:00:00Z",
        ),
    ]

    result = _run(reviewed)

    assert result.agent_outputs[0].human_review_status == SpecialistReviewStatus.REJECTED
    assert result.candidate_criteria == []
    assert [item.rejection_reason.value for item in result.review_action_results[1:]] == [
        "invalid_transition",
        "before_value_required",
    ]


def test_deferred_candidate_cannot_be_edited():
    payload, _, _, candidate_id = _candidate_context()
    reviewed = copy.deepcopy(payload)
    reviewed["specialist_agent_workspace"]["review_actions"] = [
        _action(
            action_id="CANDIDATE-DEFER",
            action="defer_candidate",
            target_type="candidate_criterion",
            target_id=candidate_id,
            before={"candidate_status": "candidate_only"},
            after={"candidate_status": "deferred"},
            timestamp="2026-03-01T00:00:00Z",
        ),
        _action(
            action_id="CANDIDATE-EDIT-DEFERRED",
            action="edit_candidate",
            target_type="candidate_criterion",
            target_id=candidate_id,
            before={
                "applicability_notes": ["Gene- and assay-specific review remains required."],
                "human_review_status": "deferred",
            },
            after={"applicability_notes": ["Should not be applied."]},
            timestamp="2026-03-02T00:00:00Z",
        ),
    ]

    result = _run(reviewed)

    assert result.candidate_criteria[0].candidate_status == CandidateStatus.DEFERRED
    assert result.review_action_results[1].rejection_reason.value == "invalid_transition"


@pytest.mark.parametrize(
    ("edit", "before", "expected_category"),
    [
        (
            {"supporting_observations": "not-a-list"},
            {"supporting_observations": ["Reviewed source-linked functional observation."]},
            "list_type",
        ),
        (
            {"proposed_strength": "x" * 81},
            {"proposed_strength": "organizational_default_only"},
            "string_too_long",
        ),
        (
            {"candidate_status": "unsupported_enum"},
            {"candidate_status": "candidate_only"},
            "unsupported_edit_field",
        ),
        (
            {"source_ledger_entry_ids": ["MALFORMED-NOT-ALLOWED"]},
            {"source_ledger_entry_ids": []},
            "unsupported_edit_field",
        ),
        (
            {"unknown_field": "value"},
            {"unknown_field": None},
            "unsupported_edit_field",
        ),
    ],
)
def test_malformed_candidate_edits_are_atomic(edit, before, expected_category):
    payload, first, _, candidate_id = _candidate_context()
    reviewed = copy.deepcopy(payload)
    reviewed["specialist_agent_workspace"]["review_actions"] = [
        _action(
            action_id=f"INVALID-EDIT-{expected_category}",
            action="edit_candidate",
            target_type="candidate_criterion",
            target_id=candidate_id,
            before={**before, "human_review_status": "pending"},
            after=edit,
        )
    ]

    result = _run(reviewed)

    assert result.candidate_criteria == first.candidate_criteria
    assert result.applied_review_actions == []
    audit = result.review_action_results[0]
    assert audit.rejection_reason.value == "invalid_edit_payload"
    assert expected_category in audit.validation_categories
    assert audit.validated_after is None


def test_multi_field_and_forbidden_candidate_edits_are_atomic():
    payload, first, _, candidate_id = _candidate_context()
    reviewed = copy.deepcopy(payload)
    original = first.candidate_criteria[0]
    reviewed["specialist_agent_workspace"]["review_actions"] = [
        _action(
            action_id="CANDIDATE-MULTI-INVALID",
            action="edit_candidate",
            target_type="candidate_criterion",
            target_id=candidate_id,
            before={
                "proposed_strength": original.proposed_strength,
                "supporting_observations": original.supporting_observations,
                "human_review_status": "pending",
            },
            after={
                "proposed_strength": "bounded",
                "supporting_observations": "invalid-scalar",
            },
            timestamp="2026-03-01T00:00:00Z",
        ),
        _action(
            action_id="CANDIDATE-FORBIDDEN",
            action="edit_candidate",
            target_type="candidate_criterion",
            target_id=candidate_id,
            before={
                "gene_disease_context": original.gene_disease_context,
                "human_review_status": "pending",
            },
            after={"gene_disease_context": "The variant is pathogenic."},
            timestamp="2026-03-02T00:00:00Z",
        ),
    ]

    result = _run(reviewed)

    assert result.candidate_criteria == first.candidate_criteria
    assert [item.rejection_reason.value for item in result.review_action_results] == [
        "invalid_edit_payload",
        "forbidden_edit",
    ]


def test_valid_candidate_and_output_edits_are_fully_validated_and_audited():
    payload, first, output_id, candidate_id = _candidate_context()
    candidate = first.candidate_criteria[0]
    output = first.agent_outputs[0]
    reviewed = copy.deepcopy(payload)
    reviewed["specialist_agent_workspace"]["review_actions"] = [
        _action(
            action_id="OUTPUT-EDIT-VALID",
            action="edit_agent_output",
            target_type="agent_output",
            target_id=output_id,
            before={
                "summary": output.summary,
                "human_review_status": "pending",
            },
            after={"summary": "Human-reviewed discussion summary."},
            timestamp="2026-03-01T00:00:00Z",
        ),
        _action(
            action_id="CANDIDATE-EDIT-VALID",
            action="edit_candidate",
            target_type="candidate_criterion",
            target_id=candidate_id,
            before={
                "applicability_notes": candidate.applicability_notes,
                "proposed_strength": candidate.proposed_strength,
                "human_review_status": "pending",
            },
            after={
                "applicability_notes": ["Bounded human-review note."],
                "proposed_strength": "discussion_only",
            },
            timestamp="2026-03-02T00:00:00Z",
        ),
    ]

    result = _run(reviewed)

    assert result.agent_outputs[0].human_reviewed_summary == (
        "Human-reviewed discussion summary."
    )
    assert result.agent_outputs[0].human_review_status == SpecialistReviewStatus.EDITED
    assert result.agent_outputs[0].safety_review.passed is True
    assert result.candidate_criteria[0].proposed_strength == "discussion_only"
    assert result.candidate_criteria[0].human_review_status == SpecialistReviewStatus.EDITED
    assert len(result.applied_review_actions) == 2
    assert all(item.validated_after for item in result.review_action_results)
    assert result.review_action_results[0].authoritative_before["summary"] == output.summary


@pytest.mark.parametrize(
    "summary",
    [
        "The variant is pathogenic.",
        "x" * 4001,
    ],
)
def test_invalid_output_edits_are_rejected_without_mutation(summary):
    payload, first, output_id, _ = _candidate_context()
    reviewed = copy.deepcopy(payload)
    reviewed["specialist_agent_workspace"]["review_actions"] = [
        _action(
            action_id="OUTPUT-EDIT-INVALID",
            action="edit_agent_output",
            target_type="agent_output",
            target_id=output_id,
            before={
                "summary": first.agent_outputs[0].summary,
                "human_review_status": "pending",
            },
            after={"summary": summary},
        )
    ]

    result = _run(reviewed)

    assert result.agent_outputs == first.agent_outputs
    assert result.applied_review_actions == []
    assert result.review_action_results[0].result_status.value == "rejected"
    assert result.review_action_results[0].validated_after is None


def test_output_edit_cannot_change_sources_or_fabricate_approval():
    payload, first, output_id, _ = _candidate_context()
    reviewed = copy.deepcopy(payload)
    reviewed["specialist_agent_workspace"]["review_actions"] = [
        _action(
            action_id="OUTPUT-EDIT-UNSUPPORTED-FIELDS",
            action="edit_agent_output",
            target_type="agent_output",
            target_id=output_id,
            before={
                "summary": first.agent_outputs[0].summary,
                "human_review_status": "pending",
            },
            after={
                "summary": "Human-reviewed discussion summary.",
                "source_ledger_entry_ids": ["LEDGER-FABRICATED"],
                "proposal_status": "approved",
            },
        )
    ]

    result = _run(reviewed)

    assert result.agent_outputs == first.agent_outputs
    assert result.applied_review_actions == []
    audit = result.review_action_results[0]
    assert audit.rejection_reason.value == "invalid_edit_payload"
    assert audit.validation_categories == ["unsupported_edit_field"]


def test_review_audit_serialization_is_deterministic_and_separated():
    payload, _, output_id, _ = _candidate_context()
    payload["specialist_agent_workspace"]["review_actions"] = [
        _action(
            action_id="AUDIT-APPLIED",
            action="accept_agent_output_for_discussion",
            target_type="agent_output",
            target_id=output_id,
            before={"human_review_status": "pending"},
            after={"human_review_status": "accepted_for_discussion"},
            timestamp="2026-03-01T00:00:00Z",
        ),
        _action(
            action_id="AUDIT-REJECTED",
            action="reject_agent_output",
            target_type="agent_output",
            target_id="OUTPUT-MISSING",
            before={"human_review_status": "pending"},
            after={"human_review_status": "rejected"},
            timestamp="2026-03-02T00:00:00Z",
        ),
    ]

    first = _run(copy.deepcopy(payload))
    second = _run(copy.deepcopy(payload))
    first_json = json.dumps(
        first.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    second_json = json.dumps(
        second.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )

    assert first_json == second_json
    assert hashlib.sha256(first_json.encode()).hexdigest() == hashlib.sha256(
        second_json.encode()
    ).hexdigest()
    assert [item.action_id for item in first.applied_review_actions] == ["AUDIT-APPLIED"]
    assert [item.result_status.value for item in first.review_action_results] == [
        "applied",
        "rejected",
    ]
    assert first.reproducibility.applied_human_review_actions[0]["action_id"] == (
        "AUDIT-APPLIED"
    )
    assert first.reproducibility.human_review_action_results[1][
        "rejection_reason"
    ] == "target_not_found"
