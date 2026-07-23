"""
Case-Based Reasoner for Anomaly Recognition and Response.

Maintains a library of known anomaly cases, matches incoming anomaly events
to stored patterns, and produces PDDL modifications for replanning.
"""                                                                         # Module docstring explaining that this file matches anomalies to known cases and creates replanning instructions.


from dataclasses import dataclass, field                                    # Imports dataclass for data-storage classes and field for safe default lists and dictionaries.
from typing import List, Dict, Any, Callable, Optional, Set, Tuple          # Imports type hints for collections, functions, optional values, and grouped values.

from anomalies import AnomalyEvent, AnomalyType                            # Imports the class representing one anomaly and the enum containing the possible anomaly categories.
from state import WorldState                                               # Imports WorldState so response builders can examine the current simulation state.
from pddl_parser import GoalCondition                                      # Imports GoalCondition so responses can add, remove, or change PDDL goals.


# ---------------------------------------------------------------------------
# Case definition
# ---------------------------------------------------------------------------

@dataclass                                                                  # Automatically creates an initializer and other useful methods for CaseResponse.
class CaseResponse:                                                         # Defines a data container describing changes needed for replanning.
    """Describes the PDDL modifications needed to handle an anomaly."""      # Class docstring explaining the purpose of CaseResponse.

    # Connections to remove: [(from, to), ...]
    remove_connections: List[Tuple[str, str]] = field(default_factory=list) # Stores road connections that should be removed; each connection contains a starting and ending location.

    # Facts to remove from init (predicate, args)
    remove_facts: List[Tuple[str, List[str]]] = field(default_factory=list) # Stores PDDL facts that should be removed from the problem's initial state.

    # Facts to add to init (predicate, args)
    add_facts: List[Tuple[str, List[str]]] = field(default_factory=list)    # Stores PDDL facts that should be added to the problem's initial state.

    # New objects to add: {type: [names]}
    add_objects: Dict[str, List[str]] = field(default_factory=dict)         # Stores new PDDL objects grouped by type, such as {"package": ["package_new1"]}.

    # Goal conditions to remove
    remove_goals: List[GoalCondition] = field(default_factory=list)         # Stores goal conditions that should be removed from the replanned problem.

    # Goal conditions to add
    add_goals: List[GoalCondition] = field(default_factory=list)            # Stores new goal conditions that should be added to the replanned problem.

    # Goal conditions to modify (replace matching package goals)
    modify_goals: Dict[str, GoalCondition] = field(default_factory=dict)    # Maps a package name to the replacement goal that should be used for that package.

    # Trucks to remove from service
    remove_trucks: List[str] = field(default_factory=list)                  # Stores the names of trucks that should be removed from the replanned problem.

    # Human-readable explanation
    explanation: str = ""                                                   # Stores a readable explanation of how the anomaly will be handled.


@dataclass                                                                  # Automatically creates common methods for the Case data-storage class.
class Case:                                                                 # Defines one stored case in the case library.
    """A stored case in the case library."""                                # Class docstring explaining that each Case represents one known anomaly pattern.

    name: str                                                               # Stores the short name of the case, such as "road_closure".
    anomaly_type: AnomalyType                                               # Stores the AnomalyType that this case recognizes.
    description: str                                                        # Stores a readable description of the anomaly pattern.

    # Function that builds a CaseResponse given the anomaly and state
    build_response: Callable[[AnomalyEvent, WorldState], CaseResponse]      # Stores the function that receives an event and state and returns a CaseResponse.


# ---------------------------------------------------------------------------
# Response builders for each anomaly type
# ---------------------------------------------------------------------------

def _build_road_closure_response(                                           # Defines the function that builds a response for a road-closure anomaly.
    event: AnomalyEvent,                                                    # Receives the specific road-closure event.
    state: WorldState,                                                      # Receives the current world state, although this function does not directly use it.
) -> CaseResponse:                                                          # Returns a CaseResponse describing the necessary PDDL changes.
    """Handle a road closure by removing the connection from the PDDL model."""  # Docstring explaining the purpose of this response builder.

    from_loc = event.details["from"]                                        # Retrieves the starting location of the closed road from the event details.
    to_loc = event.details["to"]                                            # Retrieves the ending location of the closed road from the event details.

    response = CaseResponse(                                                # Creates a CaseResponse containing the road-closure modifications.
        remove_connections=[(from_loc, to_loc), (to_loc, from_loc)],        # Removes both directions of the road so the connection is treated as bidirectional and fully closed.
        explanation=(                                                       # Begins the human-readable explanation of the response.
            f"Road between {from_loc} and {to_loc} is closed. "             # States which road was closed.
            f"Removing bidirectional connection and replanning with "       # Explains that both road directions will be removed.
            f"alternative routes."                                          # Explains that the planner will search for another route.
        ),
    )

    return response                                                         # Returns the completed CaseResponse to the case library.


def _build_truck_breakdown_response(                                        # Defines the function that builds a response for a truck breakdown.
    event: AnomalyEvent,                                                    # Receives the specific truck-breakdown event.
    state: WorldState,                                                      # Receives the current world state so the function can find cargo inside the truck.
) -> CaseResponse:                                                          # Returns a CaseResponse describing the necessary PDDL changes.
    """
    Handle a truck breakdown by dumping cargo at current location
    and removing the truck from the problem.
    """                                                                     # Docstring explaining the truck-breakdown response.

    truck = event.details["truck"]                                          # Retrieves the name of the broken truck from the anomaly details.
    location = event.details["location"]                                    # Retrieves the truck's breakdown location from the anomaly details.

    # Find all packages currently in this truck
    cargo_to_dump = []                                                      # Creates an empty list for packages and cargo areas found inside the broken truck.

    for pkg, t, area in state.cargo:                                        # Loops through each cargo record containing a package, truck, and cargo area.
        if t == truck:                                                      # Checks whether the cargo belongs to the truck that broke down.
            cargo_to_dump.append((pkg, area))                               # Saves the package and area so the package can be placed at the breakdown location.

    # Build facts: packages are now on the ground at the breakdown location
    add_facts = []                                                          # Creates an empty list for new PDDL facts describing the dumped packages.

    for pkg, area in cargo_to_dump:                                         # Loops through each package found inside the broken truck.
        add_facts.append(("at", [pkg, location]))                           # Adds a PDDL fact stating that the package is now at the breakdown location.

    response = CaseResponse(                                                # Creates a CaseResponse containing the truck-breakdown modifications.
        add_facts=add_facts,                                                # Adds the new package-location facts to the replanned problem.
        remove_trucks=[truck],                                              # Marks the broken truck for removal from the replanned problem.
        explanation=(                                                       # Begins the human-readable explanation.
            f"{truck} broke down at {location}. "                           # States which truck broke down and where.
            f"Dumping {len(cargo_to_dump)} package(s) at {location} and "   # States how many packages will be unloaded.
            f"removing truck from service. Replanning with remaining trucks."  # Explains that the broken truck is removed and the other trucks must complete the plan.
        ),
    )

    return response                                                         # Returns the completed truck-breakdown response.


def _build_new_delivery_response(                                           # Defines the function that builds a response for a new-delivery anomaly.
    event: AnomalyEvent,                                                    # Receives the specific new-delivery event.
    state: WorldState,                                                      # Receives the current world state, although this function does not directly use it.
) -> CaseResponse:                                                          # Returns a CaseResponse describing the necessary additions.
    """Handle a new emergency delivery by adding a package and goal."""      # Docstring explaining the new-delivery response.

    pkg_name = event.details["package"]                                     # Retrieves the new package name from the anomaly details.
    origin = event.details["origin"]                                        # Retrieves the new package's starting location.
    destination = event.details["destination"]                              # Retrieves the new package's required destination.

    response = CaseResponse(                                                # Creates a CaseResponse containing the new-delivery modifications.
        add_objects={"package": [pkg_name]},                                # Adds the new package as a PDDL object of type package.
        add_facts=[("at", [pkg_name, origin])],                             # Adds a PDDL fact stating that the package begins at the origin.
        add_goals=[GoalCondition(                                           # Adds a new delivery goal for the emergency package.
            predicate="at-destination",                                     # Uses the at-destination predicate for the new goal.
            arguments=[pkg_name, destination],                              # Supplies the package name and destination as the goal arguments.
        )],
        explanation=(                                                       # Begins the human-readable explanation.
            f"Emergency delivery: {pkg_name} has appeared at {origin} "     # States which package appeared and where.
            f"and must be delivered to {destination}. Adding to plan."      # States its destination and explains that it will be added to the plan.
        ),
    )

    return response                                                         # Returns the completed new-delivery response.


def _build_deadline_change_response(                                        # Defines the function that builds a response for a deadline change.
    event: AnomalyEvent,                                                    # Receives the specific deadline-change event.
    state: WorldState,                                                      # Receives the current world state, although this function does not directly use it.
) -> CaseResponse:                                                          # Returns a CaseResponse containing a modified goal.
    """Handle a deadline tightening by modifying the goal."""               # Docstring explaining the deadline-change response.

    pkg_name = event.details["package"]                                     # Retrieves the package whose deadline changed.
    new_deadline = event.details["new_deadline"]                            # Retrieves the package's new delivery deadline.

    # Find the destination for this package from existing goals or state
    # We'll modify matching goals in the replanner
    response = CaseResponse(                                                # Creates a CaseResponse containing the replacement deadline goal.
        modify_goals={                                                      # Begins the dictionary of package goals that must be changed.
            pkg_name: GoalCondition(                                        # Associates the affected package with a new GoalCondition.
                predicate="delivered",                                      # Uses the delivered predicate for the replacement goal.
                arguments=[pkg_name, "__DEST__", new_deadline],             # Stores the package, a destination placeholder, and the new deadline.
                # __DEST__ is a placeholder — the PDDL writer will resolve it
            ),
        },
        explanation=(                                                       # Begins the human-readable explanation.
            f"Deadline for {pkg_name} has been tightened to {new_deadline}. "  # States which package has the new deadline.
            f"Updating delivery goal and replanning."                       # Explains that the goal will be changed before replanning.
        ),
    )

    return response                                                         # Returns the completed deadline-change response.


# ---------------------------------------------------------------------------
# Case library
# ---------------------------------------------------------------------------

class CaseLibrary:                                                          # Defines the case-based reasoner's stored knowledge base.
    """
    The Case-Based Reasoner's knowledge base.

    Contains a library of cases that map anomaly patterns to PDDL
    modification strategies. Matches incoming anomalies to known cases
    and produces the appropriate response.
    """                                                                     # Class docstring explaining how CaseLibrary connects anomalies to response strategies.

    def __init__(self):                                                     # Defines the constructor that runs when a CaseLibrary object is created.
        self.cases: List[Case] = []                                         # Creates an initially empty list that will store Case objects.
        self._load_default_cases()                                          # Calls the internal method that adds the four built-in anomaly cases.

    def _load_default_cases(self):                                          # Defines an internal method that creates the default case library.
        """Load the built-in case library for the trucks domain."""         # Docstring explaining the purpose of the method.

        self.cases = [                                                      # Replaces the case list with the built-in Case objects.
            Case(                                                           # Creates the stored case for road closures.
                name="road_closure",                                        # Gives the case its short identifying name.
                anomaly_type=AnomalyType.ROAD_CLOSURE,                      # Matches this case with ROAD_CLOSURE events.
                description="A road segment has become impassable.",        # Stores a readable description of the case.
                build_response=_build_road_closure_response,                # Assigns the road-closure response-building function.
            ),

            Case(                                                           # Creates the stored case for truck breakdowns.
                name="truck_breakdown",                                     # Gives the case its short identifying name.
                anomaly_type=AnomalyType.TRUCK_BREAKDOWN,                   # Matches this case with TRUCK_BREAKDOWN events.
                description="A truck has suffered mechanical failure.",     # Stores a readable description of the case.
                build_response=_build_truck_breakdown_response,             # Assigns the truck-breakdown response-building function.
            ),

            Case(                                                           # Creates the stored case for new deliveries.
                name="new_delivery",                                        # Gives the case its short identifying name.
                anomaly_type=AnomalyType.NEW_DELIVERY,                      # Matches this case with NEW_DELIVERY events.
                description="An emergency package has appeared for delivery.",  # Stores a readable description of the case.
                build_response=_build_new_delivery_response,                # Assigns the new-delivery response-building function.
            ),

            Case(                                                           # Creates the stored case for deadline changes.
                name="deadline_change",                                     # Gives the case its short identifying name.
                anomaly_type=AnomalyType.DEADLINE_CHANGE,                   # Matches this case with DEADLINE_CHANGE events.
                description="A delivery deadline has been tightened.",      # Stores a readable description of the case.
                build_response=_build_deadline_change_response,             # Assigns the deadline-change response-building function.
            ),
        ]

    def recognize(self, event: AnomalyEvent) -> Optional[Case]:             # Defines a method that tries to match an AnomalyEvent with a stored Case.
        """
        Match an anomaly event to a known case.

        Returns the matching Case, or None if no match is found.
        """                                                                 # Method docstring explaining the recognition process.

        for case in self.cases:                                             # Loops through each stored case in the case library.
            if case.anomaly_type == event.anomaly_type:                     # Checks whether the case's anomaly type matches the event's anomaly type.
                return case                                                 # Immediately returns the first matching Case.

        return None                                                         # Returns None if none of the stored cases match the event.

    def get_response(                                                       # Defines a method that creates the CaseResponse for a matched case.
        self,                                                               # Refers to the current CaseLibrary object.
        case: Case,                                                         # Receives the Case that was matched by recognize().
        event: AnomalyEvent,                                                # Receives the specific anomaly event.
        state: WorldState,                                                  # Receives the current world state.
    ) -> CaseResponse:                                                      # Returns a CaseResponse containing the necessary modifications.
        """
        Build the PDDL modification response for a matched case.

        Args:
            case: The matched case from the library.
            event: The anomaly event that triggered the match.
            state: The current world state.

        Returns:
            A CaseResponse with the necessary PDDL modifications.
        """                                                                 # Method docstring describing the inputs and returned response.

        return case.build_response(event, state)                            # Calls the response-building function stored in the Case and returns its CaseResponse.

    def add_case(self, case: Case):                                         # Defines a method that allows another Case to be added to the library.
        """Add a new case to the library (extensibility)."""                # Docstring explaining that the library can be expanded.
        self.cases.append(case)                                             # Adds the supplied Case object to the end of the case list.

    def list_cases(self) -> List[str]:                                      # Defines a method that returns readable summaries of all stored cases.
        """Return a summary of all known cases."""                          # Docstring explaining the purpose of list_cases().
        return [f"{c.name}: {c.description}" for c in self.cases]           # Builds and returns one formatted description string for every stored Case.

