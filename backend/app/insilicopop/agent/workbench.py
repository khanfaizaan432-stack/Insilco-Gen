from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import BaseModel, Field


ALLOWED_ARTIFACTS = {
    "agent_state.json",
    "agent_trace.json",
    "action_proposals.json",
    "llm_action_proposals.json",
    "validated_actions.json",
    "command_previews.yaml",
    "blocked_actions.md",
    "failure_scope.md",
    "carried_memory.json",
    "workflow_selection.json",
    "final_report.md",
}

ALLOWED_REPRODUCIBILITY_ARTIFACTS = {
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
    "reproducibility/results_audit.json",
    "reproducibility/guardrail_decisions.json",
    "reproducibility/provenance_index.json",
    "reproducibility/runtime_lock.json",
    "reproducibility/checksums.sha256",
}

SECRET_KEY_MARKERS = ("api_key", "authorization", "auth_header", "bearer", "password", "secret", "token")
REDACTED = "[REDACTED]"


class AgentRunSummary(BaseModel):
    run_id: str
    created_at: str | None = None
    workflow_family: str | None = None
    llm_provider: str = "mock"
    external_llm_called: bool = False
    external_tools_executed: bool = False
    current_step: str | None = None
    research_lane: str | None = None
    evidence_retrieval_mode: str | None = None
    evidence_snippet_count: int = 0
    evidence_local_only: bool = True
    orchestration_backend: str | None = None
    orchestration_fallback_used: bool = True
    orchestration_node_count: int = 0
    orchestration_blocked_nodes: list[str] = Field(default_factory=list)
    orchestration_safety_flags: dict[str, bool] = Field(default_factory=dict)
    clinical_intake_completeness: str | None = None
    clinical_policy_block_count: int = 0
    hpo_suggestion_count: int = 0
    hpo_contradiction_count: int = 0
    hpo_promoted_observation_count: int = 0
    hpo_curation_artifact_available: bool = False
    inheritance_audit_count: int = 0
    inheritance_audit_status_counts: dict[str, int] = Field(default_factory=dict)
    relationship_issue_count: int = 0
    mendelian_inconsistency_count: int = 0
    evaluable_parent_child_transmission_count: int = 0
    pedigree_inheritance_audit_artifact_available: bool = False
    variant_intelligence_request_count: int = 0
    variant_validation_status_counts: dict[str, int] = Field(default_factory=dict)
    variant_normalization_status_counts: dict[str, int] = Field(default_factory=dict)
    variant_equivalence_status_counts: dict[str, int] = Field(default_factory=dict)
    variant_intelligence_artifact_available: bool = False
    human_review_required: bool = True
    selected_recipe_id: str | None = None
    selected_recipe_maturity_tier: str | None = None
    selected_recipe_status: str | None = None
    artifact_count: int = 0
    has_final_report: bool = False
    has_reproducibility_bundle: bool = False


class AgentRunDetail(AgentRunSummary):
    query: str | None = None
    uploaded_files: dict[str, str] = Field(default_factory=dict)
    selected_recipe: dict[str, Any] | None = None
    claim_audit: dict[str, Any] | None = None
    results_audit: dict[str, Any] | None = None
    data_governance_audit: dict[str, Any] | None = None
    metadata_registry_audit: dict[str, Any] | None = None
    evidence_retrieval: dict[str, Any] | None = None
    orchestration_trace: dict[str, Any] | None = None
    clinical_case_intake: dict[str, Any] | None = None
    phenotype_hpo_curation: dict[str, Any] | None = None
    pedigree_inheritance_audit: dict[str, Any] | None = None
    variant_intelligence: dict[str, Any] | None = None
    artifact_names: list[str] = Field(default_factory=list)


class AgentArtifactSummary(BaseModel):
    artifact_name: str
    file_type: str
    size_bytes: int
    created: bool = True


class AgentArtifactContent(BaseModel):
    artifact_name: str
    file_type: str
    content: Any
    size_bytes: int


class ReproducibilityBundleSummary(BaseModel):
    run_id: str
    generated: bool
    files: list[str] = Field(default_factory=list)
    file_count: int = 0
    runtime_lock: dict[str, Any] | None = None


class WorkbenchRunStore:
    def __init__(self, generated_root: Path | None = None) -> None:
        self.generated_root = generated_root or Path(__file__).resolve().parents[2] / "generated" / "agents"

    def list_runs(self) -> list[AgentRunSummary]:
        if not self.generated_root.exists():
            return []
        run_dirs = [path for path in self.generated_root.iterdir() if path.is_dir()]
        run_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return [self._summary(run_dir) for run_dir in run_dirs if (run_dir / "agent_state.json").is_file()]

    def run_detail(self, run_id: str) -> AgentRunDetail:
        run_dir = self._run_dir(run_id)
        summary = self._summary(run_dir)
        state = self._read_json_if_available(run_dir / "agent_state.json")
        return AgentRunDetail(
            **summary.model_dump(),
            query=state.get("query"),
            uploaded_files=_string_dict(state.get("uploaded_files", {})),
            selected_recipe=state.get("selected_recipe") if isinstance(state.get("selected_recipe"), dict) else None,
            claim_audit=state.get("claim_audit") if isinstance(state.get("claim_audit"), dict) else None,
            results_audit=state.get("results_audit") if isinstance(state.get("results_audit"), dict) else None,
            data_governance_audit=state.get("data_governance_audit") if isinstance(state.get("data_governance_audit"), dict) else None,
            metadata_registry_audit=state.get("metadata_registry_audit") if isinstance(state.get("metadata_registry_audit"), dict) else None,
            evidence_retrieval=state.get("evidence_retrieval") if isinstance(state.get("evidence_retrieval"), dict) else None,
            orchestration_trace=state.get("orchestration_trace") if isinstance(state.get("orchestration_trace"), dict) else None,
            clinical_case_intake=state.get("clinical_case_intake") if isinstance(state.get("clinical_case_intake"), dict) else None,
            phenotype_hpo_curation=state.get("phenotype_hpo_curation") if isinstance(state.get("phenotype_hpo_curation"), dict) else None,
            pedigree_inheritance_audit=state.get("pedigree_inheritance_audit") if isinstance(state.get("pedigree_inheritance_audit"), dict) else None,
            variant_intelligence=state.get("variant_intelligence") if isinstance(state.get("variant_intelligence"), dict) else None,
            artifact_names=[artifact.artifact_name for artifact in self.list_artifacts(run_id)],
        )

    def list_artifacts(self, run_id: str) -> list[AgentArtifactSummary]:
        run_dir = self._run_dir(run_id)
        artifacts = []
        for relative_path in sorted(ALLOWED_ARTIFACTS | ALLOWED_REPRODUCIBILITY_ARTIFACTS):
            path = run_dir / relative_path
            if path.is_file():
                artifacts.append(
                    AgentArtifactSummary(
                        artifact_name=relative_path,
                        file_type=_file_type(path),
                        size_bytes=path.stat().st_size,
                    )
                )
        return artifacts

    def read_artifact(self, run_id: str, artifact_name: str) -> AgentArtifactContent:
        run_dir = self._run_dir(run_id)
        relative_path = self._allowed_relative_artifact(artifact_name)
        path = (run_dir / relative_path).resolve()
        if not _is_relative_to(path, run_dir.resolve()) or not path.is_file():
            raise FileNotFoundError(relative_path)
        content = _read_safe_content(path)
        return AgentArtifactContent(
            artifact_name=relative_path,
            file_type=_file_type(path),
            content=_redact(content),
            size_bytes=path.stat().st_size,
        )

    def final_report(self, run_id: str) -> AgentArtifactContent:
        return self.read_artifact(run_id, "final_report.md")

    def workflow_selection(self, run_id: str) -> dict[str, Any]:
        content = self.read_artifact(run_id, "workflow_selection.json").content
        return content if isinstance(content, dict) else {}

    def reproducibility(self, run_id: str) -> ReproducibilityBundleSummary:
        run_dir = self._run_dir(run_id)
        files = [name for name in sorted(ALLOWED_REPRODUCIBILITY_ARTIFACTS) if (run_dir / name).is_file()]
        runtime_lock = None
        runtime_lock_path = run_dir / "reproducibility" / "runtime_lock.json"
        if runtime_lock_path.is_file():
            runtime_lock = _redact(self._read_json_if_available(runtime_lock_path))
        return ReproducibilityBundleSummary(
            run_id=run_id,
            generated=bool(files),
            files=files,
            file_count=len(files),
            runtime_lock=runtime_lock,
        )

    def _summary(self, run_dir: Path) -> AgentRunSummary:
        state = self._read_json_if_available(run_dir / "agent_state.json")
        workflow_selection = state.get("workflow_selection", {}) if isinstance(state, dict) else {}
        selected_recipe = state.get("selected_recipe", {}) if isinstance(state, dict) else {}
        selected_recipe = selected_recipe if isinstance(selected_recipe, dict) else {}
        evidence_retrieval = state.get("evidence_retrieval", {}) if isinstance(state, dict) else {}
        evidence_retrieval = evidence_retrieval if isinstance(evidence_retrieval, dict) else {}
        orchestration_trace = state.get("orchestration_trace", {}) if isinstance(state, dict) else {}
        orchestration_trace = orchestration_trace if isinstance(orchestration_trace, dict) else {}
        clinical_case_intake = state.get("clinical_case_intake", {}) if isinstance(state, dict) else {}
        clinical_case_intake = clinical_case_intake if isinstance(clinical_case_intake, dict) else {}
        phenotype_hpo_curation = state.get("phenotype_hpo_curation", {}) if isinstance(state, dict) else {}
        phenotype_hpo_curation = phenotype_hpo_curation if isinstance(phenotype_hpo_curation, dict) else {}
        pedigree_inheritance_audit = state.get("pedigree_inheritance_audit", {}) if isinstance(state, dict) else {}
        pedigree_inheritance_audit = pedigree_inheritance_audit if isinstance(pedigree_inheritance_audit, dict) else {}
        variant_intelligence = state.get("variant_intelligence", {}) if isinstance(state, dict) else {}
        variant_intelligence = variant_intelligence if isinstance(variant_intelligence, dict) else {}
        inheritance_audits = pedigree_inheritance_audit.get("inheritance_audits", []) or []
        inheritance_status_counts: dict[str, int] = {}
        for item in inheritance_audits:
            if isinstance(item, dict):
                status = str(item.get("status", "cannot_evaluate"))
                inheritance_status_counts[status] = inheritance_status_counts.get(status, 0) + 1
        transmission_summary = pedigree_inheritance_audit.get("available_parent_child_transmission_summary", {}) or {}
        artifacts = [name for name in ALLOWED_ARTIFACTS | ALLOWED_REPRODUCIBILITY_ARTIFACTS if (run_dir / name).is_file()]
        return AgentRunSummary(
            run_id=run_dir.name,
            created_at=_created_at(run_dir),
            workflow_family=workflow_selection.get("workflow_family") if isinstance(workflow_selection, dict) else None,
            llm_provider=str(state.get("llm_provider", "mock")),
            external_llm_called=bool(state.get("external_llm_called", False)),
            external_tools_executed=bool(state.get("external_tools_executed", False)),
            current_step=state.get("current_step"),
            research_lane=state.get("research_lane"),
            evidence_retrieval_mode=evidence_retrieval.get("retrieval_mode"),
            evidence_snippet_count=int(evidence_retrieval.get("snippets_returned", 0) or 0),
            evidence_local_only=bool(evidence_retrieval.get("local_only", True)),
            orchestration_backend=orchestration_trace.get("orchestration_backend"),
            orchestration_fallback_used=bool(orchestration_trace.get("fallback_used", True)),
            orchestration_node_count=len(orchestration_trace.get("graph_nodes_executed", []) or []),
            orchestration_blocked_nodes=[str(item) for item in orchestration_trace.get("blocked_nodes", []) or []],
            orchestration_safety_flags=orchestration_trace.get("safety_flags", {}) if isinstance(orchestration_trace.get("safety_flags"), dict) else {},
            clinical_intake_completeness=clinical_case_intake.get("intake_completeness"),
            clinical_policy_block_count=len(clinical_case_intake.get("policy_blocks", []) or []),
            hpo_suggestion_count=len(phenotype_hpo_curation.get("hpo_suggestions", []) or []),
            hpo_contradiction_count=len(phenotype_hpo_curation.get("contradictions", []) or []),
            hpo_promoted_observation_count=len(phenotype_hpo_curation.get("promoted_observations", []) or []),
            hpo_curation_artifact_available=(run_dir / "reproducibility" / "phenotype_hpo_curation.json").is_file(),
            inheritance_audit_count=len(inheritance_audits),
            inheritance_audit_status_counts={key: inheritance_status_counts[key] for key in sorted(inheritance_status_counts)},
            relationship_issue_count=len(pedigree_inheritance_audit.get("relationship_issues", []) or []),
            mendelian_inconsistency_count=len(pedigree_inheritance_audit.get("mendelian_inconsistencies", []) or []),
            evaluable_parent_child_transmission_count=int(transmission_summary.get("evaluable_transmission_count", 0) or 0) if isinstance(transmission_summary, dict) else 0,
            pedigree_inheritance_audit_artifact_available=(run_dir / "reproducibility" / "pedigree_inheritance_audit.json").is_file(),
            variant_intelligence_request_count=len(variant_intelligence.get("normalization_results", []) or []),
            variant_validation_status_counts=_safe_count_dict(variant_intelligence.get("validation_status_counts", {})),
            variant_normalization_status_counts=_safe_count_dict(variant_intelligence.get("normalization_status_counts", {})),
            variant_equivalence_status_counts=_safe_count_dict(variant_intelligence.get("equivalence_status_counts", {})),
            variant_intelligence_artifact_available=(run_dir / "reproducibility" / "variant_intelligence.json").is_file(),
            human_review_required=True,
            selected_recipe_id=selected_recipe.get("recipe_id"),
            selected_recipe_maturity_tier=selected_recipe.get("maturity_tier"),
            selected_recipe_status=selected_recipe.get("status"),
            artifact_count=len(artifacts),
            has_final_report=(run_dir / "final_report.md").is_file(),
            has_reproducibility_bundle=(run_dir / "reproducibility").is_dir(),
        )

    def _run_dir(self, run_id: str) -> Path:
        if not run_id or any(part in {".", ".."} for part in PurePosixPath(run_id.replace("\\", "/")).parts):
            raise FileNotFoundError(run_id)
        run_dir = (self.generated_root / run_id).resolve()
        root = self.generated_root.resolve()
        if not _is_relative_to(run_dir, root) or not run_dir.is_dir():
            raise FileNotFoundError(run_id)
        return run_dir

    def _allowed_relative_artifact(self, artifact_name: str) -> str:
        normalized = artifact_name.replace("\\", "/").lstrip("/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise PermissionError(artifact_name)
        relative_path = path.as_posix()
        if relative_path not in ALLOWED_ARTIFACTS and relative_path not in ALLOWED_REPRODUCIBILITY_ARTIFACTS:
            raise PermissionError(artifact_name)
        return relative_path

    def _read_json_if_available(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return payload if isinstance(payload, dict) else {}


def _read_safe_content(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(text) or []
    return _redact_text(text)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if _is_secret_key(str(key)):
                redacted[key] = REDACTED
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(text: str) -> str:
    redacted_lines = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in SECRET_KEY_MARKERS):
            redacted_lines.append(REDACTED)
        else:
            redacted_lines.append(line)
    return "\n".join(redacted_lines) + ("\n" if text.endswith("\n") else "")


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SECRET_KEY_MARKERS)


def _file_type(path: Path) -> str:
    if path.name == "checksums.sha256":
        return "sha256"
    return path.suffix.lstrip(".") or "text"


def _created_at(path: Path) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _safe_count_dict(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        try:
            result[str(key)] = int(item)
        except (TypeError, ValueError):
            continue
    return {key: result[key] for key in sorted(result)}
