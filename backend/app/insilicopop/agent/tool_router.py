from __future__ import annotations

from app.insilicopop.agent.actions import AgentAction
from app.insilicopop.tools.admixture_commands import build_admixture_k_sweep_commands
from app.insilicopop.tools.eigensoft_commands import build_smartpca_command_preview
from app.insilicopop.tools.plink_commands import (
    build_hwe_command,
    build_ld_prune_command,
    build_missingness_command,
    build_relatedness_command,
    build_roh_command,
)
from app.insilicopop.tools.selection_commands import build_ihs_plan, build_xpehh_plan
from app.insilicopop.tools.vcftools_commands import build_fst_command, build_windowed_fst_command


class ToolRouter:
    def dry_run(self, action: AgentAction) -> AgentAction:
        preview = self.preview_for(action.action_type)
        if preview is not None:
            action.command_preview = _normalize_preview(preview, action)
            if isinstance(action.command_preview, list):
                action.expected_outputs = sorted({output for item in action.command_preview for output in item.get("expected_outputs", [])})
            else:
                action.expected_outputs = list(action.command_preview.get("expected_outputs", []))
        return action

    def preview_for(self, action_type: str):
        if action_type == "dry_run_plink_qc":
            return [build_missingness_command(), build_hwe_command(), build_relatedness_command()]
        if action_type == "dry_run_ld_pruning":
            return build_ld_prune_command()
        if action_type == "dry_run_pca":
            return build_smartpca_command_preview()
        if action_type == "dry_run_admixture":
            return build_admixture_k_sweep_commands()
        if action_type == "dry_run_fst":
            return [build_fst_command(), build_windowed_fst_command()]
        if action_type == "dry_run_roh":
            return build_roh_command()
        if action_type == "dry_run_selection_scan":
            return [build_ihs_plan(), build_xpehh_plan()]
        return None


def _normalize_preview(preview, action: AgentAction):
    if isinstance(preview, list):
        return [_normalize_one(item, action) for item in preview]
    return _normalize_one(preview, action)


def _normalize_one(item: dict, action: AgentAction) -> dict:
    normalized = dict(item)
    normalized.setdefault("purpose", action.title)
    normalized.setdefault("required_inputs", action.required_inputs)
    normalized.setdefault("expected_outputs", action.expected_outputs or item.get("expected_outputs", []))
    normalized["execution_enabled"] = False
    return normalized
