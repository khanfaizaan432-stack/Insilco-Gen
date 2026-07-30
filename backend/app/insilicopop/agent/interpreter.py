from __future__ import annotations

import re
from pathlib import Path
from typing import Any


REPRODUCIBILITY_FILES = [
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
    "reproducibility/clinical_case_intake.json",
    "reproducibility/phenotype_hpo_curation.json",
    "reproducibility/pedigree_inheritance_audit.json",
    "reproducibility/variant_intelligence.json",
    "reproducibility/pre_test_assessment.json",
    "reproducibility/test_strategy_workspace.json",
    "reproducibility/result_evidence_workspace.json",
    "reproducibility/specialist_agent_workspace.json",
    "reproducibility/guardrail_decisions.json",
    "reproducibility/provenance_index.json",
    "reproducibility/runtime_lock.json",
    "reproducibility/checksums.sha256",
]


class AgentInterpreter:
    def final_report(
        self,
        *,
        run_id: str | None = None,
        query: str | None = None,
        uploaded_files: dict[str, str] | None = None,
        reliability_score: int | None,
        planned_count: int,
        completed_count: int = 0,
        blocked_count: int,
        planned_actions: list[Any] | None = None,
        completed_actions: list[Any] | None = None,
        blocked_actions: list[Any] | None = None,
        failures: list[dict[str, Any]],
        workflow_selection: dict[str, Any] | None = None,
        selected_recipe: dict[str, Any] | None = None,
        recipe_selection_warning: str | None = None,
        command_previews: list[dict[str, Any]] | None = None,
        claim_audit: dict[str, Any] | None = None,
        results_audit: dict[str, Any] | None = None,
        data_governance_audit: dict[str, Any] | None = None,
        metadata_registry_audit: dict[str, Any] | None = None,
        evidence_retrieval: dict[str, Any] | None = None,
        orchestration_trace: dict[str, Any] | None = None,
        clinical_case_intake: dict[str, Any] | None = None,
        phenotype_hpo_curation: dict[str, Any] | None = None,
        pedigree_inheritance_audit: dict[str, Any] | None = None,
        variant_intelligence: dict[str, Any] | None = None,
        pre_test_assessment: dict[str, Any] | None = None,
        test_strategy_workspace: dict[str, Any] | None = None,
        result_evidence_workspace: dict[str, Any] | None = None,
        specialist_agent_workspace: dict[str, Any] | None = None,
        byok_runtime: dict[str, Any] | None = None,
        carried_memory: dict[str, Any] | None = None,
        llm_provider: str = "mock",
        external_llm_called: bool = False,
        external_tools_executed: bool = False,
        current_step: str | None = None,
        generated_artifact_count: int | None = None,
        validated_actions: list[dict[str, Any]] | None = None,
    ) -> str:
        workflow_selection = workflow_selection or {}
        selected_recipe = selected_recipe or None
        uploaded_files = uploaded_files or {}
        planned_actions = planned_actions or []
        completed_actions = completed_actions or []
        blocked_actions = blocked_actions or []
        command_previews = command_previews or []
        claim_audit = claim_audit or {}
        results_audit = results_audit or {}
        data_governance_audit = data_governance_audit or {}
        metadata_registry_audit = metadata_registry_audit or {}
        evidence_retrieval = evidence_retrieval or {}
        orchestration_trace = orchestration_trace or {}
        clinical_case_intake = clinical_case_intake or {}
        phenotype_hpo_curation = phenotype_hpo_curation or {}
        pedigree_inheritance_audit = pedigree_inheritance_audit or {}
        variant_intelligence = variant_intelligence or {}
        pre_test_assessment = pre_test_assessment or {}
        test_strategy_workspace = test_strategy_workspace or {}
        result_evidence_workspace = result_evidence_workspace or {}
        specialist_agent_workspace = specialist_agent_workspace or {}
        byok_runtime = byok_runtime or {}
        carried_memory = carried_memory or {}
        validated_actions = validated_actions or []

        lines = [
            "# InSilicoPop Agent Run Report",
            "",
            "Deterministic dry-run agent loop. No external tools were executed.",
            "This is research workflow guidance, not clinical diagnosis or genetic counseling.",
            "",
            "## 1. Research Goal",
            "",
            _redact(query) if query else "No explicit research goal was provided.",
            "",
            "## 2. Input Inventory",
            "",
            *_input_inventory_lines(uploaded_files),
            "",
            "Raw genomic files were inventoried only. They were not parsed or executed in this run.",
            "",
            "## 3. Workflow Selection",
            "",
            f"Selected workflow family: `{workflow_selection.get('workflow_family', 'unknown')}`",
            "",
            f"Confidence: {workflow_selection.get('confidence', 'unknown')}",
            "",
            "Matched inputs:",
            *_list_lines(workflow_selection.get("matched_inputs", []), none_text="No matched input signals recorded."),
            "",
            "Missing inputs:",
            *_list_lines(workflow_selection.get("missing_inputs", []), none_text="No workflow-level missing inputs recorded."),
            "",
            "Rationale:",
            _redact(str(workflow_selection.get("rationale", "not recorded"))),
            "",
            "## Recipe Preview",
            "",
            *_recipe_preview_lines(selected_recipe, recipe_selection_warning),
            "",
            "## 4. Planned Actions",
            "",
            f"Planned actions: {planned_count}",
            f"Completed actions: {completed_count}",
            f"Blocked actions: {blocked_count}",
            "",
            *_action_lines(planned_actions),
            "",
            "## 5. Dry-Run Command Previews",
            "",
            "These commands were not executed by InSilicoPop.",
            "Execution enabled: false",
            "",
            *_command_preview_lines(command_previews),
            "",
            "## 6. Missing Inputs and Dependencies",
            "",
            *_missing_dependency_lines(workflow_selection, failures, command_previews),
            "",
            "## 7. Blocked Actions and Unsupported Claims",
            "",
            *_blocked_claim_lines(blocked_actions, failures, validated_actions),
            "",
            "## Recipe-Aware Claim Audit",
            "",
            *_claim_audit_lines(claim_audit),
            "",
            *_data_governance_audit_lines(data_governance_audit),
            "",
            *_metadata_registry_audit_lines(metadata_registry_audit),
            "",
            *_evidence_retrieval_lines(evidence_retrieval),
            "",
            *_orchestration_trace_lines(orchestration_trace),
            "",
            *_byok_runtime_lines(byok_runtime),
            "",
            *_clinical_case_intake_lines(clinical_case_intake),
            "",
            *_global_intake_context_lines(clinical_case_intake.get("global_intake_context") or {}),
            "",
            *_phenotype_hpo_curation_lines(phenotype_hpo_curation),
            "",
            *_pedigree_inheritance_audit_lines(pedigree_inheritance_audit),
            "",
            *_pre_test_assessment_lines(
                pre_test_assessment,
                strategy_generated=bool(test_strategy_workspace.get("test_strategy_generated", False)),
            ),
            "",
            *_test_strategy_workspace_lines(test_strategy_workspace),
            "",
            *_result_evidence_workspace_lines(result_evidence_workspace),
            "",
            *_specialist_agent_workspace_lines(specialist_agent_workspace),
            "",
            *_variant_intelligence_lines(variant_intelligence),
            "",
            *_results_audit_section_lines(results_audit),
            "Population-genetics guardrails:",
            "- ADMIXTURE components must not be equated with literal ancestry.",
            "- PCA clusters must not be interpreted as caste/religion/community identity.",
            "- ROH must not be claimed to prove endogamy without caveats.",
            "- FST/selection scans must not be claimed to prove selection without adequate controls.",
            "- No purity/superiority claims.",
            "- No clinical diagnosis.",
            "",
            "## 8. Scientific Validity Notes",
            "",
            *_validity_notes(str(workflow_selection.get("workflow_family", "unknown"))),
            "",
            "## 9. Memory Capsule Summary",
            "",
            *_memory_lines(carried_memory),
            "",
            "## 10. Reproducibility Bundle",
            "",
            "Generated reproducibility files:",
            *[f"- {path}" for path in REPRODUCIBILITY_FILES],
            "",
            "- Command previews are dry-run only.",
            "- Generated artifact checksums are recorded in `reproducibility/checksums.sha256`.",
            "- raw user genomic files are not checksummed by default.",
            "",
            "## 11. Human Review Required",
            "",
            "- Approve or edit planned commands before running externally.",
            "- Confirm sample metadata and population labels.",
            "- Confirm LD pruning/QC status before interpretation.",
            "- Review blocked claims.",
            "- Review final report before publication or sharing.",
            "",
            "InSilicoPop provides research workflow support and scientific audit assistance. It does not replace expert human review.",
            "",
            "## 12. Run Metadata",
            "",
            f"- run_id: `{run_id or 'unknown'}`",
            f"- llm_provider: `{_redact(llm_provider)}`",
            f"- external_llm_called: `{str(external_llm_called).lower()}`",
            f"- external_tools_executed: `{str(external_tools_executed).lower()}`",
            f"- workflow_family: `{workflow_selection.get('workflow_family', 'unknown')}`",
            f"- research_lane: `{metadata_registry_audit.get('research_lane', 'unknown')}`",
            f"- current_step: `{current_step or 'unknown'}`",
            f"- reliability_score: `{reliability_score if reliability_score is not None else 'unknown'}`",
            f"- generated_artifact_count: `{generated_artifact_count if generated_artifact_count is not None else 'unknown'}`",
        ]
        return "\n".join(lines) + "\n"


def _input_inventory_lines(uploaded_files: dict[str, str]) -> list[str]:
    if not uploaded_files:
        return ["- No declared inputs were provided."]
    categories = {
        "VCF": [],
        "PLINK bed/bim/fam": [],
        "ped/map": [],
        "pgen/pvar/psam": [],
        "BAM/CRAM": [],
        "metadata": [],
        "result files": [],
        "audit/result outputs": [],
        "other": [],
    }
    for field_name, filename in sorted(uploaded_files.items()):
        for category in _categories_for(field_name, filename):
            categories[category].append(f"{field_name}: {_redact(filename)}")
    lines: list[str] = []
    for category, values in categories.items():
        if values:
            lines.append(f"- {category}: {', '.join(values)}")
    return lines or ["- No declared inputs were provided."]


def _recipe_preview_lines(selected_recipe: dict[str, Any] | None, warning: str | None) -> list[str]:
    if not selected_recipe:
        return [
            "- selected_recipe: none",
            f"- warning: {_redact(warning or 'No deterministic dry-run recipe preview was selected.')}",
            "- Existing workflow selection remains available; no recipe execution occurred.",
        ]
    lines = [
        f"- selected recipe ID: `{_redact(str(selected_recipe.get('recipe_id', 'unknown')))}`",
        f"- version: `{_redact(str(selected_recipe.get('version', 'unknown')))}`",
        f"- workflow family: `{_redact(str(selected_recipe.get('workflow_family', 'unknown')))}`",
        f"- status: `{_redact(str(selected_recipe.get('status', 'unknown')))}`",
        f"- maturity tier: `{_redact(str(selected_recipe.get('maturity_tier', 'unknown')))}`",
        "- dry-run-only: true. This is a selected deterministic dry-run recipe preview; it was not executed.",
        "- external_tools_executed: false",
        "- raw_genomic_files_parsed: false",
        "- human_review_required: true",
        "",
        "Provenance sources:",
    ]
    sources = selected_recipe.get("provenance_sources", []) or []
    if sources:
        for source in sources:
            if isinstance(source, dict):
                title = _redact(str(source.get("title", "source")))
                source_type = _redact(str(source.get("source_type", "unknown")))
                note = source.get("note")
                url = source.get("url")
                suffix = f" ({source_type})"
                if url:
                    suffix += f" - {_redact(str(url))}"
                if note:
                    suffix += f": {_redact(str(note))}"
                lines.append(f"- {title}{suffix}")
            else:
                lines.append(f"- {_redact(str(source))}")
    else:
        lines.append("- No recipe provenance sources recorded.")
    lines.extend(["", "Planned dry-run recipe steps:"])
    steps = selected_recipe.get("dry_run_steps", []) or []
    if steps:
        for step in steps:
            if isinstance(step, dict):
                lines.append(f"- {_redact(str(step.get('step_id', 'step')))}: {_redact(str(step.get('title', 'planned dry-run step')))}")
                if step.get("description"):
                    lines.append(f"  {_redact(str(step['description']))}")
            else:
                lines.append(f"- {_redact(str(step))}")
    else:
        lines.append("- No dry-run recipe steps recorded.")
    lines.extend(["", "Blocked interpretations:"])
    lines.extend(_list_lines(selected_recipe.get("blocked_interpretations", []), none_text="No blocked interpretations recorded."))
    lines.extend(["", "Scientific validity notes:"])
    lines.extend(_list_lines(selected_recipe.get("scientific_validity_notes", []), none_text="No scientific validity notes recorded."))
    lines.extend(["", "Human review checklist:"])
    lines.extend(_list_lines(selected_recipe.get("human_review_checklist", []), none_text="No human review checklist recorded."))
    return lines


def _categories_for(field_name: str, filename: str) -> list[str]:
    lowered = f"{field_name} {filename}".lower()
    suffixes = set(Path(filename.lower()).suffixes)
    if filename.lower().endswith(".vcf.gz"):
        suffixes.add(".vcf.gz")
    categories: list[str] = []
    if ".vcf" in suffixes or ".vcf.gz" in suffixes:
        categories.append("VCF")
    if {".bed", ".bim", ".fam"} & suffixes:
        categories.append("PLINK bed/bim/fam")
    if {".ped", ".map"} & suffixes:
        categories.append("ped/map")
    if {".pgen", ".pvar", ".psam"} & suffixes:
        categories.append("pgen/pvar/psam")
    if {".bam", ".cram"} & suffixes:
        categories.append("BAM/CRAM")
    if "metadata" in lowered or "sample" in lowered:
        categories.append("metadata")
    if field_name in {"pca", "admixture", "fst", "roh", "plink_qc", "selection_scan"}:
        categories.append("audit/result outputs")
    if any(marker in lowered for marker in ["pca", "admixture", "fst", "roh", "selection", "smartpca", "eigenvec", "eigenval"]):
        categories.append("result files")
    return categories or ["other"]


def _action_lines(actions: list[Any]) -> list[str]:
    if not actions:
        return ["- No planned actions were recorded."]
    lines = []
    for action in actions:
        item = _object_dict(action)
        title = _redact(str(item.get("title", "untitled action")))
        action_type = item.get("action_type", "unknown")
        status = item.get("status", "unknown")
        lines.append(f"- `{action_type}` ({status}): {title}")
    return lines


def _command_preview_lines(command_previews: list[dict[str, Any]]) -> list[str]:
    if not command_previews:
        return ["- No dry-run command previews were generated."]
    recipe_ids = sorted({str(preview.get("selected_recipe_id")) for preview in command_previews if preview.get("selected_recipe_id")})
    recipe_text = f" Selected recipe ID(s): `{', '.join(_redact(recipe_id) for recipe_id in recipe_ids)}`." if recipe_ids else ""
    lines: list[str] = [
        "- The selected deterministic recipe shaped these dry-run previews."
        " The previews were not executed. Raw genomic files were not parsed."
        " Human review is required before any real-world command use."
        f"{recipe_text}",
    ]
    for index, preview in enumerate(command_previews, start=1):
        lines.append(f"{index}. Tool: `{_redact(str(preview.get('tool', 'unknown')))}`")
        lines.append(f"   Purpose: {_redact(str(preview.get('purpose', 'not recorded')))}")
        if preview.get("selected_recipe_id"):
            lines.append(f"   Selected recipe: `{_redact(str(preview.get('selected_recipe_id')))}`")
        if preview.get("recipe_step_id"):
            lines.append(f"   Recipe step: `{_redact(str(preview.get('recipe_step_id')))}`")
        lines.append(f"   Command preview:")
        lines.append("   ```text")
        for command_line in str(preview.get("command", "not recorded")).splitlines() or ["not recorded"]:
            lines.append(f"   {_redact(command_line)}")
        lines.append("   ```")
        lines.append(f"   Required inputs: {_join_values(preview.get('required_inputs', []))}")
        lines.append(f"   Expected outputs: {_join_values(preview.get('expected_outputs', []))}")
        lines.append(f"   Dry-run only: {str(bool(preview.get('dry_run_only', True))).lower()}")
        lines.append(f"   Execution enabled: {str(bool(preview.get('execution_enabled', False))).lower()}")
        lines.append(f"   External tools executed: {str(bool(preview.get('external_tools_executed', False))).lower()}")
        lines.append(f"   Raw genomic files parsed: {str(bool(preview.get('raw_genomic_files_parsed', False))).lower()}")
        lines.append(f"   Human review required: {str(bool(preview.get('human_review_required', True))).lower()}")
    return lines


def _missing_dependency_lines(
    workflow_selection: dict[str, Any],
    failures: list[dict[str, Any]],
    command_previews: list[dict[str, Any]],
) -> list[str]:
    lines = []
    lines.extend(f"- Missing input: {_redact(str(item))}" for item in workflow_selection.get("missing_inputs", []) or [])
    lines.extend(f"- Blocked until: {_redact(str(item))}" for item in workflow_selection.get("blocked_until", []) or [])
    for failure in failures:
        fix = failure.get("recommended_fix")
        if fix:
            lines.append(f"- Required fix: {_redact(str(fix))}")
    blocked_if = []
    for preview in command_previews:
        blocked_if.extend(str(item) for item in preview.get("blocked_if", []) or [])
    lines.extend(f"- Command dependency: {_redact(item)}" for item in sorted(set(blocked_if)))
    return lines or ["- No missing inputs or dependencies were recorded."]


def _blocked_claim_lines(blocked_actions: list[Any], failures: list[dict[str, Any]], validated_actions: list[dict[str, Any]]) -> list[str]:
    lines = []
    for action in blocked_actions:
        item = _object_dict(action)
        lines.append(
            f"- Blocked action `{item.get('action_type', 'unknown')}`: {_redact(str(item.get('title', 'untitled action')))}"
        )
        if item.get("blocked_reason"):
            lines.append(f"  Reason: {_redact(str(item['blocked_reason']))}")
    for validated in validated_actions:
        for reason in validated.get("blocking_reasons", []) or []:
            lines.append(f"- Blocked claim: {_redact(str(reason))}")
    for failure in failures:
        lines.append(
            f"- {failure.get('severity', 'unknown')}: {_redact(str(failure.get('failure_type', 'failure')))} - {_redact(str(failure.get('message', 'not recorded')))}"
        )
    return lines or ["- No blocked actions or unsupported claims were recorded."]


def _claim_audit_lines(claim_audit: dict[str, Any]) -> list[str]:
    if not claim_audit:
        return ["- No recipe-aware claim audit was generated."]
    lines = [
        f"- selected_recipe_id: `{_redact(str(claim_audit.get('selected_recipe_id', 'unknown')))}`",
        f"- workflow_family: `{_redact(str(claim_audit.get('workflow_family', 'unknown')))}`",
        f"- dry_run_only: `{str(bool(claim_audit.get('dry_run_only', True))).lower()}`",
        f"- human_review_required: `{str(bool(claim_audit.get('human_review_required', True))).lower()}`",
        f"- external_tools_executed: `{str(bool(claim_audit.get('external_tools_executed', False))).lower()}`",
        f"- raw_genomic_files_parsed: `{str(bool(claim_audit.get('raw_genomic_files_parsed', False))).lower()}`",
        "",
        "Blocked interpretation categories:",
    ]
    lines.extend(_list_lines(claim_audit.get("blocked_interpretations", []), none_text="No blocked interpretation categories recorded."))
    lines.extend(["", "Unsupported claim categories:"])
    lines.extend(_list_lines(claim_audit.get("unsupported_claim_categories", []), none_text="No unsupported claim categories recorded."))
    lines.extend(["", "Required caveats:"])
    lines.extend(_list_lines(claim_audit.get("required_caveats", []), none_text="No required caveats recorded."))
    lines.extend(["", "Human review flags:"])
    lines.extend(_list_lines(claim_audit.get("human_review_flags", []), none_text="No human review flags recorded."))
    return lines


def _data_governance_audit_lines(data_governance_audit: dict[str, Any]) -> list[str]:
    if not data_governance_audit:
        return [
            "## Data Governance Audit",
            "",
            "- No data governance audit was generated.",
        ]
    scope = data_governance_audit.get("data_use_agreement_scope", {}) or {}
    lines = [
        "## Data Governance Audit",
        "",
        "- human review is required.",
        "- Audit checks declared research-use scope, dataset access model, consent/DUA compatibility, credential model, and governance caveats.",
        "- Audit does not verify legal compliance.",
        "- Audit does not replace institutional ethics committee, data access committee, PI, clinician, data privacy officer, or legal review.",
        f"- status: `{_redact(str(data_governance_audit.get('status', 'unknown')))}`",
        f"- declared_scope_present: `{str(bool(data_governance_audit.get('declared_scope_present', False))).lower()}`",
        f"- dataset_terms_verified: `{str(bool(data_governance_audit.get('dataset_terms_verified', False))).lower()}`",
        f"- raw_data_network_access_allowed: `{str(bool(data_governance_audit.get('raw_data_network_access_allowed', False))).lower()}`",
        f"- human_review_required: `{str(bool(data_governance_audit.get('human_review_required', True))).lower()}`",
        f"- data_access_credential_model: `{_redact(str(scope.get('data_access_credential_model', 'unknown')))}`",
        f"- dataset_source: `{_redact(str(scope.get('dataset_source', 'unknown')))}`",
        "",
        "Blocked by governance policy:",
    ]
    lines.extend(_list_lines(data_governance_audit.get("blocked", []), none_text="No governance policy blocks recorded."))
    lines.extend(["", "Governance caveats:"])
    lines.extend(_list_lines(data_governance_audit.get("caveats", []), none_text="No governance caveats recorded."))
    lines.append("")
    return lines


def _metadata_registry_audit_lines(metadata_registry_audit: dict[str, Any]) -> list[str]:
    if not metadata_registry_audit:
        return [
            "## Metadata Registry Audit",
            "",
            "- No metadata registry audit was generated.",
        ]
    registry = metadata_registry_audit.get("metadata_registry", {}) or {}
    project = registry.get("project_metadata", {}) if isinstance(registry, dict) else {}
    sample = registry.get("sample_metadata", {}) if isinstance(registry, dict) else {}
    lines = [
        "## Metadata Registry Audit",
        "",
        f"- research_lane: `{_redact(str(metadata_registry_audit.get('research_lane', 'unknown')))}`",
        f"- status: `{_redact(str(metadata_registry_audit.get('status', 'unknown')))}`",
        f"- metadata_completeness_score: `{metadata_registry_audit.get('metadata_completeness_score', 0.0)}`",
        f"- human_review_required: `{str(bool(metadata_registry_audit.get('human_review_required', True))).lower()}`",
        f"- biological_interpretation_made: `{str(bool(metadata_registry_audit.get('biological_interpretation_made', False))).lower()}`",
        f"- clinical_decision_made: `{str(bool(metadata_registry_audit.get('clinical_decision_made', False))).lower()}`",
        f"- project_title_declared: `{str(bool(project.get('title'))).lower()}`",
        f"- data_access_level: `{_redact(str(project.get('data_access_level', 'unknown')))}`",
        f"- cohort_labels_declared: `{str(bool(sample.get('cohort_labels_declared', False))).lower()}`",
        "",
        "Missing required metadata:",
    ]
    lines.extend(_list_lines(metadata_registry_audit.get("missing_required_metadata", []), none_text="No missing required metadata recorded."))
    lines.extend(["", "Metadata caveats:"])
    lines.extend(_list_lines(metadata_registry_audit.get("caveats", []), none_text="No metadata caveats recorded."))
    lines.extend(["", "Out-of-scope blocks:"])
    lines.extend(_list_lines(metadata_registry_audit.get("blocked_out_of_scope_categories", []), none_text="No out-of-scope metadata requests recorded."))
    lines.append("")
    return lines


def _evidence_retrieval_lines(evidence_retrieval: dict[str, Any]) -> list[str]:
    if not evidence_retrieval:
        return [
            "## Evidence Retrieval Preview",
            "",
            "- No evidence retrieval preview was generated.",
        ]
    snippets = evidence_retrieval.get("snippets", []) or []
    source_ids = evidence_retrieval.get("source_ids", []) or []
    warnings = evidence_retrieval.get("warnings", []) or []
    caveats = evidence_retrieval.get("caveats", []) or []
    lines = [
        "## Evidence Retrieval Preview",
        "",
        "- local evidence retrieval only.",
        "- source-grounded snippets only.",
        "- no external database/API call made.",
        "- no biological/clinical conclusion made.",
        "- human review required.",
        f"- retrieval_mode: `{_redact(str(evidence_retrieval.get('retrieval_mode', 'unknown')))}`",
        f"- chroma_available: `{str(bool(evidence_retrieval.get('chroma_available', False))).lower()}`",
        f"- langchain_available: `{str(bool(evidence_retrieval.get('langchain_available', False))).lower()}`",
        f"- snippets_returned: `{int(evidence_retrieval.get('snippets_returned', 0) or 0)}`",
        f"- local_only: `{str(bool(evidence_retrieval.get('local_only', True))).lower()}`",
        f"- external_call_made: `{str(bool(evidence_retrieval.get('external_call_made', False))).lower()}`",
        f"- raw_data_ingested: `{str(bool(evidence_retrieval.get('raw_data_ingested', False))).lower()}`",
        "",
        "Source IDs:",
    ]
    lines.extend(_list_lines(source_ids, none_text="No source IDs recorded."))
    lines.extend(["", "Retrieval warnings:"])
    lines.extend(_list_lines(warnings, none_text="No retrieval warnings recorded."))
    lines.extend(["", "Retrieval caveats:"])
    lines.extend(_list_lines(caveats, none_text="No retrieval caveats recorded."))
    lines.extend(["", "Retrieved snippets:"])
    if snippets:
        for item in snippets:
            if not isinstance(item, dict):
                continue
            source_id = _redact(str(item.get("source_id", "unknown")))
            method = _redact(str(item.get("retrieval_method", "unknown")))
            snippet = _redact(str(item.get("snippet", "")))
            lines.append(f"- `{source_id}` via `{method}`: {snippet}")
    else:
        lines.append("- No snippets returned.")
    lines.append("")
    return lines


def _orchestration_trace_lines(orchestration_trace: dict[str, Any]) -> list[str]:
    if not orchestration_trace:
        return [
            "## Controlled Orchestration Preview",
            "",
            "- No controlled orchestration trace was generated.",
            "- deterministic audits remain authoritative.",
            "- human review required.",
        ]
    flags = orchestration_trace.get("safety_flags", {}) or {}
    executed = orchestration_trace.get("graph_nodes_executed", []) or []
    blocked = orchestration_trace.get("blocked_nodes", []) or []
    return [
        "## Controlled Orchestration Preview",
        "",
        "- orchestration is bounded to an allowlisted graph.",
        "- no autonomous tool execution occurred.",
        "- no external LLM/API call was made by default.",
        "- no raw genomic data was parsed.",
        "- deterministic audits remain authoritative.",
        "- human review required.",
        f"- orchestration_enabled: `{str(bool(orchestration_trace.get('orchestration_enabled', True))).lower()}`",
        f"- orchestration_backend: `{_redact(str(orchestration_trace.get('orchestration_backend', 'unknown')))}`",
        f"- langgraph_available: `{str(bool(orchestration_trace.get('langgraph_available', False))).lower()}`",
        f"- fallback_used: `{str(bool(orchestration_trace.get('fallback_used', True))).lower()}`",
        f"- nodes_executed: `{len(executed)}`",
        f"- blocked_nodes: `{_redact(', '.join(str(item) for item in blocked) if blocked else 'none')}`",
        f"- autonomous_tool_execution: `{str(bool(flags.get('autonomous_tool_execution', False))).lower()}`",
        f"- external_tools_executed: `{str(bool(flags.get('external_tools_executed', False))).lower()}`",
        f"- external_llm_called: `{str(bool(flags.get('external_llm_called', False))).lower()}`",
        f"- raw_genomic_files_parsed: `{str(bool(flags.get('raw_genomic_files_parsed', False))).lower()}`",
        f"- biological_or_clinical_conclusion_made: `{str(bool(flags.get('biological_or_clinical_conclusion_made', False))).lower()}`",
        f"- clinical_decision_made: `{str(bool(flags.get('clinical_decision_made', False))).lower()}`",
        f"- final_acmg_classification_made: `{str(bool(flags.get('final_acmg_classification_made', False))).lower()}`",
    ]


def _clinical_case_intake_lines(clinical_case_intake: dict[str, Any]) -> list[str]:
    if not clinical_case_intake:
        return []
    counts = clinical_case_intake.get("phenotype_state_counts", {}) or {}
    hypotheses = clinical_case_intake.get("supplied_hypotheses", []) or []
    hypothesis_summaries = [
        f"{item.get('hypothesis_type', 'unknown')}:{item.get('inheritance_candidate') or 'supplied'}"
        for item in hypotheses
        if isinstance(item, dict)
    ]
    return [
        "## Clinical Case Intake Preview",
        "",
        "Research-use-only structured clinical genetics curation intake. No diagnosis, treatment recommendation, final ACMG/AMP classification, clinical sign-out, or patient-facing return was made.",
        f"- schema_version: `{_redact(str(clinical_case_intake.get('schema_version', 'unknown')))}`",
        f"- research_use_only: `{str(bool(clinical_case_intake.get('research_use_only', True))).lower()}`",
        f"- pseudonymous_case_id: `{_redact(str(clinical_case_intake.get('pseudonymous_case_id', 'unknown')))}`",
        f"- intended_use: `{_redact(str(clinical_case_intake.get('intended_use', 'unknown')))}`",
        f"- redaction_declared: `{str(bool(clinical_case_intake.get('redaction_declared', False))).lower()}`",
        f"- intake_completeness: `{_redact(str(clinical_case_intake.get('intake_completeness', 'unknown')))}`",
        f"- phenotype_state_counts: `{_redact(', '.join(f'{key}={counts[key]}' for key in sorted(counts)))}`",
        f"- candidate_variant_count: `{int(clinical_case_intake.get('candidate_variant_count', 0) or 0)}`",
        f"- pedigree_record_count: `{int(clinical_case_intake.get('pedigree_record_count', 0) or 0)}`",
        f"- supplied_hypotheses: `{_redact(', '.join(hypothesis_summaries) if hypothesis_summaries else 'none')}`",
        f"- validation_errors: `{len(clinical_case_intake.get('validation_errors', []) or [])}`",
        f"- validation_warnings: `{len(clinical_case_intake.get('validation_warnings', []) or [])}`",
        f"- missing_information: `{len(clinical_case_intake.get('missing_information', []) or [])}`",
        f"- policy_blocks: `{len(clinical_case_intake.get('policy_blocks', []) or [])}`",
        f"- reviewer_status: `{_redact(str(clinical_case_intake.get('reviewer_status', 'unknown')))}`",
        "- human_review_required: `true`",
        "- inheritance_calculation_performed: `false`",
        "- variant_normalization_performed: `false`",
        "- external_llm_called: `false`",
        "- external_tools_executed: `false`",
        "- raw_genomic_files_parsed: `false`",
    ]


def _byok_runtime_lines(runtime: dict[str, Any]) -> list[str]:
    if not runtime:
        return []
    budget = runtime.get("budget") or {}
    return [
        "## BYOK Runtime Provenance",
        "",
        "Non-secret, session-derived configuration and usage only. Credentials and request prompts are never included in this report.",
        f"- provider: `{_redact(str(runtime.get('provider', 'mock')))}`",
        f"- model: `{_redact(str(runtime.get('model', 'mock')))}`",
        f"- external_provider_configured: `{str(runtime.get('provider') != 'mock').lower()}`",
        f"- request_count: `{int(runtime.get('request_count', 0) or 0)}`",
        f"- provider_attempt_count: `{int(runtime.get('provider_attempt_count', 0) or 0)}`",
        f"- workflow_provider_attempt_count: `{int(runtime.get('workflow_provider_attempt_count', 0) or 0)}`",
        f"- connection_test_attempt_count: `{int(runtime.get('connection_test_attempt_count', 0) or 0)}`",
        f"- connection_test_request_count: `{int(runtime.get('connection_test_request_count', 0) or 0)}`",
        f"- connection_test_success_count: `{int(runtime.get('connection_test_success_count', 0) or 0)}`",
        f"- connection_test_failure_count: `{int(runtime.get('connection_test_failure_count', 0) or 0)}`",
        f"- remaining_connection_tests: `{int(runtime.get('remaining_connection_tests', 0) or 0)}`",
        f"- cache_hit_count: `{int(runtime.get('cache_hit_count', 0) or 0)}`",
        f"- retry_count: `{int(runtime.get('retry_count', 0) or 0)}`",
        f"- input_tokens: `{int(runtime.get('input_tokens', 0) or 0)}`",
        f"- output_tokens: `{int(runtime.get('output_tokens', 0) or 0)}`",
        f"- estimated_cost_usd: `{float(runtime.get('estimated_cost_usd', 0) or 0):.8f}`",
        f"- max_calls: `{int(budget.get('max_calls', 0) or 0)}`",
        f"- max_total_tokens: `{int(budget.get('max_total_tokens', 0) or 0)}`",
        f"- external_call_made: `{str(bool(runtime.get('external_call_made', False))).lower()}`",
        f"- external_workflow_call_made: `{str(bool(runtime.get('external_workflow_call_made', False))).lower()}`",
    ]


def _global_intake_context_lines(context: dict[str, Any]) -> list[str]:
    if not context:
        return []
    language = context.get("language_context") or {}
    laboratories = context.get("laboratory_contexts") or []
    family_samples = context.get("family_sample_contexts") or []
    access = context.get("testing_access_context") or {}
    governance = context.get("governance_consent_context") or {}
    locale = context.get("locale_profile") or {}
    constraints = access.get("constraints") or []
    lines = [
        "### Global Intake and Care Context",
        "",
        "Optional user-supplied care and laboratory context. Values are descriptive, unverified, and do not alter clinical conclusions.",
        f"- schema_version: `{_redact(str(context.get('schema_version', 'unknown')))}`",
        f"- country_code: `{_redact(str(context.get('country_code') or 'not supplied'))}`",
        f"- care_setting: `{_redact(str(context.get('care_setting', 'unknown')))}`",
        f"- care_stage: `{_redact(str(context.get('care_stage', 'unknown')))}`",
        f"- referral_context_exact: `{_redact(str(context.get('referral_context_exact') or 'not supplied'))}`",
        f"- laboratory_context_count: `{len(laboratories)}`",
        f"- family_sample_context_count: `{len(family_samples)}`",
        f"- testing_access_constraints: `{_redact(', '.join(str(item) for item in constraints) if constraints else 'none supplied')}`",
        f"- governance_context_supplied: `{str(bool(governance)).lower()}`",
    ]
    if language:
        lines.extend(
            [
                f"- original_language: `{_redact(str(language.get('original_language_code') or 'not supplied'))}`",
                f"- original_text: `{_redact(str(language.get('original_text') or 'not supplied'))}`",
                f"- translated_language: `{_redact(str(language.get('translated_language_code') or 'not supplied'))}`",
                f"- translated_text: `{_redact(str(language.get('translated_text') or 'not supplied'))}`",
                f"- translation_status: `{_redact(str(language.get('translation_status', 'unknown')))}`",
                f"- translation_review_state: `{_redact(str(language.get('translation_review_state', 'unreviewed')))}`",
            ]
        )
        if language.get("translation_status") == "machine_translated":
            lines.append("- translation_caveat: Machine-translated wording requires human expert review; original and translated text remain separate.")
    if locale.get("profile_type") == "india":
        lines.extend(
            [
                "",
                "#### India Locale Context",
                "",
                "This locale profile was explicitly selected; it was not inferred from genetic, language, name, or location data.",
                f"- state_or_union_territory_code: `{_redact(str(locale.get('state_or_union_territory_code') or 'not supplied'))}`",
                f"- district_or_region_exact: `{_redact(str(locale.get('district_or_region_exact') or 'not supplied'))}`",
                f"- care_setting: `{_redact(str(locale.get('care_setting', 'unknown')))}`",
                f"- public_program_or_scheme_exact: `{_redact(str(locale.get('public_program_or_scheme_exact') or 'not supplied'))}`",
                f"- consanguinity_status: `{_redact(str(locale.get('consanguinity_status', 'not_assessed')))}`",
                f"- relationship_description_original: `{_redact(str(locale.get('relationship_description_original') or 'not supplied'))}`",
                f"- relationship_description_translated: `{_redact(str(locale.get('relationship_description_translated') or 'not supplied'))}`",
                f"- relationship_context_review_status: `{_redact(str(locale.get('relationship_context_review_status', 'not_reviewed')))}`",
                f"- relationship_description_corrected: `{_redact(str(locale.get('relationship_description_corrected') or 'not supplied'))}`",
                f"- relationship_context_review_provenance_source_ids: `{_redact(', '.join(str(item) for item in locale.get('relationship_context_review_provenance_source_ids', []) or []) or 'none')}`",
                "- relationship_context_caveat: Descriptive user-supplied context only; no paternity, identity, or inheritance conclusion was inferred.",
            ]
        )
    return lines


def _phenotype_hpo_curation_lines(curation: dict[str, Any]) -> list[str]:
    if not curation:
        return []
    suggestions = curation.get("hpo_suggestions", []) or []
    contradictions = curation.get("contradictions", []) or []
    actions = curation.get("review_actions", []) or []
    promoted = curation.get("promoted_observations", []) or []
    state_counts: dict[str, int] = {}
    review_counts: dict[str, int] = {}
    labels = []
    negated = 0
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        state = str(item.get("proposed_state", "unknown"))
        state_counts[state] = state_counts.get(state, 0) + 1
        review = str(item.get("review_status", "pending"))
        review_counts[review] = review_counts.get(review, 0) + 1
        labels.append(f"{item.get('hpo_id', 'unknown')}:{item.get('canonical_label', 'unknown')}")
        if isinstance(item.get("negation"), dict):
            negated += 1
    policy_codes = sorted(str(item.get("code")) for item in curation.get("policy_blocks", []) or [] if isinstance(item, dict))
    return [
        "## Phenotype and HPO Curation Preview",
        "",
        "Research-use-only candidate phenotype structuring. Suggestions are proposed, not approved, and require human review.",
        f"- research_use_only: `{str(bool(curation.get('research_use_only', True))).lower()}`",
        f"- pseudonymous_case_id: `{_redact(str(curation.get('pseudonymous_case_id', 'unknown')))}`",
        f"- snippet_count: `{len(curation.get('source_snippets', []) or [])}`",
        f"- registry_version: `{_redact(str(curation.get('registry_version', 'unknown')))}`",
        f"- algorithm_version: `{_redact(str(curation.get('algorithm_version', 'unknown')))}`",
        f"- suggestion_count: `{len(suggestions)}`",
        f"- HPO suggestions: `{_redact(', '.join(labels) if labels else 'none')}`",
        f"- proposed_state_counts: `{_redact(', '.join(f'{key}={state_counts[key]}' for key in sorted(state_counts)) or 'none')}`",
        f"- negated_count: `{negated}`",
        f"- contradiction_count: `{len(contradictions)}`",
        f"- reviewer_state_counts: `{_redact(', '.join(f'{key}={review_counts[key]}' for key in sorted(review_counts)) or 'none')}`",
        f"- reviewer_action_count: `{len(actions)}`",
        f"- promoted_observation_count: `{len(promoted)}`",
        f"- validation_warnings: `{len(curation.get('validation_warnings', []) or [])}`",
        f"- policy_block_codes: `{_redact(', '.join(policy_codes) if policy_codes else 'none')}`",
        "- human_review_required: `true`",
        "- diagnosis_made: `false`",
        "- treatment_recommendation_made: `false`",
        "- final_acmg_classification_made: `false`",
    ]


def _pre_test_assessment_lines(
    assessment: dict[str, Any],
    *,
    strategy_generated: bool = False,
) -> list[str]:
    if not assessment:
        return []
    referral = assessment.get("referral_packet") or {}
    history = assessment.get("clinical_history") or {}
    checkpoints = assessment.get("clinician_checkpoint_status_counts") or {}
    lines = [
        "## Referral and Pre-Test Clinical Assessment",
        "",
        (
            "Deterministic organization of supplied pre-test information only. The separate staged strategy workspace may contain proposed-not-approved options; this assessment does not recommend, approve, or order a test."
            if strategy_generated
            else "Deterministic organization of supplied pre-test information only. No test strategy was generated, no WES/WGS or other test was recommended, and no test was approved or ordered."
        ),
        "",
        "### Supplied Referral and History",
        f"- schema_version: `{_redact(str(assessment.get('schema_version', 'unknown')))}`",
        f"- referral_source: `{_redact(str(referral.get('source', 'not supplied')))}`",
        f"- referral_urgency_context: `{_redact(str(referral.get('urgency_context', 'not supplied')))}`",
        f"- supplied_referral_reason: `{_redact(str(referral.get('reason_exact', 'not supplied')))}`",
        f"- clinical_history_supplied: `{str(bool(history)).lower()}`",
        f"- supplied_history_summary: `{_redact(str(history.get('summary_exact', 'not supplied')))}`",
        f"- structured_history_item_count: `{len(history.get('items', []) or [])}`",
        f"- linked_phenotype_count: `{len(history.get('phenotype_observation_ids', []) or [])}`",
        f"- linked_pedigree_member_count: `{len(history.get('pedigree_member_ids', []) or [])}`",
        f"- previous_investigation_count: `{len(assessment.get('previous_investigation_timeline', []) or [])}`",
        f"- known_family_report_count: `{len(assessment.get('known_family_reports', []) or [])}`",
        "",
        "### Deterministic Assessment",
        f"- algorithm_version: `{_redact(str(assessment.get('algorithm_version', 'unknown')))}`",
        f"- testing_status_as_supplied: `{_redact(str(assessment.get('testing_status_as_supplied', 'unknown')))}`",
        f"- assessment_outcome: `{_redact(str(assessment.get('assessment_outcome', 'unknown')))}`",
        f"- outcome_rationale_codes: `{_redact(', '.join(str(item) for item in assessment.get('outcome_rationale_codes', []) or []) or 'none')}`",
        f"- open_missing_information_count: `{int(assessment.get('open_missing_information_count', 0) or 0)}`",
        f"- open_blocking_information_count: `{int(assessment.get('open_blocking_information_count', 0) or 0)}`",
        f"- open_human_review_count: `{int(assessment.get('open_human_review_count', 0) or 0)}`",
        f"- linkage_issue_count: `{len(assessment.get('linkage_issues', []) or [])}`",
        f"- ready_for_test_strategy_review: `{str(bool(assessment.get('ready_for_test_strategy_review', False))).lower()}`",
    ]
    for heading, key in (
        ("Blocking Information", "blocking_items"),
        ("Advisory Information", "advisory_items"),
        ("Human-Review Items", "human_review_items"),
        ("Informational Limitations", "informational_items"),
    ):
        items = assessment.get(key, []) or []
        codes = sorted(str(item.get("code", "missing_information")) for item in items if isinstance(item, dict))
        lines.extend(["", f"### {heading}", f"- item_codes: `{_redact(', '.join(codes) if codes else 'none')}`"])
    decisions = assessment.get("clinician_decisions", []) or []
    decision_values = sorted(
        f"{item.get('checkpoint_type', 'unknown')}={item.get('status', 'unknown')}"
        for item in decisions
        if isinstance(item, dict)
    )
    lines.extend([
        "",
        "### Clinician Decisions (Explicitly Supplied Only)",
        f"- supplied_checkpoint_decisions: `{_redact(', '.join(decision_values) if decision_values else 'none')}`",
        f"- clinician_checkpoint_status_counts: `{_redact(', '.join(f'{key}={checkpoints[key]}' for key in sorted(checkpoints)) or 'none')}`",
        "",
        "### Safety Boundary",
        "- readiness does not recommend or authorize any genetic test.",
        "- test_strategy_generated: `false`",
        "- test_recommendation_made: `false`",
        "- test_order_placed: `false`",
        "- automatic_wes_or_wgs_recommendation_made: `false`",
        "- diagnosis_made: `false`",
        "- treatment_recommendation_made: `false`",
        "- final_acmg_classification_made: `false`",
        "- human_review_required: `true`",
    ])
    return lines


def _test_strategy_workspace_lines(workspace: dict[str, Any]) -> list[str]:
    if not workspace:
        return []
    options = workspace.get("options", []) or []
    review_items = workspace.get("rule_review_items", []) or []
    linkage_issues = workspace.get("linkage_issues", []) or []
    lines = [
        "## Staged Test-Strategy Workspace",
        "",
        "Bounded test and investigation classes for clinician comparison. Every option is proposed, not approved; no final test was selected, approved, or ordered.",
        f"- schema_version: `{_redact(str(workspace.get('schema_version', 'unknown')))}`",
        f"- algorithm_version: `{_redact(str(workspace.get('algorithm_version', 'unknown')))}`",
        f"- catalogue_version: `{_redact(str(workspace.get('catalogue_version', 'unknown')))}`",
        f"- rule_spec_version: `{_redact(str(workspace.get('rule_spec_version', 'unknown')))}`",
        f"- workspace_status: `{_redact(str(workspace.get('workspace_status', 'unknown')))}`",
        f"- pre_test_assessment_outcome: `{_redact(str(workspace.get('pre_test_assessment_outcome', 'not supplied')))}`",
        f"- proposed_option_count: `{len(options)}`",
        f"- rule_review_item_count: `{len(review_items)}`",
        f"- linkage_issue_count: `{len(linkage_issues)}`",
        "",
        "### Proposed Options for Human Review",
    ]
    if not options:
        lines.append("- No catalogue option was surfaced.")
    for option in options:
        if not isinstance(option, dict):
            continue
        facts = option.get("trigger_facts", []) or []
        lines.extend(
            [
                f"- `{_redact(str(option.get('test_class', 'unknown')))}` — status `{_redact(str(option.get('status', 'proposed_not_approved')))}` — feasibility `{_redact(str(option.get('feasibility_status', 'unknown')))}`",
                f"  - why surfaced: {_redact('; '.join(str(item) for item in option.get('why_surfaced', []) or []) or 'not recorded')}",
                f"  - explicit trigger facts: {_redact('; '.join(str(item.get('fact_summary_exact', 'not recorded')) for item in facts if isinstance(item, dict)) or 'none')}",
                f"  - general detection scope: {_redact('; '.join(str(item) for item in option.get('general_detection_scope', []) or []) or 'not recorded')}",
                f"  - important blind spots: {_redact('; '.join(str(item) for item in option.get('important_blind_spots', []) or []) or 'not recorded')}",
                f"  - prerequisites: {_redact('; '.join(str(item) for item in option.get('prerequisites', []) or []) or 'none')}",
                f"  - reasons to defer: {_redact('; '.join(str(item) for item in option.get('reasons_to_defer', []) or []) or 'none')}",
                f"  - after a negative result: {_redact('; '.join(str(item) for item in option.get('after_negative_result', []) or []) or 'not recorded')}",
            ]
        )
    review_codes = sorted(
        str(item.get("code", "requires_rule_review")) for item in review_items if isinstance(item, dict)
    )
    lines.extend(
        [
            "",
            "### Rule and Linkage Review",
            f"- rule_review_codes: `{_redact(', '.join(review_codes) if review_codes else 'none')}`",
            f"- linkage_issue_count: `{len(linkage_issues)}`",
            "",
            "### Safety Boundary",
            "- every option status: `proposed_not_approved`",
            "- human_review_required: `true`",
            "- test_recommendation_made: `false`",
            "- test_approved: `false`",
            "- test_order_placed: `false`",
            "- final_test_selected: `false`",
            "- medically_necessary_claim_made: `false`",
            "- diagnosis_made: `false`",
            "- treatment_recommendation_made: `false`",
            "- final_acmg_classification_made: `false`",
        ]
    )
    return lines


def _result_evidence_workspace_lines(workspace: dict[str, Any]) -> list[str]:
    if not workspace:
        return []
    findings = workspace.get("normalized_findings", []) or []
    retrievals = workspace.get("retrieval_records", []) or []
    entries = workspace.get("ledger_entries", []) or []
    summaries = workspace.get("generated_summaries", []) or []
    conflicts = [item for item in entries if item.get("conflict_detected")]
    duplicates = [item for item in entries if item.get("duplicate_of")]
    lines = [
        "## Result and Evidence Workspace",
        "",
        "Externally reported content is preserved beside deterministic normalized representations. "
        "The evidence ledger records source statements and does not assign ACMG criteria, evidence strength, "
        "pathogenicity, causality, diagnosis, treatment, or clinical sign-out.",
        f"- result_intake_version: `{_redact(str(workspace.get('result_intake_version', 'unknown')))}`",
        f"- normalization_version: `{_redact(str(workspace.get('normalization_version', 'unknown')))}`",
        f"- retrieval_version: `{_redact(str(workspace.get('retrieval_version', 'unknown')))}`",
        f"- ledger_version: `{_redact(str(workspace.get('ledger_version', 'unknown')))}`",
        f"- source_result_count: `{len(workspace.get('source_results', []) or [])}`",
        f"- normalized_finding_count: `{len(findings)}`",
        f"- retrieval_record_count: `{len(retrievals)}`",
        f"- evidence_ledger_entry_count: `{len(entries)}`",
        f"- conflict_count: `{len(conflicts)}`",
        f"- duplicate_count: `{len(duplicates)}`",
        "",
        "### Reported and Normalized Findings",
    ]
    if not findings:
        lines.append("- None supplied.")
    for finding in findings:
        lines.extend(
            [
                f"- finding_id: `{_redact(str(finding.get('finding_id', 'unknown')))}`",
                f"  - category: `{_redact(str(finding.get('category', 'unknown')))}`",
                f"  - normalization_status: `{_redact(str(finding.get('normalization_status', 'unknown')))}`",
                f"  - normalization_rule_id: `{_redact(str(finding.get('normalization_rule_id', 'unknown')))}`",
                "  - Reported finding remains preserved in `reported_finding_snapshot`.",
                "  - Normalized representation is additive and human-reviewable.",
            ]
        )
    lines.extend(["", "### Controlled Retrieval"])
    if not retrievals:
        lines.append("- No retrieval was attempted.")
    for retrieval in retrievals:
        lines.append(
            f"- `{_redact(str(retrieval.get('query_id', 'unknown')))}` / "
            f"`{_redact(str(retrieval.get('source_name', 'unknown')))}`: "
            f"`{_redact(str(retrieval.get('state', 'unknown')))}`"
        )
        if retrieval.get("no_records_wording"):
            lines.append(f"  - {_redact(str(retrieval['no_records_wording']))}")
    lines.extend(["", "### Evidence Ledger"])
    if not entries:
        lines.append("- No source-backed ledger entries were created.")
    for entry in entries:
        lines.extend(
            [
                f"- ledger_entry_id: `{_redact(str(entry.get('ledger_entry_id', 'unknown')))}`",
                f"  - Source statement: {_redact(str(entry.get('source_statement', 'not supplied')))}",
                f"  - source_identifier: `{_redact(str(entry.get('source_identifier', 'unknown')))}`",
                f"  - source_version: `{_redact(str(entry.get('source_version', 'unknown')))}`",
            ]
        )
        if entry.get("conflict_detected"):
            lines.append(
                "  - Sources provide differing observations or interpretations. "
                "InSilicoPop has not resolved the conflict."
            )
    lines.extend(["", "### Proposed Evidence Summaries"])
    if not summaries:
        lines.append("- None requested.")
    for summary in summaries:
        lines.extend(
            [
                f"- summary_status: `{_redact(str(summary.get('summary_status', 'unknown')))}`",
                f"  - System-generated summary: {_redact(str(summary.get('system_summary', 'not supplied')))}",
                f"  - source ledger IDs: `{', '.join(_redact(str(item)) for item in summary.get('summary_based_on_source_ids', []))}`",
            ]
        )
    lines.extend(
        [
            "",
            "- External laboratory classification: classification reported by the external source; not assigned by InSilicoPop.",
            "- External interpretation recorded: not assigned by InSilicoPop.",
            "- human_review_required: `true`",
            "- diagnosis_made: `false`",
            "- treatment_recommendation_made: `false`",
            "- final_acmg_classification_made: `false`",
            "- acmg_criteria_generated: `false`",
            "- clinical_sign_out_made: `false`",
        ]
    )
    return lines


def _specialist_agent_workspace_lines(workspace: dict[str, Any]) -> list[str]:
    if not workspace:
        return []
    registry = workspace.get("approved_registry", []) or []
    decisions = workspace.get("spawn_decisions", []) or []
    outputs = workspace.get("agent_outputs", []) or []
    candidates = workspace.get("candidate_criteria", []) or []
    disagreements = workspace.get("disagreement_groups", []) or []
    action_results = workspace.get("review_action_results", []) or []
    applied_action_results = [
        item for item in action_results if item.get("result_status") == "applied"
    ]
    rejected_action_results = [
        item for item in action_results if item.get("result_status") == "rejected"
    ]
    lines = [
        "## Specialist Agents and Candidate ACMG Workspace",
        "",
        "Bounded specialist tasks inspect only selected structured inputs and reviewed evidence-ledger records. "
        "All agent conclusions remain proposed, not approved. Candidate ACMG evidence is an organizational "
        "category requiring human review; it is not a criterion determination or a variant classification.",
        f"- registry_version: `{_redact(str(workspace.get('registry_version', 'unknown')))}`",
        f"- safety_policy_version: `{_redact(str(workspace.get('safety_policy_version', 'unknown')))}`",
        f"- approved_specialist_count: `{len(registry)}`",
        f"- spawn_request_count: `{len(workspace.get('spawn_requests', []) or [])}`",
        f"- task_envelope_count: `{len(workspace.get('task_envelopes', []) or [])}`",
        f"- proposed_agent_output_count: `{len(outputs)}`",
        f"- review_ready_output_count: `{len(workspace.get('review_ready_output_ids', []) or [])}`",
        f"- candidate_acmg_evidence_count: `{len(candidates)}`",
        f"- disagreement_group_count: `{len(disagreements)}`",
        f"- applied_review_action_count: `{len(applied_action_results)}`",
        f"- rejected_review_action_count: `{len(rejected_action_results)}`",
        "",
        "### Approved Registry",
    ]
    for item in registry:
        lines.append(
            f"- `{_redact(str(item.get('agent_id', 'unknown')))}` — "
            f"{_redact(str(item.get('display_name', 'Specialist agent')))}; "
            f"may_spawn_agents=`false`"
        )
    if not registry:
        lines.append("- No approved registry loaded.")
    lines.extend(["", "### Bounded Task Decisions"])
    for item in decisions:
        lines.append(
            f"- `{_redact(str(item.get('spawn_request_id', 'unknown')))}`: "
            f"`{_redact(str(item.get('status', 'not_started')))}` — "
            f"{_redact(str(item.get('message', 'Human decision required.')))}"
        )
    if not decisions:
        lines.append("- No bounded task requested.")
    lines.extend(["", "### Proposed Agent Outputs"])
    for item in outputs:
        lines.extend(
            [
                f"- `{_redact(str(item.get('agent_output_id', 'unknown')))}` / "
                f"`{_redact(str(item.get('agent_id', 'unknown')))}`: "
                f"`{_redact(str(item.get('status', 'not_started')))}` / proposed_not_approved",
                f"  - {_redact(str(item.get('summary', 'No summary supplied.')))}",
                f"  - source ledger IDs: `{', '.join(_redact(str(value)) for value in item.get('source_ledger_entry_ids', [])) or 'none'}`",
                f"  - safety review: `{_redact(str((item.get('safety_review') or {}).get('review_status', 'unknown')))}`",
            ]
        )
    if not outputs:
        lines.append("- No specialist output generated.")
    lines.extend(["", "### Candidate ACMG Evidence"])
    for item in candidates:
        lines.extend(
            [
                f"- `{_redact(str(item.get('candidate_criterion_id', 'unknown')))}` — "
                f"`{_redact(str(item.get('criterion_code', 'unknown')))}` — "
                f"`{_redact(str(item.get('candidate_status', 'requires_rule_review')))}`",
                f"  - source ledger IDs: `{', '.join(_redact(str(value)) for value in item.get('source_ledger_entry_ids', [])) or 'none'}`",
                "  - Human decision required. Accepted for discussion does not mean criterion satisfied.",
            ]
        )
    if not candidates:
        lines.append("- No candidate ACMG evidence item generated.")
    lines.extend(["", "### Human-Review Action Results"])
    for item in applied_action_results:
        lines.append(
            f"- applied: `{_redact(str(item.get('action_id', 'unknown')))}` / "
            f"`{_redact(str(item.get('target_type', 'target')))}` "
            f"`{_redact(str(item.get('target_id', 'unknown')))}`"
        )
    for item in rejected_action_results:
        lines.append(
            f"- rejected: `{_redact(str(item.get('action_id', 'unknown')))}` / "
            f"`{_redact(str(item.get('rejection_reason', 'invalid_review_action')))}` — "
            f"{_redact(str(item.get('message', 'Authoritative state preserved.')))}"
        )
    if not action_results:
        lines.append("- No specialist human-review action result recorded.")
    lines.extend(
        [
            "",
            "### External ACMG Assessment",
            "External ACMG assessment recorded; not assigned by InSilicoPop."
            if workspace.get("external_acmg_assessments")
            else "No external ACMG assessment recorded.",
            "",
            "- recursive_spawning_used: `false`",
            "- dynamic_roles_created: `false`",
            "- majority_vote_used: `false`",
            "- automatic_criterion_combination_used: `false`",
            "- pathogenicity_score_calculated: `false`",
            "- diagnosis_made: `false`",
            "- treatment_recommendation_made: `false`",
            "- test_order_placed: `false`",
            "- clinical_sign_out_made: `false`",
            "- human_review_required: `true`",
        ]
    )
    return lines


def _pedigree_inheritance_audit_lines(audit: dict[str, Any]) -> list[str]:
    if not audit:
        return []
    audits = audit.get("inheritance_audits", []) or []
    statuses: dict[str, int] = {}
    bounded_results = []
    for item in audits:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "cannot_evaluate"))
        statuses[status] = statuses.get(status, 0) + 1
        bounded_results.append(f"{item.get('hypothesis_type', 'unknown')}:{status}")
    affected = audit.get("affected_status_summary", {}) or {}
    testing = audit.get("testing_availability_summary", {}) or {}
    transmission = audit.get("available_parent_child_transmission_summary", {}) or {}
    policy_codes = sorted(str(item.get("code")) for item in audit.get("policy_blocks", []) or [] if isinstance(item, dict))
    return [
        "## Pedigree and Inheritance Audit Preview",
        "",
        "Research-use-only deterministic consistency audit of supplied structured records. These statuses do not establish diagnosis, pathogenicity, inheritance, or a final clinical conclusion.",
        f"- schema_version: `{_redact(str(audit.get('schema_version', 'unknown')))}`",
        f"- algorithm_version: `{_redact(str(audit.get('algorithm_version', 'unknown')))}`",
        f"- research_use_only: `{str(bool(audit.get('research_use_only', True))).lower()}`",
        f"- pseudonymous_case_id: `{_redact(str(audit.get('pseudonymous_case_id', 'unknown')))}`",
        f"- family_member_count: `{int(audit.get('member_count', 0) or 0)}`",
        f"- biological_parent_relationship_count: `{int(audit.get('biological_parent_relationship_count', 0) or 0)}`",
        f"- supplied_hypothesis_count: `{len(audits)}`",
        f"- audit_status_counts: `{_redact(', '.join(f'{key}={statuses[key]}' for key in sorted(statuses)) or 'none')}`",
        f"- bounded_hypothesis_statuses: `{_redact(', '.join(bounded_results) if bounded_results else 'none')}`",
        f"- affected_status_summary: `{_redact(', '.join(f'{key}={affected[key]}' for key in sorted(affected)) or 'none')}`",
        f"- testing_availability_summary: `{_redact(', '.join(f'{key}={testing[key]}' for key in sorted(testing)) or 'none')}`",
        f"- evaluable_parent_child_transmission_count: `{int(transmission.get('evaluable_transmission_count', 0) or 0)}`",
        f"- non_evaluable_parent_child_transmission_count: `{int(transmission.get('non_evaluable_transmission_count', 0) or 0)}`",
        f"- missing_information_count: `{len(audit.get('missing_information', []) or [])}`",
        f"- phase_requirement_count: `{len(audit.get('phase_requirements', []) or [])}`",
        f"- supplied_record_inconsistency_count: `{len(audit.get('mendelian_inconsistencies', []) or [])}`",
        f"- relationship_issue_count: `{len(audit.get('relationship_issues', []) or [])}`",
        f"- reviewer_status: `{_redact(str(audit.get('reviewer_status', 'unknown')))}`",
        f"- policy_block_codes: `{_redact(', '.join(policy_codes) if policy_codes else 'none')}`",
        "- inheritance_consistency_audit_performed: `true`",
        "- inheritance_clinically_established: `false`",
        "- human_review_required: `true`",
        "- external_llm_called: `false`",
        "- external_tools_executed: `false`",
        "- raw_genomic_files_parsed: `false`",
    ]
def _results_audit_section_lines(results_audit: dict[str, Any]) -> list[str]:
    if not results_audit:
        return []
    lines = [
        "## Results-Only Audit Preview",
        "",
        f"- selected_recipe_id: `{_redact(str(results_audit.get('selected_recipe_id', 'unknown')))}`",
        f"- workflow_family: `{_redact(str(results_audit.get('workflow_family', 'unknown')))}`",
        f"- dry_run_only: `{str(bool(results_audit.get('dry_run_only', True))).lower()}`",
        f"- human_review_required: `{str(bool(results_audit.get('human_review_required', True))).lower()}`",
        f"- external_tools_executed: `{str(bool(results_audit.get('external_tools_executed', False))).lower()}`",
        f"- raw_genomic_files_parsed: `{str(bool(results_audit.get('raw_genomic_files_parsed', False))).lower()}`",
        f"- deep_result_files_parsed: `{str(bool(results_audit.get('deep_result_files_parsed', False))).lower()}`",
        "- declared result files were inventoried by name only; result contents were not parsed.",
        "- no biological, clinical, ancestry, caste/community/religion, purity, superiority, or identity conclusions were made.",
        "",
        "Declared result artifacts:",
    ]
    artifacts = results_audit.get("declared_result_artifacts", []) or []
    if artifacts:
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            lines.append(
                f"- `{_redact(str(artifact.get('artifact_id', 'artifact')))}` "
                f"{_redact(str(artifact.get('artifact_type', 'unknown_result_artifact')))}: "
                f"{_redact(str(artifact.get('declared_path_or_name', 'not recorded')))}; "
                f"parsed={str(bool(artifact.get('parsed', False))).lower()}, "
                f"raw_file_read={str(bool(artifact.get('raw_file_read', False))).lower()}"
            )
    else:
        lines.append("- No declared result artifacts were recorded.")
    lines.extend(["", "Missing result context:"])
    lines.extend(_list_lines(results_audit.get("missing_result_context", []), none_text="No missing result context recorded."))
    lines.extend(["", "Unsafe claim checks:"])
    lines.extend(_list_lines(results_audit.get("unsafe_claim_checks", []), none_text="No unsafe claim checks recorded."))
    lines.extend(["", "Human review flags:"])
    lines.extend(_list_lines(results_audit.get("human_review_flags", []), none_text="No human review flags recorded."))
    lines.append("")
    return lines


def _variant_intelligence_lines(variant_intelligence: dict[str, Any]) -> list[str]:
    if not variant_intelligence:
        return []
    results = variant_intelligence.get("normalization_results", []) or []
    lines = [
        "## Variant Intelligence Preview",
        "",
        "The active reference registry is synthetic and fixture-only; it exists to demonstrate deterministic architecture and testing. Genome-wide human reference normalization is not available in v0.30. Generated normalized representations apply only when the supplied allele resolves against the pinned fixture window.",
        "These outputs do not establish clinical significance, pathogenicity, causality, diagnosis, treatment relevance, or final transcript relevance.",
        f"- schema_version: `{_redact(str(variant_intelligence.get('schema_version', 'unknown')))}`",
        f"- algorithm_version: `{_redact(str(variant_intelligence.get('algorithm_version', 'unknown')))}`",
        f"- request_count: `{len(results)}`",
        f"- variant_validation_performed: `{str(bool(variant_intelligence.get('variant_validation_performed', False))).lower()}`",
        f"- variant_normalization_performed: `{str(bool(variant_intelligence.get('variant_normalization_performed', False))).lower()}`",
        "- variant_pathogenicity_interpretation_performed: `false`",
        "- transcript_selection_performed: `false`",
        "- raw_genomic_files_parsed: `false`",
        "- human_review_required: `true`",
        "",
        "Bounded request summaries (exact biological strings are retained in the allowlisted reproducibility artifact, not repeated here):",
    ]
    if not results:
        lines.append("- No variant normalization requests were supplied.")
    for item in results:
        if not isinstance(item, dict):
            continue
        output_types = sorted(
            str(output.get("output_type", "unknown"))
            for output in item.get("normalized_outputs", []) or []
            if isinstance(output, dict)
        )
        lines.append(
            f"- request `{_redact(str(item.get('request_id', 'unknown')))}` / candidate `{_redact(str(item.get('candidate_variant_id', 'unknown')))}`: "
            f"validation `{_redact(str(item.get('validation_status', 'cannot_validate')))}`, "
            f"normalization `{_redact(str(item.get('normalization_status', 'cannot_normalize')))}`, "
            f"equivalence `{_redact(str(item.get('equivalence_status', 'unresolved_equivalence')))}`, "
            f"outputs `{_redact(', '.join(output_types) or 'none')}`"
        )
        reference_context = item.get("reference_context_used", {}) or {}
        if not isinstance(reference_context, dict):
            reference_context = {}
        reference_verified = reference_context.get("reference_context_verified") is True
        reference_heading = (
            "pinned reference context (authoritative resolved fixture window)"
            if reference_verified
            else "supplied/unresolved reference context (no authoritative pinned reference window was resolved)"
        )
        sequence_digest = str(reference_context.get("sequence_sha256") or "unresolved")
        digest_prefix = sequence_digest[:16] + ("..." if len(sequence_digest) > 16 else "")
        lines.append(
            f"  - {reference_heading}: "
            f"source `{_redact(str(reference_context.get('reference_source_id') or 'unresolved'))}`, "
            f"accession `{_redact(str(reference_context.get('reference_accession') or 'unresolved'))}`, "
            f"build `{_redact(str(reference_context.get('genome_build') or 'unresolved'))}`, "
            f"contig `{_redact(str(reference_context.get('chromosome') or 'unresolved'))}`, "
            f"bounds `{_redact(str(reference_context.get('window_start_zero_based')))}:{_redact(str(reference_context.get('window_end_zero_based')))}`, "
            f"coordinate convention `{_redact(str(reference_context.get('reference_window_coordinate_system') or 'unresolved'))}`, "
            f"registry `{_redact(str(reference_context.get('registry_version') or 'unresolved'))}`, "
            f"provenance `{_redact(str(reference_context.get('provenance_source_id') or 'unresolved'))}`, "
            f"fixture_only `{str(bool(reference_context.get('fixture_only', False))).lower()}`, "
            f"sequence_sha256_prefix `{_redact(digest_prefix)}`"
        )
    return lines


def _validity_notes(workflow_family: str) -> list[str]:
    common = {
        "vcf_population_structure": [
            "- Missingness QC is required before interpretation.",
            "- LD pruning is required before PCA interpretation.",
            "- ADMIXTURE should use a K range and CV/seed stability review.",
            "- FST requires valid population labels and adequate sample sizes.",
            "- ROH requires founder-effect/endogamy caveats.",
        ],
        "hard_called_snp": [
            "- PLINK QC is required.",
            "- Heterozygosity, HWE, and relatedness checks should be reviewed where appropriate.",
            "- LD pruning is required before PCA/ADMIXTURE interpretation.",
        ],
        "results_only_audit": [
            "- Conclusions depend on provenance and available outputs.",
            "- Missing raw/QC files reduce reliability.",
            "- Claims should be tied to parsed evidence.",
        ],
        "genotype_likelihood_low_depth": [
            "- Do not default to a hard-called PLINK workflow.",
            "- Use genotype-likelihood-aware planning such as ANGSD/PCAngsd/NGSadmix/realSFS/PopGLen-style workflows.",
            "- Hard-called SNP interpretation may be inappropriate for low-depth data.",
        ],
        "insufficient_inputs": [
            "- No strong scientific claims can be made.",
            "- Request concrete input files before interpretation.",
        ],
    }
    return common.get(workflow_family, ["- Use workflow-specific QC and provenance checks before interpretation."])


def _memory_lines(carried_memory: dict[str, Any]) -> list[str]:
    if not carried_memory:
        return ["No carried scientific memory was available for this run."]
    lines: list[str] = []
    critical = carried_memory.get("critical_facts", []) or []
    blocked = carried_memory.get("blocked_interpretations", []) or []
    next_steps = carried_memory.get("enables_next_steps", []) or []
    provenance_refs = carried_memory.get("provenance_refs", []) or []
    dependencies = carried_memory.get("downstream_dependencies", []) or []

    lines.append("Critical facts:")
    lines.extend(_list_lines([_fact_text(item) for item in critical], none_text="No critical facts recorded."))
    lines.append("")
    lines.append("Blocked interpretations:")
    lines.extend(_list_lines(blocked, none_text="No blocked interpretations recorded."))
    lines.append("")
    lines.append("Next-step dependencies:")
    lines.extend(_list_lines(next_steps or dependencies, none_text="No next-step dependencies recorded."))
    lines.append("")
    lines.append("Provenance refs:")
    lines.extend(_list_lines(provenance_refs, none_text="No provenance refs recorded."))
    return lines


def _fact_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or item.get("fact_id") or item)
    return str(item)


def _list_lines(items: Any, *, none_text: str) -> list[str]:
    if not items:
        return [f"- {none_text}"]
    return [f"- {_redact(str(item))}" for item in items]


def _join_values(items: Any) -> str:
    if not items:
        return "none recorded"
    if isinstance(items, list):
        return ", ".join(_redact(str(item)) for item in items)
    return _redact(str(items))


def _object_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return dict(getattr(item, "__dict__", {}))


def _redact(text: str) -> str:
    redacted = text
    patterns = [
        r"(?i)(api[_-]?key|authorization|bearer|token|secret|password)\s*[:=]\s*['\"]?[^,'\"\s)]+",
        r"sk-[A-Za-z0-9_-]{12,}",
    ]
    for pattern in patterns:
        redacted = re.sub(pattern, "[REDACTED]", redacted)
    return redacted
