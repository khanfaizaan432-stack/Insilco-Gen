from __future__ import annotations

import hashlib
from typing import Any


def provenance_id(source_step: str, rule_id: str | None, text: str) -> str:
    seed = f"{source_step}|{rule_id or 'fact'}|{text}".encode("utf-8")
    return "prov_" + hashlib.sha1(seed).hexdigest()[:10]


def build_fact_provenance_index(raw_output: Any, source_step: str) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_output, dict):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for finding in raw_output.get("findings", []) or []:
        if not isinstance(finding, dict):
            continue
        provenance = finding.get("provenance") or {}
        rule_id = provenance.get("rule_id") or finding.get("code")
        pid = provenance_id(source_step, rule_id, finding.get("message", ""))
        index[pid] = provenance or {
            "source_file": source_step,
            "auditor_name": "DomainMemoryCompressor",
            "rule_id": rule_id,
            "evidence_value": finding.get("message", ""),
        }
    return index


def compact_provenance_ref(source_step: str, rule_id: str | None, text: str) -> str:
    return provenance_id(source_step, rule_id, text)
