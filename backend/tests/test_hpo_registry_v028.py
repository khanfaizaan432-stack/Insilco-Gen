from app.insilicopop.clinical.hpo_registry import load_hpo_registry


def test_registry_is_local_versioned_and_stably_ordered():
    registry = load_hpo_registry()
    assert registry.registry_version == "insilicopop-hpo-mini-2026-07-v1"
    assert len(registry.terms) == 10
    assert [item.hpo_id for item in registry.terms] == sorted(item.hpo_id for item in registry.terms)
    assert registry is load_hpo_registry()


def test_registry_resolves_canonical_term_and_bounded_synonyms():
    term = load_hpo_registry().resolve("HP:0001250")
    assert term is not None
    assert term.canonical_label == "Seizure"
    assert "Seizures" in term.synonyms
    assert load_hpo_registry().resolve("HP:9999999") is None

