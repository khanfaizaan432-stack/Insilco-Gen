from __future__ import annotations

from app.insilicopop.clinical import build_clinical_case_intake


def minimal_case(**updates):
    payload = {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-001",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "reviewer_status": "pending",
        "human_review_required": True,
    }
    payload.update(updates)
    return payload


def test_valid_minimal_clinical_intake_is_typed_and_bounded():
    result = build_clinical_case_intake(minimal_case())
    assert result.schema_version == "0.27"
    assert result.pseudonymous_case_id == "CASE-001"
    assert result.intake_completeness == "incomplete"
    assert result.human_review_required is True
    assert result.diagnosis_made is False
    assert result.variant_normalization_performed is False


def test_full_structured_intake_preserves_safe_ids_and_counts_without_inference():
    result = build_clinical_case_intake(
        minimal_case(
            genome_build="GRCh38",
            provenance=[{"source_id": "SRC-1", "source_type": "redacted_case_form", "redacted": True}],
            phenotypes=[
                {"observation_id": "PH-1", "supplied_term": "supplied finding", "hpo_id": "HP:0001250", "state": "present", "review_state": "confirmed"}
            ],
            candidate_variants=[
                {"candidate_id": "VAR-1", "submitted_representation": "submitted representation", "gene": "GENE1", "genome_build": "GRCh38", "review_state": "pending"}
            ],
            pedigree=[
                {"family_member_id": "FAM-1", "relationship_to_proband": "proband", "affected_status": "affected", "phenotype_references": ["PH-1"], "testing_availability": "available"}
            ],
            hypotheses=[
                {"hypothesis_id": "HYP-1", "hypothesis_type": "inheritance", "value": "supplied hypothesis", "inheritance_candidate": "autosomal_dominant"}
            ],
        )
    )
    assert result.intake_completeness == "complete"
    assert result.phenotype_state_counts["present"] == 1
    assert result.candidate_variant_ids == ["VAR-1"]
    assert result.pedigree_member_ids == ["FAM-1"]
    assert result.inheritance_calculation_performed is False
    assert result.supplied_hypotheses[0].inheritance_candidate == "autosomal_dominant"


def test_all_allowed_phenotype_states_and_invalid_state_handling():
    states = ["present", "absent", "unknown", "not_assessed", "resolved"]
    result = build_clinical_case_intake(
        minimal_case(phenotypes=[{"observation_id": f"PH-{index}", "supplied_term": "term", "state": state} for index, state in enumerate(states)])
    )
    assert result.phenotype_state_counts == {state: 1 for state in states}

    invalid = build_clinical_case_intake(minimal_case(phenotypes=[{"observation_id": "PH-X", "supplied_term": "term", "state": "positive"}]))
    assert invalid.intake_completeness == "invalid"
    assert any(issue.field == "phenotypes.0.state" for issue in invalid.validation_errors)


def test_duplicate_ids_missing_redaction_and_incomplete_variant_are_distinct_categories():
    result = build_clinical_case_intake(
        minimal_case(
            redaction_declared=None,
            phenotypes=[
                {"observation_id": "PH-DUP", "supplied_term": "one", "state": "present"},
                {"observation_id": "PH-DUP", "supplied_term": "two", "state": "absent"},
            ],
            candidate_variants=[{"candidate_id": "VAR-1", "submitted_representation": "submitted"}],
        )
    )
    assert {item.code for item in result.validation_errors} >= {"redaction_declaration_required", "duplicate_local_identifier"}
    assert "candidate_variant_incomplete" in {item.code for item in result.validation_warnings}
    assert result.missing_information
    assert result.policy_blocks == []
