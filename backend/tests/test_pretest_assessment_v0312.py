from __future__ import annotations

import copy
import json

from app.insilicopop.clinical import build_clinical_case_full_bundle, build_clinical_case_intake


def complete_case():
    return {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-PRETEST-1",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "human_review_required": True,
        "provenance": [{"source_id": "SRC-REF", "source_type": "redacted_referral"}],
        "phenotypes": [
            {"observation_id": "PH-1", "supplied_term": "developmental delay", "state": "present"}
        ],
        "pedigree": [
            {
                "family_member_id": "FAM-1",
                "relationship_to_proband": "affected sibling",
                "affected_status": "affected",
            }
        ],
        "pre_test_assessment": {
            "schema_version": "0.31.2",
            "referral_packet": {
                "referral_id": "REF-1",
                "source": "specialist",
                "referring_specialty_exact": "paediatrics",
                "reason_exact": "Review supplied developmental concerns and family history.",
                "urgency_context": "routine",
                "provenance_source_ids": ["SRC-REF"],
            },
            "clinical_history": {
                "history_id": "HIST-1",
                "summary_exact": "Redacted structured history summary.",
                "phenotype_observation_ids": ["PH-1"],
                "pedigree_member_ids": ["FAM-1"],
                "onset_exact": "early childhood",
                "disease_course": "static",
                "birth_history_status": "none_reported",
                "development_history_status": "supplied",
                "development_history_exact": "Supplied developmental history reviewed.",
                "review_status": "confirmed",
                "provenance_source_ids": ["SRC-REF"],
            },
            "previous_investigations_review_status": "supplied",
            "previous_investigations": [
                {
                    "investigation_id": "INV-2",
                    "category": "imaging",
                    "test_or_assessment_exact": "MRI report",
                    "occurred_on_or_period_exact": "2024",
                    "result_summary_exact": "Supplied report summary retained for review.",
                    "report_availability": "available",
                    "provenance_source_ids": ["SRC-REF"],
                }
            ],
            "known_family_reports_review_status": "supplied",
            "pedigree_review_status": "supplied",
            "known_family_reports": [
                {
                    "family_report_id": "FREP-1",
                    "family_member_id": "FAM-1",
                    "report_type_exact": "supplied affected-relative report",
                    "report_availability": "available",
                    "provenance_source_ids": ["SRC-REF"],
                }
            ],
            "context_review": {
                "sample_availability": "potentially_available",
                "sample_context_exact": "Proband sample potentially available; supplied context only.",
                "access_review_status": "reviewed_no_constraints_reported",
            },
            "testing_status": "ready_for_test_strategy_review",
            "clinician_checkpoints": [
                {
                    "checkpoint_id": "CHK-1",
                    "checkpoint_type": "pre_test_assessment_review",
                    "status": "confirmed",
                    "reviewer_role_exact": "clinical genetics reviewer",
                    "provenance_source_ids": ["SRC-REF"],
                }
            ],
            "human_review_required": True,
        },
    }


def assessment(payload=None):
    return build_clinical_case_full_bundle(payload or complete_case())[4]


def test_complete_review_reaches_strategy_review_checkpoint_without_generating_strategy():
    result = assessment()
    assert result.schema_version == "0.31.2"
    assert result.assessment_outcome.value == "ready_for_test_strategy_review"
    assert result.ready_for_test_strategy_review is True
    assert result.open_missing_information_count == 0
    assert result.linkage_issues == []
    assert result.test_strategy_generated is False
    assert result.test_recommendation_made is False
    assert result.test_order_placed is False
    assert result.automatic_wes_or_wgs_recommendation_made is False
    assert result.diagnosis_made is False
    assert result.final_acmg_classification_made is False
    assert result.human_review_required is True


def test_empty_assessment_builds_specific_missing_information_plan():
    payload = complete_case()
    payload["pre_test_assessment"] = {"schema_version": "0.31.2"}
    result = assessment(payload)
    codes = {item.code for item in result.missing_information_plan}
    assert result.assessment_outcome.value == "more_information_required"
    assert {
        "referral_packet_not_supplied",
        "clinical_genetics_history_not_supplied",
        "previous_investigations_not_assessed",
        "known_family_reports_not_assessed",
        "sample_availability_not_assessed",
        "access_and_affordability_not_assessed",
    } <= codes
    assert all(item.request_id.startswith("PREMISS-") for item in result.missing_information_plan)


def test_no_test_yet_is_preserved_as_supplied_even_when_more_information_is_missing():
    payload = complete_case()
    payload["pre_test_assessment"] = {"schema_version": "0.31.2", "testing_status": "no_test_yet"}
    result = assessment(payload)
    assert result.assessment_outcome.value == "no_test_yet"
    assert result.ready_for_test_strategy_review is False
    assert result.open_missing_information_count > 0


def test_ready_status_without_confirmed_clinician_checkpoint_awaits_review():
    payload = complete_case()
    payload["pre_test_assessment"]["clinician_checkpoints"][0]["status"] = "pending"
    result = assessment(payload)
    assert result.assessment_outcome.value == "awaiting_human_review"
    assert result.outcome_rationale_codes == ["pre_test_assessment_checkpoint_not_confirmed"]


def test_unknown_phenotype_pedigree_family_and_provenance_links_are_explicit():
    payload = complete_case()
    request = payload["pre_test_assessment"]
    request["clinical_history"]["phenotype_observation_ids"] = ["PH-MISSING"]
    request["clinical_history"]["pedigree_member_ids"] = ["FAM-MISSING"]
    request["known_family_reports"][0]["family_member_id"] = "FAM-MISSING"
    request["referral_packet"]["provenance_source_ids"] = ["SRC-MISSING"]
    result = assessment(payload)
    codes = {item.code for item in result.linkage_issues}
    assert result.assessment_outcome.value == "more_information_required"
    assert {"unknown_phenotype_link", "unknown_pedigree_link", "unknown_family_report_member", "unknown_provenance_source"} <= codes


def test_user_supplied_missing_information_is_preserved_and_can_be_resolved():
    payload = complete_case()
    payload["pre_test_assessment"]["supplied_missing_information_requests"] = [
        {
            "request_id": "REQ-OPEN",
            "category": "family_report",
            "information_needed_exact": "Retrieve the supplied affected-relative report.",
            "why_needed_exact": "Confirm the exact reported result before strategy review.",
            "linked_record_ids": ["FREP-1"],
        },
        {
            "request_id": "REQ-DONE",
            "category": "other",
            "information_needed_exact": "Previously requested bounded record.",
            "status": "resolved",
        },
    ]
    result = assessment(payload)
    items = {item.request_id: item for item in result.missing_information_plan}
    assert items["REQ-OPEN"].source == "user_supplied"
    assert items["REQ-DONE"].status.value == "resolved"
    assert result.open_missing_information_count == 1
    assert result.assessment_outcome.value == "more_information_required"


def test_direct_identifier_is_blocked_redacted_and_cannot_become_ready():
    payload = complete_case()
    secret = "Contact patient@example.org about the referral"
    payload["pre_test_assessment"]["referral_packet"]["reason_exact"] = secret
    intake, _, _, _, result = build_clinical_case_full_bundle(payload)
    assert "email_address" in {item.code for item in intake.policy_blocks}
    assert result.assessment_outcome.value == "awaiting_human_review"
    assert secret not in json.dumps(result.model_dump())
    assert result.referral_packet.reason_exact == "[REDACTED_DIRECT_IDENTIFIER]"


def test_out_of_scope_diagnosis_treatment_and_test_order_requests_remain_blocked():
    payload = complete_case()
    payload["requested_actions"] = ["diagnosis", "recommend treatment", "order a genetic test", "recommend WES"]
    intake, _, _, _, result = build_clinical_case_full_bundle(payload, request_text="Provide final ACMG classification")
    codes = {item.code for item in intake.policy_blocks}
    assert {"diagnosis_request", "treatment_request", "test_order_request", "test_recommendation_request", "final_classification_request"} <= codes
    assert result.assessment_outcome.value == "awaiting_human_review"
    assert result.test_order_placed is False


def test_extra_test_recommendation_catalogue_field_is_rejected():
    payload = complete_case()
    payload["pre_test_assessment"]["test_recommendations"] = ["WES"]
    intake = build_clinical_case_intake(payload)
    assert intake.intake_completeness == "invalid"
    assert any("test_recommendations" in (item.field or "") for item in intake.validation_errors)


def test_reordering_records_preserves_deterministic_result():
    payload = complete_case()
    second = copy.deepcopy(payload["pre_test_assessment"]["previous_investigations"][0])
    second["investigation_id"] = "INV-1"
    payload["pre_test_assessment"]["previous_investigations"].append(second)
    first = assessment(payload)
    reordered = copy.deepcopy(payload)
    reordered["pre_test_assessment"]["previous_investigations"].reverse()
    reordered["pre_test_assessment"]["clinician_checkpoints"].reverse()
    assert first == assessment(reordered)


def test_exact_redacted_clinical_wording_is_preserved_without_normalization():
    payload = complete_case()
    exact = "  supplied referral wording with deliberate spacing  "
    payload["pre_test_assessment"]["referral_packet"]["reason_exact"] = exact
    assert assessment(payload).referral_packet.reason_exact == exact


def test_explicit_timeline_order_is_used_without_interpreting_free_text_dates():
    payload = complete_case()
    later = payload["pre_test_assessment"]["previous_investigations"][0]
    later["timeline_order"] = 2
    earlier = copy.deepcopy(later)
    earlier.update(investigation_id="INV-1", timeline_order=1, occurred_on_or_period_exact="supplied earlier period")
    payload["pre_test_assessment"]["previous_investigations"].append(earlier)
    result = assessment(payload)
    assert [item.investigation_id for item in result.previous_investigation_timeline] == ["INV-1", "INV-2"]


def test_incomplete_prior_and_family_reports_create_targeted_information_requests():
    payload = complete_case()
    payload["pre_test_assessment"]["previous_investigations"][0]["report_availability"] = "partial"
    payload["pre_test_assessment"]["known_family_reports"][0]["report_availability"] = "requested"
    result = assessment(payload)
    codes = {item.code for item in result.missing_information_plan}
    assert {"previous_investigation_report_incomplete", "known_family_report_requested"} <= codes
    assert result.assessment_outcome.value == "more_information_required"


def test_unconfirmed_history_review_prevents_readiness():
    payload = complete_case()
    payload["pre_test_assessment"]["clinical_history"]["review_status"] = "needs_revision"
    result = assessment(payload)
    assert "clinical_history_review_not_confirmed" in {item.code for item in result.missing_information_plan}
    assert result.assessment_outcome.value == "awaiting_human_review"


def test_optional_extension_preserves_legacy_intake_serialization():
    payload = complete_case()
    payload.pop("pre_test_assessment")
    intake, _, _, _, result = build_clinical_case_full_bundle(payload)
    assert result is None
    assert "pre_test_assessment" not in intake.model_dump()
