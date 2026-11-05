"""
World State Management for the Trucks Domain Simulation.

Maintains the mutable world state during plan execution and provides
action-application logic for the domain actions: drive, drive-instant,
load, unload, deliver.

Roads carry a distance (miles) and speed (mph); travel time is
distance / speed rounded half-up to whole hours (t steps). Problems without
road data fall back to the original behavior of 1t per drive.
"""                                                                         # Module docstring explaining that this file stores the changing simulation state and applies plan actions.


from dataclasses import dataclass, field                                    # Imports dataclass for data-storage classes and field for creating safe default collections.
from typing import Set, Dict, Tuple, Optional, List                        # Imports type hints for sets, dictionaries, tuples, optional values, and lists.
from copy import deepcopy                                                  # Imports deepcopy so complete independent copies of WorldState can be created.

from pddl_parser import PddlProblem                                        # Imports the parsed PDDL problem class used to create the initial WorldState.


# ---------------------------------------------------------------------------
# Plan action (a single step from the sas_plan output)
# ---------------------------------------------------------------------------

@dataclass                                                                  # Automatically creates methods such as __init__() for PlanAction.
class PlanAction:                                                           # Defines an object representing one action returned by Fast Downward.
    """A grounded plan action, e.g. (drive truck1 l3 l2 t0 t1)."""          # Class docstring providing an example of a complete plan action.

    name: str                                                               # Stores the action name, such as drive, load, unload, or deliver.
    args: List[str]                                                         # Stores the action arguments in their original order.

    def __str__(self):                                                      # Defines how a PlanAction should appear when converted into readable text.
        return f"({self.name} {' '.join(self.args)})"                       # Returns text such as "(drive truck1 l3 l2 t0 t1)".


# ---------------------------------------------------------------------------
# World state
# ---------------------------------------------------------------------------

@dataclass                                                                  # Automatically creates an initializer and other common methods for WorldState.
class WorldState:                                                           # Defines the mutable object containing the simulator's current world information.
    """Mutable snapshot of the trucks-domain world."""                      # Class docstring explaining that this object represents one moment in the simulation.

    # Truck locations: truck_name -> location
    truck_locations: Dict[str, str] = field(default_factory=dict)           # Maps each active truck name to its current location.

    # Package locations: package_name -> location  (only for packages on the ground)
    package_locations: Dict[str, str] = field(default_factory=dict)         # Maps each package on the ground to its current location.

    # Packages in trucks: (package, truck, area) tuples
    cargo: Set[Tuple[str, str, str]] = field(default_factory=set)           # Stores records identifying each package currently inside a truck and cargo area.

    # Free truck areas: (area, truck) tuples
    free_areas: Set[Tuple[str, str]] = field(default_factory=set)           # Stores truck cargo areas that are currently unoccupied.

    # Road connections: (from_loc, to_loc) tuples — mutable for road closures
    connections: Set[Tuple[str, str]] = field(default_factory=set)          # Stores directed roads between locations and can be changed when roads close.

    # Closer relations: (a1, a2) meaning a1 is closer to the cab than a2
    closer: Set[Tuple[str, str]] = field(default_factory=set)               # Stores ordering relationships between truck cargo areas.

    # Current time step name (e.g. "t0")
    current_time: str = "t0"                                                # Stores the simulator's current symbolic time and begins at t0 by default.

    # Time ordering: list of time step names in order [t0, t1, t2, ...]
    time_steps: List[str] = field(default_factory=list)                     # Stores all time-step names in chronological order.

    # Set of delivered packages: (package, location, deadline_time)
    delivered: Set[Tuple[str, str, str]] = field(default_factory=set)       # Stores completed delivery records containing package, location, and delivery time.

    # Packages that reached their destination: (package, location)
    at_destination: Set[Tuple[str, str]] = field(default_factory=set)       # Stores packages that reached their required destination locations.

    # le predicates: (t1, t2) pairs
    le_predicates: Set[Tuple[str, str]] = field(default_factory=set)        # Stores PDDL less-than-or-equal time relationships.

    # All objects by type for PDDL regeneration
    objects: Dict[str, List[str]] = field(default_factory=dict)             # Stores every parsed PDDL object grouped by object type.

    # All trucks in the problem (to track breakdowns)
    all_trucks: List[str] = field(default_factory=list)                     # Stores every truck name so the simulator can track active and broken trucks.

    # All packages (including dynamically added ones)
    all_packages: List[str] = field(default_factory=list)                   # Stores original packages and packages added by new-delivery anomalies.

    # All locations
    all_locations: List[str] = field(default_factory=list)                  # Stores every location defined in the PDDL problem.

    # All truck areas
    all_areas: List[str] = field(default_factory=list)                      # Stores every truck cargo-area object.

    # Road distance in integer miles: (from_loc, to_loc) -> miles
    road_distance: Dict[Tuple[str, str], int] = field(default_factory=dict)  # Stores each directed road's length in whole miles.

    # Road speed in integer mph: (from_loc, to_loc) -> mph
    road_speed: Dict[Tuple[str, str], int] = field(default_factory=dict)    # Stores each directed road's speed limit in miles per hour.

    # Grid coordinates (1 cell = 1 mile): location -> x / y
    loc_x: Dict[str, int] = field(default_factory=dict)                     # Stores each location's horizontal grid coordinate.
    loc_y: Dict[str, int] = field(default_factory=dict)                     # Stores each location's vertical grid coordinate.

    def road_duration(self, from_loc: str, to_loc: str) -> int:              # Computes a road's rounded travel time in hours.
        """Return the rounded travel time (in whole hours/ticks) for a road.

        Round-half-up, no minimum: 35mi@30mph -> 1t, 85mi@30mph -> 3t,
        45mi@30mph -> 2t, 10mi@30mph -> 0t (instant hop).
        Roads without metrics (original problems) count as 1t.
        """
        d = self.road_distance.get((from_loc, to_loc))                     # Gets the road's distance in miles.
        s = self.road_speed.get((from_loc, to_loc))                        # Gets the road's speed in mph.

        if d is None or s is None or s <= 0:
            return 1                                                       # Legacy problem without road metrics: keep 1t per drive.

        return (2 * d + s) // (2 * s)                                     # floor(d/s + 0.5), i.e. round-half-up, using integers only.

    def has_road_metrics(self) -> bool:                                     # Reports whether the problem carries distance/speed data.
        """True when at least one road has a distance and a speed."""
        return bool(self.road_distance) and bool(self.road_speed)

    def copy(self) -> 'WorldState':                                         # Returns an independent copy of the current state.
        """Return a deep copy of this state."""
        return deepcopy(self)

    def get_next_time(self) -> Optional[str]:                               # Returns the time step immediately after current_time.
        """Return the time step after the current one, or None if at the end."""

        try:
            idx = self.time_steps.index(self.current_time)

            if idx + 1 < len(self.time_steps):
                return self.time_steps[idx + 1]

        except ValueError:
            pass

        return None

    def get_remaining_time_steps(self) -> List[str]:                        # Returns current_time and every later time step.
        """Return time steps from current_time onward (inclusive)."""

        try:
            idx = self.time_steps.index(self.current_time)
            return self.time_steps[idx:]

        except ValueError:
            return self.time_steps


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def _time_key(t: str) -> int:                                               # Sort key for time names: t0, t1, t2, ...
    return int(t[1:]) if t[1:].isdigit() else 0


def initialize_from_problem(problem: PddlProblem) -> WorldState:            # Converts a parsed PDDL problem into the simulator's starting state.
    """Build an initial WorldState from a parsed PDDL problem."""

    state = WorldState()
    state.objects = deepcopy(problem.objects)

    # Collect typed objects
    state.all_trucks = list(problem.objects.get('truck', []))
    state.all_packages = list(problem.objects.get('package', []))
    state.all_locations = list(problem.objects.get('location', []))
    state.all_areas = list(problem.objects.get('truckarea', []))

    # Build ordered time steps (sorted by numeric suffix: t0, t1, t2, ...)
    state.time_steps = sorted(problem.objects.get('time', []), key=_time_key)

    # Process init facts
    for pred, args in problem.init_facts:

        if pred == 'at':                                                    # An object is at a location.
            obj_name, loc = args[0], args[1]

            if obj_name in state.all_trucks:
                state.truck_locations[obj_name] = loc

            elif obj_name in state.all_packages:
                state.package_locations[obj_name] = loc

        elif pred == 'free':                                                # A truck cargo area is free.
            area, truck = args[0], args[1]
            state.free_areas.add((area, truck))

        elif pred == 'connected':                                           # A directed road.
            state.connections.add((args[0], args[1]))

        elif pred == 'road-distance':                                      # A road's distance in miles, e.g. d35.
            try:
                state.road_distance[(args[0], args[1])] = int(args[2][1:])
            except (ValueError, IndexError):
                pass

        elif pred == 'road-speed':                                         # A road's speed in mph, e.g. s30.
            try:
                state.road_speed[(args[0], args[1])] = int(args[2][1:])
            except (ValueError, IndexError):
                pass

        elif pred == 'loc-x':                                              # A location's grid x coordinate, e.g. c12.
            try:
                state.loc_x[args[0]] = int(args[1][1:])
            except (ValueError, IndexError):
                pass

        elif pred == 'loc-y':                                              # A location's grid y coordinate.
            try:
                state.loc_y[args[0]] = int(args[1][1:])
            except (ValueError, IndexError):
                pass

        elif pred == 'closer':                                              # Cargo-area loading order.
            state.closer.add((args[0], args[1]))

        elif pred == 'time-now':                                            # Starting time.
            state.current_time = args[0]

        elif pred == 'le':                                                  # Less-than-or-equal time relation.
            state.le_predicates.add((args[0], args[1]))

        elif pred == 'in':                                                  # A package starts inside a truck: in ?p ?t ?a
            state.cargo.add((args[0], args[1], args[2]))

    return state


def _ensure_time(state: WorldState, t: str):                               # Keeps the ordered time list in sync.
    """Add a time-step name to state.time_steps if it is missing.

    Used when a replanned plan references extended horizon times (t7, t8, ...)
    that were created by the replan writer but do not exist in the original
    problem's time list.
    """
    if t in state.time_steps:
        return

    state.time_steps.append(t)
    state.time_steps.sort(key=_time_key)


# ---------------------------------------------------------------------------
# Action validation and application
# ---------------------------------------------------------------------------

EXPECTED_ARG_COUNTS = {"drive": 5, "drive-instant": 4, "load": 4, "unload": 4, "deliver": 4}


def validate_action(state: WorldState, action: PlanAction) -> Optional[str]:
    """Return an error message when an action is not valid in the current state."""
    name = action.name.lower()
    args = action.args

    if name not in EXPECTED_ARG_COUNTS:
        return f"unknown action '{action.name}'"
    if len(args) != EXPECTED_ARG_COUNTS[name]:
        return f"{name} expects {EXPECTED_ARG_COUNTS[name]} arguments, got {len(args)}"

    if name in ("drive", "drive-instant"):
        truck, from_loc, to_loc, t1 = args[:4]
        if state.truck_locations.get(truck) != from_loc:
            return f"{truck} is not at {from_loc}"
        if (from_loc, to_loc) not in state.connections:
            return f"no active road connects {from_loc} to {to_loc}"
        if state.current_time != t1:
            return f"current time is {state.current_time}, not {t1}"
        if t1 not in state.time_steps:
            return f"unknown time step {t1}"

        expected = state.road_duration(from_loc, to_loc)                    # 1 for problems without road data.

        if name == "drive-instant":
            if expected != 0:
                return f"{from_loc}->{to_loc} takes {expected}t, so it cannot be an instant drive"
        else:
            t2 = args[4]
            if t2 not in state.time_steps:
                return f"unknown time step {t2}"
            gap = state.time_steps.index(t2) - state.time_steps.index(t1)
            if gap != expected:
                return f"{from_loc}->{to_loc} takes {expected}t, but the plan uses {gap}t ({t1}->{t2})"

    elif name == "load":
        package, truck, area, location = args
        if state.truck_locations.get(truck) != location:
            return f"{truck} is not at {location}"
        if state.package_locations.get(package) != location:
            return f"{package} is not at {location}"
        if (area, truck) not in state.free_areas:
            return f"area {area} on {truck} is not free"
        blocked = [
            closer_area for closer_area, farther_area in state.closer
            if farther_area == area and (closer_area, truck) not in state.free_areas
        ]
        if blocked:
            return f"closer area(s) {', '.join(sorted(blocked))} must be free"

    elif name == "unload":
        package, truck, area, location = args
        if state.truck_locations.get(truck) != location:
            return f"{truck} is not at {location}"
        if (package, truck, area) not in state.cargo:
            return f"{package} is not in area {area} on {truck}"
        blocked = [
            closer_area for closer_area, farther_area in state.closer
            if farther_area == area and (closer_area, truck) not in state.free_areas
        ]
        if blocked:
            return f"closer area(s) {', '.join(sorted(blocked))} must be free"

    elif name == "deliver":
        package, location, t1, t2 = args
        if state.package_locations.get(package) != location:
            return f"{package} is not at {location}"
        if state.current_time != t1:
            return f"current time is {state.current_time}, not {t1}"
        if (t1, t2) not in state.le_predicates:
            return f"deadline {t2} is earlier than {t1} or is unknown"

    return None


def apply_action(state: WorldState, action: PlanAction) -> WorldState:       # Changes the current state according to one completed plan action.
    """
    Validate a grounded plan action, then apply it to the world state
    (in place) and return it. Raises ValueError for an invalid action.

    Actions:
        (drive ?truck ?from ?to ?t1 ?t2)
        (drive-instant ?truck ?from ?to ?t1)
        (load ?package ?truck ?area ?location)
        (unload ?package ?truck ?area ?location)
        (deliver ?package ?location ?t1 ?t2)
    """

    error = validate_action(state, action)
    if error:
        raise ValueError(f"Invalid action {action}: {error}")

    name = action.name.lower()
    args = action.args

    if name == 'drive':                                                     # Moves a truck and advances the clock by the road's travel time.
        truck, from_loc, to_loc, t1, t2 = args
        _ensure_time(state, t2)
        state.truck_locations[truck] = to_loc
        state.current_time = t2

    elif name == 'drive-instant':                                           # 0t road: the truck moves, the clock does not.
        truck, from_loc, to_loc, t1 = args
        state.truck_locations[truck] = to_loc

    elif name == 'load':                                                    # Package leaves the ground and enters a free cargo area.
        package, truck, area, location = args

        if package in state.package_locations:
            del state.package_locations[package]

        state.cargo.add((package, truck, area))
        state.free_areas.discard((area, truck))

    elif name == 'unload':                                                  # Package leaves the truck and is placed on the ground.
        package, truck, area, location = args

        state.cargo.discard((package, truck, area))
        state.package_locations[package] = location
        state.free_areas.add((area, truck))

    elif name == 'deliver':                                                 # Package is handed over at its destination.
        package, location, t1, t2 = args

        if package in state.package_locations:
            del state.package_locations[package]

        state.delivered.add((package, location, t2))
        state.at_destination.add((package, location))

    return state


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def state_summary(state: WorldState, include_roads: bool = False) -> str:   # Converts a WorldState into a short readable report.
    """Return a concise human-readable summary of the current world state.

    visualizer.py parses these lines, so keep their format stable.
    """

    lines = [f"  Time: {state.current_time}"]

    for truck in sorted(state.all_trucks):
        loc = state.truck_locations.get(truck, "???")
        cargo_list = [p for p, t, a in state.cargo if t == truck]
        cargo_str = f" carrying [{', '.join(sorted(cargo_list))}]" if cargo_list else ""
        lines.append(f"  {truck} @ {loc}{cargo_str}")

    ground_pkgs = sorted(state.package_locations.items())

    if ground_pkgs:
        lines.append(
            f"  Packages on ground: "
            f"{', '.join(f'{p}@{l}' for p, l in ground_pkgs)}"
        )

    if state.delivered:
        lines.append(
            f"  Delivered: "
            f"{', '.join(f'{p}→{l}' for p, l, _ in sorted(state.delivered))}"
        )

    if include_roads and state.connections and state.has_road_metrics():
        lines.append("  Roads (distance @ speed = travel time):")

        for from_loc, to_loc in sorted(state.connections):
            d = state.road_distance.get((from_loc, to_loc))
            s = state.road_speed.get((from_loc, to_loc))

            if d is not None and s is not None:
                dur = state.road_duration(from_loc, to_loc)
                lines.append(f"    {from_loc} → {to_loc}: {d}mi @ {s}mph = {dur}t")

    return '\n'.join(lines)
