from __future__ import annotations

import pytest

from app.insilicopop.clinical import build_clinical_case_intake


def case_with_request(request: str):
    return {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-SAFE",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "human_review_required": True,
        "requested_actions": [request],
    }


@pytest.mark.parametrize(
    ("requested_action", "code"),
    [
        ("confirm diagnosis", "diagnosis_request"),
        ("recommend treatment", "treatment_request"),
        ("provide final ACMG classification", "final_classification_request"),
        ("give a pathogenic conclusion", "final_classification_request"),
        ("clinical sign-out", "clinical_sign_out_request"),
        ("return results to patient", "patient_return_request"),
        ("return secondary findings", "secondary_findings_return_request"),
        ("send raw genomic data to an external API", "external_raw_data_request"),
        ("infer caste", "caste_community_religion_request"),
        ("infer genetic purity", "purity_superiority_request"),
        ("ADMIXTURE proves ancestry", "pca_admixture_identity_request"),
    ],
)
def test_prohibited_requests_create_explicit_policy_blocks(requested_action, code):
    result = build_clinical_case_intake(case_with_request(requested_action))
    assert result.intake_completeness == "blocked"
    assert code in {item.code for item in result.policy_blocks}
    assert result.human_review_required is True


def test_bounded_direct_identifier_and_unredacted_text_rules():
    payload = case_with_request("structure supplied intake")
    payload["case_label"] = "contact person@example.org"
    result = build_clinical_case_intake(payload)
    assert "email_address" in {item.code for item in result.policy_blocks}


def test_safety_invariants_are_false_by_default_and_no_inferences_are_run():
    result = build_clinical_case_intake(case_with_request("structure supplied intake"))
    assert result.external_llm_called is False
    assert result.external_api_call_made is False
    assert result.external_tools_executed is False
    assert result.raw_genomic_files_parsed is False
    assert result.inheritance_calculation_performed is False
    assert result.variant_normalization_performed is False
    assert result.human_review_required is True
