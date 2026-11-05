# Merge guide: grid visualization + both plan modes

Rule followed: every file keeps its name and its job. Tomas's grid,
road-metric, GIF and browser work and the `--plan` branch's validation and
anomaly-ID work are both kept; code was added or adjusted only where the
workflow needed it. Tested end to end with Fast Downward 24.06 on Python 3.9
and 3.13.

Copy this folder over your repo on a new branch
(`git switch -c merge-grid-visualization`). The layout matches the repo.

## File by file

| File | Job (unchanged) | Based on | What was added or adjusted |
|---|---|---|---|
| `simulator.py` | Runs a plan step by step, anomalies, replanning, snapshots | `--plan` branch + Tomas's frames | Plan is optional: given = load, omitted = generate. Tomas's `state_history`, hourly drive frames, `get_run_snapshots`, random anomalies (`anomaly_chance`, `seed`, `max_anomalies`, off by default) all kept |
| `state.py` | World state + action rules | Tomas's | `validate_action` from the `--plan` branch put back, updated for multi-hour roads and `drive-instant` |
| `planner.py` | Finds/runs Fast Downward, reads plans | `--plan` branch | Also honors Tomas's `FAST_DOWNWARD_DIR` and `fd_config.json`; his `resolve_fast_downward_dir`, `_looks_like_fast_downward`, `search_fast_downward` kept; output in `.planner-output/` |
| `pddl_writer.py` | Writes PDDL for replans | Tomas's | Replan horizon scales with the slowest road; `problem_to_pddl()` added |
| `pddl_parser.py` | Reads PDDL | both (were nearly identical) | Reads `drive-instant`, ignores comments, several objects per line, `parse_problem_text()` |
| `anomalies.py` | Anomaly types, validation, random generator | Tomas's | Random road closures keep the map connected; a `--seed` now repeats exactly |
| `case_library.py` | Anomaly → response | unchanged | — |
| `main.py` | Command line | `--plan` branch | `--plan` optional, `--save-plan`; Tomas's `--anomaly-chance`, `--seed`, `--no-anomalies`, `--max-anomalies` back (chance defaults to 0) |
| `gui.py` | Tkinter app | `--plan` branch controls + Tomas's grid drawing | Load/Generate choice; Tomas's chance + seed controls; `width` crash fixed |
| `server.py` | Local web server for the browser app | Tomas's | Same port, endpoints and field names (`problems` list, `found`/`path`/`configured`, string anomalies, `anomaly_chance`, `seed`); adds plan source, plan files, uploads |
| `static/index.html`, `style.css`, `app.js` | Browser page | **Tomas's** | His layout, canvas drawing and controls kept. Added: Generate / Load plan file choice (+ save, upload), "Load .pddl file", an "Add an anomaly from a list" helper that writes lines into his Manual anomalies box, a Plan panel with progress, replan markers on the timeline. Fixed: the auto-run log showed `\n` instead of new lines; closed roads now show when jumping straight to a later frame |
| `visualizer.py` | Grid map → GIF / window (matplotlib) | **Tomas's, unchanged** | — (called exactly as before) |
| `run_map.py` | HTML run map after each `main.py` run | `--plan` branch's `visualizer.py` | **Renamed only**, so Tomas's file could keep `visualizer.py` |
| `README.md` | Project README | Tomas's | Updated sections: plan modes, Fast Downward lookup, random anomalies, structure |
| `VISUALIZATION.md` | Visualization notes | `--plan` branch | Covers all three viewers; `visualizer.py run.txt` → `run_map.py run.txt` |
| `check_setup.py` | Setup check | `--plan` branch | Also checks domain, upgraded problems, browser files |
| `tools/upgrade_problems.py` | Adds grid/road data to p01–p30 | **Tomas's** | Only refactored so the browser can reuse it (`upgrade_problem_text()`); output is byte-for-byte identical to his on all 30 problems |
| `tools/make_plans.py` | Regenerates `plans/` | new | — |
| `fast-downward-24.06.1/trucks/domain.pddl` | Extended Trucks domain | stand-in (Tomas's wasn't in the upload) | See note below |
| `run_windows_browser.bat`, `run_mac_browser.sh` | Double-click launchers | new, same pattern as the existing `.bat`/`.sh` | — |

Unchanged and not included (keep yours): `configure_fast_downward.py`,
`run_windows_demo.bat`, `run_windows_clean.bat`, `run_windows_visualizer.bat`,
`run_mac_demo.sh`, `make_plan.sh`, `plans/`, `tests/`.
Tomas's `oldSimulator.py` is a reference copy and isn't used.

## Domain file

Tomas's `domain.pddl` wasn't in what I received, so this folder has one that
matches the facts his upgrade tool writes (`road-distance`, `road-speed`,
`road-span`, `zero-time-road`, `loc-x`, `loc-y`, and `drive-instant` for 0t
roads). Tested against the real p01–p30 after his upgrade: the same problems
solve as before the upgrade (p01–p11, p14, p16 within 2 minutes each with
`lazy_greedy`; the larger ones are slow before and after). **If you have
Tomas's `domain.pddl`, use his instead.**

## One-time setup after copying

```
py tools/upgrade_problems.py     # Tomas's tool: adds grid + road data (skip if already done)
py tools/make_plans.py           # always: old plans don't match the new travel times
                                 # (large problems are slow; e.g. py tools/make_plans.py p01 p02 p03 to start)
py check_setup.py
```

(macOS/Linux: `python3` instead of `py`.)

Add to `.gitignore`:
```
.planner-output/
.fast-downward-path
fd_config.json
```

## Running it

```
py server.py                                        # browser app (or run_windows_browser.bat)
py main.py --problem p01                            # generate with Fast Downward
py main.py --problem p01 --save-plan                # ...and save to plans\p01.plan
py main.py --problem p01 --plan plans\p01.plan      # load a pre-made plan
py main.py --problem p01 --plan plans\p01.plan --anomaly-id 1 --step-id 2 --anomaly-args l1 l3
py main.py --problem p01 --anomaly-chance 0.3 --seed 42
py visualizer.py --problem p01 --no-anomalies --save run_p01.gif
py gui.py
```

## Not included yet

The question-form editor (build or edit a problem by answering questions,
then save it as `.pddl`) is the next phase. `pddl_writer.problem_to_pddl()`
and `/api/upload-problem` are the pieces it builds on.
