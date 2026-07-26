from __future__ import annotations

import copy

from app.insilicopop.clinical import (
    build_clinical_case_strategy_bundle,
    load_test_strategy_catalogue,
)
from app.insilicopop.clinical.test_strategy_models import TestClass as StrategyTestClass
from backend.tests.test_pretest_assessment_v0312 import complete_case


def strategy_payload(*, mechanism="exome_scope", review_state="confirmed", record_id="PH-1"):
    payload = complete_case()
    payload["test_strategy_workspace"] = {
        "schema_version": "0.31.3",
        "comparison_note_exact": "Compare only bounded classes surfaced from reviewed inputs.",
        "rule_inputs": [
            {
                "rule_input_id": "RULE-EXOME-1",
                "mechanism": mechanism,
                "rationale_exact": "A clinician reviewed an exome-scope mechanism for comparison.",
                "review_state": review_state,
                "trigger_facts": [
                    {
                        "fact_id": "FACT-PH-1",
                        "fact_summary_exact": "The supplied structured phenotype record was reviewed.",
                        "source_path": "clinical_case_intake.phenotypes.PH-1",
                        "source_record_ids": [record_id],
                        "provenance_source_ids": ["SRC-REF"],
                    }
                ],
            }
        ],
        "human_review_required": True,
    }
    if mechanism == "other":
        payload["test_strategy_workspace"]["rule_inputs"][0]["other_mechanism_exact"] = "Locally proposed mechanism without an approved rule."
    return payload


def workspace(payload=None):
    return build_clinical_case_strategy_bundle(payload or strategy_payload())[5]


def test_catalogue_contains_exactly_the_bounded_test_classes():
    entries = load_test_strategy_catalogue()
    assert {entry.test_class for entry in entries} == set(StrategyTestClass)
    assert len(entries) == len(StrategyTestClass)
    assert all(entry.catalogue_entry_id.startswith("TSCAT-") for entry in entries)
    assert all(entry.general_detection_scope for entry in entries)
    assert all(entry.important_blind_spots for entry in entries)
    assert all(entry.proband_sample_requirements for entry in entries)
    assert all(entry.family_sample_requirements for entry in entries)
    assert all(entry.after_negative_result for entry in entries)


def test_confirmed_exome_rule_surfaces_singleton_and_trio_as_proposed_not_approved():
    result = workspace()
    assert result.schema_version == "0.31.3"
    assert result.workspace_status.value == "proposed_options_for_review"
    assert {item.test_class.value for item in result.options} == {"singleton_wes", "trio_wes"}
    assert result.proposed_option_count == 2
    assert result.test_strategy_generated is True
    assert all(item.status == "proposed_not_approved" for item in result.options)
    assert all(item.approved is False and item.ordered is False for item in result.options)
    assert all(item.requires_clinician_selection is True for item in result.options)
    assert all(item.trigger_facts[0].fact_summary_exact == "The supplied structured phenotype record was reviewed." for item in result.options)
    assert result.test_recommendation_made is False
    assert result.final_test_selected is False
    assert result.medically_necessary_claim_made is False
    assert result.diagnosis_made is False
    assert result.treatment_recommendation_made is False
    assert result.final_acmg_classification_made is False


def test_trio_is_constrained_without_represented_parental_samples_but_singleton_is_reviewable():
    statuses = {item.test_class.value: item.feasibility_status.value for item in workspace().options}
    assert statuses == {"singleton_wes": "reviewable", "trio_wes": "constrained"}
    trio = next(item for item in workspace().options if item.test_class.value == "trio_wes")
    assert any("maternal and paternal" in item for item in trio.reasons_to_defer)


def test_available_parental_samples_make_trio_reviewable_without_selecting_it():
    payload = strategy_payload()
    payload["global_intake_context"] = {
        "schema_version": "0.31",
        "enabled": True,
        "family_sample_contexts": [
            {
                "family_member_id": "MOTHER-1",
                "relationship_to_proband_exact": "mother",
                "sample_category": "maternal",
                "sample_availability": "available",
            },
            {
                "family_member_id": "FATHER-1",
                "relationship_to_proband_exact": "father",
                "sample_category": "paternal",
                "sample_availability": "potentially_available",
            },
        ],
    }
    result = workspace(payload)
    trio = next(item for item in result.options if item.test_class.value == "trio_wes")
    assert trio.feasibility_status.value == "reviewable"
    assert trio.approved is False
    assert trio.ordered is False


def test_pending_rule_input_does_not_surface_a_test_class():
    result = workspace(strategy_payload(review_state="pending"))
    assert result.options == []
    assert result.workspace_status.value == "requires_rule_review"
    assert [item.code for item in result.rule_review_items] == ["rule_input_not_confirmed"]
    assert result.test_strategy_generated is False


def test_unapproved_other_mechanism_returns_requires_rule_review():
    result = workspace(strategy_payload(mechanism="other"))
    assert result.options == []
    assert result.workspace_status.value == "requires_rule_review"
    assert [item.code for item in result.rule_review_items] == ["mechanism_requires_approved_rule"]


def test_unknown_trigger_record_blocks_the_rule_input_with_stable_linkage_issue():
    result = workspace(strategy_payload(record_id="PH-UNKNOWN"))
    assert result.options == []
    assert result.workspace_status.value == "requires_rule_review"
    assert result.linkage_issues[0].code == "unknown_strategy_fact_record"
    assert result.linkage_issues[0].source_record_id == "PH-UNKNOWN"
    assert result.rule_review_items[0].code == "trigger_fact_linkage_requires_review"


def test_unknown_trigger_provenance_blocks_the_rule_input():
    payload = strategy_payload()
    payload["test_strategy_workspace"]["rule_inputs"][0]["trigger_facts"][0]["provenance_source_ids"] = [
        "SRC-UNKNOWN"
    ]
    result = workspace(payload)
    assert result.options == []
    assert result.linkage_issues[0].code == "unknown_strategy_fact_provenance"
    assert result.linkage_issues[0].source_record_id == "SRC-UNKNOWN"


def test_pretest_not_ready_defers_genomic_rule_and_surfaces_no_genomic_test_yet():
    payload = strategy_payload()
    payload["pre_test_assessment"]["testing_status"] = "no_test_yet"
    result = workspace(payload)
    assert result.workspace_status.value == "deferred_pending_prerequisites"
    assert [item.test_class.value for item in result.options] == ["no_genomic_test_yet"]
    assert result.options[0].feasibility_status.value == "deferred_pending_prerequisites"
    assert any(item.code == "investigation_option_deferred_by_pretest_readiness" for item in result.rule_review_items)


def test_pretest_not_ready_also_defers_non_genetic_and_biochemical_investigation_classes():
    for mechanism in ("non_genetic_investigation", "biochemical_or_metabolic"):
        payload = strategy_payload(mechanism=mechanism)
        payload["pre_test_assessment"]["testing_status"] = "no_test_yet"
        result = workspace(payload)
        assert [item.test_class.value for item in result.options] == ["no_genomic_test_yet"]
        assert any(
            item.code == "investigation_option_deferred_by_pretest_readiness"
            for item in result.rule_review_items
        )


def test_partial_existing_report_surfaces_report_review_class_without_commercial_product():
    payload = strategy_payload(mechanism="specialist_review")
    payload["pre_test_assessment"]["previous_investigations"][0]["report_availability"] = "partial"
    result = workspace(payload)
    classes = {item.test_class.value for item in result.options}
    assert "obtain_or_review_existing_report" in classes
    report = next(item for item in result.options if item.test_class.value == "obtain_or_review_existing_report")
    assert report.commercial_product_selected is False
    assert report.status == "proposed_not_approved"


def test_supplied_access_affordability_and_india_context_are_preserved_without_price_or_worth_inference():
    payload = strategy_payload(mechanism="single_gene")
    payload["global_intake_context"] = {
        "schema_version": "0.31",
        "enabled": True,
        "country_code": "IN",
        "care_setting": "tertiary_hospital",
        "testing_access_context": {
            "constraints": ["travel_limitation_reported", "financial_or_access_limitation_reported"],
            "estimated_turnaround_time_exact": "Supplied estimate: several weeks.",
        },
        "locale_profile": {
            "schema_version": "0.31",
            "profile_type": "india",
            "country_code": "IN",
            "care_setting": "government_hospital",
        },
    }
    payload["pre_test_assessment"]["context_review"]["access_review_status"] = "constraints_supplied"
    payload["pre_test_assessment"]["context_review"]["affordability_context_exact"] = "Family supplied an affordability constraint."
    payload["test_strategy_workspace"]["rule_inputs"][0]["rationale_exact"] = "Human-reviewed single-gene mechanism."
    result = workspace(payload)
    context = result.options[0].supplied_context
    assert context.locale_profile_type == "india"
    assert "travel_limitation_reported" in context.access_constraints
    assert context.affordability_context_exact == "Family supplied an affordability constraint."
    assert context.universal_price_assumed is False
    assert context.patient_worth_inference_made is False


def test_rule_and_fact_reordering_produces_identical_result():
    first = strategy_payload(mechanism="single_gene")
    second_rule = copy.deepcopy(first["test_strategy_workspace"]["rule_inputs"][0])
    second_rule["rule_input_id"] = "RULE-SPECIALIST-2"
    second_rule["mechanism"] = "specialist_review"
    second_rule["rationale_exact"] = "Specialist review question supplied."
    second_rule["trigger_facts"][0]["fact_id"] = "FACT-PH-2"
    first["test_strategy_workspace"]["rule_inputs"].append(second_rule)
    second = copy.deepcopy(first)
    second["test_strategy_workspace"]["rule_inputs"].reverse()
    assert workspace(first).model_dump(mode="json") == workspace(second).model_dump(mode="json")


def test_duplicate_rule_and_fact_identifiers_are_invalid_intake():
    payload = strategy_payload()
    duplicate = copy.deepcopy(payload["test_strategy_workspace"]["rule_inputs"][0])
    payload["test_strategy_workspace"]["rule_inputs"].append(duplicate)
    intake = build_clinical_case_strategy_bundle(payload)[0]
    duplicate_namespaces = {item.field for item in intake.validation_errors if item.code == "duplicate_local_identifier"}
    assert {"test_strategy_rule_input", "test_strategy_fact"} <= duplicate_namespaces


def test_strategy_schema_rejects_order_approval_and_final_selection_fields():
    payload = strategy_payload()
    payload["test_strategy_workspace"]["test_order"] = "WES"
    intake, *_, result = build_clinical_case_strategy_bundle(payload)
    assert intake.intake_completeness == "invalid"
    assert result is None
    assert any(item.code == "schema_validation_error" for item in intake.validation_errors)


def test_direct_identifier_in_strategy_text_is_blocked_and_redacted_downstream():
    payload = strategy_payload(mechanism="single_gene")
    payload["test_strategy_workspace"]["rule_inputs"][0]["rationale_exact"] = "Contact person@example.org for single-gene review."
    intake, *_, result = build_clinical_case_strategy_bundle(payload)
    assert intake.intake_completeness == "blocked"
    assert any(item.category == "direct_identifier" for item in intake.policy_blocks)
    assert "person@example.org" not in str(result.model_dump(mode="json"))


def test_absent_strategy_declaration_preserves_frozen_service_contract_and_returns_none_only_in_new_bundle():
    payload = complete_case()
    bundle = build_clinical_case_strategy_bundle(payload)
    assert bundle[4].assessment_outcome.value == "ready_for_test_strategy_review"
    assert bundle[5] is None
