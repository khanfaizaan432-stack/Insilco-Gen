from app.insilicopop.agent.actions import make_action
from app.insilicopop.agent.state import AgentState


def test_agent_state_initializes_and_records_actions():
    state = AgentState(run_id="run1", query="test")
    action = make_action(1, "parse_inputs", "Parse", "Parse inputs")

    state.record_action(action)
    state.complete_action(action)
    state.carry_memory({"facts": ["x"], "size_chars": 10})

    assert state.run_id == "run1"
    assert state.completed_actions[0].status == "completed"
    assert state.carried_memory["facts"] == ["x"]


def test_agent_state_records_blocked_actions():
    state = AgentState(run_id="run1")
    action = make_action(1, "block_interpretation", "Block", "Unsafe", status="planned")

    state.record_action(action)
    state.block_action(action, "unsafe interpretation")

    assert state.blocked_actions[0].status == "blocked"
    assert state.blocked_actions[0].blocked_reason == "unsafe interpretation"

