# PDDL Anomaly Replanning Simulator

A Trucks-domain simulator that executes an externally generated plan, applies
a user-selected anomaly at a user-selected execution step, and uses Fast
Downward to create and execute a replacement plan.

## Updated workflow

1. Generate the original plan outside the simulator.
2. Supply that plan to the simulator with `--plan`.
3. Supply the anomaly ID and step ID.
4. The simulator displays and executes the original plan.
5. At the selected step, it applies the anomaly and asks Fast Downward for a
   new plan.
6. The simulator displays and executes the new plan.

The simulator no longer generates its own initial plan or randomly chooses the
anomaly and step.

## Requirements

- Python 3.9 or newer
- No pip packages are required
- Windows replanning support is included in this repository
- macOS/Linux requires a locally compiled Fast Downward checkout

## Windows quick start 

The included `fast-downward-24.06.1` folder contains the Windows planner
binary, domain, and all 30 problem files. After cloning or downloading the
repository, open PowerShell or Command Prompt in the project folder.

Check the setup:

```powershell
py check_setup.py
```

Run the supplied original plan without an anomaly:

```powershell
py main.py --problem p01 --plan plans\p01.plan
```

Run the complete road-closure and replanning demonstration:

```powershell
py main.py --problem p01 --plan plans\p01.plan --anomaly-id 1 --step-id 2 --anomaly-args l1 l3
```

For the easiest Windows demonstration, double-click:

- `run_windows_clean.bat` for the original plan only
- `run_windows_demo.bat` for the original plan, anomaly, and new plan

## macOS quick start

The compiled Fast Downward search binary is operating-system specific. First,
configure the path to a Mac-compiled Fast Downward checkout one time:

```bash
python3 configure_fast_downward.py "/path/to/fast-downward.py"
```

The path may point to either `fast-downward.py` or its containing directory.
The setting is saved locally in `.fast-downward-path` and is ignored by Git.

Check the setup:

```bash
python3 check_setup.py
```

Run the supplied original plan without an anomaly:

```bash
python3 main.py --problem p01 --plan plans/p01.plan
```

Run the complete road-closure and replanning demonstration:

```bash
python3 main.py --problem p01 --plan plans/p01.plan \
  --anomaly-id 1 --step-id 2 --anomaly-args l1 l3
```

After the one-time configuration, this shortcut runs the same demonstration:

```bash
bash run_mac_demo.sh
```

To inspect the currently selected planner:

```bash
python3 configure_fast_downward.py --show
```

You can still override the saved path for one run:

```bash
python3 main.py --problem p01 --plan plans/p01.plan \
  --anomaly-id 1 --step-id 2 --anomaly-args l1 l3 \
  --fast-downward "/another/path/to/fast-downward.py"
```

## Command cheat sheet

### Clean execution

Windows:

```powershell
py main.py --problem p01 --plan plans\p01.plan
```

macOS/Linux:

```bash
python3 main.py --problem p01 --plan plans/p01.plan
```

### One selected anomaly

Windows:

```powershell
py main.py --problem p01 --plan plans\p01.plan --anomaly-id 1 --step-id 2 --anomaly-args l1 l3
```

macOS/Linux:

```bash
python3 main.py --problem p01 --plan plans/p01.plan --anomaly-id 1 --step-id 2 --anomaly-args l1 l3
```

### Multiple selected anomalies

Windows PowerShell:

```powershell
py main.py --problem p01 --plan plans\p01.plan `
  --anomaly road_closure:2:l1:l3 `
  --anomaly new_delivery:8:package_new1:l2:l3
```

macOS/Linux:

```bash
python3 main.py --problem p01 --plan plans/p01.plan \
  --anomaly road_closure:2:l1:l3 \
  --anomaly new_delivery:8:package_new1:l2:l3
```

## Anomaly IDs and arguments

| ID | Name | Required `--anomaly-args` |
|---:|---|---|
| 1 | Road closure | `FROM TO` |
| 2 | Truck breakdown | `TRUCK` |
| 3 | New delivery | `PACKAGE ORIGIN DESTINATION` |
| 4 | Deadline change | `PACKAGE NEW_DEADLINE` |

Names can be used instead of numeric IDs:

```text
road_closure
truck_breakdown
new_delivery
deadline_change
```

The repeatable all-in-one `--anomaly` formats are:

```text
road_closure:STEP:FROM:TO
truck_breakdown:STEP:TRUCK
new_delivery:STEP:PACKAGE:ORIGIN:DESTINATION
deadline_change:STEP:PACKAGE:NEW_DEADLINE
```

## Generate the original plan outside the simulator

From the included Fast Downward directory on Windows:

```powershell
cd fast-downward-24.06.1
py fast-downward.py --plan-file ..\plans\p01.plan trucks\domain.pddl trucks\p01.pddl --search "eager_greedy([ff()])"
cd ..
```

The simulator then reads the generated file instead of calling Fast Downward
for the original plan:

```powershell
py main.py --problem p01 --plan plans\p01.plan
```

## Plan validation

Before changing the state, the simulator validates every supplied action. It
rejects malformed or impossible actions, including:

- driving from the wrong location or across a closed road;
- using the wrong time step;
- loading a package or truck from the wrong location;
- violating truck-area loading or unloading order;
- delivering a package from the wrong location; and
- ending before every goal or scheduled anomaly is reached.

## Tests

Windows:

```powershell
py -m unittest discover -s tests -v
```

macOS/Linux:

```bash
python3 -m unittest discover -s tests -v
```

## Main files

- `main.py` — command-line input for the problem, plan, anomaly ID, and step ID
- `simulator.py` — plan execution, anomaly handling, and replanning
- `planner.py` — plan parsing, platform detection, and Fast Downward execution
- `configure_fast_downward.py` — one-time macOS/Linux planner configuration
- `check_setup.py` — verifies required files and the platform-specific planner
- `state.py` — world state, action validation, and action execution
- `anomalies.py` — anomaly definitions and state-aware validation
- `case_library.py` — case-based anomaly responses
- `pddl_writer.py` — regenerated PDDL problems used for replanning
- `gui.py` — graphical interface using the same external inputs
- `plans/p01.plan` — supplied example original plan
- `tests/test_simulator.py` — automated tests
