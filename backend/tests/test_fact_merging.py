from app.insilicopop.memory.governor import CarriedMemory, CompressedMemoryItem, MemoryGovernor


def run(texts):
    item = CompressedMemoryItem(
        step_name="test",
        memory_mode="compact",
        compressed_memory={
            "fact_items": [
                {
                    "fact_id": f"f{i}",
                    "text": text,
                    "category": "fact",
                    "importance_score": 0.8,
                    "is_critical": True,
                    "source_step": "test",
                    "provenance_id": f"prov_{i}",
                    "retained_reason": "test",
                }
                for i, text in enumerate(texts)
            ]
        },
    )
    return MemoryGovernor().update(CarriedMemory(), item, 2000).carried_memory


def test_ld_pruning_merge():
    memory = run(["LD pruning unknown", "PCA interpretation provisional"])
    assert any("PCA interpretation provisional" in fact.text for fact in memory.facts)


def test_admixture_k_merge():
    memory = run(["ADMIXTURE K=2-3 only", "narrow K", "Run K=2-10"])
    assert any("K=2-10" in fact.text for fact in memory.facts)


def test_roh_endogamy_merge():
    memory = run(["high ROH burden", "endogamy caveat"])
    assert any("endogamy" in fact.text.lower() for fact in memory.facts)

