from __future__ import annotations

from app.schemas.memory import MemoryCompressResponse


def memory_response_to_report(response: MemoryCompressResponse) -> dict[str, object]:
    return response.model_dump()
