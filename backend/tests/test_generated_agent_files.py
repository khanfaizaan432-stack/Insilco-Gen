import json
from pathlib import Path

from app.insilicopop.agent.loop import AgentLoop


def test_generated_agent_files_exist_and_match_response_counts():
    result = AgentLoop().run(
        query="selection is proven",
        uploads={
            "selection_scan": {
                "filename": "selection.tsv",
                "content": b"chr\tposition\tgene\tihs\tp_value\n1\t123\tLCT\t2.8\t0.001\n",
            }
        },
        memory_mode="compact",
    )

    expected = {
        "agent_state",
        "agent_trace",
        "action_proposals",
        "validated_actions",
        "command_previews",
        "blocked_actions",
        "failure_scope",
        "carried_memory",
        "final_report",
    }
    assert expected.issubset(result["generated_files"])
    for key in expected:
        meta = result["generated_files"][key]
        assert meta["created"] is True
        assert meta["filename"]
        assert meta["absolute_path"]
        assert meta["relative_path"]
        assert meta["file_type"]

    state = json.loads(Path(result["generated_files"]["agent_state"]["absolute_path"]).read_text(encoding="utf-8"))
    assert len(state["planned_actions"]) == len(result["planned_actions"])
    assert len(state["blocked_actions"]) == len(result["blocked_actions"])
    assert len(state["command_previews"]) == len(result["command_previews"])
