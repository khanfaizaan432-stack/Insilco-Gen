from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from fastapi.encoders import jsonable_encoder

from app.schemas.insilicopop import AuditFinding


def build_reliability_markdown(score: int, findings: list[AuditFinding], reliability: dict[str, Any] | None = None) -> str:
    reliability = reliability or {}
    lines = [
        "# InSilicoPop Reliability Report",
        "",
        f"Reliability score: {score}/100",
        f"Score band: {reliability.get('score_band', 'unknown')}",
        "",
        "## Penalties",
    ]
    penalties = reliability.get("penalties", [])
    if not penalties:
        lines.append("- None")
    for penalty in penalties:
        lines.append(f"- {penalty.get('rule_id')}: {penalty.get('points')} points - {penalty.get('reason')}")
    lines.extend(["", "## Positive Factors"])
    for factor in reliability.get("positive_factors", []) or ["None recorded"]:
        lines.append(f"- {factor}")
    lines.extend(["", "## Risk Flags"])
    for finding in findings:
        lines.append(f"- {finding.severity.upper()}: {finding.code} - {finding.message}")
    return "\n".join(lines) + "\n"


def build_overclaim_markdown(findings: list[AuditFinding]) -> str:
    overclaims = [finding for finding in findings if finding.code.startswith("overclaim_")]
    lines = ["# Overclaim Warnings", ""]
    if not overclaims:
        lines.append("No explicit overclaim pattern was detected. This is not clinical or genetic counseling advice.")
    for finding in overclaims:
        lines.append(f"- {finding.code}: {finding.message}")
        lines.append("  Required fix: use cautious research language and add correction, demographic, and endogamy caveats before strong interpretation.")
    return "\n".join(lines) + "\n"


def write_audit_outputs(run_dir: Path, payload: dict[str, Any], memory: dict[str, Any], plan: dict[str, Any], score: int, findings: list[AuditFinding]) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "audit_report": run_dir / "insilicopop_audit_report.json",
        "compressed_memory": run_dir / "compressed_memory.json",
        "next_analysis_plan": run_dir / "next_analysis_plan.yaml",
        "reliability_report": run_dir / "reliability_report.md",
        "overclaim_warnings": run_dir / "overclaim_warnings.md",
        "provenance_trace": run_dir / "provenance_trace.json",
    }
    files["audit_report"].write_text(json.dumps(jsonable_encoder(payload), indent=2), encoding="utf-8")
    files["compressed_memory"].write_text(json.dumps(jsonable_encoder(memory), indent=2), encoding="utf-8")
    files["next_analysis_plan"].write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    reliability = payload.get("reliability") if isinstance(payload.get("reliability"), dict) else {}
    files["reliability_report"].write_text(build_reliability_markdown(score, findings, reliability), encoding="utf-8")
    files["overclaim_warnings"].write_text(build_overclaim_markdown(findings), encoding="utf-8")
    provenance_trace = _provenance_trace(findings, reliability, plan, memory)
    files["provenance_trace"].write_text(json.dumps(jsonable_encoder(provenance_trace), indent=2), encoding="utf-8")
    return {
        key: {
            "filename": path.name,
            "absolute_path": str(path.resolve()),
            "relative_path": str(path),
            "file_type": path.suffix.lstrip(".") or "text",
            "created": path.exists(),
        }
        for key, path in files.items()
    }


def _provenance_trace(
    findings: list[AuditFinding],
    reliability: dict[str, Any],
    plan: dict[str, Any],
    memory: dict[str, Any],
) -> list[dict[str, Any]]:
    trace = [
        {
            "kind": "risk_flag",
            "code": finding.code,
            "message": finding.message,
            "severity": finding.severity,
            "provenance": finding.provenance.model_dump() if finding.provenance else None,
        }
        for finding in findings
    ]
    for penalty in reliability.get("penalties", []):
        trace.append({"kind": "reliability_penalty", **penalty})
    for step in plan.get("recommended_steps", []):
        trace.append({"kind": "recommended_step", **step})
    for step in plan.get("blocked_steps", []):
        trace.append({"kind": "blocked_step", **step})
    for tool_name, memory_item in memory.get("tools", {}).items():
        compressed = memory_item.get("compressed_memory", {})
        for fact in compressed.get("key_facts", []):
            trace.append(
                {
                    "kind": "memory_fact",
                    "tool_name": tool_name,
                    "fact": fact,
                    "provenance": {
                        "source_file": tool_name,
                        "parser_name": f"{tool_name}_parser",
                        "auditor_name": "DomainMemoryCompressor",
                        "rule_id": f"MEMORY_RETAIN_{tool_name.upper()}",
                        "evidence_value": fact,
                        "severity": "info",
                    },
                }
            )
    return trace
