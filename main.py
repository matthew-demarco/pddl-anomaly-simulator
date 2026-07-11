"""
Trucks Domain — Anomaly Replanning Simulator
=============================================

Main entry point. Simulates truck plan execution with random anomaly
injection and automated replanning via Case-Based Reasoning.

Usage:
    python main.py --problem p01 [--anomaly-chance 0.2] [--seed 42] [--verbose]
    python main.py --list          # List available problems
    python main.py --help
"""

import argparse
import sys
from pathlib import Path

from simulator import Simulator


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent
TRUCKS_DIR = PROJECT_DIR / "fast-downward-24.06.1" / "trucks"
DOMAIN_FILE = TRUCKS_DIR / "domain.pddl"


def get_problem_path(problem_id: str) -> Path:
    """Resolve a problem ID like 'p01' or '1' to a full path."""
    # Accept 'p01', 'p1', '1', '01', etc.
    problem_id = problem_id.strip().lower()
    if not problem_id.startswith('p'):
        # Pad with leading zero if single digit
        try:
            num = int(problem_id)
            problem_id = f"p{num:02d}"
        except ValueError:
            pass

    filename = f"{problem_id}.pddl"
    path = TRUCKS_DIR / filename
    return path


def list_problems():
    """List all available truck problem files."""
    problems = sorted(TRUCKS_DIR.glob("p*.pddl"))
    print(f"\nAvailable problems in {TRUCKS_DIR}:\n")
    for p in problems:
        # Quick peek at object counts
        text = p.read_text(encoding='utf-8')
        trucks = text.count(" - truck")
        packages = text.count(" - package")
        locations = text.count(" - location")
        print(f"  {p.stem:6s}  |  {trucks} truck(s), {packages} packages, {locations} locations")
    print(f"\nTotal: {len(problems)} problems")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Trucks Domain — Anomaly Replanning Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --problem p01                  # Run p01 with default settings
  python main.py --problem p01 --no-anomalies   # Run p01 without anomalies
  python main.py --problem 3 --seed 42          # Run p03 with fixed seed
  python main.py --problem p07 --anomaly-chance 0.5
  python main.py --list                         # List available problems
        """,
    )

    parser.add_argument(
        "--problem", "-p",
        type=str,
        help="Problem ID (e.g., 'p01', '1', '03')",
    )
    parser.add_argument(
        "--anomaly-chance", "-a",
        type=float,
        default=0.2,
        help="Probability of anomaly per drive action (0.0-1.0, default: 0.2)",
    )
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--no-anomalies",
        action="store_true",
        help="Run without any anomalies (clean execution)",
    )
    parser.add_argument(
        "--max-anomalies",
        type=int,
        default=5,
        help="Maximum number of anomalies per run (default: 5)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=True,
        help="Show detailed state after each action (default: True)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress verbose output",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available problem files",
    )
    parser.add_argument(
        "--search",
        type=str,
        default="eager_greedy([ff()])",
        help="Fast Downward search strategy (e.g., eager_greedy([ff()]), astar(blind()))",
    )
    parser.add_argument(
        "--export-states",
        type=str,
        default=None,
        help="Directory to save the state of each problem step (e.g. 'state_history')",
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Emit JSON state dynamically for UI parsing",
    )

    args = parser.parse_args()

    if args.list:
        list_problems()
        return

    if not args.problem:
        parser.print_help()
        print("\nError: --problem is required (e.g., --problem p01)")
        sys.exit(1)

    # Resolve paths
    problem_path = get_problem_path(args.problem)
    if not problem_path.exists():
        print(f"Error: Problem file not found: {problem_path}")
        sys.exit(1)

    if not DOMAIN_FILE.exists():
        print(f"Error: Domain file not found: {DOMAIN_FILE}")
        sys.exit(1)

    # Configure
    anomaly_chance = 0.0 if args.no_anomalies else args.anomaly_chance
    verbose = not args.quiet

    # Run simulation
    sim = Simulator(
        domain_path=str(DOMAIN_FILE),
        problem_path=str(problem_path),
        anomaly_chance=anomaly_chance,
        seed=args.seed,
        verbose=verbose,
        max_anomalies=args.max_anomalies,
        search=args.search,
        export_states_dir=args.export_states,
        json_output=args.json_output,
    )

    result = sim.run()

    # Exit code
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
