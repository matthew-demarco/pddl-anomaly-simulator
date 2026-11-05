"""
visualizer.py

Runs the trucks simulator *in-process* and visualizes the result directly
from Simulator.state_history — no subprocess, no stdout scraping, no
intermediate JSON file.

The map is drawn as a grid where 1 cell = 1 mile. Locations sit on grid
coordinates, roads are labeled with their distance/speed/travel-time, and
trucks animate along roads at one frame per hour (t).

Usage:
    python visualizer.py --problem p01 --no-anomalies --save run_p01.gif
    python visualizer.py --problem p01 --anomaly road_closure:3:l2:l3 --show
"""

import argparse
import math
import sys

import matplotlib.pyplot as plt
import matplotlib.animation as animation

from simulator import get_run_snapshots

# Reuse main.py's existing path resolution and anomaly-string parsing so
# --problem p01 / --anomaly road_closure:3:l2:l3 behave identically to the CLI.
from main import get_problem_path, parse_manual_anomaly, DOMAIN_FILE


def _round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def draw_frame(ax, snap, road_meta, all_edges):
    """Draw one state snapshot onto a matplotlib axes."""
    ax.clear()
    ax.set_facecolor("#1e1e1e")

    grid = snap.get("grid") or {}
    locs = grid.get("locations") or {}

    if not locs:
        _draw_circle_frame(ax, snap)
        return

    gw = max(1, grid.get("width") or 1)
    gh = max(1, grid.get("height") or 1)

    # Grid lines: 1 cell = 1 mile
    for i in range(gw + 1):
        ax.axvline(i, color="#2b2b2b", linewidth=0.5)

    for j in range(gh + 1):
        ax.axhline(j, color="#2b2b2b", linewidth=0.5)

    coords = {loc: (x, y) for loc, (x, y) in locs.items()}

    # Current connections (undirected view for drawing)
    current_edges = {
        tuple(sorted([c1, c2]))
        for c1, c2 in snap.get("connections", [])
        if c1 in coords and c2 in coords
    }
    all_edges.update(current_edges)

    # Roads
    for pair in all_edges:
        if pair[0] not in coords or pair[1] not in coords:
            continue

        (x1, y1), (x2, y2) = coords[pair[0]], coords[pair[1]]

        if pair in current_edges:
            ax.plot([x1, x2], [y1, y2], color="#7f8c8d", linewidth=1.5, zorder=1)
            meta = road_meta.get(pair)

            if meta:
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                ax.text(
                    mx, my + 0.4,
                    f"{meta['distance']}mi @{meta['speed']}mph = {meta['duration']}t",
                    color="#aab7b8", fontsize=6, ha="center", zorder=2,
                )
        else:
            ax.plot([x1, x2], [y1, y2], color="#e74c3c", linewidth=2.5, zorder=1)
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            ax.text(mx, my, "X", color="#ffdddd", fontsize=10,
                    ha="center", va="center", zorder=2)

    # Locations
    for loc, (x, y) in coords.items():
        ax.plot(x, y, "o", markersize=14, color="#2c3e50",
                markeredgecolor="#ecf0f1", markeredgewidth=1.2, zorder=3)
        ax.text(x, y, loc, color="#ecf0f1", fontsize=7,
                ha="center", va="center", zorder=4)

    # Trucks at interpolated positions
    for tname, pos in (snap.get("truck_positions") or {}).items():
        if pos.get("x") is None or pos.get("y") is None:
            loc = snap.get("trucks", {}).get(tname)

            if loc not in coords:
                continue

            x, y = coords[loc]
            y = y + 0.9
        else:
            x, y = pos["x"], pos["y"]

        ax.plot(x, y, "s", markersize=9, color="#e74c3c", zorder=5)
        ax.text(x, y - 0.75, tname, color="#ffffff", fontsize=6,
                ha="center", zorder=5)

        if pos.get("road"):
            d, s, mc = pos.get("distance"), pos.get("speed"), pos.get("miles_covered")

            if d is not None and s is not None and mc is not None:
                prog = f"{mc:.0f}/{d}mi @{s}mph"
            else:
                prog = f"{pos.get('fraction', 0):.0%}"

            ax.text(x, y + 0.75, prog, color="#f1c40f", fontsize=6,
                    ha="center", zorder=5)

    # HUD
    hour = snap.get("hour")
    hour_txt = f" ({hour} hr)" if hour is not None else ""
    ax.set_title(
        f"Current time: {snap.get('current_time', '?')}{hour_txt}   "
        f"(grid: 1 cell = 1 mile)",
        color="#ecf0f1", fontsize=10, pad=12,
    )

    last = snap.get("last_action", "")
    if last:
        ax.text(0.01, -0.08, last, transform=ax.transAxes,
                color="#f1c40f", fontsize=8, family="monospace")

    ax.set_xlim(-0.5, gw - 0.5)
    ax.set_ylim(gh - 0.5, -0.5)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])

    for spine in ax.spines.values():
        spine.set_color("#555555")


def _draw_circle_frame(ax, snap):
    """Fallback for problems without grid coordinates: circular layout."""
    locs = sorted(
        snap.get("locations", []),
        key=lambda x: int(x[1:]) if x[1:].isdigit() else 0,
    )
    n = len(locs)
    coords = {}

    for i, loc in enumerate(locs):
        angle = (i / n) * 2 * math.pi - math.pi / 2
        coords[loc] = (math.cos(angle) * 0.4 + 0.5, math.sin(angle) * 0.4 + 0.5)

    current_edges = {
        tuple(sorted([c1, c2]))
        for c1, c2 in snap.get("connections", [])
        if c1 in coords and c2 in coords
    }

    for pair in current_edges:
        (x1, y1), (x2, y2) = coords[pair[0]], coords[pair[1]]
        ax.plot([x1, x2], [y1, y2], color="#7f8c8d", linewidth=1.5, zorder=1)

    for loc, (x, y) in coords.items():
        ax.plot(x, y, "o", markersize=14, color="#2c3e50",
                markeredgecolor="#ecf0f1", markeredgewidth=1.2, zorder=3)
        ax.text(x, y, loc, color="#ecf0f1", fontsize=7,
                ha="center", va="center", zorder=4)

    for tname, loc in snap.get("trucks", {}).items():
        if loc in coords:
            x, y = coords[loc]
            ax.plot(x, y + 0.08, "s", markersize=9, color="#e74c3c", zorder=5)

    ax.set_xlim(0, 1)
    ax.set_ylim(1, 0)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])


def build_animation(run, interval_ms=900):
    """Build a matplotlib animation from a get_run_snapshots() result."""
    snapshots = run["snapshots"]

    fig, ax = plt.subplots(figsize=(8, 8))
    fig.patch.set_facecolor("#1e1e1e")

    # Road metadata keyed by undirected pair (from any snapshot that has it)
    road_meta = {}

    for snap in snapshots:
        for r in snap.get("roads", []):
            a, b = r.get("from"), r.get("to")
            road_meta[tuple(sorted([a, b]))] = r

    all_edges = set()
    frames = []

    for snap in snapshots:
        current = {
            tuple(sorted([c1, c2]))
            for c1, c2 in snap.get("connections", [])
        }
        all_edges.update(current)
        frames.append((dict(snap), set(all_edges)))

    def update(i):
        snap, edges = frames[i]
        draw_frame(ax, snap, road_meta, edges)
        return []

    anim = animation.FuncAnimation(
        fig, update, frames=len(frames), interval=interval_ms, blit=False
    )
    return fig, anim


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
        f"[visualizer] status={summary['status']} "
        f"snapshots={len(run['snapshots'])} "
        f"replans={summary['replans_triggered']} "
        f"anomalies={len(summary['anomalies'])}"
    )
    if summary["status"] != "SUCCESS":
        print(f"[visualizer] failure_reason: {summary['failure_reason']}")

    fig, anim = build_animation(run, interval_ms=args.interval_ms)

    fps = max(1, 1000 // args.interval_ms)
    if args.save:
        writer = animation.PillowWriter(fps=fps) if args.save.endswith(".gif") else "ffmpeg"
        anim.save(args.save, writer=writer)
        print(f"[visualizer] Saved animation to {args.save}")

    if args.show:
        plt.show()

    if not args.save and not args.show:
        out_path = f"{args.problem}_animation.gif"
        anim.save(out_path, writer=animation.PillowWriter(fps=fps))
        print(f"[visualizer] Saved animation to {out_path}")


if __name__ == "__main__":
    main()
