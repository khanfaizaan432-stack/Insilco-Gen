from app.insilicopop.memory.governor import CarriedMemory, CompressedMemoryItem, MemoryGovernor


def update_for(text: str):
    item = CompressedMemoryItem(
        step_name="test",
        memory_mode="compact",
        compressed_memory={
            "fact_items": [
                {
                    "fact_id": "f1",
                    "text": text,
                    "category": "fact",
                    "importance_score": 0.9,
                    "is_critical": True,
                    "source_step": "test",
                    "provenance_id": "prov_test_001",
                    "retained_reason": "test",
                }
            ]
        },
    )
    return MemoryGovernor().update(CarriedMemory(), item, 1500).carried_memory.dependency_capsules


def assert_capsule(capsules):
    assert capsules
    capsule = capsules[0]
    assert capsule.trigger_fact
    assert capsule.implication
    assert capsule.blocked_interpretation
    assert capsule.required_next_step
    assert capsule.provenance_id


def test_capsule_for_admixture_narrow_k():
    assert_capsule(update_for("ADMIXTURE K=2-3 only narrow K"))


def test_capsule_for_ld_pruning_unknown():
    assert_capsule(update_for("LD pruning unknown"))


def test_capsule_for_selection_correction_missing():
    assert_capsule(update_for("selection correction not_documented"))

