"""
PDDL Problem Writer for the Trucks Domain.

Generates a new PDDL problem file from the current world state, incorporating
modifications from anomaly responses. This enables replanning from the
current state with an updated problem definition.
"""

from pathlib import Path
from typing import List, Optional, Dict, Tuple, Set

from state import WorldState
from pddl_parser import PddlProblem, GoalCondition
from case_library import CaseResponse


def generate_problem_pddl(
    state: WorldState,
    original_problem: PddlProblem,
    response: Optional[CaseResponse] = None,
    output_path: Optional[str] = None,
    remaining_goals: Optional[List[GoalCondition]] = None,
) -> str:
    """
    Generate a PDDL problem file reflecting the current world state.

    Args:
        state: Current world state mid-simulation.
        original_problem: The original parsed problem (for structure reference).
        response: Optional CaseResponse with anomaly-driven modifications.
        output_path: Where to write the file. If None, returns just the string.
        remaining_goals: If provided, use these as goals instead of computing from original.

    Returns:
        The generated PDDL string.
    """
    lines = []

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    lines.append(f"(define (problem {original_problem.name}-replanned)")
    lines.append(f"(:domain {original_problem.domain})")

    # -----------------------------------------------------------------------
    # Objects
    # -----------------------------------------------------------------------
    # Start with current objects from state
    objects: Dict[str, List[str]] = {}

    # Trucks (minus broken-down ones)
    removed_trucks = set()
    if response:
        removed_trucks = set(response.remove_trucks)

    active_trucks = [t for t in state.all_trucks if t not in removed_trucks]
    if active_trucks:
        objects["truck"] = active_trucks

    # Packages: all from state (already includes anomaly-added ones), minus fully delivered
    delivered_pkgs = {p for p, _, _ in state.delivered}
    at_dest_pkgs = {p for p, _ in state.at_destination}
    finished_pkgs = delivered_pkgs & at_dest_pkgs
    active_pkgs = list(dict.fromkeys(
        p for p in state.all_packages if p not in finished_pkgs
    ))  # dict.fromkeys preserves order and deduplicates

    if active_pkgs:
        objects["package"] = active_pkgs

    # Locations
    if state.all_locations:
        objects["location"] = list(state.all_locations)

    # Time steps: from current time onward, EXTENDED for replanning
    remaining_times = state.get_remaining_time_steps()
    if response:
        # Add extra time steps to give the planner room after anomalies
        extra_steps = 5  # extra buffer
        if remaining_times:
            last_num = int(remaining_times[-1][1:]) if remaining_times[-1][1:].isdigit() else 0
            for j in range(1, extra_steps + 1):
                remaining_times.append(f"t{last_num + j}")
    if remaining_times:
        objects["time"] = remaining_times

    # Truck areas
    if state.all_areas:
        objects["truckarea"] = list(state.all_areas)

    # Write objects block
    lines.append("(:objects")
    for obj_type, obj_names in objects.items():
        for name in obj_names:
            lines.append(f"\t{name} - {obj_type}")
    lines.append(")")

    # -----------------------------------------------------------------------
    # Init
    # -----------------------------------------------------------------------
    lines.append("")
    lines.append("(:init")

    # Truck locations
    for truck in active_trucks:
        loc = state.truck_locations.get(truck)
        if loc:
            lines.append(f"\t(at {truck} {loc})")

    # Free areas (only for active trucks)
    for area, truck in sorted(state.free_areas):
        if truck in removed_trucks:
            continue
        lines.append(f"\t(free {area} {truck})")

    # Closer relations
    for a1, a2 in sorted(state.closer):
        lines.append(f"\t(closer {a1} {a2})")

    # Package locations (on ground) — state already reflects anomaly changes
    seen_pkg_facts = set()
    for pkg in active_pkgs:
        if pkg in state.package_locations:
            key = ("at", pkg, state.package_locations[pkg])
            if key not in seen_pkg_facts:
                seen_pkg_facts.add(key)
                lines.append(f"\t(at {pkg} {state.package_locations[pkg]})")

    # Cargo (packages in trucks)
    for pkg, truck, area in sorted(state.cargo):
        if truck not in removed_trucks and pkg in active_pkgs:
            lines.append(f"\t(in {pkg} {truck} {area})")

    # Connections — state already has road closures removed
    for from_loc, to_loc in sorted(state.connections):
        lines.append(f"\t(connected {from_loc} {to_loc})")

    # Time: current time
    lines.append(f"\t(time-now {state.current_time})")

    # le predicates: generate fresh for all remaining times (including extended)
    for i in range(len(remaining_times)):
        for j in range(i, len(remaining_times)):
            lines.append(f"\t(le {remaining_times[i]} {remaining_times[j]})")

    # next predicates: rebuild for all remaining times (including extended)
    for i in range(len(remaining_times) - 1):
        lines.append(f"\t(next {remaining_times[i]} {remaining_times[i+1]})")

    lines.append(")")

    # -----------------------------------------------------------------------
    # Goal
    # -----------------------------------------------------------------------
    lines.append("")

    # Determine goals
    goals = _compute_goals(
        state, original_problem, response, remaining_goals, remaining_times
    )

    lines.append("(:goal (and ")
    for goal in goals:
        args_str = " ".join(goal.arguments)
        lines.append(f"\t({goal.predicate} {args_str})")
    lines.append("))")

    lines.append("")
    lines.append(")")

    pddl_text = "\n".join(lines)

    if output_path:
        Path(output_path).write_text(pddl_text, encoding='utf-8')

    return pddl_text


def _compute_goals(
    state: WorldState,
    original_problem: PddlProblem,
    response: Optional[CaseResponse],
    remaining_goals: Optional[List[GoalCondition]],
    remaining_times: List[str],
) -> List[GoalCondition]:
    """Compute the goal list for the replanned problem."""

    # Start with remaining goals or original goals
    if remaining_goals is not None:
        goals = list(remaining_goals)
    else:
        goals = list(original_problem.goal_conditions)

    # Remove already-achieved goals
    filtered = []
    for goal in goals:
        pkg = goal.arguments[0] if goal.arguments else None

        # Check if this goal is already satisfied
        if goal.predicate == "delivered":
            if any(p == pkg for p, _, _ in state.delivered):
                continue  # Already delivered
        elif goal.predicate == "at-destination":
            if any(p == pkg for p, _ in state.at_destination):
                continue  # Already at destination

        filtered.append(goal)

    goals = filtered

    # Apply anomaly response modifications
    if response:
        # Remove specified goals
        for rg in response.remove_goals:
            goals = [g for g in goals if not (
                g.predicate == rg.predicate and g.arguments == rg.arguments
            )]

        # Add new goals
        goals.extend(response.add_goals)

        # Modify goals (e.g., tighten deadlines)
        for pkg_name, new_goal in response.modify_goals.items():
            modified = False
            for i, goal in enumerate(goals):
                if goal.arguments and goal.arguments[0] == pkg_name:
                    if new_goal.predicate == "delivered":
                        # Resolve __DEST__ placeholder
                        dest = goal.arguments[1] if len(goal.arguments) > 1 else "l1"
                        new_args = list(new_goal.arguments)
                        new_args = [a if a != "__DEST__" else dest for a in new_args]
                        goals[i] = GoalCondition(
                            predicate=new_goal.predicate,
                            arguments=new_args,
                        )
                        modified = True
                        break
            if not modified:
                # If no existing goal found, add a new one
                # Pick the first location as default destination
                args = list(new_goal.arguments)
                args = [a if a != "__DEST__" else state.all_locations[0] for a in args]
                goals.append(GoalCondition(
                    predicate=new_goal.predicate,
                    arguments=args,
                ))

    # Relax ALL delivery deadlines to the extended time horizon.
    # Anomalies make original deadlines impossible — the planner will still
    # find the shortest plan (fewest actions) within the extended window.
    final_goals = []
    for goal in goals:
        if goal.predicate == "delivered" and len(goal.arguments) >= 3:
            # Replace original deadline with the last available time step
            goal = GoalCondition(
                predicate=goal.predicate,
                arguments=[goal.arguments[0], goal.arguments[1], remaining_times[-1]],
            )
        final_goals.append(goal)

    return final_goals

