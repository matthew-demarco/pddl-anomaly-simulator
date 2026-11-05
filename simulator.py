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
from typing import List, Optional, Tuple, Dict, Any
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

        # In-memory snapshot history, always collected regardless of
        # --json-output, so a caller running the Simulator directly (e.g. a
        # visualizer) can read sim.state_history after/while run() executes.
        self.state_history: List[Dict[str, Any]] = []
        self._last_event: Optional[str] = None

    def _export_state(self, suffix: str):
        if not self.export_states_dir:
            return
        os.makedirs(self.export_states_dir, exist_ok=True)
        filename = f"{self._export_seq:03d}_{suffix}.pddl"
        out_path = os.path.join(self.export_states_dir, filename)
        generate_problem_pddl(state=self.state, original_problem=self.problem, response=None, output_path=out_path)
        self._export_seq += 1

    def _time_index(self, t: str) -> Optional[int]:
        """Return the chronological index of a time-step name like 't3', or None."""
        try:
            return self.state.time_steps.index(t)
        except ValueError:
            return None

    def _grid_info(self) -> Dict[str, Any]:
        """Return the grid layout: 1 cell = 1 mile."""
        locs = {}

        for loc in self.state.all_locations:
            x = self.state.loc_x.get(loc)
            y = self.state.loc_y.get(loc)

            if x is not None and y is not None:
                locs[loc] = [x, y]

        width = max((v[0] for v in locs.values()), default=0) + 1 if locs else 0
        height = max((v[1] for v in locs.values()), default=0) + 1 if locs else 0

        return {"width": width, "height": height, "locations": locs}

    def _roads_info(self) -> List[Dict[str, Any]]:
        """Return per-road distance/speed/duration metadata for current connections."""
        roads = []

        for f, t in sorted(self.state.connections):
            d = self.state.road_distance.get((f, t))
            s = self.state.road_speed.get((f, t))

            if d is None or s is None:
                continue

            roads.append({
                "from": f,
                "to": t,
                "distance": d,
                "speed": s,
                "duration": self.state.road_duration(f, t),
            })

        return roads

    def _resting_position(self, truck: str) -> Dict[str, Any]:
        """Return a truck's display position when parked at a location."""
        loc = self.state.truck_locations.get(truck)

        return {
            "x": self.state.loc_x.get(loc),
            "y": self.state.loc_y.get(loc),
            "road": None,
            "location": loc,
            "fraction": 0.0,
        }

    def _build_state_snapshot(self) -> Dict[str, Any]:
        """Build a plain-dict snapshot of the current world state.

        Always available on self.state_history regardless of --json-output,
        so a caller holding a Simulator instance directly (a visualizer, a
        notebook, a test) can read it without going through stdout at all.
        """
        return {
            "locations": list(self.state.all_locations),
            "trucks": {t: loc for t, loc in self.state.truck_locations.items()},
            "packages_at_locations": {pkg: loc for pkg, loc in self.state.package_locations.items()},
            "cargo": [{"package": p, "truck": t, "area": a} for p, t, a in self.state.cargo],
            "connections": [[f, t] for f, t in self.state.connections],
            "delivered": [{"package": p, "location": l, "time": t} for p, l, t in self.state.delivered],
            "current_time": self.state.current_time,
            "hour": self._time_index(self.state.current_time),
            "grid": self._grid_info(),
            "roads": self._roads_info(),
            "truck_positions": {t: self._resting_position(t) for t in self.state.truck_locations},
            "goals": [{"predicate": gc.predicate, "arguments": gc.arguments} for gc in self.problem.goal_conditions],
            "last_action": self._last_event,
        }

    def _emit_json_state(self, event: Optional[str] = None, snapshot: Optional[Dict[str, Any]] = None):
        """Record a snapshot in self.state_history, and also print it to
        stdout as @@MAP_STATE@@ JSON when --json-output is set (kept for the
        existing GUI, which consumes that stream over a subprocess pipe).

        An optional prebuilt snapshot can be supplied (used for the per-hour
        in-transit frames emitted while a truck is driving a multi-hour road)."""
        if event is not None:
            self._last_event = event

        if snapshot is None:
            snapshot = self._build_state_snapshot()
        else:
            snapshot["last_action"] = self._last_event                     # Keeps supplied in-transit frames consistent with the event log.

        self.state_history.append(snapshot)

        if self.json_output:
            self._log(f"@@MAP_STATE@@{json.dumps(snapshot)}")

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
        self._emit_json_state(event="(initial state)")

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

            if anomaly is None:
                # No manually scheduled anomaly at this step: fall back to the
                # random anomaly generator (anomaly-chance control in the GUI).
                anomaly = self.anomaly_gen.maybe_trigger(self.state, action)

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

                # Adopt the replanned problem's remaining goals so snapshots
                # and reports reflect the world the new plan is pursuing.
                try:
                    from pddl_parser import parse_problem
                    replanned_problem = parse_problem(self._last_replan_problem_path)
                    self.problem.goal_conditions = replanned_problem.goal_conditions
                except Exception:
                    pass  # Keep the previous goals if the temp file is unreadable.

                # Replace current plan
                plan = new_plan
                plan_idx = 0
                self._log("")
                self._emit_json_state(event=f"ANOMALY: {anomaly.description}")
                continue

            self._log(f"  Step {step:3d}: 🟢 {action}")

            if action.name.lower() in ("drive", "drive-instant"):
                self._execute_drive(action, step)
            else:
                self.state = apply_action(self.state, action)
                self.result.total_actions_executed += 1
                self._finish_action(action)

            plan_idx += 1

            if self.verbose:
                self._log(state_summary(self.state))
                self._log("")

        # --- Final report ---
        self._log("")
        self._log("━" * 65)
        self._log("  PHASE 3: Mission Report")
        self._log("━" * 65)

        # Success requires the (possibly replanned) goals to actually hold.
        unsatisfied = self._unsatisfied_goals()

        if unsatisfied:
            self.result.success = False
            self.result.failure_reason = (
                f"Plan finished but {len(unsatisfied)} goal(s) unsatisfied: "
                + "; ".join(unsatisfied[:3])
            )
            self._log(f"  ❌ {self.result.failure_reason}")
        else:
            self.result.success = True

        self.result.final_state = self.state
        self._print_report()

        return self.result

    def _unsatisfied_goals(self) -> List[str]:
        """Return human-readable descriptions of goals that do not hold in the final state."""
        unsatisfied = []

        for goal in self.problem.goal_conditions:
            args = goal.arguments

            if goal.predicate == "delivered" and len(args) == 3:
                pkg, loc, deadline = args
                matches = [t for p, l, t in self.state.delivered if p == pkg and l == loc]

                if not matches:
                    unsatisfied.append(f"{pkg} not delivered to {loc}")
                    continue

                try:
                    delivered_idx = min(
                        self.state.time_steps.index(t) for t in matches
                    )
                    deadline_idx = self.state.time_steps.index(deadline)
                except ValueError:
                    continue

                if delivered_idx > deadline_idx:
                    unsatisfied.append(
                        f"{pkg} delivered to {loc} late ({matches[0]} > {deadline})"
                    )

            elif goal.predicate == "at-destination" and len(args) == 2:
                pkg, loc = args

                if (pkg, loc) not in self.state.at_destination:
                    unsatisfied.append(f"{pkg} not at {loc}")

        return unsatisfied

    def _execute_drive(self, action, step: int):
        """Execute a drive action, emitting one snapshot per hour in transit.

        The truck's motion is normalized to the road's rounded travel time:
        a road rated 35mi @ 30mph = 1t shows the truck covering 1/dur of the
        road at each hourly tick, so it always arrives exactly on the final
        tick. Intermediate frames keep the truck logically at its origin
        location while displaying its interpolated grid position.
        """
        state = self.state
        name = action.name.lower()

        if name == "drive-instant":
            truck, from_loc, to_loc, t1 = action.args
            dur = 0
            i1 = self._time_index(t1)
        else:
            truck, from_loc, to_loc, t1, t2 = action.args
            i1, i2 = self._time_index(t1), self._time_index(t2)
            dur = (i2 - i1) if (i1 is not None and i2 is not None and i2 >= i1) else 1

        d = state.road_distance.get((from_loc, to_loc))
        s = state.road_speed.get((from_loc, to_loc))
        x1, y1 = state.loc_x.get(from_loc), state.loc_y.get(from_loc)
        x2, y2 = state.loc_x.get(to_loc), state.loc_y.get(to_loc)

        # In-transit frames for each completed hour except the arrival hour.
        for h in range(1, dur):
            snapshot = self._build_state_snapshot()

            if i1 is not None and i1 + h < len(state.time_steps):
                t_mid = state.time_steps[i1 + h]
                snapshot["current_time"] = t_mid
                snapshot["hour"] = i1 + h

            frac = h / dur
            pos = {
                "x": None,
                "y": None,
                "road": [from_loc, to_loc],
                "location": from_loc,
                "fraction": frac,
                "speed": s,
                "distance": d,
                "miles_covered": round(frac * d, 1) if d is not None else None,
                "hours_remaining": dur - h,
            }

            if x1 is not None and x2 is not None and y1 is not None and y2 is not None:
                pos["x"] = x1 + frac * (x2 - x1)
                pos["y"] = y1 + frac * (y2 - y1)

            snapshot["truck_positions"][truck] = pos

            miles_txt = f"{frac * d:.0f}/{d}mi" if d is not None else f"{frac:.0%}"
            self._emit_json_state(
                event=f"(driving {truck} {from_loc}→{to_loc} {miles_txt})",
                snapshot=snapshot,
            )

        # Arrival: apply the action for real, then emit the final frame.
        self.state = apply_action(self.state, action)
        self.result.total_actions_executed += 1
        self._finish_action(action)

    def _finish_action(self, action):
        """Export state and emit the post-action snapshot."""
        action_clean = f"action_{action.name}_" + "_".join(action.args)
        self._export_state(action_clean)
        self._emit_json_state(event=str(action))

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
        self._last_replan_problem_path = temp_problem

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


def get_run_snapshots(
    domain_path: str,
    problem_path: str,
    **simulator_kwargs,
) -> Dict[str, Any]:
    """
    Run a simulation in-process and return everything a visualizer needs,
    with no subprocess and no stdout parsing involved.

    Returns:
        {
          "snapshots": List[dict]   # sim.state_history
          "summary": {
              "status": "SUCCESS" | "FAILED",
              "failure_reason": str,
              "actions_executed": int,
              "replans_triggered": int,
              "anomalies": [{"type": str, "description": str}, ...],
          },
        }
    """
    sim = Simulator(domain_path=domain_path, problem_path=problem_path, **simulator_kwargs)
    result = sim.run()

    return {
        "snapshots": sim.state_history,
        "summary": {
            "status": "SUCCESS" if result.success else "FAILED",
            "failure_reason": result.failure_reason,
            "actions_executed": result.total_actions_executed,
            "replans_triggered": result.replans_triggered,
            "anomalies": [
                {"type": a.anomaly_type.name, "description": a.description}
                for a in result.anomalies_encountered
            ],
        },
    }