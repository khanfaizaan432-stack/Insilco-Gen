from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.audit_service import InSilicoPopAuditService
from app.insilicopop.benchmarks.agent_trace import AgentMemoryBenchmarkRunner
from app.insilicopop.benchmarks.runner import MemoryBenchmarkRunner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.insilicopop.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    benchmark = subparsers.add_parser("benchmark-memory")
    benchmark.add_argument("--scenario", default="all")
    benchmark.add_argument("--token-budget", type=int, default=1000)

    history = subparsers.add_parser("benchmark-history")
    history.add_argument("--last", type=int, default=10)

    agent_memory = subparsers.add_parser("benchmark-agent-memory")
    agent_memory.add_argument("--scenario", default="all")
    agent_memory.add_argument("--budget-chars", type=int, default=1500)
    agent_memory.add_argument("--memory-mode", default="compact")

    audit = subparsers.add_parser("audit")
    audit.add_argument("--metadata")
    audit.add_argument("--pca")
    audit.add_argument("--admixture")
    audit.add_argument("--fst")
    audit.add_argument("--roh")
    audit.add_argument("--plink-qc")
    audit.add_argument("--selection")
    audit.add_argument("--query")

    agent_run = subparsers.add_parser("agent-run")
    agent_run.add_argument("--metadata")
    agent_run.add_argument("--pca")
    agent_run.add_argument("--admixture")
    agent_run.add_argument("--fst")
    agent_run.add_argument("--roh")
    agent_run.add_argument("--plink-qc")
    agent_run.add_argument("--selection")
    agent_run.add_argument("--vcf")
    agent_run.add_argument("--plink-bed")
    agent_run.add_argument("--plink-bim")
    agent_run.add_argument("--plink-fam")
    agent_run.add_argument("--ped")
    agent_run.add_argument("--map")
    agent_run.add_argument("--pgen")
    agent_run.add_argument("--pvar")
    agent_run.add_argument("--psam")
    agent_run.add_argument("--bam")
    agent_run.add_argument("--cram")
    agent_run.add_argument("--query")
    agent_run.add_argument("--goal")
    agent_run.add_argument("--memory-budget-chars", type=int, default=1500)
    agent_run.add_argument("--memory-mode", default="compact", choices=["compact", "ultra_compact"])
    agent_run.add_argument("--max-steps", type=int, default=8)
    agent_run.add_argument("--llm-provider", default="mock", choices=["mock", "openai_compatible"])
    agent_run.add_argument("--clinical-case-intake")

    args = parser.parse_args(argv)
    if args.command == "benchmark-memory":
        result = MemoryBenchmarkRunner().run(args.scenario, args.token_budget)
        print(f"InSilicoPop memory benchmark run_id={result['run_id']}")
        print(f"winner={result['winner']}")
        print(result["summary"])
        print(json.dumps({"generated_files": result["generated_files"]}, indent=2))
        return 0
    if args.command == "audit":
        result = InSilicoPopAuditService().run(args.query, _audit_uploads(args)).model_dump()
        print(f"InSilicoPop audit run_id={result['run_id']}")
        print(f"reliability_score={result['reliability_score']}")
        print(f"risk_flags={len(result['risk_flags'])}")
        print(json.dumps({"generated_files": result["generated_files"]}, indent=2))
        return 0
    if args.command == "benchmark-history":
        _print_history(args.last)
        return 0
    if args.command == "agent-run":
        result = AgentLoop().run(
            query=args.query or args.goal,
            uploads=_audit_uploads(args),
            max_steps=args.max_steps,
            memory_budget_chars=args.memory_budget_chars,
            memory_mode=args.memory_mode,
            llm_provider=args.llm_provider,
            clinical_case_intake=_json_object_file(args.clinical_case_intake) if args.clinical_case_intake else None,
        )
        top_failure = result["failure_reasons"][0]["message"] if result["failure_reasons"] else "none"
        memory_size = result["carried_memory"].get("size_chars", 0)
        report_path = result["generated_files"]["final_report"]["absolute_path"]
        reliability = result["final_state"].get("reliability_score")
        current_step = result["final_state"].get("current_step")
        print(f"InSilicoPop agent run_id={result['run_id']}")
        print(f"reliability_score={reliability}")
        print(f"final_state_current_step={current_step}")
        print(f"planned_actions={len(result['planned_actions'])}")
        print(f"completed_actions={len(result['completed_actions'])}")
        print(f"blocked_actions={len(result['blocked_actions'])}")
        print(f"failure_reasons={len(result['failure_reasons'])}")
        print(f"command_previews={len(result['command_previews'])}")
        print(f"agent_trace_events={len(result['agent_trace'])}")
        print(f"carried_memory_non_empty={bool(result['carried_memory'])}")
        print(f"top_failure_reason={top_failure}")
        print(f"memory_size_chars={memory_size}")
        print(f"generated_report={report_path}")
        print("external_llm_called=false")
        print("external_tools_executed=false")
        specialist = result["final_state"].get("specialist_agent_workspace") or {}
        print(f"specialist_agent_outputs={len(specialist.get('agent_outputs', []))}")
        print(f"candidate_acmg_evidence_items={len(specialist.get('candidate_criteria', []))}")
        print(
            "specialist_review_actions_applied="
            f"{len(specialist.get('applied_review_actions', []))}"
        )
        print(
            "specialist_review_actions_rejected="
            f"{sum(1 for item in specialist.get('review_action_results', []) if item.get('result_status') == 'rejected')}"
        )
        return 0
    if args.command == "benchmark-agent-memory":
        result = AgentMemoryBenchmarkRunner().run(args.scenario, args.budget_chars, args.memory_mode)
        print(f"InSilicoPop agent-memory benchmark run_id={result['run_id']}")
        print(f"winner={result['winner']}")
        print("scenario | method | critical_recall | dependency_recall | blocked_recall | next_step_recall | budget_violations | final_score")
        for method, method_result in result["results"].items():
            aggregate = method_result["aggregate"]
            print(
                f"{result['scenario']} | {method} | {aggregate['final_critical_fact_recall']} | "
                f"{aggregate['downstream_dependency_recall']} | {aggregate['blocked_interpretation_recall']} | "
                f"{aggregate['next_step_dependency_recall']} | {aggregate['budget_violation_count']} | {aggregate['final_score']}"
            )
        return 0
    return 2


def _audit_uploads(args: argparse.Namespace) -> dict[str, dict[str, bytes | str] | None]:
    mapping = {
        "metadata": args.metadata,
        "pca": args.pca,
        "admixture": args.admixture,
        "fst": args.fst,
        "roh": args.roh,
        "plink_qc": args.plink_qc,
        "selection_scan": args.selection,
        "vcf": getattr(args, "vcf", None),
        "plink_bed": getattr(args, "plink_bed", None),
        "plink_bim": getattr(args, "plink_bim", None),
        "plink_fam": getattr(args, "plink_fam", None),
        "ped": getattr(args, "ped", None),
        "map": getattr(args, "map", None),
        "pgen": getattr(args, "pgen", None),
        "pvar": getattr(args, "pvar", None),
        "psam": getattr(args, "psam", None),
        "bam": getattr(args, "bam", None),
        "cram": getattr(args, "cram", None),
    }
    uploads: dict[str, dict[str, bytes | str] | None] = {}
    for name, path_value in mapping.items():
        if not path_value:
            uploads[name] = None
            continue
        path = Path(path_value)
        uploads[name] = {"content": path.read_bytes(), "filename": path.name}
    return uploads


def _print_history(last: int) -> None:
    history_path = Path(__file__).resolve().parents[1] / "generated" / "benchmarks" / "benchmark_history.jsonl"
    if not history_path.exists():
        print("run_id | scenario | method | critical_recall | compression_ratio | final_score")
        return
    rows = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print("run_id | scenario | method | critical_recall | compression_ratio | final_score")
    for row in rows[-last:]:
        critical = row.get("critical_fact_recall", row.get("final_critical_fact_recall", ""))
        ratio = row.get("compression_ratio", "")
        score = row.get("final_score", "")
        print(
            f"{row['run_id']} | {row['scenario']} | {row['method']} | "
            f"{critical} | {ratio} | {score}"
        )


def _json_object_file(path_value: str) -> dict[str, Any]:
    value = json.loads(Path(path_value).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("clinical case intake file must contain a JSON object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
