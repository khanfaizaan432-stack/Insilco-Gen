from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.insilicopop.clinical import build_clinical_case_result_evidence_bundle


def base_case() -> dict:
    return {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-V032",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "human_review_required": True,
        "provenance": [
            {
                "source_id": "SRC-REF",
                "source_type": "structured_referral",
                "reference": "Synthetic referral",
            }
        ],
        "phenotypes": [
            {
                "observation_id": "PH-1",
                "supplied_term": "Synthetic reviewed phenotype",
                "state": "present",
                "review_state": "confirmed",
                "source_reference": "SRC-REF",
            }
        ],
    }


def provenance(**overrides) -> dict:
    value = {
        "source_type": "external_laboratory_report",
        "source_document_id": "DOC-1",
        "source_document_hash": "a" * 64,
        "source_document_name": "synthetic-report.pdf",
        "source_document_date": "2026-01-02",
        "source_page_or_section": "page 2",
        "reporting_laboratory": "Synthetic Laboratory",
        "laboratory_accreditation_status": "unknown",
        "accreditation_scope_verified": "requires_review",
        "test_name_as_reported": "Synthetic bounded panel",
        "test_method_as_reported": "Synthetic sequencing method",
        "test_scope_as_reported": "Synthetic gene scope",
        "specimen_type": "blood",
        "report_issue_date": "2026-01-02",
        "report_version": "1",
        "report_status": "final_as_reported",
        "entered_by": "research-curator",
        "entered_at": "2026-01-03T00:00:00Z",
        "reviewed_by": "reviewer",
        "reviewed_at": "2026-01-04T00:00:00Z",
        "translation_status": "not_applicable",
        "transcription_status": "known",
    }
    value.update(overrides)
    return value


def sequence_finding(**overrides) -> dict:
    value = {
        "finding_id": "FIND-SEQ-1",
        "category": "sequence_variant_result",
        "original_text": "GENE1 NM_000001.2:c.10A>G was reported.",
        "original_terminology": ["substitution"],
        "original_variant_string": "NM_000001.2:c.10A>G",
        "transcription_confidence": "known",
        "human_transcription_verified": True,
        "sequence_variant": {
            "gene_symbol_reported": "gene1",
            "transcript_reported": "NM_000001.2",
            "reference_assembly_reported": "hg38",
            "chromosome": "1",
            "genomic_position": 100,
            "reference_allele": "a",
            "alternate_allele": "g",
            "hgvs_g_reported": "NC_000001.11:g.100A>G",
            "hgvs_c_reported": "NM_000001.2:c.10A>G",
            "hgvs_p_reported": "p.(Synthetic)",
            "zygosity_reported": "Heterozygous",
            "variant_type": "SNV",
        },
        "external_laboratory_classification": {
            "value": "uncertain_significance",
            "value_as_reported": "Variant of uncertain significance",
            "classification_system_as_reported": "Laboratory five-tier system",
            "classification_date": "2026-01-02",
            "classification_source": "Synthetic Laboratory report",
            "classification_review_status": "unreviewed",
        },
        "fact_links": [
            {
                "link_id": "LINK-1",
                "fact_type": "phenotype_fact",
                "fact_id": "PH-1",
                "relationship": "requires_clinician_correlation",
            }
        ],
    }
    value.update(overrides)
    return value


def sequence_result(**overrides) -> dict:
    value = {
        "result_id": "RESULT-SEQ-1",
        "case_id": "CASE-V032",
        "category": "sequence_variant_result",
        "provenance": provenance(),
        "findings": [sequence_finding()],
    }
    value.update(overrides)
    return value


def fixture_adapter(records=None, **overrides) -> dict:
    value = {
        "source_name": "FixtureDB",
        "source_type": "variant_database_record",
        "source_version": "2026.1",
        "source_url_or_identifier": "fixture://variant-db/2026.1",
        "adapter_state": "available",
        "retrieval_method": "deterministic_fixture",
        "records": records or [],
    }
    value.update(overrides)
    return value


def fixture_record(record_id="REC-1", **overrides) -> dict:
    value = {
        "fixture_record_id": record_id,
        "query_id": "QUERY-1",
        "source_identifier": "SYNTHETIC:1",
        "source_title": "Synthetic source record",
        "source_version": "1",
        "publication_date": "2025-01-01",
        "jurisdiction": "not_applicable",
        "evidence_domain": "case_observation",
        "source_statement": "The synthetic source reports an observation.",
        "source_excerpt": "Synthetic bounded excerpt.",
        "source_location": "record section 1",
        "structured_observation": {"observation": "reported"},
        "applicability_status": "unreviewed",
    }
    value.update(overrides)
    return value


def workspace_payload(*, results=None, queries=None, adapters=None, summaries=None) -> dict:
    payload = base_case()
    payload["result_evidence_workspace"] = {
        "schema_version": "0.32",
        "results": results if results is not None else [sequence_result()],
        "retrieval_queries": queries
        if queries is not None
        else [
            {
                "query_id": "QUERY-1",
                "finding_id": "FIND-SEQ-1",
                "normalized_gene": "GENE1",
                "normalized_variant": "NM_000001.2:c.10A>G",
                "transcript": "NM_000001.2",
                "reference_assembly": "GRCh38",
                "variant_type": "snv",
                "condition_term_reviewed": "Synthetic reviewed condition term",
                "inheritance_term_reviewed": "unknown",
                "evidence_source_selection": ["FixtureDB"],
                "language": "en",
                "review_status": "human_reviewed",
                "reviewed_by": "reviewer",
                "reviewed_at": "2026-01-04T00:00:00Z",
            }
        ],
        "source_adapters": adapters
        if adapters is not None
        else [fixture_adapter([fixture_record()])],
        "summary_requests": summaries
        if summaries is not None
        else [
            {
                "summary_request_id": "SUMMARY-REQ-1",
                "finding_id": "FIND-SEQ-1",
                "requested_by": "reviewer",
                "requested_at": "2026-01-04T00:00:00Z",
                "summary_limitations": ["Synthetic fixture only."],
            }
        ],
        "review_actions": [
            {
                "action_id": "ACTION-1",
                "action": "accept_as_transcribed",
                "target_type": "finding",
                "target_id": "FIND-SEQ-1",
                "reviewer_role": "clinical_research_reviewer",
                "reviewer_id": "reviewer",
                "timestamp": "2026-01-04T00:00:00Z",
                "before_value": {"status": "requires_review"},
                "after_value": {"status": "accepted_into_workspace"},
            }
        ],
        "external_interpretations": [
            {
                "external_interpretation_id": "EXT-INT-1",
                "finding_id": "FIND-SEQ-1",
                "external_interpretation_recorded": True,
                "external_interpretation_source": "External review meeting",
                "external_interpretation_date": "2026-01-05",
                "external_interpretation_text": "External interpretation transcribed for review.",
                "external_classification": "uncertain_significance",
                "verification_status": "unreviewed",
            }
        ],
        "human_review_required": True,
    }
    return payload


def workspace(payload=None):
    return build_clinical_case_result_evidence_bundle(payload or workspace_payload())[6]


def test_complete_sequence_normalizes_without_overwriting_reported_source():
    result = workspace()
    finding = result.normalized_findings[0]
    assert finding.normalization_status.value == "normalized"
    assert finding.normalization_rule_id == "NORM-001"
    assert finding.reported_value["gene_symbol_reported"] == "gene1"
    assert finding.normalized_value["gene_symbol_normalized"] == "GENE1"
    assert finding.normalized_value["reference_assembly_normalized"] == "GRCh38"
    assert finding.normalized_value["transcript_version"] == "2"
    assert finding.normalized_value["hgvs_p_normalized"] is None
    assert finding.reported_finding_snapshot.original_variant_string == "NM_000001.2:c.10A>G"
    with pytest.raises(ValidationError):
        finding.normalization_status = "rejected_as_invalid"


def test_missing_source_report_splits_blocking_and_advisory_fields():
    result_record = sequence_result(provenance=provenance(source_document_id=None, source_document_hash=None, reporting_laboratory=None))
    result = workspace(workspace_payload(results=[result_record], queries=[], adapters=[], summaries=[]))
    assessment = result.intake_assessments[0]
    assert assessment.intake_status.value == "requires_rule_review"
    assert assessment.blocking_missing_fields == ["source_document_hash", "source_document_id"]
    assert "reporting_laboratory" in assessment.advisory_missing_fields
    assert result.normalized_findings[0].normalization_status.value == "requires_rule_review"
    assert result.normalized_findings[0].reported_finding_snapshot.original_text


def test_external_classification_and_interpretation_remain_external():
    result = workspace()
    classification = result.source_results[0].findings[0].external_laboratory_classification
    assert classification.label == "external_laboratory_classification"
    assert "not assigned by InSilicoPop" in classification.required_wording
    assert "insilicopop_final_classification" not in result.model_dump(mode="json")
    assert "not assigned by InSilicoPop" in result.external_interpretations[0].required_wording
    assert result.final_acmg_classification_made is False
    assert result.pathogenicity_interpretation_performed is False


def test_negative_report_is_scope_bounded_and_never_excludes_disease():
    negative = {
        "result_id": "RESULT-NEG-1",
        "case_id": "CASE-V032",
        "category": "negative_or_uninformative_result",
        "provenance": provenance(source_document_id="DOC-NEG", source_document_hash="b" * 64),
        "findings": [
            {
                "finding_id": "FIND-NEG-1",
                "category": "negative_or_uninformative_result",
                "original_text": "No reportable finding in the stated synthetic panel scope.",
                "negative_or_uninformative": {
                    "negative_scope": "Synthetic panel scope",
                    "genes_or_regions_assessed": ["GENE1", "GENE2"],
                    "variant_classes_assessed": ["snv", "small_indel"],
                    "coverage_or_resolution_as_reported": "As stated in the source report.",
                    "limitations_as_reported": ["Repeat expansions were not assessed."],
                    "secondary_findings_policy": "Not assessed.",
                    "reanalysis_policy_as_reported": "Not provided.",
                },
            }
        ],
    }
    result = workspace(workspace_payload(results=[negative], queries=[], adapters=[], summaries=[]))
    wording = result.intake_assessments[0].bounded_result_wording
    assert wording == "No reportable finding was identified within the externally reported scope and limitations."
    serialized = str(result.model_dump(mode="json")).lower()
    for forbidden in ("normal genome", "genetic disease excluded", "no mutation exists", "not genetic"):
        assert forbidden not in serialized


def test_missing_transcript_or_assembly_is_partial_and_retrieval_is_deferred():
    finding = sequence_finding()
    finding["sequence_variant"]["transcript_reported"] = None
    finding["sequence_variant"]["reference_assembly_reported"] = None
    result = workspace(workspace_payload(results=[sequence_result(findings=[finding])]))
    normalized = result.normalized_findings[0]
    assert normalized.normalization_status.value == "partially_normalized"
    assert normalized.normalization_rule_id == "NORM-002"
    assert normalized.normalized_value["transcript_normalized"] is None
    assert normalized.normalized_value["reference_assembly_normalized"] is None
    assert result.retrieval_records[0].state.value == "requires_rule_review"
    assert result.ledger_entries == []


def test_conflicting_sequence_representations_are_preserved_and_not_merged():
    finding = sequence_finding()
    finding["sequence_variant"]["alternate_source_representations"] = [
        "NM_000001.2:c.10A>G",
        "NM_000001.2:c.11A>G",
    ]
    finding["sequence_variant"]["representations_equivalent"] = False
    result = workspace(workspace_payload(results=[sequence_result(findings=[finding])]))
    normalized = result.normalized_findings[0]
    assert normalized.normalization_status.value == "requires_rule_review"
    assert normalized.normalization_rule_id == "NORM-003"
    assert len(normalized.reported_value["alternate_source_representations"]) == 2
    assert result.retrieval_records[0].state.value == "requires_rule_review"


def test_cnv_approximate_breakpoints_remain_approximate():
    cnv = {
        "result_id": "RESULT-CNV-1",
        "case_id": "CASE-V032",
        "category": "copy_number_result",
        "provenance": provenance(source_document_id="DOC-CNV", source_document_hash="c" * 64),
        "findings": [
            {
                "finding_id": "FIND-CNV-1",
                "category": "copy_number_result",
                "original_text": "Approximate deletion was reported.",
                "copy_number": {
                    "copy_number_type": "deletion",
                    "region_reported": "approximately 1q21",
                    "assembly": "GRCh38",
                    "chromosome": "1",
                    "copy_number_state": "one_copy",
                    "genes_listed_by_source": ["GENE1"],
                    "breakpoint_precision": "unknown",
                },
            }
        ],
    }
    result = workspace(workspace_payload(results=[cnv], queries=[], adapters=[], summaries=[]))
    finding = result.normalized_findings[0]
    assert finding.normalization_status.value == "partially_normalized"
    assert finding.normalized_value["breakpoint_precision"] == "approximate"
    assert finding.normalized_value["start"] is None
    assert finding.normalized_value["end"] is None


def test_cytogenetic_iscn_and_repeat_categories_are_preserved_without_invention():
    cyto = {
        "result_id": "RESULT-CYTO-1",
        "case_id": "CASE-V032",
        "category": "cytogenetic_result",
        "provenance": provenance(source_document_id="DOC-CYTO", source_document_hash="d" * 64),
        "findings": [
            {
                "finding_id": "FIND-CYTO-1",
                "category": "cytogenetic_result",
                "original_text": "Synthetic ISCN record.",
                "structural_or_cytogenetic": {
                    "iscn_reported": "46,XX,synthetic[20]",
                    "chromosomes_involved": ["X"],
                    "mosaic_cell_counts": "20 cells reported",
                    "culture_or_tissue": "blood culture",
                },
            }
        ],
    }
    repeat = {
        "result_id": "RESULT-REP-1",
        "case_id": "CASE-V032",
        "category": "repeat_expansion_result",
        "provenance": provenance(source_document_id="DOC-REP", source_document_hash="e" * 64),
        "findings": [
            {
                "finding_id": "FIND-REP-1",
                "category": "repeat_expansion_result",
                "original_text": "One allele was reported in an expanded category.",
                "repeat_expansion": {
                    "repeat_locus": "SYNTH1",
                    "repeat_unit": "CAG",
                    "allele_category_reported": ["expanded"],
                    "measurement_method": "categorical assay",
                    "reportable_range": "category only",
                },
            }
        ],
    }
    result = workspace(workspace_payload(results=[cyto, repeat], queries=[], adapters=[], summaries=[]))
    by_id = {item.finding_id: item for item in result.normalized_findings}
    assert by_id["FIND-CYTO-1"].normalized_value["iscn_reported"] == "46,XX,synthetic[20]"
    assert by_id["FIND-REP-1"].normalized_value["allele_sizes_reported"] == []
    assert by_id["FIND-REP-1"].normalized_value["allele_category_reported"] == ["expanded"]


def test_mitochondrial_heteroplasmy_is_bound_to_specimen_assay_and_limit():
    mt = {
        "result_id": "RESULT-MT-1",
        "case_id": "CASE-V032",
        "category": "mitochondrial_result",
        "provenance": provenance(source_document_id="DOC-MT", source_document_hash="f" * 64, specimen_type="blood"),
        "findings": [
            {
                "finding_id": "FIND-MT-1",
                "category": "mitochondrial_result",
                "original_text": "Synthetic blood heteroplasmy was reported.",
                "mitochondrial": {
                    "mt_reference_sequence": "NC_012920.1",
                    "mt_hgvs_reported": "m.100A>G",
                    "heteroplasmy_reported": "20 percent in blood",
                    "heteroplasmy_value": 20,
                    "heteroplasmy_unit": "percent",
                    "specimen_type": "blood",
                    "detection_limit": "5 percent",
                },
            }
        ],
    }
    result = workspace(workspace_payload(results=[mt], queries=[], adapters=[], summaries=[]))
    binding = result.normalized_findings[0].normalized_value["heteroplasmy_binding"]
    assert binding == {
        "specimen_type": "blood",
        "detection_limit": "5 percent",
        "assay_scope": "reported_assay_only",
        "propagated_to_other_tissues_or_relatives": False,
    }


def test_biochemical_conversion_is_validated_reversible_and_source_preserving():
    biochemical = {
        "result_id": "RESULT-BIO-1",
        "case_id": "CASE-V032",
        "category": "biochemical_result",
        "provenance": provenance(source_document_id="DOC-BIO", source_document_hash="1" * 64, specimen_type="plasma"),
        "findings": [
            {
                "finding_id": "FIND-BIO-1",
                "category": "biochemical_result",
                "original_text": "Glucose 90 mg/dL was reported.",
                "biochemical": {
                    "analyte": "glucose",
                    "value": 90,
                    "unit_reported": "mg/dL",
                    "requested_normalized_unit": "mmol/L",
                    "specimen": "plasma",
                    "abnormal_flag_as_reported": "not flagged",
                },
            }
        ],
    }
    result = workspace(workspace_payload(results=[biochemical], queries=[], adapters=[], summaries=[]))
    finding = result.normalized_findings[0]
    assert finding.reported_value["value"] == 90
    assert finding.reported_value["unit_reported"] == "mg/dL"
    assert finding.normalized_value["value_normalized"] == pytest.approx(4.9949)
    assert finding.normalized_value["unit_normalized"] == "mmol/L"
    assert finding.normalization_rule_id == "BIOCHEM-GLUCOSE-MGDL-MMOLL-001"
    assert result.diagnosis_made is False


def test_no_records_and_source_unavailable_are_distinct_and_nonclinical():
    no_records = workspace(workspace_payload(adapters=[fixture_adapter([])], summaries=[]))
    no_result = no_records.retrieval_records[0]
    assert no_result.state.value == "no_records_found"
    assert no_result.no_records_wording == "No records were returned by the selected source FixtureDB for this query."
    assert "No evidence exists" not in no_result.no_records_wording

    unavailable = workspace(
        workspace_payload(
            adapters=[fixture_adapter([], adapter_state="source_unavailable")],
            summaries=[],
        )
    )
    assert unavailable.retrieval_records[0].state.value == "source_unavailable"
    assert unavailable.retrieval_records[0].no_records_wording is None
    assert unavailable.ledger_entries == []


def test_unreviewed_query_is_visible_but_not_executed():
    payload = workspace_payload()
    payload["result_evidence_workspace"]["retrieval_queries"][0]["review_status"] = "unreviewed"
    result = workspace(payload)
    retrieval = result.retrieval_records[0]
    assert retrieval.state.value == "ready_for_review"
    assert retrieval.normalized_query
    assert retrieval.source_name == "not_selected"
    assert retrieval.result_count == 0
    assert result.ledger_entries == []


def test_ledger_preserves_duplicates_updates_conflicts_and_proposed_summary():
    records = [
        fixture_record("REC-1", interpretation_tag="observation_a", conflict_group_id="CG-1"),
        fixture_record("REC-2", interpretation_tag="observation_a", conflict_group_id="CG-1"),
        fixture_record(
            "REC-3",
            source_version="2",
            publication_date="2026-01-01",
            source_statement="The updated synthetic source reports a differing observation.",
            interpretation_tag="observation_b",
            conflict_group_id="CG-1",
            withdrawn_or_updated=True,
        ),
    ]
    result = workspace(workspace_payload(adapters=[fixture_adapter(records)]))
    entries = result.ledger_entries
    assert len(entries) == 3
    assert sum(bool(item.duplicate_of) for item in entries) == 1
    assert any(item.newer_version_of for item in entries)
    assert any(item.superseded_by for item in entries)
    assert all(item.conflict_detected for item in entries)
    assert all("has not resolved the conflict" in item.conflict_description for item in entries)
    assert any(item.withdrawn_or_updated for item in entries)
    summary = result.generated_summaries[0]
    assert summary.summary_status == "proposed_not_approved"
    assert summary.summary_based_on_source_ids == sorted(item.ledger_entry_id for item in entries)
    assert "ACMG criteria" in summary.system_summary
    serialized = str(result.model_dump(mode="json"))
    for code in ("PVS1", "PS2", "PS3", "PM2", "PP3", "BA1", "BS1"):
        assert code not in serialized


def test_fact_link_is_descriptive_and_unknown_fact_requires_review():
    payload = workspace_payload()
    unknown = copy.deepcopy(payload["result_evidence_workspace"]["results"][0]["findings"][0]["fact_links"][0])
    unknown["link_id"] = "LINK-2"
    unknown["fact_id"] = "PH-UNKNOWN"
    payload["result_evidence_workspace"]["results"][0]["findings"][0]["fact_links"].append(unknown)
    result = workspace(payload)
    by_id = {item.link_id: item for item in result.fact_link_assessments}
    assert by_id["LINK-1"].linkage_status == "linked"
    assert "no causality" in by_id["LINK-1"].message
    assert by_id["LINK-2"].linkage_status == "requires_rule_review"


def test_reordering_input_records_is_deterministic():
    records = [
        fixture_record("REC-1"),
        fixture_record("REC-2", source_identifier="SYNTHETIC:2", source_statement="Second statement."),
    ]
    first_payload = workspace_payload(adapters=[fixture_adapter(records)])
    second_payload = copy.deepcopy(first_payload)
    second_payload["result_evidence_workspace"]["source_adapters"][0]["records"].reverse()
    first = workspace(first_payload).model_dump(mode="json")
    second = workspace(second_payload).model_dump(mode="json")
    assert first == second


def test_invalid_workspace_does_not_corrupt_case_state():
    payload = workspace_payload()
    payload["result_evidence_workspace"]["results"][0]["findings"].append(
        copy.deepcopy(payload["result_evidence_workspace"]["results"][0]["findings"][0])
    )
    bundle = build_clinical_case_result_evidence_bundle(payload)
    assert bundle[0].intake_completeness == "invalid"
    assert bundle[6] is None
    assert any(item.code == "schema_validation_error" for item in bundle[0].validation_errors)
