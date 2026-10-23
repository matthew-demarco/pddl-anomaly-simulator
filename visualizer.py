"""
Standalone run visualizer for the PDDL Anomaly Replanning Simulator.
===================================================================

Combines two data sources into a single interactive map:

  1. The PDDL problem file  -> the static world (locations, road network,
                               package start positions, delivery goals)
  2. The simulator console output -> the dynamic timeline (truck movement,
                               package pickups, anomalies, replans)

This module never imports simulator.py, anomalies.py or state.py, so it
cannot affect simulation behaviour. It only reads text.

Public entry point:
    render(log_text, problem_path, out_path=None, open_browser=True)
"""

from __future__ import annotations

import json
import re
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------------------
# Part 1 — read the PDDL problem file (the static world)
# ---------------------------------------------------------------------------


def _strip_comments(text: str) -> str:
    return "\n".join(line.split(";")[0] for line in text.splitlines())


def parse_problem(problem_path) -> dict:
    """Extract locations, roads, packages, trucks and goals from a .pddl file."""
    text = _strip_comments(Path(problem_path).read_text(encoding="utf-8", errors="replace"))

    # The :objects block is declared one "name(s) - type" group per line.
    objects_block = ""
    if ":objects" in text.lower():
        start = text.lower().index(":objects") + len(":objects")
        depth = 1
        for i, ch in enumerate(text[start:], start=start):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    objects_block = text[start:i]
                    break
        else:
            objects_block = text[start:]

    by_type: dict[str, list[str]] = {}
    for line in objects_block.splitlines():
        line = line.strip().rstrip(")").strip()
        if "-" not in line:
            continue
        names_part, _, type_part = line.rpartition("-")
        type_name = type_part.strip().lower()
        if not type_name:
            continue
        bucket = by_type.setdefault(type_name, [])
        for token in names_part.split():
            if token and token not in bucket:
                bucket.append(token)

    def typed(type_name: str):
        return list(by_type.get(type_name.lower(), []))

    locations = typed("location")
    packages = typed("package")
    trucks = typed("truck")
    times = typed("time")

    roads = []
    seen = set()
    for a, b in re.findall(r"\(\s*connected\s+(\S+?)\s+(\S+?)\s*\)", text, re.IGNORECASE):
        key = tuple(sorted((a, b)))
        if key not in seen:
            seen.add(key)
            roads.append({"a": key[0], "b": key[1]})

    start_positions = {}
    for obj, loc in re.findall(r"\(\s*at\s+(\S+?)\s+(\S+?)\s*\)", text, re.IGNORECASE):
        start_positions[obj] = loc

    goals = {}
    goal_block = text.split(":goal", 1)[-1] if ":goal" in text else ""
    for pkg, loc, deadline in re.findall(
        r"\(\s*delivered\s+(\S+?)\s+(\S+?)\s+(\S+?)\s*\)", goal_block, re.IGNORECASE
    ):
        goals[pkg] = {"destination": loc, "deadline": deadline}
    for pkg, loc in re.findall(
        r"\(\s*at-destination\s+(\S+?)\s+(\S+?)\s*\)", goal_block, re.IGNORECASE
    ):
        goals.setdefault(pkg, {"destination": loc, "deadline": None})

    name_match = re.search(r"\(define\s*\(problem\s+(\S+?)\s*\)", text, re.IGNORECASE)

    return {
        "name": name_match.group(1) if name_match else Path(problem_path).stem,
        "file": str(problem_path),
        "locations": _natural_sort(locations),
        "roads": roads,
        "packages": packages,
        "trucks": trucks,
        "times": _natural_sort(times),
        "start_positions": start_positions,
        "goals": goals,
    }


def _natural_sort(items):
    def key(value):
        parts = re.split(r"(\d+)", value)
        return [int(p) if p.isdigit() else p for p in parts]

    return sorted(items, key=key)


# ---------------------------------------------------------------------------
# Part 2 — read the simulator console output (the dynamic timeline)
# ---------------------------------------------------------------------------

RE_STEP = re.compile(r"^\s*Step\s+(\d+):\s*(?:\S+\s+)?\((.+)\)\s*$")
RE_TIME = re.compile(r"^\s*Time:\s*(\S+)\s*$")
RE_TRUCK = re.compile(r"^\s*(\S+)\s+@\s+(\S+?)\s*(?:carrying\s+\[([^\]]*)\])?\s*$")
RE_GROUND = re.compile(r"^\s*Packages on ground:\s*(.+?)\s*$")
RE_DELIVERED = re.compile(r"^\s*Delivered:\s*(.+?)\s*$")
RE_ANOMALY = re.compile(r"ANOMALY at step\s+(\d+)")
RE_REMOVED = re.compile(r"Removed connection:\s*(\S+)\s*\S\s*(\S+)")
RE_NEW_PKG = re.compile(r"Added\s+(\S+)\s+at\s+(\S+)")
RE_NEW_PKG_DEST = re.compile(
    r"package\s+(\S+)\s+appeared at\s+(\S+)\s+and must be delivered to\s+(\S+?)\.?$"
)
RE_DEADLINE = re.compile(r"deadline for\s+(\S+)\s+(?:has\s+)?chang\w*\s+to\s+(\S+?)\.?$", re.I)
RE_BREAKDOWN = re.compile(r"(\S+)\s+has broken down", re.I)
RE_NEW_PLAN = re.compile(r"New plan:\s*(\d+)\s*actions")
RE_INITIAL_PLAN = re.compile(r"Initial plan:\s*(\d+)\s*actions")
RE_REPLAN = re.compile(r"REPLANNING \(attempt #(\d+)\)")
RE_STATUS = re.compile(r"^\s*Status:\s*(?:\S+\s+)?(\S+)\s*$")
RE_EXECUTED = re.compile(r"Actions executed:\s*(\d+)")
RE_REPLANS = re.compile(r"Replans triggered:\s*(\d+)")
RE_PLAN_HEADER = re.compile(r"^\s*Plan\s*\((\d+)\s*actions?\):\s*$")
RE_PLAN_LINE = re.compile(r"^\s*(\d+)\.\s*\((.+)\)\s*$")
RE_PROBLEM = re.compile(r"^\s*Problem:\s*(\S+)")

# Lines that are decoration, not data
BOX_CHARS = "\u2554\u255a\u2551\u2550\u2500\u2501\u2014="


def _clean_box(line: str) -> str:
    return line.strip().lstrip("\u2551").strip().strip(BOX_CHARS).strip()


def _split_list(value: str, sep: str):
    if not value or value.lower() in {"none", "(none)", "-"}:
        return []
    return [item.strip() for item in value.split(sep) if item.strip()]


def _close_plan(plans, actions, frames):
    """Store a finished plan block. The first is the initial plan; every later
    one belongs to the most recent replan (anomaly) frame."""
    if not plans:
        plans.append({"id": 0, "label": "Initial plan", "actions": list(actions),
                      "replan": None})
        return
    trigger = None
    for frame in reversed(frames):
        if frame["kind"] == "anomaly":
            trigger = frame
            break
    plan_id = len(plans)
    plans.append({"id": plan_id, "label": f"Replan #{plan_id}",
                  "actions": list(actions), "replan": None})
    if trigger is not None:
        trigger["new_plan_id"] = plan_id


def _assign_plan_positions(frames, plans):
    """Tag each frame with the plan it is executing and how far along it is,
    and attach a before/after diff to every replan frame."""
    import difflib

    active, done = 0, 0
    for frame in frames:
        if frame["kind"] == "anomaly":
            new_id = frame.get("new_plan_id")
            if new_id is not None and plans:
                old_remaining = plans[active]["actions"][done:] if active < len(plans) else []
                new_actions = plans[new_id]["actions"]
                matcher = difflib.SequenceMatcher(a=old_remaining, b=new_actions, autojunk=False)
                ops, kept, removed, added = [], 0, 0, 0
                for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                    if tag == "equal":
                        kept += i2 - i1
                        ops += [{"op": "keep", "text": t} for t in old_remaining[i1:i2]]
                    else:
                        removed += i2 - i1
                        added += j2 - j1
                        ops += [{"op": "remove", "text": t} for t in old_remaining[i1:i2]]
                        ops += [{"op": "add", "text": t} for t in new_actions[j1:j2]]
                frame["replan"] = {
                    "from_plan": active, "to_plan": new_id,
                    "executed_before": done,
                    "old_remaining": len(old_remaining), "new_total": len(new_actions),
                    "kept": kept, "removed": removed, "added": added, "diff": ops,
                }
                active, done = new_id, 0
            frame["plan_id"], frame["plan_pos"] = active, done
        elif frame["kind"] == "step":
            done += 1
            frame["plan_id"], frame["plan_pos"] = active, done
        else:
            frame["plan_id"], frame["plan_pos"] = active, done


def parse_log(log_text: str) -> dict:
    """Turn simulator stdout into an ordered list of timeline frames."""
    lines = log_text.splitlines()

    frames = []
    closed_roads = []          # accumulates across the whole run
    extra_packages = {}        # packages created mid-run by new_delivery
    deadline_overrides = {}
    broken_trucks = []
    summary = {}
    pending_anomaly = None
    plans = []                 # every plan printed: initial + one per replan
    plan_buffer = None         # actions of the plan block being read

    current = None

    def flush():
        nonlocal current
        if current is not None:
            frames.append(current)
            current = None

    def new_frame(kind, step, action=None, carry_from=None):
        frame = {
            "kind": kind,
            "step": step,
            "action": action,
            "time": None,
            "trucks": {},
            "ground": {},
            "delivered": [],
            "anomaly": None,
            "note": None,
            "closed": list(closed_roads),
            "broken": list(broken_trucks),
            "packages_added": dict(extra_packages),
            "deadlines": dict(deadline_overrides),
        }
        if carry_from:
            frame["time"] = carry_from.get("time")
            frame["trucks"] = json.loads(json.dumps(carry_from.get("trucks", {})))
            frame["ground"] = dict(carry_from.get("ground", {}))
            frame["delivered"] = list(carry_from.get("delivered", []))
        return frame

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        # --- plan blocks ("Plan (N actions):" + numbered lines) ----------
        if plan_buffer is not None:
            match = RE_PLAN_LINE.match(line)
            if match:
                plan_buffer.append(match.group(2).strip())
                continue
            _close_plan(plans, plan_buffer, frames)
            plan_buffer = None
        if RE_PLAN_HEADER.match(line):
            flush()
            plan_buffer = []
            continue

        match = RE_PROBLEM.match(line)
        if match and "problem" not in summary:
            summary["problem"] = match.group(1)

        match = RE_INITIAL_PLAN.search(line)
        if match:
            summary["initial_plan_actions"] = int(match.group(1))

        # --- anomaly banner ---------------------------------------------
        match = RE_ANOMALY.search(line)
        if match:
            pending_anomaly = {"step": int(match.group(1)), "text": ""}
            continue

        if pending_anomaly is not None and not pending_anomaly["text"]:
            text = _clean_box(line)
            if text and not text.startswith("Case matched"):
                pending_anomaly["text"] = text
                continue

        # --- anomaly side effects ---------------------------------------
        match = RE_REMOVED.search(line)
        if match:
            key = tuple(sorted((match.group(1), match.group(2))))
            if list(key) not in [list(c) for c in closed_roads]:
                closed_roads.append(list(key))
            continue

        match = RE_NEW_PKG.search(line)
        if match:
            pkg, loc = match.group(1), match.group(2)
            extra_packages.setdefault(pkg, {"origin": loc, "destination": None})
            if pending_anomaly and pending_anomaly.get("text"):
                dest = RE_NEW_PKG_DEST.search(pending_anomaly["text"])
                if dest and dest.group(1) == pkg:
                    extra_packages[pkg]["destination"] = dest.group(3)
            continue

        match = RE_DEADLINE.search(line)
        if match:
            deadline_overrides[match.group(1)] = match.group(2)
            continue

        match = RE_BREAKDOWN.search(line)
        if match and match.group(1) not in broken_trucks:
            broken_trucks.append(match.group(1))
            continue

        match = RE_REPLAN.search(line)
        if match:
            # Emit a dedicated frame for the anomaly + replan moment
            flush()
            previous = frames[-1] if frames else None
            frame = new_frame("anomaly", pending_anomaly["step"] if pending_anomaly else None,
                              carry_from=previous)
            frame["anomaly"] = pending_anomaly or {"step": None, "text": "Anomaly"}
            frame["closed"] = list(closed_roads)
            frame["broken"] = list(broken_trucks)
            frame["packages_added"] = dict(extra_packages)
            frame["deadlines"] = dict(deadline_overrides)
            frame["note"] = f"Replanning (attempt #{match.group(1)})"
            # new packages appear on the ground immediately
            for pkg, info in extra_packages.items():
                frame["ground"][pkg] = info["origin"]
            frames.append(frame)
            pending_anomaly = None
            continue

        match = RE_NEW_PLAN.search(line)
        if match and frames:
            frames[-1]["new_plan_actions"] = int(match.group(1))
            continue

        # --- state blocks -----------------------------------------------
        if stripped.rstrip(":").lower() == "initial state":
            flush()
            current = new_frame("initial", 0)
            current["action"] = "Initial state"
            continue

        if stripped.rstrip(":").lower() == "final state":
            flush()
            current = new_frame("final", None)
            current["action"] = "Final state"
            continue

        match = RE_STEP.match(line)
        if match:
            flush()
            current = new_frame("step", int(match.group(1)), action=match.group(2))
            continue

        if current is None:
            match = RE_STATUS.match(line)
            if match:
                summary["status"] = match.group(1)
            match = RE_EXECUTED.search(line)
            if match:
                summary["actions_executed"] = int(match.group(1))
            match = RE_REPLANS.search(line)
            if match:
                summary["replans"] = int(match.group(1))
            continue

        match = RE_TIME.match(line)
        if match:
            current["time"] = match.group(1)
            continue

        match = RE_GROUND.match(line)
        if match:
            current["ground"] = {}
            for item in _split_list(match.group(1), ","):
                if "@" in item:
                    pkg, loc = item.split("@", 1)
                    current["ground"][pkg.strip()] = loc.strip()
            continue

        match = RE_DELIVERED.match(line)
        if match:
            current["delivered"] = []
            for item in _split_list(match.group(1), ","):
                parts = re.split(r"\u2192|->", item)
                if len(parts) == 2:
                    current["delivered"].append(
                        {"package": parts[0].strip(), "location": parts[1].strip()}
                    )
            continue

        match = RE_TRUCK.match(line)
        if match and "@" in line:
            name, loc, carrying = match.group(1), match.group(2), match.group(3)
            current["trucks"][name] = {
                "location": loc,
                "carrying": _split_list(carrying or "", ","),
            }
            continue

        match = RE_STATUS.match(line)
        if match:
            summary["status"] = match.group(1)
            continue
        match = RE_EXECUTED.search(line)
        if match:
            summary["actions_executed"] = int(match.group(1))
            continue
        match = RE_REPLANS.search(line)
        if match:
            summary["replans"] = int(match.group(1))
            continue

    if plan_buffer is not None:
        _close_plan(plans, plan_buffer, frames)
        plan_buffer = None
    flush()
    _assign_plan_positions(frames, plans)

    # Packages on the ground are only printed when non-empty, and a frame that
    # omits the line means "unchanged except for what the action did". Carry
    # forward is already handled by the simulator's own printing, so we only
    # backfill frames that never received any truck info at all.
    last_trucks = {}
    for frame in frames:
        if frame["trucks"]:
            last_trucks = frame["trucks"]
        else:
            frame["trucks"] = json.loads(json.dumps(last_trucks))

    return {"frames": frames, "summary": summary, "plans": plans,
            "closed_roads": closed_roads,
            "extra_packages": extra_packages, "deadline_overrides": deadline_overrides}


# ---------------------------------------------------------------------------
# Part 3 — combine and render
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #0f1420; --panel: #171e2e; --line: #263149; --edge: #4a5a7a;
    --text: #e8edf7; --muted: #93a1bd; --accent: #4da3ff; --good: #35c98b;
    --bad: #ff5f6d; --warn: #ffb84d; --pkg: #ffd166;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: #0f1420; color: #e8edf7;
         font-family: "Segoe UI", system-ui, sans-serif; }
  header { padding: 14px 20px; border-bottom: 1px solid #263149; }
  h1 { margin: 0; font-size: 17px; font-weight: 600; }
  header .sub { color: #93a1bd; font-size: 12px; margin-top: 4px; }
  .wrap { display: grid; grid-template-columns: 1fr 320px; gap: 0; height: calc(100vh - 62px); }
  .stage { position: relative; }
  svg { width: 100%; height: 100%; display: block; }
  .side { border-left: 1px solid #263149; background: #171e2e; padding: 16px;
          overflow-y: auto; font-size: 13px; }
  .side h2 { font-size: 11px; text-transform: uppercase; letter-spacing: .08em;
             color: #93a1bd; margin: 18px 0 8px; font-weight: 600; }
  .side h2:first-child { margin-top: 0; }
  .action { font-family: Consolas, monospace; font-size: 13px; color: #4da3ff;
            background: #101725; padding: 8px 10px; border-radius: 6px;
            word-break: break-word; }
  .row { display: flex; justify-content: space-between; padding: 3px 0;
         border-bottom: 1px solid #212b41; }
  .row span:last-child { color: #93a1bd; font-family: Consolas, monospace; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 20px;
           font-size: 11px; font-weight: 600; }
  .anomaly-box { background: rgba(255,95,109,.12); border-left: 3px solid #ff5f6d;
                 padding: 9px 11px; border-radius: 4px; color: #ffc9cd; line-height: 1.45; }
  .note { color: #ffb84d; font-size: 12px; margin-top: 6px; }
  .chip { display: inline-block; background: #223049; color: #cfdaf0;
          border-radius: 4px; padding: 2px 7px; margin: 2px 3px 2px 0;
          font-family: Consolas, monospace; font-size: 12px; }
  .chip.done { background: rgba(53,201,139,.18); color: #7ff0bd; }
  .controls { position: absolute; left: 0; right: 0; bottom: 0; padding: 12px 18px;
              background: rgba(15,20,32,.94); border-top: 1px solid #263149;
              display: flex; align-items: center; gap: 12px; }
  button { background: #223049; color: #e8edf7; border: 1px solid #33425f;
           border-radius: 6px; padding: 7px 13px; cursor: pointer; font-size: 13px; }
  button:hover { background: #2b3b58; }
  input[type=range] { flex: 1; accent-color: #4da3ff; }
  .stepLabel { font-family: Consolas, monospace; color: #93a1bd; min-width: 108px;
               font-size: 12px; text-align: right; }
  .legend { position: absolute; top: 14px; left: 18px; font-size: 11px; color: #93a1bd;
            background: rgba(15,20,32,.8); padding: 8px 11px; border-radius: 6px; }
  .legend i { display: inline-block; width: 9px; height: 9px; border-radius: 50%;
              margin-right: 5px; vertical-align: middle; }
  .tl { position: relative; flex: 1; display: flex; align-items: center; }
  .tl input[type=range] { width: 100%; }
  .tick { position: absolute; top: -9px; width: 0; height: 0; transform: translateX(-50%);
          border-left: 6px solid transparent; border-right: 6px solid transparent;
          border-top: 9px solid #ffb84d; cursor: pointer; }
  .planbadge { position: absolute; top: 14px; right: 18px; background: rgba(15,20,32,.85);
               border: 1px solid #33425f; border-radius: 6px; padding: 7px 11px;
               font-size: 12px; color: #cfdaf0; }
  .planbadge b { color: #ffb84d; }
  .banner { position: absolute; top: 56px; left: 50%; transform: translateX(-50%);
            background: rgba(255,184,77,.16); border: 1px solid #ffb84d; color: #ffe2b0;
            padding: 9px 18px; border-radius: 8px; font-size: 14px; font-weight: 600;
            display: none; text-align: center; max-width: 70%; }
  .plan { position: relative; font-family: Consolas, monospace; font-size: 12px; max-height: 230px;
          overflow-y: auto; background: #101725; border-radius: 6px; padding: 4px 0; }
  .pl { padding: 2px 10px; color: #cfdaf0; white-space: nowrap; }
  .pl.done { color: #5f6e8c; }
  .pl.done::before { content: "\2713 "; color: #35c98b; }
  .pl.now { background: rgba(77,163,255,.2); color: #fff; border-left: 3px solid #4da3ff; }
  .pl.add { background: rgba(53,201,139,.14); color: #8ff0c2; }
  .pl.add::before { content: "+ "; }
  .pl.remove { background: rgba(255,95,109,.14); color: #ffb3ba; text-decoration: line-through; }
  .pl.remove::before { content: "- "; }
  .pl.keep { color: #7d8aa6; }
  .pl.keep::before { content: "  "; white-space: pre; }
  .stats { display: flex; gap: 8px; margin-bottom: 8px; font-size: 12px; }
  .stats span { padding: 2px 8px; border-radius: 12px; font-weight: 600; }
  .s-keep { background: #223049; color: #cfdaf0; }
  .s-add { background: rgba(53,201,139,.18); color: #7ff0bd; }
  .s-rem { background: rgba(255,95,109,.18); color: #ffb3ba; }
  .jump { margin: 2px 4px 2px 0; padding: 4px 9px; font-size: 12px; }
  g.truck { transition: transform .45s cubic-bezier(.4,0,.2,1); }
  circle.node { transition: stroke .3s, fill .3s; }
  line.road { transition: stroke .3s, opacity .3s; }
  g.pkg { transition: transform .45s cubic-bezier(.4,0,.2,1); }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <div class="sub">__SUBTITLE__</div>
</header>
<div class="wrap">
  <div class="stage">
    <div class="legend">
      <div><i style="background:#4da3ff"></i>truck</div>
      <div><i style="background:#ffd166"></i>package waiting</div>
      <div><i style="background:#35c98b"></i>delivered</div>
      <div><i style="background:#ff5f6d"></i>closed road</div>
    </div>
    <div class="planbadge" id="planBadge"></div>
    <div class="banner" id="banner"></div>
    <svg id="map" viewBox="0 0 900 620" preserveAspectRatio="xMidYMid meet"></svg>
    <div class="controls">
      <button id="prev">Prev</button>
      <button id="play">Play</button>
      <button id="next">Next</button>
      <div class="tl"><div id="ticks"></div><input type="range" id="slider" min="0" value="0"></div>
      <div class="stepLabel" id="stepLabel"></div>
    </div>
  </div>
  <div class="side">
    <h2>Current action</h2>
    <div class="action" id="action">-</div>
    <div id="anomalyWrap"></div>
    <div id="replanWrap"></div>
    <h2 id="planTitle">Plan</h2>
    <div class="plan" id="planList"></div>
    <div id="jumps" style="margin-top:8px"></div>
    <h2>Clock</h2>
    <div class="row"><span>Sim time</span><span id="time">-</span></div>
    <div class="row"><span>Frame</span><span id="frame">-</span></div>
    <h2>Trucks</h2>
    <div id="trucks"></div>
    <h2>Packages waiting</h2>
    <div id="ground"></div>
    <h2>Delivered</h2>
    <div id="delivered"></div>
    <h2>Goals</h2>
    <div id="goals"></div>
    <h2>Run summary</h2>
    <div id="summary"></div>
  </div>
</div>
<script>
const DATA = __DATA__;
const world = DATA.world, frames = DATA.timeline.frames, summary = DATA.timeline.summary;
const plans = DATA.timeline.plans || [];

const W = 900, H = 620, CX = W/2, CY = H/2 - 20;
const R = Math.min(W, H) * 0.32;
const pos = {};
const locs = world.locations;
locs.forEach((loc, i) => {
  if (locs.length === 1) { pos[loc] = {x: CX, y: CY}; return; }
  const angle = -Math.PI/2 + (2*Math.PI*i)/locs.length;
  pos[loc] = { x: CX + R*Math.cos(angle), y: CY + R*Math.sin(angle) };
});

const svg = document.getElementById('map');
const NS = 'http://www.w3.org/2000/svg';
function el(tag, attrs) {
  const node = document.createElementNS(NS, tag);
  for (const k in attrs) node.setAttribute(k, attrs[k]);
  return node;
}
const roadLayer = el('g', {}), nodeLayer = el('g', {}),
      pkgLayer = el('g', {}), truckLayer = el('g', {});
svg.append(roadLayer, nodeLayer, pkgLayer, truckLayer);

const roadEls = {};
world.roads.forEach(r => {
  const a = pos[r.a], b = pos[r.b];
  if (!a || !b) return;
  const line = el('line', {x1:a.x, y1:a.y, x2:b.x, y2:b.y, class:'road',
                           stroke:'#4a5a7a', 'stroke-width':3});
  roadEls[[r.a,r.b].sort().join('|')] = line;
  roadLayer.appendChild(line);
});

const nodeEls = {};
locs.forEach(loc => {
  const p = pos[loc];
  const c = el('circle', {cx:p.x, cy:p.y, r:26, class:'node',
                          fill:'#1d2740', stroke:'#4a5a7a', 'stroke-width':2.5});
  const t = el('text', {x:p.x, y:p.y+5, 'text-anchor':'middle',
                        fill:'#e8edf7', 'font-size':14, 'font-weight':700,
                        'font-family':'"Segoe UI", system-ui, sans-serif',
                        'letter-spacing':'0.5'});
  t.textContent = loc.toUpperCase();
  nodeEls[loc] = c;
  nodeLayer.append(c, t);
});

// package markers, one per package that ever exists
const allPkgs = new Set(world.packages);
frames.forEach(f => {
  Object.keys(f.ground || {}).forEach(p => allPkgs.add(p));
  (f.delivered || []).forEach(d => allPkgs.add(d.package));
  Object.values(f.trucks || {}).forEach(t => (t.carrying||[]).forEach(p => allPkgs.add(p)));
});
const pkgList = [...allPkgs];
const pkgEls = {};
pkgList.forEach(p => {
  const g = el('g', {class:'pkg'});
  const box = el('rect', {x:-7, y:-7, width:14, height:14, rx:3,
                          fill:'#ffd166', stroke:'#0f1420', 'stroke-width':1.5});
  const label = el('text', {x:0, y:-11, 'text-anchor':'middle', fill:'#93a1bd',
                            'font-size':9, 'font-family':'Consolas, monospace'});
  label.textContent = p.replace('package','p');
  g.append(box, label);
  pkgEls[p] = {g, box, label};
  pkgLayer.appendChild(g);
});

const truckEls = {};
const truckNames = new Set(world.trucks);
frames.forEach(f => Object.keys(f.trucks||{}).forEach(t => truckNames.add(t)));
[...truckNames].forEach(name => {
  const g = el('g', {class:'truck'});
  const body = el('rect', {x:-22, y:-13, width:44, height:26, rx:6,
                           fill:'#4da3ff', stroke:'#0f1420', 'stroke-width':2});
  const label = el('text', {x:0, y:5, 'text-anchor':'middle', fill:'#08111f',
                            'font-size':11, 'font-weight':700,
                            'font-family':'Consolas, monospace'});
  label.textContent = name.replace('truck','T');
  g.append(body, label);
  truckEls[name] = {g, body};
  truckLayer.appendChild(g);
});

// Few packages: a labelled ring around the node. Many (p19-p30): a compact
// unlabelled grid offset from the node, so nothing overlaps the road network.
const RING_MAX = 6;
function slotFor(i, n, cx, cy) {
  if (n <= RING_MAX) {
    const angle = -Math.PI/2 + (2*Math.PI*i)/Math.max(n, 3);
    return {dx: 54*Math.cos(angle), dy: 54*Math.sin(angle), label: true};
  }
  const cols = Math.min(5, Math.ceil(Math.sqrt(n)));
  const rows = Math.ceil(n / cols);
  const gap = 17;
  const gw = (cols - 1) * gap, gh = (rows - 1) * gap;
  // push the grid away from the diagram centre so it clears the edges
  const ox = cx < CX ? -(gw + 52) : (gw ? 52 : 52);
  const oy = cy < CY ? -(gh + 40) : 40;
  const col = i % cols, row = Math.floor(i / cols);
  return {dx: ox + col*gap - (cx < CX ? 0 : 0), dy: oy + row*gap, label: false};
}

function render(idx) {
  const f = frames[idx];
  if (!f) return;

  const closed = new Set((f.closed||[]).map(c => [...c].sort().join('|')));
  for (const key in roadEls) {
    const isClosed = closed.has(key);
    roadEls[key].setAttribute('stroke', isClosed ? '#ff5f6d' : '#4a5a7a');
    roadEls[key].setAttribute('stroke-dasharray', isClosed ? '7 6' : 'none');
    roadEls[key].setAttribute('opacity', isClosed ? 0.85 : 1);
  }

  const delivered = new Set((f.delivered||[]).map(d => d.package));
  const deliveredAt = {};
  (f.delivered||[]).forEach(d => { deliveredAt[d.package] = d.location; });

  const carriedBy = {};
  Object.entries(f.trucks||{}).forEach(([name, t]) =>
    (t.carrying||[]).forEach(p => { carriedBy[p] = name; }));

  const byLoc = {};
  pkgList.forEach(p => {
    let loc = null;
    if (delivered.has(p)) loc = deliveredAt[p];
    else if (carriedBy[p]) loc = (f.trucks[carriedBy[p]]||{}).location;
    else if ((f.ground||{})[p]) loc = f.ground[p];
    if (loc) { (byLoc[loc] = byLoc[loc] || []).push(p); }
    pkgEls[p].g.setAttribute('opacity', loc ? 1 : 0);
  });

  Object.entries(byLoc).forEach(([loc, list]) => {
    const p = pos[loc]; if (!p) return;
    list.forEach((pkg, i) => {
      const slot = slotFor(i, list.length, p.x, p.y);
      pkgEls[pkg].g.setAttribute('transform',
        `translate(${p.x + slot.dx}, ${p.y + slot.dy})`);
      const isDone = delivered.has(pkg);
      const isCarried = !!carriedBy[pkg];
      pkgEls[pkg].box.setAttribute('fill',
        isDone ? '#35c98b' : (isCarried ? '#4da3ff' : '#ffd166'));
      pkgEls[pkg].label.setAttribute('opacity', slot.label ? 1 : 0);
    });
  });

  const broken = new Set(f.broken||[]);
  Object.entries(truckEls).forEach(([name, refs]) => {
    const t = (f.trucks||{})[name];
    if (!t || !pos[t.location]) { refs.g.setAttribute('opacity', 0); return; }
    refs.g.setAttribute('opacity', 1);
    const p = pos[t.location];
    refs.g.setAttribute('transform', `translate(${p.x}, ${p.y - 42})`);
    refs.body.setAttribute('fill', broken.has(name) ? '#ff5f6d' : '#4da3ff');
  });

  locs.forEach(loc => {
    const here = Object.values(f.trucks||{}).some(t => t.location === loc);
    nodeEls[loc].setAttribute('stroke', here ? '#4da3ff' : '#4a5a7a');
    nodeEls[loc].setAttribute('stroke-width', here ? 4 : 2.5);
  });

  document.getElementById('action').textContent =
    f.action ? (f.kind === 'step' ? '(' + f.action + ')' : f.action)
             : (f.kind === 'anomaly' ? 'anomaly interrupt' : '-');
  document.getElementById('time').textContent = f.time || '-';
  document.getElementById('frame').textContent = (idx+1) + ' / ' + frames.length;

  const aw = document.getElementById('anomalyWrap');
  aw.innerHTML = '';
  if (f.anomaly) {
    const h = document.createElement('h2'); h.textContent = 'Anomaly';
    const box = document.createElement('div');
    box.className = 'anomaly-box';
    box.textContent = (f.anomaly.step ? 'Step ' + f.anomaly.step + ': ' : '') + f.anomaly.text;
    aw.append(h, box);
    if (f.note) {
      const n = document.createElement('div'); n.className = 'note';
      n.textContent = f.note + (f.new_plan_actions ? ' -> new plan, ' + f.new_plan_actions + ' actions' : '');
      aw.appendChild(n);
    }
  }


  // ---- plan panel: active plan with progress ---------------------------
  const plan = plans[f.plan_id || 0];
  const planDiv = document.getElementById('planList');
  planDiv.innerHTML = '';
  const rp = f.replan;
  document.getElementById('planTitle').textContent = plan
    ? plan.label + ' (' + plan.actions.length + ' actions)' : 'Plan';
  document.getElementById('planBadge').innerHTML = plan
    ? 'Active plan: <b>' + plan.label + '</b>' + (f.plan_pos != null ? ' &middot; ' + f.plan_pos + '/' + plan.actions.length + ' done' : '')
    : '';
  if (plan) {
    plan.actions.forEach((a, i) => {
      const d = document.createElement('div');
      d.className = 'pl' + (i < f.plan_pos ? ' done' : (i === f.plan_pos ? ' now' : ''));
      d.textContent = (i + 1) + '. (' + a + ')';
      planDiv.appendChild(d);
    });
    const nowEl = planDiv.querySelector('.now');
    if (nowEl) planDiv.scrollTop = Math.max(0, nowEl.offsetTop - 80);
  }

  // ---- replan banner + before/after diff -------------------------------
  const rw = document.getElementById('replanWrap');
  const bn = document.getElementById('banner');
  rw.innerHTML = '';
  if (rp) {
    const toPlan = plans[rp.to_plan];
    bn.style.display = 'block';
    bn.textContent = 'REPLAN: ' + toPlan.label + ' created at step ' + (f.anomaly && f.anomaly.step != null ? f.anomaly.step : '?');
    const h = document.createElement('h2'); h.textContent = 'What changed in the plan';
    const st = document.createElement('div'); st.className = 'stats';
    st.innerHTML = '<span class="s-keep">' + rp.kept + ' kept</span>' +
                   '<span class="s-rem">' + rp.removed + ' removed</span>' +
                   '<span class="s-add">' + rp.added + ' added</span>';
    const info = document.createElement('div'); info.className = 'note';
    info.textContent = rp.executed_before + ' actions already executed; ' + rp.old_remaining +
                       ' were left in the old plan, the new plan has ' + rp.new_total + '.';
    const box = document.createElement('div'); box.className = 'plan';
    rp.diff.forEach(o => {
      const d = document.createElement('div'); d.className = 'pl ' + o.op;
      d.textContent = '(' + o.text + ')'; box.appendChild(d);
    });
    rw.append(h, st, info, box);
  } else {
    bn.style.display = 'none';
  }

  const trucksDiv = document.getElementById('trucks');
  trucksDiv.innerHTML = '';
  Object.entries(f.trucks||{}).forEach(([name, t]) => {
    const row = document.createElement('div'); row.className = 'row';
    const a = document.createElement('span');
    a.textContent = name + (broken.has(name) ? ' (broken down)' : '');
    const b = document.createElement('span');
    b.textContent = t.location + ((t.carrying||[]).length ? ' [' + t.carrying.join(', ') + ']' : '');
    row.append(a, b); trucksDiv.appendChild(row);
  });

  const groundDiv = document.getElementById('ground');
  groundDiv.innerHTML = '';
  const waiting = Object.entries(f.ground||{}).filter(([p]) => !delivered.has(p));
  if (!waiting.length) groundDiv.innerHTML = '<span style="color:#93a1bd">none</span>';
  waiting.forEach(([p, loc]) => {
    const c = document.createElement('span'); c.className = 'chip';
    c.textContent = p + ' @ ' + loc; groundDiv.appendChild(c);
  });

  const delDiv = document.getElementById('delivered');
  delDiv.innerHTML = '';
  if (!(f.delivered||[]).length) delDiv.innerHTML = '<span style="color:#93a1bd">none yet</span>';
  (f.delivered||[]).forEach(d => {
    const c = document.createElement('span'); c.className = 'chip done';
    c.textContent = d.package + ' -> ' + d.location; delDiv.appendChild(c);
  });

  const goalsDiv = document.getElementById('goals');
  goalsDiv.innerHTML = '';
  const goals = Object.assign({}, world.goals);
  Object.entries(f.packages_added||{}).forEach(([p, info]) => {
    if (info.destination) goals[p] = {destination: info.destination, deadline: null, added: true};
  });
  Object.entries(goals).forEach(([pkg, g]) => {
    const row = document.createElement('div'); row.className = 'row';
    const a = document.createElement('span');
    a.textContent = pkg + (g.added ? ' (new)' : '');
    const dl = (f.deadlines||{})[pkg] || g.deadline;
    const b = document.createElement('span');
    b.textContent = '-> ' + g.destination + (dl ? ' by ' + dl : '') +
                    (delivered.has(pkg) ? '  done' : '');
    if (delivered.has(pkg)) b.style.color = '#7ff0bd';
    row.append(a, b); goalsDiv.appendChild(row);
  });

  const sumDiv = document.getElementById('summary');
  sumDiv.innerHTML = '';
  Object.entries(summary).forEach(([k, v]) => {
    const row = document.createElement('div'); row.className = 'row';
    const a = document.createElement('span');
    a.textContent = k.replace(/_/g, ' ');
    const b = document.createElement('span'); b.textContent = v;
    row.append(a, b); sumDiv.appendChild(row);
  });
}

const slider = document.getElementById('slider');
slider.max = frames.length - 1;
let idx = 0, timer = null;
frames.forEach((f, i) => {
  if (!f.replan) return;
  const left = frames.length > 1 ? (i / (frames.length - 1)) * 100 : 0;
  const t = document.createElement('div'); t.className = 'tick';
  t.style.left = 'calc(8px + (100% - 16px) * ' + (left/100) + ')';
  t.title = plans[f.replan.to_plan].label;
  t.onclick = () => { stop(); go(i); };
  document.getElementById('ticks').appendChild(t);
  const b = document.createElement('button'); b.className = 'jump';
  b.textContent = 'Jump to ' + plans[f.replan.to_plan].label;
  b.onclick = () => { stop(); go(i); };
  document.getElementById('jumps').appendChild(b);
});
function go(i) {
  idx = Math.max(0, Math.min(frames.length - 1, i));
  slider.value = idx;
  const f = frames[idx];
  document.getElementById('stepLabel').textContent =
    f.kind === 'anomaly' ? 'REPLAN' : (f.step != null ? 'step ' + f.step : f.kind);
  render(idx);
}
document.getElementById('prev').onclick = () => { stop(); go(idx - 1); };
document.getElementById('next').onclick = () => { stop(); go(idx + 1); };
slider.oninput = () => { stop(); go(+slider.value); };
function stop() { if (timer) { clearInterval(timer); timer = null;
  document.getElementById('play').textContent = 'Play'; } }
document.getElementById('play').onclick = () => {
  if (timer) { stop(); return; }
  document.getElementById('play').textContent = 'Pause';
  if (idx >= frames.length - 1) go(0);
  timer = setInterval(() => {
    if (idx >= frames.length - 1) { stop(); return; }
    go(idx + 1);
  }, 950);
};
document.addEventListener('keydown', e => {
  if (e.key === 'ArrowRight') { stop(); go(idx + 1); }
  if (e.key === 'ArrowLeft') { stop(); go(idx - 1); }
  if (e.key === ' ') { e.preventDefault(); document.getElementById('play').click(); }
});
go(0);
</script>
</body>
</html>
"""


def render(log_text: str, problem_path, out_path=None, open_browser: bool = True):
    """Build the interactive map from a PDDL problem plus captured console output."""
    world = parse_problem(problem_path)
    timeline = parse_log(log_text)

    if not timeline["frames"]:
        print("\n  [Visualizer] No execution steps found in output; map skipped.")
        return None

    if out_path is None:
        out_dir = Path(__file__).resolve().parent / "run_maps"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"{Path(problem_path).stem}_map.html"
    out_path = Path(out_path)

    summary = timeline["summary"]
    subtitle = (
        f"{len(world['locations'])} locations, {len(world['roads'])} roads, "
        f"{len(timeline['frames'])} timeline frames"
    )
    if summary.get("status"):
        subtitle += f" — status {summary['status']}"
    if timeline["closed_roads"]:
        closed = ", ".join(f"{a}-{b}" for a, b in timeline["closed_roads"])
        subtitle += f" — closed: {closed}"

    payload = {"world": world, "timeline": timeline}
    html = (
        HTML_TEMPLATE.replace("__DATA__", json.dumps(payload))
        .replace("__TITLE__", f"Anomaly Replanning Map — {world['name']}")
        .replace("__SUBTITLE__", subtitle)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    print("\n" + "=" * 65)
    print("  VISUALIZATION")
    print("=" * 65)
    print(f"  Locations parsed : {', '.join(world['locations'])}")
    print(f"  Roads parsed     : {len(world['roads'])}")
    print(f"  Timeline frames  : {len(timeline['frames'])}")
    if timeline["closed_roads"]:
        print(f"  Roads closed     : "
              f"{', '.join(f'{a} <-> {b}' for a, b in timeline['closed_roads'])}")
    if timeline["extra_packages"]:
        print(f"  Packages added   : {', '.join(timeline['extra_packages'])}")
    print(f"  Map written to   : {out_path}")
    print("=" * 65)

    if open_browser:
        try:
            webbrowser.open(out_path.resolve().as_uri())
        except Exception as exc:  # pragma: no cover
            print(f"  [Visualizer] Could not open browser automatically: {exc}")

    return out_path


class TeeCapture:
    """Mirror everything written to a stream into an internal buffer."""

    def __init__(self, stream):
        self._stream = stream
        self._chunks = []

    def write(self, data):
        self._chunks.append(data)
        try:
            return self._stream.write(data)
        except UnicodeEncodeError:
            enc = getattr(self._stream, "encoding", None) or "ascii"
            return self._stream.write(data.encode(enc, "replace").decode(enc))

    def flush(self):
        self._stream.flush()

    def isatty(self):
        return getattr(self._stream, "isatty", lambda: False)()

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", "utf-8")

    def text(self):
        return "".join(self._chunks)


# ---------------------------------------------------------------------------
# Optional: run standalone against an already-saved log file
#   py visualizer.py run.txt fast-downward-24.06.1/trucks/p01.pddl
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: py visualizer.py <run_log.txt> <problem.pddl>")
        sys.exit(1)
    raw = Path(sys.argv[1]).read_bytes()
    # PowerShell's "*>" and ">" redirection writes UTF-16; detect it by BOM.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        log = raw.decode("utf-16", errors="replace")
    else:
        log = raw.decode("utf-8-sig", errors="replace")
    render(log, sys.argv[2])
