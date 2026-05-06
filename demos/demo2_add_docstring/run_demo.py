#!/usr/bin/env python3
"""
Demo 2: Add Docstrings

Scenario: calculator.py has 5 functions without docstrings.
The agent analyzes them and adds proper docstrings.

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
    work_dir = Path(tempfile.mkdtemp(prefix="codesentry_demo2_"))
    shutil.copytree(demo_dir, work_dir, dirs_exist_ok=True)

    print("=" * 60)
    print("CodeSentry Demo 2: Add Docstrings")
    print("=" * 60)
    print(f"\nWorkspace: {work_dir}")
    print("\n--- BEFORE ---")
    print((work_dir / "calculator.py").read_text(encoding="utf-8"))

    # First, run baseline tests
    print("\n--- BASELINE TESTS ---")
    import subprocess
    result = subprocess.run(
        ["pytest", str(work_dir / "test_calculator.py"), "-v", "--tb=short"],
        capture_output=True, text=True, cwd=str(work_dir),
    )
    print(result.stdout[-500:] if result.stdout else "No output")

    # Run the agent
    print("\n--- AGENT RUNNING ---")
    orch = Orchestrator(workspace_root=str(work_dir))
    result = await orch.run(
        "Add proper docstrings to all functions in calculator.py. "
        "Each docstring should describe what the function does, its parameters, and return value."
    )

    print(f"\n--- RESULT ---")
    print(f"Success: {result.success}")
    print(f"Duration: {result.total_duration_ms:.0f}ms")

    print("\n--- AFTER ---")
    print((work_dir / "calculator.py").read_text(encoding="utf-8"))

    # Run tests again
    print("\n--- POST-CHANGE TESTS ---")
    result2 = subprocess.run(
        ["pytest", str(work_dir / "test_calculator.py"), "-v", "--tb=short"],
        capture_output=True, text=True, cwd=str(work_dir),
    )
    print(result2.stdout[-500:] if result2.stdout else "No output")
    tests_pass = result2.returncode == 0

    print(f"\n[DONE] Demo 2 completed (tests {'pass' if tests_pass else 'fail'})")
    return tests_pass


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
