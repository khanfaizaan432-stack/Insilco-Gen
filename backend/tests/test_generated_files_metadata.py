import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_generated_files_include_metadata_and_non_empty_trace():
    response = client.post(
        "/insilicopop/audit",
        files={"metadata_file": ("metadata.csv", b"sample_id,population\nS1,North Indian\n", "text/csv")},
    )

    files = response.json()["generated_files"]
    for metadata in files.values():
        assert metadata["filename"]
        assert metadata["file_type"]
        assert metadata["created"] is True
        assert Path(metadata["absolute_path"]).exists()

    trace = json.loads(Path(files["provenance_trace"]["absolute_path"]).read_text(encoding="utf-8"))
    assert trace
