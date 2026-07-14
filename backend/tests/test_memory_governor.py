from app.insilicopop.memory.governor import CarriedMemory, CompressedMemoryItem, MemoryGovernor


def item(facts):
    return CompressedMemoryItem(
        step_name="test",
        memory_mode="compact",
        compressed_memory={
            "fact_items": facts,
        },
    )


def fact(fact_id, text, critical=False, score=0.5, category="fact"):
    return {
        "fact_id": fact_id,
        "text": text,
        "category": category,
        "importance_score": score,
        "is_critical": critical,
        "source_step": "test",
        "provenance_id": f"prov_{fact_id}",
        "downstream_dependency": text if critical else None,
        "retained_reason": "protected critical fact" if critical else "test",
    }


def test_critical_facts_are_retained_under_budget():
    result = MemoryGovernor().update(
        CarriedMemory(),
        item([fact("critical", "LD pruning unknown", True, 0.95), fact("low", "generic boilerplate", False, 0.1)]),
        budget_chars=600,
    )

    assert any(memory_fact.fact_id == "critical" for memory_fact in result.carried_memory.facts)


def test_duplicate_warnings_are_merged():
    governor = MemoryGovernor()
    first = governor.update(CarriedMemory(), item([fact("w1", "LD pruning unknown", True, 0.9, "warning")]), 1000)
    second = governor.update(first.carried_memory, item([fact("w2", "LD pruning unknown", True, 0.8, "warning")]), 1000)

    assert len([fact for fact in second.carried_memory.facts if fact.text == "LD pruning unknown"]) == 1
    assert any(entry["action"] == "merge_duplicate" for entry in second.decision_trace)


def test_low_importance_facts_dropped_first_and_logs_populated():
    facts = [fact("c", "selection proven overclaim", True, 0.95)] + [
        fact(f"l{i}", f"low importance generic summary {i}", False, 0.1) for i in range(20)
    ]

    result = MemoryGovernor().update(CarriedMemory(), item(facts), budget_chars=900)

    assert result.dropped_facts
    assert result.carried_memory.dropped_facts_log
    assert result.carried_memory.memory_decision_trace

