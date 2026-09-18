import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anomalies import AnomalyType, ScheduledAnomaly
from main import build_id_anomaly
import planner
from planner import parse_plan, resolve_fast_downward_script
from simulator import Simulator
from state import PlanAction


DOMAIN = ROOT / "fast-downward-24.06.1" / "trucks" / "domain.pddl"
PROBLEM = ROOT / "fast-downward-24.06.1" / "trucks" / "p01.pddl"
PLAN = ROOT / "plans" / "p01.plan"


def make_simulator(**kwargs):
    return Simulator(
        domain_path=str(DOMAIN),
        problem_path=str(PROBLEM),
        plan_path=str(PLAN),
        verbose=False,
        **kwargs,
    )


class SimulatorTests(unittest.TestCase):
    def run_quietly(self, simulator):
        with redirect_stdout(io.StringIO()):
            return simulator.run()

    def test_supplied_plan_completes_problem(self):
        result = self.run_quietly(make_simulator())
        self.assertTrue(result.success, result.failure_reason)
        self.assertEqual(result.total_actions_executed, 13)
        self.assertEqual(result.replans_triggered, 0)

    def test_invalid_supplied_plan_is_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".plan", delete=False) as handle:
            handle.write("(drive truck1 l3 l99 t0 t1)\n")
            invalid_plan = handle.name

        simulator = Simulator(
            domain_path=str(DOMAIN),
            problem_path=str(PROBLEM),
            plan_path=invalid_plan,
            verbose=False,
        )
        result = self.run_quietly(simulator)
        self.assertFalse(result.success)
        self.assertIn("no active road", result.failure_reason)

    def test_separate_anomaly_and_step_ids(self):
        anomaly = build_id_anomaly("1", 2, ["l1", "l3"])
        self.assertEqual(anomaly.step, 2)
        self.assertEqual(anomaly.anomaly_type, AnomalyType.ROAD_CLOSURE)
        self.assertEqual(anomaly.details, {"from": "l1", "to": "l3"})

    def test_rejected_scheduled_anomaly_fails_run(self):
        scheduled = ScheduledAnomaly(
            step=2,
            anomaly_type=AnomalyType.ROAD_CLOSURE,
            details={"from": "l1", "to": "l99"},
        )
        result = self.run_quietly(
            make_simulator(scheduled_anomalies=[scheduled])
        )
        self.assertFalse(result.success)
        self.assertIn("was rejected", result.failure_reason)

    def test_unreached_anomaly_step_fails_run(self):
        scheduled = ScheduledAnomaly(
            step=99,
            anomaly_type=AnomalyType.ROAD_CLOSURE,
            details={"from": "l1", "to": "l3"},
        )
        result = self.run_quietly(
            make_simulator(scheduled_anomalies=[scheduled])
        )
        self.assertFalse(result.success)
        self.assertIn("step(s): 99", result.failure_reason)

    @patch("simulator.run_fast_downward")
    def test_scheduled_anomaly_triggers_replan(self, mock_planner):
        # This is the valid replacement plan from the state after step 1.
        # Replanning extends ordinary deadlines through t11.
        mock_planner.return_value = [
            PlanAction("load", ["package2", "truck1", "a2", "l2"]),
            PlanAction("load", ["package1", "truck1", "a1", "l2"]),
            PlanAction("drive", ["truck1", "l2", "l3", "t1", "t2"]),
            PlanAction("unload", ["package1", "truck1", "a1", "l3"]),
            PlanAction("deliver", ["package1", "l3", "t2", "t11"]),
            PlanAction("drive", ["truck1", "l3", "l2", "t2", "t3"]),
            PlanAction("load", ["package3", "truck1", "a1", "l2"]),
            PlanAction("drive", ["truck1", "l2", "l1", "t3", "t4"]),
            PlanAction("unload", ["package3", "truck1", "a1", "l1"]),
            PlanAction("unload", ["package2", "truck1", "a2", "l1"]),
            PlanAction("deliver", ["package2", "l1", "t4", "t4"]),
            PlanAction("deliver", ["package3", "l1", "t4", "t11"]),
        ]
        scheduled = ScheduledAnomaly(
            step=2,
            anomaly_type=AnomalyType.ROAD_CLOSURE,
            details={"from": "l1", "to": "l3"},
        )

        result = self.run_quietly(
            make_simulator(scheduled_anomalies=[scheduled])
        )

        self.assertTrue(result.success, result.failure_reason)
        self.assertEqual(result.replans_triggered, 1)
        self.assertEqual(len(result.anomalies_encountered), 1)
        mock_planner.assert_called_once()

    def test_plan_parser_rejects_malformed_lines(self):
        with tempfile.NamedTemporaryFile("w", suffix=".plan", delete=False) as handle:
            handle.write("drive truck1 l3 l2 t0 t1\n")
            malformed_plan = handle.name

        with self.assertRaisesRegex(ValueError, "Invalid plan syntax"):
            parse_plan(malformed_plan)

    def test_explicit_fast_downward_directory_is_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            resolved = resolve_fast_downward_script(directory)
            self.assertEqual(resolved, Path(directory) / "fast-downward.py")

    def test_fast_downward_environment_path_is_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {"FAST_DOWNWARD_PATH": directory},
                clear=True,
            ):
                resolved = resolve_fast_downward_script()
            self.assertEqual(resolved, Path(directory) / "fast-downward.py")

    def test_saved_fast_downward_path_is_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / ".fast-downward-path"
            checkout = Path(directory) / "checkout"
            checkout.mkdir()
            config.write_text(str(checkout), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(planner, "FAST_DOWNWARD_CONFIG", config):
                    resolved = resolve_fast_downward_script()
            self.assertEqual(resolved, checkout / "fast-downward.py")


if __name__ == "__main__":
    unittest.main()
