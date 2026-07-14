from __future__ import annotations

import copy

import pytest

from app.insilicopop.clinical.models import CandidateVariantIntake, ClinicalCaseIntake
from app.insilicopop.clinical.variant_models import VariantNormalizationRequest
from app.insilicopop.clinical.variant_normalization import normalize_variant_request
from app.insilicopop.clinical.variant_service import build_variant_intelligence


def candidate(**updates):
    data = {"candidate_id": "VAR-1", "submitted_representation": "structured allele", "genome_build": "GRCh38", "chromosome": "1"}
    data.update(updates)
    return CandidateVariantIntake.model_validate(data)


def request(**updates):
    data = {
        "request_id": "REQ-1",
        "candidate_variant_id": "VAR-1",
        "supplied_representation": "1:100:A:G",
        "representation_type": "genomic_coordinate",
        "declared_variant_class": "snv",
        "structured_allele": {
            "chromosome": "1", "position": 100, "reference": "A", "alternate": "G",
            "coordinate_system": "one_based_closed", "genome_build": "GRCh38",
            "reference_accession": "NC_000001.11",
        },
        "requested_outputs": ["normalized_hgvs", "spdi", "canonical_internal_allele"],
        "provenance_source_ids": ["SRC-2", "SRC-1"],
    }
    data.update(updates)
    return VariantNormalizationRequest.model_validate(data)


def outputs(result):
    return {item.output_type.value: item for item in result.normalized_outputs}


@pytest.mark.parametrize(
    ("ref", "alt", "variant_class"),
    [("A", "G", "snv"), ("A", "", "deletion"), ("", "G", "insertion"), ("AC", "GT", "mnv"), ("AC", "G", "delins")],
)
def test_supported_simple_allele_classes_normalize_deterministically(ref, alt, variant_class):
    allele = request().structured_allele.model_dump()
    allele.update(reference=ref, alternate=alt, coordinate_system="one_based_closed")
    result = normalize_variant_request(request(structured_allele=allele), candidate())
    internal = outputs(result)["canonical_internal_allele"]
    assert internal.status == "generated"
    assert internal.value["variant_class"] == variant_class
    assert result.validation_status.value == "valid"
    assert result.normalization_status.value == "normalized"
    assert result.equivalence_status.value == "exact_equivalence"


def test_minimal_representation_is_separate_and_marks_normalized_equivalence():
    allele = request().structured_allele.model_dump()
    allele.update(reference="AC", alternate="AT")
    result = normalize_variant_request(request(structured_allele=allele), candidate())
    value = outputs(result)["canonical_internal_allele"].value
    assert (value["start_zero_based"], value["reference"], value["alternate"]) == (100, "C", "T")
    assert result.supplied_request_snapshot.structured_allele.reference == "AC"
    assert result.equivalence_status.value == "normalized_equivalence"


def test_verified_bounded_reference_enables_left_normalization_and_records_provenance():
    allele = request().structured_allele.model_dump()
    allele.update(
        position=4, reference="A", alternate="", coordinate_system="one_based_closed",
        reference_context_sequence="AAAAAA", reference_context_start=0, reference_context_verified=True,
    )
    result = normalize_variant_request(request(structured_allele=allele), candidate())
    value = outputs(result)["canonical_internal_allele"].value
    assert value["start_zero_based"] == 0
    assert result.reference_context_used.reference_context_verified is True
    assert any(op.operation_name == "left_normalize_with_verified_bounded_reference" for op in result.normalization_operations)
    assert all(len(op.input_hash) == 64 for op in result.normalization_operations)
    assert all(op.algorithm_version == "insilicopop-variant-intelligence-0.30.0" for op in result.normalization_operations)


def test_all_equivalence_states_are_explicit():
    exact = normalize_variant_request(request(), candidate())
    minimal = request().structured_allele.model_dump()
    minimal.update(reference="AC", alternate="AT")
    normalized = normalize_variant_request(request(structured_allele=minimal), candidate())
    unresolved = normalize_variant_request(request(structured_allele=None), candidate())
    conflict = normalize_variant_request(request(), candidate(genome_build="GRCh37"))
    unsupported = normalize_variant_request(request(declared_variant_class="cnv"), candidate())
    assert [item.equivalence_status.value for item in (exact, normalized, unresolved, conflict, unsupported)] == [
        "exact_equivalence", "normalized_equivalence", "unresolved_equivalence",
        "incompatible_representations", "unsupported_representation",
    ]


def test_missing_context_does_not_fabricate_hgvs_spdi_caid_or_vrs():
    result = normalize_variant_request(
        request(
            structured_allele=None,
            requested_outputs=["normalized_hgvs", "spdi", "caid", "vrs"],
        ),
        candidate(),
    )
    by_type = outputs(result)
    assert all(item.status in {"not_generated", "unsupported"} for item in by_type.values())
    assert all(item.value is None for item in by_type.values())
    assert by_type["caid"].reason_code == "CAID_LOOKUP_UNAVAILABLE"
    assert by_type["vrs"].reason_code == "NORMALIZATION_LIBRARY_UNAVAILABLE"


def test_supplied_caid_is_preserved_but_never_generated():
    result = normalize_variant_request(request(supplied_caid="CA123", requested_outputs=["caid"]), candidate())
    assert outputs(result)["caid"].status == "preserved"
    assert outputs(result)["caid"].value == "CA123"


def test_formatting_anomalies_block_silent_normalization():
    allele = request().structured_allele.model_dump()
    allele["alternate"] = "g"
    result = normalize_variant_request(request(supplied_representation=" 1:100:A:g ", structured_allele=allele), candidate())
    assert result.supplied_request_snapshot.supplied_representation == " 1:100:A:g "
    assert result.supplied_request_snapshot.structured_allele.alternate == "g"
    assert outputs(result)["canonical_internal_allele"].status == "not_generated"


def test_request_output_and_provenance_reordering_is_deterministic():
    first = normalize_variant_request(request(), candidate())
    reordered = request(
        requested_outputs=list(reversed(request().requested_outputs)),
        provenance_source_ids=list(reversed(request().provenance_source_ids)),
    )
    second = normalize_variant_request(reordered, candidate())
    assert first == second
    assert first.stable_result_id == second.stable_result_id


def test_aggregate_request_and_candidate_ordering_is_deterministic():
    base = {
        "schema_version": "0.27", "pseudonymous_case_id": "CASE-DETERMINISM",
        "intended_use": "clinical_genetics_research_curation", "redaction_declared": True,
        "human_review_required": True,
        "candidate_variants": [
            {"candidate_id": "VAR-2", "submitted_representation": "second", "genome_build": "GRCh38", "chromosome": "1"},
            {"candidate_id": "VAR-1", "submitted_representation": "first", "genome_build": "GRCh38", "chromosome": "1"},
        ],
        "variant_intelligence": {"schema_version": "0.30", "human_review_required": True, "normalization_requests": [
            request(request_id="REQ-2", candidate_variant_id="VAR-2").model_dump(mode="json"),
            request().model_dump(mode="json"),
        ]},
    }
    changed = copy.deepcopy(base)
    changed["candidate_variants"].reverse()
    changed["variant_intelligence"]["normalization_requests"].reverse()
    first = build_variant_intelligence(ClinicalCaseIntake.model_validate(base))
    second = build_variant_intelligence(ClinicalCaseIntake.model_validate(changed))
    assert first == second
    assert first.stable_result_id == second.stable_result_id


@pytest.mark.parametrize("variant_class", [
    "cnv", "structural_variant", "inversion", "translocation", "repeat_expansion",
    "mosaic", "somatic", "mitochondrial_complex", "complex_rearrangement",
    "pharmacogenomic_haplotype", "hla_allele", "star_allele", "polygenic_score",
])
def test_unsupported_classes_never_normalize(variant_class):
    result = normalize_variant_request(request(declared_variant_class=variant_class), candidate())
    assert result.validation_status.value == "unsupported"
    assert result.normalization_status.value == "unsupported"
    assert result.unsupported_reasons
