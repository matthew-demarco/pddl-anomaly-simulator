"""
Plan Simulator for the Trucks Domain.

Executes a plan step-by-step, checking for anomalies before each action.
When an anomaly is detected, invokes the Case-Based Reasoner and triggers
replanning with a modified PDDL problem file.

The initial plan comes from one of two sources:
  * LOAD:     a pre-made plan file (plan_path given)
  * GENERATE: Fast Downward plans it from the problem (plan_path omitted)

Every state is recorded in self.state_history as a plain dict ("snapshot"),
including one frame per hour while a truck drives a multi-hour road. The
browser app (server.py) reads state_history directly; the Tkinter GUI reads
the same snapshots as @@MAP_STATE@@ JSON lines when json_output is on.
"""

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from anomalies import AnomalyEvent, AnomalyGenerator, AnomalyType, ScheduledAnomaly, create_manual_event
from case_library import CaseLibrary, CaseResponse
from pddl_parser import parse_domain, parse_problem
from pddl_writer import generate_problem_pddl
from planner import parse_plan, run_fast_downward
from state import (
    PlanAction,
    WorldState,
    apply_action,
    initialize_from_problem,
    state_summary,
    validate_action,
)


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
    plan_source: str = ""                     # "loaded" or "generated"
    saved_plan_path: Optional[str] = None     # set when a generated plan was saved


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class Simulator:
    """
    Step-by-step plan executor with anomaly injection and replanning.

    Flow:
        1. Get the initial plan: load plan_path, or generate it with Fast Downward
        2. For each action in the plan:
           a. Check for a user-scheduled anomaly (or, if anomaly_chance > 0,
              a random one from the AnomalyGenerator)
           b. If anomaly:
              i.   Recognize via CaseLibrary
              ii.  Apply PDDL modifications
              iii. Regenerate problem file
              iv.  Re-invoke Fast Downward
              v.   Continue with new plan
           c. Validate and execute the action, update world state
              (drives emit one frame per hour on the road)
        3. Report results
    """

    def __init__(
        self,
        domain_path: str,
        problem_path: str,
        plan_path: Optional[str] = None,
        anomaly_chance: float = 0.0,
        seed: Optional[int] = None,
        verbose: bool = True,
        max_anomalies: int = 5,
        scheduled_anomalies: Optional[List[ScheduledAnomaly]] = None,
        search: str = "eager_greedy([ff()])",
        fast_downward_script: Optional[str] = None,
        export_states_dir: Optional[str] = None,
        json_output: bool = False,
        save_plan_path: Optional[str] = None,
    ):
        self.domain_path = str(Path(domain_path).resolve())
        self.problem_path = str(Path(problem_path).resolve())
        self.plan_path = str(Path(plan_path).resolve()) if plan_path else None
        self.save_plan_path = str(Path(save_plan_path).resolve()) if save_plan_path else None
        self.search = search
        self.fast_downward_script = fast_downward_script
        self.export_states_dir = export_states_dir
        self.json_output = json_output
        self.verbose = verbose
        self.anomaly_chance = anomaly_chance

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

        # Parse the domain and problem
        self.domain = parse_domain(self.domain_path)
        self.problem = parse_problem(self.problem_path)

        # Initialize world state
        self.state = initialize_from_problem(self.problem)

        # Components
        self.anomaly_gen = AnomalyGenerator(                             # Random anomalies (off unless anomaly_chance > 0).
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
        self._step = 0
        self._plan_id = 0
        self._plan_pos = 0
        self._broken_trucks: Set[str] = set()
        self._initial_edges: Set[Tuple[str, str]] = {
            tuple(sorted(c)) for c in self.state.connections
        }

        # In-memory snapshot history, always collected (regardless of
        # json_output) so a caller holding the Simulator (server.py, a test,
        # a notebook) can read it directly. self.plans lists every plan used:
        # the initial one plus one per replan.
        self.state_history: List[Dict[str, Any]] = []
        self.plans: List[Dict[str, Any]] = []
        self._last_event: Optional[str] = None

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def _export_state(self, suffix: str):
        if not self.export_states_dir:
            return
        os.makedirs(self.export_states_dir, exist_ok=True)
        filename = f"{self._export_seq:03d}_{suffix}.pddl"
        out_path = os.path.join(self.export_states_dir, filename)
        generate_problem_pddl(state=self.state, original_problem=self.problem, response=None, output_path=out_path)
        self._export_seq += 1

    @staticmethod
    def _time_index(t: Optional[str]) -> Optional[int]:
        """Hour number of a time name like 't3' (by its number, so it stays correct after replans)."""
        if t and t[1:].isdigit():
            return int(t[1:])
        return None

    def _grid_info(self) -> Dict[str, Any]:
        """Return the grid layout: 1 cell = 1 mile. Empty when the problem has no coordinates."""
        locs = {}
        for loc in self.state.all_locations:
            x, y = self.state.loc_x.get(loc), self.state.loc_y.get(loc)
            if x is not None and y is not None:
                locs[loc] = [x, y]

        width = max((v[0] for v in locs.values()), default=-1) + 1
        height = max((v[1] for v in locs.values()), default=-1) + 1
        return {"width": width, "height": height, "locations": locs}

    def _roads_info(self) -> List[Dict[str, Any]]:
        """Every road that existed at the start (one entry per pair), with metrics and open/closed status."""
        open_edges = {tuple(sorted(c)) for c in self.state.connections}
        roads = []
        for a, b in sorted(self._initial_edges):
            d = self.state.road_distance.get((a, b), self.state.road_distance.get((b, a)))
            s = self.state.road_speed.get((a, b), self.state.road_speed.get((b, a)))
            roads.append({
                "from": a,
                "to": b,
                "distance": d,
                "speed": s,
                "duration": self.state.road_duration(a, b) if d is not None and s is not None else None,
                "closed": (a, b) not in open_edges,
            })
        return roads

    def _resting_position(self, truck: str) -> Dict[str, Any]:
        """A truck's display position when parked at a location."""
        loc = self.state.truck_locations.get(truck)
        return {
            "x": self.state.loc_x.get(loc),
            "y": self.state.loc_y.get(loc),
            "road": None,
            "location": loc,
            "fraction": 0.0,
        }

    def _build_state_snapshot(self, kind: str = "action") -> Dict[str, Any]:
        """Build a plain-dict snapshot of the current world state."""
        s = self.state
        open_edges = {tuple(sorted(c)) for c in s.connections}
        return {
            "kind": kind,                       # initial | action | transit | anomaly | stopped
            "step": self._step,
            "plan_id": self._plan_id,
            "plan_pos": self._plan_pos,         # actions of the current plan already done
            "locations": list(s.all_locations),
            "trucks": dict(s.truck_locations),
            "broken_trucks": sorted(self._broken_trucks),
            "packages_at_locations": dict(s.package_locations),
            "cargo": [{"package": p, "truck": t, "area": a} for p, t, a in sorted(s.cargo)],
            "connections": [[f, t] for f, t in sorted(s.connections)],
            "closed_roads": [list(e) for e in sorted(self._initial_edges - open_edges)],
            "delivered": [{"package": p, "location": l, "time": t} for p, l, t in sorted(s.delivered)],
            "current_time": s.current_time,
            "hour": self._time_index(s.current_time),
            "grid": self._grid_info(),
            "roads": self._roads_info(),
            "truck_positions": {t: self._resting_position(t) for t in s.truck_locations},
            "goals": [{"predicate": g.predicate, "arguments": g.arguments} for g in self.problem.goal_conditions],
            "last_action": self._last_event,
        }

    def initial_snapshot(self) -> Dict[str, Any]:
        """The map before anything runs (used by the browser to show a problem immediately)."""
        return self._build_state_snapshot(kind="initial")

    def _emit_json_state(
        self,
        event: Optional[str] = None,
        snapshot: Optional[Dict[str, Any]] = None,
        kind: str = "action",
        extra: Optional[Dict[str, Any]] = None,
    ):
        """Record a snapshot in self.state_history, and print it as an
        @@MAP_STATE@@ JSON line when json_output is set (read by gui.py)."""
        if event is not None:
            self._last_event = event

        if snapshot is None:
            snapshot = self._build_state_snapshot(kind)
        snapshot["last_action"] = self._last_event
        if extra:
            snapshot.update(extra)

        self.state_history.append(snapshot)

        if self.json_output:
            self._log(f"@@MAP_STATE@@{json.dumps(snapshot)}")

    def _register_plan(self, plan: List[PlanAction], label: str, source: str):
        self.plans.append({
            "id": len(self.plans),
            "label": label,
            "source": source,
            "actions": [str(a) for a in plan],
        })
        self._plan_id = len(self.plans) - 1
        self._plan_pos = 0

    # ------------------------------------------------------------------
    # Setup checks and the initial plan
    # ------------------------------------------------------------------

    def _compatibility_error(self) -> Optional[str]:
        """Explain a domain/problem mismatch before Fast Downward gives a cryptic error."""
        domain_uses_spans = any("road-span" in a.precondition_raw for a in self.domain.actions)
        problem_has_spans = any(p == "road-span" for p, _ in self.problem.init_facts)

        if domain_uses_spans and self.state.connections and not problem_has_spans:
            return (
                "This problem has no road distance/speed data, but domain.pddl needs it. "
                "Upgrade the problem with: py tools/upgrade_problems.py"
            )
        if problem_has_spans and not domain_uses_spans:
            return (
                "This problem has road distance/speed data, but domain.pddl is the original "
                "Trucks domain. Replace domain.pddl with the extended version."
            )
        return None

    def _get_initial_plan(self) -> Optional[List[PlanAction]]:
        """Load the supplied plan, or generate one with Fast Downward. Sets failure_reason on error."""
        if self.plan_path:
            self.result.plan_source = "loaded"
            self._log("  PHASE 1: Loading supplied initial plan")
            self._log("━" * 65)
            try:
                return parse_plan(self.plan_path)
            except (OSError, ValueError) as error:
                self._log(f"  ❌ Could not load supplied plan: {error}")
                self.result.failure_reason = f"Invalid supplied plan: {error}"
                return None

        self.result.plan_source = "generated"
        self._log("  PHASE 1: Generating initial plan with Fast Downward")
        self._log("━" * 65)
        plan = run_fast_downward(
            self.domain_path,
            self.problem_path,
            search=self.search,
            plan_file=self.save_plan_path,                              # None -> .planner-output/sas_plan
            fast_downward_script=self.fast_downward_script,
        )
        if plan is None:
            self._log("  ❌ Fast Downward could not generate an initial plan.")
            self.result.failure_reason = (
                "No initial plan: Fast Downward was not found, or the problem is unsolvable "
                "(see the [Planner] lines above)."
            )
            return None

        if self.save_plan_path:
            self.result.saved_plan_path = self.save_plan_path
            self._log(f"  💾 Saved generated plan to {self.save_plan_path}")
        return plan

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> SimulationResult:
        """Execute the full simulation loop."""
        self._log("=" * 65)
        self._log("  TRUCKS DOMAIN — ANOMALY REPLANNING SIMULATOR")
        self._log("=" * 65)
        self._log(f"  Problem: {self.problem.name}")
        self._log(f"  Domain:  {self.domain.name}")
        self._log(f"  Plan source: {self.plan_path or 'generated by Fast Downward'}")
        self._log(f"  Scheduled anomalies: {len(self.scheduled_anomalies)}")
        self._log(f"  Anomaly chance: {self.anomaly_chance:.0%}")
        self._log(f"  Case library: {len(self.case_library.cases)} cases loaded")
        self._log("=" * 65)
        self._log("")

        mismatch = self._compatibility_error()
        if mismatch:
            self._log(f"  ❌ {mismatch}")
            self.result.failure_reason = mismatch
            return self.result

        # --- Initial plan ---
        self._log("━" * 65)
        plan = self._get_initial_plan()
        if plan is None:
            return self.result
        if not plan:
            self._log("  ❌ The initial plan contains no actions.")
            self.result.failure_reason = "Initial plan is empty."
            return self.result

        self._log(f"  ✅ Initial plan: {len(plan)} actions ({self.result.plan_source})")
        self._log("")
        self._print_plan(plan)
        self._register_plan(plan, "Initial plan", self.result.plan_source)

        # --- Execution loop ---
        self._log("")
        self._log("━" * 65)
        self._log("  PHASE 2: Executing plan with anomaly monitoring")
        self._log("━" * 65)
        self._log("")
        self._log("  Initial state:")
        self._log(state_summary(self.state, include_roads=True))
        self._log("")

        self._export_state("initial")
        self._emit_json_state(event="(initial state)", kind="initial")

        plan_idx = 0

        while plan_idx < len(plan):
            action = plan[plan_idx]
            self._step += 1
            step = self._step

            # --- Check for a scheduled anomaly ---
            anomaly = None
            scheduled = next((item for item in self.scheduled_anomalies if item.step == step), None)

            if scheduled is not None:
                self.scheduled_anomalies.remove(scheduled)

                try:
                    anomaly = create_manual_event(scheduled, self.state)
                except ValueError as error:
                    self._log(f"  ⚠️ Scheduled anomaly at step {step} was rejected: {error}")
                    return self._stop(f"Scheduled anomaly at step {step} was rejected: {error}")

            if anomaly is None and self.anomaly_chance > 0:
                # No anomaly scheduled at this step: fall back to the random
                # anomaly generator (anomaly-chance control in the GUI / browser).
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
                try:
                    new_plan = self._replan(response)
                except ValueError as error:                              # e.g. a deadline the writer cannot keep
                    self._log(f"  ❌ {error}")
                    new_plan = None

                if new_plan is None:
                    self._log(f"  ❌ Replanning failed — no valid plan found.")
                    return self._stop(f"Replanning failed after {anomaly.anomaly_type.name} anomaly.")

                self._replan_counter += 1
                self.result.replans_triggered += 1
                self._log(f"  ✅ New plan: {len(new_plan)} actions")
                self._print_plan(new_plan)

                # Replace current plan
                plan = new_plan
                plan_idx = 0
                self._register_plan(plan, f"Replan #{self._replan_counter}", "replanned")
                self._log("")
                self._emit_json_state(
                    event=f"ANOMALY: {anomaly.description}",
                    kind="anomaly",
                    extra={"anomaly": {
                        "step": step,
                        "type": anomaly.anomaly_type.name,
                        "description": anomaly.description,
                        "response": response.explanation,
                    }},
                )
                continue

            self._log(f"  Step {step:3d}: 🟢 {action}")
            try:
                if action.name.lower() in ("drive", "drive-instant"):
                    self._execute_drive(action)                          # Emits hourly frames, then applies the action.
                else:
                    self.state = apply_action(self.state, action)
                    self.result.total_actions_executed += 1
                    self._plan_pos += 1
                    self._finish_action(action)
            except ValueError as error:
                self._log(f"  ❌ {error}")
                return self._stop(str(error))

            plan_idx += 1

            if self.verbose:
                self._log(state_summary(self.state))
                self._log("")

        # --- Final report ---
        self._log("")
        self._log("━" * 65)
        self._log("  PHASE 3: Mission Report")
        self._log("━" * 65)
        self.result.final_state = self.state
        pending_steps = sorted(item.step for item in self.scheduled_anomalies)
        unsatisfied = self._unsatisfied_goals()
        if pending_steps:
            self.result.success = False
            self.result.failure_reason = (
                "Plan ended before scheduled anomaly step(s): "
                + ", ".join(str(s) for s in pending_steps)
            )
        elif unsatisfied:
            self.result.success = False
            self.result.failure_reason = "Plan ended before satisfying: " + ", ".join(unsatisfied)
        else:
            self.result.success = True
        self._print_report()

        return self.result

    def _stop(self, reason: str) -> SimulationResult:
        """End the run early with a reason, recording a final 'stopped' frame for the map."""
        self.result.failure_reason = reason
        self.result.final_state = self.state
        self._emit_json_state(event=f"STOPPED: {reason}", kind="stopped")
        self._print_report()
        return self.result

    def _unsatisfied_goals(self) -> List[str]:
        """Return readable descriptions of goals missing from the final state."""
        missing = []
        for goal in self.problem.goal_conditions:
            args = goal.arguments
            satisfied = False
            if goal.predicate == "delivered" and len(args) == 3:
                satisfied = tuple(args) in self.state.delivered
            elif goal.predicate == "at-destination" and len(args) == 2:
                satisfied = tuple(args) in self.state.at_destination

            if not satisfied:
                missing.append(f"({goal.predicate} {' '.join(args)})")
        return missing

    # ------------------------------------------------------------------
    # Executing actions
    # ------------------------------------------------------------------

    def _execute_drive(self, action: PlanAction):
        """Execute a drive, emitting one snapshot per hour while the truck is on the road.

        The truck's motion is normalized to the road's rounded travel time: on a
        2t road it covers half the distance at each hourly tick, so it always
        arrives exactly on the final tick. Intermediate frames keep the truck
        logically at its origin while displaying its interpolated grid position.
        """
        error = validate_action(self.state, action)                     # Never draw frames for an invalid drive.
        if error:
            raise ValueError(f"Invalid action {action}: {error}")

        state = self.state
        truck, from_loc, to_loc, t1 = action.args[:4]
        steps = state.time_steps
        i1 = steps.index(t1)
        dur = 0 if action.name.lower() == "drive-instant" else steps.index(action.args[4]) - i1

        d = state.road_distance.get((from_loc, to_loc))
        s = state.road_speed.get((from_loc, to_loc))
        x1, y1 = state.loc_x.get(from_loc), state.loc_y.get(from_loc)
        x2, y2 = state.loc_x.get(to_loc), state.loc_y.get(to_loc)

        # In-transit frames for each completed hour except the arrival hour.
        for h in range(1, dur):
            snapshot = self._build_state_snapshot(kind="transit")
            t_mid = steps[i1 + h]
            snapshot["current_time"] = t_mid
            snapshot["hour"] = self._time_index(t_mid)

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
            if None not in (x1, y1, x2, y2):
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
        self._plan_pos += 1
        self._finish_action(action)

    def _finish_action(self, action: PlanAction):
        """Export state and emit the post-action snapshot."""
        action_clean = f"action_{action.name}_" + "_".join(action.args)
        self._export_state(action_clean)
        self._emit_json_state(event=str(action), kind="action")

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
            self._broken_trucks.add(truck)
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
        temp_dir = tempfile.mkdtemp(prefix="trucks_replan_")
        temp_problem = os.path.join(temp_dir, "replanned_problem.pddl")
        temp_plan = os.path.join(temp_dir, "sas_plan")

        try:
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

            plan = run_fast_downward(
                self.domain_path,
                temp_problem,
                search=self.search,
                plan_file=temp_plan,
                fast_downward_script=self.fast_downward_script,
            )

            if plan is not None:
                # The generated problem contains all accumulated anomaly goal
                # changes. Keeping it as the current problem ensures a later
                # replan does not forget an earlier new delivery/deadline change.
                self.problem = parse_problem(temp_problem)
                self.state.time_steps = list(self.problem.objects.get("time", []))
                self.state.le_predicates = {
                    (args[0], args[1])
                    for predicate, args in self.problem.init_facts
                    if predicate == "le" and len(args) == 2
                }
            return plan
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

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

        if r.final_state:
            completed = {p for p, _, _ in r.final_state.delivered}
            completed.update(p for p, _ in r.final_state.at_destination)
            self._log(f"  Deliveries completed: {len(completed)}")

        self._log("")
        self._log("=" * 65)

    def _log(self, message: str):
        """Print a log message (handles Windows console encoding)."""
        try:
            print(message)
        except UnicodeEncodeError:
            print(message.encode('ascii', errors='replace').decode('ascii'))


def summarize_result(sim: "Simulator", result: SimulationResult) -> Dict[str, Any]:
    """Plain-dict run summary shared by server.py and get_run_snapshots()."""
    return {
        "status": "SUCCESS" if result.success else "FAILED",
        "failure_reason": result.failure_reason,
        "plan_source": result.plan_source,
        "saved_plan": result.saved_plan_path,
        "actions_executed": result.total_actions_executed,
        "replans_triggered": result.replans_triggered,
        "anomalies": [
            {"type": a.anomaly_type.name, "description": a.description}
            for a in result.anomalies_encountered
        ],
    }


def get_run_snapshots(domain_path: str, problem_path: str, **simulator_kwargs) -> Dict[str, Any]:
    """
    Run a simulation in-process and return everything a visualizer needs,
    with no subprocess and no stdout parsing involved:
        {"snapshots": [...], "plans": [...], "summary": {...}}
    """
    sim = Simulator(domain_path=domain_path, problem_path=problem_path, **simulator_kwargs)
    result = sim.run()
    return {"snapshots": sim.state_history, "plans": sim.plans, "summary": summarize_result(sim, result)}
