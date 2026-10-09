"""
visualize_live.py

Runs the trucks simulator *in-process* and visualizes the result directly
from Simulator.state_history — no subprocess, no stdout scraping, no
intermediate JSON file. Replaces the run_and_parse.py + visualize_run.py
two-step pipeline with a single direct call.

Usage:
    python3 visualize_live.py --problem p01 --no-anomalies --save run_p01.gif
    python3 visualize_live.py --problem p01 --anomaly road_closure:3:l2:l3 --show
"""

import argparse
import sys

import matplotlib.pyplot as plt
import matplotlib.animation as animation

from simulator import get_run_snapshots
from visualize_run import build_animation

# Reuse main.py's existing path resolution and anomaly-string parsing so
# --problem p01 / --anomaly road_closure:3:l2:l3 behave identically to the CLI.
from main import get_problem_path, parse_manual_anomaly, DOMAIN_FILE


def main():
    parser = argparse.ArgumentParser(
        description="Run the trucks simulator and visualize it directly (no subprocess)."
    )
    parser.add_argument("--problem", "-p", required=True, help="Problem ID (e.g. p01)")
    parser.add_argument("--anomaly-chance", "-a", type=float, default=0.2)
    parser.add_argument("--seed", "-s", type=int, default=None)
    parser.add_argument("--no-anomalies", action="store_true")
    parser.add_argument("--max-anomalies", type=int, default=5)
    parser.add_argument(
        "--anomaly", action="append", type=parse_manual_anomaly, default=[],
        help="Schedule a manual anomaly, e.g. road_closure:3:l2:l3 (repeatable)",
    )
    parser.add_argument("--search", default="eager_greedy([ff()])")
    parser.add_argument("--save", default=None, help="Save animation to this path (.gif or .mp4)")
    parser.add_argument("--show", action="store_true", help="Open an interactive window")
    parser.add_argument("--interval-ms", type=int, default=900)
    args = parser.parse_args()

    problem_path = get_problem_path(args.problem)
    if not problem_path.exists():
        print(f"Error: Problem file not found: {problem_path}")
        sys.exit(1)

    anomaly_chance = 0.0 if args.no_anomalies else args.anomaly_chance

    run = get_run_snapshots(
        domain_path=str(DOMAIN_FILE),
        problem_path=str(problem_path),
        anomaly_chance=anomaly_chance,
        seed=args.seed,
        verbose=False,
        max_anomalies=args.max_anomalies,
        scheduled_anomalies=args.anomaly,
        search=args.search,
        json_output=False,  # not needed -- we read sim.state_history directly
    )

    summary = run["summary"]
    print(
        f"[visualize_live] status={summary['status']} "
        f"snapshots={len(run['snapshots'])} "
        f"replans={summary['replans_triggered']} "
        f"anomalies={len(summary['anomalies'])}"
    )
    if summary["status"] != "SUCCESS":
        print(f"[visualize_live] failure_reason: {summary['failure_reason']}")

    fig, anim = build_animation(run, interval_ms=args.interval_ms)

    fps = max(1, 1000 // args.interval_ms)
    if args.save:
        writer = animation.PillowWriter(fps=fps) if args.save.endswith(".gif") else "ffmpeg"
        anim.save(args.save, writer=writer)
        print(f"[visualize_live] Saved animation to {args.save}")

    if args.show:
        plt.show()

    if not args.save and not args.show:
        out_path = f"{args.problem}_animation.gif"
        anim.save(out_path, writer=animation.PillowWriter(fps=fps))
        print(f"[visualize_live] Saved animation to {out_path}")


if __name__ == "__main__":
    main()