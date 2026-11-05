"""
PDDL Problem Writer for the Trucks Domain.

Generates a new PDDL problem file from the current world state, incorporating
modifications from anomaly responses. This enables replanning from the
current state with an updated problem definition.

Also provides problem_to_pddl(), a plain serializer used by
tools/upgrade_problems.py and by the browser upload / future question-form
editor to save problems as .pddl files.
"""                                                                         # Module docstring explaining that this file creates PDDL problem files.


from pathlib import Path                                                    # Imports Path so generated PDDL text can be written to a file.
from typing import List, Optional, Dict, Tuple                              # Imports type hints for lists, optional values, dictionaries, and tuples.

from state import WorldState                                               # Imports WorldState so the writer can read the simulator's current state.
from pddl_parser import PddlProblem, GoalCondition                         # Imports the parsed PDDL problem class and the class representing one goal.
from case_library import CaseResponse                                      # Imports CaseResponse so anomaly-related PDDL modifications can be applied.


# Extra hours added to the horizon on every replan, per hour of the slowest road.
EXTRA_REPLAN_STEPS_PER_HOUR = 5


# ---------------------------------------------------------------------------
# Generic serializer (problem data -> PDDL text)
# ---------------------------------------------------------------------------

def problem_to_pddl(
    name: str,
    domain: str,
    objects: Dict[str, List[str]],
    init_facts: List[Tuple[str, List[str]]],
    goals: List[GoalCondition],
) -> str:
    """Serialize problem data to PDDL text: one object per line, one fact per line."""
    lines = [f"(define (problem {name})", f"(:domain {domain})", "(:objects"]

    for obj_type, names in objects.items():
        for obj in names:
            lines.append(f"\t{obj} - {obj_type}")

    lines += [")", "", "(:init"]

    for predicate, args in init_facts:
        lines.append(f"\t({predicate} {' '.join(args)})")

    lines += [")", "", "(:goal (and "]

    for goal in goals:
        lines.append(f"\t({goal.predicate} {' '.join(goal.arguments)})")

    lines += ["))", "", ")", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Replanning writer (world state -> PDDL text)
# ---------------------------------------------------------------------------

def generate_problem_pddl(                                                 # Defines the main function that creates an updated PDDL problem.
    state: WorldState,                                                     # Receives the current simulation state after completed actions or anomalies.
    original_problem: PddlProblem,                                         # Receives the original parsed PDDL problem for its name, domain, objects, and goals.
    response: Optional[CaseResponse] = None,                               # Optionally receives anomaly-response modifications; None means there is no anomaly response.
    output_path: Optional[str] = None,                                     # Optionally receives the path where the generated PDDL file should be saved.
    remaining_goals: Optional[List[GoalCondition]] = None,                 # Optionally receives a specific goal list instead of using the original problem goals.
) -> str:                                                                  # Returns the complete generated PDDL problem as a string.
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

    lines = []                                                              # Holds each line of the generated PDDL file.

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------

    base_name = original_problem.name
    if not base_name.endswith("-replanned"):
        base_name = f"{base_name}-replanned"                               # Avoids p01-replanned-replanned after several replans.

    lines.append(f"(define (problem {base_name})")
    lines.append(f"(:domain {original_problem.domain})")

    # -----------------------------------------------------------------------
    # Objects
    # -----------------------------------------------------------------------

    objects: Dict[str, List[str]] = {}                                     # Groups current object names by their PDDL types.

    # Trucks (minus broken-down ones)
    removed_trucks = set(response.remove_trucks) if response else set()
    active_trucks = [t for t in state.all_trucks if t not in removed_trucks]

    if active_trucks:
        objects["truck"] = active_trucks

    # Packages: all from state (already includes anomaly-added ones), minus fully delivered
    delivered_pkgs = {p for p, _, _ in state.delivered}
    at_dest_pkgs = {p for p, _ in state.at_destination}
    finished_pkgs = delivered_pkgs & at_dest_pkgs

    active_pkgs = list(dict.fromkeys(
        p for p in state.all_packages if p not in finished_pkgs
    ))

    if active_pkgs:
        objects["package"] = active_pkgs

    # Locations
    if state.all_locations:
        objects["location"] = list(state.all_locations)

    # Time steps: from current time onward, EXTENDED for replanning
    remaining_times = list(state.get_remaining_time_steps())                # Copy so extending it never alters state.time_steps.

    if response and remaining_times:
        # Give the planner room after an anomaly. Slow roads need more room,
        # so the extension scales with the slowest road's travel time.
        slowest = max(
            (state.road_duration(f, t) for f, t in state.connections),
            default=1,
        )
        extra_steps = EXTRA_REPLAN_STEPS_PER_HOUR * max(1, slowest)
        last_num = int(remaining_times[-1][1:]) if remaining_times[-1][1:].isdigit() else 0

        for j in range(1, extra_steps + 1):
            remaining_times.append(f"t{last_num + j}")

    if remaining_times:
        objects["time"] = remaining_times

    # Truck areas
    if state.all_areas:
        objects["truckarea"] = list(state.all_areas)

    # Road-metric objects (mile / mph / gridcoord) actually referenced below
    mile_objs, mph_objs, coord_objs = set(), set(), set()

    for from_loc, to_loc in sorted(state.connections):
        d = state.road_distance.get((from_loc, to_loc))
        s = state.road_speed.get((from_loc, to_loc))

        if d is not None:
            mile_objs.add(f"d{d}")

        if s is not None:
            mph_objs.add(f"s{s}")

    for loc in state.all_locations:
        if loc in state.loc_x:
            coord_objs.add(f"c{state.loc_x[loc]}")

        if loc in state.loc_y:
            coord_objs.add(f"c{state.loc_y[loc]}")

    def _num_key(name: str) -> int:
        return int(name[1:]) if name[1:].isdigit() else 0

    if mile_objs:
        objects["mile"] = sorted(mile_objs, key=_num_key)

    if mph_objs:
        objects["mph"] = sorted(mph_objs, key=_num_key)

    if coord_objs:
        objects["gridcoord"] = sorted(coord_objs, key=_num_key)

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

    # Road metrics: distance (miles) and speed (mph) per directed road
    for from_loc, to_loc in sorted(state.connections):
        d = state.road_distance.get((from_loc, to_loc))
        s = state.road_speed.get((from_loc, to_loc))

        if d is not None:
            lines.append(f"\t(road-distance {from_loc} {to_loc} d{d})")

        if s is not None:
            lines.append(f"\t(road-speed {from_loc} {to_loc} s{s})")

    # Road spans: (road-span from to t1 t2) means departing at t1 arrives at t2,
    # where the gap equals the road's rounded travel time. Generated for every
    # remaining time step (including the extended replan horizon). Roads without
    # metrics count as 1t, so they still drive with the extended domain.
    for from_loc, to_loc in sorted(state.connections):
        dur = state.road_duration(from_loc, to_loc)

        if dur == 0:
            lines.append(f"\t(zero-time-road {from_loc} {to_loc})")         # 0t roads use the drive-instant action.
            continue

        for i, t_start in enumerate(remaining_times):
            j = i + dur

            if j < len(remaining_times):
                lines.append(f"\t(road-span {from_loc} {to_loc} {t_start} {remaining_times[j]})")

    # Grid coordinates: 1 cell = 1 mile
    for loc in state.all_locations:
        if loc in state.loc_x:
            lines.append(f"\t(loc-x {loc} c{state.loc_x[loc]})")

        if loc in state.loc_y:
            lines.append(f"\t(loc-y {loc} c{state.loc_y[loc]})")

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

    goals = _compute_goals(
        state,
        original_problem,
        response,
        remaining_goals,
        remaining_times,
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

        if goal.predicate == "delivered":
            if any(p == pkg for p, _, _ in state.delivered):
                continue

        elif goal.predicate == "at-destination":
            if any(p == pkg for p, _ in state.at_destination):
                continue

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
                        new_args = [a if a != "__DEST__" else dest for a in new_goal.arguments]

                        goals[i] = GoalCondition(
                            predicate=new_goal.predicate,
                            arguments=new_args,
                        )

                        modified = True
                        break

            if not modified:
                # If no existing goal found, add a new one
                # Pick the first location as default destination
                args = [a if a != "__DEST__" else state.all_locations[0] for a in new_goal.arguments]

                goals.append(GoalCondition(
                    predicate=new_goal.predicate,
                    arguments=args,
                ))

    # Track packages whose deadlines were manually changed.
    # Their selected deadlines must be preserved during replanning.
    manually_changed_packages = set()

    if response:
        for pkg_name, modified_goal in response.modify_goals.items():
            if (
                modified_goal.predicate == "delivered"
                and len(modified_goal.arguments) >= 3
            ):
                new_deadline = modified_goal.arguments[2]

                if new_deadline not in remaining_times:
                    raise ValueError(
                        f"Deadline change failed for {pkg_name}: "
                        f"{new_deadline} is not a valid remaining time."
                    )

                manually_changed_packages.add(pkg_name)

    # Relax ordinary delivery deadlines to the extended time horizon, but only
    # during an actual replan (response given). Pure state exports keep the
    # original deadlines. Manually selected deadlines are always preserved.
    final_goals = []

    for goal in goals:
        if (
            response is not None
            and goal.predicate == "delivered"
            and len(goal.arguments) >= 3
            and goal.arguments[0] not in manually_changed_packages
        ):
            goal = GoalCondition(
                predicate=goal.predicate,
                arguments=[
                    goal.arguments[0],
                    goal.arguments[1],
                    remaining_times[-1],
                ],
            )

        final_goals.append(goal)

    return final_goals
