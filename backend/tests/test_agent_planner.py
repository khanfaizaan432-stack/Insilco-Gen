from app.insilicopop.agent.planner import AgentPlanner


def _flags(*codes):
    return [{"code": code, "provenance": {"rule_id": code, "provenance_id": code}} for code in codes]


def test_planner_creates_admixture_k_sweep_action():
    actions = AgentPlanner().plan(audit_report={"x": 1}, risk_flags=_flags("admixture_k_sweep_too_narrow"), carried_memory={})

    assert any(action.action_type == "dry_run_admixture" for action in actions)


def test_planner_creates_ld_pruning_action():
    actions = AgentPlanner().plan(audit_report={"x": 1}, risk_flags=_flags("pca_ld_pruning_not_documented"), carried_memory={})

    assert any(action.action_type == "dry_run_ld_pruning" for action in actions)


def test_planner_blocks_selection_overclaim():
    actions = AgentPlanner().plan(audit_report={"x": 1}, risk_flags=_flags("selection_overclaim_proven"), carried_memory={})

    blocked = [action for action in actions if action.status == "blocked"]
    assert any("selection" in (action.blocked_reason or "") for action in blocked)


def test_planner_blocks_tiny_population_fst_claim():
    actions = AgentPlanner().plan(audit_report={"x": 1}, risk_flags=_flags("fst_tiny_sample_size_caveat"), carried_memory={})

    assert any(action.action_type == "block_interpretation" and action.status == "blocked" for action in actions)

