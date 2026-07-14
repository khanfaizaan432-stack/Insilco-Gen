from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> int:
    commands = [
        [sys.executable, "-m", "pytest", "backend"],
        [
            sys.executable,
            "-m",
            "app.insilicopop.cli",
            "audit",
            "--metadata",
            "examples/indian_metadata.csv",
            "--pca",
            "examples/pca_results.csv",
            "--admixture",
            "examples/admixture_cv_errors.csv",
            "--fst",
            "examples/fst_matrix.csv",
            "--roh",
            "examples/roh_summary.csv",
            "--selection",
            "examples/selection_scan_results.csv",
            "--query",
            "selection is proven",
        ],
        [
            sys.executable,
            "-m",
            "app.insilicopop.cli",
            "agent-run",
            "--query",
            "selection is proven",
            "--metadata",
            "examples/indian_metadata.csv",
            "--pca",
            "examples/pca_results.csv",
            "--admixture",
            "examples/admixture_cv_errors.csv",
            "--fst",
            "examples/fst_matrix.csv",
            "--roh",
            "examples/roh_summary.csv",
            "--selection",
            "examples/selection_scan_results.csv",
            "--memory-budget-chars",
            "1500",
            "--memory-mode",
            "compact",
        ],
        [sys.executable, "-m", "app.insilicopop.cli", "benchmark-memory", "--scenario", "admixture_underfit"],
        [sys.executable, "-m", "app.insilicopop.cli", "benchmark-agent-memory", "--scenario", "all", "--budget-chars", "1500", "--memory-mode", "compact"],
    ]
    for command in commands:
        cwd = ROOT if command[2:4] == ["pytest", "backend"] else BACKEND
        print(f"RUN {' '.join(command)}")
        subprocess.run(command, cwd=cwd, check=True)
    print("PRE_TAR_CHECK_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
