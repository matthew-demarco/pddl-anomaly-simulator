"""
Generate the pre-made plan files in plans/ with Fast Downward.

Run this after upgrading the problems (tools/upgrade_problems.py): plans made
for the original problems no longer match the new road travel times.

Usage:
    py tools/make_plans.py               # every problem
    py tools/make_plans.py p01 p05       # only these
    py tools/make_plans.py --missing     # only problems that have no plan yet
"""

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from planner import fast_downward_status, run_fast_downward  # noqa: E402

TRUCKS_DIR = PROJECT_DIR / "fast-downward-24.06.1" / "trucks"
DOMAIN_FILE = TRUCKS_DIR / "domain.pddl"
PLANS_DIR = PROJECT_DIR / "plans"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("problems", nargs="*", help="Problem IDs such as p01 (default: all)")
    parser.add_argument("--missing", action="store_true", help="Skip problems that already have a plan")
    parser.add_argument("--search", default="lazy_greedy([ff()],preferred=[ff()])", help="Fast Downward search string")
    parser.add_argument("--timeout", type=int, default=300, help="Seconds allowed per problem")
    args = parser.parse_args()

    status = fast_downward_status()
    if not status["ok"]:
        print(f"Fast Downward is not ready: {status['message']}")
        return 1

    if args.problems:
        paths = [TRUCKS_DIR / (p if p.endswith(".pddl") else f"{p}.pddl") for p in args.problems]
    else:
        paths = sorted(p for p in TRUCKS_DIR.glob("*.pddl") if p.name != "domain.pddl")

    PLANS_DIR.mkdir(exist_ok=True)
    made, failed = 0, []

    for path in paths:
        target = PLANS_DIR / f"{path.stem}.plan"
        if not path.is_file():
            print(f"[MISSING] {path.name}")
            failed.append(path.stem)
            continue
        if args.missing and target.is_file():
            print(f"[SKIP] {target.name} already exists")
            continue

        print(f"[...] {path.stem}", flush=True)
        plan = run_fast_downward(str(DOMAIN_FILE), str(path), search=args.search,
                                 timeout=args.timeout, plan_file=str(target))
        if plan:
            print(f"[OK] {target.relative_to(PROJECT_DIR)}: {len(plan)} actions")
            made += 1
        else:
            print(f"[FAILED] {path.stem}: no plan (see the [Planner] lines above)")
            failed.append(path.stem)

    print(f"\nMade {made} plan(s)." + (f" Failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
