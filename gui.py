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

PROJECT_DIR = Path(__file__).resolve().parent
TRUCKS_DIR = PROJECT_DIR / "fast-downward-24.06.1" / "trucks"

# Try to detect default MSYS2 Python, otherwise fallback to system Python
DEFAULT_PYTHON = r"C:\msys64\ucrt64\bin\python.exe"
if not os.path.exists(DEFAULT_PYTHON):
    DEFAULT_PYTHON = sys.executable

class SimulatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Trucks Domain Anomaly Replanning Simulator")
        self.root.geometry("1150x900")
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
        problems = sorted(p.stem for p in TRUCKS_DIR.glob("*.pddl") if p.name != "domain.pddl") or [f"p{i:02d}" for i in range(1, 31)]
        self.problem_var = tk.StringVar(value="p01" if "p01" in problems else problems[0])
        self.problem_combo = ttk.Combobox(control_frame, textvariable=self.problem_var, values=problems, state="readonly")
        self.problem_combo.pack(fill=tk.X, pady=(0, 15))
        self.problem_combo.bind("<<ComboboxSelected>>", lambda e: self.plan_var.set(str(Path("plans") / f"{self.problem_var.get()}.plan")))

        # Plan source: load a pre-made plan file, or generate one with Fast Downward
        ttk.Label(control_frame, text="Initial Plan:").pack(anchor=tk.W, pady=(0, 2))
        self.plan_source_var = tk.StringVar(value="load")
        source_frame = ttk.Frame(control_frame)
        source_frame.pack(fill=tk.X)
        ttk.Radiobutton(source_frame, text="Load plan file", value="load", variable=self.plan_source_var,
                        command=self._update_plan_widgets).pack(side=tk.LEFT)
        ttk.Radiobutton(source_frame, text="Generate", value="generate", variable=self.plan_source_var,
                        command=self._update_plan_widgets).pack(side=tk.LEFT, padx=(10, 0))

        self.plan_var = tk.StringVar(value=str(Path("plans") / f"{self.problem_var.get()}.plan"))
        self.plan_entry = ttk.Entry(control_frame, textvariable=self.plan_var)
        self.plan_entry.pack(fill=tk.X, pady=(4, 2))
        self.save_plan_var = tk.BooleanVar(value=False)
        self.save_plan_check = ttk.Checkbutton(control_frame, text="Save generated plan to plans/", variable=self.save_plan_var)
        self.save_plan_check.pack(anchor=tk.W, pady=(0, 15))

        # Deterministic anomaly input
        ttk.Label(control_frame, text="Anomaly ID (Optional):").pack(anchor=tk.W, pady=(0, 2))
        self.anomaly_id_var = tk.StringVar(value="")
        ttk.Entry(control_frame, textvariable=self.anomaly_id_var).pack(fill=tk.X, pady=(0, 2))
        ttk.Label(control_frame, text="1=road, 2=truck, 3=new delivery, 4=deadline", font=("Segoe UI", 8, "italic")).pack(anchor=tk.W)

        ttk.Label(control_frame, text="Step ID (Optional):").pack(anchor=tk.W, pady=(8, 2))
        self.step_id_var = tk.StringVar(value="")
        ttk.Entry(control_frame, textvariable=self.step_id_var).pack(fill=tk.X)

        ttk.Label(control_frame, text="Anomaly Arguments:").pack(anchor=tk.W, pady=(8, 2))
        self.anomaly_args_var = tk.StringVar(value="")
        ttk.Entry(control_frame, textvariable=self.anomaly_args_var).pack(fill=tk.X, pady=(0, 15))

        # Random anomalies (off at 0%)
        ttk.Label(control_frame, text="Random Anomaly Chance (0.0 - 1.0):").pack(anchor=tk.W, pady=(0, 2))
        self.chance_var = tk.DoubleVar(value=0.0)
        ttk.Scale(control_frame, from_=0.0, to=1.0, variable=self.chance_var, command=self._update_chance_label).pack(fill=tk.X)
        self.chance_label = ttk.Label(control_frame, text="0%")
        self.chance_label.pack(anchor=tk.E)

        ttk.Label(control_frame, text="Random Seed (Optional):").pack(anchor=tk.W, pady=(0, 2))
        self.seed_var = tk.StringVar(value="")
        ttk.Entry(control_frame, textvariable=self.seed_var).pack(fill=tk.X, pady=(0, 15))

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

        ttk.Label(control_frame, text="Fast Downward Path (Optional):").pack(anchor=tk.W, pady=(0, 2))
        self.fast_downward_var = tk.StringVar(value="")
        ttk.Entry(control_frame, textvariable=self.fast_downward_var).pack(fill=tk.X, pady=(0, 15))

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
        self._update_plan_widgets()

    def _update_chance_label(self, val):
        self.chance_label.config(text=f"{float(val):.0%}")

    def _update_plan_widgets(self):
        """Enable the plan-file box in Load mode and the save option in Generate mode."""
        loading = self.plan_source_var.get() == "load"
        self.plan_entry.config(state=tk.NORMAL if loading else tk.DISABLED)
        self.save_plan_check.config(state=tk.DISABLED if loading else tk.NORMAL)

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

    # ------------------------------------------------------------------
    # Map drawing: grid layout (1 cell = 1 mile) when the problem has
    # coordinates, otherwise the original circle layout.
    # ------------------------------------------------------------------

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
        locs = data.get("locations", [])
        if not locs:
            return

        if grid_locs and len(grid_locs) == len(locs):
            coords, to_px = self._grid_layout(grid, grid_locs, width, height)
        else:
            coords, to_px = self._circle_layout(locs, width, height), None

        self._draw_roads(data, coords)
        node_radius = 18
        self._draw_locations(data, coords, node_radius)
        self._draw_packages(data, coords, node_radius)
        self._draw_trucks(data, coords, to_px, node_radius)
        self._draw_hud(data, width)

    def _grid_layout(self, grid, grid_locs, width, height):
        gw = max(1, grid.get("width") or 1)
        gh = max(1, grid.get("height") or 1)
        margin_top, margin_bottom = 120, 30
        cell = min((width - 60) / gw, (height - margin_top - margin_bottom) / gh)
        cell = max(cell, 3)
        ox = (width - cell * gw) / 2
        oy = margin_top + (height - margin_top - margin_bottom - cell * gh) / 2

        def to_px(x, y):
            return (ox + (x + 0.5) * cell, oy + (y + 0.5) * cell)

        # Grid lines: each cell is 1 mile (every 5th line on large maps)
        step = 5 if max(gw, gh) > 80 else 1
        for i in range(0, gw + 1, step):
            self.canvas.create_line(ox + i * cell, oy, ox + i * cell, oy + gh * cell, fill="#2b2b2b")
        for j in range(0, gh + 1, step):
            self.canvas.create_line(ox, oy + j * cell, ox + gw * cell, oy + j * cell, fill="#2b2b2b")

        return {loc: to_px(x, y) for loc, (x, y) in grid_locs.items()}, to_px

    def _circle_layout(self, locs, width, height):
        center_x, center_y = width / 2, height / 2 + 30
        radius = min(width, height - 60) / 2 * 0.72
        locs = sorted(locs, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)
        coords = {}
        for i, loc in enumerate(locs):
            angle = (i / len(locs)) * 2 * math.pi - math.pi / 2
            coords[loc] = (center_x + radius * math.cos(angle), center_y + radius * math.sin(angle))
        return coords

    def _draw_roads(self, data, coords):
        # Road metadata (distance/speed/time and closed flag) keyed by undirected pair
        roads = {tuple(sorted([r["from"], r["to"]])): r for r in data.get("roads", [])}
        if not roads:                                   # older snapshots: derive roads from connections
            if not hasattr(self, "all_known_connections"):
                self.all_known_connections = set()
            current = {tuple(sorted(c)) for c in data.get("connections", [])}
            self.all_known_connections.update(current)
            roads = {pair: {"closed": pair not in current} for pair in self.all_known_connections}

        moving = {tuple(sorted(p["road"])) for p in (data.get("truck_positions") or {}).values() if p.get("road")}

        for pair, meta in roads.items():
            if pair[0] not in coords or pair[1] not in coords:
                continue
            x1, y1 = coords[pair[0]]
            x2, y2 = coords[pair[1]]
            mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2

            if meta.get("closed"):
                self.canvas.create_line(x1, y1, x2, y2, fill="#e74c3c", width=5, dash=(8, 6))
                self.canvas.create_text(mid_x, mid_y, text="❌", fill="#ffdddd", font=("Segoe UI", 14))
                continue

            active = pair in moving
            self.canvas.create_line(x1, y1, x2, y2, fill="#4da3ff" if active else "#7f8c8d", width=4 if active else 3)
            if meta.get("distance") is not None and not active:
                label = f"{meta['distance']}mi @ {meta['speed']}mph = {meta['duration']}t"
                self.canvas.create_text(mid_x, mid_y - 11, text=label, fill="#aab7b8", font=("Segoe UI", 8))

    def _draw_locations(self, data, coords, node_radius):
        trucks_here = set((data.get("trucks") or {}).values())
        for loc, (x, y) in coords.items():
            self.canvas.create_oval(
                x - node_radius, y - node_radius, x + node_radius, y + node_radius,
                fill="#2c3e50", outline="#4da3ff" if loc in trucks_here else "#ecf0f1", width=3 if loc in trucks_here else 2
            )
            self.canvas.create_text(x, y, text=loc, fill="#ecf0f1", font=("Segoe UI", 10, "bold"))

    def _draw_packages(self, data, coords, node_radius):
        # Waiting packages: orange badge (top right). Delivered: green badge (top left).
        loc_pkgs, loc_delivered = {}, {}
        for p, loc in (data.get("packages_at_locations") or {}).items():
            loc_pkgs.setdefault(loc, []).append(p)
        for d in data.get("delivered", []):
            loc_delivered.setdefault(d["location"], []).append(d["package"])

        for loc, lst in loc_pkgs.items():
            if loc in coords:
                x, y = coords[loc]
                self.canvas.create_oval(x + node_radius, y - node_radius - 10, x + node_radius + 20, y - node_radius + 10,
                                        fill="#f39c12", outline="#d35400")
                self.canvas.create_text(x + node_radius + 10, y - node_radius, text=str(len(lst)),
                                        fill="white", font=("Segoe UI", 8, "bold"))

        for loc, lst in loc_delivered.items():
            if loc in coords:
                x, y = coords[loc]
                self.canvas.create_oval(x - node_radius - 28, y - node_radius - 10, x - node_radius - 2, y - node_radius + 10,
                                        fill="#27ae60", outline="#2ecc71")
                self.canvas.create_text(x - node_radius - 15, y - node_radius, text="✅" + str(len(lst)),
                                        fill="white", font=("Segoe UI", 8))

    def _draw_trucks(self, data, coords, to_px, node_radius):
        trucks = data.get("trucks") or {}
        positions = data.get("truck_positions") or {name: {"location": loc} for name, loc in trucks.items()}
        truck_cargo = {}
        for c in data.get("cargo", []):
            truck_cargo.setdefault(c.get("truck"), []).append(c["package"])

        # Parked trucks at the same location are fanned out side by side.
        parked = {}
        for name, pos in positions.items():
            if not pos.get("road"):
                parked.setdefault(pos.get("location") or trucks.get(name), []).append(name)
        fanout = {name: (i - (len(names) - 1) / 2) * 46 for names in parked.values() for i, name in enumerate(sorted(names))}

        for name, pos in positions.items():
            road = pos.get("road")
            if road and road[0] in coords and road[1] in coords:
                if to_px and pos.get("x") is not None:
                    x, y = to_px(pos["x"], pos["y"])
                else:                                    # circle layout: interpolate along the drawn road
                    (x1, y1), (x2, y2) = coords[road[0]], coords[road[1]]
                    f = pos.get("fraction", 0)
                    x, y = x1 + (x2 - x1) * f, y1 + (y2 - y1) * f
            else:
                loc = pos.get("location") or trucks.get(name)
                if loc not in coords:
                    continue
                x, y = coords[loc]
                x, y = x + fanout.get(name, 0), y + node_radius + 15

            self.canvas.create_rectangle(x - 22, y - 11, x + 22, y + 11, fill="#e74c3c", outline="#c0392b")
            self.canvas.create_text(x, y, text=name, fill="white", font=("Segoe UI", 8, "bold"))

            c_list = truck_cargo.get(name, [])
            if c_list:
                self.canvas.create_text(x, y + 20, text=f"\U0001F4E6x{len(c_list)}", fill="#f1c40f", font=("Segoe UI", 8))

            if road:
                d, s, mc = pos.get("distance"), pos.get("speed"), pos.get("miles_covered")
                prog = f"{mc:.0f}/{d}mi @ {s}mph" if None not in (d, s, mc) else f"{pos.get('fraction', 0):.0%}"
                self.canvas.create_text(x, y - 19, text=prog, fill="#f1c40f", font=("Segoe UI", 8, "bold"))

        for name in data.get("broken_trucks", []):
            self.canvas.create_text(20, self.canvas.winfo_height() - 20, anchor=tk.SW,
                                    text=f"{name}: broken down", fill="#e74c3c", font=("Segoe UI", 9, "bold"))

    def _draw_hud(self, data, width):
        current_time_str = data.get("current_time", "t?")
        hour = data.get("hour")
        hour_txt = f"  (hour {hour})" if hour is not None else ""
        self.canvas.create_text(20, 20, anchor=tk.NW, text=f"Current Time:  {current_time_str}{hour_txt}",
                                fill="#f1c40f", font=("Courier", 16, "bold"))
        if (data.get("grid") or {}).get("locations"):
            self.canvas.create_text(20, 45, anchor=tk.NW,
                                    text="Grid: 1 cell = 1 mile  |  roads: distance @ speed = travel time",
                                    fill="#95a5a6", font=("Segoe UI", 9))
        last = data.get("last_action")
        if last:
            self.canvas.create_text(20, 65, anchor=tk.NW, text=last, fill="#4da3ff", font=("Consolas", 10))

        goals = data.get("goals", [])
        if goals:
            self.canvas.create_text(width - 20, 20, anchor=tk.NE, text="Delivery Goals:",
                                    fill="#ecf0f1", font=("Segoe UI", 12, "bold"))
            y_offset = 45
            deliv_pkgs = {d["package"] for d in data.get("delivered", [])}

            for g in goals:
                args = g.get("arguments", [])
                if len(args) < 2:
                    continue
                pkg, loc = args[0], args[1]
                deadline = f"by {args[2]}" if len(args) > 2 else "no deadline"
                is_deliv = pkg in deliv_pkgs
                icon = "✅" if is_deliv else "⏳"     # kept outside the f-string so Python 3.9-3.11 can run it
                txt = f"{icon} {pkg} ➔ {loc}  ({deadline})"
                self.canvas.create_text(width - 20, y_offset, anchor=tk.NE, text=txt,
                                        fill="#27ae60" if is_deliv else "#bdc3c7", font=("Segoe UI", 10))
                y_offset += 20

    def run_simulation(self):
        if self.process and self.process.poll() is None:
            messagebox.showwarning("Warning", "A simulation is already running.")
            return

        problem = self.problem_var.get().strip()
        plan = self.plan_var.get().strip()
        anomaly_id = self.anomaly_id_var.get().strip()
        step_id = self.step_id_var.get().strip()
        anomaly_args = self.anomaly_args_var.get().split()
        verbose = self.verbose_var.get()
        python_exe = self.python_var.get().strip()
        fast_downward = self.fast_downward_var.get().strip()

        if plan and not os.path.isabs(plan):
            plan = str(PROJECT_DIR / plan)                 # plans/p01.plan is relative to the project folder

        if not os.path.exists(python_exe):
            messagebox.showerror("Error", f"Python executable not found at:\n{python_exe}\n\nPlease check the path.")
            return

        loading = self.plan_source_var.get() == "load"
        if loading and not os.path.isfile(plan):
            messagebox.showerror("Error", f"Plan file not found at:\n{plan}\n\nChoose 'Generate' to plan with Fast Downward instead.")
            return

        seed = self.seed_var.get().strip()
        if seed and not seed.isdigit():
            messagebox.showerror("Error", "Random seed must be a whole number (or empty).")
            return

        if bool(anomaly_id) != bool(step_id):
            messagebox.showerror("Error", "Anomaly ID and Step ID must be entered together.")
            return

        search = self.search_var.get().strip()

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
        cmd = [python_exe, "-u", "main.py", "--problem", problem, "--search", search, "--json-output"]
        chance = round(self.chance_var.get(), 2)
        if chance > 0:
            cmd.extend(["--anomaly-chance", str(chance)])
            if seed:
                cmd.extend(["--seed", seed])
        if loading:
            cmd.extend(["--plan", plan])
        elif self.save_plan_var.get():
            cmd.append("--save-plan")
        if fast_downward:
            cmd.extend(["--fast-downward", fast_downward])
        if anomaly_id:
            cmd.extend(["--anomaly-id", anomaly_id, "--step-id", step_id])
            if anomaly_args:
                cmd.append("--anomaly-args")
                cmd.extend(anomaly_args)
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
                    errors='replace',
                    cwd=str(PROJECT_DIR),                  # main.py and plans/ are found no matter where the GUI was started
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
