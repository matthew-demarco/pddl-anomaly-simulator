"""
Plan Simulator for the Trucks Domain.

Executes a plan step-by-step, checking for anomalies before each action.
When an anomaly is detected, invokes the Case-Based Reasoner and triggers
replanning with a modified PDDL problem file.
"""

import os                      # Used for file/folder operations: os.makedirs(...), os.listdir(...), os.path.join(...), os.path.isfile(...), os.remove(...)
import tempfile                # Used for temporary replanning folders: tempfile.mkdtemp(prefix="trucks_replan_")
import shutil                  # Used for copying/moving/removing files and folders (check later whether it is actually used)
import json                    # Used for GUI output: json.dumps(data)

from pathlib import Path                                                # Used for path handling: Path(...).resolve()
from typing import List, Optional, Tuple                                # List[T] = list of type T, Optional[T] = T or None, Tuple[A, B] = pair of values
from dataclasses import dataclass, field                                                          # Used for SimulationResult: @dataclass, field(default_factory=list)
from pddl_parser import PddlProblem, parse_domain, parse_problem                                  # Used to read PDDL files: parse_domain(...), parse_problem(...)
from state import WorldState, PlanAction, apply_action, initialize_from_problem, state_summary    # Used for world state and execution: initialize_from_problem(...), apply_action(...), state_summary(...)
from anomalies import AnomalyGenerator, AnomalyEvent, AnomalyType       # Used for anomaly generation: AnomalyGenerator(...), maybe_trigger(...)
from case_library import CaseLibrary, CaseResponse                      # Used for case-based reasoning: recognize(...), get_response(...)
from pddl_writer import generate_problem_pddl                           # Used during replanning: generate_problem_pddl(...)
from planner import run_fast_downward, cleanup_planner_files            # Used to generate plans: run_fast_downward(...), cleanup_planner_files(...)


# ---------------------------------------------------------------------------
# Simulation result
# ---------------------------------------------------------------------------

@dataclass                                       # Python decorator that automatically creates common methods for a class that mainly stores data.
class SimulationResult:                
    """Summary of a simulation run."""
    success: bool                                 # Stores whether the simulation finished succesfully, can only be true or false
    total_actions_executed: int = 0                 # Stores the number of plan actions that were successfully executed, starts at 0
    anomalies_encountered: List[AnomalyEvent] = field(default_factory=list)     # Stores every anomaly that occurred during the simulation. List[AnomalyEvent] means this is a list containing AnomalyEvent objects default_factory=list creates a new empty list for each SimulationResult.
    replans_triggered: int = 0                      # Stores the number of times Fast Downward generated a replacement plan, starts at 0
    final_state: Optional[WorldState] = None        # Stores the state of the world when the simulation finishes. Optional[WorldState] means it may contain a WorldState object or None. It begins as None because the simulation has not finished yet.
    failure_reason: str = ""                        # Stores a written explanation when the simulation fails. It begins as an empty string because no failure has occurred yet.


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class Simulator:
    """
    Step-by-step plan executor with anomaly injection and replanning.

    Flow:
        1. Generate initial plan with Fast Downward
        2. For each action in the plan:
           a. Check for anomaly (via AnomalyGenerator)
           b. If anomaly:
              i.   Recognize via CaseLibrary
              ii.  Apply PDDL modifications
              iii. Regenerate problem file
              iv.  Re-invoke Fast Downward
              v.   Continue with new plan
           c. Execute action, update world state
        3. Report results
    """

    def __init__(  # This basically says define a special method named __init__ inside the Simulator class. Python automatically calls __init__ when a new Simulator object is created. After Python creates the Simulator object, this method sets up all of the information and components that the simulator needs.
        self,       # self refers to the specific Simulator object being created. Allows values to be stored inside that object
        domain_path: str,   # The location of the PDDL domain file. Should be a string
        problem_path: str,      # The location of the PDDL problem file. Should be a string
        anomaly_chance: float = 0.2,    # The probability that a random anomaly will happen. Probably will be getting rid of this. Should be a float, default value is 20%
        seed: Optional[int] = None,     # An optional starting value for Python's random-number generator. Using the same seed can make the same random events happen again. Optional[int] means this value can be an integer or None(no specific seed was provided)
        verbose: bool = True,           # Controls whether detailed simulator information should be printed. By default it does
        max_anomalies: int = 5,         # The maximum number of random anomalies that can occur in one run. Default is 5
        search: str = "eager_greedy([ff()])", # The search algorithm and heuristic sent to Fast Downward. The default uses eager greedy search with the FF heuristic.
        export_states_dir: Optional[str] = None,        # An optional path to a folder where simulator states are saved. Optional[str] means this can be a string containing folder paths or none(state exporting is disabled.)
        json_output: bool = False,                      # Controls whether state information is printed in JSON format. Most likely used by gui
    ):
        self.domain_path = str(Path(domain_path).resolve()) # Converts the provided domain file path into a full absolute path. First, Path(domain_path) converts the string into a Path object. Then .resolve() converts it into a full absolute path. Then str(...) converts the Path object back into a normal string. Lastly self.domain_path stores the result inside the Simulator object.
        self.search = search                                # Save the selected Fast Downward search configuration
        self.export_states_dir = export_states_dir          # Save the optional state-export folder.
        self.json_output = json_output                      # Save whether JSON output is enabled.
        
        # Clear out previous state history if enabled
        if self.export_states_dir:                          # Check whether self.export_states_dir contains a folder path. If it does
            os.makedirs(self.export_states_dir, exist_ok=True)      # Create the export folder if it does not already exist. exist_ok=True prevents an error if the folder already exists.
            for filename in os.listdir(self.export_states_dir):     # Get every item name inside the export directory. Process one item at a time using the variable filename.
                file_path = os.path.join(self.export_states_dir, filename)      # Combine the directory path and filename to form the items complete path. os.path.join() uses the correct separator for the operating system
                try:                                                            # Attempt to run the following file-deletion code. If an error occurs, Python moves to the except block.
                    if os.path.isfile(file_path):                               # Check whether the current path points to a file. Directories will not be removed by this code.
                        os.remove(file_path)                                    # Delete the file so state data from an earlier run does not remain in the export directory.
                except Exception:                                               # Catch any error caused while checking or deleting the current file
                    pass                                                        # Ignore the error and continue running.
            
        self.problem_path = str(Path(problem_path).resolve())                   # Convert the supplied problem-file path into a full absolute path and store it inside the Simulator object.
        self.anomaly_chance = anomaly_chance                                    # Store the random anomaly probability. Likely will remove
        self.verbose = verbose                                                  # Store whether detailed output should be printed.

        # Parse the domain and problem
        self.domain = parse_domain(self.domain_path)                            # Read and parse the PDDL domain file. Store the parsed domain object in self.domain.
        self.problem = parse_problem(self.problem_path)                         # Read and parse the PDDL problem file. Store the parsed problem object in self.problem.

        # Initialize world state
        self.state = initialize_from_problem(self.problem)                      # Creates the starting WorldState from the parsed PDDL problem and stores it in self.state.

        # Components
        self.anomaly_gen = AnomalyGenerator(                                    # Creates the component responsible for randomly generating anomalies.
            anomaly_chance=anomaly_chance,                                      # Passes the probability that an anomaly will occur during each anomaly check.
            seed=seed,                                                          # Passes the optional random seed so the same random sequence can be reproduced.
            max_anomalies=max_anomalies,                                        # Passes the maximum number of anomalies allowed during one simulation run.
        )
        self.case_library = CaseLibrary()                                       # Creates the case library used to recognize anomalies and choose an appropriate response.

        # Tracking
        self.result = SimulationResult(success=False)                           # Creates an object that stores the simulation results; success starts as False because the run is not finished.
        self._replan_counter = 0                                                # Starts the internal count of replanning attempts at zero.
        self._export_seq = 0                                                    # Starts the sequence number used to name exported state files at zero.

    def _export_state(self, suffix: str):                                       # Defines an internal method that exports the current state as a PDDL file; suffix is added to the filename.
        if not self.export_states_dir:                                          # Checks whether no export directory was provided.
            return                                                              # Exits the method immediately when state exporting is disabled.
        os.makedirs(self.export_states_dir, exist_ok=True)                      # Creates the export directory if needed and avoids an error if it already exists.
        filename = f"{self._export_seq:03d}_{suffix}.pddl"                      # Builds a filename using a three-digit sequence number, the suffix, and the .pddl extension.
        out_path = os.path.join(self.export_states_dir, filename)               # Combines the export directory and filename into the complete output path.
        generate_problem_pddl(state=self.state, original_problem=self.problem, response=None, output_path=out_path)    # Writes the current world state to a PDDL file without applying an anomaly response.
        self._export_seq += 1                                                   # Increases the export sequence number so the next exported file gets a new number.

    def _emit_json_state(self):                                                 # Defines an internal method that converts the current world state into JSON output for the GUI.
        """Emit world state as JSON for UI visualization."""
        if not self.json_output:                                                # Checks whether JSON output is disabled.
            return                                                              # Exits the method immediately if the simulator is not supposed to produce JSON output.
            
        data = {                                                                # Creates a dictionary containing the world-state information that will be converted to JSON.
            "locations": list(self.state.all_locations),                        # Converts all known locations into a list and stores them under the "locations" key.
            "trucks": {t: loc for t, loc in self.state.truck_locations.items()},            # Creates a dictionary mapping each truck to its current location.
            "packages_at_locations": {pkg: loc for pkg, loc in self.state.package_locations.items()}, # Creates a dictionary mapping each package to its current location.
            "cargo": [{"package": p, "truck": t, "area": a} for p, t, a in self.state.cargo],           # Creates a list of dictionaries describing packages currently loaded in trucks.
            "connections": [[f, t] for f, t in self.state.connections],                                 # Creates a list of road connections, where each connection contains a starting and ending location.
            "delivered": [{"package": p, "location": l, "time": t} for p, l, t in self.state.delivered],    # Creates a list describing packages that have been delivered, including location and time.
            "current_time": self.state.current_time,                                                        # Stores the simulator's current time.
            "goals": [{"predicate": gc.predicate, "arguments": gc.arguments} for gc in self.problem.goal_conditions],       # Creates a list describing every goal condition from the original PDDL problem.
        }
        self._log(f"@@MAP_STATE@@{json.dumps(data)}")                                                                       # Converts the data dictionary into JSON text, adds a GUI marker, and prints it using the simulator's logging method.

    def run(self) -> SimulationResult:                                          # Defines the main method that runs the complete simulation and returns a SimulationResult object.
        """Execute the full simulation loop."""
        self._log("=" * 65)                                                     # Prints 65 equal signs to create a visual border.
        self._log("  TRUCKS DOMAIN — ANOMALY REPLANNING SIMULATOR")             # Prints the simulator's title.
        self._log("=" * 65)                                                     # Prints another visual border.
        self._log(f"  Problem: {self.problem.name}")                            # Prints the name of the parsed PDDL problem.
        self._log(f"  Domain:  {self.domain.name}")                             # Prints the name of the parsed PDDL domain.
        self._log(f"  Anomaly chance: {self.anomaly_chance:.0%}")               # Prints the anomaly probability as a percentage with no decimal places.
        self._log(f"  Case library: {len(self.case_library.cases)} cases loaded")       # Prints how many cases are stored in the case library.
        self._log("=" * 65)                                                             # Prints another border.
        self._log("")                                                                   # Prints a blank line

        # --- Initial plan ---
        self._log("━" * 65)                                                     # Prints a visual separator for Phase 1.
        self._log("  PHASE 1: Generating initial plan")                         # Prints the Phase 1 heading.
        self._log("━" * 65)                                                     # Prints another Phase 1 separator.

        cleanup_planner_files()                                                 # Deletes files left behind by previous Fast Downward runs.
        plan = run_fast_downward(self.domain_path, self.problem_path, search=self.search)       # Runs Fast Downward using the domain, problem, and search configuration and stores the returned plan.

        if plan is None:                                                        # Checks whether Fast Downward failed to find a plan.
            self._log("  ❌ Fast Downward could not find an initial plan.")     # Prints an error message if no plan was found.
            self.result.failure_reason = "No initial plan found."                # Records the reason for failure in the SimulationResult object.
            return self.result                                                   # Ends run() immediately and returns the failed result.

        self._log(f"  ✅ Initial plan: {len(plan)} actions")                    # Prints the number of actions in the initial plan.
        self._log("")                                                           # Prints a blank line.
        self._print_plan(plan)                                                  # Calls _print_plan() to display every action in the plan.

        # --- Execution loop ---
        self._log("")                                                           # Prints a blank line.
        self._log("━" * 65)                                                     # Prints a visual separator for Phase 2.
        self._log("  PHASE 2: Executing plan with anomaly monitoring")          # Prints the Phase 2 heading.
        self._log("━" * 65)                                                     # Prints another Phase 2 separator.
        self._log("")                                                           # Prints a blank line.
        self._log("  Initial state:")                                           # Prints a heading for the starting world state.
        self._log(state_summary(self.state))                                    # Creates and prints a readable summary of the current WorldState.
        self._log("")                                                           # Prints a blank line.

        self._export_state("initial")                                           # Exports the initial world state to a PDDL file if state exporting is enabled.
        self._emit_json_state()                                                 # Sends the initial world state as JSON if JSON output is enabled.

        step = 0                                                                # Starts the overall simulation step counter at zero.
        plan_idx = 0                                                            # Starts at index zero, which represents the first action in the current plan.

        while plan_idx < len(plan):                                             # Continues looping while there are still actions left in the current plan.
            action = plan[plan_idx]                                             # Retrieves the current action from the plan using plan_idx.
            step += 1                                                           # Increases the overall simulation step number by one.

            # --- Check for anomaly ---
            anomaly = self.anomaly_gen.maybe_trigger(self.state, action)        # Asks the random anomaly generator whether an anomaly should occur before the current action.

            if anomaly:                                                         # Runs this block if maybe_trigger() returned an AnomalyEvent instead of None.
                self._log(f"  ╔══════════════════════════════════════════════")     # Prints the top of the anomaly message box.
                self._log(f"  ║ 🔴 ANOMALY at step {step}!")                        # Prints the step number where the anomaly occurred.
                self._log(f"  ║ {anomaly.description}")                             # Prints the anomaly's human-readable description.
                self._log(f"  ╚══════════════════════════════════════════════")     # Prints the bottom of the anomaly message box.
                self.result.anomalies_encountered.append(anomaly)                   # Adds the anomaly to the list stored in the SimulationResult.

                # --- Case-Based Reasoning ---
                case = self.case_library.recognize(anomaly)                     # Asks the case library to find a case that matches the anomaly.
                if case is None:                                                # Checks whether the case library failed to find a matching case.
                    self._log(f"  ⚠️  No matching case found! Attempting to continue...")   # Prints a warning that the anomaly could not be handled.
                    plan_idx += 1                                               # Moves to the next action in the current plan.
                    continue                                                    # Immediately jumps back to the beginning of the while loop.

                self._log(f"  🧠 Case matched: '{case.name}'")                  # Prints the name of the case that matched the anomaly.
                response = self.case_library.get_response(case, anomaly, self.state)    # Builds a response using the matched case, anomaly information, and current state.
                self._log(f"  📋 Response: {response.explanation}")                     # Prints the explanation stored in the CaseResponse.

                # --- Apply state modifications from anomaly ---
                self._apply_anomaly_to_state(anomaly, response)                 # Applies the anomaly's immediate effects to the current WorldState.
                self._export_state(f"anomaly_{anomaly.anomaly_type.name}")      # Exports the state after the anomaly using its type in the filename.

                # --- Replan ---
                self._log("")                                                   # Prints a blank line
                self._log(f"  🔵 REPLANNING (attempt #{self._replan_counter + 1})...")          # Prints the number of the upcoming replanning attempt.
                new_plan = self._replan(response)                               # Generates a modified PDDL problem and asks Fast Downward for a replacement plan.
                if new_plan is None:                                        # Checks whether Fast Downward failed to generate a replacement plan.
                    self._log(f"  ❌ Replanning failed — no valid plan found.")  # Prints an error message explaining that replanning failed.
                    self.result.failure_reason = (                          # Begins storing a description of why the simulation failed.
                        f"Replanning failed after {anomaly.anomaly_type.name} anomaly."  # Creates a failure message containing the anomaly type.
                    )
                    self.result.final_state = self.state                    # Saves the current WorldState as the final state before ending the simulation.
                    return self.result                                      # Immediately ends run() and returns the failed SimulationResult object.

                self._replan_counter += 1                                  # Increases the simulator's internal count of successful replanning attempts by one.
                self.result.replans_triggered += 1                          # Increases the replanning count stored in the final SimulationResult.
                self._log(f"  ✅ New plan: {len(new_plan)} actions")        # Prints how many actions are contained in the new plan.
                self._print_plan(new_plan)                                  # Calls _print_plan() to display every action in the new plan.

                # Replace current plan
                plan = new_plan                                             # Replaces the old plan with the newly generated plan.
                plan_idx = 0                                                # Resets the plan position to zero so execution starts at the first action of the new plan.
                self._log("")                                               # Prints a blank line.
                self._emit_json_state()                                     # Sends the current state to the GUI as JSON if JSON output is enabled.
                continue                                                    # Jumps back to the beginning of the while loop without executing the old selected action.

            self._log(f"  Step {step:3d}: 🟢 {action}")                    # Prints the current step number and action when no anomaly occurred; :3d gives the number a width of three spaces.
            self.state = apply_action(self.state, action)                   # Executes the current plan action and stores the returned updated WorldState.
            self.result.total_actions_executed += 1                         # Increases the number of successfully executed actions by one.
            plan_idx += 1                                                   # Moves the plan index to the next action in the current plan.
            
            action_clean = f"action_{action.name}_" + "_".join(action.args) # Creates a filename-friendly action label by combining the action name and arguments with underscores.
            self._export_state(action_clean)                               # Exports the state after the action using action_clean as part of the filename.
            self._emit_json_state()                                         # Sends the updated state to the GUI as JSON if JSON output is enabled.

            if self.verbose:                                                # Checks whether detailed console output is enabled.
                self._log(state_summary(self.state))                        # Creates and prints a readable summary of the updated WorldState.
                self._log("")                                               # Prints a blank line after the state summary.

        # --- Final report ---
        self._log("")                                                       # Prints a blank line after the action loop finishes.
        self._log("━" * 65)                                                 # Prints a 65-character separator for the final report section.
        self._log("  PHASE 3: Mission Report")                              # Prints the Phase 3 heading.
        self._log("━" * 65)                                                 # Prints another separator under the Phase 3 heading.
        self.result.success = True                                          # Marks the simulation as successful because the current plan finished.
        self.result.final_state = self.state                                # Saves the current WorldState as the final state.
        self._print_report()                                                # Calls _print_report() to display the final simulation results.

        return self.result                                                  # Returns the completed SimulationResult to the code that called run().


    def _apply_anomaly_to_state(self, anomaly: AnomalyEvent, response: CaseResponse):  # Defines a helper method that applies an anomaly's immediate effects to the current WorldState.
        """Apply the immediate effects of an anomaly to the world state.""" # Docstring explaining the purpose of this method.

        if anomaly.anomaly_type == AnomalyType.ROAD_CLOSURE:                # Checks whether the anomaly is a road closure.
            for from_loc, to_loc in response.remove_connections:           # Loops through every road connection that the CaseResponse says should be removed.
                self.state.connections.discard((from_loc, to_loc))          # Removes the connection from the state's connection set without causing an error if it is already missing.
                self._log(f"  ↳ Removed connection: {from_loc} ↔ {to_loc}") # Prints the road connection that was removed.

        elif anomaly.anomaly_type == AnomalyType.TRUCK_BREAKDOWN:           # Checks whether the anomaly is a truck breakdown.
            truck = anomaly.details["truck"]                               # Gets the broken truck's name from the anomaly's details dictionary.
            loc = anomaly.details["location"]                              # Gets the broken truck's current location from the anomaly's details dictionary.

            # Dump all cargo at current location
            to_remove = []                                                  # Creates an empty list to hold cargo records that must later be removed.
            for pkg, t, area in self.state.cargo:                           # Loops through each cargo record containing a package, truck, and cargo area.
                if t == truck:                                              # Checks whether the cargo belongs to the truck that broke down.
                    to_remove.append((pkg, t, area))                         # Saves the cargo record so it can safely be removed after the loop.
                    self.state.package_locations[pkg] = loc                 # Places the package at the broken truck's current location.
                    self.state.free_areas.add((area, truck))                # Marks the truck's cargo area as free.
                    self._log(f"  ↳ Dumped {pkg} at {loc}")                 # Prints which package was unloaded and where it was placed.

            for item in to_remove:                                          # Loops through all cargo records belonging to the broken truck.
                self.state.cargo.discard(item)                              # Removes each cargo record from the state's cargo collection.

            # Remove truck from active service
            if truck in self.state.truck_locations:                         # Checks whether the broken truck is still in the truck-location dictionary.
                del self.state.truck_locations[truck]                       # Deletes the broken truck's location entry.
            self.state.all_trucks = [t for t in self.state.all_trucks if t != truck]  # Rebuilds the truck list without the broken truck.
            self._log(f"  ↳ Removed {truck} from service")                 # Prints that the truck was removed from service.

        elif anomaly.anomaly_type == AnomalyType.NEW_DELIVERY:              # Checks whether the anomaly adds a new delivery request.
            pkg = anomaly.details["package"]                               # Gets the new package's name from the anomaly details.
            origin = anomaly.details["origin"]                             # Gets the new package's starting location from the anomaly details.
            self.state.all_packages.append(pkg)                            # Adds the new package to the list of all packages.
            self.state.package_locations[pkg] = origin                     # Records the new package at its starting location.
            self._log(f"  ↳ Added {pkg} at {origin}")                      # Prints the package name and starting location.

        elif anomaly.anomaly_type == AnomalyType.DEADLINE_CHANGE:           # Checks whether the anomaly changes a delivery deadline.
            # Deadline changes are handled in goal modification during replanning
            self._log(f"  ↳ Deadline modification will be applied during replanning")  # Explains that the deadline change will be handled while generating the replanning problem.


    def _replan(self, response: CaseResponse) -> Optional[List[PlanAction]]: # Defines a method that returns either a new list of PlanAction objects or None if planning fails.
        """Generate a new plan by writing a modified PDDL problem and re-invoking Fast Downward."""  # Docstring explaining the replanning process.

        # Create a temporary problem file
        temp_dir = tempfile.mkdtemp(prefix="trucks_replan_")                # Creates a unique temporary directory whose name begins with trucks_replan_.
        temp_problem = os.path.join(temp_dir, "replanned_problem.pddl")      # Creates the complete path for the modified temporary PDDL problem file.
        temp_plan = os.path.join(temp_dir, "sas_plan")                      # Creates the complete path where Fast Downward should save the new plan.

        # Generate the modified problem
        pddl_text = generate_problem_pddl(                                  # Generates a modified PDDL problem using the current state and CaseResponse.
            state=self.state,                                               # Passes the current WorldState after the anomaly was applied.
            original_problem=self.problem,                                  # Passes the original parsed PDDL problem for its objects, goals, and other information.
            response=response,                                              # Passes the anomaly response containing additional PDDL modifications.
            output_path=temp_problem,                                       # Tells the function where to save the modified PDDL problem.
        )

        if self.verbose:                                                     # Checks whether detailed console output is enabled.
            self._log(f"  [Replan] Generated problem file: {temp_problem}") # Prints the path of the newly generated PDDL problem file.
            self._log(f"  [Replan] Problem preview:")                       # Prints a heading before displaying a preview of the PDDL text.
            for line in pddl_text.split('\n')[:5]:                          # Splits the PDDL text into lines and loops through only the first five.
                self._log(f"    {line}")                                    # Prints the current preview line with indentation.
            self._log(f"    ...")                                          # Shows that additional PDDL lines exist but are not being printed.

        # Invoke Fast Downward on the modified problem
        cleanup_planner_files()                                             # Removes files left behind by earlier Fast Downward runs.
        plan = run_fast_downward(                                           # Runs Fast Downward using the modified problem file.
            self.domain_path,                                               # Passes the original PDDL domain file path.
            temp_problem,                                                   # Passes the modified temporary PDDL problem file path.
            search=self.search,                                             # Passes the configured Fast Downward search strategy.
            plan_file=temp_plan,                                            # Tells Fast Downward where to save the generated plan file.
        )

        return plan                                                         # Returns the new plan or None if Fast Downward could not find one.


    def _print_plan(self, plan: List[PlanAction]):                          # Defines a helper method that prints all actions in a plan.
        """Print a plan summary."""                                         # Docstring explaining that this method prints a plan summary.
        self._log(f"  Plan ({len(plan)} actions):")                        # Prints the total number of actions in the plan.
        for i, action in enumerate(plan):                                   # Loops through the plan while receiving both the action's index and the action itself.
            self._log(f"    {i+1:3d}. {action}")                           # Prints the action number starting at 1; :3d gives the number a width of three spaces.


    def _print_report(self):                                                # Defines a helper method that prints the final simulation report.
        """Print the final simulation report."""                            # Docstring explaining the purpose of the method.
        r = self.result                                                     # Creates the shorter local variable r as another reference to self.result.
        status = "✅ SUCCESS" if r.success else "❌ FAILED"                 # Chooses the success message if r.success is True, otherwise chooses the failure message.
        self._log(f"  Status: {status}")                                    # Prints the chosen simulation status.

        if r.failure_reason:                                                # Checks whether a nonempty failure explanation exists.
            self._log(f"  Reason: {r.failure_reason}")                      # Prints the recorded failure explanation.

        self._log(f"  Actions executed: {r.total_actions_executed}")        # Prints the number of actions that successfully executed.
        self._log(f"  Anomalies encountered: {len(r.anomalies_encountered)}")  # Prints the number of anomalies encountered during the run.

        for a in r.anomalies_encountered:                                   # Loops through every stored anomaly.
            self._log(f"    • {a.anomaly_type.name}: {a.description}")      # Prints each anomaly's type and human-readable description.

        self._log(f"  Replans triggered: {r.replans_triggered}")            # Prints how many successful replanning events occurred.
        self._log("")                                                       # Prints a blank line.
        self._log("  Final state:")                                         # Prints a heading for the final world state.

        if r.final_state:                                                   # Checks whether a final WorldState was stored.
            self._log(state_summary(r.final_state))                         # Creates and prints a readable summary of the final state.

        # Check goal satisfaction
        if r.final_state:                                                   # Checks again whether a final WorldState is available.
            delivered = r.final_state.delivered                            # Stores the final state's completed-delivery collection in a shorter variable.
            at_dest = r.final_state.at_destination                          # Stores the final state's at-destination package collection in a shorter variable.
            self._log(f"  Deliveries completed: {len(delivered) + len(at_dest)}")  # Adds the sizes of both collections and prints the total number of completed deliveries.

        self._log("")                                                       # Prints a blank line.
        self._log("=" * 65)                                                 # Prints 65 equal signs as the final report border.


    def _log(self, message: str):                                           # Defines an internal helper method that prints one text message safely.
        """Print a log message (handles Windows console encoding)."""       # Docstring explaining that this method handles character-encoding errors.
        try:                                                                # Attempts to execute the following print statement normally.
            print(message)                                                  # Prints the supplied message to the console.
        except UnicodeEncodeError:                                          # Catches an error caused when the console cannot display one or more Unicode characters.
            # Fallback: replace unencodable characters
            print(message.encode('ascii', errors='replace').decode('ascii'))  # Converts the message to ASCII, replaces unsupported characters, converts it back to text, and prints it.


