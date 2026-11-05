"""Check that the simulator, its problem files and the platform-specific planner are ready."""

import os
import platform
import sys
from pathlib import Path

from pddl_parser import parse_problem
from planner import fast_downward_status


PROJECT_DIR = Path(__file__).resolve().parent
TRUCKS_DIR = PROJECT_DIR / "fast-downward-24.06.1" / "trucks"
DOMAIN_FILE = TRUCKS_DIR / "domain.pddl"
REQUIRED_FILES = [
    PROJECT_DIR / "main.py",
    PROJECT_DIR / "server.py",
    PROJECT_DIR / "static" / "index.html",
    PROJECT_DIR / "static" / "app.js",
    PROJECT_DIR / "static" / "style.css",
    DOMAIN_FILE,
    TRUCKS_DIR / "p01.pddl",
]


def main() -> int:
    print("PDDL Anomaly Simulator Setup Check")
    print(f"Operating system: {platform.system()} {platform.machine()}")
    print(f"Python: {sys.version.split()[0]}")
    print()

    files_ok = True
    for path in REQUIRED_FILES:
        if path.is_file():
            print(f"[OK] {path.relative_to(PROJECT_DIR)}")
        else:
            print(f"[MISSING] {path.relative_to(PROJECT_DIR)}")
            files_ok = False

    # The extended domain (road distances/speeds) and upgraded problems must match.
    if DOMAIN_FILE.is_file():
        domain_text = DOMAIN_FILE.read_text(encoding="utf-8")
        if "road-span" in domain_text and "drive-instant" in domain_text:
            print("[OK] domain.pddl has road distance/speed support")
        else:
            print("[OLD] domain.pddl is the original Trucks domain (no road distances)")
            files_ok = False

    problems = sorted(p for p in TRUCKS_DIR.glob("*.pddl") if p.name != "domain.pddl")
    not_upgraded = []
    for path in problems:
        try:
            if not any(pred == "road-span" for pred, _ in parse_problem(str(path)).init_facts):
                not_upgraded.append(path.stem)
        except Exception:
            not_upgraded.append(f"{path.stem} (unreadable)")
    if problems and not not_upgraded:
        print(f"[OK] {len(problems)} problem files have road data")
    elif not_upgraded:
        print(f"[OLD] {len(not_upgraded)} problem file(s) without road data: {', '.join(not_upgraded[:8])}"
              + (" ..." if len(not_upgraded) > 8 else ""))
        print("      Fix with: py tools/upgrade_problems.py")
        files_ok = False

    plans = sorted((PROJECT_DIR / "plans").glob("*.plan"))
    print(f"[INFO] {len(plans)} pre-made plan file(s) in plans/")

    status = fast_downward_status()
    planner_ok = bool(status["ok"])
    marker = "OK" if planner_ok else "NOT READY"
    print(f"[{marker}] {status['message']}  (source: {status['source']})")

    if not planner_ok and os.name != "nt":
        print(
            "Configure a Mac/Linux build with:\n"
            "  python3 configure_fast_downward.py /path/to/fast-downward.py"
        )

    try:
        import matplotlib  # noqa: F401
        print("[OK] matplotlib (optional, only for GIF export)")
    except ImportError:
        print("[OPTIONAL] matplotlib not installed; only needed for GIF export")

    print()
    if files_ok and planner_ok:
        print("Ready: load plans, generate plans, and replan after anomalies.")
        print("Start the browser app with:  py server.py   (macOS/Linux: python3 server.py)")
        return 0

    if files_ok:
        print("Ready to LOAD pre-made plans without anomalies.")
        print("Generating plans and replanning after anomalies need Fast Downward (see above).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
