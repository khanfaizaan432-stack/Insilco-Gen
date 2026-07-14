import json
import subprocess
import sys
from pathlib import Path

from app.insilicopop.agent.loop import AgentLoop


def _uploads():
    return {
        "selection_scan": {
            "filename": "selection.tsv",
            "content": b"chr\tposition\tgene\tihs\tp_value\n1\t123\tLCT\t2.8\t0.001\n",
        }
    }


def test_agent_response_exposes_internal_counts_and_final_step():
    result = AgentLoop().run(query="selection is proven", uploads=_uploads(), memory_mode="compact")
    state = result["final_state"]

    assert result["planned_actions"]
    assert result["blocked_actions"]
    assert result["failure_reasons"]
    assert len(result["planned_actions"]) == len(state["planned_actions"])
    assert len(result["blocked_actions"]) == len(state["blocked_actions"])
    assert len(result["failure_reasons"]) == len(state["failure_reasons"])
    assert state["current_step"] in {"completed", "blocked", "report_generated"}
    assert state["current_step"] != "audit_inputs"


def test_agent_state_file_matches_response_counts():
    result = AgentLoop().run(query="selection is proven", uploads=_uploads(), memory_mode="compact")
    state_path = Path(result["generated_files"]["agent_state"]["absolute_path"])
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert len(state["planned_actions"]) == len(result["planned_actions"])
    assert len(state["blocked_actions"]) == len(result["blocked_actions"])
    assert len(state["failure_reasons"]) == len(result["failure_reasons"])


def test_cli_and_service_expose_same_nonzero_count_shape():
    service_result = AgentLoop().run(query="selection is proven", uploads=_uploads(), memory_mode="compact")
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.insilicopop.cli",
            "agent-run",
            "--query",
            "selection is proven",
            "--selection",
            "examples/selection_scan_results.csv",
            "--memory-mode",
            "compact",
        ],
        cwd="backend",
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )

    assert len(service_result["planned_actions"]) > 0
    assert len(service_result["blocked_actions"]) > 0
    assert "planned_actions=" in cli.stdout
    assert "blocked_actions=" in cli.stdout
    assert "command_previews=" in cli.stdout
    assert "final_state_current_step=" in cli.stdout
    assert "external_llm_called=false" in cli.stdout
