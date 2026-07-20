from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
NODE = shutil.which("node")


def _javascript_function(source: str, name: str) -> str:
    start = source.index(f"function {name}")
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Workbench function {name} was not complete")


def _run_merge(values: dict[str, str]) -> dict[str, object]:
    if NODE is None:
        pytest.skip("Node is unavailable for the isolated Workbench DOM behavior test")
    html = client.get("/insilicopop/workbench").text
    functions = "\n".join(
        _javascript_function(html, name)
        for name in ("rawValueOf", "valueOf", "nextUiId", "upsertContextEntry", "mergeOptionalGlobalIntake")
    )
    script = f"""
const values = {json.dumps(values)};
const elements = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, {{value}}]));
globalThis.document = {{getElementById: (id) => elements[id]}};
{functions}
try {{
  mergeOptionalGlobalIntake();
  process.stdout.write(JSON.stringify({{status: "success", value: elements.clinical_case_intake.value}}));
}} catch (error) {{
  process.stdout.write(JSON.stringify({{status: "error", message: String(error.message)}}));
}}
"""
    completed = subprocess.run([NODE, "-e", script], check=True, capture_output=True, text=True, timeout=15)
    return json.loads(completed.stdout)


def _dom_values() -> dict[str, str]:
    ids = [
        "global_country",
        "global_region",
        "global_care_setting",
        "global_care_stage",
        "preferred_language",
        "source_language",
        "translation_status",
        "translation_review",
        "original_clinical_wording",
        "translated_clinical_text",
        "laboratory_source_id",
        "laboratory_source_label",
        "laboratory_report_date",
        "laboratory_test_type",
        "laboratory_sample_type",
        "laboratory_method",
        "family_member_id",
        "family_sample_context",
        "family_sample_availability",
        "access_constraints",
        "locale_profile",
        "india_state",
        "india_care_setting",
        "india_relationship",
        "india_relationship_exact",
    ]
    return {identifier: "" for identifier in ids}


def test_dom_merge_preserves_existing_context_and_exact_language_whitespace():
    intake = {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-DOM",
        "global_intake_context": {
            "schema_version": "0.31",
            "referral_context_exact": "existing referral context",
            "laboratory_contexts": [{"laboratory_source_id": "LAB-EXISTING", "source_label": "Existing"}],
        },
    }
    values = _dom_values()
    values["clinical_case_intake"] = json.dumps(intake)
    values["original_clinical_wording"] = "  exact original wording  "
    result = _run_merge(values)
    assert result["status"] == "success"
    merged = json.loads(result["value"])
    context = merged["global_intake_context"]
    assert context["referral_context_exact"] == "existing referral context"
    assert context["laboratory_contexts"][0]["laboratory_source_id"] == "LAB-EXISTING"
    assert context["language_context"]["original_text"] == "  exact original wording  "


def test_dom_merge_reports_dependent_laboratory_field_error_instead_of_discarding_it():
    values = _dom_values()
    values["clinical_case_intake"] = json.dumps({"schema_version": "0.27", "pseudonymous_case_id": "CASE-DOM"})
    values["laboratory_test_type"] = "  exact exome wording  "
    result = _run_merge(values)
    assert result == {
        "status": "error",
        "message": "A laboratory source label is required when adding a laboratory record.",
    }


def test_dom_repeated_merge_is_idempotent_and_stable_update_does_not_duplicate():
    values = _dom_values()
    values["clinical_case_intake"] = json.dumps(
        {
            "schema_version": "0.27",
            "pseudonymous_case_id": "CASE-DOM",
            "global_intake_context": {"schema_version": "0.31", "laboratory_contexts": [], "family_sample_contexts": []},
        }
    )
    values["laboratory_source_label"] = "Lab A"
    values["laboratory_method"] = "  method one  "
    values["family_sample_context"] = "  Mother  "
    first = _run_merge(values)
    first_context = json.loads(first["value"])["global_intake_context"]
    values["laboratory_source_id"] = first_context["laboratory_contexts"][0]["laboratory_source_id"]
    values["family_member_id"] = first_context["family_sample_contexts"][0]["family_member_id"]
    values["clinical_case_intake"] = first["value"]
    second = _run_merge(values)
    context = json.loads(second["value"])["global_intake_context"]
    assert len(context["laboratory_contexts"]) == 1
    assert len(context["family_sample_contexts"]) == 1
    assert context["laboratory_contexts"][0]["laboratory_source_id"] == "UI-LAB-1"
    assert context["family_sample_contexts"][0]["family_member_id"] == "UI-FAMILY-1"

    values["laboratory_method"] = "  edited method  "
    values["clinical_case_intake"] = second["value"]
    edited = _run_merge(values)
    laboratories = json.loads(edited["value"])["global_intake_context"]["laboratory_contexts"]
    assert len(laboratories) == 1
    assert laboratories[0]["assay_or_sequencing_method_exact"] == "  edited method  "


def test_dom_distinct_laboratory_entry_is_preserved():
    values = _dom_values()
    values["clinical_case_intake"] = json.dumps({"schema_version": "0.27", "pseudonymous_case_id": "CASE-DOM"})
    values["laboratory_source_label"] = "Lab A"
    first = _run_merge(values)
    values["clinical_case_intake"] = first["value"]
    values["laboratory_source_label"] = "Lab B"
    second = _run_merge(values)
    laboratories = json.loads(second["value"])["global_intake_context"]["laboratory_contexts"]
    assert [item["source_label"] for item in laboratories] == ["Lab A", "Lab B"]
    assert [item["laboratory_source_id"] for item in laboratories] == ["UI-LAB-1", "UI-LAB-2"]


def test_dom_existing_india_locale_fields_survive_and_explicit_switch_changes_profile():
    intake = {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-DOM",
        "global_intake_context": {
            "schema_version": "0.31",
            "locale_profile": {
                "profile_type": "india",
                "country_code": "IN",
                "district_or_region_exact": "Existing district",
                "public_program_or_scheme_exact": "Existing scheme",
            },
        },
    }
    values = _dom_values()
    values["clinical_case_intake"] = json.dumps(intake)
    values["locale_profile"] = "india"
    values["india_state"] = "KA"
    merged = _run_merge(values)
    locale = json.loads(merged["value"])["global_intake_context"]["locale_profile"]
    assert locale["district_or_region_exact"] == "Existing district"
    assert locale["public_program_or_scheme_exact"] == "Existing scheme"
    assert locale["state_or_union_territory_code"] == "KA"

    values["clinical_case_intake"] = merged["value"]
    values["locale_profile"] = "global_default"
    switched = _run_merge(values)
    assert json.loads(switched["value"])["global_intake_context"]["locale_profile"] == {"profile_type": "global_default"}


def test_dom_same_laboratory_keeps_distinct_tests_and_stable_id_edits_only_one():
    values = _dom_values()
    values["clinical_case_intake"] = json.dumps({"schema_version": "0.27", "pseudonymous_case_id": "CASE-DOM"})
    values["laboratory_source_label"] = "Lab A"
    values["laboratory_test_type"] = "WGS"
    first = _run_merge(values)
    first_context = json.loads(first["value"])["global_intake_context"]
    first_id = first_context["laboratory_contexts"][0]["laboratory_source_id"]

    values["clinical_case_intake"] = first["value"]
    values["laboratory_source_id"] = ""
    values["laboratory_test_type"] = "WES"
    second = _run_merge(values)
    laboratories = json.loads(second["value"])["global_intake_context"]["laboratory_contexts"]
    assert [(item["source_label"], item["test_type_exact"]) for item in laboratories] == [("Lab A", "WGS"), ("Lab A", "WES")]

    values["clinical_case_intake"] = second["value"]
    values["laboratory_source_id"] = first_id
    values["laboratory_source_label"] = ""
    values["laboratory_test_type"] = ""
    values["laboratory_method"] = "edited method"
    edited = _run_merge(values)
    laboratories = json.loads(edited["value"])["global_intake_context"]["laboratory_contexts"]
    assert laboratories[0]["test_type_exact"] == "WGS"
    assert laboratories[0]["assay_or_sequencing_method_exact"] == "edited method"
    assert laboratories[1]["test_type_exact"] == "WES"


def test_dom_same_relationship_ids_remain_distinct_and_known_availability_survives_blank_edit():
    values = _dom_values()
    values["clinical_case_intake"] = json.dumps({"schema_version": "0.27", "pseudonymous_case_id": "CASE-DOM"})
    values["family_member_id"] = "SISTER-1"
    values["family_sample_context"] = "Sister"
    values["family_sample_availability"] = "available"
    first = _run_merge(values)

    values["clinical_case_intake"] = first["value"]
    values["family_member_id"] = "SISTER-2"
    values["family_sample_context"] = "Sister"
    values["family_sample_availability"] = "unknown"
    second = _run_merge(values)
    family = json.loads(second["value"])["global_intake_context"]["family_sample_contexts"]
    assert [item["family_member_id"] for item in family] == ["SISTER-1", "SISTER-2"]

    values["clinical_case_intake"] = second["value"]
    values["family_member_id"] = "SISTER-1"
    values["family_sample_context"] = "Sister"
    values["family_sample_availability"] = ""
    unchanged = _run_merge(values)
    family = json.loads(unchanged["value"])["global_intake_context"]["family_sample_contexts"]
    assert family[0]["sample_availability"] == "available"
    assert family[1]["sample_availability"] == "unknown"
