"""
Fast Downward Planner Integration.

Invokes Fast Downward to solve a PDDL problem and parses the resulting plan.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from state import PlanAction


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Path to the fast-downward directory (relative to this file's location)
_THIS_DIR = Path(__file__).resolve().parent
FAST_DOWNWARD_DIR = _THIS_DIR / "fast-downward-24.06.1"
FAST_DOWNWARD_SCRIPT = FAST_DOWNWARD_DIR / "fast-downward.py"


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------

def parse_plan(plan_path: str) -> List[PlanAction]:
    """
    Parse a sas_plan file into a list of PlanAction objects.

    Each line looks like: (drive truck1 l3 l2 t0 t1)
    Comment lines starting with ';' are ignored.
    """
    actions = []
    text = Path(plan_path).read_text(encoding='utf-8')
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith(';'):
            continue
        # Remove surrounding parens
        inner = line.strip('()')
        tokens = inner.split()
        if tokens:
            actions.append(PlanAction(name=tokens[0], args=tokens[1:]))
    return actions


# ---------------------------------------------------------------------------
# Fast Downward invocation
# ---------------------------------------------------------------------------

def run_fast_downward(
    domain_path: str,
    problem_path: str,
    search: str = "eager_greedy([ff()])",
    timeout: int = 120,
    plan_file: Optional[str] = None,
) -> Optional[List[PlanAction]]:
    """
    Run Fast Downward on the given domain and problem files.

    Args:
        domain_path: Path to the domain PDDL file.
        problem_path: Path to the problem PDDL file.
        search: Search algorithm string for Fast Downward.
        timeout: Maximum time in seconds.
        plan_file: Optional explicit path for the plan output file.

    Returns:
        List of PlanAction objects if a plan was found, None otherwise.
    """
    # Find the Python interpreter
    python_exe = sys.executable or "python"

    # Resolve all paths to absolute (FD runs with a different cwd)
    domain_abs = str(Path(domain_path).resolve())
    problem_abs = str(Path(problem_path).resolve())
    plan_abs = str(Path(plan_file).resolve()) if plan_file else str(FAST_DOWNWARD_DIR / "sas_plan")

    # Build the command
    cmd = [
        python_exe,
        str(FAST_DOWNWARD_SCRIPT),
        "--plan-file", plan_abs,
        domain_abs,
        problem_abs,
        "--search", search,
    ]

    print(f"  [Planner] Running Fast Downward...")
    print(f"  [Planner] Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(FAST_DOWNWARD_DIR),
        )

        # Fast Downward exit codes:
        # 0  = solution found
        # 12 = no solution (unsolvable)
        # Other = error
        if result.returncode in (0,):
            if Path(plan_abs).exists():
                actions = parse_plan(plan_abs)
                print(f"  [Planner] Plan found with {len(actions)} actions.")
                return actions
            else:
                print(f"  [Planner] Plan file not found at {plan_abs}")
                return None
        else:
            # Check if a plan was still generated despite non-zero exit
            if Path(plan_abs).exists():
                actions = parse_plan(plan_abs)
                if actions:
                    print(f"  [Planner] Plan found with {len(actions)} actions (exit code {result.returncode}).")
                    return actions

            print(f"  [Planner] Fast Downward failed (exit code {result.returncode}).")
            if result.stderr:
                # Only print last few lines of stderr
                err_lines = result.stderr.strip().split('\n')
                for line in err_lines[-5:]:
                    print(f"  [Planner] {line}")
            return None

    except subprocess.TimeoutExpired:
        print(f"  [Planner] Fast Downward timed out after {timeout}s.")
        return None
    except FileNotFoundError as e:
        print(f"  [Planner] Could not find Fast Downward: {e}")
        return None


def cleanup_planner_files():
    """Remove temporary files left by Fast Downward."""
    for fname in ["output.sas", "output", "sas_plan"]:
        fpath = FAST_DOWNWARD_DIR / fname
        if fpath.exists():
            try:
                fpath.unlink()
            except OSError:
                pass
