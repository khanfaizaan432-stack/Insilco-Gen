from __future__ import annotations

import copy
import json

import pytest

from app.insilicopop.clinical.service import build_clinical_case_bundle


def member(member_id, relationship, *, affected="unknown", sex="not_recorded", testing="available"):
    return {
        "family_member_id": member_id,
        "relationship_to_proband": relationship,
        "affected_status": affected,
        "sex_for_inheritance": sex,
        "testing_availability": testing,
    }


def observation(observation_id, member_id, candidate_id, presence, *, zygosity="unknown", testing="tested", confirmation="confirmed"):
    return {
        "observation_id": observation_id,
        "family_member_id": member_id,
        "candidate_variant_id": candidate_id,
        "presence_state": presence,
        "zygosity": zygosity,
        "testing_state": testing,
        "confirmation_state": confirmation,
        "provenance_source_ids": ["SRC-1"],
    }


def relationship(relationship_id, parent_id, child_id, relationship_type="biological_parent"):
    return {
        "relationship_id": relationship_id,
        "relationship_type": relationship_type,
        "parent_member_id": parent_id,
        "child_member_id": child_id,
        "provenance_source_ids": ["SRC-1"],
    }


def phase(phase_id, candidate_ids, state, *, evidence_basis="directly_supplied", review_state="confirmed"):
    return {
        "phase_declaration_id": phase_id,
        "candidate_variant_ids": candidate_ids,
        "state": state,
        "evidence_basis": evidence_basis,
        "review_state": review_state,
        "provenance_source_ids": ["SRC-1"],
    }


def x_linked_context(
    *,
    locus="non_pseudoautosomal_x",
    sex_chromosome="sufficient_for_bounded_rule",
    mosaic="not_indicated_in_supplied_records",
):
    return {
        "locus_context": locus,
        "sex_chromosome_context": sex_chromosome,
        "mosaic_context": mosaic,
        "provenance_source_ids": ["SRC-1"],
        "review_state": "confirmed",
    }


def payload(
    hypothesis,
    *,
    members=None,
    relationships=None,
    observations=None,
    candidate_ids=None,
    genes=None,
    phases=None,
    phase_id=None,
    x_context=None,
):
    candidate_ids = candidate_ids or ["VAR-1"]
    genes = genes or ["GENE1"] * len(candidate_ids)
    return {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-V029-RULES",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "human_review_required": True,
        "genome_build": "GRCh38",
        "provenance": [{"source_id": "SRC-1", "source_type": "synthetic_fixture"}],
        "phenotypes": [{"observation_id": "PH-1", "supplied_term": "fictional finding", "state": "unknown"}],
        "candidate_variants": [
            {
                "candidate_id": candidate_id,
                "submitted_representation": f"fictional candidate {index + 1}",
                "gene": genes[index],
            }
            for index, candidate_id in enumerate(candidate_ids)
        ],
        "pedigree": members or [member("MEM-P", "proband", affected="affected")],
        "hypotheses": [
            {
                "hypothesis_id": "HYP-1",
                "hypothesis_type": "inheritance",
                "value": "supplied inheritance hypothesis",
                "inheritance_candidate": hypothesis,
            }
        ],
        "pedigree_inheritance_audit": {
            "schema_version": "0.29",
            "proband_member_id": "MEM-P",
            "relationships": relationships or [],
            "variant_observations": observations or [],
            "audit_targets": [
                {
                    "audit_target_id": "TARGET-1",
                    "hypothesis_id": "HYP-1",
                    "candidate_variant_ids": candidate_ids,
                    **({"phase_declaration_id": phase_id} if phase_id else {}),
                    **({"x_linked_context": x_context} if x_context is not None else {}),
                }
            ],
            "phase_declarations": phases or [],
            "human_review_required": True,
        },
    }


def audit(data):
    result = build_clinical_case_bundle(data)[2]
    assert result is not None
    return result


def status(result):
    return result.inheritance_audits[0].status.value


def test_autosomal_dominant_requires_explicit_vertical_support_for_consistent_status():
    members = [
        member("MEM-P", "proband", affected="affected"),
        member("MEM-A", "parent", affected="affected"),
    ]
    result = audit(
        payload(
            "autosomal_dominant",
            members=members,
            relationships=[relationship("REL-1", "MEM-A", "MEM-P")],
            observations=[
                observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="heterozygous"),
                observation("OBS-A", "MEM-A", "VAR-1", "present", zygosity="heterozygous"),
            ],
        )
    )
    assert status(result) == "consistent"
    assert result.inheritance_audits[0].phase_assessment_id is None


def test_autosomal_dominant_affected_absence_and_unaffected_carrier_are_reviewable_not_inconsistent():
    members = [
        member("MEM-P", "proband", affected="affected"),
        member("MEM-A", "relative", affected="affected"),
        member("MEM-U", "relative", affected="unaffected"),
    ]
    result = audit(
        payload(
            "autosomal_dominant",
            members=members,
            observations=[
                observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="heterozygous"),
                observation("OBS-A", "MEM-A", "VAR-1", "absent"),
                observation("OBS-U", "MEM-U", "VAR-1", "present", zygosity="heterozygous"),
            ],
        )
    )
    assert status(result) == "partially_consistent"
    assert result.mendelian_inconsistencies == []
    assert {item.code for item in result.review_actions} >= {
        "review_affected_relative_candidate_absence",
        "review_unaffected_supplied_carrier",
    }


def test_autosomal_dominant_candidate_absent_in_both_supplied_parents_is_not_automatically_impossible():
    members = [member("MEM-P", "proband", affected="affected"), member("MEM-A", "parent"), member("MEM-B", "parent")]
    result = audit(
        payload(
            "autosomal_dominant",
            members=members,
            relationships=[relationship("REL-A", "MEM-A", "MEM-P"), relationship("REL-B", "MEM-B", "MEM-P")],
            observations=[
                observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="heterozygous"),
                observation("OBS-A", "MEM-A", "VAR-1", "absent"),
                observation("OBS-B", "MEM-B", "VAR-1", "absent"),
            ],
        )
    )
    assert status(result) == "partially_consistent"
    assert result.mendelian_inconsistencies == []


def test_autosomal_recessive_homozygous_record_and_missing_second_allele_are_distinct():
    homozygous = audit(
        payload(
            "autosomal_recessive",
            observations=[observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="homozygous")],
        )
    )
    assert status(homozygous) == "consistent"
    heterozygous = audit(
        payload(
            "autosomal_recessive",
            observations=[observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="heterozygous")],
        )
    )
    assert status(heterozygous) == "missing_evidence"
    assert "required_second_candidate_missing" in {item.code for item in heterozygous.missing_information}


def test_x_linked_missing_context_is_missing_evidence_even_when_candidate_text_says_x():
    data = payload(
        "x_linked",
        members=[member("MEM-P", "proband", affected="affected", sex="male")],
        observations=[observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="hemizygous")],
    )
    data["candidate_variants"][0]["chromosome"] = "X"
    result = audit(data)
    assert status(result) == "missing_evidence"
    assert "x_linked_audit_context_required" in {item.code for item in result.missing_information}


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        (x_linked_context(locus="unknown"), "cannot_evaluate"),
        (x_linked_context(locus="pseudoautosomal_x"), "cannot_evaluate"),
        (x_linked_context(locus="non_x"), "cannot_evaluate"),
        (x_linked_context(sex_chromosome="other_or_complex"), "cannot_evaluate"),
        (x_linked_context(sex_chromosome="unknown"), "cannot_evaluate"),
        (x_linked_context(mosaic="indicated_or_possible"), "cannot_evaluate"),
        (x_linked_context(mosaic="unknown"), "cannot_evaluate"),
    ],
)
def test_x_linked_context_gates_father_to_son_conflict(context, expected):
    members = [member("MEM-P", "proband", affected="affected", sex="male"), member("MEM-A", "parent", affected="affected", sex="male")]
    result = audit(
        payload(
            "x_linked",
            members=members,
            relationships=[relationship("REL-1", "MEM-A", "MEM-P")],
            observations=[
                observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="hemizygous"),
                observation("OBS-A", "MEM-A", "VAR-1", "present", zygosity="hemizygous"),
            ],
            x_context=context,
        )
    )
    assert status(result) == expected
    assert "x_linked_father_to_son_supplied_record_conflict" not in {item.code for item in result.mendelian_inconsistencies}


def test_x_linked_rules_require_fully_gated_non_par_context_and_safe_wording():
    missing_sex = audit(
        payload("x_linked", observations=[observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="hemizygous")], x_context=x_linked_context())
    )
    assert status(missing_sex) == "missing_evidence"
    members = [
        member("MEM-P", "proband", affected="affected", sex="male"),
        member("MEM-A", "parent", affected="affected", sex="male"),
    ]
    conflict = audit(
        payload(
            "x_linked",
            members=members,
            relationships=[relationship("REL-1", "MEM-A", "MEM-P")],
            observations=[
                observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="hemizygous"),
                observation("OBS-A", "MEM-A", "VAR-1", "present", zygosity="hemizygous"),
            ],
            x_context=x_linked_context(),
        )
    )
    assert status(conflict) == "inconsistent"
    assert "x_linked_father_to_son_supplied_record_conflict" in {item.code for item in conflict.mendelian_inconsistencies}
    text = json.dumps(conflict.model_dump(mode="json"), sort_keys=True).casefold()
    assert "non-pseudoautosomal x-linked candidate and parent-child observation records conflict" in text
    assert all(term not in text for term in ["paternity", "non-parentage", "relationship discrepancy", "sample swap", "biological impossibility"])


def test_x_linked_female_record_is_retained_for_review():
    result = audit(
        payload(
            "x_linked",
            members=[member("MEM-P", "proband", affected="affected", sex="female")],
            observations=[observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="heterozygous")],
            x_context=x_linked_context(),
        )
    )
    assert status(result) == "partially_consistent"
    assert "review_female_x_linked_record" in {item.code for item in result.review_actions}


def test_mitochondrial_maternal_line_paternal_review_and_heteroplasmy_are_bounded():
    maternal_members = [member("MEM-P", "proband", affected="affected"), member("MEM-M", "parent", affected="affected", sex="female")]
    consistent = audit(
        payload(
            "mitochondrial",
            members=maternal_members,
            relationships=[relationship("REL-M", "MEM-M", "MEM-P")],
            observations=[observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="homoplasmic"), observation("OBS-M", "MEM-M", "VAR-1", "present", zygosity="homoplasmic")],
        )
    )
    assert status(consistent) == "consistent"
    heteroplasmic_data = copy.deepcopy(consistent.model_dump(mode="json"))
    assert heteroplasmic_data["inheritance_clinically_established"] is False
    heteroplasmic = audit(
        payload(
            "mitochondrial",
            members=maternal_members,
            relationships=[relationship("REL-M", "MEM-M", "MEM-P")],
            observations=[observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="heteroplasmic"), observation("OBS-M", "MEM-M", "VAR-1", "present", zygosity="heteroplasmic")],
        )
    )
    assert status(heteroplasmic) == "partially_consistent"
    paternal_members = [member("MEM-P", "proband", affected="affected"), member("MEM-F", "parent", affected="affected", sex="male")]
    paternal = audit(
        payload(
            "mitochondrial",
            members=paternal_members,
            relationships=[relationship("REL-F", "MEM-F", "MEM-P")],
            observations=[observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="homoplasmic"), observation("OBS-F", "MEM-F", "VAR-1", "present", zygosity="homoplasmic")],
        )
    )
    assert status(paternal) == "partially_consistent"
    assert paternal.mendelian_inconsistencies == []
    assert "paternal_mtdna_observation_requires_review" in {item.code for item in paternal.review_actions}
    paternal_text = json.dumps(paternal.model_dump(mode="json"), sort_keys=True).casefold()
    assert all(term not in paternal_text for term in ["paternity", "non-parentage", "sample swap", "biological impossibility", "severity", "recurrence risk"])

    insufficient = audit(
        payload(
            "mitochondrial",
            members=paternal_members,
            relationships=[relationship("REL-F", "MEM-F", "MEM-P")],
            observations=[observation("OBS-P", "MEM-P", "VAR-1", "present"), observation("OBS-F", "MEM-F", "VAR-1", "present")],
        )
    )
    assert status(insufficient) == "cannot_evaluate"
    assert insufficient.mendelian_inconsistencies == []


def de_novo_payload(parent_a_presence="absent", *, parent_b_testing="tested", include_parent_b=True):
    members = [member("MEM-P", "proband", affected="affected"), member("MEM-A", "parent")]
    relationships = [relationship("REL-A", "MEM-A", "MEM-P")]
    observations = [
        observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="heterozygous"),
        observation("OBS-A", "MEM-A", "VAR-1", parent_a_presence),
    ]
    if include_parent_b:
        members.append(member("MEM-B", "parent"))
        relationships.append(relationship("REL-B", "MEM-B", "MEM-P"))
        observations.append(observation("OBS-B", "MEM-B", "VAR-1", "absent", testing=parent_b_testing))
    return payload("de_novo", members=members, relationships=relationships, observations=observations)


def test_de_novo_exact_prerequisites_and_wording():
    result = audit(de_novo_payload())
    assert status(result) == "consistent"
    explanation = result.inheritance_audits[0].bounded_explanation
    assert explanation == "Consistent with the supplied de novo hypothesis under the bounded available records."
    assert "confirmed de novo" not in explanation.casefold()
    assert "established de novo" not in explanation.casefold()
    assert "proven de novo" not in explanation.casefold()


def test_de_novo_positive_untested_and_missing_parent_states_are_explicit():
    positive = audit(de_novo_payload(parent_a_presence="present"))
    assert status(positive) == "inconsistent"
    untested = audit(de_novo_payload(parent_b_testing="not_tested"))
    assert status(untested) == "missing_evidence"
    missing_parent = audit(de_novo_payload(include_parent_b=False))
    assert status(missing_parent) == "missing_evidence"
    assert "two_supplied_parent_records_required" in {item.code for item in missing_parent.missing_relative_requirements}


def compound_payload(*, genes=("GENE1", "GENE1"), phase_state="confirmed_in_trans", evidence_basis="directly_supplied", review_state="confirmed", include_phase=True):
    candidate_ids = ["VAR-1", "VAR-2"]
    phases = [phase("PHASE-1", candidate_ids, phase_state, evidence_basis=evidence_basis, review_state=review_state)] if include_phase else []
    return payload(
        "compound_heterozygous",
        candidate_ids=candidate_ids,
        genes=list(genes),
        observations=[
            observation("OBS-P-1", "MEM-P", "VAR-1", "present", zygosity="heterozygous"),
            observation("OBS-P-2", "MEM-P", "VAR-2", "present", zygosity="heterozygous"),
        ],
        phases=phases,
        phase_id="PHASE-1" if include_phase else None,
    )


def test_compound_heterozygous_phase_states_are_exact_and_presumed_is_not_promoted():
    confirmed = audit(compound_payload())
    assert status(confirmed) == "consistent"
    assert confirmed.phase_assessments[0].assessment == "confirmed_in_trans"
    presumed = audit(compound_payload(phase_state="presumed_in_trans", evidence_basis="supplied_presumed", review_state="pending"))
    assert status(presumed) == "partially_consistent"
    assert presumed.phase_assessments[0].supplied_state == "presumed_in_trans"
    assert presumed.phase_assessments[0].assessment == "presumed_in_trans"
    unknown = audit(compound_payload(phase_state="unknown", evidence_basis="not_supplied", review_state="pending"))
    assert status(unknown) == "missing_evidence"
    cis = audit(compound_payload(phase_state="confirmed_in_cis"))
    assert status(cis) == "inconsistent"


def test_unconfirmed_phase_declaration_is_not_silently_treated_as_confirmed():
    result = audit(compound_payload(review_state="pending"))
    assert status(result) == "missing_evidence"
    assert result.phase_assessments[0].assessment == "unknown"


@pytest.mark.parametrize(
    ("genes", "expected"),
    [
        ((None, "GENE1"), "missing_evidence"),
        (("GENE1", None), "missing_evidence"),
        (("GENE1", "gene1"), "cannot_evaluate"),
        (("GENE1", "GENE2"), "cannot_evaluate"),
    ],
)
def test_compound_heterozygous_requires_same_exact_non_empty_gene_identifier(genes, expected):
    result = audit(compound_payload(genes=genes))
    assert status(result) == expected
    text = json.dumps(result.model_dump(mode="json"), sort_keys=True).casefold()
    if expected == "missing_evidence":
        assert "no identifier or alias is inferred" in text
    else:
        assert "no equivalence is inferred" in result.inheritance_audits[0].bounded_explanation.casefold()
    assert "normalized" not in text


def test_two_positive_only_parent_observations_are_insufficient_for_in_trans_support():
    candidate_ids = ["VAR-1", "VAR-2"]
    members = [member("MEM-P", "proband", affected="affected"), member("MEM-A", "parent"), member("MEM-B", "parent")]
    result = audit(
        payload(
            "compound_heterozygous",
            candidate_ids=candidate_ids,
            genes=["GENE1", "GENE1"],
            members=members,
            relationships=[relationship("REL-A", "MEM-A", "MEM-P"), relationship("REL-B", "MEM-B", "MEM-P")],
            observations=[
                observation("OBS-P-1", "MEM-P", "VAR-1", "present", zygosity="heterozygous"),
                observation("OBS-P-2", "MEM-P", "VAR-2", "present", zygosity="heterozygous"),
                observation("OBS-A-1", "MEM-A", "VAR-1", "present", zygosity="heterozygous"),
                observation("OBS-B-2", "MEM-B", "VAR-2", "present", zygosity="heterozygous"),
            ],
        )
    )
    assert status(result) == "missing_evidence"
    assert result.phase_assessments[0].assessment == "unknown"
    assert "reciprocal_parental_phase_observations_required" in {item.code for item in result.phase_requirements}


def test_complete_reciprocal_parental_observations_support_separate_phase_assessment():
    candidate_ids = ["VAR-1", "VAR-2"]
    members = [member("MEM-P", "proband", affected="affected"), member("MEM-A", "parent"), member("MEM-B", "parent")]
    result = audit(
        payload(
            "compound_heterozygous",
            candidate_ids=candidate_ids,
            genes=["GENE1", "GENE1"],
            members=members,
            relationships=[relationship("REL-A", "MEM-A", "MEM-P"), relationship("REL-B", "MEM-B", "MEM-P")],
            observations=[
                observation("OBS-P-1", "MEM-P", "VAR-1", "present", zygosity="heterozygous"),
                observation("OBS-P-2", "MEM-P", "VAR-2", "present", zygosity="heterozygous"),
                observation("OBS-A-1", "MEM-A", "VAR-1", "present", zygosity="heterozygous"),
                observation("OBS-A-2", "MEM-A", "VAR-2", "absent"),
                observation("OBS-B-1", "MEM-B", "VAR-1", "absent"),
                observation("OBS-B-2", "MEM-B", "VAR-2", "present", zygosity="heterozygous"),
            ],
        )
    )
    assert status(result) == "consistent"
    assert result.phase_assessments[0].supplied_state == "not_supplied"
    assert result.phase_assessments[0].assessment == "supported_in_trans_by_supplied_parental_observations"
    assert len(result.phase_assessments[0].supporting_observation_ids) == 4


@pytest.mark.parametrize("second_parent_first_presence", [None, "present"])
def test_missing_or_conflicting_reciprocal_parental_observation_is_not_accepted(second_parent_first_presence):
    observations = [
        observation("OBS-P-1", "MEM-P", "VAR-1", "present", zygosity="heterozygous"),
        observation("OBS-P-2", "MEM-P", "VAR-2", "present", zygosity="heterozygous"),
        observation("OBS-A-1", "MEM-A", "VAR-1", "present"),
        observation("OBS-A-2", "MEM-A", "VAR-2", "absent"),
        observation("OBS-B-2", "MEM-B", "VAR-2", "present"),
    ]
    if second_parent_first_presence is not None:
        observations.append(observation("OBS-B-1", "MEM-B", "VAR-1", second_parent_first_presence))
    result = audit(
        payload(
            "compound_heterozygous",
            candidate_ids=["VAR-1", "VAR-2"],
            genes=["GENE1", "GENE1"],
            members=[member("MEM-P", "proband", affected="affected"), member("MEM-A", "parent"), member("MEM-B", "parent")],
            relationships=[relationship("REL-A", "MEM-A", "MEM-P"), relationship("REL-B", "MEM-B", "MEM-P")],
            observations=observations,
        )
    )
    assert status(result) == "missing_evidence"
    assert result.phase_assessments[0].assessment == "unknown"
    assert "reciprocal_parental_phase_observations_required" in {item.code for item in result.phase_requirements}


def test_supplied_unknown_phase_remains_unknown_with_reciprocal_parental_evidence():
    data = compound_payload(phase_state="unknown", evidence_basis="not_supplied", review_state="pending")
    declaration_before = json.dumps(data["pedigree_inheritance_audit"]["phase_declarations"][0], separators=(",", ":"), ensure_ascii=False)
    members = [member("MEM-P", "proband", affected="affected"), member("MEM-A", "parent"), member("MEM-B", "parent")]
    data["pedigree"] = members
    data["pedigree_inheritance_audit"]["relationships"] = [relationship("REL-A", "MEM-A", "MEM-P"), relationship("REL-B", "MEM-B", "MEM-P")]
    data["pedigree_inheritance_audit"]["variant_observations"].extend([
        observation("OBS-A-1", "MEM-A", "VAR-1", "present"),
        observation("OBS-A-2", "MEM-A", "VAR-2", "absent"),
        observation("OBS-B-1", "MEM-B", "VAR-1", "absent"),
        observation("OBS-B-2", "MEM-B", "VAR-2", "present"),
    ])
    result = audit(data)
    declaration_after = json.dumps(data["pedigree_inheritance_audit"]["phase_declarations"][0], separators=(",", ":"), ensure_ascii=False)
    assert declaration_after == declaration_before
    assert status(result) == "missing_evidence"
    assert result.phase_assessments[0].supplied_state == "unknown"
    assert result.phase_assessments[0].assessment == "unknown"


@pytest.mark.parametrize("hypothesis", ["unknown", "other"])
def test_unknown_and_other_hypotheses_cannot_be_evaluated(hypothesis):
    result = audit(payload(hypothesis, observations=[observation("OBS-P", "MEM-P", "VAR-1", "present")]))
    assert status(result) == "cannot_evaluate"


def test_parent_child_transmission_output_uses_bounded_public_terminology():
    data = de_novo_payload()
    result = audit(data)
    dumped = result.model_dump(mode="json")
    assert "available_parent_child_transmission_summary" in dumped
    assert "parent_child_transmission_records" in dumped
    assert "available_meioses" not in json.dumps(dumped).casefold()
    summary = result.available_parent_child_transmission_summary
    assert summary.evaluable_transmission_count == 2
    assert summary.non_evaluable_transmission_count == 0


def test_equivalent_reordered_inputs_and_issue_ids_are_stable():
    data = de_novo_payload(parent_b_testing="not_tested")
    first = audit(data)
    reordered = copy.deepcopy(data)
    reordered["pedigree"] = list(reversed(reordered["pedigree"]))
    declaration = reordered["pedigree_inheritance_audit"]
    declaration["relationships"] = list(reversed(declaration["relationships"]))
    declaration["variant_observations"] = list(reversed(declaration["variant_observations"]))
    second = audit(reordered)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [item.issue_id for item in first.missing_relative_requirements] == [item.issue_id for item in second.missing_relative_requirements]


def test_result_categories_are_separate_and_not_duplicated():
    data = de_novo_payload(include_parent_b=False)
    result = audit(data)
    category_ids = {
        "warnings": {item.issue_id for item in result.validation_warnings},
        "relationships": {item.issue_id for item in result.relationship_issues},
        "mendelian": {item.issue_id for item in result.mendelian_inconsistencies},
        "relative": {item.issue_id for item in result.missing_relative_requirements},
    }
    for name, ids in category_ids.items():
        for other_name, other_ids in category_ids.items():
            if name != other_name:
                assert ids.isdisjoint(other_ids)


def test_all_result_category_finding_ids_are_pairwise_disjoint():
    result = audit(de_novo_payload(include_parent_b=False))
    categories = {
        "validation_errors": {item.issue_id for item in result.validation_errors},
        "validation_warnings": {item.issue_id for item in result.validation_warnings},
        "missing_information": {item.issue_id for item in result.missing_information},
        "policy_blocks": {item.issue_id for item in result.policy_blocks},
        "relationship_issues": {item.issue_id for item in result.relationship_issues},
        "mendelian_inconsistencies": {item.issue_id for item in result.mendelian_inconsistencies},
        "inheritance_audits": {item.audit_id for item in result.inheritance_audits},
        "phase_requirements": {item.issue_id for item in result.phase_requirements},
        "missing_relative_requirements": {item.issue_id for item in result.missing_relative_requirements},
        "review_actions": {item.action_id for item in result.review_actions},
    }
    for name, ids in categories.items():
        for other_name, other_ids in categories.items():
            if name != other_name:
                assert ids.isdisjoint(other_ids)


def test_v029_outputs_contain_no_prohibited_relationship_or_speculative_cause_wording():
    outputs = [audit(de_novo_payload())]
    outputs.append(
        audit(
            payload(
                "autosomal_dominant",
                members=[member("MEM-P", "proband", affected="affected"), member("MEM-U", "relative", affected="unaffected")],
                observations=[
                    observation("OBS-P", "MEM-P", "VAR-1", "present", zygosity="heterozygous"),
                    observation("OBS-U", "MEM-U", "VAR-1", "present", zygosity="heterozygous"),
                ],
            )
        )
    )
    text = json.dumps([result.model_dump(mode="json") for result in outputs], sort_keys=True).casefold()
    prohibited = [
        "paternity",
        "non-parentage",
        "relationship-discrepancy",
        "biological-discrepancy",
        "adoption",
        "donor conception",
        "consanguinity",
        "parental mosaicism",
        "sample-swap",
        "sample swap",
        "penetrance",
        "lod score",
        "likelihood ratio",
        "segregation strength",
        "recurrence risk",
        "biological impossibility",
    ]
    assert all(term not in text for term in prohibited)
    assert all(result.human_review_required is True for result in outputs)
    assert all(result.diagnosis_made is False for result in outputs)
    assert all(result.pathogenicity_conclusion_made is False for result in outputs)
