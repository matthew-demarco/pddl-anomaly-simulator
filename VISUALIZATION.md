# Visualization Addition (visualizationtest3)

This is the `New_anomaly_changes` branch of the PDDL Anomaly Replanning
Simulator (external `--plan` workflow, Windows Fast Downward included) plus an
automatic interactive run map generated after every simulation.

## Changes from the branch
| File | Status |
|---|---|
| `visualizer.py` | New. Builds the map (standard library only, never imports the simulator). |
| `main.py` | Modified. Optional visualizer import, `--no-map` and `--map-file` flags, stdout capture, UTF-8 output on Windows. |
| `run_windows_visualizer.bat` | New. Double-click demo: plan, road closure, replan, map. |
| everything else | Unchanged. |

## Windows usage (PowerShell, in this folder)
    py check_setup.py
    py main.py --problem p01 --plan plans\p01.plan
    py main.py --problem p01 --plan plans\p01.plan --anomaly-id 1 --step-id 2 --anomaly-args l1 l3

The map is written to `run_maps\<problem>_map.html` and opens in the default
browser. Flags: `--no-map` skips it, `--map-file PATH` chooses the location.

Rebuild a map from a saved log (UTF-8 or PowerShell UTF-16 both work):

    py main.py --problem p01 --plan plans\p01.plan --anomaly-id 1 --step-id 2 --anomaly-args l1 l3 > run.txt
    py visualizer.py run.txt fast-downward-24.06.1\trucks\p01.pddl

## Reading the map
Circles are locations, lines are roads. Closed roads turn red and dashed. The
blue rectangle is the truck (red if broken down). Packages are yellow waiting,
blue aboard, green delivered.

## Replan tracking
- A banner and an orange marker on the timeline slider show every replan; the
  "Jump to Replan #N" buttons go straight to it.
- The sidebar lists the active plan with finished actions ticked and the next
  action highlighted.
- At a replan, "What changed in the plan" compares the unexecuted part of the
  old plan with the new plan: kept, removed (red) and added (green) actions.

## How the pieces fit
The PDDL problem file, the plan file and the simulator run stay separate.
`visualizer.py` combines the problem file (static world) with the simulator
output (timeline); it can also be run later on a saved log.

## Testing different PDDL problems
`--problem pNN` loads `fast-downward-24.06.1\trucks\pNN.pddl` (plus `domain.pddl`).
Each problem needs its own plan file passed with `--plan`:

    py fast-downward-24.06.1\fast-downward.py --plan-file plans\p12.plan fast-downward-24.06.1\trucks\domain.pddl fast-downward-24.06.1\trucks\p12.pddl --search "lazy_greedy([ff()],preferred=[ff()])"
    py main.py --problem p12 --plan plans\p12.plan --anomaly-id 1 --step-id 4 --anomaly-args l1 l2

Your own problem file: save it in `fast-downward-24.06.1\trucks\` as `mytest.pddl`
and use `--problem mytest`.
