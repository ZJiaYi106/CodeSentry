#!/usr/bin/env python3
"""
Demo 1: Fix Typo Bug

Scenario: utils.py has two variable name typos (numers → numbers, fist → first).
The agent explores the repo, finds the bugs, and fixes them.

Run:  python run_demo.py
"""

import asyncio
import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from app.agents.orchestrator import Orchestrator
from app.memory.long_term import clear_collection, get_collection_stats


async def main():
    # Prepare workspace (copy demo files to a temp dir so the agent can modify them)
    demo_dir = Path(__file__).parent / "workspace"
    work_dir = Path(tempfile.mkdtemp(prefix="codesentry_demo1_"))
    shutil.copytree(demo_dir, work_dir, dirs_exist_ok=True)

    print("=" * 60)
    print("CodeSentry Demo 1: Fix Typo Bug")
    print("=" * 60)
    print(f"\nWorkspace: {work_dir}")
    print("\n--- BEFORE ---")
    print((work_dir / "utils.py").read_text(encoding="utf-8"))

    # Run the agent
    print("\n--- AGENT RUNNING ---")
    orch = Orchestrator(workspace_root=str(work_dir))
    result = await orch.run("Fix the variable name typos in utils.py")

    print(f"\n--- RESULT ---")
    print(f"Success: {result.success}")
    print(f"Duration: {result.total_duration_ms:.0f}ms")
    print(f"Phases: {[p['phase'] for p in result.phases]}")

    print("\n--- AFTER ---")
    print((work_dir / "utils.py").read_text(encoding="utf-8"))

    # Check memory stats
    stats = await get_collection_stats()
    print(f"\n--- MEMORY ---")
    for name, count in stats.items():
        print(f"  {name}: {count} entries")

    # Report
    print(f"\n[DONE] Demo 1 completed (success={result.success})")
    return result.success


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
