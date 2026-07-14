from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.insilicopop.memory.budget import budget_reservations, fact_sort_key, governor_score, serialized_size


class MemoryFact(BaseModel):
    fact_id: str
    text: str
    category: str = "fact"
    importance_score: float = 0.5
    is_critical: bool = False
    source_step: str
    provenance_id: str | None = None
    downstream_dependency: str | None = None
    downstream_dependencies: list[str] = Field(default_factory=list)
    blocks_interpretations: list[str] = Field(default_factory=list)
    enables_next_steps: list[str] = Field(default_factory=list)
    retained_reason: str = "retained"
    merge_key: str | None = None


class DependencyCapsule(BaseModel):
    capsule_id: str
    trigger_fact: str
    implication: str
    blocked_interpretation: str
    required_next_step: str
    provenance_id: str | None = None


class CarriedMemory(BaseModel):
    facts: list[MemoryFact] = Field(default_factory=list)
    critical_facts: list[MemoryFact] = Field(default_factory=list)
    warnings: list[MemoryFact] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    downstream_dependencies: list[str] = Field(default_factory=list)
    blocked_interpretations: list[str] = Field(default_factory=list)
    enables_next_steps: list[str] = Field(default_factory=list)
    dependency_capsules: list[DependencyCapsule] = Field(default_factory=list)
    provenance_refs: list[str] = Field(default_factory=list)
    dropped_facts_log: list[dict[str, Any]] = Field(default_factory=list)
    memory_decision_trace: list[dict[str, Any]] = Field(default_factory=list)
    memory_mode: Literal["compact", "ultra_compact"] = "compact"
    size_chars: int = 0
    budget_usage_by_category: dict[str, Any] = Field(default_factory=dict)


class CompressedMemoryItem(BaseModel):
    step_name: str
    memory_mode: Literal["compact", "ultra_compact"] = "compact"
    compressed_memory: dict[str, Any]


class MemoryUpdateResult(BaseModel):
    carried_memory: CarriedMemory
    kept_facts: list[MemoryFact]
    dropped_facts: list[MemoryFact]
    merged_facts: list[MemoryFact]
    decision_trace: list[dict[str, Any]]
    budget_before: int
    budget_after: int
    over_budget: bool


class MemoryGovernor:
    def update(
        self,
        current_memory: CarriedMemory,
        new_item: CompressedMemoryItem,
        budget_chars: int,
    ) -> MemoryUpdateResult:
        budget_before = max(budget_chars - current_memory.size_chars, 0)
        incoming = _facts_from_item(new_item)
        merged, duplicate_trace = _merge_facts(current_memory.facts, incoming)
        merged, semantic_trace = _semantic_merge(merged)
        trace = list(current_memory.memory_decision_trace)
        trace.extend(duplicate_trace)
        trace.extend(semantic_trace)
        sorted_facts = sorted(merged, key=fact_sort_key, reverse=True)
        kept: list[MemoryFact] = []
        dropped: list[MemoryFact] = []
        for fact in sorted_facts:
            candidate = _build_memory(
                kept + [fact],
                current_memory.assumptions,
                current_memory.dropped_facts_log,
                trace,
                new_item.memory_mode,
            )
            if _budget_size(candidate) <= budget_chars or _is_protected(fact):
                kept.append(fact)
                trace.append({"action": "keep", "fact_id": fact.fact_id, "score": governor_score(fact), "reason": fact.retained_reason})
            else:
                dropped.append(fact)
                trace.append({"action": "drop", "fact_id": fact.fact_id, "reason": "over budget and non-critical"})

        carried = _build_memory(
            kept,
            current_memory.assumptions or ["deterministic_local_memory"],
            current_memory.dropped_facts_log
            + [
                {
                    "fact_id": fact.fact_id,
                    "text": fact.text,
                    "reason": "over budget and lower importance than protected facts",
                }
                for fact in dropped
            ],
            trace,
            new_item.memory_mode,
        )
        carried.size_chars = _budget_size(carried)
        over_budget = carried.size_chars > budget_chars
        if over_budget:
            carried.memory_decision_trace.append(
                {
                    "action": "over_budget",
                    "size_chars": carried.size_chars,
                    "budget_chars": budget_chars,
                    "reason": "protected critical facts exceed budget",
                }
            )
        return MemoryUpdateResult(
            carried_memory=carried,
            kept_facts=kept,
            dropped_facts=dropped,
            merged_facts=merged,
            decision_trace=carried.memory_decision_trace,
            budget_before=budget_before,
            budget_after=max(budget_chars - carried.size_chars, 0),
            over_budget=over_budget,
        )


def _facts_from_item(item: CompressedMemoryItem) -> list[MemoryFact]:
    memory = item.compressed_memory
    raw_items = memory.get("fact_items") or memory.get("fi") or []
    facts = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        fact = dict(raw)
        fact.setdefault("source_step", item.step_name)
        fact.setdefault("fact_id", f"{item.step_name}_{len(facts)}")
        enriched = _enrich_fact(fact, item.step_name)
        facts.append(MemoryFact(**enriched))
    if facts:
        return facts
    fallback_values = []
    for key in ["facts", "cf", "warnings", "w", "downstream_dependencies", "d"]:
        values = memory.get(key, [])
        if isinstance(values, list):
            fallback_values.extend(str(value) for value in values)
    return [
        MemoryFact(
            fact_id=f"{item.step_name}_{idx}",
            text=text,
            category="fact",
            importance_score=0.7,
            is_critical=_is_critical(text),
            source_step=item.step_name,
            retained_reason="fallback fact extraction",
        )
        for idx, text in enumerate(dict.fromkeys(fallback_values))
    ]


def _merge_facts(existing: list[MemoryFact], incoming: list[MemoryFact]) -> tuple[list[MemoryFact], list[dict[str, Any]]]:
    by_text = {(fact.merge_key or fact.text.lower()): fact for fact in existing}
    trace: list[dict[str, Any]] = []
    for fact in incoming:
        key = fact.merge_key or fact.text.lower()
        if key in by_text:
            existing_fact = by_text[key]
            existing_fact.importance_score = max(existing_fact.importance_score, fact.importance_score)
            existing_fact.is_critical = existing_fact.is_critical or fact.is_critical
            existing_fact.downstream_dependencies = _uniq(existing_fact.downstream_dependencies + fact.downstream_dependencies)
            existing_fact.blocks_interpretations = _uniq(existing_fact.blocks_interpretations + fact.blocks_interpretations)
            existing_fact.enables_next_steps = _uniq(existing_fact.enables_next_steps + fact.enables_next_steps)
            if existing_fact.text != fact.text:
                existing_fact.text = _merged_text(existing_fact.merge_key, existing_fact.text, fact.text)
            trace.append({"action": "merge_duplicate", "fact_id": existing_fact.fact_id, "source_step": fact.source_step})
        else:
            by_text[key] = fact
    return list(by_text.values()), trace


def _build_memory(
    facts: list[MemoryFact],
    assumptions: list[str],
    dropped_log: list[dict[str, Any]],
    trace: list[dict[str, Any]],
    memory_mode: Literal["compact", "ultra_compact"],
) -> CarriedMemory:
    warnings = [fact for fact in facts if fact.category == "warning" or "warning" in fact.retained_reason.lower()]
    critical = [fact for fact in facts if fact.is_critical]
    deps = sorted({dep for fact in facts for dep in ([fact.downstream_dependency] if fact.downstream_dependency else []) + fact.downstream_dependencies if dep})
    blocks = sorted({block for fact in facts for block in fact.blocks_interpretations})
    next_steps = sorted({step for fact in facts for step in fact.enables_next_steps})
    capsules = _dependency_capsules(facts)
    prov = sorted({fact.provenance_id for fact in facts if fact.provenance_id})
    memory = CarriedMemory(
        facts=facts,
        critical_facts=critical,
        warnings=warnings,
        assumptions=assumptions,
        downstream_dependencies=deps,
        blocked_interpretations=blocks,
        enables_next_steps=next_steps,
        dependency_capsules=capsules,
        provenance_refs=prov,
        dropped_facts_log=dropped_log,
        memory_decision_trace=trace,
        memory_mode=memory_mode,
    )
    memory.budget_usage_by_category = _budget_usage(memory)
    memory.size_chars = _budget_size(memory)
    return memory


def _is_critical(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in ["selection", "proven", "ld pruning", "tiny", "high roh", "narrow k", "highest fst", "best k", "correction", "seed"])


def _enrich_fact(fact: dict[str, Any], step_name: str) -> dict[str, Any]:
    text = str(fact.get("text", ""))
    lowered = text.lower()
    deps = list(fact.get("downstream_dependencies") or [])
    blocks = list(fact.get("blocks_interpretations") or [])
    next_steps = list(fact.get("enables_next_steps") or [])
    merge_key = fact.get("merge_key")
    if "ld pruning" in lowered:
        merge_key = "pca_ld_pruning"
        deps.append("PCA and ADMIXTURE interpretation should remain provisional.")
        blocks.append("Strong PCA cluster interpretation")
        next_steps.append("Run PLINK LD pruning before PCA.")
    if "narrow k" in lowered or ("admixture" in lowered and "k" in lowered):
        merge_key = "admixture_k_sweep"
        deps.append("Do not interpret ancestry components until broader K sweep is completed.")
        blocks.append("Strong ancestry interpretation")
        next_steps.append("Run ADMIXTURE K=2-10 with multiple seeds.")
    if "high roh" in lowered:
        merge_key = "roh_endogamy"
        deps.append("Interpret ROH with endogamy/founder-effect caveat.")
        blocks.append("Disease interpretation from ROH alone")
        next_steps.append("Run population-specific ROH/IBD summary.")
    if "highest fst" in lowered:
        merge_key = merge_key or "fst_highest_pair"
        deps.append("Pairwise FST interpretation should account for sample sizes.")
        blocks.append("Strong FST population separation claim")
        next_steps.append("Use larger groups or cautious pairwise FST interpretation.")
    elif "tiny" in lowered:
        merge_key = merge_key or "fst_tiny_n"
        deps.append("Pairwise FST interpretation should account for tiny population sample sizes.")
        blocks.append("Strong FST population separation claim")
        next_steps.append("Use larger groups or cautious pairwise FST interpretation.")
    if "selection" in lowered or "correction" in lowered:
        merge_key = merge_key or "selection_correction"
        deps.append("Selection candidates require correction and demographic caveats.")
        blocks.append("Selection is proven interpretation")
        next_steps.append("Add multiple-testing correction and demographic controls.")
    if "north indian" in lowered or "broad" in lowered:
        merge_key = merge_key or "broad_labels"
        deps.append("Broad labels may hide fine-scale endogamous structure.")
        blocks.append("Fine-scale population interpretation from broad labels")
        next_steps.append("Collect finer-grained community/endogamous group metadata.")
    fact["downstream_dependencies"] = _uniq(deps)
    fact["blocks_interpretations"] = _uniq(blocks)
    fact["enables_next_steps"] = _uniq(next_steps)
    fact["merge_key"] = merge_key
    if fact["downstream_dependencies"] or fact["blocks_interpretations"] or fact["enables_next_steps"]:
        fact["importance_score"] = max(float(fact.get("importance_score", 0.5)), 0.85)
        fact["retained_reason"] = "dependency-bearing fact"
    return fact


def _semantic_merge(facts: list[MemoryFact]) -> tuple[list[MemoryFact], list[dict[str, Any]]]:
    by_key: dict[str, MemoryFact] = {}
    trace: list[dict[str, Any]] = []
    for fact in facts:
        key = fact.merge_key or fact.fact_id
        if key in by_key:
            existing = by_key[key]
            existing.text = _merged_text(key, existing.text, fact.text)
            existing.importance_score = max(existing.importance_score, fact.importance_score)
            existing.is_critical = existing.is_critical or fact.is_critical
            existing.downstream_dependencies = _uniq(existing.downstream_dependencies + fact.downstream_dependencies)
            existing.blocks_interpretations = _uniq(existing.blocks_interpretations + fact.blocks_interpretations)
            existing.enables_next_steps = _uniq(existing.enables_next_steps + fact.enables_next_steps)
            trace.append({"action": "merge_related", "merge_key": key, "fact_id": existing.fact_id})
        else:
            by_key[key] = fact
    return list(by_key.values()), trace


def _merged_text(merge_key: str | None, left: str, right: str) -> str:
    if merge_key == "pca_ld_pruning":
        return "LD pruning unknown -> PCA interpretation provisional."
    if merge_key == "admixture_k_sweep":
        return "ADMIXTURE K=2-3 only; narrow K sweep -> broaden to K=2-10 before ancestry interpretation."
    if merge_key == "roh_endogamy":
        return "High ROH burden -> interpret with endogamy/founder-effect caveat."
    if merge_key == "selection_correction":
        return "Selection signal correction not_documented -> do not claim selection is proven."
    if merge_key == "fst_tiny_n":
        return "Tiny population groups fewer than five -> use caution in pairwise FST interpretation."
    if merge_key == "broad_labels":
        return "Broad Indian labels -> collect finer-grained endogamous group metadata."
    return left if left == right else f"{left} -> {right}"


def _dependency_capsules(facts: list[MemoryFact]) -> list[DependencyCapsule]:
    capsules: list[DependencyCapsule] = []
    for fact in facts:
        if not (fact.downstream_dependencies or fact.blocks_interpretations or fact.enables_next_steps):
            continue
        capsules.append(
            DependencyCapsule(
                capsule_id=f"dep_{fact.fact_id[:24]}",
                trigger_fact=fact.text,
                implication=fact.downstream_dependencies[0] if fact.downstream_dependencies else "Interpretation is provisional.",
                blocked_interpretation=fact.blocks_interpretations[0] if fact.blocks_interpretations else "Over-strong interpretation",
                required_next_step=fact.enables_next_steps[0] if fact.enables_next_steps else "Review supporting analysis.",
                provenance_id=fact.provenance_id,
            )
        )
    return capsules


def _is_protected(fact: MemoryFact) -> bool:
    return fact.is_critical or bool(fact.downstream_dependencies or fact.blocks_interpretations or fact.enables_next_steps)


def _budget_view(memory: CarriedMemory) -> dict[str, Any]:
    return {
        "facts": [fact.text for fact in memory.facts],
        "dependency_capsules": [
            {
                "trigger_fact": capsule.trigger_fact,
                "blocked_interpretation": capsule.blocked_interpretation,
                "required_next_step": capsule.required_next_step,
                "provenance_id": capsule.provenance_id,
            }
            for capsule in memory.dependency_capsules
        ],
        "provenance_refs": memory.provenance_refs,
        "memory_mode": memory.memory_mode,
    }


def _budget_size(memory: CarriedMemory) -> int:
    return serialized_size(_budget_view(memory))


def _budget_usage(memory: CarriedMemory) -> dict[str, int]:
    reservations = budget_reservations(max(_budget_size(memory), 1))
    return {
        "critical_and_capsules": serialized_size(
            {
                "critical_facts": [fact.model_dump() for fact in memory.critical_facts],
                "dependency_capsules": [capsule.model_dump() for capsule in memory.dependency_capsules],
            }
        ),
        "warnings_and_blocks": serialized_size({"warnings": [fact.text for fact in memory.warnings], "blocked": memory.blocked_interpretations}),
        "metrics": serialized_size({"dependencies": memory.downstream_dependencies, "next_steps": memory.enables_next_steps}),
        "provenance_and_summaries": serialized_size({"provenance_refs": memory.provenance_refs, "assumptions": memory.assumptions}),
        "reserved_budget_model": reservations,
    }


def _uniq(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
