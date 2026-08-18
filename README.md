# PDDL Anomaly Replanning Simulator

A Python-based planning simulator that uses PDDL and Fast Downward to model truck deliveries and dynamically replan when unexpected events occur.

This project extends an existing truck-delivery simulator with deterministic, user-scheduled anomalies. Users can choose the anomaly type, the exact execution step when it occurs, and the affected road, truck, package, or deadline.

## Features

- Deterministic step-based anomaly scheduling
- Four supported anomaly types:
  - Road closure
  - Truck breakdown
  - New delivery
  - Deadline change
- State-aware anomaly validation
- Automatic PDDL regeneration
- Fast Downward replanning
- Multiple scheduled anomalies in one simulation
- Case-Based Reasoning integration
- Windows-compatible Fast Downward runtime included
- 30 included Trucks-domain PDDL problem instances

## How It Works

1. Fast Downward generates an initial plan for a truck-delivery PDDL problem.
2. The simulator executes the plan step by step.
3. A manually scheduled anomaly is triggered at the selected execution step.
4. The anomaly is validated against the current world state.
5. The simulator updates the world state and/or planning goals.
6. A modified PDDL problem is generated.
7. Fast Downward creates a replacement plan.
8. The simulator continues from the updated state instead of restarting from the beginning.

## Requirements

- Windows
- Python 3
- Git, if cloning the repository

A Windows-compatible Fast Downward runtime is included in the repository, so Fast Downward does not need to be built separately.

## Quick Start

Clone the repository:

```powershell
git clone https://github.com/matthew-demarco/pddl-anomaly-simulator.git
cd pddl-anomaly-simulator
```

Run a baseline simulation:

```powershell
py main.py --problem p01 --no-anomalies
```

List the available PDDL problems:

```powershell
py main.py --list
```

The repository includes 30 planning problems, from `p01` through `p30`.

## Manual Anomaly Syntax

Manual anomalies use the following format:

```text
--anomaly TYPE:STEP:DETAILS
```

The `--anomaly` option can be repeated to schedule multiple anomalies during one run.

The step number refers to the global simulator execution step.

## Road Closure

Format:

```text
road_closure:STEP:FROM:TO
```

Example:

```powershell
py main.py --problem p01 --no-anomalies --anomaly road_closure:3:l2:l3
```

At execution step 3, the road between `l2` and `l3` is closed.

The simulator updates the road network and asks Fast Downward to generate a new plan using the remaining connections.

## New Delivery

Format:

```text
new_delivery:STEP:PACKAGE:ORIGIN:DESTINATION
```

Example:

```powershell
py main.py --problem p01 --no-anomalies --anomaly new_delivery:8:package_new1:l2:l3
```

At step 8, a new package named `package_new1` appears at `l2` and must be delivered to `l3`.

The package is added to the current planning state and a new delivery goal is created before replanning.

## Deadline Change

Format:

```text
deadline_change:STEP:PACKAGE:NEW_DEADLINE
```

Example:

```powershell
py main.py --problem p01 --no-anomalies --anomaly deadline_change:3:package1:t2
```

At step 3, the deadline for `package1` changes to `t2`.

The modified deadline is included when the PDDL problem is regenerated for replanning.

## Truck Breakdown

Format:

```text
truck_breakdown:STEP:TRUCK
```

Example:

```powershell
py main.py --problem p01 --no-anomalies --anomaly truck_breakdown:3:truck1
```

The simulator checks that the requested truck is active before applying the breakdown.

A truck breakdown is rejected if only one active truck remains, because removing the final truck would make the delivery problem impossible.

Many of the included benchmark problems contain only one truck, so this command may demonstrate the validation behavior rather than a successful truck-breakdown replan.

## Multiple Anomalies

Multiple anomalies can be scheduled by repeating the `--anomaly` option.

Example:

```powershell
py main.py --problem p01 --no-anomalies `
  --anomaly road_closure:3:l2:l3 `
  --anomaly new_delivery:8:package_new1:l2:l3
```

This schedules:

- a road closure at step 3
- a new delivery at step 8

The simulator replans after each valid anomaly and continues from the current world state.

## Manual Anomaly Validation

Manual anomaly requests are validated before being applied.

Validation includes:

- verifying that a requested road exists
- verifying that a requested truck is active
- preventing the final active truck from breaking down
- preventing duplicate package names
- checking that package origins are valid locations
- checking that package destinations are valid locations
- requiring different origin and destination locations
- verifying that a deadline-change package exists
- preventing deadline changes for packages that have already been delivered
- verifying that a selected deadline is still a remaining time step

Invalid anomalies are rejected and reported in the console.

## Understanding `--no-anomalies`

The original simulator included randomly generated anomalies.

The `--no-anomalies` option disables the old random anomaly behavior.

Manually supplied `--anomaly` options can still be used at the same time.

Example:

```powershell
py main.py --problem p01 --no-anomalies --anomaly road_closure:3:l2:l3
```

Using `--no-anomalies` with a manual `--anomaly` makes demonstrations deterministic and repeatable.

## Project Structure

```text
pddl-anomaly-simulator/
│
├── main.py
├── anomalies.py
├── simulator.py
├── case_library.py
├── pddl_writer.py
├── planner.py
├── state.py
├── pddl_parser.py
├── gui.py
│
└── fast-downward-24.06.1/
    ├── fast-downward.py
    ├── builds/
    ├── driver/
    └── trucks/
        ├── domain.pddl
        ├── p01.pddl
        ├── p02.pddl
        └── ...
```

### Main Files

- `main.py` — command-line interface and manual anomaly parsing
- `anomalies.py` — anomaly definitions, scheduling model, and validation
- `simulator.py` — execution loop, anomaly triggering, and replanning
- `case_library.py` — Case-Based Reasoning responses for anomaly types
- `pddl_writer.py` — generates modified PDDL problems
- `planner.py` — Fast Downward integration
- `state.py` — world-state representation and action execution
- `pddl_parser.py` — PDDL parsing
- `gui.py` — graphical simulation interface
- `fast-downward-24.06.1/` — bundled Fast Downward runtime
- `fast-downward-24.06.1/trucks/` — Trucks PDDL domain and benchmark problems

## About the PDDL Problems

The files `p01.pddl` through `p30.pddl` are different truck-delivery planning scenarios.

Objects such as:

```text
package1
package2
truck1
l1
l2
t1
t2
```

are objects inside the simulated planning environment.

For example:

- `package1` represents a delivery package
- `truck1` represents a truck
- `l1` represents a location
- `t1` represents a time step

These are PDDL planning objects, not Python software packages.

## My Contribution

I implemented the deterministic/manual-anomaly scheduling feature in the existing simulator.

My primary changes were made in:

- `anomalies.py`
- `main.py`
- `simulator.py`

My work included:

- creating the `ScheduledAnomaly` data model
- adding command-line parsing for manual anomaly requests
- adding the repeatable `--anomaly` option
- allowing users to choose exact anomaly execution steps
- implementing manual road-closure scheduling
- implementing manual truck-breakdown scheduling
- implementing manual new-delivery scheduling
- implementing manual deadline-change scheduling
- adding state-aware anomaly validation
- integrating scheduled anomalies into the simulator execution loop
- connecting manual anomalies to the existing Case-Based Reasoning pipeline
- integrating anomaly-triggered PDDL regeneration and Fast Downward replanning
- preparing and verifying the bundled Windows Fast Downward runtime

## Collaboration

This project was developed collaboratively using Git branches and pull requests.

Ryan8536 contributed the deadline-preservation fix in `pddl_writer.py`.

That change ensures that a manually selected package deadline remains preserved when the PDDL problem is regenerated during replanning.

Ryan also contributed cleanup changes related to accidental Markdown code fences in Python source files.

## Technologies and Concepts

- Python
- PDDL
- Fast Downward
- Git
- GitHub
- `argparse`
- Python `dataclasses`
- Python type hints
- subprocess execution
- Case-Based Reasoning
- automated replanning
- state validation
- event scheduling
- command-line interface design
- Tkinter
- JSON
- graph-based road modeling

## Known Limitations

- Multiple anomalies can be scheduled in one run, but two anomalies assigned to the exact same execution step are not both processed.
- The graphical interface currently exposes the older random-anomaly controls and does not provide manual anomaly scheduling controls.
- Many included benchmark problems contain only one truck, which can prevent successful truck-breakdown replanning.
- Project-level automated regression tests have not yet been added.
- An anomaly scheduled after the simulation finishes will not occur.

## Example Demonstrations

### Deterministic Deadline Change

```powershell
py main.py --problem p01 --no-anomalies --anomaly deadline_change:3:package1:t2
```

### Road Closure

```powershell
py main.py --problem p01 --no-anomalies --anomaly road_closure:3:l2:l3
```

### Multiple Anomalies

```powershell
py main.py --problem p01 --no-anomalies `
  --anomaly road_closure:3:l2:l3 `
  --anomaly new_delivery:8:package_new1:l2:l3
```

During execution, useful output to look for includes:

```text
ANOMALY at step
REPLANNING
Plan found
Status: SUCCESS
```

## Third-Party Components

Fast Downward and the included Trucks-domain PDDL benchmark files are external components used by this project.

The bundled Fast Downward runtime is included to make the simulator easier to run on Windows.

These third-party files are not part of my original implementation contribution.

## Repository

https://github.com/matthew-demarco/pddl-anomaly-simulator