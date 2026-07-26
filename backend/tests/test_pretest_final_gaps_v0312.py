from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.clinical import build_clinical_case_full_bundle
from backend.tests.test_pretest_assessment_v0312 import assessment, complete_case


FAMILIAL_ASSERTIONS = (
    "family_history",
    "affected_relative",
    "segregation_relevant_unaffected_relative",
    "familial_disorder_claim",
    "known_familial_variant",
    "relative_genetic_report",
    "consanguinity_or_parental_relationship",
    "inheritance_question",
)


def _without_represented_family_context(payload):
    payload["pedigree"] = []
    request = payload["pre_test_assessment"]
    request["clinical_history"]["pedigree_member_ids"] = []
    request["known_family_reports_review_status"] = "none_reported"
    request["known_family_reports"] = []
    request["family_history_review_status"] = "not_assessed"
    request.pop("family_history_summary_exact", None)
    return request


def _familial_item(assertion_type, item_id="HI-FAMILY", exact="Supplied typed familial claim.", links=None):
    return {
        "item_id": item_id,
        "category": "family_context",
        "exact_supplied_text": exact,
        "source_type": "patient_or_family_reported",
        "assertion_type": assertion_type,
        "review_status": "reviewed",
        "phenotype_links": ["PH-1"],
        "pedigree_person_links": links or [],
        "provenance_source_ids": ["SRC-REF"],
    }


@pytest.mark.parametrize(
    ("assertion_type", "exact"),
    [
        ("affected_relative", "Affected sibling reported by family."),
        ("affected_relative", "Affected parent reported by family."),
        ("known_familial_variant", "Known familial variant reported in a relative."),
    ],
)
def test_typed_familial_claim_without_pedigree_cannot_become_ready(assertion_type, exact):
    payload = complete_case()
    request = _without_represented_family_context(payload)
    request["pedigree_review_status"] = "none_reported"
    request["clinical_history"]["items"] = [_familial_item(assertion_type, exact=exact)]
    result = assessment(payload)
    item = next(item for item in result.blocking_items if item.code == "familial_claim_pedigree_context_not_supplied")
    assert result.assessment_outcome.value == "more_information_required"
    assert item.linked_record_ids == ["HI-FAMILY"]
    assert result.clinical_history.items[0].exact_supplied_text == exact
    assert result.clinical_history.items[0].source_type.value == "patient_or_family_reported"
    assert result.clinical_history.items[0].assertion_type.value == assertion_type
    assert result.clinical_history.items[0].pedigree_person_links == []


@pytest.mark.parametrize("assertion_type", FAMILIAL_ASSERTIONS)
def test_every_typed_familial_assertion_is_pedigree_relevant(assertion_type):
    payload = complete_case()
    request = _without_represented_family_context(payload)
    request["pedigree_review_status"] = "none_reported"
    request["clinical_history"]["items"] = [_familial_item(assertion_type)]
    result = assessment(payload)
    assert result.ready_for_test_strategy_review is False
    assert "familial_claim_pedigree_context_not_supplied" in {item.code for item in result.blocking_items}


def test_familial_claim_with_valid_pedigree_link_can_progress():
    payload = complete_case()
    payload["pre_test_assessment"]["clinical_history"]["items"] = [
        _familial_item("affected_relative", links=["FAM-1"])
    ]
    result = assessment(payload)
    assert result.assessment_outcome.value == "ready_for_test_strategy_review"
    assert "familial_claim_pedigree_context_not_supplied" not in {item.code for item in result.missing_information_plan}


def test_unrelated_typed_history_does_not_trigger_pedigree_review():
    payload = complete_case()
    request = _without_represented_family_context(payload)
    request["pedigree_review_status"] = "none_reported"
    request["clinical_history"]["items"] = [
        {
            **_familial_item("reported_symptom", exact="Standalone reported symptom."),
            "category": "symptom",
        }
    ]
    result = assessment(payload)
    assert result.assessment_outcome.value == "ready_for_test_strategy_review"
    assert not any("pedigree" in item.code or "familial_claim" in item.code for item in result.missing_information_plan)


@pytest.mark.parametrize("state", ["supplied", "none_reported", "unavailable", "not_collected", "deferred", "not_relevant", "unknown"])
@pytest.mark.parametrize("relevant", [False, True])
@pytest.mark.parametrize("familial_claim", [False, True])
@pytest.mark.parametrize("pedigree_checkpoint_confirmed", [False, True])
def test_pedigree_state_relevance_claim_and_checkpoint_matrix(
    state, relevant, familial_claim, pedigree_checkpoint_confirmed
):
    payload = complete_case()
    request = _without_represented_family_context(payload)
    request["pedigree_review_status"] = state
    request["pedigree_relevant_to_referral"] = relevant
    request["clinical_history"]["items"] = [_familial_item("affected_relative")] if familial_claim else []
    if pedigree_checkpoint_confirmed:
        request["clinician_checkpoints"].append(
            {
                "checkpoint_id": "CHK-PEDIGREE",
                "checkpoint_type": "pedigree_review",
                "status": "confirmed",
                "reviewer_role_exact": "clinical genetics reviewer",
                "provenance_source_ids": ["SRC-REF"],
            }
        )
    effective_relevance = relevant or familial_claim
    expected_ready = {
        "supplied": pedigree_checkpoint_confirmed and not effective_relevance,
        "none_reported": not effective_relevance,
        "unavailable": (not effective_relevance) or pedigree_checkpoint_confirmed,
        "not_collected": not effective_relevance,
        "deferred": not effective_relevance,
        "not_relevant": not effective_relevance,
        "unknown": False,
    }[state]
    result = assessment(payload)
    assert result.ready_for_test_strategy_review is expected_ready
    if not expected_ready:
        assert result.assessment_outcome.value in {"more_information_required", "awaiting_human_review"}


def test_relevant_deferred_pedigree_is_not_resolved_by_generic_checkpoint():
    payload = complete_case()
    request = _without_represented_family_context(payload)
    request["pedigree_review_status"] = "deferred"
    request["pedigree_relevant_to_referral"] = True
    result = assessment(payload)
    assert result.ready_for_test_strategy_review is False
    assert "pedigree_linkage_not_supplied" in {item.code for item in result.blocking_items}


def _india_payload(review_status="not_reviewed"):
    payload = complete_case()
    payload["global_intake_context"] = {
        "country_code": "IN",
        "locale_profile": {
            "profile_type": "india",
            "country_code": "IN",
            "consanguinity_status": "reported",
            "supplied_relationship": "related_degree_unknown",
            "relationship_description_original": "  related, degree unknown  ",
            "relationship_context_review_status": review_status,
        },
    }
    return payload


@pytest.mark.parametrize(
    ("status", "expected_outcome", "item_expected"),
    [
        ("not_reviewed", "awaiting_human_review", True),
        ("reviewed_confirmed", "ready_for_test_strategy_review", False),
        ("requires_clarification", "awaiting_human_review", True),
    ],
)
def test_india_relationship_context_typed_review_states(status, expected_outcome, item_expected):
    result = assessment(_india_payload(status))
    codes = {item.code for item in result.human_review_items}
    assert result.assessment_outcome.value == expected_outcome
    assert ("upstream_reported_relationship_context_requires_expert_review" in codes) is item_expected


def test_corrected_india_relationship_context_preserves_original_corrected_and_provenance():
    payload = _india_payload("reviewed_corrected")
    locale = payload["global_intake_context"]["locale_profile"]
    locale["relationship_description_corrected"] = "  reviewed relationship representation  "
    locale["relationship_context_review_provenance_source_ids"] = ["SRC-REF", "SRC-REF"]
    result = assessment(payload)
    intake = build_clinical_case_full_bundle(payload)[0]
    saved = intake.global_intake_context["locale_profile"]
    assert result.assessment_outcome.value == "ready_for_test_strategy_review"
    assert saved["relationship_description_original"] == "  related, degree unknown  "
    assert saved["relationship_description_corrected"] == "  reviewed relationship representation  "
    assert saved["relationship_context_review_provenance_source_ids"] == ["SRC-REF"]


def test_unrelated_checkpoint_does_not_resolve_india_relationship_review():
    result = assessment(_india_payload())
    assert result.assessment_outcome.value == "awaiting_human_review"
    assert "upstream_reported_relationship_context_requires_expert_review" in {
        item.code for item in result.human_review_items
    }


def test_explicit_relationship_review_checkpoint_resolves_only_relationship_item():
    payload = _india_payload()
    payload["pre_test_assessment"]["clinician_checkpoints"].append(
        {
            "checkpoint_id": "CHK-RELATIONSHIP",
            "checkpoint_type": "relationship_context_review",
            "status": "confirmed",
            "reviewer_role_exact": "clinical genetics reviewer",
            "provenance_source_ids": ["SRC-REF"],
        }
    )
    result = assessment(payload)
    assert result.assessment_outcome.value == "ready_for_test_strategy_review"
    assert "upstream_reported_relationship_context_requires_expert_review" not in {
        item.code for item in result.missing_information_plan
    }
    assert {item.checkpoint_type.value for item in result.clinician_decisions} == {
        "pre_test_assessment_review",
        "relationship_context_review",
    }


def test_reviewed_relationship_context_resolves_only_its_own_item():
    payload = _india_payload("reviewed_confirmed")
    payload["global_intake_context"]["language_context"] = {
        "source_language": "Hindi",
        "original_text": "मूल पाठ",
        "translated_text": "Translated working text",
        "translation_status": "machine_translated",
        "translation_review_state": "unreviewed",
    }
    result = assessment(payload)
    codes = {item.code for item in result.missing_information_plan}
    assert "upstream_reported_relationship_context_requires_expert_review" not in codes
    assert "upstream_machine_translation_requires_expert_review" in codes
    assert result.ready_for_test_strategy_review is False


def test_corrected_relationship_context_requires_representation_and_provenance():
    payload = _india_payload("reviewed_corrected")
    intake = build_clinical_case_full_bundle(payload)[0]
    assert intake.intake_completeness == "invalid"


def test_supplied_pedigree_with_records_and_links_is_consistent():
    result = assessment(complete_case())
    assert result.assessment_outcome.value == "ready_for_test_strategy_review"
    assert "pedigree_supplied_without_represented_context" not in {
        item.code for item in result.missing_information_plan
    }


def test_supplied_pedigree_with_reviewed_none_reported_state_is_consistent():
    payload = complete_case()
    request = _without_represented_family_context(payload)
    request["pedigree_review_status"] = "supplied"
    request["family_history_review_status"] = "none_reported"
    result = assessment(payload)
    assert result.assessment_outcome.value == "ready_for_test_strategy_review"


def test_supplied_pedigree_with_reviewed_family_history_summary_is_consistent():
    payload = complete_case()
    request = _without_represented_family_context(payload)
    request["pedigree_review_status"] = "supplied"
    request["family_history_review_status"] = "supplied"
    request["family_history_summary_exact"] = "Reviewed family history did not identify an affected relative."
    result = assessment(payload)
    assert result.assessment_outcome.value == "ready_for_test_strategy_review"


def test_supplied_but_empty_pedigree_cannot_become_ready():
    payload = complete_case()
    request = _without_represented_family_context(payload)
    request["pedigree_review_status"] = "supplied"
    result = assessment(payload)
    item = next(
        item for item in result.human_review_items if item.code == "pedigree_supplied_without_represented_context"
    )
    assert item.request_id.startswith("PREMISS-")
    assert result.assessment_outcome.value == "awaiting_human_review"


def test_supplied_pedigree_with_invalid_link_cannot_become_ready():
    payload = complete_case()
    request = _without_represented_family_context(payload)
    request["pedigree_review_status"] = "supplied"
    request["clinical_history"]["pedigree_member_ids"] = ["FAM-MISSING"]
    result = assessment(payload)
    assert result.assessment_outcome.value == "more_information_required"
    assert "unknown_pedigree_link" in {item.code for item in result.linkage_issues}


def test_relationship_review_is_rendered_without_test_or_clinical_recommendations(tmp_path: Path):
    payload = _india_payload("reviewed_corrected")
    locale = payload["global_intake_context"]["locale_profile"]
    locale["relationship_description_corrected"] = "reviewed relationship representation"
    locale["relationship_context_review_provenance_source_ids"] = ["SRC-REF"]
    result = AgentLoop(generated_root=tmp_path).run(
        query="Structure supplied relationship context",
        uploads={},
        clinical_case_intake=payload,
    )
    report = Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    artifact = json.loads(
        (Path(result["reproducibility_bundle"]["path"]) / "clinical_case_intake.json").read_text(encoding="utf-8")
    )
    assert "relationship_context_review_status: `reviewed_corrected`" in report
    assert "relationship_description_corrected: `reviewed relationship representation`" in report
    assert artifact["global_intake_context"]["locale_profile"]["relationship_description_original"] == "  related, degree unknown  "
    assert result["pre_test_assessment"]["test_recommendation_made"] is False
    assert result["pre_test_assessment"]["test_order_placed"] is False
    assert result["pre_test_assessment"]["diagnosis_made"] is False
    assert result["pre_test_assessment"]["treatment_recommendation_made"] is False
    assert result["external_llm_called"] is False
    assert result["external_tools_executed"] is False
