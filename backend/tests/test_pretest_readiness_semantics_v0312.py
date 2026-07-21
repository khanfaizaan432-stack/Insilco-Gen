from __future__ import annotations

import copy

import pytest

from app.insilicopop.clinical import build_clinical_case_full_bundle
from backend.tests.test_inheritance_audit_v029 import member, observation, payload as pedigree_payload, relationship, x_linked_context
from backend.tests.test_pretest_assessment_v0312 import assessment, complete_case


def _codes(result, collection):
    return {item.code for item in getattr(result, collection)}


def test_unreviewed_machine_translation_maps_to_human_review_but_variant_absence_does_not():
    data = complete_case()
    data["global_intake_context"] = {
        "country_code": "DE",
        "language_context": {
            "source_language": "Deutsch",
            "original_text": "supplied source wording",
            "translated_text": "supplied machine translation",
            "translation_status": "machine_translated",
            "translation_review_state": "unreviewed",
        },
    }
    data.pop("candidate_variants", None)
    data.pop("genome_build", None)
    result = assessment(data)
    assert result.assessment_outcome.value == "awaiting_human_review"
    assert "upstream_machine_translation_requires_expert_review" in _codes(result, "human_review_items")
    assert "candidate_variants_not_supplied" not in {item.code for item in result.missing_information_plan}
    assert "genome_build_not_declared" not in {item.code for item in result.missing_information_plan}


def test_human_reviewed_machine_translation_does_not_block_progression():
    data = complete_case()
    data["global_intake_context"] = {
        "language_context": {
            "original_text": "source wording",
            "translated_text": "reviewed translation",
            "translation_status": "machine_translated",
            "translation_review_state": "human_reviewed",
        }
    }
    result = assessment(data)
    assert result.assessment_outcome.value == "ready_for_test_strategy_review"


def test_india_relationship_context_maps_to_human_review():
    data = complete_case()
    data["global_intake_context"] = {
        "country_code": "IN",
        "locale_profile": {
            "profile_type": "india",
            "country_code": "IN",
            "consanguinity_status": "reported",
            "supplied_relationship": "related_degree_unknown",
            "relationship_description_original": "related, degree unknown",
        },
    }
    result = assessment(data)
    assert result.assessment_outcome.value == "awaiting_human_review"
    assert "upstream_reported_relationship_context_requires_expert_review" in _codes(result, "human_review_items")


def _attach_pretest(data):
    data["pre_test_assessment"] = copy.deepcopy(complete_case()["pre_test_assessment"])
    request = data["pre_test_assessment"]
    request["referral_packet"]["provenance_source_ids"] = ["SRC-1"]
    request["clinical_history"]["phenotype_observation_ids"] = ["PH-1"]
    request["clinical_history"]["pedigree_member_ids"] = ["MEM-P"]
    request["clinical_history"]["provenance_source_ids"] = ["SRC-1"]
    request["known_family_reports_review_status"] = "none_reported"
    request["known_family_reports"] = []
    request["previous_investigations_review_status"] = "none_reported"
    request["previous_investigations"] = []
    request["clinician_checkpoints"][0]["provenance_source_ids"] = ["SRC-1"]
    return data


def test_inconsistent_pedigree_audit_maps_to_human_review():
    data = pedigree_payload(
        "x_linked",
        members=[member("MEM-P", "proband", affected="affected", sex="male"), member("MEM-A", "parent", affected="affected", sex="male")],
        relationships=[relationship("REL-1", "MEM-A", "MEM-P")],
        observations=[observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="hemizygous"), observation("OBS-A", "MEM-A", "VAR-1", "present", zygosity="hemizygous")],
        x_context=x_linked_context(),
    )
    result = build_clinical_case_full_bundle(_attach_pretest(data))[4]
    assert result.assessment_outcome.value == "awaiting_human_review"
    assert {"upstream_pedigree_inconsistency", "upstream_inheritance_audit_inconsistent"} <= _codes(result, "human_review_items")


def test_advisory_context_is_visible_and_does_not_block_ready_outcome():
    data = complete_case()
    data["pre_test_assessment"]["context_review"] = {}
    result = assessment(data)
    assert {"sample_availability_not_assessed", "access_and_affordability_not_assessed"} <= _codes(result, "advisory_items")
    assert result.assessment_outcome.value == "ready_for_test_strategy_review"


@pytest.mark.parametrize(
    ("pedigree_status", "relevant", "pedigree", "links", "expected_outcome", "expected_code"),
    [
        ("supplied", None, True, True, "ready_for_test_strategy_review", None),
        ("supplied", None, True, False, "more_information_required", "pedigree_linkage_not_supplied"),
        ("unavailable", None, True, False, "more_information_required", "pedigree_linkage_not_supplied"),
        ("unavailable", False, False, False, "ready_for_test_strategy_review", "pedigree_context_limited"),
        ("none_reported", False, False, False, "ready_for_test_strategy_review", None),
        ("not_relevant", False, False, False, "ready_for_test_strategy_review", None),
        ("not_collected", True, False, False, "more_information_required", "pedigree_linkage_not_supplied"),
    ],
)
def test_pedigree_relevance_and_availability_states(pedigree_status, relevant, pedigree, links, expected_outcome, expected_code):
    data = complete_case()
    request = data["pre_test_assessment"]
    request["pedigree_review_status"] = pedigree_status
    request["pedigree_relevant_to_referral"] = relevant
    if not pedigree:
        data["pedigree"] = []
        request["known_family_reports_review_status"] = "none_reported"
        request["known_family_reports"] = []
    request["clinical_history"]["pedigree_member_ids"] = ["FAM-1"] if links else []
    result = assessment(data)
    assert result.assessment_outcome.value == expected_outcome
    all_codes = {item.code for item in result.missing_information_plan}
    assert (expected_code in all_codes) if expected_code else ("pedigree_linkage_not_supplied" not in all_codes)


def test_claim_level_history_provenance_retains_source_assertion_negation_and_exact_wording():
    data = complete_case()
    exact = "  Family reports episodic weakness; wording retained exactly.  "
    data["pre_test_assessment"]["clinical_history"]["items"] = [
        {"item_id": "HI-1", "category": "symptom", "exact_supplied_text": exact, "source_type": "patient_or_family_reported", "assertion_type": "reported_symptom", "review_status": "reviewed", "phenotype_links": ["PH-1"]},
        {"item_id": "HI-2", "category": "examination", "exact_supplied_text": "No supplied weakness on examination.", "source_type": "clinician_examination", "assertion_type": "relevant_negative", "review_status": "reviewed", "negated": True},
        {"item_id": "HI-3", "category": "translation", "exact_supplied_text": "Translated supplied statement.", "source_type": "translated_statement", "assertion_type": "reported_symptom", "review_status": "unreviewed"},
    ]
    result = assessment(data)
    items = {item.item_id: item for item in result.clinical_history.items}
    assert items["HI-1"].exact_supplied_text == exact
    assert items["HI-1"].source_type.value == "patient_or_family_reported"
    assert items["HI-2"].source_type.value == "clinician_examination"
    assert items["HI-2"].negated is True
    assert items["HI-3"].source_type.value == "translated_statement"
    assert result.assessment_outcome.value == "awaiting_human_review"


def test_disputed_history_claim_requires_human_review_and_relevant_negative_requires_negation():
    data = complete_case()
    item = {"item_id": "HI-1", "category": "record", "exact_supplied_text": "Previous-record claim.", "source_type": "previous_medical_record", "assertion_type": "previous_diagnosis_claim", "review_status": "disputed"}
    data["pre_test_assessment"]["clinical_history"]["items"] = [item]
    assert assessment(data).assessment_outcome.value == "awaiting_human_review"
    item.update(assertion_type="relevant_negative", negated=False)
    assert build_clinical_case_full_bundle(data)[0].intake_completeness == "invalid"


def test_set_like_identifiers_are_deduplicated_sorted_and_byte_equivalent():
    first = complete_case()
    first["provenance"].append({"source_id": "SRC-Z", "source_type": "synthetic_fixture"})
    first["pre_test_assessment"]["referral_packet"]["provenance_source_ids"] = ["SRC-Z", "SRC-REF", "SRC-Z"]
    first["pre_test_assessment"]["clinical_history"]["phenotype_observation_ids"] = ["PH-1", "PH-1"]
    second = copy.deepcopy(first)
    second["pre_test_assessment"]["referral_packet"]["provenance_source_ids"].reverse()
    assert assessment(first).model_dump_json() == assessment(second).model_dump_json()
    assert assessment(first).referral_packet.provenance_source_ids == ["SRC-REF", "SRC-Z"]


@pytest.mark.parametrize(
    ("status", "essential", "expected_code", "impact", "outcome"),
    [
        ("available", False, None, None, "ready_for_test_strategy_review"),
        ("partial", False, "known_family_report_partial", "advisory", "ready_for_test_strategy_review"),
        ("requested", False, "known_family_report_requested", "advisory", "ready_for_test_strategy_review"),
        ("unavailable", False, "known_family_report_unavailable", "advisory", "ready_for_test_strategy_review"),
        ("unavailable", True, "known_family_report_unavailable", "blocking", "more_information_required"),
        ("unknown", False, "known_family_report_availability_not_reviewed", "human_review_required", "awaiting_human_review"),
        ("not_assessed", False, "known_family_report_availability_not_reviewed", "human_review_required", "awaiting_human_review"),
    ],
)
def test_family_report_availability_semantics(status, essential, expected_code, impact, outcome):
    data = complete_case()
    report = data["pre_test_assessment"]["known_family_reports"][0]
    report.update(report_availability=status, essential_to_referral=essential)
    result = assessment(data)
    assert result.assessment_outcome.value == outcome
    if expected_code:
        item = next(item for item in result.missing_information_plan if item.code == expected_code)
        assert item.readiness_impact.value == impact
    else:
        assert not any(item.code.startswith("known_family_report_") for item in result.missing_information_plan)


def test_four_bounded_outcomes_remain_available_without_test_recommendation():
    outcomes = set()
    for requested in ("ready_for_test_strategy_review", "no_test_yet", "more_information_required", "awaiting_human_review"):
        data = complete_case()
        data["pre_test_assessment"]["testing_status"] = requested
        result = assessment(data)
        outcomes.add(result.assessment_outcome.value)
        assert result.test_recommendation_made is False
        assert result.test_strategy_generated is False
        assert result.automatic_wes_or_wgs_recommendation_made is False
    assert outcomes == {"ready_for_test_strategy_review", "no_test_yet", "more_information_required", "awaiting_human_review"}
