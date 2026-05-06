#!/usr/bin/env python3
"""
Demo 3: Refactor Long Function

Scenario: data_processor.py has a long process_user_data() that does validation,
statistics, and result building in one function. The agent refactors it into
smaller helper functions.

Run:  python run_demo.py
"""

import asyncio
import os
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from app.agents.orchestrator import Orchestrator
from app.memory.long_term import get_collection_stats


async def main():
    demo_dir = Path(__file__).parent / "workspace"
    work_dir = Path(tempfile.mkdtemp(prefix="codesentry_demo3_"))
    shutil.copytree(demo_dir, work_dir, dirs_exist_ok=True)

    print("=" * 60)
    print("CodeSentry Demo 3: Refactor Long Function")
    print("=" * 60)
    print(f"\nWorkspace: {work_dir}")
    print(f"\nOriginal file: {len((work_dir / 'data_processor.py').read_text(encoding='utf-8').splitlines())} lines")

    # Run baseline tests
    print("\n--- BASELINE TESTS ---")
    import subprocess
    result = subprocess.run(
        ["pytest", str(work_dir / "test_data_processor.py"), "-v", "--tb=short"],
        capture_output=True, text=True, cwd=str(work_dir),
    )
    print(result.stdout[-500:] if result.stdout else "No output")
    baseline_pass = result.returncode == 0
    print(f"Baseline tests: {'PASS' if baseline_pass else 'FAIL'}")

    # Run the agent
    print("\n--- AGENT RUNNING ---")
    orch = Orchestrator(workspace_root=str(work_dir))
    result = await orch.run(
        "Refactor process_user_data() in data_processor.py. "
        "Extract the validation logic, statistics calculation, and result building "
        "into separate smaller helper functions. Keep all existing functionality and tests passing."
    )

    print(f"\n--- RESULT ---")
    print(f"Success: {result.success}")
    print(f"Duration: {result.total_duration_ms:.0f}ms")

    print(f"\nRefactored file: {len((work_dir / 'data_processor.py').read_text(encoding='utf-8').splitlines())} lines")
    print("\n--- AFTER (first 60 lines) ---")
    lines = (work_dir / "data_processor.py").read_text(encoding="utf-8").splitlines()
    for line in lines[:60]:
        print(line)

    # Run tests after refactor
    print("\n--- POST-CHANGE TESTS ---")
    result2 = subprocess.run(
        ["pytest", str(work_dir / "test_data_processor.py"), "-v", "--tb=short"],
        capture_output=True, text=True, cwd=str(work_dir),
    )
    print(result2.stdout[-500:] if result2.stdout else "No output")
    tests_pass = result2.returncode == 0

    print(f"\n[DONE] Demo 3 completed (tests {'pass' if tests_pass else 'fail'})")
    return tests_pass


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
