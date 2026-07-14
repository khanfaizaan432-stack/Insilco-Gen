from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.insilicopop.clinical.models import AffectedStatus, ClinicalCaseIntake
from app.insilicopop.clinical.service import build_clinical_case_bundle, build_clinical_case_with_curation


def base_payload(**updates):
    payload = {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-V029",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "human_review_required": True,
        "genome_build": "GRCh38",
        "provenance": [{"source_id": "SRC-1", "source_type": "synthetic_fixture"}],
        "phenotypes": [{"observation_id": "PH-1", "supplied_term": "fictional finding", "state": "unknown"}],
        "candidate_variants": [{"candidate_id": "VAR-1", "submitted_representation": "fictional candidate", "gene": "GENE1"}],
        "pedigree": [{"family_member_id": "MEM-P", "relationship_to_proband": "proband", "affected_status": "affected"}],
        "hypotheses": [{"hypothesis_id": "HYP-1", "hypothesis_type": "inheritance", "value": "supplied", "inheritance_candidate": "autosomal_dominant"}],
    }
    payload.update(updates)
    return payload


def audit_request(**updates):
    request = {
        "schema_version": "0.29",
        "proband_member_id": "MEM-P",
        "relationships": [],
        "variant_observations": [{
            "observation_id": "OBS-P-1",
            "family_member_id": "MEM-P",
            "candidate_variant_id": "VAR-1",
            "presence_state": "present",
            "zygosity": "heterozygous",
            "testing_state": "tested",
            "confirmation_state": "confirmed",
        }],
        "audit_targets": [{"audit_target_id": "TARGET-1", "hypothesis_id": "HYP-1", "candidate_variant_ids": ["VAR-1"]}],
        "phase_declarations": [],
        "human_review_required": True,
    }
    request.update(updates)
    return request


def test_top_level_schema_and_public_two_value_contract_remain_exact():
    payload = base_payload()
    result = build_clinical_case_with_curation(payload)
    assert isinstance(result, tuple) and len(result) == 2
    intake, curation = result
    assert intake.schema_version == "0.27"
    assert curation is None
    assert intake.inheritance_calculation_performed is False
    assert "pedigree_inheritance_audit" not in intake.model_dump()


def test_nested_v029_request_is_typed_and_bundle_returns_three_values():
    payload = base_payload(pedigree_inheritance_audit=audit_request())
    case = ClinicalCaseIntake.model_validate(payload)
    assert case.schema_version == "0.27"
    assert case.pedigree_inheritance_audit.schema_version == "0.29"
    result = build_clinical_case_bundle(payload)
    assert len(result) == 3
    assert result[2] is not None
    assert result[2].inheritance_consistency_audit_performed is True
    assert result[2].inheritance_clinically_established is False


def test_not_assessed_is_strictly_additive_and_old_unknown_is_preserved():
    assert AffectedStatus.NOT_ASSESSED.value == "not_assessed"
    old = ClinicalCaseIntake.model_validate(base_payload())
    assert old.pedigree[0].affected_status == AffectedStatus.AFFECTED
    unknown = ClinicalCaseIntake.model_validate(base_payload(pedigree=[{"family_member_id": "MEM-P", "relationship_to_proband": "proband"}]))
    assert unknown.pedigree[0].affected_status == AffectedStatus.UNKNOWN
    assert unknown.model_dump(mode="json")["pedigree"][0]["affected_status"] == "unknown"


@pytest.mark.parametrize("field", ["name", "date_of_birth", "medical_record_number", "address", "family_narrative"])
def test_new_models_forbid_direct_identifier_and_narrative_fields(field):
    request = audit_request()
    request[field] = "not allowed"
    with pytest.raises(ValidationError):
        ClinicalCaseIntake.model_validate(base_payload(pedigree_inheritance_audit=request))


@pytest.mark.parametrize(
    "mutator",
    [
        lambda request: request["variant_observations"][0].update(provenance_source_ids=["person@example.org"]),
        lambda request: request["audit_targets"][0].update(candidate_variant_ids=["person@example.org"]),
    ],
)
def test_identifier_lists_reject_non_identifier_content(mutator):
    request = audit_request()
    mutator(request)
    with pytest.raises(ValidationError):
        ClinicalCaseIntake.model_validate(base_payload(pedigree_inheritance_audit=request))


def test_unique_ids_and_exact_references_are_validated_without_inference():
    request = audit_request(
        variant_observations=[
            audit_request()["variant_observations"][0],
            copy.deepcopy(audit_request()["variant_observations"][0]),
        ],
        audit_targets=[{"audit_target_id": "TARGET-1", "hypothesis_id": "UNKNOWN-HYP", "candidate_variant_ids": ["UNKNOWN-VAR"]}],
    )
    audit = build_clinical_case_bundle(base_payload(pedigree_inheritance_audit=request))[2]
    codes = {item.code for item in audit.validation_errors}
    assert {"duplicate_variant_observation_id", "duplicate_member_candidate_observation", "unknown_audit_hypothesis_reference", "unknown_audit_candidate_reference"} <= codes
    assert audit.inheritance_audits[0].status == "cannot_evaluate"


def test_relationship_graph_detects_self_cycle_duplicate_and_excess_parent_edges():
    pedigree = [
        {"family_member_id": "MEM-P", "relationship_to_proband": "proband"},
        {"family_member_id": "MEM-A", "relationship_to_proband": "parent"},
        {"family_member_id": "MEM-B", "relationship_to_proband": "parent"},
        {"family_member_id": "MEM-C", "relationship_to_proband": "parent"},
    ]
    relationships = [
        {"relationship_id": "R-SELF", "relationship_type": "biological_parent", "parent_member_id": "MEM-A", "child_member_id": "MEM-A"},
        {"relationship_id": "R-1", "relationship_type": "biological_parent", "parent_member_id": "MEM-A", "child_member_id": "MEM-P"},
        {"relationship_id": "R-1-DUP", "relationship_type": "biological_parent", "parent_member_id": "MEM-A", "child_member_id": "MEM-P"},
        {"relationship_id": "R-2", "relationship_type": "biological_parent", "parent_member_id": "MEM-B", "child_member_id": "MEM-P"},
        {"relationship_id": "R-3", "relationship_type": "biological_parent", "parent_member_id": "MEM-C", "child_member_id": "MEM-P"},
        {"relationship_id": "R-CYCLE", "relationship_type": "biological_parent", "parent_member_id": "MEM-P", "child_member_id": "MEM-A"},
    ]
    audit = build_clinical_case_bundle(base_payload(pedigree=pedigree, pedigree_inheritance_audit=audit_request(relationships=relationships)))[2]
    codes = {item.code for item in audit.relationship_issues}
    assert {"self_parent_reference", "duplicate_biological_parent_edge", "excess_biological_parent_edges", "pedigree_cycle"} <= codes
    assert not ({item.issue_id for item in audit.relationship_issues} & {item.issue_id for item in audit.validation_warnings})


def test_other_supplied_relationship_is_retained_but_not_interpreted():
    pedigree = [
        {"family_member_id": "MEM-P", "relationship_to_proband": "proband"},
        {"family_member_id": "MEM-X", "relationship_to_proband": "other"},
    ]
    request = audit_request(relationships=[{"relationship_id": "R-X", "relationship_type": "other_supplied", "parent_member_id": "MEM-X", "child_member_id": "MEM-P"}])
    audit = build_clinical_case_bundle(base_payload(pedigree=pedigree, pedigree_inheritance_audit=request))[2]
    assert "unsupported_supplied_relationship_structure" in {item.code for item in audit.validation_warnings}
    assert audit.biological_parent_relationship_count == 0
    assert audit.available_parent_child_transmission_summary.candidate_parent_child_transmission_count == 0


def test_input_models_do_not_mutate_or_rewrite_old_payloads():
    payload = base_payload(pedigree_inheritance_audit=audit_request())
    original = copy.deepcopy(payload)
    build_clinical_case_bundle(payload)
    assert payload == original


def test_x_linked_context_is_target_scoped_typed_and_provenance_validated():
    request = audit_request()
    request["audit_targets"][0]["x_linked_context"] = {
        "locus_context": "non_pseudoautosomal_x",
        "sex_chromosome_context": "sufficient_for_bounded_rule",
        "mosaic_context": "not_indicated_in_supplied_records",
        "provenance_source_ids": ["UNKNOWN-SOURCE"],
        "review_state": "confirmed",
    }
    data = base_payload(
        hypotheses=[{"hypothesis_id": "HYP-1", "hypothesis_type": "inheritance", "value": "supplied", "inheritance_candidate": "x_linked"}],
        pedigree_inheritance_audit=request,
    )
    case = ClinicalCaseIntake.model_validate(data)
    context = case.pedigree_inheritance_audit.audit_targets[0].x_linked_context
    assert context.locus_context.value == "non_pseudoautosomal_x"
    result = build_clinical_case_bundle(data)[2]
    assert "unknown_provenance_reference" in {item.code for item in result.validation_errors}


def test_exact_candidate_biological_strings_round_trip_and_formatting_is_flagged():
    candidate = {
        "candidate_id": "VAR-RAW",
        "submitted_representation": "  ACGTACGT  ",
        "gene": " GENE1 ",
        "transcript": " NM_000001.2 ",
        "genome_build": " GRCh38 ",
        "chromosome": " X ",
        "position": 100,
        "ref": " A ",
        "alt": " T ",
        "submitted_hgvs": [" NM_000001.2:c.1A>T "],
        "provenance": [{"source_id": "SRC-1", "source_type": "synthetic_fixture", "reference": " NC_000023.11 "}],
    }
    data = base_payload(candidate_variants=[candidate])
    case = ClinicalCaseIntake.model_validate(data)
    preserved = case.candidate_variants[0].model_dump(mode="json")
    assert preserved["submitted_representation"] == "  ACGTACGT  "
    assert preserved["gene"] == " GENE1 "
    assert preserved["transcript"] == " NM_000001.2 "
    assert preserved["genome_build"] == " GRCh38 "
    assert preserved["chromosome"] == " X "
    assert preserved["ref"] == " A "
    assert preserved["alt"] == " T "
    assert preserved["submitted_hgvs"] == [" NM_000001.2:c.1A>T "]
    assert preserved["provenance"][0]["reference"] == " NC_000023.11 "

    intake = build_clinical_case_bundle(data)[0]
    serialized = intake.model_dump(mode="json")["supplied_candidate_variants"][0]
    assert serialized == preserved
    anomaly_fields = {item.field for item in intake.validation_warnings if item.code == "candidate_biological_string_formatting_anomaly"}
    assert {
        "candidate_variants.submitted_representation",
        "candidate_variants.gene",
        "candidate_variants.transcript",
        "candidate_variants.genome_build",
        "candidate_variants.chromosome",
        "candidate_variants.ref",
        "candidate_variants.alt",
        "candidate_variants.submitted_hgvs.0",
        "candidate_variants.provenance.0.reference",
    } <= anomaly_fields


def test_gene_formatting_anomaly_is_not_silently_normalized_for_compound_comparison():
    data = base_payload(
        candidate_variants=[
            {"candidate_id": "VAR-1", "submitted_representation": "one", "gene": " GENE1 "},
            {"candidate_id": "VAR-2", "submitted_representation": "two", "gene": " GENE1 "},
        ],
        hypotheses=[{"hypothesis_id": "HYP-1", "hypothesis_type": "inheritance", "value": "supplied", "inheritance_candidate": "compound_heterozygous"}],
        pedigree_inheritance_audit=audit_request(
            variant_observations=[
                {"observation_id": "OBS-P-1", "family_member_id": "MEM-P", "candidate_variant_id": "VAR-1", "presence_state": "present", "testing_state": "tested", "confirmation_state": "confirmed"},
                {"observation_id": "OBS-P-2", "family_member_id": "MEM-P", "candidate_variant_id": "VAR-2", "presence_state": "present", "testing_state": "tested", "confirmation_state": "confirmed"},
            ],
            audit_targets=[{"audit_target_id": "TARGET-1", "hypothesis_id": "HYP-1", "candidate_variant_ids": ["VAR-1", "VAR-2"]}],
        ),
    )
    result = build_clinical_case_bundle(data)[2]
    assert result.inheritance_audits[0].status.value == "cannot_evaluate"
    assert "exact_supplied_gene_identifier_format_review_required" in {item.code for item in result.missing_information}
