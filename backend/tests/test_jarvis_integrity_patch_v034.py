from __future__ import annotations

import copy

import pytest

from app.insilicopop.clinical import build_clinical_case_v034_bundle
from app.insilicopop.clinical.jarvis_report import (
    _forbidden_matches,
    _run_critics,
    build_jarvis_synthesis_report_workspace,
)
from app.insilicopop.clinical.models import ClinicalCaseIntake
from app.insilicopop.clinical.result_evidence_models import HumanReviewStatus
from backend.tests.test_jarvis_synthesis_report_v034 import _payload


def _source_bundle(payload: dict | None = None):
    payload = copy.deepcopy(payload or _payload())
    return payload, build_clinical_case_v034_bundle(payload)


def _build_with_entries(entries, *, payload: dict | None = None):
    payload, bundle = _source_bundle(payload)
    ledger = bundle[6].model_copy(update={"ledger_entries": list(entries)})
    workspace = build_jarvis_synthesis_report_workspace(
        ClinicalCaseIntake.model_validate(payload),
        intake=bundle[0],
        phenotype_curation=bundle[1],
        pedigree_audit=bundle[2],
        variant_intelligence=bundle[3],
        pretest_assessment=bundle[4],
        test_strategy_workspace=bundle[5],
        result_evidence_workspace=ledger,
        specialist_agent_workspace=bundle[7],
    )
    return workspace, ledger, bundle[7]


def _accepted_entry(**updates):
    _, bundle = _source_bundle()
    return bundle[6].ledger_entries[0].model_copy(
        update={
            "human_review_status": HumanReviewStatus.ACCEPTED_INTO_WORKSPACE,
            **updates,
        }
    )


@pytest.mark.parametrize(
    ("updates", "decision", "reason"),
    [
        ({"withdrawn_or_updated": True}, "quarantined", "withdrawn_record"),
        ({"applicability_status": "retracted"}, "quarantined", "retracted_record"),
        ({"applicability_status": "invalid"}, "excluded", "invalid_record"),
        ({"applicability_status": "stale"}, "context_only", "stale_record_context_only"),
        (
            {"applicability_status": "corrected"},
            "context_only",
            "corrected_record_context_only",
        ),
        (
            {"superseded_by": "LEDGER-SUCCESSOR"},
            "quarantined",
            "superseded_record",
        ),
        (
            {"applicability_status": "context_only"},
            "context_only",
            "stale_record_context_only",
        ),
    ],
)
def test_lifecycle_records_are_quarantined_from_factual_narrative(
    updates, decision, reason
):
    entry = _accepted_entry(**updates)
    workspace, _, _ = _build_with_entries([entry])
    eligibility = next(
        item
        for item in workspace.eligibility_decisions
        if item.input_artifact_id == entry.ledger_entry_id
    )
    assert eligibility.decision.value == decision
    assert eligibility.reason_code.value == reason
    linked_claims = [
        item
        for item in workspace.synthesis_claims
        if entry.ledger_entry_id
        in (
            item.supporting_evidence_ids
            + item.contradicting_evidence_ids
            + item.unresolved_evidence_ids
        )
    ]
    assert linked_claims
    assert all(not item.eligible_for_report for item in linked_claims)
    assert all(item.report_use == "context_only" for item in linked_claims)
    factual_sections = [
        item
        for item in workspace.report_sections
        if item.section_type not in {"limitations", "critic_findings"}
    ]
    assert all(entry.ledger_entry_id not in item.citation_ids for item in factual_sections)
    limitations = next(
        item for item in workspace.report_sections if item.section_type == "limitations"
    )
    assert entry.ledger_entry_id in limitations.citation_ids
    assert reason in limitations.narrative


def test_active_successor_is_eligible_while_superseded_record_is_context_only():
    old = _accepted_entry(
        ledger_entry_id="LEDGER-OLD",
        superseded_by="LEDGER-NEW",
    )
    new = _accepted_entry(
        ledger_entry_id="LEDGER-NEW",
        newer_version_of="LEDGER-OLD",
        supersedes_source_record="LEDGER-OLD",
        source_version="2",
        source_statement="Corrected current source observation.",
    )
    workspace, _, _ = _build_with_entries([old, new])
    by_id = {
        item.input_artifact_id: item for item in workspace.eligibility_decisions
    }
    assert by_id["LEDGER-OLD"].reason_code.value == "superseded_record"
    assert by_id["LEDGER-OLD"].linked_successor_id == "LEDGER-NEW"
    assert by_id["LEDGER-NEW"].decision.value == "eligible"
    assert (
        "evidence_ledger_entry:LEDGER-NEW"
        in workspace.reproducibility.eligible_input_ids
    )
    assert (
        "evidence_ledger_entry:LEDGER-OLD"
        in workspace.reproducibility.excluded_input_ids
    )


def test_evidence_roles_and_reproducibility_are_separate_and_stable():
    supporting = _accepted_entry(
        ledger_entry_id="LEDGER-SUPPORT",
        structured_observation={"stance": "supportive"},
    )
    contradicting = _accepted_entry(
        ledger_entry_id="LEDGER-CONTRADICT",
        structured_observation={"stance": "contradictory"},
    )
    unresolved = _accepted_entry(
        ledger_entry_id="LEDGER-UNRESOLVED",
        structured_observation={"stance": "unknown"},
    )
    first, _, _ = _build_with_entries([unresolved, supporting, contradicting])
    second, _, _ = _build_with_entries([contradicting, unresolved, supporting])
    role_claims = {
        evidence_id: next(
            item
            for item in first.synthesis_claims
            if evidence_id
            in (
                item.supporting_evidence_ids
                + item.contradicting_evidence_ids
                + item.unresolved_evidence_ids
            )
            and item.origin_category.value == "retrieved_source_claim"
        )
        for evidence_id in {
            "LEDGER-SUPPORT",
            "LEDGER-CONTRADICT",
            "LEDGER-UNRESOLVED",
        }
    }
    assert role_claims["LEDGER-SUPPORT"].supporting_evidence_ids == ["LEDGER-SUPPORT"]
    assert role_claims["LEDGER-CONTRADICT"].contradicting_evidence_ids == [
        "LEDGER-CONTRADICT"
    ]
    assert role_claims["LEDGER-UNRESOLVED"].unresolved_evidence_ids == [
        "LEDGER-UNRESOLVED"
    ]
    assert first.reproducibility.evidence_role_mappings
    assert first.reproducibility.provider_context["provider"] == "deterministic"
    assert first.reproducibility.budget_context["external_call_budget"] == 0
    assert first.reproducibility.deterministic_fallback_used is True
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.reproducibility.workspace_hash == second.reproducibility.workspace_hash


def test_proposed_claim_records_dangling_and_excluded_reuse_reasons():
    withdrawn = _accepted_entry(withdrawn_or_updated=True)
    payload = _payload()
    payload["jarvis_synthesis_report_workspace"]["proposed_claims"] = [
        {
            "proposal_id": "PROPOSAL-REUSE",
            "statement": "Proposal remains unapproved.",
            "supporting_evidence_ids": [withdrawn.ledger_entry_id],
        },
        {
            "proposal_id": "PROPOSAL-DANGLING",
            "statement": "Unknown proposal remains unapproved.",
            "supporting_evidence_ids": ["LEDGER-UNKNOWN"],
        },
    ]
    workspace, _, _ = _build_with_entries([withdrawn], payload=payload)
    reasons = {
        item.input_artifact_id: item.reason_code.value
        for item in workspace.eligibility_decisions
        if item.input_artifact_type == "proposed_synthesis_claim"
    }
    assert reasons == {
        "PROPOSAL-DANGLING": "unknown_reference",
        "PROPOSAL-REUSE": "excluded_record_reuse_attempt",
    }
    assert all(not item.eligible_for_report for item in workspace.excluded_proposed_claims)


def _review_action(action_id, action, section, before, after, timestamp):
    return {
        "action_id": action_id,
        "action": action,
        "target_type": "report_section",
        "target_id": section.section_id,
        "reviewer_role": "clinical_research_reviewer",
        "timestamp": timestamp,
        "before_value": before,
        "after_value": after,
        "notes": action_id,
    }


@pytest.mark.parametrize(
    ("first_action", "first_status", "second_action", "second_status"),
    [
        ("accept", "accepted", "accept", "accepted"),
        ("reject", "rejected", "accept", "accepted"),
        ("reject", "rejected", "edit", "edited"),
        ("defer", "deferred", "accept", "accepted"),
        ("defer", "deferred", "edit", "edited"),
        ("reject", "rejected", "reject", "rejected"),
        ("defer", "deferred", "defer", "deferred"),
    ],
)
def test_terminal_report_transitions_are_rejected_atomically(
    first_action, first_status, second_action, second_status
):
    payload = _payload()
    initial = build_clinical_case_v034_bundle(payload)[8]
    section = initial.report_sections[0]
    before = section.model_dump(mode="json")
    after_first = copy.deepcopy(before)
    after_first["human_review_status"] = first_status
    after_first["reviewer_notes"] = "FIRST"
    after_second = copy.deepcopy(after_first)
    after_second["human_review_status"] = second_status
    after_second["reviewer_notes"] = "SECOND"
    if second_action == "edit":
        after_second["title"] = "Bounded edited title"
    payload["jarvis_synthesis_report_workspace"]["review_actions"] = [
        _review_action(
            "FIRST",
            first_action,
            section,
            before,
            after_first,
            "2026-07-30T10:00:00Z",
        ),
        _review_action(
            "SECOND",
            second_action,
            section,
            after_first,
            after_second,
            "2026-07-30T10:01:00Z",
        ),
    ]
    result = build_clinical_case_v034_bundle(payload)[8]
    assert result.review_action_results[0].result_status.value == "applied"
    rejected = result.review_action_results[1]
    assert rejected.result_status.value == "rejected"
    assert rejected.rejection_reason.value == "invalid_transition"
    assert rejected.validated_after is None
    assert [item.action_id for item in result.applied_review_actions] == ["FIRST"]
    final = next(item for item in result.report_sections if item.section_id == section.section_id)
    assert final.human_review_status.value == first_status


@pytest.mark.parametrize(
    ("action", "status"),
    [
        ("accept", "accepted"),
        ("reject", "rejected"),
        ("defer", "deferred"),
        ("request_more_information", "more_information_requested"),
    ],
)
def test_allowed_pending_non_edit_transitions_apply(action, status):
    payload = _payload()
    initial = build_clinical_case_v034_bundle(payload)[8]
    section = initial.report_sections[0]
    before = section.model_dump(mode="json")
    after = copy.deepcopy(before)
    after["human_review_status"] = status
    after["reviewer_notes"] = f"ACTION-{action.upper()}"
    payload["jarvis_synthesis_report_workspace"]["review_actions"] = [
        _review_action(
            f"ACTION-{action.upper()}",
            action,
            section,
            before,
            after,
            "2026-07-30T11:00:00Z",
        )
    ]
    result = build_clinical_case_v034_bundle(payload)[8]
    assert result.review_action_results[0].result_status.value == "applied"
    assert result.report_sections[0].human_review_status.value == status


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing_before", "before_value_required"),
        ("stale_before", "before_value_mismatch"),
        ("incorrect_after", "after_value_mismatch"),
        ("unknown_target", "target_not_found"),
        ("target_type_collision", "target_type_mismatch"),
        ("malformed_edit", "invalid_edit_payload"),
    ],
)
def test_invalid_review_shapes_are_rejected_without_authoritative_mutation(
    mutation, reason
):
    payload = _payload()
    initial = build_clinical_case_v034_bundle(payload)[8]
    section = initial.report_sections[0]
    before = section.model_dump(mode="json")
    after = copy.deepcopy(before)
    after["human_review_status"] = "accepted"
    action = _review_action(
        "INVALID-SHAPE",
        "accept",
        section,
        before,
        after,
        "2026-07-30T12:00:00Z",
    )
    if mutation == "missing_before":
        action["before_value"] = None
    elif mutation == "stale_before":
        action["before_value"] = {**before, "title": "stale"}
    elif mutation == "incorrect_after":
        action["after_value"] = before
    elif mutation == "unknown_target":
        action["target_id"] = "REPORT-SECTION-UNKNOWN"
    elif mutation == "target_type_collision":
        action["target_id"] = initial.synthesis_claims[0].claim_id
    elif mutation == "malformed_edit":
        action["action"] = "edit"
        action["after_value"] = {"section_id": section.section_id}
    payload["jarvis_synthesis_report_workspace"]["review_actions"] = [action]
    result = build_clinical_case_v034_bundle(payload)[8]
    rejected = result.review_action_results[0]
    assert rejected.result_status.value == "rejected"
    assert rejected.rejection_reason.value == reason
    assert rejected.validated_after is None
    assert result.applied_review_actions == []
    if mutation not in {"unknown_target", "target_type_collision"}:
        assert result.report_sections[0] == section


def test_oversized_review_snapshot_is_rejected_at_schema_boundary():
    payload = _payload()
    initial = build_clinical_case_v034_bundle(payload)[8]
    section = initial.report_sections[0]
    payload["jarvis_synthesis_report_workspace"]["review_actions"] = [
        {
            "action_id": "OVERSIZED",
            "action": "accept",
            "target_type": "report_section",
            "target_id": section.section_id,
            "reviewer_role": "reviewer",
            "timestamp": "2026-07-30T13:00:00Z",
            "before_value": {"oversized": "x" * 31_000},
            "after_value": section.model_dump(mode="json"),
        }
    ]
    bundle = build_clinical_case_v034_bundle(payload)
    assert bundle[0].intake_completeness == "invalid"
    assert bundle[8] is None


@pytest.mark.parametrize(
    "phrase",
    [
        "This result is diagnostic of the condition.",
        "This variant is pathogenic.",
        "This variant is benign.",
        "This variant is causative.",
        "This confirms the condition.",
        "The condition was confirmed.",
        "This rules out the condition.",
        "The condition was ruled out.",
        "Order this test.",
        "We recommend treatment.",
        "This is the final classification.",
    ],
)
def test_safety_language_positive_rules(phrase):
    assert _forbidden_matches(phrase)


def test_safety_language_allows_explicit_external_attribution_and_negation():
    assert _forbidden_matches(
        "External source 'Lab' reports a classification 'pathogenic'. "
        "This assessment was not assigned by InSilicoPop."
    ) == []
    assert _forbidden_matches(
        "A final classification must not be made by this draft."
    ) == []


def test_critics_detect_privacy_and_citation_mismatch_without_mutating_inputs():
    workspace = build_clinical_case_v034_bundle(_payload())[8]
    claim = workspace.synthesis_claims[0].model_copy(
        update={"statement": "A hidden biological relationship and sample-swap conclusion."}
    )
    section = next(item for item in workspace.report_sections if item.claim_ids)
    mismatched = section.model_copy(update={"citation_ids": []})
    claims = [claim, *workspace.synthesis_claims[1:]]
    sections = [
        mismatched if item.section_id == section.section_id else item
        for item in workspace.report_sections
    ]
    before = {
        "claims": [item.model_dump(mode="json") for item in claims],
        "sections": [item.model_dump(mode="json") for item in sections],
    }
    _, findings = _run_critics(
        case_id=workspace.pseudonymous_case_id,
        claims=claims,
        excluded_claims=workspace.excluded_proposed_claims,
        sections=sections,
        result_evidence_workspace=build_clinical_case_v034_bundle(_payload())[6],
        specialist_agent_workspace=build_clinical_case_v034_bundle(_payload())[7],
        eligibility_decisions=workspace.eligibility_decisions,
    )
    assert {"PRIVACY-BOUNDARY", "CITATION-MISMATCH"} <= {
        item.code for item in findings
    }
    after = {
        "claims": [item.model_dump(mode="json") for item in claims],
        "sections": [item.model_dump(mode="json") for item in sections],
    }
    assert before == after


def test_report_contract_is_distinct_and_narratives_expose_integrity_metadata():
    workspace = build_clinical_case_v034_bundle(_payload())[8]
    assert [item.section_type for item in workspace.report_sections] == [
        "referral_summary",
        "clinical_history",
        "phenotype_hpo",
        "pedigree_inheritance",
        "previous_investigations",
        "missing_information",
        "pretest_readiness",
        "test_strategy",
        "result_normalization",
        "evidence_ledger",
        "specialist_outputs",
        "candidate_acmg",
        "disagreements",
        "limitations",
        "jarvis_briefing",
        "scientific_synthesis",
        "critic_findings",
        "cited_draft_narrative",
        "human_review_history",
    ]
    synthesis = next(
        item
        for item in workspace.report_sections
        if item.section_type == "scientific_synthesis"
    )
    for marker in (
        "claim:",
        "support:",
        "uncertainty:",
        "origin:",
        "supporting:",
        "contradicting:",
        "unresolved:",
        "conflict:",
        "use:",
        "eligibility:",
        "exclusions:",
        "human_review:",
        "draft:draft_not_clinically_approved",
    ):
        assert marker in synthesis.narrative
    assert all(
        item.narrative_status == "draft_not_clinically_approved"
        and item.clinically_approved is False
        for item in workspace.report_sections
    )
