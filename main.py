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
from anomalies import AnomalyType, ScheduledAnomaly

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

def parse_manual_anomaly(value: str) -> ScheduledAnomaly:
    """
    Convert command-line anomaly text into a ScheduledAnomaly.

    Formats:
        road_closure:STEP:FROM:TO
        truck_breakdown:STEP:TRUCK
        new_delivery:STEP:PACKAGE:ORIGIN:DESTINATION
        deadline_change:STEP:PACKAGE:NEW_DEADLINE
    """

    parts = [part.strip() for part in value.split(":")]

    if len(parts) < 2:
        raise argparse.ArgumentTypeError(
            "Anomaly must include a type and step."
        )

    anomaly_name = parts[0].lower()

    try:
        step = int(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid anomaly step: {parts[1]}"
        )

    if step < 1:
        raise argparse.ArgumentTypeError(
            "Anomaly step must be 1 or greater."
        )

    if anomaly_name == "road_closure":
        if len(parts) != 4:
            raise argparse.ArgumentTypeError(
                "Use road_closure:STEP:FROM:TO"
            )

        return ScheduledAnomaly(
            step=step,
            anomaly_type=AnomalyType.ROAD_CLOSURE,
            details={
                "from": parts[2],
                "to": parts[3],
            },
        )

    if anomaly_name == "truck_breakdown":
        if len(parts) != 3:
            raise argparse.ArgumentTypeError(
                "Use truck_breakdown:STEP:TRUCK"
            )

        return ScheduledAnomaly(
            step=step,
            anomaly_type=AnomalyType.TRUCK_BREAKDOWN,
            details={
                "truck": parts[2],
            },
        )

    if anomaly_name == "new_delivery":
        if len(parts) != 5:
            raise argparse.ArgumentTypeError(
                "Use new_delivery:STEP:PACKAGE:ORIGIN:DESTINATION"
            )

        return ScheduledAnomaly(
            step=step,
            anomaly_type=AnomalyType.NEW_DELIVERY,
            details={
                "package": parts[2],
                "origin": parts[3],
                "destination": parts[4],
            },
        )

    if anomaly_name == "deadline_change":
        if len(parts) != 4:
            raise argparse.ArgumentTypeError(
                "Use deadline_change:STEP:PACKAGE:NEW_DEADLINE"
            )

        return ScheduledAnomaly(
            step=step,
            anomaly_type=AnomalyType.DEADLINE_CHANGE,
            details={
                "package": parts[2],
                "new_deadline": parts[3],
            },
        )

    raise argparse.ArgumentTypeError(
        f"Unknown anomaly type: {anomaly_name}"
    )

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
        "--anomaly",
        action="append",
        type=parse_manual_anomaly,
        default=[],
        help=(
        "Schedule a manual anomaly. May be used more than once. "
        "Example: road_closure:3:l2:l3"
    ),
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
   

    sim = Simulator(
        domain_path=str(DOMAIN_FILE),
        problem_path=str(problem_path),
        anomaly_chance=anomaly_chance,
        seed=args.seed,
        verbose=verbose,
        max_anomalies=args.max_anomalies,
        scheduled_anomalies=args.anomaly,
        search=args.search,
        export_states_dir=args.export_states,
        json_output=args.json_output,
    )

    result = sim.run()

    # Exit code
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
