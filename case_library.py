"""
Case-Based Reasoner for Anomaly Recognition and Response.

Maintains a library of known anomaly cases, matches incoming anomaly events
to stored patterns, and produces PDDL modifications for replanning.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Callable, Optional, Set, Tuple

from anomalies import AnomalyEvent, AnomalyType
from state import WorldState
from pddl_parser import GoalCondition


# ---------------------------------------------------------------------------
# Case definition
# ---------------------------------------------------------------------------

@dataclass
class CaseResponse:
    """Describes the PDDL modifications needed to handle an anomaly."""
    # Connections to remove: [(from, to), ...]
    remove_connections: List[Tuple[str, str]] = field(default_factory=list)

    # Facts to remove from init (predicate, args)
    remove_facts: List[Tuple[str, List[str]]] = field(default_factory=list)

    # Facts to add to init (predicate, args)
    add_facts: List[Tuple[str, List[str]]] = field(default_factory=list)

    # New objects to add: {type: [names]}
    add_objects: Dict[str, List[str]] = field(default_factory=dict)

    # Goal conditions to remove
    remove_goals: List[GoalCondition] = field(default_factory=list)

    # Goal conditions to add
    add_goals: List[GoalCondition] = field(default_factory=list)

    # Goal conditions to modify (replace matching package goals)
    modify_goals: Dict[str, GoalCondition] = field(default_factory=dict)  # package_name -> new goal

    # Trucks to remove from service
    remove_trucks: List[str] = field(default_factory=list)

    # Human-readable explanation
    explanation: str = ""


@dataclass
class Case:
    """A stored case in the case library."""
    name: str
    anomaly_type: AnomalyType
    description: str
    # Function that builds a CaseResponse given the anomaly and state
    build_response: Callable[[AnomalyEvent, WorldState], CaseResponse]


# ---------------------------------------------------------------------------
# Response builders for each anomaly type
# ---------------------------------------------------------------------------

def _build_road_closure_response(
    event: AnomalyEvent, state: WorldState
) -> CaseResponse:
    """Handle a road closure by removing the connection from the PDDL model."""
    from_loc = event.details["from"]
    to_loc = event.details["to"]

    response = CaseResponse(
        remove_connections=[(from_loc, to_loc), (to_loc, from_loc)],
        explanation=(
            f"Road between {from_loc} and {to_loc} is closed. "
            f"Removing bidirectional connection and replanning with "
            f"alternative routes."
        ),
    )
    return response


def _build_truck_breakdown_response(
    event: AnomalyEvent, state: WorldState
) -> CaseResponse:
    """
    Handle a truck breakdown by dumping cargo at current location
    and removing the truck from the problem.
    """
    truck = event.details["truck"]
    location = event.details["location"]

    # Find all packages currently in this truck
    cargo_to_dump = []
    for pkg, t, area in state.cargo:
        if t == truck:
            cargo_to_dump.append((pkg, area))

    # Build facts: packages are now on the ground at the breakdown location
    add_facts = []
    for pkg, area in cargo_to_dump:
        add_facts.append(("at", [pkg, location]))

    response = CaseResponse(
        add_facts=add_facts,
        remove_trucks=[truck],
        explanation=(
            f"{truck} broke down at {location}. "
            f"Dumping {len(cargo_to_dump)} package(s) at {location} and "
            f"removing truck from service. Replanning with remaining trucks."
        ),
    )
    return response


def _build_new_delivery_response(
    event: AnomalyEvent, state: WorldState
) -> CaseResponse:
    """Handle a new emergency delivery by adding a package and goal."""
    pkg_name = event.details["package"]
    origin = event.details["origin"]
    destination = event.details["destination"]

    response = CaseResponse(
        add_objects={"package": [pkg_name]},
        add_facts=[("at", [pkg_name, origin])],
        add_goals=[GoalCondition(
            predicate="at-destination",
            arguments=[pkg_name, destination],
        )],
        explanation=(
            f"Emergency delivery: {pkg_name} has appeared at {origin} "
            f"and must be delivered to {destination}. Adding to plan."
        ),
    )
    return response


def _build_deadline_change_response(
    event: AnomalyEvent, state: WorldState
) -> CaseResponse:
    """Handle a deadline tightening by modifying the goal."""
    pkg_name = event.details["package"]
    new_deadline = event.details["new_deadline"]

    # Find the destination for this package from existing goals or state
    # We'll modify matching goals in the replanner
    response = CaseResponse(
        modify_goals={
            pkg_name: GoalCondition(
                predicate="delivered",
                arguments=[pkg_name, "__DEST__", new_deadline],
                # __DEST__ is a placeholder — the PDDL writer will resolve it
            ),
        },
        explanation=(
            f"Deadline for {pkg_name} has been tightened to {new_deadline}. "
            f"Updating delivery goal and replanning."
        ),
    )
    return response


# ---------------------------------------------------------------------------
# Case library
# ---------------------------------------------------------------------------

class CaseLibrary:
    """
    The Case-Based Reasoner's knowledge base.

    Contains a library of cases that map anomaly patterns to PDDL
    modification strategies. Matches incoming anomalies to known cases
    and produces the appropriate response.
    """

    def __init__(self):
        self.cases: List[Case] = []
        self._load_default_cases()

    def _load_default_cases(self):
        """Load the built-in case library for the trucks domain."""
        self.cases = [
            Case(
                name="road_closure",
                anomaly_type=AnomalyType.ROAD_CLOSURE,
                description="A road segment has become impassable.",
                build_response=_build_road_closure_response,
            ),
            Case(
                name="truck_breakdown",
                anomaly_type=AnomalyType.TRUCK_BREAKDOWN,
                description="A truck has suffered mechanical failure.",
                build_response=_build_truck_breakdown_response,
            ),
            Case(
                name="new_delivery",
                anomaly_type=AnomalyType.NEW_DELIVERY,
                description="An emergency package has appeared for delivery.",
                build_response=_build_new_delivery_response,
            ),
            Case(
                name="deadline_change",
                anomaly_type=AnomalyType.DEADLINE_CHANGE,
                description="A delivery deadline has been tightened.",
                build_response=_build_deadline_change_response,
            ),
        ]

    def recognize(self, event: AnomalyEvent) -> Optional[Case]:
        """
        Match an anomaly event to a known case.

        Returns the matching Case, or None if no match is found.
        """
        for case in self.cases:
            if case.anomaly_type == event.anomaly_type:
                return case
        return None

    def get_response(
        self, case: Case, event: AnomalyEvent, state: WorldState
    ) -> CaseResponse:
        """
        Build the PDDL modification response for a matched case.

        Args:
            case: The matched case from the library.
            event: The anomaly event that triggered the match.
            state: The current world state.

        Returns:
            A CaseResponse with the necessary PDDL modifications.
        """
        return case.build_response(event, state)

    def add_case(self, case: Case):
        """Add a new case to the library (extensibility)."""
        self.cases.append(case)

    def list_cases(self) -> List[str]:
        """Return a summary of all known cases."""
        return [f"{c.name}: {c.description}" for c in self.cases]
