"""
World State Management for the Trucks Domain Simulation.

Maintains the mutable world state during plan execution and provides
action-application logic for the four domain actions: drive, load, unload, deliver.
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

    def copy(self) -> 'WorldState':                                         # Defines a method that returns an independent copy of the current state.
        """Return a deep copy of this state."""                             # Method docstring explaining that nested collections are also copied.
        return deepcopy(self)                                               # Creates and returns a copy whose data can be changed without affecting the original state.

    def get_next_time(self) -> Optional[str]:                               # Defines a method that returns the time step immediately after current_time.
        """Return the time step after the current one, or None if at the end."""  # Method docstring explaining the return value.

        try:                                                                # Attempts to find current_time inside the ordered time-step list.
            idx = self.time_steps.index(self.current_time)                  # Stores the numerical position of current_time in time_steps.

            if idx + 1 < len(self.time_steps):                              # Checks whether another time step exists after the current one.
                return self.time_steps[idx + 1]                             # Returns the next chronological time step.

        except ValueError:                                                  # Handles the case where current_time is not found in time_steps.
            pass                                                            # Does nothing and allows the method to return None.

        return None                                                         # Returns None if there is no next time or the current time could not be found.

    def get_remaining_time_steps(self) -> List[str]:                        # Defines a method that returns current_time and every later time step.
        """Return time steps from current_time onward (inclusive)."""       # Method docstring explaining that the current time is included.

        try:                                                                # Attempts to locate current_time inside the time-step list.
            idx = self.time_steps.index(self.current_time)                  # Stores the position of current_time.
            return self.time_steps[idx:]                                    # Returns a slice beginning at current_time and continuing to the end.

        except ValueError:                                                  # Handles the case where current_time is missing from time_steps.
            return self.time_steps                                          # Returns the complete list as a fallback.


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def initialize_from_problem(problem: PddlProblem) -> WorldState:            # Defines a function that converts a parsed PDDL problem into the simulator's starting state.
    """Build an initial WorldState from a parsed PDDL problem."""            # Function docstring explaining its purpose.

    state = WorldState()                                                    # Creates a new WorldState with empty collections and default values.
    state.objects = deepcopy(problem.objects)                               # Copies the parsed PDDL object dictionary into the state.

    # Collect typed objects
    state.all_trucks = list(problem.objects.get('truck', []))               # Copies all objects of type truck, or uses an empty list if none exist.
    state.all_packages = list(problem.objects.get('package', []))           # Copies all objects of type package.
    state.all_locations = list(problem.objects.get('location', []))         # Copies all objects of type location.
    state.all_areas = list(problem.objects.get('truckarea', []))            # Copies all objects of type truckarea.

    # Build ordered time steps
    time_objs = problem.objects.get('time', [])                             # Gets the time objects from the parsed PDDL problem.

    # Sort by numeric suffix: t0, t1, t2, ...
    state.time_steps = sorted(                                              # Sorts the time names into chronological numeric order.
        time_objs,                                                          # Supplies the list of parsed time objects.
        key=lambda t: int(t[1:]) if t[1:].isdigit() else 0,                 # Extracts the number after "t"; names without a numeric suffix are treated as zero.
    )

    # Process init facts
    for pred, args in problem.init_facts:                                   # Loops through every predicate and argument list in the original PDDL initial state.

        if pred == 'at':                                                    # Checks whether the fact says an object is at a location.
            obj_name, loc = args[0], args[1]                               # Retrieves the object's name and location.

            if obj_name in state.all_trucks:                                # Checks whether the object is a truck.
                state.truck_locations[obj_name] = loc                       # Records the truck at that location.

            elif obj_name in state.all_packages:                            # Checks whether the object is a package.
                state.package_locations[obj_name] = loc                     # Records the package on the ground at that location.

        elif pred == 'free':                                                # Checks whether the fact says a truck cargo area is free.
            area, truck = args[0], args[1]                                  # Retrieves the area and truck names.
            state.free_areas.add((area, truck))                             # Adds the free-area record to the state.

        elif pred == 'connected':                                           # Checks whether the fact represents a road connection.
            state.connections.add((args[0], args[1]))                       # Adds the directed connection from the first location to the second.

        elif pred == 'closer':                                              # Checks whether the fact represents a closer relationship between truck areas.
            state.closer.add((args[0], args[1]))                            # Adds the cargo-area ordering relationship.

        elif pred == 'time-now':                                            # Checks whether the fact specifies the starting time.
            state.current_time = args[0]                                    # Sets the state's current time to the provided time name.

        elif pred == 'le':                                                  # Checks whether the fact represents a less-than-or-equal time relationship.
            state.le_predicates.add((args[0], args[1]))                     # Adds the time-ordering pair to the state.

        elif pred == 'in':                                                  # Checks whether the fact says a package begins inside a truck.
            # in ?p ?t ?a
            state.cargo.add((args[0], args[1], args[2]))                    # Adds the package, truck, and cargo-area record to the cargo set.

    return state                                                            # Returns the fully initialized WorldState.


# ---------------------------------------------------------------------------
# Action application
# ---------------------------------------------------------------------------

def apply_action(state: WorldState, action: PlanAction) -> WorldState:       # Defines the function that changes the current state according to one completed plan action.
    """
    Apply a grounded plan action to the world state (in place) and return it.

    Actions:
        (drive ?truck ?from ?to ?t1 ?t2)
        (load ?package ?truck ?area ?location)
        (unload ?package ?truck ?area ?location)
        (deliver ?package ?location ?t1 ?t2)
    """                                                                     # Function docstring listing the expected arguments for each supported action.

    name = action.name.lower()                                              # Converts the action name to lowercase so capitalization does not affect matching.
    args = action.args                                                      # Creates a shorter local reference to the action argument list.

    if name == 'drive':                                                     # Checks whether the current action moves a truck.
        truck, from_loc, to_loc, t1, t2 = args                              # Unpacks the truck, source, destination, starting time, and ending time.
        state.truck_locations[truck] = to_loc                               # Updates the truck's location to the drive destination.
        state.current_time = t2                                             # Advances the world state's current time to the action's ending time.

    elif name == 'load':                                                    # Checks whether the current action loads a package into a truck.
        package, truck, area, location = args                               # Unpacks the package, truck, cargo area, and location.

        # Package leaves the ground
        if package in state.package_locations:                              # Checks whether the package currently has a ground-location record.
            del state.package_locations[package]                            # Removes the package from the ground-location dictionary.

        # Package enters the truck
        state.cargo.add((package, truck, area))                             # Adds a record stating that the package is inside the specified truck area.

        # Area is no longer free
        state.free_areas.discard((area, truck))                             # Removes the cargo area from the free-area set without failing if it is already absent.

    elif name == 'unload':                                                  # Checks whether the current action unloads a package from a truck.
        package, truck, area, location = args                               # Unpacks the package, truck, cargo area, and location.

        # Package leaves the truck
        state.cargo.discard((package, truck, area))                         # Removes the package's cargo record from the truck.

        # Package is now on the ground at the truck's location
        state.package_locations[package] = location                         # Records the package on the ground at the unload location.

        # Area becomes free
        state.free_areas.add((area, truck))                                 # Marks the truck's cargo area as available again.

    elif name == 'deliver':                                                 # Checks whether the current action completes a package delivery.
        package, location, t1, t2 = args                                    # Unpacks the package, destination location, starting time, and ending time.

        # Package is delivered
        if package in state.package_locations:                              # Checks whether the delivered package still has a ground-location record.
            del state.package_locations[package]                            # Removes the package from the ground-location dictionary.

        state.delivered.add((package, location, t2))                        # Adds a completed-delivery record containing package, location, and delivery time.
        state.at_destination.add((package, location))                       # Records that the package reached its destination.

    return state                                                            # Returns the same WorldState object after modifying it in place.


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def state_summary(state: WorldState) -> str:                                # Defines a function that converts a WorldState into a short readable report.
    """Return a concise human-readable summary of the current world state."""  # Function docstring explaining its purpose.

    lines = []                                                              # Creates an empty list for each line of the state summary.
    lines.append(f"  Time: {state.current_time}")                           # Adds the current simulation time as the first summary line.

    for truck in sorted(state.all_trucks):                                  # Loops through all truck names in alphabetical order.
        loc = state.truck_locations.get(truck, "???")                       # Gets the truck's current location or displays ??? if no location exists.
        cargo_list = [p for p, t, a in state.cargo if t == truck]           # Builds a list of package names currently carried by this truck.
        cargo_str = f" carrying [{', '.join(sorted(cargo_list))}]" if cargo_list else ""  # Creates cargo text when the truck is carrying packages.
        lines.append(f"  {truck} @ {loc}{cargo_str}")                       # Adds a summary line showing the truck's location and optional cargo.

    ground_pkgs = sorted(state.package_locations.items())                   # Creates a sorted list of packages currently located on the ground.

    if ground_pkgs:                                                        # Checks whether at least one package is on the ground.
        lines.append(                                                       # Adds one summary line listing all packages on the ground.
            f"  Packages on ground: "
            f"{', '.join(f'{p}@{l}' for p, l in ground_pkgs)}"             # Formats each package as package@location and joins them with commas.
        )

    if state.delivered:                                                    # Checks whether any deliveries have been completed.
        lines.append(                                                       # Adds one summary line listing delivered packages and locations.
            f"  Delivered: "
            f"{', '.join(f'{p}→{l}' for p, l, _ in sorted(state.delivered))}"  # Formats each completed delivery as package→location.
        )

    return '\n'.join(lines)                                                 # Combines all summary lines into one string separated by newline characters.

