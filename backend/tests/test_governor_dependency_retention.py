from app.insilicopop.memory.governor import CarriedMemory, CompressedMemoryItem, MemoryGovernor


def fact(fact_id, text, score=0.1):
    return {
        "fact_id": fact_id,
        "text": text,
        "category": "fact",
        "importance_score": score,
        "is_critical": "LD pruning" in text or "selection" in text,
        "source_step": "test",
        "provenance_id": f"prov_{fact_id}",
        "retained_reason": "test",
    }


def test_dependency_facts_retained_before_generic_summaries():
    item = CompressedMemoryItem(
        step_name="test",
        memory_mode="compact",
        compressed_memory={"fact_items": [fact("dep", "LD pruning unknown", 0.7)] + [fact(f"g{i}", f"generic summary {i}", 0.1) for i in range(20)]},
    )

    result = MemoryGovernor().update(CarriedMemory(), item, 900)

    assert any("LD pruning" in memory_fact.text for memory_fact in result.carried_memory.facts)
    assert result.carried_memory.dropped_facts_log


def test_blocked_interpretations_and_next_steps_retained_under_tight_budget():
    item = CompressedMemoryItem(
        step_name="selection",
        memory_mode="compact",
        compressed_memory={"fact_items": [fact("sel", "selection correction not_documented", 0.9)]},
    )

    result = MemoryGovernor().update(CarriedMemory(), item, 500)

    assert result.carried_memory.blocked_interpretations
    assert result.carried_memory.enables_next_steps
    assert result.carried_memory.dependency_capsules

