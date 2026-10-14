# PDDL Anomaly Replanning Simulator

A Trucks-domain simulator that executes an externally generated plan, applies
a user-selected anomaly at a user-selected execution step, and uses Fast
Downward to create and execute a replacement plan. After each run, it can
generate an interactive HTML map of the execution and every replan.

## Workflow

1. Generate the original plan outside the simulator.
2. Supply that plan to the simulator with `--plan`.
3. Supply the anomaly ID and step ID.
4. The simulator displays and executes the original plan.
5. At the selected step, it applies the anomaly and asks Fast Downward for a
   new plan.
6. The simulator displays and executes the new plan.
7. An interactive run map is written to `run_maps/` and opened in the browser.

The simulator does not generate its own initial plan or randomly choose the
anomaly and step.

## Requirements

- Python 3.9 or newer
- No pip packages are required (`gui.py` uses Tkinter, which ships with most
  Python installations)
- Windows replanning support is included in this repository
- macOS/Linux requires a locally compiled Fast Downward checkout

## Project files

### Core simulator

| File | Purpose |
|---|---|
| `main.py` | Entry point. Reads the command-line options (problem, plan, anomaly ID, step ID), runs the simulation, and generates the run map. |
| `simulator.py` | Execution engine. Runs the plan step by step, triggers scheduled anomalies, calls the planner to replan, and executes the new plan. |
| `state.py` | World state (trucks, packages, roads, time). Validates each action before applying it. |
| `anomalies.py` | The four anomaly types (road closure, truck breakdown, new delivery, deadline change) and state-aware validation for each. |
| `case_library.py` | Case-based reasoning: the predefined response strategy for each anomaly type. |
| `pddl_parser.py` | Reads the PDDL domain and problem files into Python objects. |
| `pddl_writer.py` | Writes a new PDDL problem file from the current post-anomaly state so Fast Downward can replan from that point. |
| `planner.py` | Fast Downward integration: locates the correct installation for the operating system, runs it, and parses the resulting plan. |

### Interfaces

| File | Purpose |
|---|---|
| `gui.py` | Tkinter graphical interface for running simulations. |
| `visualizer.py` | Builds the interactive HTML run map (roads, truck, packages, replan markers). Uses only the standard library and can also rebuild a map from a saved log. |

### Setup and demo scripts

| File | Purpose |
|---|---|
| `check_setup.py` | Verifies that required files exist and that Fast Downward is ready on this computer. |
| `configure_fast_downward.py` | One-time macOS/Linux setup that saves the path to a locally compiled Fast Downward. |
| `run_windows_clean.bat` | Double-click demo: original plan only, no anomaly. |
| `run_windows_demo.bat` | Double-click demo: original plan, road closure, and replan. |
| `run_windows_visualizer.bat` | Same as the demo, plus the run map. |
| `run_mac_demo.sh` | macOS version of the road-closure demo. |

### Data

| File | Purpose |
|---|---|
| `plans/p01.plan` | Example original plan, generated ahead of time by Fast Downward. |
| `fast-downward-24.06.1/` | Bundled Fast Downward planner with the Windows binary, plus the Trucks domain (`trucks/domain.pddl`) and problems `p01`–`p30`. |

### Tests and documentation

| File | Purpose |
|---|---|
| `tests/test_simulator.py` | Automated tests. |
| `README.md` | This file. |
| `VISUALIZATION.md` | Details on the run map and how to read it. |
| `.gitignore` | Generated files Git should not track (caches, run maps, planner output, local config). |
| `.gitattributes` | Line-ending rules so the `.bat` and `.sh` scripts work on both Windows and macOS. |

## Windows quick start

The included `fast-downward-24.06.1` folder contains the Windows planner
binary, domain, and all 30 problem files. Open PowerShell or Command Prompt in
the project folder.

```powershell
# 1. Check the setup
py check_setup.py

# 2. Run the original plan without an anomaly
py main.py --problem p01 --plan plans/p01.plan

# 3. Run the full road-closure and replanning demonstration
py main.py --problem p01 --plan plans/p01.plan --anomaly-id 1 --step-id 2 --anomaly-args l1 l3
```

Or double-click:

- `run_windows_clean.bat`: original plan only
- `run_windows_demo.bat`: original plan, anomaly, and new plan
- `run_windows_visualizer.bat`: the demo plus the run map

## macOS quick start

The compiled Fast Downward search binary is operating-system specific, so the
bundled Windows binary will not run on macOS. Compile Fast Downward locally,
then point the simulator at it once:

```bash
# 1. Save the path to your Mac-compiled Fast Downward (one time)
python3 configure_fast_downward.py "/path/to/fast-downward.py"

# 2. Check the setup
python3 check_setup.py

# 3. Run the original plan without an anomaly
python3 main.py --problem p01 --plan plans/p01.plan

# 4. Run the full road-closure and replanning demonstration
python3 main.py --problem p01 --plan plans/p01.plan \
  --anomaly-id 1 --step-id 2 --anomaly-args l1 l3
```

The path may point to either `fast-downward.py` or its containing directory.
It is saved locally in `.fast-downward-path`, which Git ignores.

Shortcut after configuration:

```bash
bash run_mac_demo.sh
```

Show which planner is currently selected:

```bash
python3 configure_fast_downward.py --show
```

Override the saved path for a single run:

```bash
python3 main.py --problem p01 --plan plans/p01.plan \
  --anomaly-id 1 --step-id 2 --anomaly-args l1 l3 \
  --fast-downward "/another/path/to/fast-downward.py"
```

## Graphical interface

Windows:

```powershell
py gui.py
```

macOS/Linux:

```bash
python3 gui.py
```

## Command cheat sheet

On Windows use `py` and backslashes (`plans\p01.plan`). On macOS/Linux use
`python3` and forward slashes (`plans/p01.plan`).

### List available problems

```bash
python3 main.py --list
```

### Clean execution

```bash
python3 main.py --problem p01 --plan plans/p01.plan
```

### One selected anomaly

```bash
python3 main.py --problem p01 --plan plans/p01.plan \
  --anomaly-id 1 --step-id 2 --anomaly-args l1 l3
```

### Multiple selected anomalies

macOS/Linux:

```bash
python3 main.py --problem p01 --plan plans/p01.plan \
  --anomaly road_closure:2:l1:l3 \
  --anomaly new_delivery:8:package_new1:l2:l3
```

Windows PowerShell:

```powershell
py main.py --problem p01 --plan plans\p01.plan `
  --anomaly road_closure:2:l1:l3 `
  --anomaly new_delivery:8:package_new1:l2:l3
```

Only one anomaly may be scheduled per step.

### Other options

| Option | Effect |
|---|---|
| `--quiet`, `-q` | Suppress the state printout after each action. |
| `--search "..."` | Fast Downward search strategy for replanning (default `eager_greedy([ff()])`). |
| `--no-map` | Skip generating the run map. |
| `--map-file PATH` | Choose where the run map is written. |
| `--export-states DIR` | Save the state at each step to a directory (e.g. `state_history`). |
| `--json-output` | Emit JSON state for UI parsing. |
| `--fast-downward PATH` | One-run override of the Fast Downward location. |

## Anomaly IDs and arguments

| ID | Name | Required `--anomaly-args` |
|---:|---|---|
| 1 | Road closure | `FROM TO` |
| 2 | Truck breakdown | `TRUCK` |
| 3 | New delivery | `PACKAGE ORIGIN DESTINATION` |
| 4 | Deadline change | `PACKAGE NEW_DEADLINE` |

Names can be used instead of numeric IDs: `road_closure`, `truck_breakdown`,
`new_delivery`, `deadline_change`.

The repeatable all-in-one `--anomaly` formats are:

```text
road_closure:STEP:FROM:TO
truck_breakdown:STEP:TRUCK
new_delivery:STEP:PACKAGE:ORIGIN:DESTINATION
deadline_change:STEP:PACKAGE:NEW_DEADLINE
```

## Run map

Each run writes an interactive map to `run_maps/<problem>_map.html` and opens
it in the default browser. Circles are locations and lines are roads; closed
roads turn red and dashed. The truck is a blue rectangle (red if broken down).
Packages are yellow while waiting, blue on board, and green when delivered.
Replans are marked on the timeline, and the sidebar compares the old and new
plans. See `VISUALIZATION.md` for details.

Rebuild a map later from a saved log:

```bash
python3 main.py --problem p01 --plan plans/p01.plan \
  --anomaly-id 1 --step-id 2 --anomaly-args l1 l3 > run.txt
python3 visualizer.py run.txt fast-downward-24.06.1/trucks/p01.pddl
```

## Generating an original plan

Each problem needs its own plan file. From the project folder on Windows:

```powershell
py fast-downward-24.06.1\fast-downward.py --plan-file plans\p12.plan fast-downward-24.06.1\trucks\domain.pddl fast-downward-24.06.1\trucks\p12.pddl --search "eager_greedy([ff()])"
py main.py --problem p12 --plan plans\p12.plan --anomaly-id 1 --step-id 4 --anomaly-args l1 l2
```

On macOS/Linux, use the same command with `python3`, forward slashes, and the
path to your locally compiled `fast-downward.py`.

To use your own problem, save it in `fast-downward-24.06.1/trucks/` (for
example `mytest.pddl`) and run with `--problem mytest`.

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