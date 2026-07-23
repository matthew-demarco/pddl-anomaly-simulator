"""
PDDL Problem Writer for the Trucks Domain.

Generates a new PDDL problem file from the current world state, incorporating
modifications from anomaly responses. This enables replanning from the
current state with an updated problem definition.
"""                                                                         # Module docstring explaining that this file creates updated PDDL problem files for replanning.


from pathlib import Path                                                    # Imports Path so generated PDDL text can be written to a file.
from typing import List, Optional, Dict, Tuple, Set                         # Imports type hints for lists, optional values, dictionaries, tuples, and sets.

from state import WorldState                                               # Imports WorldState so the writer can read the simulator's current state.
from pddl_parser import PddlProblem, GoalCondition                         # Imports the parsed PDDL problem class and the class representing one goal.
from case_library import CaseResponse                                      # Imports CaseResponse so anomaly-related PDDL modifications can be applied.


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
    """                                                                     # Function docstring explaining the inputs and generated output.

    lines = []                                                              # Creates an empty list that will hold each line of the generated PDDL file.

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------

    lines.append(f"(define (problem {original_problem.name}-replanned)")    # Adds the opening problem definition and gives the replanned problem a modified name.
    lines.append(f"(:domain {original_problem.domain})")                   # Adds the name of the PDDL domain used by the original problem.

    # -----------------------------------------------------------------------
    # Objects
    # -----------------------------------------------------------------------

    # Start with current objects from state
    objects: Dict[str, List[str]] = {}                                     # Creates a dictionary that will group current object names by their PDDL types.

    # Trucks (minus broken-down ones)
    removed_trucks = set()                                                 # Creates an empty set for trucks that should not appear in the replanned problem.

    if response:                                                           # Checks whether an anomaly CaseResponse was provided.
        removed_trucks = set(response.remove_trucks)                       # Copies the response's removed truck names into a set for quick lookup.

    active_trucks = [t for t in state.all_trucks if t not in removed_trucks]  # Builds a list containing trucks that are still available for service.

    if active_trucks:                                                      # Checks whether at least one active truck remains.
        objects["truck"] = active_trucks                                   # Adds the active trucks to the PDDL objects dictionary under the truck type.

    # Packages: all from state (already includes anomaly-added ones), minus fully delivered
    delivered_pkgs = {p for p, _, _ in state.delivered}                   # Creates a set containing package names recorded as delivered.
    at_dest_pkgs = {p for p, _ in state.at_destination}                   # Creates a set containing package names recorded as being at their destination.
    finished_pkgs = delivered_pkgs & at_dest_pkgs                         # Keeps packages appearing in both sets, meaning they are considered fully finished.

    active_pkgs = list(dict.fromkeys(                                     # Builds an ordered list of unique packages that are not fully finished.
        p for p in state.all_packages if p not in finished_pkgs           # Includes each known package unless it appears in the finished package set.
    ))                                                                      # dict.fromkeys() removes duplicates while preserving the original order.

    if active_pkgs:                                                        # Checks whether any active packages remain.
        objects["package"] = active_pkgs                                   # Adds active packages to the PDDL object dictionary under the package type.

    # Locations
    if state.all_locations:                                                # Checks whether the state contains any locations.
        objects["location"] = list(state.all_locations)                    # Adds all locations to the PDDL object dictionary.

    # Time steps: from current time onward, EXTENDED for replanning
    remaining_times = state.get_remaining_time_steps()                     # Gets the current time and all later time steps from the WorldState.

    if response:                                                           # Checks whether replanning is happening because of an anomaly.
        # Add extra time steps to give the planner room after anomalies
        extra_steps = 5                                                    # Chooses to add five extra time steps to the replanning time horizon.

        if remaining_times:                                                # Checks whether at least one remaining time step exists.
            last_num = int(remaining_times[-1][1:]) if remaining_times[-1][1:].isdigit() else 0  # Extracts the numeric part of the final time name, such as 8 from "t8".
            for j in range(1, extra_steps + 1):                            # Loops five times using the numbers 1 through 5.
                remaining_times.append(f"t{last_num + j}")                 # Adds new time names after the previous final time, such as t9 through t13.

    if remaining_times:                                                    # Checks whether the remaining-time list is not empty.
        objects["time"] = remaining_times                                  # Adds the remaining and extended time steps as PDDL time objects.

    # Truck areas
    if state.all_areas:                                                    # Checks whether truck cargo areas exist.
        objects["truckarea"] = list(state.all_areas)                       # Adds all truck areas to the PDDL object dictionary.

    # Write objects block
    lines.append("(:objects")                                              # Adds the opening line of the PDDL objects section.

    for obj_type, obj_names in objects.items():                            # Loops through every PDDL object type and its list of object names.
        for name in obj_names:                                             # Loops through each object name belonging to the current type.
            lines.append(f"\t{name} - {obj_type}")                         # Writes one PDDL object declaration, such as truck1 - truck.

    lines.append(")")                                                      # Closes the PDDL objects section.

    # -----------------------------------------------------------------------
    # Init
    # -----------------------------------------------------------------------

    lines.append("")                                                       # Adds a blank line to improve readability in the generated file.
    lines.append("(:init")                                                 # Adds the opening line of the PDDL initial-state section.

    # Truck locations
    for truck in active_trucks:                                            # Loops through each truck that remains active.
        loc = state.truck_locations.get(truck)                             # Gets the truck's current location, or None if no location is recorded.

        if loc:                                                            # Checks whether a location was found for the truck.
            lines.append(f"\t(at {truck} {loc})")                          # Writes a PDDL fact stating that the truck is currently at that location.

    # Free areas (only for active trucks)
    for area, truck in sorted(state.free_areas):                           # Loops through sorted free cargo-area records.
        if truck in removed_trucks:                                        # Checks whether the area belongs to a truck that was removed.
            continue                                                       # Skips that free-area fact and moves to the next record.

        lines.append(f"\t(free {area} {truck})")                           # Writes a PDDL fact stating that the truck area is free.

    # Closer relations
    for a1, a2 in sorted(state.closer):                                    # Loops through sorted closer relationships between truck areas.
        lines.append(f"\t(closer {a1} {a2})")                              # Writes each closer relationship as a PDDL fact.

    # Package locations (on ground) — state already reflects anomaly changes
    seen_pkg_facts = set()                                                 # Creates a set to prevent duplicate package-location facts.

    for pkg in active_pkgs:                                                # Loops through each package that still belongs in the replanned problem.
        if pkg in state.package_locations:                                 # Checks whether the package is currently located on the ground.
            key = ("at", pkg, state.package_locations[pkg])                # Creates a tuple uniquely identifying the package-location fact.

            if key not in seen_pkg_facts:                                  # Checks whether the fact has not already been written.
                seen_pkg_facts.add(key)                                    # Records the fact so it will not be added again.
                lines.append(f"\t(at {pkg} {state.package_locations[pkg]})")  # Writes the package's current ground location as a PDDL fact.

    # Cargo (packages in trucks)
    for pkg, truck, area in sorted(state.cargo):                           # Loops through sorted cargo records containing package, truck, and cargo area.
        if truck not in removed_trucks and pkg in active_pkgs:             # Includes the cargo only if its truck is active and its package is unfinished.
            lines.append(f"\t(in {pkg} {truck} {area})")                   # Writes a PDDL fact stating that the package is inside the truck area.

    # Connections — state already has road closures removed
    for from_loc, to_loc in sorted(state.connections):                     # Loops through every current directed road connection.
        lines.append(f"\t(connected {from_loc} {to_loc})")                 # Writes each road connection as a PDDL connected fact.

    # Time: current time
    lines.append(f"\t(time-now {state.current_time})")                     # Writes a fact identifying the simulator's current time.

    # le predicates: generate fresh for all remaining times (including extended)
    for i in range(len(remaining_times)):                                  # Loops through every remaining time-step index.
        for j in range(i, len(remaining_times)):                           # Loops from the current time index through all later time indexes.
            lines.append(f"\t(le {remaining_times[i]} {remaining_times[j]})")  # Writes a less-than-or-equal time relationship for each valid ordered pair.

    # next predicates: rebuild for all remaining times (including extended)
    for i in range(len(remaining_times) - 1):                              # Loops through every remaining time except the last one.
        lines.append(f"\t(next {remaining_times[i]} {remaining_times[i+1]})")  # Writes a next relationship between consecutive time steps.

    lines.append(")")                                                      # Closes the PDDL initial-state section.

    # -----------------------------------------------------------------------
    # Goal
    # -----------------------------------------------------------------------

    lines.append("")                                                       # Adds a blank line before the goal section.

    # Determine goals
    goals = _compute_goals(                                                # Calls the helper function that decides which goals remain and how anomalies modify them.
        state,                                                             # Passes the current WorldState.
        original_problem,                                                  # Passes the original parsed PDDL problem.
        response,                                                          # Passes the optional anomaly response.
        remaining_goals,                                                   # Passes any explicitly supplied goal list.
        remaining_times,                                                   # Passes the remaining and extended time horizon.
    )

    lines.append("(:goal (and ")                                           # Adds the opening of the PDDL goal section containing an and expression.

    for goal in goals:                                                     # Loops through each final GoalCondition.
        args_str = " ".join(goal.arguments)                               # Combines the goal arguments into one space-separated string.
        lines.append(f"\t({goal.predicate} {args_str})")                   # Writes the goal predicate and arguments as a PDDL expression.

    lines.append("))")                                                     # Closes the and expression and the goal section.

    lines.append("")                                                       # Adds a blank line before the end of the problem file.
    lines.append(")")                                                      # Closes the complete PDDL problem definition.

    pddl_text = "\n".join(lines)                                           # Combines all generated lines into one string separated by newline characters.

    if output_path:                                                        # Checks whether the caller supplied a destination file path.
        Path(output_path).write_text(pddl_text, encoding='utf-8')          # Writes the generated PDDL text to the requested file using UTF-8 encoding.

    return pddl_text                                                       # Returns the generated PDDL text whether or not it was also written to a file.


def _compute_goals(                                                        # Defines an internal helper function that builds the goal list for replanning.
    state: WorldState,                                                     # Receives the current world state.
    original_problem: PddlProblem,                                         # Receives the original problem and its original goals.
    response: Optional[CaseResponse],                                      # Receives optional anomaly-related goal modifications.
    remaining_goals: Optional[List[GoalCondition]],                        # Receives an optional explicitly provided list of remaining goals.
    remaining_times: List[str],                                            # Receives the available time steps for the replanned problem.
) -> List[GoalCondition]:                                                  # Returns the final list of GoalCondition objects.
    """Compute the goal list for the replanned problem."""                 # Function docstring explaining the purpose of _compute_goals().

    # Start with remaining goals or original goals
    if remaining_goals is not None:                                        # Checks whether the caller supplied a specific remaining-goal list.
        goals = list(remaining_goals)                                      # Copies the supplied goals so the original list is not modified.
    else:                                                                  # Runs when no custom remaining-goal list was provided.
        goals = list(original_problem.goal_conditions)                     # Copies the original problem's goal conditions.

    # Remove already-achieved goals
    filtered = []                                                          # Creates an empty list for goals that have not yet been completed.

    for goal in goals:                                                     # Loops through each current goal.
        pkg = goal.arguments[0] if goal.arguments else None                # Treats the first goal argument as the package name when arguments exist.

        # Check if this goal is already satisfied
        if goal.predicate == "delivered":                                  # Checks whether the goal requires a timed delivery.
            if any(p == pkg for p, _, _ in state.delivered):               # Checks whether the package already appears in the delivered records.
                continue                                                   # Skips the completed goal and moves to the next goal.

        elif goal.predicate == "at-destination":                           # Checks whether the goal requires a package to reach a destination.
            if any(p == pkg for p, _ in state.at_destination):             # Checks whether the package already appears in the at-destination records.
                continue                                                   # Skips the completed goal.

        filtered.append(goal)                                              # Keeps the goal because it has not yet been satisfied.

    goals = filtered                                                       # Replaces the original goal list with only the unfinished goals.

    # Apply anomaly response modifications
    if response:                                                           # Checks whether an anomaly response was supplied.

        # Remove specified goals
        for rg in response.remove_goals:                                   # Loops through each goal that the response says should be removed.
            goals = [g for g in goals if not (                            # Rebuilds the goal list without goals matching the removal request.
                g.predicate == rg.predicate and g.arguments == rg.arguments  # Treats a goal as matching when both its predicate and arguments are equal.
            )]

        # Add new goals
        goals.extend(response.add_goals)                                   # Adds all new anomaly-created goals to the existing goal list.

        # Modify goals (e.g., tighten deadlines)
        for pkg_name, new_goal in response.modify_goals.items():           # Loops through each package and its replacement goal.
            modified = False                                               # Tracks whether an existing goal was successfully replaced.

            for i, goal in enumerate(goals):                               # Loops through the goals while also tracking each goal's index.
                if goal.arguments and goal.arguments[0] == pkg_name:        # Checks whether the current goal belongs to the affected package.

                    if new_goal.predicate == "delivered":                   # Checks whether the replacement is a timed delivered goal.

                        # Resolve __DEST__ placeholder
                        dest = goal.arguments[1] if len(goal.arguments) > 1 else "l1"  # Uses the existing goal's destination or falls back to "l1".
                        new_args = list(new_goal.arguments)                 # Copies the replacement goal arguments.
                        new_args = [a if a != "__DEST__" else dest for a in new_args]  # Replaces the special destination placeholder with the resolved destination.

                        goals[i] = GoalCondition(                           # Replaces the old goal at its current index.
                            predicate=new_goal.predicate,                    # Uses the replacement goal predicate.
                            arguments=new_args,                             # Uses the replacement arguments containing the actual destination.
                        )

                        modified = True                                    # Records that an existing goal was successfully changed.
                        break                                              # Stops searching because the matching package goal was found.

            if not modified:                                               # Runs when no existing goal was found for the package.

                # If no existing goal found, add a new one
                # Pick the first location as default destination
                args = list(new_goal.arguments)                            # Copies the replacement goal arguments.
                args = [a if a != "__DEST__" else state.all_locations[0] for a in args]  # Replaces the destination placeholder with the first known location.

                goals.append(GoalCondition(                                # Adds the new goal because no existing package goal could be replaced.
                    predicate=new_goal.predicate,                           # Uses the replacement goal predicate.
                    arguments=args,                                        # Uses the arguments containing the fallback destination.
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

    # Relax ordinary delivery deadlines to the extended time horizon,
    # but preserve manually selected deadlines for affected packages.
    final_goals = []

    for goal in goals:
        if (
            goal.predicate == "delivered"
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