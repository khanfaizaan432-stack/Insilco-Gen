from __future__ import annotations

import copy
import hashlib

import pytest

from app.insilicopop.clinical.models import CandidateVariantIntake, ClinicalCaseIntake
from app.insilicopop.clinical.variant_models import VariantNormalizationRequest
from app.insilicopop.clinical.variant_normalization import normalize_variant_request
from app.insilicopop.clinical.variant_service import build_variant_intelligence
from app.insilicopop.clinical.variant_reference_registry import SYNTHETIC_REFERENCE_SOURCE_ID
from app.insilicopop.clinical.variant_reference_registry import clone_reference_window, resolve_reference_window
import app.insilicopop.clinical.variant_normalization as normalization_module


def candidate(**updates):
    data = {"candidate_id": "VAR-1", "submitted_representation": "structured allele", "genome_build": "InSilicoPopSynthetic-0.30", "chromosome": "TEST1"}
    data.update(updates)
    return CandidateVariantIntake.model_validate(data)


def request(**updates):
    data = {
        "request_id": "REQ-1",
        "candidate_variant_id": "VAR-1",
        "supplied_representation": "TEST1:2:A:G",
        "representation_type": "genomic_coordinate",
        "declared_variant_class": "snv",
        "structured_allele": {
            "chromosome": "TEST1", "position": 2, "reference": "A", "alternate": "G",
            "coordinate_system": "one_based_closed", "genome_build": "InSilicoPopSynthetic-0.30",
            "reference_accession": "ISP_TESTREF.1", "reference_source_id": SYNTHETIC_REFERENCE_SOURCE_ID,
        },
        "requested_outputs": ["normalized_hgvs", "spdi", "canonical_internal_allele"],
        "provenance_source_ids": ["SRC-2", "SRC-1"],
    }
    data.update(updates)
    return VariantNormalizationRequest.model_validate(data)


def outputs(result):
    return {item.output_type.value: item for item in result.normalized_outputs}


def issue_codes(result):
    return {item.code for group in (
        result.validation_errors, result.warnings, result.missing_information,
        result.unsupported_reasons, result.conflicts, result.review_actions,
    ) for item in group}


@pytest.mark.parametrize(
    ("ref", "alt", "variant_class"),
    [("A", "G", "snv"), ("A", "", "deletion"), ("", "G", "insertion"), ("AC", "GT", "mnv"), ("AC", "G", "delins")],
)
def test_supported_simple_allele_classes_normalize_deterministically(ref, alt, variant_class):
    allele = request().structured_allele.model_dump()
    allele.update(reference=ref, alternate=alt, coordinate_system="one_based_closed", position=5 if ref == "AC" else 2)
    result = normalize_variant_request(request(declared_variant_class=variant_class, structured_allele=allele), candidate())
    internal = outputs(result)["canonical_internal_allele"]
    assert internal.status == "generated"
    assert internal.value["variant_class"] == variant_class
    assert result.validation_status.value == "valid"
    assert result.normalization_status.value == "normalized"
    assert result.equivalence_status.value == ("normalized_equivalence" if variant_class == "deletion" else "exact_equivalence")


def test_minimal_representation_is_separate_and_marks_normalized_equivalence():
    allele = request().structured_allele.model_dump()
    allele.update(reference="AC", alternate="AT", position=5)
    result = normalize_variant_request(request(declared_variant_class="mnv", structured_allele=allele), candidate())
    value = outputs(result)["canonical_internal_allele"].value
    assert (value["start_zero_based"], value["reference"], value["alternate"]) == (5, "C", "T")
    assert result.supplied_request_snapshot.structured_allele.reference == "AC"
    assert result.equivalence_status.value == "normalized_equivalence"


def test_verified_bounded_reference_enables_left_normalization_and_records_provenance():
    allele = request().structured_allele.model_dump()
    allele.update(
        position=4, reference="A", alternate="", coordinate_system="one_based_closed",
        reference_context_sequence=" caller supplied evidence ", reference_context_start=0, reference_context_verified=True,
    )
    result = normalize_variant_request(request(declared_variant_class="deletion", structured_allele=allele), candidate())
    value = outputs(result)["canonical_internal_allele"].value
    assert value["start_zero_based"] == 0
    assert result.reference_context_used.reference_context_verified is True
    assert any(op.operation_name == "left_normalize_with_pinned_bounded_reference" for op in result.normalization_operations)
    assert all(len(op.input_hash) == 64 for op in result.normalization_operations)
    assert all(op.algorithm_version == "insilicopop-variant-intelligence-0.30.1" for op in result.normalization_operations)
    left = next(op for op in result.normalization_operations if op.operation_name == "left_normalize_with_pinned_bounded_reference")
    assert left.reference_context.reference_source_id == SYNTHETIC_REFERENCE_SOURCE_ID
    assert len(left.reference_context.sequence_sha256) == 64
    assert left.reference_context.registry_version == "insilicopop-reference-windows-0.30.1"
    assert "CALLER_REFERENCE_VERIFICATION_NOT_ACCEPTED" in issue_codes(result)


def test_caller_verification_flag_without_pinned_source_cannot_enable_normalization():
    allele = request().structured_allele.model_dump()
    allele.update(
        reference_source_id=None,
        reference_context_sequence="AAAAA",
        reference_context_start=0,
        reference_context_verified=True,
    )
    result = normalize_variant_request(request(structured_allele=allele), candidate())
    assert {"REFERENCE_DATA_UNAVAILABLE", "CALLER_REFERENCE_VERIFICATION_NOT_ACCEPTED"} <= issue_codes(result)
    assert result.reference_context_used.reference_context_verified is False
    assert result.equivalence_status.value == "unresolved_equivalence"
    assert all(item.status == "not_generated" for item in result.normalized_outputs)
    assert not any(op.operation_name.startswith("left_normalize") for op in result.normalization_operations)


@pytest.mark.parametrize(
    ("representation_type", "supplied", "allele_update"),
    [
        ("hgvs_genomic", "ISP_TESTREF.1:g.2A>G", {"reference": "a"}),
        ("spdi", "ISP_TESTREF.1:1:A:G", {"genome_build": None}),
        ("hgvs_protein", "NP_000001.1:p.Val1Ala", {"coordinate_system": "unknown"}),
        ("caid", "CA123", {"position": 0}),
        ("unknown", "unknown supplied record", {"reference_source_id": None}),
    ],
)
def test_non_coordinate_representations_cannot_use_structured_fields_to_bypass_validation(representation_type, supplied, allele_update):
    allele = request().structured_allele.model_dump()
    allele.update(allele_update)
    result = normalize_variant_request(
        request(representation_type=representation_type, supplied_representation=supplied, structured_allele=allele),
        candidate(),
    )
    assert result.equivalence_status.value in {"incompatible_representations", "unsupported_representation"}
    assert not any(item.status == "generated" for item in result.normalized_outputs)
    assert "INCOMPATIBLE_REPRESENTATION_FIELDS" in issue_codes(result) or result.validation_status.value == "unsupported"


def test_unresolved_or_bogus_dotted_accession_never_generates_hgvs_or_spdi():
    allele = request().structured_allele.model_dump()
    allele.update(reference_source_id="UNKNOWN-SOURCE", reference_accession="bogus.dotted")
    result = normalize_variant_request(request(structured_allele=allele), candidate())
    assert "REFERENCE_DATA_UNAVAILABLE" in issue_codes(result)
    assert outputs(result)["normalized_hgvs"].value is None
    assert outputs(result)["spdi"].value is None
    assert result.equivalence_status.value == "unresolved_equivalence"


def test_reference_window_digest_changes_reference_operation_identity(monkeypatch):
    first = normalize_variant_request(request(), candidate())
    original = resolve_reference_window(SYNTHETIC_REFERENCE_SOURCE_ID)
    assert original is not None
    changed_sequence = original.sequence[:-1] + "A"
    changed = clone_reference_window(
        original,
        sequence=changed_sequence,
        sequence_sha256=hashlib.sha256(changed_sequence.encode("ascii")).hexdigest(),
    )
    monkeypatch.setattr(normalization_module, "resolve_reference_window", lambda _source_id: changed)
    second = normalize_variant_request(request(), candidate())
    first_op = next(op for op in first.normalization_operations if op.operation_name == "pinned_reference_context_check")
    second_op = next(op for op in second.normalization_operations if op.operation_name == "pinned_reference_context_check")
    assert first_op.operation_id != second_op.operation_id
    assert first_op.reference_context.sequence_sha256 != second_op.reference_context.sequence_sha256


def test_reference_mismatch_and_window_boundaries_refuse_normalization():
    mismatch = request().structured_allele.model_dump()
    mismatch.update(reference="C", alternate="G")
    mismatch_result = normalize_variant_request(request(structured_allele=mismatch), candidate())
    assert "REFERENCE_MISMATCH" in issue_codes(mismatch_result)
    assert mismatch_result.equivalence_status.value == "incompatible_representations"
    boundary = request().structured_allele.model_dump()
    boundary.update(position=21, reference="T", alternate="G")
    boundary_result = normalize_variant_request(request(structured_allele=boundary), candidate())
    assert "REFERENCE_WINDOW_OUT_OF_RANGE" in issue_codes(boundary_result)
    assert not any(item.status == "generated" for item in boundary_result.normalized_outputs)


def test_resolved_hgvs_spdi_coordinate_and_deleted_sequence_outputs():
    snv = normalize_variant_request(request(), candidate())
    assert outputs(snv)["normalized_hgvs"].value == "ISP_TESTREF.1:g.2A>G"
    assert outputs(snv)["spdi"].value == "ISP_TESTREF.1:1:A:G"
    deletion_allele = request().structured_allele.model_dump()
    deletion_allele.update(position=2, reference="A", alternate="")
    deletion = normalize_variant_request(request(declared_variant_class="deletion", structured_allele=deletion_allele), candidate())
    assert outputs(deletion)["spdi"].value == "ISP_TESTREF.1:0:A:"
    assert outputs(deletion)["normalized_hgvs"].value == "ISP_TESTREF.1:g.1del"
    delins_allele = request().structured_allele.model_dump()
    delins_allele.update(position=5, reference="AC", alternate="G")
    delins = normalize_variant_request(request(declared_variant_class="delins", structured_allele=delins_allele), candidate())
    assert outputs(delins)["spdi"].value == "ISP_TESTREF.1:4:AC:G"
    assert outputs(delins)["normalized_hgvs"].value == "ISP_TESTREF.1:g.5_6delinsG"


def test_one_based_position_one_insertion_has_deterministic_interbase_outputs():
    allele = request().structured_allele.model_dump()
    allele.update(position=1, reference="", alternate="G")
    result = normalize_variant_request(request(declared_variant_class="insertion", structured_allele=allele), candidate())
    assert outputs(result)["spdi"].value == "ISP_TESTREF.1:1::G"
    assert outputs(result)["normalized_hgvs"].value == "ISP_TESTREF.1:g.1_2insG"


def test_simple_duplication_requires_proven_tandem_ref_alt_relationship():
    valid = request().structured_allele.model_dump()
    valid.update(position=2, reference="A", alternate="AA")
    result = normalize_variant_request(request(declared_variant_class="duplication", structured_allele=valid), candidate())
    assert outputs(result)["normalized_hgvs"].value == "ISP_TESTREF.1:g.2dup"
    assert outputs(result)["spdi"].value == "ISP_TESTREF.1:2::A"
    assert outputs(result)["canonical_internal_allele"].value["format_id"] == "insilicopop-canonical-allele-0.30.1"
    invalid = dict(valid)
    invalid["alternate"] = "AG"
    refused = normalize_variant_request(request(declared_variant_class="duplication", structured_allele=invalid), candidate())
    assert "AMBIGUOUS_REPRESENTATION" in issue_codes(refused)
    assert not any(item.status == "generated" for item in refused.normalized_outputs)


@pytest.mark.parametrize(
    "supplied",
    [
        "HLA-B*57:01", "CYP2D6*4", "pharmacogenomic haplotype", "polygenic risk score",
        "somatic variant", "mosaic VAF 4%", "mitochondrial complex heteroplasmy",
        "N]2:321682]", "t(9;22) fusion", "CAG[42]", "<DEL>",
    ],
)
def test_recognizable_unsupported_text_refuses_even_when_misdeclared_supported(supplied):
    result = normalize_variant_request(request(supplied_representation=supplied, declared_variant_class="snv"), candidate())
    assert result.validation_status.value == "unsupported"
    assert result.normalization_status.value == "unsupported"
    assert result.equivalence_status.value == "unsupported_representation"
    assert not any(item.status == "generated" for item in result.normalized_outputs)


def test_operation_status_matches_missing_conflict_unsupported_and_success():
    successful = normalize_variant_request(request(), candidate())
    assert next(op for op in successful.normalization_operations if op.operation_name == "bounded_schema_and_context_validation").status == "succeeded"
    missing_allele = request().structured_allele.model_dump()
    missing_allele["reference_source_id"] = None
    missing = normalize_variant_request(request(structured_allele=missing_allele), candidate())
    conflict = normalize_variant_request(request(), candidate(genome_build="GRCh37"))
    unsupported = normalize_variant_request(request(declared_variant_class="cnv"), candidate())
    for result in (missing, conflict, unsupported):
        operation = next(op for op in result.normalization_operations if op.operation_name == "bounded_schema_and_context_validation")
        assert operation.status == "refused"
        assert operation.output_hash is None


def test_all_equivalence_states_are_explicit():
    exact = normalize_variant_request(request(), candidate())
    minimal = request().structured_allele.model_dump()
    minimal.update(reference="AC", alternate="AT", position=5)
    normalized = normalize_variant_request(request(declared_variant_class="mnv", structured_allele=minimal), candidate())
    unresolved = normalize_variant_request(request(structured_allele=None), candidate())
    conflict = normalize_variant_request(request(), candidate(genome_build="GRCh37"))
    unsupported = normalize_variant_request(request(declared_variant_class="cnv"), candidate())
    assert [item.equivalence_status.value for item in (exact, normalized, unresolved, conflict, unsupported)] == [
        "exact_equivalence", "normalized_equivalence", "unresolved_equivalence",
        "incompatible_representations", "unsupported_representation",
    ]


def test_missing_build_unknown_coordinate_and_text_only_context_never_claim_equivalence():
    missing_build = request().structured_allele.model_dump()
    missing_build["genome_build"] = None
    missing_result = normalize_variant_request(request(structured_allele=missing_build), candidate())
    unknown_coordinate = request().structured_allele.model_dump()
    unknown_coordinate["coordinate_system"] = "unknown"
    unknown_result = normalize_variant_request(request(structured_allele=unknown_coordinate), candidate())
    text_only = normalize_variant_request(
        request(
            supplied_representation="ISP_TESTREF.1:g.2A>G",
            representation_type="hgvs_genomic",
            supplied_genome_build="InSilicoPopSynthetic-0.30",
            supplied_reference_accession="ISP_TESTREF.1",
            structured_allele=None,
        ),
        candidate(),
    )
    assert missing_result.validation_status.value == "cannot_validate"
    assert unknown_result.validation_status.value == "cannot_validate"
    assert text_only.validation_status.value == "partially_valid"
    assert all(item.equivalence_status.value == "unresolved_equivalence" for item in (missing_result, unknown_result, text_only))
    assert all(not any(output.status == "generated" for output in item.normalized_outputs) for item in (missing_result, unknown_result, text_only))


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


def test_vrs_and_missing_caid_refusals_do_not_block_valid_canonical_output():
    result = normalize_variant_request(
        request(requested_outputs=["canonical_internal_allele", "vrs", "caid"]),
        candidate(),
    )
    by_type = outputs(result)
    assert by_type["canonical_internal_allele"].status == "generated"
    assert by_type["vrs"].status == "unsupported"
    assert by_type["vrs"].value is None
    assert by_type["caid"].status == "unsupported"
    assert by_type["caid"].value is None
    assert result.normalization_status.value == "partially_normalized"


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
            {"candidate_id": "VAR-2", "submitted_representation": "second", "genome_build": "InSilicoPopSynthetic-0.30", "chromosome": "TEST1"},
            {"candidate_id": "VAR-1", "submitted_representation": "first", "genome_build": "InSilicoPopSynthetic-0.30", "chromosome": "TEST1"},
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
