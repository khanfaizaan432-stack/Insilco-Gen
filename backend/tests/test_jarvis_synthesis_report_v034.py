from __future__ import annotations

import copy

from app.insilicopop.clinical import (
    build_clinical_case_full_bundle,
    build_clinical_case_result_evidence_bundle,
    build_clinical_case_specialist_agent_bundle,
    build_clinical_case_strategy_bundle,
    build_clinical_case_v034_bundle,
)
from backend.tests.test_specialist_agents_v033 import _candidate_payload


def _payload() -> dict:
    payload, _ = _candidate_payload()
    payload["jarvis_synthesis_report_workspace"] = {
        "schema_version": "0.34",
        "proposed_claims": [],
        "review_actions": [],
        "human_review_required": True,
    }
    return payload


def test_frozen_bundle_contracts_remain_5_6_7_8_and_v034_is_9():
    payload = _payload()
    assert len(build_clinical_case_full_bundle(payload)) == 5
    assert len(build_clinical_case_strategy_bundle(payload)) == 6
    assert len(build_clinical_case_result_evidence_bundle(payload)) == 7
    assert len(build_clinical_case_specialist_agent_bundle(payload)) == 8
    bundle = build_clinical_case_v034_bundle(payload)
    assert len(bundle) == 9
    assert bundle[8].schema_version == "0.34"


def test_bounded_aggregate_is_deterministic_source_linked_and_non_clinical():
    payload = _payload()
    first = build_clinical_case_v034_bundle(payload)[8]
    second = build_clinical_case_v034_bundle(payload)[8]
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.reproducibility.workspace_hash == second.reproducibility.workspace_hash
    assert {item.critic_type.value for item in first.critic_runs} == {
        "citation_support",
        "scientific_consistency",
        "evidence_conflict",
        "safety_language",
        "privacy",
        "provenance",
    }
    assert all(item.mutation_applied is False for item in first.critic_runs)
    assert len(first.report_sections) == 19
    assert all(
        item.narrative_status == "draft_not_clinically_approved"
        and item.clinically_approved is False
        for item in first.report_sections
    )
    assert first.report_status == "draft_not_clinically_approved"
    assert first.external_llm_called is False
    assert first.external_tools_executed is False
    assert first.unrestricted_browsing_used is False
    assert first.agents_spawned is False
    assert first.critics_mutated_sources is False
    assert first.unsupported_claims_included_as_factual_conclusions is False
    assert first.diagnosis_made is False
    assert first.treatment_recommendation_made is False
    assert first.test_order_placed is False
    assert first.final_acmg_classification_made is False
    assert first.clinical_sign_out_made is False
    assert first.human_review_required is True
    assert all(
        item.source_fact_paths
        or item.supporting_evidence_ids
        or item.contradicting_evidence_ids
        or item.unresolved_evidence_ids
        or item.source_specialist_output_ids
        or item.source_candidate_criterion_ids
        or item.source_human_decision_ids
        for item in first.synthesis_claims
    )
    assert {
        item.claim_id for item in first.claim_evidence_drill_down
    } == {item.claim_id for item in first.synthesis_claims}


def test_uncontrolled_proposed_claim_is_excluded_and_critic_visible():
    payload = _payload()
    payload["jarvis_synthesis_report_workspace"]["proposed_claims"] = [
        {
            "proposal_id": "UNSUPPORTED-1",
            "statement": "This unsupported assertion should not become a factual conclusion.",
            "source_evidence_ids": ["LEDGER-DOES-NOT-EXIST"],
            "stated_support_status": "supported",
            "uncertainty_language": "Source validity has not been established.",
        }
    ]
    result = build_clinical_case_v034_bundle(payload)[8]
    excluded = result.excluded_proposed_claims[0]
    assert excluded.support_status.value == "unsupported"
    assert excluded.eligible_for_report is False
    assert all(
        excluded.claim_id not in section.claim_ids
        and excluded.statement not in section.narrative
        for section in result.report_sections
    )
    assert any(
        item.code == "CITATION-UNSUPPORTED"
        and item.target_id == excluded.claim_id
        and item.mutation_applied is False
        for item in result.critic_findings
    )


def test_direct_identifier_or_secret_in_v034_request_is_rejected_before_storage():
    for statement in (
        "Patient name: Example Person",
        "Contact reviewer@example.org",
        "api_key=do-not-store-this",
        "Call +91 98765 43210",
    ):
        payload = _payload()
        payload["jarvis_synthesis_report_workspace"]["proposed_claims"] = [
            {
                "proposal_id": "SENSITIVE-1",
                "statement": statement,
                "uncertainty_language": "Human review required.",
            }
        ]
        bundle = build_clinical_case_v034_bundle(payload)
        assert bundle[0].intake_completeness == "invalid"
        assert bundle[8] is None


def test_full_snapshot_accept_action_applies_but_report_remains_draft():
    payload = _payload()
    initial = build_clinical_case_v034_bundle(payload)[8]
    section = next(
        item for item in initial.report_sections if item.section_type == "referral_summary"
    )
    before = section.model_dump(mode="json")
    after = copy.deepcopy(before)
    after["human_review_status"] = "accepted"
    after["reviewer_notes"] = "Accepted as a bounded draft section."
    payload["jarvis_synthesis_report_workspace"]["review_actions"] = [
        {
            "action_id": "REPORT-ACCEPT-1",
            "action": "accept",
            "target_type": "report_section",
            "target_id": section.section_id,
            "reviewer_role": "clinical_research_reviewer",
            "reviewer_id": "reviewer",
            "timestamp": "2026-04-01T00:00:00Z",
            "before_value": before,
            "after_value": after,
            "notes": "Accepted as a bounded draft section.",
        }
    ]
    result = build_clinical_case_v034_bundle(payload)[8]
    reviewed = next(
        item for item in result.report_sections if item.section_id == section.section_id
    )
    assert reviewed.human_review_status.value == "accepted"
    assert reviewed.narrative_status == "draft_not_clinically_approved"
    assert reviewed.clinically_approved is False
    assert result.review_action_results[0].result_status.value == "applied"
    assert result.review_action_results[0].validated_after == reviewed.model_dump(
        mode="json"
    )


def test_stale_and_forbidden_report_edits_are_rejected_atomically():
    payload = _payload()
    initial = build_clinical_case_v034_bundle(payload)[8]
    section = next(
        item for item in initial.report_sections if item.section_type == "clinical_history"
    )
    stale_before = section.model_dump(mode="json")
    stale_before["title"] = "Stale title"
    forbidden_after = section.model_dump(mode="json")
    forbidden_after["human_review_status"] = "edited"
    forbidden_after["narrative"] = "We diagnose this case and prescribe medication."
    payload["jarvis_synthesis_report_workspace"]["review_actions"] = [
        {
            "action_id": "REPORT-STALE-1",
            "action": "accept",
            "target_type": "report_section",
            "target_id": section.section_id,
            "reviewer_role": "clinical_research_reviewer",
            "timestamp": "2026-04-01T00:00:00Z",
            "before_value": stale_before,
            "after_value": section.model_dump(mode="json"),
        },
        {
            "action_id": "REPORT-FORBIDDEN-1",
            "action": "edit",
            "target_type": "report_section",
            "target_id": section.section_id,
            "reviewer_role": "clinical_research_reviewer",
            "timestamp": "2026-04-01T00:01:00Z",
            "before_value": section.model_dump(mode="json"),
            "after_value": forbidden_after,
        },
    ]
    result = build_clinical_case_v034_bundle(payload)[8]
    assert [item.result_status.value for item in result.review_action_results] == [
        "rejected",
        "rejected",
    ]
    assert [
        item.rejection_reason.value for item in result.review_action_results
    ] == ["before_value_mismatch", "forbidden_edit"]
    assert all(
        item.validated_after is None for item in result.review_action_results
    )
    unchanged = next(
        item for item in result.report_sections if item.section_id == section.section_id
    )
    assert unchanged == section


def test_grounded_edit_can_select_eligible_claims_without_free_text_invention():
    payload = _payload()
    initial = build_clinical_case_v034_bundle(payload)[8]
    section = next(
        item
        for item in initial.report_sections
        if item.section_type == "scientific_synthesis"
    )
    claim = next(
        item for item in initial.synthesis_claims if item.claim_id in section.claim_ids
    )
    after = section.model_dump(mode="json")
    after["title"] = "Reviewed bounded synthesis"
    after["claim_ids"] = [claim.claim_id]
    after["citation_ids"] = sorted(
        claim.supporting_evidence_ids
        + claim.contradicting_evidence_ids
        + claim.unresolved_evidence_ids
        + claim.source_fact_paths
    )
    conflict = claim.support_status.value in {"conflicting", "contradicted"}
    after["narrative"] = (
        f"{claim.statement} [claim:{claim.claim_id}; support:{claim.support_status.value}; "
        f"uncertainty:{claim.uncertainty_language}; origin:{claim.origin_category.value}; "
        f"supporting:{','.join(claim.supporting_evidence_ids) or 'none'}; "
        f"contradicting:{','.join(claim.contradicting_evidence_ids) or 'none'}; "
        f"unresolved:{','.join(claim.unresolved_evidence_ids) or 'none'}; "
        f"conflict:{str(conflict).lower()}; use:{claim.report_use}; "
        f"eligibility:{','.join(claim.eligibility_decision_ids) or 'none'}; "
        f"exclusions:{','.join(item.value for item in claim.exclusion_reason_codes) or 'none'}; "
        f"human_review:{claim.human_review_status.value}; "
        "draft:draft_not_clinically_approved]"
    )
    after["human_review_status"] = "edited"
    after["reviewer_notes"] = "Selected one controlled claim for this draft."
    payload["jarvis_synthesis_report_workspace"]["review_actions"] = [
        {
            "action_id": "REPORT-EDIT-GROUNDED-1",
            "action": "edit",
            "target_type": "report_section",
            "target_id": section.section_id,
            "reviewer_role": "clinical_research_reviewer",
            "timestamp": "2026-04-01T00:02:00Z",
            "before_value": section.model_dump(mode="json"),
            "after_value": after,
        }
    ]
    result = build_clinical_case_v034_bundle(payload)[8]
    reviewed = next(
        item for item in result.report_sections if item.section_id == section.section_id
    )
    assert reviewed.human_review_status.value == "edited"
    assert reviewed.claim_ids == [claim.claim_id]
    assert result.review_action_results[0].result_status.value == "applied"


def test_unreviewed_specialist_output_does_not_enter_evidence_bearing_report():
    result = build_clinical_case_v034_bundle(_payload())[8]
    specialist_section = next(
        item for item in result.report_sections if item.section_type == "specialist_outputs"
    )
    assert specialist_section.claim_ids == []
    assert "no eligible controlled claim" in specialist_section.narrative
    candidate_section = next(
        item for item in result.report_sections if item.section_type == "candidate_acmg"
    )
    assert candidate_section.claim_ids == []
    limitations = next(
        item for item in result.report_sections if item.section_type == "limitations"
    )
    assert "candidate status" in limitations.narrative
    assert "ineligible_review_status" in limitations.narrative
