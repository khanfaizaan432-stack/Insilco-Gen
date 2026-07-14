from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class HpoTerm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hpo_id: str = Field(pattern=r"^HP:\d{7}$")
    canonical_label: str = Field(min_length=1, max_length=160)
    synonyms: tuple[str, ...] = Field(default_factory=tuple, max_length=10)


class LocalHpoRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_version: str
    source: str
    terms: tuple[HpoTerm, ...]

    def resolve(self, hpo_id: str) -> HpoTerm | None:
        return next((term for term in self.terms if term.hpo_id == hpo_id), None)


@lru_cache(maxsize=1)
def load_hpo_registry() -> LocalHpoRegistry:
    path = Path(__file__).resolve().parent / "data" / "hpo_terms_v028.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    registry = LocalHpoRegistry.model_validate(payload)
    stable_terms = tuple(sorted(registry.terms, key=lambda item: item.hpo_id))
    return registry.model_copy(update={"terms": stable_terms})
