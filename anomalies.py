"""
Anomaly Generator for the Trucks Domain Simulation.

Defines anomaly types and provides random injection logic to disrupt
plan execution, triggering the Case-Based Reasoner and replanning.
"""

import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Tuple, Optional, Dict, Any

from state import WorldState, PlanAction


# ---------------------------------------------------------------------------
# Anomaly types
# ---------------------------------------------------------------------------

class AnomalyType(Enum):
    """Types of anomalies that can occur during plan execution."""
    ROAD_CLOSURE = auto()       # A road segment becomes impassable
    TRUCK_BREAKDOWN = auto()    # A truck breaks down and cannot move
    NEW_DELIVERY = auto()       # An urgent new package appears
    DEADLINE_CHANGE = auto()    # A delivery deadline becomes tighter


# ---------------------------------------------------------------------------
# Anomaly event
# ---------------------------------------------------------------------------

@dataclass
class AnomalyEvent:
    """Describes a specific anomaly that occurred during simulation."""
    anomaly_type: AnomalyType
    description: str
    details: Dict[str, Any] = field(default_factory=dict)
    # details contains type-specific information:
    #   ROAD_CLOSURE:    {"from": "l1", "to": "l2"}
    #   TRUCK_BREAKDOWN: {"truck": "truck1", "location": "l2"}
    #   NEW_DELIVERY:    {"package": "package_new1", "origin": "l1", "destination": "l3"}
    #   DEADLINE_CHANGE: {"package": "package3", "old_deadline": "t8", "new_deadline": "t4"}
@dataclass
class ScheduledAnomaly:
    """An anomaly manually selected to occur at a specific execution step."""
    step: int
    anomaly_type: AnomalyType
    details: Dict[str, Any] = field(default_factory=dict)
def create_manual_event(
    scheduled: ScheduledAnomaly,
    state: WorldState,
) -> AnomalyEvent:
        """Validate a scheduled anomaly and convert it into an AnomalyEvent."""

        details = dict(scheduled.details)
        anomaly_type = scheduled.anomaly_type

        if anomaly_type == AnomalyType.ROAD_CLOSURE:
            from_loc = details["from"]
            to_loc = details["to"]

            if (
                (from_loc, to_loc) not in state.connections
                and (to_loc, from_loc) not in state.connections
            ):
                raise ValueError(
                    f"No active road exists between {from_loc} and {to_loc}."
                )

            description = f"Road between {from_loc} and {to_loc} has closed."

        elif anomaly_type == AnomalyType.TRUCK_BREAKDOWN:
            truck = details["truck"]
            location = state.truck_locations.get(truck)

            if location is None:
                raise ValueError(f"{truck} is not an active truck.")

            active_trucks = list(state.truck_locations.keys())

            if len(active_trucks) <= 1:
                raise ValueError(
                    "A truck breakdown cannot occur because only one active truck remains."
                )
            details["location"] = location
            description = f"{truck} has broken down at {location}."

        elif anomaly_type == AnomalyType.NEW_DELIVERY:
            package = details["package"]
            origin = details["origin"]
            destination = details["destination"]

            if package in state.all_packages:
                raise ValueError(f"Package {package} already exists.")

            if origin not in state.all_locations:
                raise ValueError(f"Unknown origin location: {origin}")

            if destination not in state.all_locations:
                raise ValueError(f"Unknown destination location: {destination}")

            if origin == destination:
                raise ValueError("Origin and destination must be different.")

            description = (
                f"New package {package} appeared at {origin} "
                f"and must be delivered to {destination}."
            )

        elif anomaly_type == AnomalyType.DEADLINE_CHANGE:
            package = details["package"]
            new_deadline = details["new_deadline"]

            if package not in state.all_packages:
                raise ValueError(f"Unknown package: {package}")

            if any(p == package for p, _, _ in state.delivered):
                raise ValueError(f"{package} has already been delivered.")

            if new_deadline not in state.get_remaining_time_steps():
                raise ValueError(
                    f"{new_deadline} is not a remaining time step."
                )

            description = (
                f"Deadline for {package} changed to {new_deadline}."
            )

        else:
            raise ValueError(f"Unsupported anomaly type: {anomaly_type}")

        return AnomalyEvent(
            anomaly_type=anomaly_type,
            description=description,
            details=details,
        )
# ---------------------------------------------------------------------------
# Anomaly generator
# ---------------------------------------------------------------------------

class AnomalyGenerator:
    """
    Generates random anomalies during simulation.

    Configurable probability per step. Only generates anomalies that make
    sense given the current world state (e.g., won't close a road that
    doesn't exist, won't break a truck that's already broken).
    """

    def __init__(
        self,
        anomaly_chance: float = 0.2,
        seed: Optional[int] = None,
        max_anomalies: int = 5,
    ):
        """
        Args:
            anomaly_chance: Probability [0, 1] of an anomaly per drive action.
            seed: Random seed for reproducibility.
            max_anomalies: Maximum total anomalies per simulation.
        """
        self.anomaly_chance = anomaly_chance
        self.rng = random.Random(seed)
        self.max_anomalies = max_anomalies
        self.anomalies_triggered = 0
        self._new_package_counter = 0

    def maybe_trigger(
        self,
        state: WorldState,
        current_action: PlanAction,
    ) -> Optional[AnomalyEvent]:
        """
        Potentially trigger an anomaly before the given action executes.

        Only triggers on 'drive' actions (anomalies happen en route).
        Returns an AnomalyEvent if triggered, None otherwise.
        """
        if self.anomalies_triggered >= self.max_anomalies:
            return None

        # Only trigger anomalies on drive actions
        if current_action.name.lower() != 'drive':
            return None

        if self.rng.random() > self.anomaly_chance:
            return None

        # Choose an anomaly type randomly
        available_types = self._get_available_types(state, current_action)
        if not available_types:
            return None

        anomaly_type = self.rng.choice(available_types)
        event = self._generate_event(anomaly_type, state, current_action)

        if event:
            self.anomalies_triggered += 1

        return event

    def _get_available_types(
        self,
        state: WorldState,
        action: PlanAction,
    ) -> List[AnomalyType]:
        """Determine which anomaly types are valid given current state."""
        available = []

        # Road closure: need at least some connections beyond the essentials
        if len(state.connections) > 2:
            available.append(AnomalyType.ROAD_CLOSURE)

        # Truck breakdown: only allow if more than one truck remains
        # Breaking the last truck makes the problem unsolvable
        active_truck_count = len([t for t in state.all_trucks if t in state.truck_locations])
        if active_truck_count > 1:
            available.append(AnomalyType.TRUCK_BREAKDOWN)

        # New delivery: always possible
        available.append(AnomalyType.NEW_DELIVERY)

        # Deadline change: need existing timed deliveries in the remaining goals
        available.append(AnomalyType.DEADLINE_CHANGE)

        return available

    def _generate_event(
        self,
        anomaly_type: AnomalyType,
        state: WorldState,
        action: PlanAction,
    ) -> Optional[AnomalyEvent]:
        """Generate a specific anomaly event of the given type."""

        if anomaly_type == AnomalyType.ROAD_CLOSURE:
            return self._gen_road_closure(state, action)
        elif anomaly_type == AnomalyType.TRUCK_BREAKDOWN:
            return self._gen_truck_breakdown(state, action)
        elif anomaly_type == AnomalyType.NEW_DELIVERY:
            return self._gen_new_delivery(state, action)
        elif anomaly_type == AnomalyType.DEADLINE_CHANGE:
            return self._gen_deadline_change(state, action)
        return None

    def _gen_road_closure(
        self, state: WorldState, action: PlanAction
    ) -> Optional[AnomalyEvent]:
        """Generate a road closure anomaly (maintains graph connectivity)."""
        connections = list(state.connections)
        if len(connections) < 6:  # Need enough connections to safely remove one
            return None

        truck, from_loc, to_loc = action.args[0], action.args[1], action.args[2]

        # 50% chance to close the exact road being used, 50% a random one
        if self.rng.random() < 0.5 and (from_loc, to_loc) in state.connections:
            closed_from, closed_to = from_loc, to_loc
        else:
            conn = self.rng.choice(connections)
            closed_from, closed_to = conn

        # Connectivity check: ensure all locations remain reachable
        test_conns = set(state.connections)
        test_conns.discard((closed_from, closed_to))
        if not self._is_connected(state.all_locations, test_conns):
            return None  # Would disconnect the graph

        return AnomalyEvent(
            anomaly_type=AnomalyType.ROAD_CLOSURE,
            description=f"Road closure: the road from {closed_from} to {closed_to} is now blocked!",
            details={"from": closed_from, "to": closed_to},
        )

    @staticmethod
    def _is_connected(locations: List[str], connections: set) -> bool:
        """Check if all locations are reachable via BFS on directed edges."""
        if not locations:
            return True
        visited = {locations[0]}
        queue = [locations[0]]
        while queue:
            loc = queue.pop(0)
            for f, t in connections:
                if f == loc and t not in visited:
                    visited.add(t)
                    queue.append(t)
        return len(visited) == len(locations)

    def _gen_truck_breakdown(
        self, state: WorldState, action: PlanAction
    ) -> Optional[AnomalyEvent]:
        """Generate a truck breakdown anomaly."""
        truck = action.args[0]  # The truck that's about to drive
        loc = state.truck_locations.get(truck, action.args[1])

        return AnomalyEvent(
            anomaly_type=AnomalyType.TRUCK_BREAKDOWN,
            description=f"Truck breakdown: {truck} has broken down at {loc}!",
            details={"truck": truck, "location": loc},
        )

    def _gen_new_delivery(
        self, state: WorldState, action: PlanAction
    ) -> Optional[AnomalyEvent]:
        """Generate a new emergency delivery anomaly."""
        self._new_package_counter += 1
        pkg_name = f"package_new{self._new_package_counter}"

        # Pick random origin and destination (different locations)
        locations = list(state.all_locations)
        if len(locations) < 2:
            return None

        origin = self.rng.choice(locations)
        dest = self.rng.choice([l for l in locations if l != origin])

        return AnomalyEvent(
            anomaly_type=AnomalyType.NEW_DELIVERY,
            description=f"New delivery: emergency {pkg_name} appeared at {origin}, must reach {dest}!",
            details={"package": pkg_name, "origin": origin, "destination": dest},
        )

    def _gen_deadline_change(
        self, state: WorldState, action: PlanAction
    ) -> Optional[AnomalyEvent]:
        """Generate a deadline tightening anomaly."""
        # Find the current time index
        try:
            current_idx = state.time_steps.index(state.current_time)
        except ValueError:
            return None

        remaining = state.time_steps[current_idx + 1:]
        if len(remaining) < 2:
            return None

        # Pick a package that hasn't been delivered yet and is still on the ground or in truck
        undelivered = []
        for pkg in state.all_packages:
            if not any(p == pkg for p, _, _ in state.delivered):
                undelivered.append(pkg)

        if not undelivered:
            return None

        pkg = self.rng.choice(undelivered)
        # New deadline: somewhere between now and the end (tighter)
        new_deadline = self.rng.choice(remaining[:max(1, len(remaining) // 2)])

        return AnomalyEvent(
            anomaly_type=AnomalyType.DEADLINE_CHANGE,
            description=f"Deadline change: {pkg} must now be delivered by {new_deadline}!",
            details={
                "package": pkg,
                "new_deadline": new_deadline,
            },
        )
