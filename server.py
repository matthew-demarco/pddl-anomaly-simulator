#!/usr/bin/env python3
"""
Local web server for the Trucks Grid Visualizer.

Serves a browser UI that renders the selected problem's map immediately on
load (no planner needed), and runs the simulator with Fast Downward when you
press Run — animating the truck along the roads hour by hour.

Runs entirely on your machine. Start it and it opens your browser:
    python server.py

Endpoints:
    GET  /                     static UI
    GET  /api/problems         list of problem ids
    GET  /api/problem/{id}     initial map view (no planning)
    POST /api/run              run a simulation, return snapshots + log
    GET  /api/fd-status        is a Fast Downward installation detected?
    POST /api/fd-path          save the Fast Downward path (fd_config.json)
"""

import json
import threading
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from main import DOMAIN_FILE, get_problem_path, parse_manual_anomaly
from planner import _looks_like_fast_downward, resolve_fast_downward_dir, search_fast_downward
from simulator import Simulator

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
PORT = 8765


class Handler(SimpleHTTPRequestHandler):
    """Serves the static UI plus a small JSON API."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    # silence default request logging
    def log_message(self, *args):
        pass

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/problems":
            problems = sorted(
                (ROOT / "fast-downward-24.06.1" / "trucks").glob("p*.pddl"),
                key=lambda p: p.stem,
            )
            self._json({"problems": [p.stem for p in problems]})
            return

        if path.startswith("/api/problem/"):
            pid = path.rsplit("/", 1)[-1]
            problem_path = get_problem_path(pid)

            if not problem_path.exists():
                self._json({"error": f"Unknown problem: {pid}"}, 404)
                return

            # Build the initial view without running the planner: the map
            # (grid, roads, locations, trucks, packages, goals) comes straight
            # from the problem file.
            sim = Simulator(
                domain_path=str(DOMAIN_FILE),
                problem_path=str(problem_path),
                verbose=False,
            )
            snapshot = sim._build_state_snapshot()
            snapshot["problem"] = pid
            self._json(snapshot)
            return

        if path == "/api/fd-status":
            # report the configured path too, so the UI can prefill the field
            configured = ""
            cfg_file = ROOT / "fd_config.json"
            if cfg_file.exists():
                try:
                    configured = str(json.loads(cfg_file.read_text(encoding="utf-8"))
                                     .get("fast_downward_dir", "")).strip()
                except (json.JSONDecodeError, OSError):
                    configured = ""
            try:
                fd_dir = resolve_fast_downward_dir()
                found = _looks_like_fast_downward(fd_dir)
                self._json({"found": found, "path": str(fd_dir), "configured": configured})
            except FileNotFoundError as e:
                self._json({"found": False, "error": str(e), "configured": configured})
            return

        if path == "/api/fd-search":
            # search the disk for Fast Downward; on a hit, remember it for next time
            found_dir = search_fast_downward()
            if found_dir is not None:
                config = ROOT / "fd_config.json"
                config.write_text(
                    json.dumps({"fast_downward_dir": str(found_dir)}, indent=2),
                    encoding="utf-8",
                )
                self._json({"found": True, "path": str(found_dir)})
            else:
                self._json({"found": False})
            return

        super().do_GET()

    # ------------------------------------------------------------------
    # POST
    # ------------------------------------------------------------------

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/run":
            try:
                req = self._read_body()
            except json.JSONDecodeError:
                self._json({"error": "Invalid JSON body"}, 400)
                return

            problem_id = str(req.get("problem", "p01"))
            problem_path = get_problem_path(problem_id)

            if not problem_path.exists():
                self._json({"error": f"Unknown problem: {problem_id}"}, 404)
                return

            # Manual anomalies: "road_closure:3:l2:l3" strings
            scheduled = []
            errors = []

            for spec in req.get("anomalies", []):
                spec = str(spec).strip()

                if not spec:
                    continue

                try:
                    scheduled.append(parse_manual_anomaly(spec))
                except Exception as e:
                    errors.append(f"Could not schedule anomaly '{spec}': {e}")

            if errors:
                self._json({"error": " ".join(errors)}, 400)
                return

            anomaly_chance = float(req.get("anomaly_chance", 0.0) or 0.0)
            anomaly_chance = max(0.0, min(1.0, anomaly_chance))
            seed = req.get("seed")
            seed = int(seed) if str(seed or "").strip().isdigit() else None
            max_anomalies = int(req.get("max_anomalies", 5) or 5)

            sim = Simulator(
                domain_path=str(DOMAIN_FILE),
                problem_path=str(problem_path),
                anomaly_chance=anomaly_chance,
                seed=seed,
                verbose=False,
                max_anomalies=max_anomalies,
                scheduled_anomalies=scheduled,
                json_output=False,  # we read state_history directly
            )

            # Capture the console output for the UI log panel.
            log_lines = []
            sim._log = lambda msg, _lines=log_lines: _lines.append(str(msg))

            result = sim.run()

            self._json({
                "problem": problem_id,
                "snapshots": sim.state_history,
                "summary": {
                    "status": "SUCCESS" if result.success else "FAILED",
                    "failure_reason": result.failure_reason,
                    "actions_executed": result.total_actions_executed,
                    "replans_triggered": result.replans_triggered,
                    "anomalies": [
                        {
                            "type": a.anomaly_type.name,
                            "description": a.description,
                        }
                        for a in result.anomalies_encountered
                    ],
                },
                "log": log_lines,
            })
            return

        if path == "/api/fd-path":
            try:
                req = self._read_body()
            except json.JSONDecodeError:
                self._json({"error": "Invalid JSON body"}, 400)
                return

            fd_path = str(req.get("path", "")).strip()
            config = ROOT / "fd_config.json"
            config.write_text(
                json.dumps({"fast_downward_dir": fd_path}, indent=2),
                encoding="utf-8",
            )
            self._json({"saved": True, "path": fd_path})
            return

        self._json({"error": "Not found"}, 404)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print("=" * 60)
    print("  Trucks Grid Visualizer")
    print(f"  Serving at {url}")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)

    # Open the default browser (Edge) shortly after the server starts.
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
