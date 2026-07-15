from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from types import MappingProxyType


REFERENCE_WINDOW_REGISTRY_VERSION = "insilicopop-reference-windows-0.30.1"
SYNTHETIC_REFERENCE_SOURCE_ID = "ISP-REF-WINDOW-0001"


@dataclass(frozen=True)
class PinnedReferenceWindow:
    reference_source_id: str
    accession: str
    accession_version: str
    genome_build: str
    contig: str
    window_start_zero_based: int
    window_end_zero_based: int
    coordinate_system: str
    sequence: str
    sequence_sha256: str
    registry_version: str
    provenance_source_id: str
    fixture_only: bool = True

    @property
    def versioned_accession(self) -> str:
        return f"{self.accession}.{self.accession_version}"

    def identity_payload(self) -> dict[str, str | int | bool]:
        return {
            "reference_source_id": self.reference_source_id,
            "accession": self.accession,
            "accession_version": self.accession_version,
            "versioned_accession": self.versioned_accession,
            "genome_build": self.genome_build,
            "contig": self.contig,
            "window_start_zero_based": self.window_start_zero_based,
            "window_end_zero_based": self.window_end_zero_based,
            "coordinate_system": self.coordinate_system,
            "sequence_sha256": self.sequence_sha256,
            "registry_version": self.registry_version,
            "provenance_source_id": self.provenance_source_id,
            "fixture_only": self.fixture_only,
        }


def _digest(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


_SYNTHETIC_SEQUENCE = "AAAAACCCCCGGGGGTTTTT"
_WINDOWS = MappingProxyType(
    {
        SYNTHETIC_REFERENCE_SOURCE_ID: PinnedReferenceWindow(
            reference_source_id=SYNTHETIC_REFERENCE_SOURCE_ID,
            accession="ISP_TESTREF",
            accession_version="1",
            genome_build="InSilicoPopSynthetic-0.30",
            contig="TEST1",
            window_start_zero_based=0,
            window_end_zero_based=len(_SYNTHETIC_SEQUENCE),
            coordinate_system="zero_based_half_open",
            sequence=_SYNTHETIC_SEQUENCE,
            sequence_sha256=_digest(_SYNTHETIC_SEQUENCE),
            registry_version=REFERENCE_WINDOW_REGISTRY_VERSION,
            provenance_source_id="INSILICOPOP_V030_SYNTHETIC_FIXTURE",
            fixture_only=True,
        )
    }
)


def resolve_reference_window(reference_source_id: str | None) -> PinnedReferenceWindow | None:
    if not reference_source_id:
        return None
    window = _WINDOWS.get(reference_source_id)
    if window is None:
        return None
    if window.registry_version != REFERENCE_WINDOW_REGISTRY_VERSION:
        return None
    if window.coordinate_system != "zero_based_half_open":
        return None
    if window.window_end_zero_based - window.window_start_zero_based != len(window.sequence):
        return None
    if _digest(window.sequence) != window.sequence_sha256:
        return None
    return window


def clone_reference_window(window: PinnedReferenceWindow, **updates: object) -> PinnedReferenceWindow:
    """Return a modified immutable window for deterministic identity tests only."""
    return replace(window, **updates)
