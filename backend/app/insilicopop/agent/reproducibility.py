from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi.encoders import jsonable_encoder

from app.insilicopop.agent.state import AgentState
from app.insilicopop.workflows.workflow_selector import (
    LOW_DEPTH_EXTENSIONS,
    PLINK_EXTENSIONS,
    RESULT_EXTENSIONS,
    RESULT_MARKERS,
    VCF_EXTENSIONS,
)


INSILICOPOP_VERSION = "v0.12"
REPRODUCIBILITY_FILE_KEYS = {
    "repro_input_inventory": "input_inventory.json",
    "repro_workflow_selection": "workflow_selection.json",
    "repro_command_previews_sh": "command_previews.sh",
    "repro_command_previews_yaml": "command_previews.yaml",
    "repro_selected_recipe": "selected_recipe.json",
    "repro_claim_audit": "claim_audit.json",
    "repro_data_governance_audit": "data_governance_audit.json",
    "repro_metadata_registry_audit": "metadata_registry_audit.json",
    "repro_evidence_retrieval": "evidence_retrieval.json",
    "repro_orchestration_trace": "orchestration_trace.json",
    "repro_guardrail_decisions": "guardrail_decisions.json",
    "repro_provenance_index": "provenance_index.json",
    "repro_runtime_lock": "runtime_lock.json",
    "repro_checksums": "checksums.sha256",
}
OPTIONAL_REPRODUCIBILITY_FILE_KEYS = {
    "repro_results_audit": "results_audit.json",
    "repro_clinical_case_intake": "clinical_case_intake.json",
    "repro_phenotype_hpo_curation": "phenotype_hpo_curation.json",
    "repro_pedigree_inheritance_audit": "pedigree_inheritance_audit.json",
    "repro_variant_intelligence": "variant_intelligence.json",
    "repro_pre_test_assessment": "pre_test_assessment.json",
    "repro_test_strategy_workspace": "test_strategy_workspace.json",
    "repro_result_evidence_workspace": "result_evidence_workspace.json",
}
REPRODUCIBILITY_FILE_RELATIVE_PATHS = [
    f"reproducibility/{name}" for name in REPRODUCIBILITY_FILE_KEYS.values()
] + [f"reproducibility/{name}" for name in OPTIONAL_REPRODUCIBILITY_FILE_KEYS.values()]


def write_reproducibility_bundle(
    run_dir: Path,
    state: AgentState,
    *,
    trace: list[dict[str, Any]],
    generated_artifacts: dict[str, Path],
) -> tuple[dict[str, Path], dict[str, Any]]:
    repro_dir = run_dir / "reproducibility"
    repro_dir.mkdir(parents=True, exist_ok=True)
    paths = {key: repro_dir / filename for key, filename in REPRODUCIBILITY_FILE_KEYS.items()}
    optional_paths = {key: repro_dir / filename for key, filename in OPTIONAL_REPRODUCIBILITY_FILE_KEYS.items()}

    _write_json(paths["repro_input_inventory"], _input_inventory(state))
    _write_json(paths["repro_workflow_selection"], jsonable_encoder(state.workflow_selection))
    paths["repro_command_previews_sh"].write_text(_command_previews_shell(state), encoding="utf-8")
    paths["repro_command_previews_yaml"].write_text(
        yaml.safe_dump(jsonable_encoder(state.command_previews), sort_keys=False),
        encoding="utf-8",
    )
    _write_json(paths["repro_selected_recipe"], _selected_recipe_payload(state))
    _write_json(paths["repro_claim_audit"], _claim_audit_payload(state))
    _write_json(paths["repro_data_governance_audit"], _data_governance_audit_payload(state))
    _write_json(paths["repro_metadata_registry_audit"], _metadata_registry_audit_payload(state))
    _write_json(paths["repro_evidence_retrieval"], _evidence_retrieval_payload(state))
    _write_json(paths["repro_orchestration_trace"], _orchestration_trace_payload(state))
    if state.results_audit:
        paths["repro_results_audit"] = optional_paths["repro_results_audit"]
        _write_json(paths["repro_results_audit"], _results_audit_payload(state))
    if state.clinical_case_intake:
        paths["repro_clinical_case_intake"] = optional_paths["repro_clinical_case_intake"]
        _write_json(paths["repro_clinical_case_intake"], state.clinical_case_intake.model_dump())
    if state.phenotype_hpo_curation:
        paths["repro_phenotype_hpo_curation"] = optional_paths["repro_phenotype_hpo_curation"]
        _write_json(paths["repro_phenotype_hpo_curation"], state.phenotype_hpo_curation.model_dump())
    if state.pedigree_inheritance_audit:
        paths["repro_pedigree_inheritance_audit"] = optional_paths["repro_pedigree_inheritance_audit"]
        _write_json(paths["repro_pedigree_inheritance_audit"], state.pedigree_inheritance_audit.model_dump())
    if state.variant_intelligence:
        paths["repro_variant_intelligence"] = optional_paths["repro_variant_intelligence"]
        _write_json(paths["repro_variant_intelligence"], state.variant_intelligence.model_dump())
    if state.pre_test_assessment:
        paths["repro_pre_test_assessment"] = optional_paths["repro_pre_test_assessment"]
        _write_json(paths["repro_pre_test_assessment"], state.pre_test_assessment.model_dump())
    if state.test_strategy_workspace:
        paths["repro_test_strategy_workspace"] = optional_paths["repro_test_strategy_workspace"]
        _write_json(paths["repro_test_strategy_workspace"], state.test_strategy_workspace.model_dump())
    if state.result_evidence_workspace:
        paths["repro_result_evidence_workspace"] = optional_paths["repro_result_evidence_workspace"]
        _write_json(
            paths["repro_result_evidence_workspace"],
            state.result_evidence_workspace.model_dump(),
        )
    _write_json(paths["repro_guardrail_decisions"], _guardrail_decisions(state, trace))
    _write_json(paths["repro_provenance_index"], _provenance_index(run_dir, state, generated_artifacts, paths))
    _write_json(paths["repro_runtime_lock"], _runtime_lock(run_dir, state, generated_artifacts, paths))
    paths["repro_checksums"].write_text(
        _checksums(run_dir, generated_artifacts, paths),
        encoding="utf-8",
    )

    bundle = {
        "generated": True,
        "path": str(repro_dir.resolve()),
        "files": sorted(_relative_to_run(run_dir, path) for path in paths.values()),
    }
    return paths, bundle


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(jsonable_encoder(payload), indent=2, sort_keys=True), encoding="utf-8")


def _input_inventory(state: AgentState) -> dict[str, Any]:
    declared_inputs = []
    categories = {
        "vcf": [],
        "plink_bed_bim_fam": [],
        "plink_ped_map": [],
        "plink_pgen_pvar_psam": [],
        "bam_cram": [],
        "metadata": [],
        "result_files": [],
        "other": [],
    }
    for field_name, filename in sorted(state.uploaded_files.items()):
        detected = _detect_categories(field_name, filename)
        declared_inputs.append(
            {
                "field": field_name,
                "filename_or_path": filename,
                "detected_categories": detected,
            }
        )
        for category in detected:
            categories[category].append(f"{field_name}:{filename}")

    return {
        "run_id": state.run_id,
        "query": state.query,
        "goal": state.query,
        "declared_inputs": declared_inputs,
        "detected_categories": categories,
        "workflow_selector_signals": {
            "workflow_family": state.workflow_selection.get("workflow_family"),
            "confidence": state.workflow_selection.get("confidence"),
            "matched_inputs": state.workflow_selection.get("matched_inputs", []),
            "missing_inputs": state.workflow_selection.get("missing_inputs", []),
            "rationale": state.workflow_selection.get("rationale"),
        },
        "raw_files_parsed": False,
        "raw_file_hashes_computed": False,
        "note": "Uploaded genomic files were inventoried by declared names/categories only; raw VCF/PLINK/BAM/CRAM contents were not parsed or hashed for this bundle.",
    }


def _detect_categories(field_name: str, filename: str) -> list[str]:
    lowered = f"{field_name} {filename}".lower()
    suffixes = _suffixes(filename)
    detected: list[str] = []
    if "metadata" in lowered or "sample" in lowered:
        detected.append("metadata")
    if any(suffix in VCF_EXTENSIONS for suffix in suffixes):
        detected.append("vcf")
    if any(suffix in {".bed", ".bim", ".fam"} for suffix in suffixes):
        detected.append("plink_bed_bim_fam")
    if any(suffix in {".ped", ".map"} for suffix in suffixes):
        detected.append("plink_ped_map")
    if any(suffix in {".pgen", ".pvar", ".psam"} for suffix in suffixes):
        detected.append("plink_pgen_pvar_psam")
    if any(suffix in LOW_DEPTH_EXTENSIONS for suffix in suffixes):
        detected.append("bam_cram")
    if _is_result_file(field_name, filename, suffixes):
        detected.append("result_files")
    if not detected:
        detected.append("other")
    return detected


def _is_result_file(field_name: str, filename: str, suffixes: set[str]) -> bool:
    lowered = f"{field_name} {filename}".lower()
    result_fields = {"pca", "admixture", "fst", "roh", "plink_qc", "selection_scan"}
    return field_name in result_fields or any(suffix in RESULT_EXTENSIONS for suffix in suffixes) or any(marker in lowered for marker in RESULT_MARKERS)


def _suffixes(filename: str) -> set[str]:
    lowered = filename.lower()
    suffixes = set(Path(lowered).suffixes)
    if lowered.endswith(".vcf.gz"):
        suffixes.add(".vcf.gz")
    return suffixes


def _command_previews_shell(state: AgentState) -> str:
    lines = [
        "# InSilicoPop dry-run command preview",
        "# WARNING: dry-run only. These commands are commented out and must not be executed by this agent.",
        "# Recipe-aware previews are generated from the selected deterministic recipe when available.",
        "# execution_enabled=false",
        "# external_tools_executed=false",
        "# raw_genomic_files_parsed=false",
        "# human_review_required=true",
        "",
    ]
    if not state.command_previews:
        lines.append("# No command previews were generated for this run.")
    for index, preview in enumerate(state.command_previews, start=1):
        tool = preview.get("tool", "unknown")
        purpose = preview.get("purpose", "dry-run command preview")
        command = str(preview.get("command", "")).strip()
        selected_recipe_id = preview.get("selected_recipe_id") or (state.selected_recipe or {}).get("recipe_id")
        lines.append(f"# [{index}] tool={tool} purpose={purpose}")
        if selected_recipe_id:
            lines.append(f"# selected_recipe_id={selected_recipe_id}")
        if preview.get("recipe_step_id"):
            lines.append(f"# recipe_step_id={preview.get('recipe_step_id')}")
        lines.append(f"# dry_run_only={str(bool(preview.get('dry_run_only', True))).lower()}")
        lines.append("# execution_enabled=false")
        lines.append("# external_tools_executed=false")
        lines.append("# raw_genomic_files_parsed=false")
        lines.append("# human_review_required=true")
        if command:
            lines.extend(_commented_command_lines(command))
        else:
            lines.append("# command unavailable")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _commented_command_lines(command: str) -> list[str]:
    lines = []
    for raw_line in command.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        lines.append(line if line.lstrip().startswith("#") else f"# {line}")
    return lines


def _guardrail_decisions(state: AgentState, trace: list[dict[str, Any]]) -> dict[str, Any]:
    blocked_claims = []
    for item in state.validated_actions:
        if item.get("blocking_reasons"):
            blocked_claims.append(
                {
                    "original_action_type": item.get("original_proposal", {}).get("action_type"),
                    "blocking_reasons": item.get("blocking_reasons", []),
                    "required_fixes": item.get("required_fixes", []),
                }
            )
    return {
        "run_id": state.run_id,
        "llm_provider": state.llm_provider,
        "external_llm_called": state.external_llm_called,
        "external_tools_executed": state.external_tools_executed,
        "byok_runtime": state.byok_runtime.model_dump() if state.byok_runtime else None,
        "workflow_family": state.workflow_selection.get("workflow_family", "unknown"),
        "research_lane": state.research_lane,
        "selected_recipe_id": (state.selected_recipe or {}).get("recipe_id"),
        "command_execution_enabled": False,
        "blocked_actions": jsonable_encoder(state.blocked_actions),
        "failure_reasons": state.failure_reasons,
        "blocked_claims": blocked_claims,
        "claim_audit": state.claim_audit,
        "data_governance_audit": state.data_governance_audit,
        "metadata_registry_audit": state.metadata_registry_audit,
        "evidence_retrieval": state.evidence_retrieval,
        "orchestration_trace": state.orchestration_trace,
        "results_audit": state.results_audit,
        "phenotype_hpo_curation": state.phenotype_hpo_curation.model_dump() if state.phenotype_hpo_curation else None,
        "pedigree_inheritance_audit": state.pedigree_inheritance_audit.model_dump() if state.pedigree_inheritance_audit else None,
        "variant_intelligence": state.variant_intelligence.model_dump() if state.variant_intelligence else None,
        "pre_test_assessment": state.pre_test_assessment.model_dump() if state.pre_test_assessment else None,
        "test_strategy_workspace": state.test_strategy_workspace.model_dump() if state.test_strategy_workspace else None,
        "result_evidence_workspace": state.result_evidence_workspace.model_dump() if state.result_evidence_workspace else None,
        "validation_notes": {
            "validated_action_count": len(state.validated_actions),
            "trace_event_count": len(trace),
            "command_previews_are_dry_run_only": True,
            "selected_recipe_is_preview_only": True,
        },
        "safety_notes": [
            "Mock provider remains default unless explicitly configured otherwise.",
            "Generated command previews are not executed.",
            "Raw genomic input files are inventoried by filename/category only for this bundle.",
            "Reports are research workflow guidance, not clinical diagnosis or genetic counseling.",
            "Pre-test assessment outputs do not select, recommend, approve, or order a test.",
        ],
    }


def _claim_audit_payload(state: AgentState) -> dict[str, Any]:
    if state.claim_audit:
        payload = dict(state.claim_audit)
    else:
        payload = {
            "selected_recipe_id": (state.selected_recipe or {}).get("recipe_id"),
            "workflow_family": state.workflow_selection.get("workflow_family", "unknown"),
            "blocked_interpretations": (state.selected_recipe or {}).get("blocked_interpretations", []),
            "unsupported_claim_categories": [],
            "required_caveats": [],
            "human_review_flags": [],
        }
    payload.update(
        {
            "dry_run_only": True,
            "human_review_required": True,
            "external_tools_executed": False,
            "raw_genomic_files_parsed": False,
            "clinical_or_consumer_claims_blocked": True,
        }
    )
    return payload


def _results_audit_payload(state: AgentState) -> dict[str, Any]:
    payload = dict(state.results_audit or {})
    payload.update(
        {
            "workflow_family": state.workflow_selection.get("workflow_family", payload.get("workflow_family")),
            "selected_recipe_id": (state.selected_recipe or {}).get("recipe_id") or payload.get("selected_recipe_id"),
            "dry_run_only": True,
            "human_review_required": True,
            "external_tools_executed": False,
            "raw_genomic_files_parsed": False,
        }
    )
    return payload


def _data_governance_audit_payload(state: AgentState) -> dict[str, Any]:
    payload = dict(state.data_governance_audit or {})
    payload.update(
        {
            "workflow_family": state.workflow_selection.get("workflow_family", payload.get("workflow_family")),
            "selected_recipe_id": (state.selected_recipe or {}).get("recipe_id") or payload.get("selected_recipe_id"),
            "dry_run_only": True,
            "human_review_required": True,
            "external_tools_executed": False,
            "raw_genomic_files_parsed": False,
            "dataset_terms_verified": False,
            "raw_data_network_access_allowed": False,
            "legal_compliance_verified": False,
        }
    )
    return payload


def _metadata_registry_audit_payload(state: AgentState) -> dict[str, Any]:
    payload = dict(state.metadata_registry_audit or {})
    payload.update(
        {
            "workflow_family": state.workflow_selection.get("workflow_family", payload.get("workflow_family")),
            "research_lane": state.research_lane or payload.get("research_lane", "insufficient_inputs"),
            "dry_run_only": True,
            "human_review_required": True,
            "external_tools_executed": False,
            "raw_genomic_files_parsed": False,
            "biological_interpretation_made": False,
            "clinical_decision_made": False,
            "final_acmg_classification_made": False,
        }
    )
    return payload


def _evidence_retrieval_payload(state: AgentState) -> dict[str, Any]:
    payload = dict(state.evidence_retrieval or {})
    payload.update(
        {
            "query": state.query,
            "goal": state.query,
            "selected_lane": state.research_lane or payload.get("selected_lane", "insufficient_inputs"),
            "lane": state.research_lane or payload.get("lane", "insufficient_inputs"),
            "local_only": True,
            "network_called": False,
            "external_call_made": False,
            "external_llm_called": False,
            "external_tools_executed": False,
            "raw_data_ingested": False,
            "raw_genomic_files_parsed": False,
            "human_review_required": True,
            "biological_or_clinical_conclusion_made": False,
            "clinical_decision_made": False,
            "final_acmg_classification_made": False,
        }
    )
    return payload


def _orchestration_trace_payload(state: AgentState) -> dict[str, Any]:
    payload = dict(state.orchestration_trace or {})
    flags = dict(payload.get("safety_flags", {}) or {})
    flags.update(
        {
            "autonomous_tool_execution": False,
            "external_tools_executed": False,
            "external_llm_called": False,
            "raw_genomic_files_parsed": False,
            "raw_data_ingested": False,
            "free_form_node_spawning": False,
            "self_modification_allowed": False,
            "arbitrary_tool_access_allowed": False,
            "external_api_call_made": False,
            "biological_or_clinical_conclusion_made": False,
            "clinical_decision_made": False,
            "final_acmg_classification_made": False,
            "diagnosis_or_treatment_recommendation_made": False,
            "ancestry_caste_purity_claim_made": False,
            "deterministic_audits_authoritative": True,
            "human_review_required": True,
        }
    )
    payload.update(
        {
            "run_id": state.run_id,
            "orchestration_enabled": bool(payload.get("orchestration_enabled", True)),
            "orchestration_backend": payload.get("orchestration_backend", "deterministic_controlled_graph"),
            "langgraph_available": bool(payload.get("langgraph_available", False)),
            "fallback_used": bool(payload.get("fallback_used", True)),
            "graph_nodes_declared": payload.get("graph_nodes_declared", []),
            "graph_nodes_executed": payload.get("graph_nodes_executed", []),
            "graph_edges_declared": payload.get("graph_edges_declared", []),
            "blocked_nodes": payload.get("blocked_nodes", []),
            "node_statuses": payload.get("node_statuses", []),
            "safety_flags": flags,
            "raw_content_recorded": False,
            "final_decisions_recorded": False,
            "trace_scope": payload.get(
                "trace_scope",
                "Controlled orchestration preview records node status summaries only.",
            ),
        }
    )
    return payload


def _selected_recipe_payload(state: AgentState) -> dict[str, Any]:
    if not state.selected_recipe:
        return {
            "recipe_id": None,
            "version": None,
            "workflow_family": state.workflow_selection.get("workflow_family"),
            "status": None,
            "maturity_tier": None,
            "dry_run_only": True,
            "external_tools_executed": False,
            "raw_genomic_files_parsed": False,
            "human_review_required": True,
            "warning": state.recipe_selection_warning or "No deterministic dry-run recipe preview was selected.",
            "provenance_sources": [],
            "blocked_interpretations": [],
            "human_review_checklist": [],
        }
    return {
        "recipe_id": state.selected_recipe.get("recipe_id"),
        "version": state.selected_recipe.get("version"),
        "workflow_family": state.selected_recipe.get("workflow_family"),
        "status": state.selected_recipe.get("status"),
        "maturity_tier": state.selected_recipe.get("maturity_tier"),
        "dry_run_only": True,
        "external_tools_executed": False,
        "raw_genomic_files_parsed": False,
        "human_review_required": True,
        "provenance_sources": state.selected_recipe.get("provenance_sources", []),
        "blocked_interpretations": state.selected_recipe.get("blocked_interpretations", []),
        "human_review_checklist": state.selected_recipe.get("human_review_checklist", []),
    }


def _provenance_index(
    run_dir: Path,
    state: AgentState,
    generated_artifacts: dict[str, Path],
    repro_paths: dict[str, Path],
) -> dict[str, Any]:
    payload = {
        "run_id": run_dir.name,
        "selected_recipe": {
            "path": "reproducibility/selected_recipe.json",
            "artifact_class": "reproducibility_bundle",
        },
        "generated_artifacts": {
            key: {"path": _relative_to_run(run_dir, path), "artifact_class": "agent_output"}
            for key, path in sorted(generated_artifacts.items())
        },
        "reproducibility_bundle": {
            key: {"path": _relative_to_run(run_dir, path), "artifact_class": "reproducibility_bundle"}
            for key, path in sorted(repro_paths.items())
        },
        "checksum_scope": "Generated run artifacts and reproducibility files only; raw uploaded genomic files are excluded.",
        "provenance_scope": "Run-level artifact provenance index; not row-level parser provenance.",
    }
    clinical_path = repro_paths.get("repro_clinical_case_intake")
    if clinical_path and state.clinical_case_intake and state.clinical_case_intake.global_intake_context:
        payload["global_intake_context"] = {
            "path": _relative_to_run(run_dir, clinical_path),
            "json_pointer": "/global_intake_context",
            "artifact_class": "sanitized_user_supplied_context",
            "source_wording_verified": False,
        }
    pretest_path = repro_paths.get("repro_pre_test_assessment")
    if pretest_path and state.pre_test_assessment:
        payload["pre_test_assessment"] = {
            "path": _relative_to_run(run_dir, pretest_path),
            "json_pointer": "/",
            "artifact_class": "deterministic_clinical_research_assessment",
            "human_review_required": True,
        }
    strategy_path = repro_paths.get("repro_test_strategy_workspace")
    if strategy_path and state.test_strategy_workspace:
        payload["test_strategy_workspace"] = {
            "path": _relative_to_run(run_dir, strategy_path),
            "json_pointer": "/",
            "artifact_class": "deterministic_proposed_not_approved_test_strategy",
            "catalogue_version": state.test_strategy_workspace.catalogue_version,
            "rule_spec_version": state.test_strategy_workspace.rule_spec_version,
            "human_review_required": True,
        }
    result_evidence_path = repro_paths.get("repro_result_evidence_workspace")
    if result_evidence_path and state.result_evidence_workspace:
        payload["result_evidence_workspace"] = {
            "path": _relative_to_run(run_dir, result_evidence_path),
            "json_pointer": "/",
            "artifact_class": "immutable_source_linked_result_and_evidence_workspace",
            "result_intake_version": state.result_evidence_workspace.result_intake_version,
            "normalization_version": state.result_evidence_workspace.normalization_version,
            "retrieval_version": state.result_evidence_workspace.retrieval_version,
            "ledger_version": state.result_evidence_workspace.ledger_version,
            "human_review_required": True,
        }
    return payload


def _runtime_lock(run_dir: Path, state: AgentState, generated_artifacts: dict[str, Path], repro_paths: dict[str, Path]) -> dict[str, Any]:
    byok = state.byok_runtime
    return {
        "run_id": state.run_id,
        "timestamp_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "python_version": platform.python_version(),
        "python_executable": Path(sys.executable).name,
        "platform": platform.platform(),
        "version": INSILICOPOP_VERSION,
        "llm_provider": state.llm_provider,
        "external_llm_called": state.external_llm_called,
        "external_tools_executed": state.external_tools_executed,
        "byok_schema_version": byok.schema_version if byok else None,
        "byok_policy_version": byok.policy_version if byok else None,
        "byok_provider": byok.provider if byok else None,
        "byok_default_model": byok.model if byok else None,
        "byok_resolved_role_models": byok.resolved_role_models if byok else {},
        "byok_logical_request_count": byok.logical_request_count if byok else 0,
        "byok_workflow_provider_attempt_count": byok.workflow_provider_attempt_count if byok else 0,
        "byok_connection_test_attempt_count": byok.connection_test_attempt_count if byok else 0,
        "byok_connection_test_request_count": byok.connection_test_request_count if byok else 0,
        "byok_connection_test_success_count": byok.connection_test_success_count if byok else 0,
        "byok_connection_test_failure_count": byok.connection_test_failure_count if byok else 0,
        "byok_remaining_connection_tests": byok.remaining_connection_tests if byok else 0,
        "byok_cache_hit_count": byok.cache_hit_count if byok else 0,
        "byok_retry_count": byok.retry_count if byok else 0,
        "byok_external_workflow_call_made": byok.external_workflow_call_made if byok else False,
        "workflow_family": state.workflow_selection.get("workflow_family", "unknown"),
        "selected_recipe_id": (state.selected_recipe or {}).get("recipe_id"),
        "orchestration_backend": state.orchestration_trace.get("orchestration_backend") if state.orchestration_trace else None,
        "orchestration_fallback_used": state.orchestration_trace.get("fallback_used") if state.orchestration_trace else None,
        "clinical_intake_schema_version": state.clinical_case_intake.schema_version if state.clinical_case_intake else None,
        "clinical_intake_research_use_only": state.clinical_case_intake.research_use_only if state.clinical_case_intake else None,
        "global_intake_schema_version": (state.clinical_case_intake.global_intake_context or {}).get("schema_version") if state.clinical_case_intake else None,
        "locale_profile_type": ((state.clinical_case_intake.global_intake_context or {}).get("locale_profile") or {}).get("profile_type") if state.clinical_case_intake else None,
        "locale_profile_explicitly_selected": bool(((state.clinical_case_intake.global_intake_context or {}).get("locale_profile") or {}).get("profile_type")) if state.clinical_case_intake else False,
        "phenotype_hpo_curation_schema_version": state.phenotype_hpo_curation.schema_version if state.phenotype_hpo_curation else None,
        "hpo_registry_version": state.phenotype_hpo_curation.registry_version if state.phenotype_hpo_curation else None,
        "hpo_algorithm_version": state.phenotype_hpo_curation.algorithm_version if state.phenotype_hpo_curation else None,
        "phenotype_hpo_curation_artifact_available": state.phenotype_hpo_curation is not None,
        "pedigree_inheritance_audit_schema_version": state.pedigree_inheritance_audit.schema_version if state.pedigree_inheritance_audit else None,
        "pedigree_inheritance_audit_algorithm_version": state.pedigree_inheritance_audit.algorithm_version if state.pedigree_inheritance_audit else None,
        "pedigree_inheritance_audit_artifact_available": state.pedigree_inheritance_audit is not None,
        "inheritance_consistency_audit_performed": state.pedigree_inheritance_audit is not None,
        "inheritance_clinically_established": False,
        "variant_intelligence_schema_version": state.variant_intelligence.schema_version if state.variant_intelligence else None,
        "variant_intelligence_algorithm_version": state.variant_intelligence.algorithm_version if state.variant_intelligence else None,
        "variant_intelligence_artifact_available": state.variant_intelligence is not None,
        "variant_validation_performed": state.variant_intelligence is not None,
        "variant_normalization_performed": state.variant_intelligence.variant_normalization_performed if state.variant_intelligence else False,
        "pre_test_assessment_schema_version": state.pre_test_assessment.schema_version if state.pre_test_assessment else None,
        "pre_test_assessment_algorithm_version": state.pre_test_assessment.algorithm_version if state.pre_test_assessment else None,
        "pre_test_assessment_artifact_available": state.pre_test_assessment is not None,
        "pre_test_assessment_outcome": state.pre_test_assessment.assessment_outcome.value if state.pre_test_assessment else None,
        "test_strategy_workspace_schema_version": state.test_strategy_workspace.schema_version if state.test_strategy_workspace else None,
        "test_strategy_workspace_algorithm_version": state.test_strategy_workspace.algorithm_version if state.test_strategy_workspace else None,
        "test_strategy_catalogue_version": state.test_strategy_workspace.catalogue_version if state.test_strategy_workspace else None,
        "test_strategy_rule_spec_version": state.test_strategy_workspace.rule_spec_version if state.test_strategy_workspace else None,
        "test_strategy_workspace_artifact_available": state.test_strategy_workspace is not None,
        "test_strategy_workspace_status": state.test_strategy_workspace.workspace_status.value if state.test_strategy_workspace else None,
        "test_strategy_proposed_option_count": state.test_strategy_workspace.proposed_option_count if state.test_strategy_workspace else 0,
        "test_strategy_generated": state.test_strategy_workspace.test_strategy_generated if state.test_strategy_workspace else False,
        "result_intake_version": state.result_evidence_workspace.result_intake_version if state.result_evidence_workspace else None,
        "normalization_version": state.result_evidence_workspace.normalization_version if state.result_evidence_workspace else None,
        "normalization_rules": state.result_evidence_workspace.normalization_rules if state.result_evidence_workspace else [],
        "source_document_hashes": state.result_evidence_workspace.source_document_hashes if state.result_evidence_workspace else [],
        "retrieval_queries": [item.model_dump() for item in state.result_evidence_workspace.retrieval_queries] if state.result_evidence_workspace else [],
        "retrieval_source_versions": state.result_evidence_workspace.retrieval_source_versions if state.result_evidence_workspace else {},
        "retrieval_timestamps": [item.retrieved_at for item in state.result_evidence_workspace.retrieval_records if item.retrieved_at] if state.result_evidence_workspace else [],
        "raw_response_hashes": state.result_evidence_workspace.raw_response_hashes if state.result_evidence_workspace else [],
        "ledger_entry_ids": [item.ledger_entry_id for item in state.result_evidence_workspace.ledger_entries] if state.result_evidence_workspace else [],
        "human_review_actions": [item.model_dump() for item in state.result_evidence_workspace.review_actions] if state.result_evidence_workspace else [],
        "result_evidence_external_llm_called": state.result_evidence_workspace.external_llm_called if state.result_evidence_workspace else False,
        "result_evidence_provider": state.result_evidence_workspace.provider if state.result_evidence_workspace else None,
        "result_evidence_byok_used": state.result_evidence_workspace.byok_used if state.result_evidence_workspace else False,
        "evidence_ledger_version": state.result_evidence_workspace.ledger_version if state.result_evidence_workspace else None,
        "result_evidence_workspace_artifact_available": state.result_evidence_workspace is not None,
        "test_recommendation_made": False,
        "test_order_placed": False,
        "variant_pathogenicity_interpretation_performed": False,
        "transcript_selection_performed": False,
        "raw_genomic_files_parsed": False,
        "human_review_required": True,
        "generated_artifact_list": sorted(_relative_to_run(run_dir, path) for path in generated_artifacts.values()),
        "reproducibility_bundle_file_list": sorted(_relative_to_run(run_dir, path) for path in repro_paths.values()),
    }


def _checksums(run_dir: Path, generated_artifacts: dict[str, Path], repro_paths: dict[str, Path]) -> str:
    candidates = list(generated_artifacts.values()) + [
        path for key, path in repro_paths.items() if key != "repro_checksums"
    ]
    rows = []
    for path in sorted({path.resolve() for path in candidates}, key=lambda item: _relative_to_run(run_dir, item)):
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {_relative_to_run(run_dir, path)}")
    return "\n".join(rows) + ("\n" if rows else "")


def _relative_to_run(run_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")
