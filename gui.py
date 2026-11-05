import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import subprocess
import threading
import sys
import os
import queue
import json
import math
from pathlib import Path

# Try to detect default MSYS2 Python, otherwise fallback to system Python
DEFAULT_PYTHON = r"C:\msys64\ucrt64\bin\python.exe"
if not os.path.exists(DEFAULT_PYTHON):
    DEFAULT_PYTHON = sys.executable

class SimulatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Trucks Domain Anomaly Replanning Simulator")
        self.root.geometry("1100x750")
        self.root.configure(padx=10, pady=10)

        # Process management
        self.process = None
        self.output_queue = queue.Queue()

        # Playback management
        self.state_history = []
        self.playback_index = -1
        self.is_playing = True
        self.playback_speed_ms = 750

        self._create_widgets()
        self._start_queue_checker()
        self._playback_loop()

    def _create_widgets(self):
        # Left Panel (Controls)
        control_frame = ttk.LabelFrame(self.root, text="Configuration", padding=10)
        control_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        # Problem Selection
        ttk.Label(control_frame, text="Problem:").pack(anchor=tk.W, pady=(0, 2))
        self.problem_var = tk.StringVar(value="p01")
        problems = [f"p{i:02d}" for i in range(1, 31)]
        self.problem_combo = ttk.Combobox(control_frame, textvariable=self.problem_var, values=problems, state="readonly")
        self.problem_combo.pack(fill=tk.X, pady=(0, 15))

        # Anomaly Chance
        ttk.Label(control_frame, text="Anomaly Chance (0.0 - 1.0):").pack(anchor=tk.W, pady=(0, 2))
        self.chance_var = tk.DoubleVar(value=0.3)
        chance_scale = ttk.Scale(control_frame, from_=0.0, to=1.0, variable=self.chance_var, command=self._update_chance_label)
        chance_scale.pack(fill=tk.X)
        self.chance_label = ttk.Label(control_frame, text="30%")
        self.chance_label.pack(anchor=tk.E, pady=(0, 15))

        # Seed
        ttk.Label(control_frame, text="Random Seed (Optional):").pack(anchor=tk.W, pady=(0, 2))
        self.seed_var = tk.StringVar(value="")
        ttk.Entry(control_frame, textvariable=self.seed_var).pack(fill=tk.X, pady=(0, 2))
        ttk.Label(control_frame, text="Leave empty for random sequence.", font=("Segoe UI", 8, "italic")).pack(anchor=tk.W, pady=(0, 15))

        # Search Type
        ttk.Label(control_frame, text="Fast Downward Search:").pack(anchor=tk.W, pady=(0, 2))
        self.search_var = tk.StringVar(value="eager_greedy([ff()])")
        search_options = [
            "eager_greedy([ff()])",
            "astar(blind())",
            "lazy_wastar([ff()])",
            "eager_greedy([cg()])"
        ]
        self.search_combo = ttk.Combobox(control_frame, textvariable=self.search_var, values=search_options, state="readonly")
        self.search_combo.pack(fill=tk.X, pady=(0, 15))

        # Verbose Output
        self.verbose_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(control_frame, text="Verbose Output (Show State)", variable=self.verbose_var).pack(anchor=tk.W, pady=(0, 2))

        # Export States
        self.export_states_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(control_frame, text="Export State History (PDDL Files)", variable=self.export_states_var).pack(anchor=tk.W, pady=(0, 15))

        # Python Path
        ttk.Label(control_frame, text="Python Executable Path:").pack(anchor=tk.W, pady=(0, 2))
        self.python_var = tk.StringVar(value=DEFAULT_PYTHON)
        ttk.Entry(control_frame, textvariable=self.python_var).pack(fill=tk.X, pady=(0, 15))

        # Fast Downward Path
        ttk.Label(control_frame, text="Fast Downward Path (optional):").pack(anchor=tk.W, pady=(0, 2))
        self.fd_var = tk.StringVar(value=self._load_fd_path())
        ttk.Entry(control_frame, textvariable=self.fd_var).pack(fill=tk.X, pady=(0, 2))
        ttk.Label(control_frame, text="Folder containing fast-downward.py + src/translate. Saved to fd_config.json.", font=("Segoe UI", 8, "italic")).pack(anchor=tk.W, pady=(0, 15))

        # Buttons
        self.run_btn = ttk.Button(control_frame, text="▶ Run Simulation", command=self.run_simulation, style="Accent.TButton")
        self.run_btn.pack(fill=tk.X, pady=(20, 5), ipady=5)

        self.stop_btn = ttk.Button(control_frame, text="⏹ Stop", command=self.stop_simulation, state=tk.DISABLED)
        self.stop_btn.pack(fill=tk.X, ipady=5)

        # Right Panel (Notebook)
        notebook_frame = ttk.Frame(self.root)
        notebook_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(notebook_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Map
        self.map_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.map_tab, text=" Live Map ")
        
        self.canvas = tk.Canvas(self.map_tab, bg="#1e1e1e", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw_map_if_data())

        # Playback controls
        playback_frame = ttk.Frame(self.map_tab, padding=5)
        playback_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.btn_prev = ttk.Button(playback_frame, text="⏪", width=3, command=self._prev_state)
        self.btn_prev.pack(side=tk.LEFT, padx=2)
        
        self.btn_play_pause = ttk.Button(playback_frame, text="⏸", width=3, command=self._toggle_play)
        self.btn_play_pause.pack(side=tk.LEFT, padx=2)
        
        self.btn_next = ttk.Button(playback_frame, text="⏩", width=3, command=self._next_state)
        self.btn_next.pack(side=tk.LEFT, padx=2)
        
        self.playback_slider_var = tk.IntVar(value=0)
        self.playback_slider = ttk.Scale(playback_frame, from_=0, to=0, variable=self.playback_slider_var, command=self._on_slider_move)
        self.playback_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        self.lbl_step = ttk.Label(playback_frame, text="Step: 0 / 0")
        self.lbl_step.pack(side=tk.RIGHT, padx=5)

        # Tab 2: Console
        self.console_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.console_tab, text=" Console Output ")
        self.console = scrolledtext.ScrolledText(self.console_tab, wrap=tk.WORD, font=("Consolas", 10), bg="#1e1e1e", fg="#cccccc")
        self.console.pack(fill=tk.BOTH, expand=True)

        style = ttk.Style()
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        self._last_state_data = None

    def _load_fd_path(self):
        """Read the saved Fast Downward path from fd_config.json."""
        try:
            cfg_path = Path(__file__).resolve().parent / "fd_config.json"

            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                return str(cfg.get("fast_downward_dir") or "")
        except Exception:
            pass

        return ""

    def _save_fd_path(self, fd_path: str):
        """Persist the Fast Downward path to fd_config.json (used by planner.py)."""
        try:
            cfg_path = Path(__file__).resolve().parent / "fd_config.json"
            cfg_path.write_text(json.dumps({"fast_downward_dir": fd_path}, indent=2), encoding="utf-8")
        except Exception as e:
            self.log(f"\n[Could not save fd_config.json: {e}]\n")

    def _update_chance_label(self, val):
        self.chance_label.config(text=f"{float(val):.0%}")

    def log(self, message):
        self.output_queue.put(message)

    def _toggle_play(self):
        self.is_playing = not self.is_playing
        self.btn_play_pause.config(text="⏸" if self.is_playing else "▶")
        
    def _prev_state(self):
        self.is_playing = False
        self.btn_play_pause.config(text="▶")
        if self.playback_index > 0:
            self.playback_index -= 1
            self._update_map_from_index()
            
    def _next_state(self):
        self.is_playing = False
        self.btn_play_pause.config(text="▶")
        if self.playback_index < len(self.state_history) - 1:
            self.playback_index += 1
            self._update_map_from_index()
            
    def _on_slider_move(self, val):
        idx = int(float(val))
        if idx != self.playback_index and 0 <= idx < len(self.state_history):
            self.playback_index = idx
            self.is_playing = False
            self.btn_play_pause.config(text="▶")
            self._update_map_from_index()
            
    def _update_map_from_index(self):
        if not self.state_history:
            self.lbl_step.config(text="Step: 0 / 0")
            return
            
        self.playback_slider.config(to=len(self.state_history)-1)
        self.playback_slider_var.set(self.playback_index)
        self.lbl_step.config(text=f"Step: {self.playback_index} / {len(self.state_history)-1}")
        
        self._last_state_data = self.state_history[self.playback_index]
        self._draw_map_if_data()
        
    def _playback_loop(self):
        if self.is_playing and self.state_history:
            if self.playback_index < len(self.state_history) - 1:
                self.playback_index += 1
                self._update_map_from_index()
        self.root.after(self.playback_speed_ms, self._playback_loop)

    def _start_queue_checker(self):
        """Poll the queue for new messages, separating mapping JSON from typical logs."""
        while not self.output_queue.empty():
            msg = self.output_queue.get()
            
            if "@@MAP_STATE@@" in msg:
                parts = msg.split("@@MAP_STATE@@")
                before = parts[0]
                json_str = parts[1].strip()
                
                if before:
                    self.console.insert(tk.END, before)
                
                try:
                    state_data = json.loads(json_str)
                    self.state_history.append(state_data)
                    self.playback_slider.config(to=len(self.state_history)-1)
                    
                    if len(self.state_history) == 1:
                        self.playback_index = 0
                        self._update_map_from_index()
                except Exception as e:
                    self.console.insert(tk.END, f"\n[GUI JSON Parse Error: {e}]\n")
            else:
                self.console.insert(tk.END, msg)
            
            self.console.see(tk.END)
            
        self.root.after(50, self._start_queue_checker)

    def _draw_map_if_data(self):
        if not self._last_state_data:
            return

        self.canvas.delete("all")
        data = self._last_state_data

        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width <= 1 or height <= 1:
            return

        grid = data.get("grid") or {}
        grid_locs = grid.get("locations") or {}

        if grid_locs:
            self._draw_grid_map(data, width, height, grid_locs)
        else:
            self._draw_circle_map(data, width, height)

        self._draw_hud(data)

    # ------------------------------------------------------------------
    # Grid map (1 cell = 1 mile)
    # ------------------------------------------------------------------

    def _draw_grid_map(self, data, width, height, grid_locs):
        grid = data.get("grid") or {}
        gw = max(1, grid.get("width") or 1)
        gh = max(1, grid.get("height") or 1)

        margin_left, margin_top, margin_bottom = 50, 120, 40
        cell = min((width - margin_left - 30) / gw, (height - margin_top - margin_bottom) / gh)
        cell = max(cell, 8)
        ox = (width - cell * gw) / 2
        oy = margin_top + (height - margin_top - margin_bottom - cell * gh) / 2

        def to_px(x, y):
            return (ox + (x + 0.5) * cell, oy + (y + 0.5) * cell)

        # Grid lines: each cell is 1 mile
        for i in range(gw + 1):
            self.canvas.create_line(ox + i * cell, oy, ox + i * cell, oy + gh * cell, fill="#2b2b2b")

        for j in range(gh + 1):
            self.canvas.create_line(ox, oy + j * cell, ox + gw * cell, oy + j * cell, fill="#2b2b2b")

        coords = {loc: to_px(x, y) for loc, (x, y) in grid_locs.items()}

        # Current connections (undirected view for drawing)
        current_edges = {
            tuple(sorted([c1, c2]))
            for c1, c2 in data.get("connections", [])
            if c1 in coords and c2 in coords
        }

        if not hasattr(self, 'all_known_connections'):
            self.all_known_connections = set()
        self.all_known_connections.update(current_edges)

        # Road metadata keyed by undirected pair
        road_meta = {}

        for r in data.get("roads", []):
            a, b = r.get("from"), r.get("to")

            if a in coords and b in coords:
                road_meta[tuple(sorted([a, b]))] = r

        # Roads with distance/speed labels
        for pair in self.all_known_connections:
            if pair[0] not in coords or pair[1] not in coords:
                continue

            x1, y1 = coords[pair[0]]
            x2, y2 = coords[pair[1]]

            if pair in current_edges:
                self.canvas.create_line(x1, y1, x2, y2, fill="#7f8c8d", width=3)
                meta = road_meta.get(pair)

                if meta:
                    mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
                    label = f"{meta['distance']}mi @ {meta['speed']}mph = {meta['duration']}t"
                    self.canvas.create_text(
                        mid_x, mid_y - 11, text=label,
                        fill="#aab7b8", font=("Segoe UI", 8)
                    )
            else:
                self.canvas.create_line(x1, y1, x2, y2, fill="#e74c3c", width=5)
                mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
                self.canvas.create_text(mid_x, mid_y, text="\u274c", fill="#ffdddd", font=("Segoe UI", 14))

        # Locations
        node_radius = 18

        for loc, (x, y) in coords.items():
            self.canvas.create_oval(
                x - node_radius, y - node_radius, x + node_radius, y + node_radius,
                fill="#2c3e50", outline="#ecf0f1", width=2
            )
            self.canvas.create_text(x, y, text=loc, fill="#ecf0f1", font=("Segoe UI", 10, "bold"))

        # Trucks at interpolated grid positions
        truck_positions = data.get("truck_positions") or {}
        trucks = data.get("trucks", {})
        cargo = data.get("cargo", [])
        truck_cargo = {}

        for c in cargo:
            truck_cargo.setdefault(c.get("truck"), []).append(c["package"])

        # Group trucks that are parked at the same location so they can be
        # fanned out horizontally instead of drawing on top of each other.
        parked_at_loc = {}

        for tname, pos in truck_positions.items():
            if pos.get("x") is None or pos.get("y") is None or not pos.get("road"):
                loc = pos.get("location") or trucks.get(tname)

                if loc is not None:
                    parked_at_loc.setdefault(loc, []).append(tname)

        loc_fanout = {}

        for loc, tnames in parked_at_loc.items():
            for i, tname in enumerate(tnames):
                loc_fanout[tname] = (i - (len(tnames) - 1) / 2) * 46

        for tname, pos in truck_positions.items():
            if pos.get("x") is None or pos.get("y") is None:
                loc = trucks.get(tname)

                if loc not in coords:
                    continue

                x, y = coords[loc]
                x = x + loc_fanout.get(tname, 0)
                y = y + node_radius + 15
            else:
                x, y = to_px(pos["x"], pos["y"])

            self.canvas.create_rectangle(
                x - 22, y - 11, x + 22, y + 11,
                fill="#e74c3c", outline="#c0392b"
            )
            self.canvas.create_text(x, y, text=tname, fill="white", font=("Segoe UI", 8, "bold"))

            c_list = truck_cargo.get(tname, [])

            if c_list:
                self.canvas.create_text(
                    x, y + 20, text=f"\U0001F4E6x{len(c_list)}",
                    fill="#f1c40f", font=("Segoe UI", 8)
                )

            if pos.get("road"):
                d = pos.get("distance")
                s = pos.get("speed")
                mc = pos.get("miles_covered")

                if d is not None and s is not None and mc is not None:
                    prog = f"{mc:.0f}/{d}mi @ {s}mph"
                else:
                    prog = f"{pos.get('fraction', 0):.0%}"

                self.canvas.create_text(
                    x, y - 19, text=prog,
                    fill="#f1c40f", font=("Segoe UI", 8, "bold")
                )

        # Un-delivered packages waiting at locations
        packages = data.get("packages_at_locations", {})
        loc_pkgs = {}

        for p, loc in packages.items():
            loc_pkgs.setdefault(loc, []).append(p)

        for loc, lst in loc_pkgs.items():
            if loc not in coords:
                continue

            x, y = coords[loc]
            self.canvas.create_oval(
                x + node_radius, y - node_radius - 10, x + node_radius + 20, y - node_radius + 10,
                fill="#f39c12", outline="#d35400"
            )
            self.canvas.create_text(
                x + node_radius + 10, y - node_radius,
                text=str(len(lst)), fill="white", font=("Segoe UI", 8, "bold")
            )

        # Delivered packages at locations
        delivered = data.get("delivered", [])
        loc_delivered = {}

        for d in delivered:
            loc_delivered.setdefault(d["location"], []).append(d["package"])

        for loc, lst in loc_delivered.items():
            if loc not in coords:
                continue

            x, y = coords[loc]
            self.canvas.create_oval(
                x - node_radius - 28, y - node_radius - 10, x - node_radius - 2, y - node_radius + 10,
                fill="#27ae60", outline="#2ecc71"
            )
            self.canvas.create_text(
                x - node_radius - 15, y - node_radius,
                text="\u2705" + str(len(lst)), fill="white", font=("Segoe UI", 8)
            )

    # ------------------------------------------------------------------
    # Legacy circular map (problems without grid coordinates)
    # ------------------------------------------------------------------

    def _draw_circle_map(self, data, width, height):
        center_x, center_y = width / 2, height / 2
        radius = min(width, height) / 2 * 0.75

        locs = data.get("locations", [])
        if not locs:
            return

        locs = sorted(locs, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)

        coords = {}
        for i, loc in enumerate(locs):
            angle = (i / len(locs)) * 2 * math.pi - math.pi / 2
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            coords[loc] = (x, y)

        connections = data.get("connections", [])
        current_edges = {tuple(sorted([c1, c2])) for c1, c2 in connections if c1 in coords and c2 in coords}

        if not hasattr(self, 'all_known_connections'):
            self.all_known_connections = set()
        self.all_known_connections.update(current_edges)

        for c1, c2 in self.all_known_connections:
            x1, y1 = coords[c1]
            x2, y2 = coords[c2]
            if (c1, c2) in current_edges:
                self.canvas.create_line(x1, y1, x2, y2, fill="#7f8c8d", width=3, dash=(6, 4))
            else:
                self.canvas.create_line(x1, y1, x2, y2, fill="#e74c3c", width=5)
                mid_x = (x1 + x2) / 2
                mid_y = (y1 + y2) / 2
                self.canvas.create_text(mid_x, mid_y, text="\u274c", fill="#ffdddd", font=("Segoe UI", 14))

        node_radius = 20
        for loc, (x, y) in coords.items():
            self.canvas.create_oval(
                x - node_radius, y - node_radius, x + node_radius, y + node_radius,
                fill="#2c3e50", outline="#ecf0f1", width=2
            )
            self.canvas.create_text(x, y, text=loc, fill="#ecf0f1", font=("Segoe UI", 10, "bold"))

        trucks = data.get("trucks", {})
        loc_trucks = {}
        for t, loc in trucks.items():
            loc_trucks.setdefault(loc, []).append(t)

        cargo = data.get("cargo", [])
        truck_cargo = {}
        for c in cargo:
            truck_cargo.setdefault(c.get("truck"), []).append(c["package"])

        for loc, v in loc_trucks.items():
            if loc not in coords:
                continue
            x, y = coords[loc]
            offset_y = node_radius + 15
            for i, t in enumerate(v):
                tx = x + (i * 45) - (len(v) * 20) + 20
                ty = y + offset_y
                self.canvas.create_rectangle(
                    tx - 20, ty - 10, tx + 20, ty + 10,
                    fill="#e74c3c", outline="#c0392b"
                )
                self.canvas.create_text(tx, ty, text=t, fill="white", font=("Segoe UI", 7, "bold"))

                c_list = truck_cargo.get(t, [])
                if c_list:
                    self.canvas.create_text(
                        tx, ty + 18, text=f"\U0001F4E6x{len(c_list)}",
                        fill="#f1c40f", font=("Segoe UI", 8)
                    )

    # ------------------------------------------------------------------
    # HUD overlay (time + goals)
    # ------------------------------------------------------------------

    def _draw_hud(self, data):
        current_time_str = data.get("current_time", "t?")
        hour = data.get("hour")
        hour_txt = f"  ({hour} hr)" if hour is not None else ""
        self.canvas.create_text(
            20, 20, anchor=tk.NW,
            text=f"Current Time:  {current_time_str}{hour_txt}",
            fill="#f1c40f", font=("Courier", 16, "bold")
        )
        self.canvas.create_text(
            20, 45, anchor=tk.NW,
            text="Grid: 1 cell = 1 mile  |  roads labeled: distance @ speed = travel time",
            fill="#95a5a6", font=("Segoe UI", 9)
        )

        goals = data.get("goals", [])
        if goals:
            self.canvas.create_text(
                width - 20, 70, anchor=tk.NE, text="Delivery Goals:",
                fill="#ecf0f1", font=("Segoe UI", 12, "bold")
            )
            y_offset = 95
            delivered = data.get("delivered", [])
            deliv_pkgs = {d["package"] for d in delivered}

            for g in goals:
                pred = g.get("predicate", "")
                args = g.get("arguments", [])

                if pred == "delivered" and len(args) == 3:
                    pkg, loc, deadline = args
                    is_deliv = pkg in deliv_pkgs
                    color = "#27ae60" if is_deliv else "#bdc3c7"
                    chk = "\u2705" if is_deliv else "\u23f3"
                    txt = f"{chk} {pkg} \u2794 {loc}  (by {deadline})"
                    self.canvas.create_text(width - 20, y_offset, anchor=tk.NE, text=txt, fill=color, font=("Segoe UI", 10))
                    y_offset += 20
                elif pred == "at-destination" and len(args) == 2:
                    pkg, loc = args
                    is_deliv = pkg in deliv_pkgs
                    color = "#27ae60" if is_deliv else "#bdc3c7"
                    chk = "\u2705" if is_deliv else "\u23f3"
                    txt = f"{chk} {pkg} \u2794 {loc}  (no deadline)"
                    self.canvas.create_text(width - 20, y_offset, anchor=tk.NE, text=txt, fill=color, font=("Segoe UI", 10))
                    y_offset += 20

    def run_simulation(self):
        if self.process and self.process.poll() is None:
            messagebox.showwarning("Warning", "A simulation is already running.")
            return

        problem = self.problem_var.get().strip()
        chance = self.chance_var.get()
        seed = self.seed_var.get().strip()
        verbose = self.verbose_var.get()
        python_exe = self.python_var.get().strip()

        if not os.path.exists(python_exe):
            messagebox.showerror("Error", f"Python executable not found at:\n{python_exe}\n\nPlease check the path.")
            return

        search = self.search_var.get().strip()

        # Persist the Fast Downward path (if any) so planner.py picks it up
        self._save_fd_path(self.fd_var.get().strip())

        # Switch to Map Tab automatically
        self.notebook.select(self.map_tab)
        
        # Reset playback state
        self.state_history.clear()
        self.playback_index = -1
        if hasattr(self, 'all_known_connections'):
            self.all_known_connections.clear()
        self.is_playing = True
        self.btn_play_pause.config(text="⏸")
        self.lbl_step.config(text="Step: 0 / 0")
        self.playback_slider.config(to=0)
        self.playback_slider_var.set(0)
        self._last_state_data = None
        self.canvas.delete("all")

        # Use -u to force unbuffered output so we get live updates in the UI
        cmd = [python_exe, "-u", "main.py", "--problem", problem, "--anomaly-chance", str(chance), "--search", search, "--json-output"]
        if seed:
            cmd.extend(["--seed", seed])
        if not verbose:
            cmd.append("--quiet")
            
        if self.export_states_var.get():
            cmd.extend(["--export-states", "state_history"])

        self.console.delete(1.0, tk.END)
        self.log(f"> Executing: {' '.join(cmd)}\n")
        self.log("-" * 80 + "\n")

        self.run_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        def target():
            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                    encoding='utf-8',
                    errors='replace'
                )

                for line in self.process.stdout:
                    self.log(line)

                self.process.wait()
                self.log(f"\n[Process exited with code {self.process.returncode}]\n")
            except Exception as e:
                self.log(f"\n[Error launching simulation: {e}]\n")
            finally:
                self.root.after(0, self._reset_buttons)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()

    def stop_simulation(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.log("\n[Simulation terminated by user]\n")
        self._reset_buttons()

    def _reset_buttons(self):
        self.run_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    app = SimulatorGUI(root)
    root.mainloop()
