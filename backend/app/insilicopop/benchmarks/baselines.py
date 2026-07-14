from __future__ import annotations

import json
from typing import Any

from app.insilicopop.audit_service import InSilicoPopAuditService
from app.insilicopop.benchmarks.tasks import BenchmarkScenario


def raw_trace_text(scenario: BenchmarkScenario) -> str:
    return json.dumps(
        {"query": scenario.query, "tool_outputs": scenario.tool_outputs},
        sort_keys=True,
    )


def domain_aware_memory(scenario: BenchmarkScenario, token_budget: int) -> dict[str, Any]:
    return domain_aware_memory_mode(scenario, token_budget, "verbose")


def domain_aware_memory_mode(scenario: BenchmarkScenario, token_budget: int, memory_mode: str) -> dict[str, Any]:
    uploads = {
        name: {"content": content.encode("utf-8"), "filename": f"{name}.csv"}
        for name, content in scenario.tool_outputs.items()
    }
    result = InSilicoPopAuditService().run(scenario.query, uploads, memory_mode=memory_mode)
    payload = result.model_dump()
    if memory_mode == "verbose":
        text_payload = payload
        raw_size = len(raw_trace_text(scenario))
        compressed_size = len(json.dumps(text_payload, sort_keys=True))
    else:
        tools = {
            tool_name: item["compressed_memory"]
            for tool_name, item in payload["compressed_memory"]["tools"].items()
        }
        text_payload = {
            "query": scenario.query,
            "risk_flags": [
                {"code": item["code"], "message": item["message"]}
                for item in payload["risk_flags"]
            ],
            "steps": [step["title"] for step in payload["next_analysis_plan"]["recommended_steps"]],
            "blocks": [step["blocked_step"] for step in payload["next_analysis_plan"]["blocked_steps"]],
            "memory": tools,
        }
        raw_size = sum(item.get("raw_size_chars", 0) for item in payload["compressed_memory"]["tools"].values())
        compressed_size = sum(item.get("compressed_size_chars", 0) for item in payload["compressed_memory"]["tools"].values())
    return {
        "method": f"domain_aware_{memory_mode}",
        "text": json.dumps(text_payload, sort_keys=True),
        "raw_size_chars": raw_size,
        "compressed_size_chars": compressed_size,
        "payload": payload,
    }


def domain_aware_verbose_memory(scenario: BenchmarkScenario, token_budget: int) -> dict[str, Any]:
    return domain_aware_memory_mode(scenario, token_budget, "verbose")


def domain_aware_compact_memory(scenario: BenchmarkScenario, token_budget: int) -> dict[str, Any]:
    return domain_aware_memory_mode(scenario, token_budget, "compact")


def domain_aware_ultra_compact_memory(scenario: BenchmarkScenario, token_budget: int) -> dict[str, Any]:
    return domain_aware_memory_mode(scenario, token_budget, "ultra_compact")


def raw_truncation_memory(scenario: BenchmarkScenario, token_budget: int) -> dict[str, Any]:
    text = raw_trace_text(scenario)
    return {"method": "raw_truncation", "text": text[:token_budget], "payload": {"truncated_text": text[:token_budget]}}


def naive_summary_memory(scenario: BenchmarkScenario, token_budget: int) -> dict[str, Any]:
    summaries = []
    for tool_name, output in scenario.tool_outputs.items():
        lines = [line for line in output.splitlines() if line.strip()]
        header = lines[0].split(",") if lines else []
        first_rows = lines[1:3]
        numeric_values = _numeric_values(lines[1:])
        summaries.append(
            {
                "tool": tool_name,
                "row_count": max(len(lines) - 1, 0),
                "columns": header,
                "first_rows": first_rows,
                "numeric_min": min(numeric_values) if numeric_values else None,
                "numeric_max": max(numeric_values) if numeric_values else None,
            }
        )
    text = json.dumps({"query": scenario.query, "generic_summary": summaries}, sort_keys=True)
    return {"method": "naive_summary", "text": text[:token_budget], "payload": summaries}


def oracle_full_memory(scenario: BenchmarkScenario, token_budget: int) -> dict[str, Any]:
    text = json.dumps(
        {
            "expected_facts": [fact.text for fact in scenario.expected_facts],
            "expected_fact_keywords": {fact.fact_id: fact.keywords for fact in scenario.expected_facts},
            "expected_next_steps": scenario.expected_next_step_keywords,
        },
        sort_keys=True,
    )
    return {"method": "oracle_full", "text": text, "payload": {"expected_facts": [fact.model_dump() for fact in scenario.expected_facts]}}


def _numeric_values(rows: list[str]) -> list[float]:
    values: list[float] = []
    for row in rows:
        for cell in row.split(","):
            try:
                values.append(float(cell))
            except ValueError:
                continue
    return values
