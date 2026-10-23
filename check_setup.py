"""Check that the simulator and platform-specific planner are ready."""

import os
import platform
import sys
from pathlib import Path

from planner import resolve_fast_downward_script, validate_fast_downward_installation


PROJECT_DIR = Path(__file__).resolve().parent
REQUIRED_FILES = [
    PROJECT_DIR / "main.py",
    PROJECT_DIR / "plans" / "p01.plan",
    PROJECT_DIR / "fast-downward-24.06.1" / "trucks" / "domain.pddl",
    PROJECT_DIR / "fast-downward-24.06.1" / "trucks" / "p01.pddl",
]


def main() -> int:
    print("PDDL Anomaly Simulator Setup Check")
    print(f"Operating system: {platform.system()} {platform.machine()}")
    print(f"Python: {sys.version.split()[0]}")

    files_ok = True
    for path in REQUIRED_FILES:
        if path.is_file():
            print(f"[OK] {path.relative_to(PROJECT_DIR)}")
        else:
            print(f"[MISSING] {path.relative_to(PROJECT_DIR)}")
            files_ok = False

    selected = resolve_fast_downward_script()
    planner_ok, planner_message = validate_fast_downward_installation(selected)
    marker = "OK" if planner_ok else "NOT READY"
    print(f"[{marker}] {planner_message}")

    if not planner_ok and os.name != "nt":
        print(
            "Configure a Mac/Linux build with:\n"
            "  python3 configure_fast_downward.py /path/to/fast-downward.py"
        )

    if files_ok and planner_ok:
        print("\nEverything needed for clean execution and replanning is ready.")
        return 0

    if files_ok:
        print("\nClean plan execution is ready, but replanning still needs setup.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
