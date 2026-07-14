from app.insilicopop.agent.loop import AgentLoop


def test_agent_loop_carries_memory_and_dependency_capsules():
    result = AgentLoop().run(
        query="selection is proven",
        uploads={
            "selection_scan": {
                "filename": "selection.tsv",
                "content": b"chr\tposition\tgene\tihs\tp_value\n1\t123\tLCT\t2.8\t0.001\n",
            }
        },
        memory_budget_chars=1500,
        memory_mode="compact",
    )

    assert result["carried_memory"]["facts"]
    assert result["carried_memory"]["dependency_capsules"]
    assert any(action["memory_dependencies"] for action in result["blocked_actions"])
