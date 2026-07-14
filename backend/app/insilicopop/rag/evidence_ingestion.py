from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


ALLOWED_GUIDANCE_SUFFIXES = {".txt", ".md", ".markdown", ".json"}
RAW_GENOMIC_SUFFIXES = {
    ".vcf",
    ".vcf.gz",
    ".bam",
    ".cram",
    ".fastq",
    ".fq",
    ".bed",
    ".bim",
    ".fam",
    ".pgen",
    ".pvar",
    ".psam",
    ".ped",
    ".map",
}


class EvidenceSourceDocument(BaseModel):
    source_id: str
    title: str
    text: str
    evidence_type: str = "internal_guidance"
    source_path: str | None = None
    allowlisted: bool = True
    local_only: bool = True
    external_call_made: bool = False
    raw_data_ingested: bool = False
    human_review_required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


def guidance_document_from_corpus_item(item: dict[str, object]) -> EvidenceSourceDocument:
    terms = [str(term) for term in item.get("terms", [])]
    text = " ".join([str(item.get("title", "")), str(item.get("snippet", "")), *terms]).strip()
    return EvidenceSourceDocument(
        source_id=str(item["source_id"]),
        title=str(item["title"]),
        text=text,
        evidence_type=str(item.get("source_type", "internal_guidance")),
        metadata={"terms": terms},
    )


def validate_guidance_path(path: str | Path) -> Path:
    candidate = Path(path)
    suffix = _compound_suffix(candidate.name)
    if suffix in RAW_GENOMIC_SUFFIXES:
        raise ValueError("Raw genomic files are not allowed in the local evidence store.")
    if candidate.is_dir():
        raise ValueError("Recursive directory ingestion is disabled for the local evidence store.")
    if suffix not in ALLOWED_GUIDANCE_SUFFIXES:
        raise ValueError("Only allowlisted text, markdown, and JSON guidance documents can be ingested.")
    return candidate


def build_guidance_document_from_text(
    *,
    source_id: str,
    title: str,
    text: str,
    source_path: str | Path | None = None,
    evidence_type: str = "local_guidance",
) -> EvidenceSourceDocument:
    if source_path is not None:
        validate_guidance_path(source_path)
    if not text.strip():
        raise ValueError("Evidence guidance document text cannot be empty.")
    return EvidenceSourceDocument(
        source_id=source_id,
        title=title,
        text=text,
        source_path=str(source_path) if source_path is not None else None,
        evidence_type=evidence_type,
    )


def _compound_suffix(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith(".vcf.gz"):
        return ".vcf.gz"
    return Path(lowered).suffix
