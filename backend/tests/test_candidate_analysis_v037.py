from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.agent.state import AgentState
from app.insilicopop.agent.workbench import WorkbenchRunStore
from app.insilicopop.cli import main as cli_main
from app.insilicopop.clinical import build_clinical_case_v035_bundle
from app.insilicopop.clinical.candidate_analysis import _validated_compound_pair
from app.insilicopop.clinical.candidate_analysis_models import (
    CANDIDATE_FIXED_FAMILY_GQ_THRESHOLD,
    CandidateAnalysisState,
    CandidateAnalysisResult,
    CandidateAnalysisRequest,
    CandidateContextInput,
    CandidateRankingComponent,
    CandidateRankingRule,
    FrequencyContext,
    NegativeUnresolvedResult,
    sha256_hex,
)
import app.main as main_module
from app.main import app


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "examples" / "insilicopop_demo" / "canonical_v037_candidate_analysis.json"
EXPECTED_PATH = REPO_ROOT / "examples" / "insilicopop_demo" / "expected_v037_candidate_analysis_output.json"
NODE = shutil.which("node")
client = TestClient(app)

CAND_RESULT = "candidate-v037-587112d0f7e70b149ae9"
CAND_INDEL = "candidate-v037-4995d09756964b7166e8"
CAND_MULTI_A = "candidate-v037-2ce0a1c76d0b8293b384"
CAND_MULTI_B = "candidate-v037-3a5d83c0d8322e941a40"
CAND_CNV = "candidate-v037-ee1542f46cfa1dc60227"


def _payload() -> dict:
    overlay = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    base_path = FIXTURE_PATH.parent / overlay.pop("base_fixture")
    base = json.loads(base_path.read_text(encoding="utf-8"))
    base.update(overlay)
    return base


def _analysis(payload: dict):
    return build_clinical_case_v035_bundle(payload)[0].candidate_analysis


def _compound_probe_inputs(*, phase: str = "phase_unknown", gene_a: str | None = "GENE1", gene_b: str | None = "GENE1"):
    def record(record_id: str, position: int, alternate: str, gene: str | None):
        annotations = () if gene is None else (SimpleNamespace(key="gene", value=gene),)
        return SimpleNamespace(
            record_id=record_id,
            source_record_id=f"source-{record_id}",
            source_record_sha256=("a" * 63 + ("1" if record_id == "RECORD-A" else "2")),
            chromosome="1",
            position=position,
            reference_allele="A",
            alternate_allele=alternate,
            source_alt_index=1,
            supplied_annotations=annotations,
        )

    record_a = record("RECORD-A", 100, "G", gene_a)
    record_b = record("RECORD-B", 200, "T", gene_b)
    contexts = {
        "A": CandidateContextInput(
            candidate_id="A",
            compound_heterozygosity_partner_candidate_id="B",
            compound_gene_context=None,
            supplied_phase=phase,
        ),
        "B": CandidateContextInput(
            candidate_id="B",
            compound_heterozygosity_partner_candidate_id="A",
            compound_gene_context=None,
            supplied_phase=phase,
        ),
    }
    gateway = SimpleNamespace(
        package_id="PKG-036",
        package_version="fixture-1",
        package_identity_sha256="a" * 64,
    )
    return contexts, {"A": record_a, "B": record_b}, gateway


def _rehashed_result_payload(payload: dict) -> dict:
    output_payload = {
        "ranked_candidates": payload["ranked_candidates"],
        "excluded_candidates": payload["excluded_candidates"],
        "exclusion_trace": payload["exclusion_trace"],
        "negative_unresolved_result": payload["negative_unresolved_result"],
        "rule": payload["ranking_rule"],
    }
    payload["ranking_output_identity_sha256"] = sha256_hex(output_payload)
    analysis_payload = copy.deepcopy(payload)
    for key in ("analysis_identity_sha256", "result_integrity_sha256", "runtime_metadata"):
        analysis_payload.pop(key, None)
    payload["analysis_identity_sha256"] = sha256_hex(analysis_payload)
    integrity_payload = copy.deepcopy(payload)
    for key in ("result_integrity_sha256", "runtime_metadata"):
        integrity_payload.pop(key, None)
    payload["result_integrity_sha256"] = sha256_hex(integrity_payload)
    return payload


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


def test_v037_fixture_and_expected_cli_summary_are_deterministic(capsys):
    first = _analysis(_payload())
    second = _analysis(_payload())
    assert first is not None and second is not None
    assert first.model_dump(mode="json") == second.model_dump(mode="json")

    assert cli_main(["v037-demo", "--fixture", str(FIXTURE_PATH)]) == 0
    actual = json.loads(capsys.readouterr().out)
    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    assert actual == expected


def test_v037_contract_is_immutable_and_exposes_score_arithmetic():
    result = _analysis(_payload())
    assert result is not None
    assert result.schema_version == "0.37"
    assert isinstance(result.ranked_candidates, tuple)
    assert isinstance(result.ranked_candidates[0].ranking_components, tuple)
    component = next(
        item
        for item in result.ranked_candidates[0].ranking_components
        if item.component_id == "phenotype_match"
    )
    assert component.weight == 4.0
    assert component.numerical_contribution == 4.0
    assert result.ranked_candidates[0].aggregate_score == round(
        sum(item.numerical_contribution or 0 for item in result.ranked_candidates[0].ranking_components),
        6,
    )
    with pytest.raises(ValidationError):
        result.ranked_candidates[0].aggregate_score = 0.0
    detached = result.model_dump(mode="json")
    detached["ranked_candidates"][0]["aggregate_score"] = -999
    assert result.ranked_candidates[0].aggregate_score != -999


def test_v037_phenotype_family_exclusion_and_safety_states_are_explicit():
    result = _analysis(_payload())
    assert result is not None
    ranked = {item.candidate_identity.candidate_id: item for item in result.ranked_candidates}
    assert ranked[CAND_RESULT].phenotype_match.exact_hpo_ids == ("HP:0001250",)
    assert ranked[CAND_MULTI_A].phenotype_match.related_hpo_ids == ("HP:0001260",)
    assert ranked[CAND_MULTI_A].inheritance_compatibility.supplied_inheritance_statements == ()
    assert any(item.category == "inheritance_statement" for item in ranked[CAND_MULTI_A].missing_information)
    assert ranked[CAND_RESULT].inheritance_compatibility.de_novo_state.value == "insufficient_information"
    assert result.family_segregation.family_shape.value == "trio"
    assert result.family_segregation.no_relationship_inference is True
    assert {item.candidate_id for item in result.excluded_candidates} == {"CAND-UNBOUND-037", CAND_CNV}
    assert any(item.code.value == "unsupported_variant_scope" for item in result.exclusion_trace)
    assert any(item.code.value == "source_record_not_found" for item in result.exclusion_trace)
    assert result.negative_unresolved_result.unsupported_result_types == ("copy_number_out_of_scope",)
    assert result.human_review_required is True
    assert result.diagnosis_made is False
    assert result.final_acmg_classification_made is False
    assert result.external_tools_executed is False
    assert "patient does not have" not in result.negative_unresolved_result.summary.casefold()
    assert "the test is negative" not in result.negative_unresolved_result.summary.casefold()


def test_v037_missing_components_have_no_score_and_stale_inputs_require_replay():
    payload = _payload()
    result = _analysis(payload)
    assert result is not None
    multi_a = next(item for item in result.ranked_candidates if item.candidate_identity.candidate_id == CAND_MULTI_A)
    missing_component = next(item for item in multi_a.ranking_components if item.component_id == "missing_information")
    unresolved_component = next(item for item in multi_a.ranking_components if item.component_id == "unresolved_uncertainty")
    assert missing_component.state.value == "missing"
    assert missing_component.numerical_contribution is None
    assert unresolved_component.numerical_contribution is None

    stale_payload = copy.deepcopy(payload)
    stale_payload["candidate_analysis"]["expected_result_package_identity_sha256"] = "0" * 64
    stale = _analysis(stale_payload)
    assert stale is not None
    assert stale.analysis_status == CandidateAnalysisState.STALE
    assert "result_package" in stale.stale_input_codes
    assert not stale.ranked_candidates
    assert all(item.exclusion_history for item in stale.excluded_candidates)


@pytest.mark.parametrize(
    ("field", "code"),
    (
        ("expected_phenotype_snapshot_sha256", "phenotype_snapshot"),
        ("expected_family_snapshot_sha256", "family_snapshot"),
        ("expected_assay_coverage_snapshot_sha256", "assay_coverage_snapshot"),
        ("ranking_rule_version", "ranking_rule"),
        ("ranking_weight_version", "ranking_rule"),
    ),
)
def test_v037_all_versioned_snapshot_and_rule_inputs_require_replay(field, code):
    payload = _payload()
    payload["candidate_analysis"][field] = "0" * 64 if field.startswith("expected_") else "stale-v0.37-rule"
    stale = _analysis(payload)
    assert stale is not None
    assert stale.analysis_status == CandidateAnalysisState.STALE
    assert code in stale.stale_input_codes
    restored = CandidateAnalysisResult.model_validate(stale.model_dump(mode="json"))
    assert restored == stale


@pytest.mark.parametrize(
    ("member_count", "shape"),
    ((1, "singleton"), (2, "duo"), (4, "extended_family")),
)
def test_v037_family_shapes_remain_supplied_and_non_inferential(member_count, shape):
    payload = _payload()
    payload["pedigree_inheritance_audit"] = None
    payload["pedigree"] = copy.deepcopy(payload["pedigree"][:member_count])
    if member_count == 4:
        payload["pedigree"].append(
            {
                "family_member_id": "SIBLING-037",
                "relationship_to_proband": "biological sibling",
                "affected_status": "unknown",
                "sex_for_inheritance": "unknown",
                "testing_availability": "unavailable",
                "provenance": [{"source_id": "FAMILY-SRC-037", "source_type": "synthetic_family_fixture"}],
            }
        )
    result = _analysis(payload)
    assert result is not None
    assert result.family_segregation.family_shape.value == shape
    assert result.family_segregation.no_relationship_inference is True
    assert all(item.relationship_state.value in {"supplied_relationship", "missing_relationship"} for item in result.family_segregation.observations)


def test_v037_family_quality_phase_compound_and_x_linked_states_are_visible():
    payload = _payload()
    context = next(item for item in payload["candidate_analysis"]["candidate_contexts"] if item["candidate_id"] == CAND_MULTI_A)
    context.update(
        {
            "inheritance_context_state": "supplied",
            "supplied_inheritance": ["compound_heterozygous", "x_linked"],
            "supplied_phase": "confirmed_trans",
            "phase_evidence": "supplied family phase record",
            "compound_heterozygosity_partner_candidate_id": CAND_INDEL,
            "x_linked_compatibility": "compatible",
        }
    )
    mother_binding = next(item for item in payload["candidate_analysis"]["family_sample_bindings"] if item["family_member_id"] == "MOTHER-037")
    mother_binding["genotype_quality_state"] = "negative"
    result = _analysis(payload)
    assert result is not None
    multi_a = next(item for item in result.ranked_candidates if item.candidate_identity.candidate_id == CAND_MULTI_A)
    inheritance = multi_a.inheritance_compatibility
    assert inheritance.x_linked_state.value == "positive"
    assert inheritance.compound_heterozygosity_state.value == "insufficient_information"
    assert inheritance.compound_partner_candidate_id == CAND_INDEL
    assert inheritance.phase_state.value != "confirmed_trans"
    assert f"compound partner={CAND_INDEL}" in inheritance.explanation
    de_novo_candidate = next(item for item in result.ranked_candidates if item.candidate_identity.candidate_id == CAND_RESULT)
    assert de_novo_candidate.inheritance_compatibility.de_novo_state.value != "deterministically_supported_de_novo"
    assert "MOTHER-037" not in de_novo_candidate.inheritance_compatibility.low_quality_member_ids
    mother_observation = next(
        item for item in de_novo_candidate.family_segregation_observations if item.family_member_id == "MOTHER-037"
    )
    assert mother_observation.observed_genotype_quality == 80.0
    assert de_novo_candidate.inheritance_compatibility.de_novo_state.value == "insufficient_information"

    mismatched_payload = _payload()
    next(item for item in mismatched_payload["candidate_analysis"]["family_sample_bindings"] if item["family_member_id"] == "MOTHER-037")["package_id"] = "OTHER-PACKAGE-037"
    mismatched_result = _analysis(mismatched_payload)
    assert mismatched_result is not None
    mismatched = next(item for item in mismatched_result.ranked_candidates if item.candidate_identity.candidate_id == CAND_RESULT)
    assert mismatched.inheritance_compatibility.de_novo_state.value != "deterministically_supported_de_novo"
    assert any("do not all point to the supplied result package" in item.statement for item in mismatched.unresolved_uncertainties)
    assert any(
        item.source_id == "FAMILY-SRC-037"
        for observation in mismatched.family_segregation_observations
        for item in observation.provenance
    )


def test_v037_assay_scope_and_poor_coverage_are_distinct_traces():
    payload = _payload()
    outside = next(item for item in payload["candidate_analysis"]["candidate_contexts"] if item["candidate_id"] == CAND_MULTI_A)
    outside["gene"] = "GENE-NOT-REPORTABLE"
    outside_result = _analysis(payload)
    assert outside_result is not None
    outside_trace = next(item for item in outside_result.exclusion_trace if item.candidate_id == CAND_MULTI_A)
    assert outside_trace.code.value == "invalid_source_binding"
    assert "source annotation" in outside_trace.reason

    poor_result = _analysis(_payload())
    assert poor_result is not None
    assert any(item.code.value == "unsupported_variant_scope" for item in poor_result.exclusion_trace)


def test_v037_ties_are_preserved_with_stable_presentation_order():
    payload = _payload()
    payload["candidate_variants"] = []
    payload["pedigree"] = []
    payload["hypotheses"] = []
    payload["pedigree_inheritance_audit"] = None
    contexts = payload["candidate_analysis"]["candidate_contexts"]
    first = copy.deepcopy(next(item for item in contexts if item["candidate_id"] == CAND_RESULT))
    second = copy.deepcopy(next(item for item in contexts if item["candidate_id"] == CAND_MULTI_B))
    first["candidate_id"] = CAND_RESULT
    first["source_record_id"] = "vcf-record-d552bedd0adc6e4c8e5c"
    second["candidate_id"] = CAND_MULTI_B
    second["source_record_id"] = "vcf-record-aa4d7899f999e76a0434"
    for item in (first, second):
        item.pop("gene", None)
        item.pop("transcript", None)
        item["consequence"] = None
        item["transcript_relevance"] = "not_assessed"
        item["gene_disease_validity"] = "not_assessed"
        item["phenotype_hpo_ids"] = []
        item["phenotype_specificity_score"] = None
        item["onset_compatibility"] = "not_assessed"
        item["population_frequency"] = None
        item["supplied_inheritance"] = []
        item["quality_state"] = "not_assessed"
        item["qc_state"] = "not_assessed"
    payload["candidate_analysis"]["candidate_contexts"] = [first, second]
    payload["candidate_analysis"]["evidence"] = []
    result = _analysis(payload)
    assert result is not None
    tied = [item for item in result.ranked_candidates if item.candidate_identity.candidate_id in {CAND_RESULT, CAND_MULTI_B}]
    assert len(tied) == 2
    assert tied[0].aggregate_score == tied[1].aggregate_score
    assert tied[0].deterministic_rank == tied[1].deterministic_rank
    assert all(item.tied is True for item in tied)
    assert tied[0].tie_group_id == tied[1].tie_group_id
    assert "stable presentation" in tied[0].tie_break_explanation


def test_v037_source_binding_is_canonical_and_cryptographically_complete():
    result = _analysis(_payload())
    assert result is not None
    identity = next(
        item.candidate_identity
        for item in result.ranked_candidates
        if item.candidate_identity.candidate_id == CAND_RESULT
    )
    source = identity.source_record
    assert identity.candidate_id == CAND_RESULT
    assert identity.stable_candidate_id.startswith("stable-candidate-v037-")
    assert source.candidate_schema_version == "0.37"
    assert source.gateway_record_id == "vcf-record-d552bedd0adc6e4c8e5c"
    assert source.source_record_key == "vcf-source-6404fd5ac340275e2e78"
    assert source.package_id == "PKG-RESULT-036"
    assert len(source.package_identity_sha256) == 64
    assert len(source.manifest_identity_sha256) == 64
    assert len(source.invocation_identity_sha256) == 64
    assert len(source.source_record_sha256) == 64
    assert (source.chromosome, source.position, source.reference_allele, source.alternate_allele, source.source_alt_index) == (
        "1",
        100,
        "A",
        "G",
        1,
    )
    assert (source.gene, source.transcript) == ("GENE1", "transcript1")

    alias_payload = _payload()
    alias_context = next(
        item for item in alias_payload["candidate_analysis"]["candidate_contexts"] if item["candidate_id"] == CAND_RESULT
    )
    alias_context["candidate_id"] = "CAND-ARBITRARY-ALIAS-037"
    alias_result = _analysis(alias_payload)
    assert alias_result is not None
    assert CAND_RESULT not in {item.candidate_identity.candidate_id for item in alias_result.ranked_candidates}
    alias_trace = next(item for item in alias_result.exclusion_trace if item.candidate_id == "CAND-ARBITRARY-ALIAS-037")
    assert alias_trace.code.value == "invalid_source_binding"

    coordinate_payload = _payload()
    coordinate_context = next(
        item for item in coordinate_payload["candidate_analysis"]["candidate_contexts"] if item["candidate_id"] == CAND_RESULT
    )
    coordinate_context["position"] = 101
    coordinate_result = _analysis(coordinate_payload)
    assert coordinate_result is not None
    coordinate_trace = next(item for item in coordinate_result.exclusion_trace if item.candidate_id == CAND_RESULT)
    assert coordinate_trace.code.value == "invalid_source_binding"


def test_v037_family_bindings_use_actual_header_calls_alt_presence_and_fixed_gq():
    result = _analysis(_payload())
    assert result is not None
    candidate = next(item for item in result.ranked_candidates if item.candidate_identity.candidate_id == CAND_RESULT)
    assert candidate.inheritance_compatibility.de_novo_state.value == "insufficient_information"
    observations = {item.family_member_id: item for item in candidate.family_segregation_observations}
    assert observations["PROBAND-037"].observed_alt_presence_state == "present"
    assert observations["PROBAND-037"].observed_genotype_quality == 99.0
    assert observations["MOTHER-037"].observed_alt_presence_state == "absent"
    assert observations["MOTHER-037"].observed_genotype_quality == 80.0
    assert "FATHER-037" in result.family_segregation.missing_relative_ids

    invalid_sample_payload = _payload()
    invalid_sample_payload["candidate_analysis"]["family_sample_bindings"].append(
        {
            "family_member_id": "FATHER-037",
            "sample_name": "SAMPLE-NOT-IN-VCF-037",
            "package_id": "PKG-RESULT-036",
            "source_id": "FAMILY-SRC-037",
            "genotype_quality_threshold": CANDIDATE_FIXED_FAMILY_GQ_THRESHOLD,
        }
    )
    invalid_sample_result = _analysis(invalid_sample_payload)
    assert invalid_sample_result is not None
    invalid_candidate = next(
        item for item in invalid_sample_result.ranked_candidates if item.candidate_identity.candidate_id == CAND_RESULT
    )
    assert invalid_candidate.inheritance_compatibility.de_novo_state.value == "insufficient_information"
    father_observation = next(
        item for item in invalid_candidate.family_segregation_observations if item.family_member_id == "FATHER-037"
    )
    assert father_observation.status.value == "missing"

    duplicate_sample_payload = _payload()
    duplicate_sample_payload["candidate_analysis"]["family_sample_bindings"][1]["sample_name"] = "SAMPLE-DEMO"
    with pytest.raises(ValidationError):
        CandidateAnalysisRequest.model_validate(duplicate_sample_payload["candidate_analysis"])

    threshold_payload = _payload()
    threshold_payload["candidate_analysis"]["family_sample_bindings"][0]["genotype_quality_threshold"] = 1000
    with pytest.raises(ValidationError):
        CandidateAnalysisRequest.model_validate(threshold_payload["candidate_analysis"])


def test_v037_compound_pairing_rejects_self_cross_gene_and_unverified_trans_phase():
    self_payload = _payload()
    self_context = next(
        item for item in self_payload["candidate_analysis"]["candidate_contexts"] if item["candidate_id"] == CAND_MULTI_A
    )
    self_context.update(
        {
            "compound_heterozygosity_partner_candidate_id": CAND_MULTI_A,
            "supplied_phase": "confirmed_trans",
            "phase_evidence": "caller supplied phase text",
        }
    )
    self_result = _analysis(self_payload)
    assert self_result is not None
    self_candidate = next(item for item in self_result.ranked_candidates if item.candidate_identity.candidate_id == CAND_MULTI_A)
    assert self_candidate.inheritance_compatibility.compound_heterozygosity_state.value == "insufficient_information"
    assert self_candidate.inheritance_compatibility.phase_state.value != "confirmed_trans"
    assert any(item.category == "compound_heterozygosity" for item in self_candidate.unresolved_uncertainties)

    cross_gene_payload = _payload()
    cross_gene_context = next(
        item for item in cross_gene_payload["candidate_analysis"]["candidate_contexts"] if item["candidate_id"] == CAND_MULTI_A
    )
    cross_gene_context.update(
        {
            "compound_heterozygosity_partner_candidate_id": CAND_RESULT,
            "supplied_phase": "confirmed_trans",
            "phase_evidence": "caller supplied phase text",
        }
    )
    cross_gene_result = _analysis(cross_gene_payload)
    assert cross_gene_result is not None
    cross_gene_candidate = next(
        item for item in cross_gene_result.ranked_candidates if item.candidate_identity.candidate_id == CAND_MULTI_A
    )
    assert cross_gene_candidate.inheritance_compatibility.compound_heterozygosity_state.value == "insufficient_information"
    assert cross_gene_candidate.inheritance_compatibility.phase_state.value != "confirmed_trans"


def test_v037_compound_pair_validation_matrix_and_phase_states():
    contexts, records, gateway = _compound_probe_inputs()

    self_context = contexts["A"].model_copy(update={"compound_heterozygosity_partner_candidate_id": "A"})
    state, partner, pair_id, error = _validated_compound_pair(
        candidate_id="A",
        context=self_context,
        gateway=gateway,
        context_by_candidate=contexts,
        record=records["A"],
        record_by_candidate=records,
        pedigree_audit=None,
        supplied_statements=("compound_heterozygous",),
    )
    assert state.value == "insufficient_information" and partner == "A" and pair_id is None and error

    duplicate_records = {**records, "B": records["A"]}
    state, _, _, error = _validated_compound_pair(
        candidate_id="A",
        context=contexts["A"],
        gateway=gateway,
        context_by_candidate=contexts,
        record=records["A"],
        record_by_candidate=duplicate_records,
        pedigree_audit=None,
        supplied_statements=("compound_heterozygous",),
    )
    assert state.value == "insufficient_information" and "same source allele" in error

    cross_contexts, cross_records, _ = _compound_probe_inputs(gene_b="GENE2")
    state, _, _, error = _validated_compound_pair(
        candidate_id="A",
        context=cross_contexts["A"],
        gateway=gateway,
        context_by_candidate=cross_contexts,
        record=cross_records["A"],
        record_by_candidate=cross_records,
        pedigree_audit=None,
        supplied_statements=("compound_heterozygous",),
    )
    assert state.value == "insufficient_information" and "same authoritative source gene" in error

    missing_contexts, missing_records, _ = _compound_probe_inputs(gene_a=None, gene_b=None)
    state, _, _, error = _validated_compound_pair(
        candidate_id="A",
        context=missing_contexts["A"],
        gateway=gateway,
        context_by_candidate=missing_contexts,
        record=missing_records["A"],
        record_by_candidate=missing_records,
        pedigree_audit=None,
        supplied_statements=("compound_heterozygous",),
    )
    assert state.value == "insufficient_information" and "gene context" in error

    state, partner, pair_id, error = _validated_compound_pair(
        candidate_id="A",
        context=contexts["A"],
        gateway=gateway,
        context_by_candidate=contexts,
        record=records["A"],
        record_by_candidate=records,
        pedigree_audit=None,
        supplied_statements=("compound_heterozygous",),
    )
    assert state.value == "phase_unknown" and partner == "B" and pair_id and error is None

    for supplied_phase, expected in (("cis", "cis"), ("supplied_trans", "supplied_trans"), ("phase_unknown", "phase_unknown")):
        phase_contexts, phase_records, _ = _compound_probe_inputs(phase=supplied_phase)
        state, _, pair_id, error = _validated_compound_pair(
            candidate_id="A",
            context=phase_contexts["A"],
            gateway=gateway,
            context_by_candidate=phase_contexts,
            record=phase_records["A"],
            record_by_candidate=phase_records,
            pedigree_audit=None,
            supplied_statements=("compound_heterozygous",),
        )
        assert state.value == expected and pair_id and error is None

    audit = SimpleNamespace(
        phase_assessments=[
            SimpleNamespace(
                involved_candidate_variant_ids=["A", "B"],
                assessment="confirmed_in_trans",
            )
        ]
    )
    state, _, pair_id, error = _validated_compound_pair(
        candidate_id="A",
        context=contexts["A"],
        gateway=gateway,
        context_by_candidate=contexts,
        record=records["A"],
        record_by_candidate=records,
        pedigree_audit=audit,
        supplied_statements=("compound_heterozygous",),
    )
    assert state.value == "confirmed_trans" and pair_id and error is None
    audit.phase_assessments[0].assessment = "supported_in_trans_by_supplied_parental_observations"
    state, _, pair_id, error = _validated_compound_pair(
        candidate_id="A",
        context=contexts["A"],
        gateway=gateway,
        context_by_candidate=contexts,
        record=records["A"],
        record_by_candidate=records,
        pedigree_audit=audit,
        supplied_statements=("compound_heterozygous",),
    )
    assert state.value == "deterministically_supported_trans" and pair_id and error is None

    confirmed_context = contexts["A"].model_copy(update={"supplied_phase": "confirmed_trans"})
    state, _, _, error = _validated_compound_pair(
        candidate_id="A",
        context=confirmed_context,
        gateway=gateway,
        context_by_candidate=contexts,
        record=records["A"],
        record_by_candidate=records,
        pedigree_audit=None,
        supplied_statements=("compound_heterozygous",),
        missing_relative_ids=("FATHER",),
    )
    assert state.value == "insufficient_information" and error is None
    state, _, _, error = _validated_compound_pair(
        candidate_id="A",
        context=confirmed_context,
        gateway=gateway,
        context_by_candidate=contexts,
        record=records["A"],
        record_by_candidate=records,
        pedigree_audit=None,
        supplied_statements=("compound_heterozygous",),
        low_quality_member_ids=("MOTHER",),
    )
    assert state.value == "insufficient_information" and error is None


def test_v037_fixture_compound_pair_is_serializable_and_order_independent():
    payload = _payload()
    result = _analysis(payload)
    assert result is not None
    pair_members = [
        item for item in result.ranked_candidates
        if item.inheritance_compatibility.compound_pair_identity
    ]
    assert len(pair_members) == 2
    assert all(item.inheritance_compatibility.compound_heterozygosity_state.value == "phase_unknown" for item in pair_members)
    assert pair_members[0].inheritance_compatibility.compound_pair_identity == pair_members[1].inheritance_compatibility.compound_pair_identity
    assert CandidateAnalysisResult.model_validate(result.model_dump(mode="json")) == result

    reversed_payload = copy.deepcopy(payload)
    reversed_payload["candidate_analysis"]["candidate_contexts"].reverse()
    reversed_result = _analysis(reversed_payload)
    assert reversed_result is not None
    assert reversed_result.model_dump(mode="json") == result.model_dump(mode="json")


@pytest.mark.parametrize("bad_value", (True, "8", 1000, float("nan"), float("inf")))
def test_v037_numeric_contract_rejects_nonfinite_coerced_and_arbitrary_thresholds(bad_value):
    payload = _payload()["candidate_analysis"]
    payload["support_threshold"] = bad_value
    with pytest.raises(ValidationError):
        CandidateAnalysisRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        CandidateRankingRule(support_threshold=1000)


@pytest.mark.parametrize(
    "bad_value",
    (True, False, "0.1", "", float("nan"), float("inf"), float("-inf"), -0.01, 1.01),
)
def test_v037_frequency_context_is_strict_at_direct_nested_and_persisted_boundaries(bad_value):
    with pytest.raises(ValidationError):
        FrequencyContext(frequency_supplied=bad_value, explanation="probe")

    nested = _payload()["candidate_analysis"]
    nested["candidate_contexts"][0]["population_frequency"] = bad_value
    with pytest.raises(ValidationError):
        CandidateAnalysisRequest.model_validate(nested)

    result = _analysis(_payload())
    assert result is not None
    persisted = result.model_dump(mode="json")
    persisted["ranked_candidates"][0]["frequency_context"]["frequency_supplied"] = bad_value
    with pytest.raises(ValidationError):
        CandidateAnalysisResult.model_validate(persisted)


@pytest.mark.parametrize("value", (0, 1, 0.123))
def test_v037_frequency_context_accepts_only_valid_unit_values(value):
    context = FrequencyContext(frequency_supplied=value, explanation="probe")
    reloaded = FrequencyContext.model_validate(json.loads(context.model_dump_json()))
    assert reloaded.frequency_supplied == value


@pytest.mark.parametrize(
    "mutation",
    ("raw_contribution", "weighted_contribution", "fixed_weight", "aggregate_score", "rank", "tie_state"),
)
def test_v037_rehashed_component_forgery_is_rejected_by_typed_reload(mutation):
    result = _analysis(_payload())
    assert result is not None
    persisted = result.model_dump(mode="json")
    component = persisted["ranked_candidates"][0]["ranking_components"][0]
    if mutation == "raw_contribution":
        component["raw_contribution"] = 999.0
    elif mutation == "weighted_contribution":
        component["numerical_contribution"] = 999.0
    elif mutation == "fixed_weight":
        component["weight"] = 999.0
    elif mutation == "aggregate_score":
        persisted["ranked_candidates"][0]["aggregate_score"] = 999.0
    elif mutation == "rank":
        persisted["ranked_candidates"][0]["deterministic_rank"] = 99
    else:
        persisted["ranked_candidates"][0]["tied"] = True
    forged = _rehashed_result_payload(persisted)
    with pytest.raises(ValidationError):
        CandidateAnalysisResult.model_validate(forged)
    with pytest.raises(ValidationError):
        CandidateAnalysisResult.verified_load(json.loads(json.dumps(forged)))


def test_v037_rehashed_forgery_is_rejected_in_state_and_artifact_paths(tmp_path):
    run = AgentLoop(generated_root=tmp_path).run(
        query="Review supplied candidate records",
        uploads={},
        clinical_case_intake=_payload(),
    )
    run_dir = tmp_path / run["run_id"]
    state_path = run_dir / "agent_state.json"
    artifact_path = run_dir / "reproducibility" / "candidate_analysis.json"
    checksum_path = run_dir / "reproducibility" / "checksums.sha256"
    original_state = json.loads(state_path.read_text(encoding="utf-8"))
    original_candidate = original_state["candidate_analysis"]
    original_artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    original_checksums = checksum_path.read_text(encoding="utf-8")
    store = WorkbenchRunStore(tmp_path)

    for mutation in ("raw_contribution", "weighted_contribution", "fixed_weight", "aggregate_score", "rank", "tie_state"):
        forged = copy.deepcopy(original_candidate)
        component = forged["ranked_candidates"][0]["ranking_components"][0]
        if mutation == "raw_contribution":
            component["raw_contribution"] = 999.0
        elif mutation == "weighted_contribution":
            component["numerical_contribution"] = 999.0
        elif mutation == "fixed_weight":
            component["weight"] = 999.0
        elif mutation == "aggregate_score":
            forged["ranked_candidates"][0]["aggregate_score"] = 999.0
        elif mutation == "rank":
            forged["ranked_candidates"][0]["deterministic_rank"] = 99
        else:
            forged["ranked_candidates"][0]["tied"] = True
        forged = _rehashed_result_payload(forged)

        state_payload = copy.deepcopy(original_state)
        state_payload["candidate_analysis"] = forged
        state_path.write_text(json.dumps(state_payload, indent=2), encoding="utf-8")
        with pytest.raises(ValidationError):
            AgentState.model_validate(state_payload)
        assert store.run_detail(run["run_id"]).candidate_analysis is None

        artifact_path.write_text(json.dumps(forged, indent=2), encoding="utf-8")
        artifact_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        checksum_lines = original_checksums.splitlines()
        for index, line in enumerate(checksum_lines):
            if line.endswith("reproducibility/candidate_analysis.json"):
                checksum_lines[index] = f"{artifact_hash}  reproducibility/candidate_analysis.json"
        checksum_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
        artifact = store.read_artifact(run["run_id"], "reproducibility/candidate_analysis.json")
        assert artifact.integrity_status == "integrity_error"
        assert artifact.integrity_error

        state_path.write_text(json.dumps(original_state, indent=2), encoding="utf-8")
        artifact_path.write_text(json.dumps(original_artifact, indent=2), encoding="utf-8")
        checksum_path.write_text(original_checksums, encoding="utf-8")


def test_v037_unordered_inputs_are_canonicalized_before_identity_hashing():
    payload = _payload()
    reordered = copy.deepcopy(payload)
    reordered["candidate_analysis"]["candidate_contexts"].reverse()
    reordered["candidate_analysis"]["evidence"].reverse()
    reordered["candidate_analysis"]["family_sample_bindings"].reverse()
    reordered["phenotypes"].reverse()
    reordered["pedigree"].reverse()
    reordered["pedigree_inheritance_audit"]["relationships"].reverse()
    reordered["pedigree_inheritance_audit"]["variant_observations"].reverse()
    first = _analysis(payload)
    second = _analysis(reordered)
    assert first is not None and second is not None
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_v037_verified_load_recomputes_scores_identities_and_integrity():
    result = _analysis(_payload())
    assert result is not None
    persisted = result.model_dump(mode="json")
    persisted["ranked_candidates"][0]["aggregate_score"] = -999
    with pytest.raises(ValidationError):
        CandidateAnalysisResult.model_validate(persisted)

    persisted = result.model_dump(mode="json")
    persisted["ranked_candidates"][0]["ranking_components"][0]["weight"] = 999
    with pytest.raises(ValidationError):
        CandidateAnalysisResult.verified_load(persisted)


def test_v037_negative_unresolved_wording_rejects_semantic_absence_variants():
    for summary in (
        "The condition is absent.",
        "No disease-causing variant exists.",
        "Confirmed absence of a genetic disorder.",
        "The test is negative.",
    ):
        with pytest.raises(ValidationError):
            NegativeUnresolvedResult(
                analysis_scope="synthetic scope",
                no_sufficiently_supported_candidate=True,
                summary=summary,
            )


def test_v037_without_a_result_package_is_unresolved_not_negative():
    payload = _payload()
    payload["result_gateway"] = None
    result = _analysis(payload)
    assert result is not None
    assert result.analysis_status == CandidateAnalysisState.NOT_ASSESSED
    assert result.negative_unresolved_result.no_sufficiently_supported_candidate is True
    assert result.negative_unresolved_result.required_no_candidate_wording == (
        "No sufficiently supported candidate was identified within the supplied analysis scope."
    )
    assert result.negative_unresolved_result.excluded_candidate_ids
    assert any(item.category == "source_result" for item in result.negative_unresolved_result.missing_information)


def test_negative_unresolved_model_rejects_absolute_negative_language():
    with pytest.raises(ValidationError):
        NegativeUnresolvedResult(
            analysis_scope="synthetic scope",
            no_sufficiently_supported_candidate=True,
            summary="The test is negative.",
        )


def test_v037_agent_state_reproducibility_and_workbench_contract(tmp_path):
    run = AgentLoop(generated_root=tmp_path).run(
        query="Review supplied candidate records",
        uploads={},
        clinical_case_intake=_payload(),
    )
    candidate = run["final_state"]["candidate_analysis"]
    assert candidate["schema_version"] == "0.37"
    assert any(item.get("event") == "candidate_analysis_completed" for item in run["agent_trace"])
    stages = {item["stage_id"]: item for item in run["final_state"]["handoff_workspace"]["case_stages"]}
    assert stages["candidate_analysis"]["status"] == "completed_for_draft_use"
    assert "clinical_case_intake" in stages["candidate_analysis"]["artifact_ids"]
    assert stages["candidate_acmg"]["status"] == "completed_for_draft_use"
    repro = Path(run["reproducibility_bundle"]["path"])
    assert (repro / "candidate_analysis.json").is_file()
    assert "reproducibility/candidate_analysis.json" in run["reproducibility_bundle"]["files"]
    assert "candidate_analysis.json" in (repro / "checksums.sha256").read_text(encoding="utf-8")
    runtime_lock = json.loads((repro / "runtime_lock.json").read_text(encoding="utf-8"))
    assert runtime_lock["candidate_analysis_schema_version"] == "0.37"
    assert runtime_lock["candidate_analysis_diagnosis_made"] is False
    store = WorkbenchRunStore(tmp_path)
    summary = store.list_runs()[0]
    assert summary.candidate_analysis_status == "partial"
    assert summary.candidate_analysis_ranked_count == 4
    assert summary.candidate_analysis_excluded_count == 2
    assert summary.candidate_analysis_artifact_available is True
    detail = store.run_detail(run["run_id"])
    assert detail.candidate_analysis is not None
    compound_rows = [
        item for item in candidate["ranked_candidates"]
        if item["inheritance_compatibility"]["compound_pair_identity"]
    ]
    assert len(compound_rows) == 2
    assert all(
        item["inheritance_compatibility"]["compound_heterozygosity_state"] == "phase_unknown"
        for item in compound_rows
    )
    assert "compound partner=" in compound_rows[0]["inheritance_compatibility"]["explanation"]
    assert any(
        item["inheritance_compatibility"]["compound_pair_identity"]
        for item in detail.candidate_analysis["ranked_candidates"]
    )
    artifact = store.read_artifact(run["run_id"], "reproducibility/candidate_analysis.json")
    assert artifact.content["schema_version"] == "0.37"
    assert artifact.integrity_status == "verified"


def test_v037_workbench_fails_closed_on_persisted_candidate_tampering(tmp_path):
    run = AgentLoop(generated_root=tmp_path).run(
        query="Review supplied candidate records",
        uploads={},
        clinical_case_intake=_payload(),
    )
    run_dir = tmp_path / run["run_id"]
    state_path = run_dir / "agent_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["candidate_analysis"]["ranked_candidates"][0]["aggregate_score"] = -999
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    store = WorkbenchRunStore(tmp_path)
    detail = store.run_detail(run["run_id"])
    assert detail.candidate_analysis is None
    assert detail.candidate_analysis_integrity_error

    artifact_path = run_dir / "reproducibility" / "candidate_analysis.json"
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact_payload["ranked_candidates"][0]["aggregate_score"] = -999
    artifact_path.write_text(json.dumps(artifact_payload, indent=2), encoding="utf-8")
    artifact = store.read_artifact(run["run_id"], "reproducibility/candidate_analysis.json")
    assert artifact.integrity_status == "integrity_error"
    assert artifact.integrity_error


def test_v037_api_and_workbench_surface_candidate_analysis(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "AgentLoop", lambda: AgentLoop(generated_root=tmp_path))
    monkeypatch.setattr(main_module, "WorkbenchRunStore", lambda: WorkbenchRunStore(tmp_path))
    response = client.post(
        "/insilicopop/agent/run",
        data={
            "query": "Review supplied candidate records",
            "clinical_case_intake": json.dumps(_payload()),
            "llm_provider": "mock",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["candidate_analysis"]["schema_version"] == "0.37"
    run_id = body["run_id"]
    detail = client.get(f"/insilicopop/agent/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["candidate_analysis"]["analysis_status"] == "partial"
    artifact = client.get(
        f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/candidate_analysis.json"
    )
    assert artifact.status_code == 200
    assert artifact.json()["content"]["schema_version"] == "0.37"
    ui = client.get("/insilicopop/workbench").text
    assert "Explainable Candidate Analysis (v0.37)" in ui
    assert "renderCandidateAnalysis" in ui
    assert "candidate-analysis" in ui
    assert "candidate-sort" in ui
    assert "candidate-compare-button" in ui


def test_v037_workbench_candidate_renderer_is_valid_isolated_javascript():
    if NODE is None:
        pytest.skip("Node is unavailable for the isolated Workbench renderer test")
    html = client.get("/insilicopop/workbench").text
    renderer = _javascript_function(html, "renderCandidateAnalysis")
    analysis = {
        "schema_version": "0.37",
        "analysis_status": "partial",
        "ranking_rule": {"rule_version": "rule-0.37", "weight_version": "weights-0.37"},
        "ranked_candidates": [
            {
                "candidate_identity": {"candidate_id": "CAND-RESULT-036", "source_record": {"source_record_id": "vcf-record-1"}},
                "deterministic_rank": 1,
                "aggregate_score": 12.5,
                "tied": False,
                "review_status": "ranked_for_review",
                "gene_transcript_context": {"gene": "GENE1", "transcript": "TX1", "consequence": "loss_of_function", "transcript_relevance": "positive", "gene_disease_validity": "positive"},
                "phenotype_match": {"exact_hpo_ids": ["HP:0000001"], "related_hpo_ids": [], "negated_hpo_ids": [], "onset_state": "positive", "explanation": "exact supplied match"},
                "inheritance_compatibility": {"state": "positive", "deterministic_compatibility": "consistent", "explanation": "supplied only"},
                "frequency_context": {"frequency_supplied": 0.001, "indian_population_source": True, "explanation": "supplied source"},
                "quality_coverage_assay": {"coverage_state": "positive", "warnings": [], "explanation": "supplied QC"},
                "ranking_components": [{"component_id": "phenotype_match", "display_name": "phenotype match", "state": "positive", "numerical_contribution": 4.0, "weight": 4.0, "deterministic_rule": "exact", "explanation": "visible"}],
                "supporting_evidence": [{"role": "supporting", "statement": "supplied", "source": {"source_id": "SRC-1"}}],
                "contradicting_evidence": [],
                "missing_information": [],
                "unresolved_uncertainties": []
            }
        ],
        "excluded_candidates": [],
        "exclusion_trace": [],
        "family_segregation": {"family_shape": "singleton", "member_count": 1, "tested_member_count": 1, "missing_relative_ids": [], "observations": []},
        "negative_unresolved_result": {"no_sufficiently_supported_candidate": False, "summary": "Sufficiently supported candidate records were retained for human review within the supplied analysis scope.", "required_no_candidate_wording": "No sufficiently supported candidate was identified within the supplied analysis scope.", "human_review_questions": [], "coverage_gaps": [], "unsupported_result_types": [], "unavailable_adapters": []},
        "source_record_ids": ["vcf-record-1"],
        "ranking_input_identity_sha256": "a" * 64,
        "ranking_output_identity_sha256": "b" * 64,
        "analysis_identity_sha256": "c" * 64
    }
    script = f"""
const analysis = {json.dumps(analysis)};
    const target = {{className: "", textContent: "", innerHTML: ""}};
    globalThis.document = {{getElementById: (id) => target}};
    let currentCandidateAnalysis = null;
    function escapeHtml(value) {{ return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }}
    function notAvailable(value) {{ return value === undefined || value === null || value === "" ? "not available" : String(value); }}
    function asJson(value) {{ return JSON.stringify(value); }}
{renderer}
renderCandidateAnalysis(analysis);
process.stdout.write(JSON.stringify({{className: target.className, html: target.innerHTML}}));
"""
    completed = subprocess.run([NODE, "-e", script], check=True, capture_output=True, text=True, timeout=15)
    rendered = json.loads(completed.stdout)
    assert rendered["className"] == ""
    assert "CAND-RESULT-036" in rendered["html"]
    assert "draft_not_clinically_approved" in rendered["html"]
    assert "Diagnosis made: false" in rendered["html"]
