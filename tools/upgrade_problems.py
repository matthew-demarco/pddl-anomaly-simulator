#!/usr/bin/env python3
"""
Upgrade all truck problem files with grid coordinates and road metrics.

For every pXX.pddl this script:
  1. Places each location on a square grid (1 cell = 1 mile), deterministically
     (seeded by the problem number, so re-runs produce identical files).
  2. Computes each road's distance in integer miles: round-half-up of the
     Euclidean distance between the two locations' grid coordinates.
  3. Picks each road's speed in mph from a fixed set, deterministically.
  4. Emits (loc-x)/(loc-y), (road-distance), (road-speed), and the precomputed
     (road-span ?from ?to ?t1 ?t2) facts that the drive actions use to advance
     the clock by round_half_up(distance / speed) hours.

Usage:
    python tools/upgrade_problems.py            # upgrade all problems in place
    python tools/upgrade_problems.py --dry-run   # print what would change

server.py also calls upgrade_problem_text() to add the same data to a .pddl
file loaded in the browser.
"""

import argparse
import math
import random
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pddl_parser import parse_problem, parse_problem_text  # noqa: E402

TRUCKS_DIR = ROOT / "fast-downward-24.06.1" / "trucks"
SPEED_CHOICES = [25, 30, 40, 50, 55, 65]

# Predicates owned by this generator: stripped before re-emitting so the
# script is idempotent (re-running it replaces stale road/grid facts).
GENERATED_PREDICATES = {"road-distance", "road-speed", "road-span", "loc-x", "loc-y", "zero-time-road"}

# Object types owned by this generator (re-emitted from scratch each run).
GENERATED_TYPES = {"mile", "mph", "gridcoord"}


def round_half_up(x: float) -> int:
    """Round half away from zero upward (1.5 -> 2, 2.5 -> 3, 0.4 -> 0)."""
    return math.floor(x + 0.5)


def time_sort_key(t: str):
    return int(t[1:]) if t[1:].isdigit() else 0


def assign_coords(locations, rng: random.Random, side: int):
    """Place locations on a side x side grid with a minimum separation."""
    coords = {}
    min_sep = max(6, side // 3)
    attempts = 0

    for loc in locations:
        while True:
            attempts += 1
            x = rng.randint(1, side - 2)
            y = rng.randint(1, side - 2)

            if all(
                (x - cx) ** 2 + (y - cy) ** 2 >= min_sep ** 2
                for cx, cy in coords.values()
            ):
                break

            if attempts > 5000:
                min_sep = max(2, min_sep - 1)
                attempts = 0

        coords[loc] = (x, y)

    return coords


def build_road_data(connections, coords, rng: random.Random, multiplier: float = 1.0):
    """Return per-undirected-road distance (mi) and speed (mph)."""
    undirected = sorted({tuple(sorted((a, b))) for a, b in connections})
    distance = {}
    speed = {}

    for a, b in undirected:
        ax, ay = coords[a]
        bx, by = coords[b]
        dist = round_half_up(math.hypot(bx - ax, by - ay))
        dist = max(dist, 1)  # distinct locations are at least 1 mile apart
        distance[(a, b)] = dist
        raw_speed = rng.choice(SPEED_CHOICES) * multiplier
        speed[(a, b)] = max(10, round(raw_speed))

    return distance, speed


def generate_problem_text(problem, coords, distance, speed):
    """Render the upgraded problem file text."""
    times = sorted(problem.objects.get("time", []), key=time_sort_key)
    lines = []

    lines.append(f"(define (problem {problem.name})")
    lines.append(f"(:domain {problem.domain})")
    lines.append("")

    # ----- objects -----
    lines.append("(:objects")

    for obj_type, names in problem.objects.items():
        if obj_type in GENERATED_TYPES:
            continue  # regenerated below from current road/grid data

        seen = set()

        for name in names:
            if name in seen:
                continue  # skip duplicate declarations from older runs

            seen.add(name)
            lines.append(f"\t{name} - {obj_type}")

    mile_objs = sorted({f"d{d}" for d in distance.values()}, key=lambda s: int(s[1:]))
    mph_objs = sorted({f"s{s}" for s in speed.values()}, key=lambda s: int(s[1:]))
    coord_objs = sorted(
        {f"c{v}" for xy in coords.values() for v in xy}, key=lambda s: int(s[1:])
    )

    for name in mile_objs:
        lines.append(f"\t{name} - mile")

    for name in mph_objs:
        lines.append(f"\t{name} - mph")

    for name in coord_objs:
        lines.append(f"\t{name} - gridcoord")

    lines.append(")")

    # ----- init -----
    lines.append("")
    lines.append("(:init")

    for pred, args in problem.init_facts:
        if pred in GENERATED_PREDICATES:
            continue  # regenerated below

        lines.append(f"\t({pred} {' '.join(args)})")

    # Grid coordinates: 1 cell = 1 mile
    for loc in sorted(coords):
        x, y = coords[loc]
        lines.append(f"\t(loc-x {loc} c{x})")
        lines.append(f"\t(loc-y {loc} c{y})")

    # NOTE: road metrics + spans are appended by the caller, followed by ")".
    return lines, times


def upgrade_problem(problem, seed: int, multiplier: float = 1.0):
    """Return (upgraded problem text, grid side) for one parsed problem."""
    locations = sorted(problem.objects.get("location", []))
    connections = {tuple(f[1]) for f in problem.init_facts if f[0] == "connected"}
    rng = random.Random(seed)

    side = max(30, 15 * math.ceil(math.sqrt(len(locations))) + 15)
    coords = assign_coords(locations, rng, side)
    distance, speed = build_road_data(connections, coords, rng, multiplier)

    lines, times = generate_problem_text(problem, coords, distance, speed)

    # Road metrics for every directed connection
    for a, b in sorted(connections):
        key = tuple(sorted((a, b)))
        d = distance[key]
        s = speed[key]
        lines.append(f"\t(road-distance {a} {b} d{d})")
        lines.append(f"\t(road-speed {a} {b} s{s})")

        dur = round_half_up(d / s)

        if dur == 0:
            lines.append(f"\t(zero-time-road {a} {b})")
            continue

        for i, t_start in enumerate(times):
            j = i + dur

            if j < len(times):
                lines.append(f"\t(road-span {a} {b} {t_start} {times[j]})")

    lines.append(")")

    # ----- goal -----
    lines.append("")
    lines.append("(:goal (and ")

    for goal in problem.goal_conditions:
        lines.append(f"\t({goal.predicate} {' '.join(goal.arguments)})")

    lines.append("))")
    lines.append("")
    lines.append(")")
    return "\n".join(lines) + "\n", side


def upgrade_problem_text(text: str, seed=None):
    """Upgrade PDDL problem text (used for browser uploads).

    Text that already has road data is returned unchanged. The seed defaults
    to one derived from the problem name, so the same file always gets the
    same map. Returns (text, info).
    """
    problem = parse_problem_text(text)
    if any(pred == "road-span" for pred, _ in problem.init_facts):
        return text, {"already_upgraded": True}
    if seed is None:
        seed = 1000 + zlib.crc32(problem.name.encode("utf-8")) % 100000
    new_text, side = upgrade_problem(problem, seed)
    return new_text, {"already_upgraded": False, "grid": side}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--multiplier", type=float, default=1.0,
        help="Scale all road speeds by this factor (used to tune feasibility)",
    )
    args = parser.parse_args()

    problems = sorted(TRUCKS_DIR.glob("p*.pddl"), key=lambda p: p.stem)

    if not problems:
        print(f"No problem files found in {TRUCKS_DIR}")
        sys.exit(1)

    for path in problems:
        problem = parse_problem(str(path))
        locations = sorted(problem.objects.get("location", []))
        connections = {tuple(f[1]) for f in problem.init_facts if f[0] == "connected"}

        if not locations or not connections:
            print(f"  {path.stem}: skipped (no locations/connections)")
            continue

        # Deterministic per-problem randomness
        seed = 1000 + int(path.stem[1:])
        text, side = upgrade_problem(problem, seed, args.multiplier)

        if args.dry_run:
            print(f"  {path.stem}: {len(locations)} locations, "
                  f"{len(connections)} roads, grid {side}x{side}")
            continue

        path.write_text(text, encoding="utf-8")

        # Sanity check: re-parse and confirm structure survived
        check = parse_problem(str(path))
        assert check.goal_conditions == problem.goal_conditions, path.stem
        orig_facts = {
            (p, tuple(a)) for p, a in problem.init_facts
            if p not in GENERATED_PREDICATES
        }
        new_facts = {(p, tuple(a)) for p, a in check.init_facts}
        missing = orig_facts - new_facts
        assert not missing, f"{path.stem}: lost facts {missing}"
        print(f"  {path.stem}: upgraded "
              f"({len(locations)} locations, {len(connections)} roads, grid {side}x{side})")

    print("Done.")


if __name__ == "__main__":
    main()
