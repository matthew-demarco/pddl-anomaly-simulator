```python
"""
Anomaly Generator for the Trucks Domain Simulation.

Defines anomaly types and provides random injection logic to disrupt
plan execution, triggering the Case-Based Reasoner and replanning.
"""                                                                         # Module docstring explaining the overall purpose of anomalies.py.


import random                                                               # Imports Python's random-number tools for choosing when and which anomalies occur.

from dataclasses import dataclass, field                                    # Imports dataclass for data-storage classes and field for creating safe default values.

from enum import Enum, auto                                                 # Imports Enum for defining fixed anomaly categories and auto() for automatically assigning their values.

from typing import List, Tuple, Optional, Dict, Any                          # Imports type hints for lists, tuples, optional values, dictionaries, and values of any type.

from state import WorldState, PlanAction                                    # Imports WorldState and PlanAction so anomaly logic can examine the current state and upcoming action.


# ---------------------------------------------------------------------------
# Anomaly types
# ---------------------------------------------------------------------------

class AnomalyType(Enum):                                                    # Defines a fixed collection of allowed anomaly types.
    """Types of anomalies that can occur during plan execution."""          # Class docstring explaining what AnomalyType represents.

    ROAD_CLOSURE = auto()                                                   # Represents a road becoming unavailable; auto() automatically assigns an internal value.
    TRUCK_BREAKDOWN = auto()                                                # Represents a truck breaking down and being unable to continue operating.
    NEW_DELIVERY = auto()                                                   # Represents a new urgent package being added during the simulation.
    DEADLINE_CHANGE = auto()                                                # Represents a package's delivery deadline becoming earlier.


# ---------------------------------------------------------------------------
# Anomaly event
# ---------------------------------------------------------------------------

@dataclass                                                                  # Automatically creates methods such as __init__() for the AnomalyEvent data-storage class.
class AnomalyEvent:                                                         # Defines an object that represents one specific anomaly occurrence.
    """Describes a specific anomaly that occurred during simulation."""      # Class docstring explaining the purpose of AnomalyEvent.

    anomaly_type: AnomalyType                                               # Stores the anomaly's category, such as ROAD_CLOSURE or TRUCK_BREAKDOWN.
    description: str                                                        # Stores a human-readable explanation of what happened.
    details: Dict[str, Any] = field(default_factory=dict)                   # Stores anomaly-specific information in a new dictionary for each AnomalyEvent.

    # details contains type-specific information:
    # ROAD_CLOSURE example:    {"from": "l1", "to": "l2"}
    # TRUCK_BREAKDOWN example: {"truck": "truck1", "location": "l2"}
    # NEW_DELIVERY example:    {"package": "package_new1", "origin": "l1", "destination": "l3"}
    # DEADLINE_CHANGE example: {"package": "package3", "old_deadline": "t8", "new_deadline": "t4"}


# ---------------------------------------------------------------------------
# Anomaly generator
# ---------------------------------------------------------------------------

class AnomalyGenerator:                                                     # Defines the component responsible for randomly generating anomalies.
    """
    Generates random anomalies during simulation.

    Configurable probability per step. Only generates anomalies that make
    sense given the current world state (e.g., won't close a road that
    doesn't exist, won't break a truck that's already broken).
    """                                                                     # Class docstring explaining the generator's purpose and restrictions.

    def __init__(                                                           # Defines the constructor that runs when an AnomalyGenerator object is created.
        self,                                                               # Refers to the particular AnomalyGenerator object being initialized.
        anomaly_chance: float = 0.2,                                        # Probability of attempting an anomaly; 0.2 represents a 20% chance.
        seed: Optional[int] = None,                                         # Optional random seed used to reproduce the same random choices.
        max_anomalies: int = 5,                                             # Maximum number of anomalies that may occur in one simulation.
    ):
        """
        Args:
            anomaly_chance: Probability [0, 1] of an anomaly per drive action.
            seed: Random seed for reproducibility.
            max_anomalies: Maximum total anomalies per simulation.
        """                                                                 # Method docstring explaining each constructor argument.

        self.anomaly_chance = anomaly_chance                                # Stores the probability used whenever the generator checks for an anomaly.
        self.rng = random.Random(seed)                                      # Creates a separate random-number generator using the optional seed.
        self.max_anomalies = max_anomalies                                  # Stores the maximum number of anomalies allowed.
        self.anomalies_triggered = 0                                        # Starts the count of generated anomalies at zero.
        self._new_package_counter = 0                                       # Starts an internal counter used to create unique names for new packages.

    def maybe_trigger(                                                       # Defines the main method that checks whether an anomaly should occur.
        self,                                                               # Refers to the current AnomalyGenerator object.
        state: WorldState,                                                  # Receives the current simulation WorldState.
        current_action: PlanAction,                                         # Receives the action that is about to execute.
    ) -> Optional[AnomalyEvent]:                                            # Returns either an AnomalyEvent or None when no anomaly occurs.
        """
        Potentially trigger an anomaly before the given action executes.

        Only triggers on 'drive' actions (anomalies happen en route).
        Returns an AnomalyEvent if triggered, None otherwise.
        """                                                                 # Method docstring explaining the anomaly check.

        if self.anomalies_triggered >= self.max_anomalies:                  # Checks whether the maximum number of anomalies has already occurred.
            return None                                                     # Returns no anomaly when the maximum has been reached.

        # Only trigger anomalies on drive actions
        if current_action.name.lower() != 'drive':                          # Converts the action name to lowercase and checks whether it is not "drive".
            return None                                                     # Returns no anomaly for load, unload, or other non-drive actions.

        if self.rng.random() > self.anomaly_chance:                         # Generates a decimal from 0 to 1 and compares it with the anomaly probability.
            return None                                                     # Returns no anomaly when the random value is outside the allowed probability.

        # Choose an anomaly type randomly
        available_types = self._get_available_types(state, current_action)  # Determines which anomaly types are currently valid.
        if not available_types:                                             # Checks whether the list of valid anomaly types is empty.
            return None                                                     # Returns no anomaly when none of the anomaly types can currently occur.

        anomaly_type = self.rng.choice(available_types)                     # Randomly selects one valid anomaly type from the list.
        event = self._generate_event(anomaly_type, state, current_action)   # Attempts to build a complete AnomalyEvent of the chosen type.

        if event:                                                           # Checks whether an event was successfully created.
            self.anomalies_triggered += 1                                   # Increases the count of generated anomalies by one.

        return event                                                        # Returns the AnomalyEvent or None if event generation failed.

    def _get_available_types(                                               # Defines an internal method that finds which anomaly categories are currently allowed.
        self,                                                               # Refers to the current AnomalyGenerator object.
        state: WorldState,                                                  # Receives the current simulation state.
        action: PlanAction,                                                 # Receives the upcoming plan action.
    ) -> List[AnomalyType]:                                                 # Returns a list containing valid AnomalyType values.
        """Determine which anomaly types are valid given current state."""  # Method docstring describing its purpose.

        available = []                                                      # Creates an empty list that will hold the valid anomaly types.

        # Road closure: need at least some connections beyond the essentials
        if len(state.connections) > 2:                                      # Checks whether the state contains more than two road connections.
            available.append(AnomalyType.ROAD_CLOSURE)                      # Adds ROAD_CLOSURE to the valid choices.

        # Truck breakdown: only allow if more than one truck remains
        # Breaking the last truck makes the problem unsolvable
        active_truck_count = len(                                           # Calculates the number of trucks that are still active.
            [t for t in state.all_trucks if t in state.truck_locations]     # Builds a list containing trucks that still have an active location entry.
        )

        if active_truck_count > 1:                                          # Checks whether more than one active truck remains.
            available.append(AnomalyType.TRUCK_BREAKDOWN)                   # Allows a truck breakdown only when another truck can continue the work.

        # New delivery: always possible
        available.append(AnomalyType.NEW_DELIVERY)                          # Always adds NEW_DELIVERY as a possible anomaly type.

        # Deadline change: need existing timed deliveries in the remaining goals
        available.append(AnomalyType.DEADLINE_CHANGE)                       # Adds DEADLINE_CHANGE as a possible anomaly type.

        return available                                                    # Returns the completed list of currently valid anomaly types.

    def _generate_event(                                                     # Defines an internal method that sends event creation to the correct helper method.
        self,                                                               # Refers to the current AnomalyGenerator object.
        anomaly_type: AnomalyType,                                          # Receives the category of anomaly that should be generated.
        state: WorldState,                                                  # Receives the current simulation state.
        action: PlanAction,                                                 # Receives the upcoming action.
    ) -> Optional[AnomalyEvent]:                                            # Returns a completed AnomalyEvent or None if creation fails.
        """Generate a specific anomaly event of the given type."""          # Method docstring describing its purpose.

        if anomaly_type == AnomalyType.ROAD_CLOSURE:                        # Checks whether a road closure was selected.
            return self._gen_road_closure(state, action)                    # Calls the road-closure generator and immediately returns its result.

        elif anomaly_type == AnomalyType.TRUCK_BREAKDOWN:                   # Checks whether a truck breakdown was selected.
            return self._gen_truck_breakdown(state, action)                 # Calls the truck-breakdown generator and returns its result.

        elif anomaly_type == AnomalyType.NEW_DELIVERY:                      # Checks whether a new delivery was selected.
            return self._gen_new_delivery(state, action)                    # Calls the new-delivery generator and returns its result.

        elif anomaly_type == AnomalyType.DEADLINE_CHANGE:                   # Checks whether a deadline change was selected.
            return self._gen_deadline_change(state, action)                 # Calls the deadline-change generator and returns its result.

        return None                                                         # Returns None if the anomaly type did not match any known category.

    def _gen_road_closure(                                                   # Defines the helper method that creates a road-closure event.
        self,                                                               # Refers to the current AnomalyGenerator object.
        state: WorldState,                                                  # Receives the current simulation state.
        action: PlanAction,                                                 # Receives the upcoming drive action.
    ) -> Optional[AnomalyEvent]:                                            # Returns a road-closure event or None if a safe closure cannot be created.
        """Generate a road closure anomaly (maintains graph connectivity)."""  # Explains that the closure should not disconnect the complete map.

        connections = list(state.connections)                              # Converts the state's road-connection collection into a list.

        if len(connections) < 6:                                            # Checks whether there are fewer than six road connections.
            return None                                                     # Avoids closing a road when the map is too small to safely remove one.

        truck, from_loc, to_loc = action.args[0], action.args[1], action.args[2]  # Extracts the truck, starting location, and destination from the drive action.

        # 50% chance to close the exact road being used, 50% a random one
        if self.rng.random() < 0.5 and (from_loc, to_loc) in state.connections:  # Checks whether the current road should be selected and actually exists.
            closed_from, closed_to = from_loc, to_loc                       # Selects the road that the truck was about to use.
        else:                                                               # Runs when the current road is not selected.
            conn = self.rng.choice(connections)                             # Randomly chooses a connection from all available roads.
            closed_from, closed_to = conn                                   # Separates the selected connection into its start and end locations.

        # Connectivity check: ensure all locations remain reachable
        test_conns = set(state.connections)                                 # Creates a copy of the current connection set for testing.
        test_conns.discard((closed_from, closed_to))                        # Removes the selected road from the test copy.

        if not self._is_connected(state.all_locations, test_conns):         # Checks whether all locations would remain reachable after the road is removed.
            return None                                                     # Cancels the road closure if it would disconnect the map.

        return AnomalyEvent(                                                # Creates and returns a completed road-closure event.
            anomaly_type=AnomalyType.ROAD_CLOSURE,                          # Records the anomaly category as ROAD_CLOSURE.
            description=f"Road closure: the road from {closed_from} to {closed_to} is now blocked!",  # Creates a human-readable description.
            details={"from": closed_from, "to": closed_to},                 # Stores the closed road's starting and ending locations.
        )

    @staticmethod                                                           # Marks _is_connected as a method that does not require self or a class object.
    def _is_connected(locations: List[str], connections: set) -> bool:      # Defines a helper method that checks whether all locations remain reachable.
        """Check if all locations are reachable via BFS on directed edges."""  # Explains that the method uses breadth-first search on directed roads.

        if not locations:                                                   # Checks whether there are no locations.
            return True                                                     # Treats an empty map as connected.

        visited = {locations[0]}                                            # Creates a set containing the first location as the starting visited location.
        queue = [locations[0]]                                              # Creates a queue starting with the first location.

        while queue:                                                        # Continues searching while there are locations left in the queue.
            loc = queue.pop(0)                                              # Removes and stores the first location in the queue.

            for f, t in connections:                                        # Examines every directed connection from location f to location t.
                if f == loc and t not in visited:                           # Checks whether the connection leaves the current location and reaches an unvisited location.
                    visited.add(t)                                          # Marks the destination as visited.
                    queue.append(t)                                         # Adds the destination to the queue so its outgoing roads are also explored.

        return len(visited) == len(locations)                               # Returns True only when every location was reached.

    def _gen_truck_breakdown(                                                # Defines the helper method that creates a truck-breakdown event.
        self,                                                               # Refers to the current AnomalyGenerator object.
        state: WorldState,                                                  # Receives the current simulation state.
        action: PlanAction,                                                 # Receives the upcoming drive action.
    ) -> Optional[AnomalyEvent]:                                            # Returns a truck-breakdown event.
        """Generate a truck breakdown anomaly."""                           # Method docstring explaining its purpose.

        truck = action.args[0]                                              # Gets the truck name from the first argument of the drive action.
        loc = state.truck_locations.get(truck, action.args[1])              # Gets the truck's current location or uses the action's starting location as a fallback.

        return AnomalyEvent(                                                # Creates and returns a completed truck-breakdown event.
            anomaly_type=AnomalyType.TRUCK_BREAKDOWN,                       # Records the anomaly category as TRUCK_BREAKDOWN.
            description=f"Truck breakdown: {truck} has broken down at {loc}!",  # Creates a human-readable description.
            details={"truck": truck, "location": loc},                      # Stores the broken truck's name and location.
        )

    def _gen_new_delivery(                                                   # Defines the helper method that creates a new-delivery event.
        self,                                                               # Refers to the current AnomalyGenerator object.
        state: WorldState,                                                  # Receives the current simulation state.
        action: PlanAction,                                                 # Receives the upcoming action, although this method does not use it directly.
    ) -> Optional[AnomalyEvent]:                                            # Returns a new-delivery event or None if there are not enough locations.
        """Generate a new emergency delivery anomaly."""                    # Method docstring explaining its purpose.

        self._new_package_counter += 1                                      # Increases the new-package counter to produce a unique package name.
        pkg_name = f"package_new{self._new_package_counter}"                # Creates a name such as package_new1 or package_new2.

        # Pick random origin and destination (different locations)
        locations = list(state.all_locations)                              # Converts all known locations into a list.

        if len(locations) < 2:                                              # Checks whether fewer than two locations exist.
            return None                                                     # Cancels the event because origin and destination must be different.

        origin = self.rng.choice(locations)                                 # Randomly chooses the package's starting location.
        dest = self.rng.choice([l for l in locations if l != origin])       # Randomly chooses a destination different from the origin.

        return AnomalyEvent(                                                # Creates and returns a completed new-delivery event.
            anomaly_type=AnomalyType.NEW_DELIVERY,                          # Records the anomaly category as NEW_DELIVERY.
            description=f"New delivery: emergency {pkg_name} appeared at {origin}, must reach {dest}!",  # Creates a readable event description.
            details={                                                       # Begins the dictionary containing new-delivery-specific information.
                "package": pkg_name,                                        # Stores the generated package name.
                "origin": origin,                                           # Stores the package's starting location.
                "destination": dest,                                        # Stores the package's required destination.
            },
        )

    def _gen_deadline_change(                                                # Defines the helper method that creates a deadline-change event.
        self,                                                               # Refers to the current AnomalyGenerator object.
        state: WorldState,                                                  # Receives the current simulation state.
        action: PlanAction,                                                 # Receives the upcoming action, although this method does not use it directly.
    ) -> Optional[AnomalyEvent]:                                            # Returns a deadline-change event or None if no valid deadline can be created.
        """Generate a deadline tightening anomaly."""                       # Method docstring explaining its purpose.

        # Find the current time index
        try:                                                                # Attempts to find the current time in the ordered list of time steps.
            current_idx = state.time_steps.index(state.current_time)        # Stores the numerical index of the current time.
        except ValueError:                                                  # Handles the case where current_time is not found in time_steps.
            return None                                                     # Cancels the anomaly because a valid later deadline cannot be calculated.

        remaining = state.time_steps[current_idx + 1:]                      # Creates a list containing only the time steps after the current time.

        if len(remaining) < 2:                                              # Checks whether fewer than two future time steps remain.
            return None                                                     # Cancels the anomaly because there is not enough room to tighten a deadline.

        # Pick a package that has not been delivered yet and is still on the ground or in a truck
        undelivered = []                                                    # Creates an empty list for packages that have not yet been delivered.

        for pkg in state.all_packages:                                      # Examines every package known to the state.
            if not any(p == pkg for p, _, _ in state.delivered):            # Checks whether the package does not appear in any completed-delivery record.
                undelivered.append(pkg)                                     # Adds the package to the list of possible deadline-change targets.

        if not undelivered:                                                 # Checks whether every package has already been delivered.
            return None                                                     # Cancels the event because there is no package whose deadline can be changed.

        pkg = self.rng.choice(undelivered)                                  # Randomly chooses an undelivered package.

        # New deadline: somewhere between now and the end (tighter)
        new_deadline = self.rng.choice(                                     # Randomly chooses an earlier deadline from the first half of the remaining time steps.
            remaining[:max(1, len(remaining) // 2)]                         # Keeps at least one possible time and limits choices to earlier remaining times.
        )

        return AnomalyEvent(                                                # Creates and returns a completed deadline-change event.
            anomaly_type=AnomalyType.DEADLINE_CHANGE,                       # Records the anomaly category as DEADLINE_CHANGE.
            description=f"Deadline change: {pkg} must now be delivered by {new_deadline}!",  # Creates a human-readable description.
            details={                                                       # Begins the dictionary containing deadline-specific information.
                "package": pkg,                                             # Stores the package whose deadline was changed.
                "new_deadline": new_deadline,                               # Stores the newly selected earlier deadline.
            },
        )
```
