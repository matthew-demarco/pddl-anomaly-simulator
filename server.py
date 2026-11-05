#!/usr/bin/env python3
"""
Local web server for the Trucks Grid Visualizer.

Start it and it opens your browser:
    py server.py              (Windows)
    python3 server.py         (macOS/Linux)

The page shows the selected problem's map immediately (no planner needed).
Pressing Run either LOADS a pre-made plan from plans/ or GENERATES one with
Fast Downward, runs it with any scheduled anomalies, and animates the trucks
hour by hour along the roads. Everything runs on this machine.

Endpoints:
    GET  /                         static UI (static/index.html)
    GET  /api/problems             problem list with counts and matching plan files
    GET  /api/problem/{id}         initial map + the choices the anomaly form needs
    GET  /api/plans                plan files in plans/
    GET  /api/plan-info?path=...   number of actions in a plan file
    GET  /api/fd-status            which Fast Downward will be used and whether it works
    POST /api/fd-path              {"path": ...} validate and save to .fast-downward-path
    GET|POST /api/fd-search        look for Fast Downward on this computer and save it
    POST /api/run                  run a simulation, return snapshots + plans + log + summary

The original request/response fields are still accepted, so an older page
keeps working: /api/run takes "anomalies" as "road_closure:3:l2:l3" strings
plus "anomaly_chance", "seed", "max_anomalies"; with no "plan_source" the
plan is generated, as before.
    POST /api/upload-problem       {"filename", "text"} save a .pddl (upgraded if needed)
    POST /api/upload-plan          {"filename", "text"} save a .plan into plans/
"""

import contextlib
import io
import json
import re
import threading
import traceback
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from main import DOMAIN_FILE, PLANS_DIR, TRUCKS_DIR, build_id_anomaly, default_plan_path, get_problem_path, parse_manual_anomaly
from pddl_parser import parse_problem, parse_problem_text
from planner import (
    _saved_path,
    fast_downward_status,
    find_fast_downward,
    parse_plan,
    parse_plan_text,
    save_fast_downward_path,
    search_fast_downward,
)
from simulator import Simulator, summarize_result
from tools.upgrade_problems import upgrade_problem_text

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
PORT = 8765
RUN_LOCK = threading.Lock()                 # one simulation at a time (stdout is captured per run)
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _safe_name(filename: str, default: str) -> str:
    """Lowercase file stem with only letters, digits, '-' and '_'."""
    stem = Path(filename or default).stem.lower()
    stem = re.sub(r"[^a-z0-9_-]+", "-", stem).strip("-")
    return stem or default


def _unique_path(folder: Path, stem: str, suffix: str) -> Path:
    """folder/stem.suffix, or stem-2, stem-3, ... if that already exists."""
    candidate = folder / f"{stem}{suffix}"
    n = 2
    while candidate.exists():
        candidate = folder / f"{stem}-{n}{suffix}"
        n += 1
    return candidate


def _problem_paths():
    return sorted(
        (p for p in TRUCKS_DIR.glob("*.pddl") if p.name != "domain.pddl"),
        key=lambda p: p.stem,
    )


def _plan_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _resolve_plan(rel: str) -> Path:
    """Turn 'plans/p01.plan' into a path, refusing anything outside plans/."""
    path = (ROOT / rel).resolve()
    if PLANS_DIR.resolve() not in path.parents:
        raise ValueError("Plan files must be inside the plans/ folder.")
    if not path.is_file():
        raise ValueError(f"Plan file not found: {rel}")
    return path


def _problem_id_ok(pid: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_-]+", pid))


class Handler(SimpleHTTPRequestHandler):
    """Serves the static UI plus a small JSON API."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, *args):                       # keep the terminal quiet
        pass

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD_BYTES:
            raise ValueError("Request is too large.")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path

        try:
            if path == "/api/problems":
                paths = _problem_paths()
                # "problems" stays a plain list of IDs (what the page's dropdown
                # expects); "details" adds counts, road data and plan files.
                self._json({
                    "problems": [p.stem for p in paths],
                    "details": {p.stem: self._problem_entry(p) for p in paths},
                })
                return

            if path.startswith("/api/problem/"):
                pid = unquote(path.rsplit("/", 1)[-1]).lower()
                problem_path = get_problem_path(pid)
                if not _problem_id_ok(pid) or not problem_path.is_file():
                    self._json({"error": f"Unknown problem: {pid}"}, 404)
                    return
                self._json(self._problem_details(pid, problem_path))
                return

            if path == "/api/plans":
                plans = sorted(PLANS_DIR.glob("*.plan")) if PLANS_DIR.is_dir() else []
                self._json({"plans": [_plan_rel(p) for p in plans]})
                return

            if path == "/api/plan-info":
                rel = (parse_qs(url.query).get("path") or [""])[0]
                actions = parse_plan(str(_resolve_plan(rel)))
                self._json({"path": rel, "actions": len(actions)})
                return

            if path == "/api/fd-status":
                self._json(self._fd_status())
                return

            if path == "/api/fd-search":
                self._json(self._fd_search())
                return

        except Exception as error:                      # report problems to the page instead of hanging
            self._json({"error": str(error)}, 400)
            return

        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    @staticmethod
    def _fd_status():
        status = fast_downward_status()
        # "found" / "path" / "configured" are the original field names.
        status.update({
            "found": status["ok"],
            "path": str(Path(status["script"]).parent),
            "configured": _saved_path() or "",
        })
        return status

    def _fd_search(self):
        found = find_fast_downward() or search_fast_downward()
        if found is None:
            return {**self._fd_status(), "found": False}
        script = found if found.name == "fast-downward.py" else found / "fast-downward.py"
        saved = save_fast_downward_path(str(script))
        return {**self._fd_status(), "found": True, "path": str(script.parent), "saved": saved["saved"]}

    def _problem_entry(self, path: Path):
        try:
            problem = parse_problem(str(path))
            upgraded = any(p == "road-span" for p, _ in problem.init_facts)
            counts = {k: len(problem.objects.get(k, [])) for k in ("truck", "package", "location")}
        except Exception:
            upgraded, counts = False, {}
        plan = default_plan_path(path)
        return {
            "id": path.stem,
            "trucks": counts.get("truck", 0),
            "packages": counts.get("package", 0),
            "locations": counts.get("location", 0),
            "upgraded": upgraded,
            "plan": _plan_rel(plan) if plan.is_file() else None,
        }

    def _problem_details(self, pid: str, problem_path: Path):
        # The map comes straight from the problem file: no planner needed.
        sim = Simulator(domain_path=str(DOMAIN_FILE), problem_path=str(problem_path), verbose=False)
        snapshot = sim.initial_snapshot()
        state = sim.state
        plan = default_plan_path(problem_path)
        snapshot.update({
            "problem": pid,
            "problem_note": sim._compatibility_error(),
            "time_steps": list(state.time_steps),
            "all_trucks": list(state.all_trucks),
            "all_packages": list(state.all_packages),
            "default_plan": _plan_rel(plan) if plan.is_file() else None,
        })
        return snapshot

    # ------------------------------------------------------------------
    # POST
    # ------------------------------------------------------------------

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            req = self._read_body()
        except (ValueError, json.JSONDecodeError) as error:
            self._json({"error": f"Invalid request: {error}"}, 400)
            return

        try:
            if path == "/api/run":
                self._run(req)
            elif path == "/api/fd-path":
                fd_path = str(req.get("path", "")).strip()
                result = save_fast_downward_path(fd_path)
                self._json({**result, "path": fd_path})
            elif path == "/api/fd-search":
                self._json(self._fd_search())
            elif path == "/api/upload-problem":
                self._upload_problem(req)
            elif path == "/api/upload-plan":
                self._upload_plan(req)
            else:
                self._json({"error": "Not found"}, 404)
        except ValueError as error:
            self._json({"error": str(error)}, 400)
        except Exception as error:                      # unexpected: show it instead of a silent 500
            self._json({"error": f"{type(error).__name__}: {error}", "trace": traceback.format_exc()}, 500)

    def _run(self, req):
        pid = str(req.get("problem", "p01")).lower()
        problem_path = get_problem_path(pid)
        if not _problem_id_ok(pid) or not problem_path.is_file():
            raise ValueError(f"Unknown problem: {pid}")

        # Plan source: "load" a file from plans/, or "generate" with Fast Downward.
        source = req.get("plan_source", "generate")
        plan_path = save_plan_path = None
        if source == "load":
            plan_path = _resolve_plan(str(req.get("plan", "")))
        elif req.get("save_plan"):
            PLANS_DIR.mkdir(exist_ok=True)
            save_plan_path = default_plan_path(problem_path)

        # Anomalies: [{"type": "road_closure", "step": 3, "args": ["l1", "l2"]}, ...]
        # or the original text form: ["road_closure:3:l1:l2", ...]
        scheduled = []
        for item in req.get("anomalies", []):
            if isinstance(item, str):
                if item.strip():
                    try:
                        scheduled.append(parse_manual_anomaly(item.strip()))
                    except Exception as error:
                        raise ValueError(f"Could not schedule anomaly '{item}': {error}")
                continue
            try:
                step = int(item.get("step"))
            except (TypeError, ValueError):
                raise ValueError(f"Anomaly step must be a whole number: {item.get('step')!r}")
            if step < 1:
                raise ValueError("Anomaly steps start at 1.")
            args = [str(a).strip() for a in item.get("args", [])]
            try:
                scheduled.append(build_id_anomaly(str(item.get("type", "")), step, args))
            except Exception as error:
                raise ValueError(str(error))

        steps = [a.step for a in scheduled]
        if len(steps) != len(set(steps)):
            raise ValueError("Only one anomaly may be scheduled at each step.")

        search = str(req.get("search") or "eager_greedy([ff()])")

        # Random anomalies (off unless anomaly_chance > 0)
        try:
            anomaly_chance = max(0.0, min(1.0, float(req.get("anomaly_chance", 0.0) or 0.0)))
            max_anomalies = int(req.get("max_anomalies", 5) or 5)
        except (TypeError, ValueError):
            raise ValueError("Anomaly chance must be a number from 0 to 1.")
        seed = req.get("seed")
        seed = int(seed) if str(seed if seed is not None else "").strip().lstrip("-").isdigit() else None

        with RUN_LOCK:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                sim = Simulator(
                    domain_path=str(DOMAIN_FILE),
                    problem_path=str(problem_path),
                    plan_path=str(plan_path) if plan_path else None,
                    save_plan_path=str(save_plan_path) if save_plan_path else None,
                    anomaly_chance=anomaly_chance,
                    seed=seed,
                    max_anomalies=max_anomalies,
                    verbose=False,
                    scheduled_anomalies=scheduled,
                    search=search,
                )
                result = sim.run()

        summary = summarize_result(sim, result)
        if result.saved_plan_path:
            summary["saved_plan"] = _plan_rel(Path(result.saved_plan_path))

        self._json({
            "problem": pid,
            "snapshots": sim.state_history,
            "plans": sim.plans,
            "summary": summary,
            "log": buffer.getvalue().splitlines(),
        })

    def _upload_problem(self, req):
        text = str(req.get("text", ""))
        problem = parse_problem_text(text)
        if not problem.objects.get("location") or not problem.objects.get("truck"):
            raise ValueError("That file does not look like a Trucks problem (no trucks or locations found).")

        upgraded_text, info = upgrade_problem_text(text)
        stem = _safe_name(req.get("filename", ""), "custom")
        target = _unique_path(TRUCKS_DIR, stem, ".pddl")
        target.write_text(upgraded_text, encoding="utf-8")
        self._json({
            "id": target.stem,
            "upgraded": not info.get("already_upgraded", False),
            "message": f"Saved as {target.name}",
        })

    def _upload_plan(self, req):
        text = str(req.get("text", ""))
        actions = parse_plan_text(text)                 # raises ValueError with the bad line number
        if not actions:
            raise ValueError("That plan file has no actions.")
        PLANS_DIR.mkdir(exist_ok=True)
        target = _unique_path(PLANS_DIR, _safe_name(req.get("filename", ""), "uploaded"), ".plan")
        target.write_text(text, encoding="utf-8")
        self._json({"path": _plan_rel(target), "actions": len(actions)})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print("=" * 60)
    print("  Trucks Grid Visualizer")
    print(f"  Serving at {url}")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()  # open the default browser

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
