import json
import subprocess
import sys
from pathlib import Path

from app.insilicopop.benchmarks.runner import MemoryBenchmarkRunner


def test_benchmark_history_jsonl_created(tmp_path):
    result = MemoryBenchmarkRunner(generated_root=tmp_path).run("admixture_underfit", 1000)
    history_path = Path(result["generated_files"]["benchmark_history"]["absolute_path"])

    assert history_path.exists()
    rows = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines()]
    assert rows
    assert {"method", "compression_ratio", "final_score"} <= set(rows[0])


def test_benchmark_history_cli_prints_recent_rows():
    subprocess.run(
        [sys.executable, "-m", "app.insilicopop.cli", "benchmark-memory", "--scenario", "admixture_underfit"],
        cwd="backend",
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "app.insilicopop.cli", "benchmark-history", "--last", "5"],
        cwd="backend",
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0
    assert "run_id | scenario | method" in result.stdout
    assert "compression_ratio" in result.stdout
