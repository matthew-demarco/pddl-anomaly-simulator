"""
Trucks Domain — Anomaly Replanning Simulator
=============================================

Main entry point. Executes an externally generated plan with user-selected
anomaly and step IDs, then replans via Case-Based Reasoning.

Usage:
    python main.py --problem p01 --plan plans/p01.plan
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


ANOMALY_IDS = {
    "1": "road_closure",
    "2": "truck_breakdown",
    "3": "new_delivery",
    "4": "deadline_change",
    "road_closure": "road_closure",
    "truck_breakdown": "truck_breakdown",
    "new_delivery": "new_delivery",
    "deadline_change": "deadline_change",
}


def build_id_anomaly(
    anomaly_id: str,
    step_id: int,
    anomaly_args: list[str],
) -> ScheduledAnomaly:
    """Build a scheduled anomaly from separate anomaly and step IDs."""
    normalized_id = anomaly_id.strip().lower().replace("-", "_")
    anomaly_name = ANOMALY_IDS.get(normalized_id)
    if anomaly_name is None:
        raise argparse.ArgumentTypeError(
            "Unknown anomaly ID. Use 1-4 or an anomaly name."
        )

    expected_args = {
        "road_closure": 2,
        "truck_breakdown": 1,
        "new_delivery": 3,
        "deadline_change": 2,
    }
    expected = expected_args[anomaly_name]
    if len(anomaly_args) != expected:
        labels = {
            "road_closure": "FROM TO",
            "truck_breakdown": "TRUCK",
            "new_delivery": "PACKAGE ORIGIN DESTINATION",
            "deadline_change": "PACKAGE NEW_DEADLINE",
        }
        raise argparse.ArgumentTypeError(
            f"Anomaly {anomaly_id} requires --anomaly-args "
            f"{labels[anomaly_name]}."
        )

    combined = ":".join([anomaly_name, str(step_id), *anomaly_args])
    return parse_manual_anomaly(combined)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Trucks Domain — Anomaly Replanning Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --problem p01 --plan plans/p01.plan
  python main.py --problem p01 --plan plans/p01.plan --anomaly-id 1 --step-id 3 --anomaly-args l1 l3
  python main.py --problem p01 --plan plans/p01.plan --anomaly road_closure:3:l1:l3
  python main.py --list                         # List available problems
        """,
    )

    parser.add_argument(
        "--problem", "-p",
        type=str,
        help="Problem ID (e.g., 'p01', '1', '03')",
    )
    parser.add_argument(
        "--plan",
        type=str,
        help="Path to an externally generated Fast Downward plan file",
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
        "--anomaly-id",
        type=str,
        help=(
            "Anomaly ID: 1=road closure, 2=truck breakdown, "
            "3=new delivery, 4=deadline change (names also accepted)"
        ),
    )
    parser.add_argument(
        "--step-id",
        type=int,
        help="Execution step ID at which the selected anomaly occurs",
    )
    parser.add_argument(
        "--anomaly-args",
        nargs="*",
        default=[],
        metavar="VALUE",
        help="Objects used by --anomaly-id (road, truck, package, etc.)",
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
        "--fast-downward",
        type=str,
        default=None,
        help=(
            "Optional one-run override path to fast-downward.py. macOS/Linux "
            "users can save this once with configure_fast_downward.py."
        ),
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

    if not args.plan:
        parser.error("--plan is required (the simulator no longer generates the initial plan)")

    # Resolve paths
    problem_path = get_problem_path(args.problem)
    if not problem_path.exists():
        print(f"Error: Problem file not found: {problem_path}")
        sys.exit(1)

    if not DOMAIN_FILE.exists():
        print(f"Error: Domain file not found: {DOMAIN_FILE}")
        sys.exit(1)

    plan_path = Path(args.plan).expanduser().resolve()
    if not plan_path.is_file():
        print(f"Error: Plan file not found: {plan_path}")
        sys.exit(1)

    has_anomaly_id = args.anomaly_id is not None
    has_step_id = args.step_id is not None
    if has_anomaly_id != has_step_id:
        parser.error("--anomaly-id and --step-id must be supplied together")
    if args.anomaly_args and not has_anomaly_id:
        parser.error("--anomaly-args requires --anomaly-id and --step-id")
    if has_step_id and args.step_id < 1:
        parser.error("--step-id must be 1 or greater")
    if has_anomaly_id and args.anomaly:
        parser.error("Use either --anomaly-id/--step-id or --anomaly, not both")

    scheduled_anomalies = list(args.anomaly)
    if has_anomaly_id:
        try:
            scheduled_anomalies.append(
                build_id_anomaly(args.anomaly_id, args.step_id, args.anomaly_args)
            )
        except argparse.ArgumentTypeError as error:
            parser.error(str(error))

    scheduled_steps = [item.step for item in scheduled_anomalies]
    if len(scheduled_steps) != len(set(scheduled_steps)):
        parser.error("Only one anomaly may be scheduled at each step ID")

    fast_downward_script = None
    if args.fast_downward:
        candidate = Path(args.fast_downward).expanduser().resolve()
        if candidate.is_dir():
            candidate = candidate / "fast-downward.py"
        if not candidate.is_file():
            parser.error(f"Fast Downward script not found: {candidate}")
        fast_downward_script = str(candidate)

    # Configure
    verbose = not args.quiet
   

    sim = Simulator(
        domain_path=str(DOMAIN_FILE),
        problem_path=str(problem_path),
        plan_path=str(plan_path),
        verbose=verbose,
        scheduled_anomalies=scheduled_anomalies,
        search=args.search,
        fast_downward_script=fast_downward_script,
        export_states_dir=args.export_states,
        json_output=args.json_output,
    )

    result = sim.run()

    # Exit code
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
