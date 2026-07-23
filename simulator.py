"""
Plan Simulator for the Trucks Domain.

Executes a plan step-by-step, checking for anomalies before each action.
When an anomaly is detected, invokes the Case-Based Reasoner and triggers
replanning with a modified PDDL problem file.
"""

import os
import tempfile
import shutil
import json
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass, field

from pddl_parser import PddlProblem, parse_domain, parse_problem
from state import WorldState, PlanAction, apply_action, initialize_from_problem, state_summary
from anomalies import AnomalyGenerator, AnomalyEvent, AnomalyType, ScheduledAnomaly, create_manual_event
from case_library import CaseLibrary, CaseResponse
from pddl_writer import generate_problem_pddl
from planner import run_fast_downward, cleanup_planner_files


# ---------------------------------------------------------------------------
# Simulation result
# ---------------------------------------------------------------------------

@dataclass
class SimulationResult:
    """Summary of a simulation run."""
    success: bool
    total_actions_executed: int = 0
    anomalies_encountered: List[AnomalyEvent] = field(default_factory=list)
    replans_triggered: int = 0
    final_state: Optional[WorldState] = None
    failure_reason: str = ""


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

    def __init__(
        self,
        domain_path: str,
        problem_path: str,
        anomaly_chance: float = 0.2,
        seed: Optional[int] = None,
        verbose: bool = True,
        max_anomalies: int = 5,
        scheduled_anomalies: Optional[List[ScheduledAnomaly]] = None,
        search: str = "eager_greedy([ff()])",
        export_states_dir: Optional[str] = None,
        json_output: bool = False,
    ):
        self.domain_path = str(Path(domain_path).resolve())
        self.search = search
        self.export_states_dir = export_states_dir
        self.json_output = json_output
        
        # Clear out previous state history if enabled
        if self.export_states_dir:
            os.makedirs(self.export_states_dir, exist_ok=True)
            for filename in os.listdir(self.export_states_dir):
                file_path = os.path.join(self.export_states_dir, filename)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                except Exception:
                    pass  # Ignore files that might be locked by editors in Windows
            
        self.problem_path = str(Path(problem_path).resolve())
        self.anomaly_chance = anomaly_chance
        self.verbose = verbose

        # Parse the domain and problem
        self.domain = parse_domain(self.domain_path)
        self.problem = parse_problem(self.problem_path)

        # Initialize world state
        self.state = initialize_from_problem(self.problem)

        # Components
        self.anomaly_gen = AnomalyGenerator(
            anomaly_chance=anomaly_chance,
            seed=seed,
            max_anomalies=max_anomalies,
        )
        self.scheduled_anomalies = list(scheduled_anomalies or [])

        self.case_library = CaseLibrary()

        # Tracking
        self.result = SimulationResult(success=False)
        self._replan_counter = 0
        self._export_seq = 0

    def _export_state(self, suffix: str):
        if not self.export_states_dir:
            return
        os.makedirs(self.export_states_dir, exist_ok=True)
        filename = f"{self._export_seq:03d}_{suffix}.pddl"
        out_path = os.path.join(self.export_states_dir, filename)
        generate_problem_pddl(state=self.state, original_problem=self.problem, response=None, output_path=out_path)
        self._export_seq += 1

    def _emit_json_state(self):
        """Emit world state as JSON for UI visualization."""
        if not self.json_output:
            return
            
        data = {
            "locations": list(self.state.all_locations),
            "trucks": {t: loc for t, loc in self.state.truck_locations.items()},
            "packages_at_locations": {pkg: loc for pkg, loc in self.state.package_locations.items()},
            "cargo": [{"package": p, "truck": t, "area": a} for p, t, a in self.state.cargo],
            "connections": [[f, t] for f, t in self.state.connections],
            "delivered": [{"package": p, "location": l, "time": t} for p, l, t in self.state.delivered],
            "current_time": self.state.current_time,
            "goals": [{"predicate": gc.predicate, "arguments": gc.arguments} for gc in self.problem.goal_conditions],
        }
        self._log(f"@@MAP_STATE@@{json.dumps(data)}")

    def run(self) -> SimulationResult:
        """Execute the full simulation loop."""
        self._log("=" * 65)
        self._log("  TRUCKS DOMAIN — ANOMALY REPLANNING SIMULATOR")
        self._log("=" * 65)
        self._log(f"  Problem: {self.problem.name}")
        self._log(f"  Domain:  {self.domain.name}")
        self._log(f"  Anomaly chance: {self.anomaly_chance:.0%}")
        self._log(f"  Case library: {len(self.case_library.cases)} cases loaded")
        self._log("=" * 65)
        self._log("")

        # --- Initial plan ---
        self._log("━" * 65)
        self._log("  PHASE 1: Generating initial plan")
        self._log("━" * 65)

        cleanup_planner_files()
        plan = run_fast_downward(self.domain_path, self.problem_path, search=self.search)

        if plan is None:
            self._log("  ❌ Fast Downward could not find an initial plan.")
            self.result.failure_reason = "No initial plan found."
            return self.result

        self._log(f"  ✅ Initial plan: {len(plan)} actions")
        self._log("")
        self._print_plan(plan)

        # --- Execution loop ---
        self._log("")
        self._log("━" * 65)
        self._log("  PHASE 2: Executing plan with anomaly monitoring")
        self._log("━" * 65)
        self._log("")
        self._log("  Initial state:")
        self._log(state_summary(self.state))
        self._log("")

        self._export_state("initial")
        self._emit_json_state()

        step = 0
        plan_idx = 0

        while plan_idx < len(plan):
            action = plan[plan_idx]
            step += 1

            # --- Check for anomaly ---
            anomaly = None

            scheduled = next(
                (
                    item
                    for item in self.scheduled_anomalies
                    if item.step == step
                ),
                None,
            )

            if scheduled is not None:
                self.scheduled_anomalies.remove(scheduled)

                try:
                    anomaly = create_manual_event(
                        scheduled,
                        self.state,
                    )
                except ValueError as error:
                    self._log(
                        f"  ⚠️ Scheduled anomaly at step {step} was rejected: {error}"
                    )

            if anomaly:
                self._log(f"  ╔══════════════════════════════════════════════")
                self._log(f"  ║ 🔴 ANOMALY at step {step}!")
                self._log(f"  ║ {anomaly.description}")
                self._log(f"  ╚══════════════════════════════════════════════")
                self.result.anomalies_encountered.append(anomaly)

                # --- Case-Based Reasoning ---
                case = self.case_library.recognize(anomaly)
                if case is None:
                    self._log(f"  ⚠️  No matching case found! Attempting to continue...")
                    plan_idx += 1
                    continue

                self._log(f"  🧠 Case matched: '{case.name}'")
                response = self.case_library.get_response(case, anomaly, self.state)
                self._log(f"  📋 Response: {response.explanation}")

                # --- Apply state modifications from anomaly ---
                self._apply_anomaly_to_state(anomaly, response)
                self._export_state(f"anomaly_{anomaly.anomaly_type.name}")

                # --- Replan ---
                self._log("")
                self._log(f"  🔵 REPLANNING (attempt #{self._replan_counter + 1})...")
                new_plan = self._replan(response)

                if new_plan is None:
                    self._log(f"  ❌ Replanning failed — no valid plan found.")
                    self.result.failure_reason = (
                        f"Replanning failed after {anomaly.anomaly_type.name} anomaly."
                    )
                    self.result.final_state = self.state
                    return self.result

                self._replan_counter += 1
                self.result.replans_triggered += 1
                self._log(f"  ✅ New plan: {len(new_plan)} actions")
                self._print_plan(new_plan)

                # Replace current plan
                plan = new_plan
                plan_idx = 0
                self._log("")
                self._emit_json_state()
                continue

            self._log(f"  Step {step:3d}: 🟢 {action}")
            self.state = apply_action(self.state, action)
            self.result.total_actions_executed += 1
            plan_idx += 1
            
            action_clean = f"action_{action.name}_" + "_".join(action.args)
            self._export_state(action_clean)
            self._emit_json_state()

            if self.verbose:
                self._log(state_summary(self.state))
                self._log("")

        # --- Final report ---
        self._log("")
        self._log("━" * 65)
        self._log("  PHASE 3: Mission Report")
        self._log("━" * 65)
        self.result.success = True
        self.result.final_state = self.state
        self._print_report()

        return self.result

    def _apply_anomaly_to_state(self, anomaly: AnomalyEvent, response: CaseResponse):
        """Apply the immediate effects of an anomaly to the world state."""

        if anomaly.anomaly_type == AnomalyType.ROAD_CLOSURE:
            for from_loc, to_loc in response.remove_connections:
                self.state.connections.discard((from_loc, to_loc))
                self._log(f"  ↳ Removed connection: {from_loc} ↔ {to_loc}")

        elif anomaly.anomaly_type == AnomalyType.TRUCK_BREAKDOWN:
            truck = anomaly.details["truck"]
            loc = anomaly.details["location"]

            # Dump all cargo at current location
            to_remove = []
            for pkg, t, area in self.state.cargo:
                if t == truck:
                    to_remove.append((pkg, t, area))
                    self.state.package_locations[pkg] = loc
                    self.state.free_areas.add((area, truck))
                    self._log(f"  ↳ Dumped {pkg} at {loc}")

            for item in to_remove:
                self.state.cargo.discard(item)

            # Remove truck from active service
            if truck in self.state.truck_locations:
                del self.state.truck_locations[truck]
            self.state.all_trucks = [t for t in self.state.all_trucks if t != truck]
            self._log(f"  ↳ Removed {truck} from service")

        elif anomaly.anomaly_type == AnomalyType.NEW_DELIVERY:
            pkg = anomaly.details["package"]
            origin = anomaly.details["origin"]
            self.state.all_packages.append(pkg)
            self.state.package_locations[pkg] = origin
            self._log(f"  ↳ Added {pkg} at {origin}")

        elif anomaly.anomaly_type == AnomalyType.DEADLINE_CHANGE:
            # Deadline changes are handled in goal modification during replanning
            self._log(f"  ↳ Deadline modification will be applied during replanning")

    def _replan(self, response: CaseResponse) -> Optional[List[PlanAction]]:
        """Generate a new plan by writing a modified PDDL problem and re-invoking Fast Downward."""
        # Create a temporary problem file
        temp_dir = tempfile.mkdtemp(prefix="trucks_replan_")
        temp_problem = os.path.join(temp_dir, "replanned_problem.pddl")
        temp_plan = os.path.join(temp_dir, "sas_plan")

        # Generate the modified problem
        pddl_text = generate_problem_pddl(
            state=self.state,
            original_problem=self.problem,
            response=response,
            output_path=temp_problem,
        )

        if self.verbose:
            self._log(f"  [Replan] Generated problem file: {temp_problem}")
            self._log(f"  [Replan] Problem preview:")
            for line in pddl_text.split('\n')[:5]:
                self._log(f"    {line}")
            self._log(f"    ...")

        # Invoke Fast Downward on the modified problem
        cleanup_planner_files()
        plan = run_fast_downward(
            self.domain_path,
            temp_problem,
            search=self.search,
            plan_file=temp_plan,
        )

        return plan

    def _print_plan(self, plan: List[PlanAction]):
        """Print a plan summary."""
        self._log(f"  Plan ({len(plan)} actions):")
        for i, action in enumerate(plan):
            self._log(f"    {i+1:3d}. {action}")

    def _print_report(self):
        """Print the final simulation report."""
        r = self.result
        status = "✅ SUCCESS" if r.success else "❌ FAILED"
        self._log(f"  Status: {status}")
        if r.failure_reason:
            self._log(f"  Reason: {r.failure_reason}")
        self._log(f"  Actions executed: {r.total_actions_executed}")
        self._log(f"  Anomalies encountered: {len(r.anomalies_encountered)}")
        for a in r.anomalies_encountered:
            self._log(f"    • {a.anomaly_type.name}: {a.description}")
        self._log(f"  Replans triggered: {r.replans_triggered}")
        self._log("")
        self._log("  Final state:")
        if r.final_state:
            self._log(state_summary(r.final_state))

        # Check goal satisfaction
        if r.final_state:
            delivered = r.final_state.delivered
            at_dest = r.final_state.at_destination
            self._log(f"  Deliveries completed: {len(delivered) + len(at_dest)}")

        self._log("")
        self._log("=" * 65)

    def _log(self, message: str):
        """Print a log message (handles Windows console encoding)."""
        try:
            print(message)
        except UnicodeEncodeError:
            # Fallback: replace unencodable characters
            print(message.encode('ascii', errors='replace').decode('ascii'))
