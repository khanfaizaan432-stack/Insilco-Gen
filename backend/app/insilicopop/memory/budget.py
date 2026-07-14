from __future__ import annotations

import json
from typing import Any, Literal


RawSizeBucket = Literal["tiny", "small", "medium", "large"]


def serialized_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, default=str))


def raw_size_bucket(size_chars: int) -> RawSizeBucket:
    if size_chars < 1000:
        return "tiny"
    if size_chars < 10000:
        return "small"
    if size_chars < 100000:
        return "medium"
    return "large"


def ratio_context(raw_size_chars: int, compression_ratio: float) -> Literal["normal", "tiny_input_overhead"]:
    if raw_size_chars < 1000 and compression_ratio > 1:
        return "tiny_input_overhead"
    return "normal"


def fact_sort_key(fact: Any) -> tuple[int, float]:
    is_critical = bool(getattr(fact, "is_critical", False))
    has_dependency = bool(getattr(fact, "downstream_dependencies", None) or getattr(fact, "downstream_dependency", None))
    has_block = bool(getattr(fact, "blocks_interpretations", None))
    has_next = bool(getattr(fact, "enables_next_steps", None))
    has_provenance = bool(getattr(fact, "provenance_id", None))
    importance = governor_score(fact)
    priority = (
        5 if is_critical else
        4 if has_block else
        3 if has_dependency else
        2 if has_next else
        1 if has_provenance else
        0
    )
    return (priority, importance)


def governor_score(fact: Any, redundancy_penalty: float = 0.0) -> float:
    importance = float(getattr(fact, "importance_score", 0.0))
    critical_bonus = 0.35 if bool(getattr(fact, "is_critical", False)) else 0.0
    dependency_bonus = 0.20 if bool(getattr(fact, "downstream_dependencies", None) or getattr(fact, "downstream_dependency", None)) else 0.0
    blocking_bonus = 0.25 if bool(getattr(fact, "blocks_interpretations", None)) else 0.0
    next_step_bonus = 0.15 if bool(getattr(fact, "enables_next_steps", None)) else 0.0
    return round(importance + critical_bonus + dependency_bonus + blocking_bonus + next_step_bonus - redundancy_penalty, 4)


def budget_reservations(budget_chars: int) -> dict[str, int]:
    return {
        "critical_and_capsules": int(budget_chars * 0.50),
        "warnings_and_blocks": int(budget_chars * 0.25),
        "metrics": int(budget_chars * 0.15),
        "provenance_and_summaries": max(budget_chars - int(budget_chars * 0.90), 0),
    }


def fits_budget(value: Any, budget_chars: int) -> bool:
    return serialized_size(value) <= budget_chars
