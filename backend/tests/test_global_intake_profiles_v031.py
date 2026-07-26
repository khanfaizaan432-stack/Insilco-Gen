from __future__ import annotations

import json
from pathlib import Path

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.clinical import build_clinical_case_intake


def _case(**updates):
    payload = {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-GLOBAL-1",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "reviewer_status": "pending",
        "human_review_required": True,
    }
    payload.update(updates)
    return payload


def test_extension_is_optional_and_legacy_serialization_is_unchanged():
    result = build_clinical_case_intake(_case())
    assert result.schema_version == "0.27"
    assert result.global_intake_context is None
    assert "global_intake_context" not in result.model_dump()


def test_non_indian_global_default_and_unknown_country_make_no_locale_assumptions():
    unknown = build_clinical_case_intake(
        _case(global_intake_context={"schema_version": "0.31", "locale_profile": {"profile_type": "global_default"}})
    )
    assert unknown.global_intake_context["country_code"] is None
    assert unknown.global_intake_context["locale_profile"] == {
        "schema_version": "0.31",
        "profile_type": "global_default",
        "country_code": None,
        "health_system_context_exact": None,
    }
    assert "india" not in json.dumps(unknown.global_intake_context).lower()

    non_indian = build_clinical_case_intake(
        _case(global_intake_context={"country_code": "DE", "locale_profile": {"profile_type": "global_default", "country_code": "DE"}})
    )
    assert non_indian.global_intake_context["country_code"] == "DE"
    assert non_indian.global_intake_context["locale_profile"]["profile_type"] == "global_default"


def test_global_context_round_trips_exact_language_laboratory_family_and_access_values():
    original = "  genaue ursprüngliche Formulierung  "
    translated = "  separate translated working text  "
    result = build_clinical_case_intake(
        _case(
            global_intake_context={
                "country_code": "DE",
                "region_or_administrative_area_exact": "Berlin region",
                "care_setting": "tertiary_hospital",
                "care_stage": "adult",
                "referral_context_exact": "Specialist referral; supplied context only",
                "language_context": {
                    "preferred_language": "Deutsch",
                    "source_language": "Deutsch",
                    "original_text": original,
                    "translated_text": translated,
                    "translation_status": "machine_translated",
                    "translation_review_state": "unreviewed",
                },
                "laboratory_contexts": [{
                    "laboratory_source_id": "LAB-1",
                    "source_label": "Supplied laboratory label",
                    "test_type_exact": "Exome test",
                    "sample_type_exact": "blood",
                    "assay_or_sequencing_method_exact": "exact method wording",
                    "genome_build_exact": " GRCh38 ",
                    "transcript_exact": " NM_000000.1 ",
                    "variant_notation_exact": [" c.1A>G "],
                    "accreditation_wording_exact": " exact supplied certification wording ",
                }],
                "family_sample_contexts": [{
                    "family_member_id": "FAM-1",
                    "sample_category": "maternal",
                    "relationship_to_proband_exact": "mother",
                    "sample_availability": "potentially_available",
                    "family_history_incomplete": True,
                }],
                "testing_access_context": {"constraints": ["travel_limitation_reported", "follow_up_uncertain"]},
            }
        )
    )
    context = result.global_intake_context
    assert context["language_context"]["original_text"] == original
    assert context["language_context"]["translated_text"] == translated
    assert context["language_context"]["translation_review_state"] == "unreviewed"
    assert context["laboratory_contexts"][0]["variant_notation_exact"] == [" c.1A>G "]
    assert context["family_sample_contexts"][0]["sample_category"] == "maternal"
    assert context["testing_access_context"]["constraints"] == ["travel_limitation_reported", "follow_up_uncertain"]
    codes = {item.code for item in result.validation_warnings}
    assert "machine_translation_requires_expert_review" in codes
    assert "laboratory_accreditation_not_independently_verified" in codes
    assert "laboratory_notation_not_validated" in codes


def test_india_profile_is_explicit_preserves_unknown_degree_and_never_inferrs_identity():
    result = build_clinical_case_intake(
        _case(
            global_intake_context={
                "country_code": "IN",
                "language_context": {"source_language": "Kannada", "translation_status": "original"},
                "locale_profile": {
                    "profile_type": "india",
                    "country_code": "IN",
                    "state_or_union_territory_code": "KA",
                    "care_setting": "medical_college",
                    "consanguinity_status": "reported",
                    "supplied_relationship": "related_degree_unknown",
                    "relationship_description_original": "related, degree unknown",
                },
            }
        )
    )
    locale = result.global_intake_context["locale_profile"]
    assert locale["profile_type"] == "india"
    assert locale["state_or_union_territory_code"] == "KA"
    assert locale["supplied_relationship"] == "related_degree_unknown"
    assert locale["relationship_description_original"] == "related, degree unknown"
    generated_keys = json.dumps(locale).lower()
    for forbidden in ("paternity", "non-paternity", "sample swap", "caste", "religion", "tribe", "ancestry identity"):
        assert forbidden not in generated_keys


def test_india_country_mismatch_and_identity_fields_fail_schema_validation():
    mismatch = build_clinical_case_intake(
        _case(global_intake_context={"country_code": "GB", "locale_profile": {"profile_type": "india", "country_code": "IN"}})
    )
    assert mismatch.intake_completeness == "invalid"
    assert any("global_intake_context" in (item.field or "") for item in mismatch.validation_errors)

    forbidden = build_clinical_case_intake(
        _case(global_intake_context={"locale_profile": {"profile_type": "india", "country_code": "IN", "caste": "not permitted"}})
    )
    assert forbidden.intake_completeness == "invalid"


def test_direct_identifier_is_recorded_as_block_and_redacted_from_persistence():
    secret_text = "Contact person@example.org about this referral"
    result = build_clinical_case_intake(
        _case(global_intake_context={"referral_context_exact": secret_text})
    )
    assert "email_address" in {item.code for item in result.policy_blocks}
    assert secret_text not in json.dumps(result.model_dump())
    assert result.global_intake_context["referral_context_exact"] == "[REDACTED_DIRECT_IDENTIFIER]"


def test_paternity_diagnosis_and_treatment_requests_remain_blocked():
    result = build_clinical_case_intake(
        _case(requested_actions=["infer paternity", "diagnosis", "recommend treatment"])
    )
    codes = {item.code for item in result.policy_blocks}
    assert {"paternity_inference_request", "diagnosis_request", "treatment_request"} <= codes
    assert result.raw_genomic_files_parsed is False


def test_report_reproducibility_and_runtime_lock_render_only_explicit_locale(tmp_path: Path):
    payload = _case(global_intake_context={
        "country_code": "IN",
        "language_context": {"original_text": "redacted original", "translated_text": "translated working text", "translation_status": "machine_translated"},
        "locale_profile": {"profile_type": "india", "country_code": "IN", "state_or_union_territory_code": "KA"},
    })
    run = AgentLoop(generated_root=tmp_path).run(query="structure intake", uploads={}, clinical_case_intake=payload)
    report = Path(run["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    repro = Path(run["reproducibility_bundle"]["path"])
    runtime = json.loads((repro / "runtime_lock.json").read_text(encoding="utf-8"))
    provenance = json.loads((repro / "provenance_index.json").read_text(encoding="utf-8"))
    assert "### Global Intake and Care Context" in report
    assert "#### India Locale Context" in report
    assert "original_text" in report and "translated_text" in report
    assert runtime["global_intake_schema_version"] == "0.31"
    assert runtime["locale_profile_type"] == "india"
    assert runtime["locale_profile_explicitly_selected"] is True
    assert provenance["global_intake_context"]["json_pointer"] == "/global_intake_context"

    legacy = AgentLoop(generated_root=tmp_path).run(query="structure intake", uploads={}, clinical_case_intake=_case())
    legacy_report = Path(legacy["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    assert "### Global Intake and Care Context" not in legacy_report
    assert "#### India Locale Context" not in legacy_report
