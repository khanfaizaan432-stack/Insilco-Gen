import json
from pathlib import Path

from app.insilicopop.agent.loop import AgentLoop


def _run_agent(tmp_path: Path):
    return AgentLoop(generated_root=tmp_path).run(
        query="selection is proven",
        uploads={
            "selection_scan": {
                "filename": "selection.tsv",
                "content": b"chr\tposition\tgene\tihs\tp_value\n1\t123\tLCT\t2.8\t0.001\n",
            },
            "vcf": {
                "filename": "cohort.vcf.gz",
                "content": b"##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n",
            },
        },
        memory_mode="compact",
    )


def test_reproducibility_bundle_files_are_generated(tmp_path):
    result = _run_agent(tmp_path)
    bundle = result["reproducibility_bundle"]

    assert bundle["generated"] is True
    expected = {
        "reproducibility/input_inventory.json",
        "reproducibility/workflow_selection.json",
        "reproducibility/command_previews.sh",
        "reproducibility/command_previews.yaml",
        "reproducibility/selected_recipe.json",
        "reproducibility/claim_audit.json",
        "reproducibility/data_governance_audit.json",
        "reproducibility/metadata_registry_audit.json",
        "reproducibility/evidence_retrieval.json",
        "reproducibility/orchestration_trace.json",
        "reproducibility/guardrail_decisions.json",
        "reproducibility/provenance_index.json",
        "reproducibility/runtime_lock.json",
        "reproducibility/checksums.sha256",
    }
    assert set(bundle["files"]) == expected
    for relative_path in expected:
        assert (Path(bundle["path"]).parent / relative_path).exists()


def test_reproducibility_bundle_preserves_dry_run_runtime_invariants(tmp_path):
    result = _run_agent(tmp_path)
    repro_dir = Path(result["reproducibility_bundle"]["path"])
    shell_preview = (repro_dir / "command_previews.sh").read_text(encoding="utf-8")
    runtime_lock = json.loads((repro_dir / "runtime_lock.json").read_text(encoding="utf-8"))
    workflow_selection = json.loads((repro_dir / "workflow_selection.json").read_text(encoding="utf-8"))
    selected_recipe = json.loads((repro_dir / "selected_recipe.json").read_text(encoding="utf-8"))
    claim_audit = json.loads((repro_dir / "claim_audit.json").read_text(encoding="utf-8"))
    data_governance_audit = json.loads((repro_dir / "data_governance_audit.json").read_text(encoding="utf-8"))
    metadata_registry_audit = json.loads((repro_dir / "metadata_registry_audit.json").read_text(encoding="utf-8"))
    evidence_retrieval = json.loads((repro_dir / "evidence_retrieval.json").read_text(encoding="utf-8"))
    orchestration_trace = json.loads((repro_dir / "orchestration_trace.json").read_text(encoding="utf-8"))
    inventory = json.loads((repro_dir / "input_inventory.json").read_text(encoding="utf-8"))

    assert "WARNING: dry-run only" in shell_preview
    command_lines = [line for line in shell_preview.splitlines() if " --" in line]
    assert command_lines
    assert all(line.startswith("# ") for line in command_lines)
    assert runtime_lock["external_tools_executed"] is False
    assert runtime_lock["external_llm_called"] is False
    assert runtime_lock["llm_provider"] == "mock"
    assert runtime_lock["selected_recipe_id"] == "vcf_population_structure_basic"
    assert workflow_selection == result["workflow_selection"]
    assert selected_recipe["recipe_id"] == "vcf_population_structure_basic"
    assert selected_recipe["dry_run_only"] is True
    assert claim_audit["selected_recipe_id"] == "vcf_population_structure_basic"
    assert claim_audit["dry_run_only"] is True
    assert claim_audit["human_review_required"] is True
    assert claim_audit["external_tools_executed"] is False
    assert claim_audit["raw_genomic_files_parsed"] is False
    assert data_governance_audit["human_review_required"] is True
    assert data_governance_audit["dataset_terms_verified"] is False
    assert data_governance_audit["raw_data_network_access_allowed"] is False
    assert data_governance_audit["legal_compliance_verified"] is False
    assert metadata_registry_audit["human_review_required"] is True
    assert metadata_registry_audit["biological_interpretation_made"] is False
    assert metadata_registry_audit["clinical_decision_made"] is False
    assert evidence_retrieval["local_only"] is True
    assert evidence_retrieval["external_call_made"] is False
    assert evidence_retrieval["raw_data_ingested"] is False
    assert evidence_retrieval["human_review_required"] is True
    assert orchestration_trace["orchestration_enabled"] is True
    assert orchestration_trace["safety_flags"]["autonomous_tool_execution"] is False
    assert orchestration_trace["safety_flags"]["external_api_call_made"] is False
    assert orchestration_trace["safety_flags"]["human_review_required"] is True
    assert inventory["raw_files_parsed"] is False
    assert inventory["raw_file_hashes_computed"] is False
    assert inventory["detected_categories"]["vcf"] == ["vcf:cohort.vcf.gz"]


def test_reproducibility_checksums_are_sorted_and_exclude_raw_inputs(tmp_path):
    result = _run_agent(tmp_path)
    repro_dir = Path(result["reproducibility_bundle"]["path"])
    checksum_lines = (repro_dir / "checksums.sha256").read_text(encoding="utf-8").splitlines()
    checksum_paths = [line.split("  ", 1)[1] for line in checksum_lines]

    assert "agent_state.json" in checksum_paths
    assert "final_report.md" in checksum_paths
    assert "reproducibility/runtime_lock.json" in checksum_paths
    assert "reproducibility/selected_recipe.json" in checksum_paths
    assert "reproducibility/claim_audit.json" in checksum_paths
    assert "reproducibility/data_governance_audit.json" in checksum_paths
    assert "reproducibility/metadata_registry_audit.json" in checksum_paths
    assert "reproducibility/evidence_retrieval.json" in checksum_paths
    assert "reproducibility/orchestration_trace.json" in checksum_paths
    assert "reproducibility/checksums.sha256" not in checksum_paths
    assert checksum_paths == sorted(checksum_paths)
    assert not any("cohort.vcf" in path or "selection.tsv" in path for path in checksum_paths)
