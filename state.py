"""
World State Management for the Trucks Domain Simulation.

Maintains the mutable world state during plan execution and provides
action-application logic for the four domain actions: drive, load, unload, deliver.
"""

from dataclasses import dataclass, field
from typing import Set, Dict, Tuple, Optional, List
from copy import deepcopy

from pddl_parser import PddlProblem


# ---------------------------------------------------------------------------
# Plan action (a single step from the sas_plan output)
# ---------------------------------------------------------------------------

@dataclass
class PlanAction:
    """A grounded plan action, e.g. (drive truck1 l3 l2 t0 t1)."""
    name: str
    args: List[str]

    def __str__(self):
        return f"({self.name} {' '.join(self.args)})"


# ---------------------------------------------------------------------------
# World state
# ---------------------------------------------------------------------------

@dataclass
class WorldState:
    """Mutable snapshot of the trucks-domain world."""

    # Truck locations: truck_name -> location
    truck_locations: Dict[str, str] = field(default_factory=dict)

    # Package locations: package_name -> location  (only for packages on the ground)
    package_locations: Dict[str, str] = field(default_factory=dict)

    # Packages in trucks: (package, truck, area) tuples
    cargo: Set[Tuple[str, str, str]] = field(default_factory=set)

    # Free truck areas: (area, truck) tuples
    free_areas: Set[Tuple[str, str]] = field(default_factory=set)

    # Road connections: (from_loc, to_loc) tuples — mutable for road closures
    connections: Set[Tuple[str, str]] = field(default_factory=set)

    # Closer relations: (a1, a2) meaning a1 is closer to the cab than a2
    closer: Set[Tuple[str, str]] = field(default_factory=set)

    # Current time step name (e.g. "t0")
    current_time: str = "t0"

    # Time ordering: list of time step names in order [t0, t1, t2, ...]
    time_steps: List[str] = field(default_factory=list)

    # Set of delivered packages: (package, location, deadline_time)
    delivered: Set[Tuple[str, str, str]] = field(default_factory=set)

    # Packages that reached their destination: (package, location)
    at_destination: Set[Tuple[str, str]] = field(default_factory=set)

    # le predicates: (t1, t2) pairs
    le_predicates: Set[Tuple[str, str]] = field(default_factory=set)

    # All objects by type for PDDL regeneration
    objects: Dict[str, List[str]] = field(default_factory=dict)

    # All trucks in the problem (to track breakdowns)
    all_trucks: List[str] = field(default_factory=list)

    # All packages (including dynamically added ones)
    all_packages: List[str] = field(default_factory=list)

    # All locations
    all_locations: List[str] = field(default_factory=list)

    # All truck areas
    all_areas: List[str] = field(default_factory=list)

    def copy(self) -> 'WorldState':
        """Return a deep copy of this state."""
        return deepcopy(self)

    def get_next_time(self) -> Optional[str]:
        """Return the time step after the current one, or None if at the end."""
        try:
            idx = self.time_steps.index(self.current_time)
            if idx + 1 < len(self.time_steps):
                return self.time_steps[idx + 1]
        except ValueError:
            pass
        return None

    def get_remaining_time_steps(self) -> List[str]:
        """Return time steps from current_time onward (inclusive)."""
        try:
            idx = self.time_steps.index(self.current_time)
            return self.time_steps[idx:]
        except ValueError:
            return self.time_steps


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def initialize_from_problem(problem: PddlProblem) -> WorldState:
    """Build an initial WorldState from a parsed PDDL problem."""
    state = WorldState()
    state.objects = deepcopy(problem.objects)

    # Collect typed objects
    state.all_trucks = list(problem.objects.get('truck', []))
    state.all_packages = list(problem.objects.get('package', []))
    state.all_locations = list(problem.objects.get('location', []))
    state.all_areas = list(problem.objects.get('truckarea', []))

    # Build ordered time steps
    time_objs = problem.objects.get('time', [])
    # Sort by numeric suffix: t0, t1, t2, ...
    state.time_steps = sorted(time_objs, key=lambda t: int(t[1:]) if t[1:].isdigit() else 0)

    # Process init facts
    for pred, args in problem.init_facts:
        if pred == 'at':
            obj_name, loc = args[0], args[1]
            if obj_name in state.all_trucks:
                state.truck_locations[obj_name] = loc
            elif obj_name in state.all_packages:
                state.package_locations[obj_name] = loc
        elif pred == 'free':
            area, truck = args[0], args[1]
            state.free_areas.add((area, truck))
        elif pred == 'connected':
            state.connections.add((args[0], args[1]))
        elif pred == 'closer':
            state.closer.add((args[0], args[1]))
        elif pred == 'time-now':
            state.current_time = args[0]
        elif pred == 'le':
            state.le_predicates.add((args[0], args[1]))
        elif pred == 'in':
            # in ?p ?t ?a
            state.cargo.add((args[0], args[1], args[2]))

    return state


# ---------------------------------------------------------------------------
# Action application
# ---------------------------------------------------------------------------

def apply_action(state: WorldState, action: PlanAction) -> WorldState:
    """
    Apply a grounded plan action to the world state (in place) and return it.

    Actions:
        (drive ?truck ?from ?to ?t1 ?t2)
        (load ?package ?truck ?area ?location)
        (unload ?package ?truck ?area ?location)
        (deliver ?package ?location ?t1 ?t2)
    """
    name = action.name.lower()
    args = action.args

    if name == 'drive':
        truck, from_loc, to_loc, t1, t2 = args
        state.truck_locations[truck] = to_loc
        state.current_time = t2

    elif name == 'load':
        package, truck, area, location = args
        # Package leaves the ground
        if package in state.package_locations:
            del state.package_locations[package]
        # Package enters the truck
        state.cargo.add((package, truck, area))
        # Area is no longer free
        state.free_areas.discard((area, truck))

    elif name == 'unload':
        package, truck, area, location = args
        # Package leaves the truck
        state.cargo.discard((package, truck, area))
        # Package is now on the ground at the truck's location
        state.package_locations[package] = location
        # Area becomes free
        state.free_areas.add((area, truck))

    elif name == 'deliver':
        package, location, t1, t2 = args
        # Package is delivered
        if package in state.package_locations:
            del state.package_locations[package]
        state.delivered.add((package, location, t2))
        state.at_destination.add((package, location))

    return state


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def state_summary(state: WorldState) -> str:
    """Return a concise human-readable summary of the current world state."""
    lines = []
    lines.append(f"  Time: {state.current_time}")

    for truck in sorted(state.all_trucks):
        loc = state.truck_locations.get(truck, "???")
        cargo_list = [p for p, t, a in state.cargo if t == truck]
        cargo_str = f" carrying [{', '.join(sorted(cargo_list))}]" if cargo_list else ""
        lines.append(f"  {truck} @ {loc}{cargo_str}")

    ground_pkgs = sorted(state.package_locations.items())
    if ground_pkgs:
        lines.append(f"  Packages on ground: {', '.join(f'{p}@{l}' for p, l in ground_pkgs)}")

    if state.delivered:
        lines.append(f"  Delivered: {', '.join(f'{p}→{l}' for p, l, _ in sorted(state.delivered))}")

    return '\n'.join(lines)
