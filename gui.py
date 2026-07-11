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
            
        center_x, center_y = width / 2, height / 2
        radius = min(width, height) / 2 * 0.75
        
        locs = data.get("locations", [])
        if not locs:
            return
            
        # Optional: Sort logically so l1, l2, ... are in order
        locs = sorted(locs, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)
        
        # Calculate coordinates for locations in a circle
        coords = {}
        for i, loc in enumerate(locs):
            angle = (i / len(locs)) * 2 * math.pi - math.pi / 2
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            coords[loc] = (x, y)
            
        # Draw roads (connections)
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
                self.canvas.create_text(mid_x, mid_y, text="❌", fill="#ffdddd", font=("Segoe UI", 14))
                    
        # Draw locations
        node_radius = 20
        for loc, (x, y) in coords.items():
            self.canvas.create_oval(
                x - node_radius, y - node_radius, x + node_radius, y + node_radius,
                fill="#2c3e50", outline="#ecf0f1", width=2
            )
            self.canvas.create_text(x, y, text=loc, fill="#ecf0f1", font=("Segoe UI", 10, "bold"))
            
        # Group trucks by location
        trucks = data.get("trucks", {})
        loc_trucks = {}
        for t, loc in trucks.items():
            loc_trucks.setdefault(loc, []).append(t)
            
        # Group cargo by truck
        cargo = data.get("cargo", [])
        truck_cargo = {}
        for c in cargo:
            t = c.get("truck")
            truck_cargo.setdefault(t, []).append(c["package"])
            
        # Draw trucks
        for loc, v in loc_trucks.items():
            if loc not in coords:
                continue
            x, y = coords[loc]
            # Offset them so they don't block the location node perfectly
            offset_y = node_radius + 15
            for i, t in enumerate(v):
                tx = x + (i * 45) - (len(v)*20) + 20
                ty = y + offset_y
                self.canvas.create_rectangle(
                    tx - 20, ty - 10, tx + 20, ty + 10, 
                    fill="#e74c3c", outline="#c0392b"
                )
                self.canvas.create_text(tx, ty, text=t, fill="white", font=("Segoe UI", 7, "bold"))
                
                # Draw cargo indicator for this truck
                c_list = truck_cargo.get(t, [])
                if c_list:
                    self.canvas.create_text(
                        tx, ty + 18, 
                        text=f"📦x{len(c_list)}", fill="#f1c40f", font=("Segoe UI", 8)
                    )

        # Draw un-delivered packages waiting at locations
        packages = data.get("packages_at_locations", {})
        loc_pkgs = {}
        for p, loc in packages.items():
            loc_pkgs.setdefault(loc, []).append(p)
            
        for loc, lst in loc_pkgs.items():
            if loc not in coords:
                continue
            x, y = coords[loc]
            self.canvas.create_oval(
                x + node_radius, y - node_radius - 10, 
                x + node_radius + 20, y - node_radius + 10,
                fill="#f39c12", outline="#d35400"
            )
            self.canvas.create_text(
                x + node_radius + 10, y - node_radius,
                text=str(len(lst)), fill="white", font=("Segoe UI", 8, "bold")
            )
            
        # Draw delivered packages at locations
        delivered = data.get("delivered", [])
        loc_delivered = {}
        for d in delivered:
            loc_delivered.setdefault(d["location"], []).append(d["package"])
            
        for loc, lst in loc_delivered.items():
            if loc not in coords:
                continue
            x, y = coords[loc]
            
            # Draw on the opposite side of waiting packages (-x offset)
            self.canvas.create_oval(
                x - node_radius - 28, y - node_radius - 10, 
                x - node_radius - 2, y - node_radius + 10,
                fill="#27ae60", outline="#2ecc71"
            )
            self.canvas.create_text(
                x - node_radius - 15, y - node_radius,
                text="✅" + str(len(lst)), fill="white", font=("Segoe UI", 8)
            )

        # Print current time HUD
        current_time_str = data.get("current_time", "t?")
        self.canvas.create_text(
            20, 20, anchor=tk.NW,
            text=f"Current Time:  {current_time_str}",
            fill="#f1c40f", font=("Courier", 16, "bold")
        )

        # Print Goals HUD
        goals = data.get("goals", [])
        if goals:
            self.canvas.create_text(
                20, 50, anchor=tk.NW, text="Delivery Goals:", fill="#ecf0f1", font=("Segoe UI", 12, "bold")
            )
            y_offset = 75
            deliv_pkgs = {d["package"] for d in delivered}
            
            for g in goals:
                pred = g.get("predicate", "")
                args = g.get("arguments", [])
                
                if pred == "delivered" and len(args) == 3:
                    pkg, loc, deadline = args
                    is_deliv = pkg in deliv_pkgs
                    color = "#27ae60" if is_deliv else "#bdc3c7"
                    chk = "✅" if is_deliv else "⏳"
                    txt = f"{chk} {pkg} ➔ {loc}  (by {deadline})"
                    self.canvas.create_text(20, y_offset, anchor=tk.NW, text=txt, fill=color, font=("Segoe UI", 10))
                    y_offset += 20
                elif pred == "at-destination" and len(args) == 2:
                    pkg, loc = args
                    is_deliv = pkg in deliv_pkgs
                    color = "#27ae60" if is_deliv else "#bdc3c7"
                    chk = "✅" if is_deliv else "⏳"
                    txt = f"{chk} {pkg} ➔ {loc}  (no deadline)"
                    self.canvas.create_text(20, y_offset, anchor=tk.NW, text=txt, fill=color, font=("Segoe UI", 10))
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
