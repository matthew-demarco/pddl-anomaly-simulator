/* Trucks Grid Visualizer — client logic */

const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------
// State
// ------------------------------------------------------------------

let frames = [];        // array of state snapshots
let frameIndex = -1;    // currently displayed frame
let playing = false;
let playTimer = null;
let playIntervalMs = 900;
let allKnownEdges = new Set();  // roads ever seen (to draw closures red)
let roadMeta = {};              // undirected pair -> {distance, speed, duration}
let currentProblem = null;
let running = false;
let problemDetails = {};        // id -> {trucks, packages, locations, upgraded, plan}
let problemInfo = null;         // /api/problem/{id} response (choices for the anomaly builder)
let runPlans = [];              // plans used in the last run: initial + one per replan

const canvas = $("map");
const ctx = canvas.getContext("2d");

// ------------------------------------------------------------------
// Canvas helpers
// ------------------------------------------------------------------

function fitCanvas() {
  const parent = canvas.parentElement;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(parent.clientWidth * dpr));
  canvas.height = Math.max(1, Math.floor(parent.clientHeight * dpr));
  canvas.style.width = parent.clientWidth + "px";
  canvas.style.height = parent.clientHeight + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function resizeCanvas() {
  fitCanvas();
  if (frameIndex >= 0 && frames[frameIndex]) drawFrame(frames[frameIndex]);
}

window.addEventListener("resize", resizeCanvas);

// ------------------------------------------------------------------
// Drawing (classic dark logistics style: dashed gray roads, circle nodes)
// ------------------------------------------------------------------

function drawFrame(snap) {
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.width / dpr;
  const height = canvas.height / dpr;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#1e1e1e";
  ctx.fillRect(0, 0, width, height);

  const grid = snap.grid || {};
  const locs = grid.locations || {};

  if (!Object.keys(locs).length) {
    drawCircleMap(snap, width, height);
    return;
  }

  const gw = Math.max(1, grid.width || 1);
  const gh = Math.max(1, grid.height || 1);
  const marginLeft = 50, marginTop = 60, marginBottom = 40;
  let cell = Math.min((width - marginLeft - 30) / gw, (height - marginTop - marginBottom) / gh);
  cell = Math.max(cell, 8);
  const ox = (width - cell * gw) / 2;
  const oy = marginTop + (height - marginTop - marginBottom - cell * gh) / 2;

  const toPx = (x, y) => [ox + (x + 0.5) * cell, oy + (y + 0.5) * cell];
  const coords = {};
  for (const [loc, xy] of Object.entries(locs)) coords[loc] = toPx(xy[0], xy[1]);

  // --- grid lines (1 cell = 1 mile) ---
  ctx.strokeStyle = "#2b2b2b";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= gw; i++) {
    ctx.moveTo(ox + i * cell, oy);
    ctx.lineTo(ox + i * cell, oy + gh * cell);
  }
  for (let j = 0; j <= gh; j++) {
    ctx.moveTo(ox, oy + j * cell);
    ctx.lineTo(ox + gw * cell, oy + j * cell);
  }
  ctx.stroke();

  // --- current connections (undirected view) ---
  const currentEdges = new Set();
  for (const [c1, c2] of snap.connections || []) {
    if (coords[c1] && coords[c2]) currentEdges.add(edgeKey(c1, c2));
  }
  for (const e of currentEdges) allKnownEdges.add(e);
  for (const [a, b] of snap.closed_roads || []) allKnownEdges.add(edgeKey(a, b));

  // road metadata keyed by undirected pair
  for (const r of snap.roads || []) {
    if (coords[r.from] && coords[r.to]) roadMeta[edgeKey(r.from, r.to)] = r;
  }

  // --- roads ---
  for (const key of allKnownEdges) {
    const [a, b] = key.split("::");
    if (!coords[a] || !coords[b]) continue;
    const [x1, y1] = coords[a], [x2, y2] = coords[b];

    if (currentEdges.has(key)) {
      ctx.strokeStyle = "#7f8c8d";
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      ctx.setLineDash([]);

      const meta = roadMeta[key];
      if (meta) {
        const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
        // offset the label perpendicular to the road so it doesn't sit on the line
        const dx = x2 - x1, dy = y2 - y1;
        const len = Math.hypot(dx, dy) || 1;
        const lx = mx + (-dy / len) * 11;
        const ly = my + (dx / len) * 11;
        const label = `${meta.distance}mi @ ${meta.speed}mph = ${meta.duration}t`;
        ctx.font = "10px 'Segoe UI', sans-serif";
        const tw = ctx.measureText(label).width;
        ctx.fillStyle = "#1e1e1e";
        ctx.fillRect(lx - tw / 2 - 3, ly - 9, tw + 6, 13);
        ctx.fillStyle = "#aab7b8";
        ctx.textAlign = "center";
        ctx.fillText(label, lx, ly + 3);
      }
    } else {
      // closed road
      ctx.strokeStyle = "#e74c3c";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
      ctx.fillStyle = "#ffdddd";
      ctx.font = "bold 13px 'Segoe UI', sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("✕", mx, my);
      ctx.textBaseline = "alphabetic";
    }
  }

  // --- location nodes (gray circles) ---
  const nodeRadius = Math.min(18, Math.max(10, cell * 0.45));
  for (const [loc, [x, y]] of Object.entries(coords)) {
    ctx.beginPath();
    ctx.arc(x, y, nodeRadius, 0, Math.PI * 2);
    ctx.fillStyle = "#2c3e50";
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#ecf0f1";
    ctx.stroke();
    ctx.fillStyle = "#ecf0f1";
    ctx.font = `bold ${Math.max(9, nodeRadius * 0.55)}px 'Segoe UI', sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(loc, x, y);
    ctx.textBaseline = "alphabetic";
  }

  // --- trucks at interpolated grid positions ---
  const truckPositions = snap.truck_positions || {};
  const trucks = snap.trucks || {};
  const cargo = {};
  for (const c of snap.cargo || []) {
    (cargo[c.truck] = cargo[c.truck] || []).push(c.package);
  }

  // fan out trucks parked at the same location
  const parkedAt = {};
  for (const [t, pos] of Object.entries(truckPositions)) {
    if (!pos.road && (pos.location || trucks[t])) {
      (parkedAt[pos.location || trucks[t]] = parkedAt[pos.location || trucks[t]] || []).push(t);
    }
  }
  const fanout = {};
  for (const names of Object.values(parkedAt)) {
    names.forEach((t, i) => { fanout[t] = (i - (names.length - 1) / 2) * 46; });
  }

  for (const [tname, pos] of Object.entries(truckPositions)) {
    let x, y;
    if (pos.road && pos.x != null && pos.y != null) {
      // in transit on a road — draw at the interpolated grid position
      [x, y] = toPx(pos.x, pos.y);
    } else {
      // parked at a location — draw just below the node so the label stays visible
      const loc = pos.location || trucks[tname];
      if (!loc || !coords[loc]) continue;
      [x, y] = coords[loc];
      x += fanout[tname] || 0;
      y += nodeRadius + 15;
    }

    ctx.fillStyle = "#e74c3c";
    ctx.strokeStyle = "#c0392b";
    ctx.lineWidth = 1.5;
    ctx.fillRect(x - 22, y - 11, 44, 22);
    ctx.strokeRect(x - 22, y - 11, 44, 22);
    ctx.fillStyle = "#fff";
    ctx.font = "bold 10px 'Segoe UI', sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(tname, x, y);
    ctx.textBaseline = "alphabetic";

    if (pos.road) {
      const d = pos.distance, s = pos.speed, mc = pos.miles_covered;
      const prog = (d != null && s != null && mc != null)
        ? `${Math.round(mc)}/${d}mi @ ${s}mph`
        : `${Math.round((pos.fraction || 0) * 100)}%`;
      ctx.fillStyle = "#f1c40f";
      ctx.font = "bold 10px 'Segoe UI', sans-serif";
      ctx.fillText(prog, x, y - 18);
    }
  }

  // --- time HUD (top-left, classic yellow) ---
  const hour = snap.hour != null ? `  (${snap.hour} hr)` : "";
  ctx.fillStyle = "#f1c40f";
  ctx.font = "bold 16px Consolas, monospace";
  ctx.textAlign = "left";
  ctx.fillText(`Current Time:  ${snap.current_time || "?"}${hour}`, 20, 30);

  ctx.fillStyle = "#95a5a6";
  ctx.font = "10px 'Segoe UI', sans-serif";
  ctx.fillText("Grid: 1 cell = 1 mile  |  roads: distance @ speed = travel time", 20, 48);
}

function edgeKey(a, b) {
  return [a, b].sort().join("::");
}

// Fallback circular layout for problems without grid data
function drawCircleMap(snap, width, height) {
  const cx = width / 2, cy = height / 2;
  const radius = Math.min(width, height) / 2 * 0.7;
  const locs = (snap.locations || []).slice().sort();
  const n = Math.max(1, locs.length);
  const coords = {};
  locs.forEach((loc, i) => {
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
    coords[loc] = [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
  });

  const edges = new Set();
  for (const [c1, c2] of snap.connections || []) {
    if (coords[c1] && coords[c2]) edges.add(edgeKey(c1, c2));
  }

  ctx.strokeStyle = "#7f8c8d";
  ctx.setLineDash([6, 4]);
  for (const key of edges) {
    const [a, b] = key.split("::");
    ctx.beginPath();
    ctx.moveTo(...coords[a]);
    ctx.lineTo(...coords[b]);
    ctx.stroke();
  }
  ctx.setLineDash([]);

  for (const [loc, [x, y]] of Object.entries(coords)) {
    ctx.beginPath();
    ctx.arc(x, y, 16, 0, Math.PI * 2);
    ctx.fillStyle = "#2c3e50";
    ctx.fill();
    ctx.strokeStyle = "#ecf0f1";
    ctx.stroke();
    ctx.fillStyle = "#ecf0f1";
    ctx.textAlign = "center";
    ctx.fillText(loc, x, y);
  }

  ctx.fillStyle = "#f1c40f";
  ctx.font = "bold 16px Consolas, monospace";
  ctx.textAlign = "left";
  ctx.fillText(`Current Time:  ${snap.current_time || "?"}`, 20, 30);
}

// ------------------------------------------------------------------
// Data panel
// ------------------------------------------------------------------

function updatePanels(snap) {
  $("time-display").textContent = snap.current_time || "—";
  $("last-action").textContent = snap.last_action || "";

  // anomaly that caused this frame's replan
  const note = $("anomaly-note");
  if (snap.anomaly) {
    note.hidden = false;
    note.textContent = `Step ${snap.anomaly.step}: ${snap.anomaly.description} ${snap.anomaly.response || ""}`;
  } else {
    note.hidden = true;
  }

  // active plan with progress (done ✓ / current highlighted)
  const plan = runPlans[snap.plan_id || 0];
  const planList = $("plan-list");
  planList.innerHTML = "";
  $("plan-title").textContent = plan ? `${plan.label} · ${plan.actions.length} actions` : "Plan";
  if (plan) {
    const pos = snap.plan_pos || 0;
    plan.actions.forEach((a, i) => {
      const li = document.createElement("li");
      li.textContent = `${i + 1}. ${a}`;
      li.className = i < pos ? "done" : (i === pos ? "now" : "");
      planList.appendChild(li);
    });
    const now = planList.querySelector(".now");
    if (now) planList.scrollTop = Math.max(0, now.offsetTop - planList.offsetTop - 60);
  }

  // goals
  const delivered = new Set((snap.delivered || []).map(d => d.package));
  const goalList = $("goal-list");
  goalList.innerHTML = "";
  for (const g of snap.goals || []) {
    const li = document.createElement("li");
    const args = g.arguments || [];
    let txt = "";
    let done = false;

    if (g.predicate === "delivered" && args.length === 3) {
      done = delivered.has(args[0]);
      txt = `${done ? "✅" : "⏳"} ${args[0]} ➔ ${args[1]}  (by ${args[2]})`;
    } else if (g.predicate === "at-destination" && args.length === 2) {
      done = delivered.has(args[0]);
      txt = `${done ? "✅" : "⏳"} ${args[0]} ➔ ${args[1]}  (no deadline)`;
    } else {
      txt = `${g.predicate} ${args.join(" ")}`;
    }

    li.textContent = txt;
    li.className = done ? "done" : "pending";
    goalList.appendChild(li);
  }

  // trucks & cargo
  const truckList = $("truck-list");
  truckList.innerHTML = "";
  const cargo = {};
  for (const c of snap.cargo || []) {
    (cargo[c.truck] = cargo[c.truck] || []).push(c.package);
  }
  for (const [t, loc] of Object.entries(snap.trucks || {})) {
    const li = document.createElement("li");
    const carried = cargo[t] || [];
    li.textContent = `${t} @ ${loc}${carried.length ? ` — carrying [${carried.join(", ")}]` : ""}`;
    truckList.appendChild(li);
  }

  // packages on the ground
  const pkgList = $("package-list");
  pkgList.innerHTML = "";
  for (const [p, loc] of Object.entries(snap.packages_at_locations || {})) {
    const li = document.createElement("li");
    li.textContent = `${p} @ ${loc}`;
    pkgList.appendChild(li);
  }
}

function showFrame(i) {
  if (!frames.length) return;
  frameIndex = Math.max(0, Math.min(frames.length - 1, i));
  const snap = frames[frameIndex];
  drawFrame(snap);
  updatePanels(snap);
  $("frame-slider").max = frames.length - 1;
  $("frame-slider").value = frameIndex;
  $("frame-label").textContent = `frame ${frameIndex + 1} / ${frames.length}` + (snap.step ? ` · step ${snap.step}` : "");
}

// ------------------------------------------------------------------
// Playback
// ------------------------------------------------------------------

function play() {
  if (!frames.length) return;
  playing = true;
  $("btn-play").textContent = "⏸";
  playTimer = setInterval(() => {
    if (frameIndex >= frames.length - 1) {
      pause();
      return;
    }
    showFrame(frameIndex + 1);
  }, playIntervalMs);
}

function pause() {
  playing = false;
  $("btn-play").textContent = "▶";
  if (playTimer) clearInterval(playTimer);
  playTimer = null;
}

$("btn-play").addEventListener("click", () => playing ? pause() : play());
$("btn-prev").addEventListener("click", () => { pause(); showFrame(frameIndex - 1); });
$("btn-next").addEventListener("click", () => { pause(); showFrame(frameIndex + 1); });
$("frame-slider").addEventListener("input", (e) => { pause(); showFrame(Number(e.target.value)); });

// ------------------------------------------------------------------
// API calls
// ------------------------------------------------------------------

async function loadProblems(selectId) {
  const res = await fetch("/api/problems");
  const data = await res.json();
  problemDetails = data.details || {};
  const select = $("problem");
  select.innerHTML = "";
  for (const p of data.problems) {
    const opt = document.createElement("option");
    opt.value = p;
    const d = problemDetails[p];
    opt.textContent = d && !d.upgraded ? `${p} (no road data)` : p;
    select.appendChild(opt);
  }
  const first = selectId && data.problems.includes(selectId) ? selectId
              : (data.problems.includes("p01") ? "p01" : data.problems[0]);
  if (!first) return;
  select.value = first;
  loadProblem(first);
}

async function loadProblem(pid) {
  currentProblem = pid;
  const res = await fetch(`/api/problem/${pid}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    $("problem-meta").textContent = err.error || "Could not load problem.";
    return;
  }
  const snap = await res.json();
  problemInfo = snap;
  // reset view for the new problem
  pause();
  frames = [snap];
  runPlans = [];
  setReplanTicks();
  allKnownEdges = new Set();
  roadMeta = {};
  showFrame(0);
  const nLocs = (snap.locations || []).length;
  const nRoads = (snap.connections || []).length / 2;
  $("problem-meta").textContent =
    `${nLocs} locations, ${nRoads} roads` + (snap.grid.width ? `, grid ${snap.grid.width}×${snap.grid.height}` : "");
  if (snap.problem_note) {
    $("problem-meta").textContent += ` — ${snap.problem_note}`;
    $("problem-meta").className = "hint error";
  } else {
    $("problem-meta").className = "hint";
  }
  $("save-plan-name").textContent = `plans/${pid}.plan`;
  await loadPlanFiles(snap.default_plan);
  renderAnomalyBuilder();
  if (snap.problem_note) return;      // the problem must be upgraded before it can run

  // Automatically load (or generate) and animate the selected problem's
  // initial plan. This uses the same simulator endpoint as the Run button,
  // with anomalies disabled, so selecting a problem is enough to populate it.
  const source = planSource();
  $("run-status").textContent = source === "load" ? "Loading initial plan..." : "Generating initial plan...";
  $("run-status").className = "hint";
  $("log").textContent = "";
  try {
    const planRes = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        problem: pid,
        plan_source: source,
        plan: $("plan-file-select").value,
        anomaly_chance: 0,
        seed: null,
        anomalies: [],
      }),
    });
    const planData = await planRes.json();

    if (!planRes.ok) {
      $("run-status").textContent = planData.error || "Could not generate the initial plan.";
      $("run-status").className = "hint error";
      return;
    }

    $("log").textContent = (planData.log || []).join("\n");
    $("log").scrollTop = $("log").scrollHeight;

    if (!planData.snapshots || !planData.snapshots.length) {
      $("run-status").textContent =
        `No plan found. ${planData.summary?.failure_reason || ""}`;
      $("run-status").className = "hint error";
      return;
    }

    allKnownEdges = new Set();
    roadMeta = {};
    frames = planData.snapshots;
    runPlans = planData.plans || [];
    setReplanTicks();
    showFrame(0);
    play();

    const summary = planData.summary || {};
    $("run-status").textContent =
      `${summary.status || "PLAN LOADED"} — ${summary.actions_executed ?? 0} actions`;
    $("run-status").className =
      summary.status === "SUCCESS" ? "hint ok" : "hint";
  } catch (err) {
    $("run-status").textContent = `Initial plan failed: ${err}`;
    $("run-status").className = "hint error";
  }
}

$("problem").addEventListener("change", (e) => loadProblem(e.target.value));

$("anomaly-chance").addEventListener("input", (e) => {
  $("chance-value").textContent = `${e.target.value}%`;
});

async function checkFdStatus() {
  const res = await fetch("/api/fd-status");
  const data = await res.json();
  const el = $("fd-status");
  if (data.configured) $("fd-path").value = data.configured;   // prefill the field
  if (data.found) {
    el.textContent = `Fast Downward detected: ${data.path}`;
    el.className = "hint ok";
  } else {
    el.textContent = "Searching your folders for Fast Downward...";
    el.className = "hint";
    // try to find it automatically
    const r = await fetch("/api/fd-search");
    const d = await r.json();
    if (d.found) {
      $("fd-path").value = d.path;
      el.textContent = `Fast Downward found: ${d.path}`;
      el.className = "hint ok";
    } else {
      el.textContent = "No Fast Downward found yet — paste its folder above.";
      el.className = "hint error";
    }
  }
}

$("fd-save").addEventListener("click", async () => {
  const path = $("fd-path").value.trim();
  await fetch("/api/fd-path", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  await checkFdStatus();
});

$("run").addEventListener("click", async () => {
  if (running) return;
  running = true;
  $("run").disabled = true;
  $("run-status").textContent = "Planning and running (can take ~10-60s)...";
  $("run-status").className = "hint";

  const anomalies = $("anomaly-input").value
    .split("\n")
    .map(s => s.trim())
    .filter(Boolean);

  const seedRaw = $("seed").value.trim();
  if (seedRaw && !/^\d+$/.test(seedRaw)) {
    $("run-status").textContent = "Random seed must be a whole number (or empty).";
    $("run-status").className = "hint error";
    running = false;
    $("run").disabled = false;
    return;
  }
  if (planSource() === "load" && !$("plan-file-select").value) {
    $("run-status").textContent = "Choose a plan file, or switch to Generate.";
    $("run-status").className = "hint error";
    running = false;
    $("run").disabled = false;
    return;
  }
  const body = {
    problem: currentProblem || "p01",
    plan_source: planSource(),
    plan: $("plan-file-select").value,
    save_plan: planSource() === "generate" && $("save-plan").checked,
    anomaly_chance: Number($("anomaly-chance").value) / 100,
    seed: seedRaw ? Number(seedRaw) : null,
    anomalies,
  };

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();

    if (!res.ok) {
      $("run-status").textContent = data.error || "Run failed.";
      $("run-status").className = "hint error";
      return;
    }

    // Log output
    const log = $("log");
    log.textContent = (data.log || []).join("\n");
    log.scrollTop = log.scrollHeight;

    if (!data.snapshots || !data.snapshots.length) {
      $("run-status").textContent =
        `No plan found. ${data.summary.failure_reason || ""}`;
      $("run-status").className = "hint error";
      return;
    }

    // reset roads view for the run
    allKnownEdges = new Set();
    roadMeta = {};
    frames = data.snapshots;
    runPlans = data.plans || [];
    setReplanTicks();
    showFrame(0);
    play();
    if (data.summary.saved_plan) await loadPlanFiles(data.summary.saved_plan);

    const s = data.summary;
    $("run-status").textContent =
      `${s.status} — ${s.actions_executed} actions, ${s.replans_triggered} replan(s), ` +
      `${s.anomalies.length} anomal${s.anomalies.length === 1 ? "y" : "ies"}. ` +
      (s.failure_reason ? `Reason: ${s.failure_reason}` : "") +
      (s.saved_plan ? ` Plan saved to ${s.saved_plan}.` : "");
    $("run-status").className = s.status === "SUCCESS" ? "hint ok" : "hint error";
  } catch (e) {
    $("run-status").textContent = `Request failed: ${e}`;
    $("run-status").className = "hint error";
  } finally {
    running = false;
    $("run").disabled = false;
  }
});

// ------------------------------------------------------------------
// Replan markers on the timeline (added)
// ------------------------------------------------------------------

function setReplanTicks() {
  const wrap = $("replan-ticks");
  wrap.innerHTML = "";
  if (frames.length < 2) return;
  frames.forEach((f, i) => {
    if (f.kind !== "anomaly" && f.kind !== "stopped") return;
    const tick = document.createElement("div");
    tick.className = "replan-tick" + (f.kind === "stopped" ? " stopped" : "");
    tick.style.left = `calc(7px + (100% - 14px) * ${i / (frames.length - 1)})`;
    tick.title = f.last_action || f.kind;
    tick.addEventListener("click", () => { pause(); showFrame(i); });
    wrap.appendChild(tick);
  });
}

// ------------------------------------------------------------------
// Plan source: generate with Fast Downward, or load a plan file (added)
// ------------------------------------------------------------------

function planSource() {
  return document.querySelector('input[name="plan-source"]:checked').value;
}

function showPlanSource() {
  const loading = planSource() === "load";
  $("load-plan-box").hidden = !loading;
  $("save-plan-row").style.display = loading ? "none" : "";
  refreshPlanMeta();
}

async function loadPlanFiles(preferred) {
  const res = await fetch("/api/plans");
  const data = await res.json();
  const select = $("plan-file-select");
  select.innerHTML = "";
  for (const p of data.plans || []) {
    const opt = document.createElement("option");
    opt.value = p;
    opt.textContent = p;
    select.appendChild(opt);
  }
  if (!(data.plans || []).length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No plan files in plans/";
    select.appendChild(opt);
  }
  if (preferred && (data.plans || []).includes(preferred)) select.value = preferred;
  showPlanSource();
}

let planLength = null;
async function refreshPlanMeta() {
  planLength = null;
  const path = $("plan-file-select").value;
  if (planSource() !== "load" || !path) { $("plan-meta").textContent = ""; return; }
  const res = await fetch(`/api/plan-info?path=${encodeURIComponent(path)}`);
  const data = await res.json();
  if (!res.ok) { $("plan-meta").textContent = data.error || ""; return; }
  planLength = data.actions;
  const forThis = path.endsWith(`/${currentProblem}.plan`);
  $("plan-meta").textContent = `${data.actions} actions` + (forThis ? "" : ` — make sure it was made for ${currentProblem}`);
}

document.querySelectorAll('input[name="plan-source"]').forEach(r => r.addEventListener("change", showPlanSource));
$("plan-file-select").addEventListener("change", refreshPlanMeta);

// ------------------------------------------------------------------
// Uploads: a .pddl problem or a .plan file (added)
// ------------------------------------------------------------------

function readChosenFile(input) {
  return new Promise((resolve, reject) => {
    const file = input.files[0];
    if (!file) return reject(new Error("No file chosen"));
    const reader = new FileReader();
    reader.onload = () => resolve({ name: file.name, text: reader.result });
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

$("problem-upload").addEventListener("click", () => $("problem-file").click());
$("problem-file").addEventListener("change", async () => {
  try {
    const f = await readChosenFile($("problem-file"));
    const data = await postJson("/api/upload-problem", { filename: f.name, text: f.text });
    await loadProblems(data.id);
    $("run-status").textContent = data.message + (data.upgraded ? " (road distances, speeds and a grid were added)" : "");
    $("run-status").className = "hint ok";
  } catch (e) {
    $("run-status").textContent = `Could not load that problem: ${e.message}`;
    $("run-status").className = "hint error";
  }
  $("problem-file").value = "";
});

$("plan-upload").addEventListener("click", () => $("plan-file").click());
$("plan-file").addEventListener("change", async () => {
  try {
    const f = await readChosenFile($("plan-file"));
    const data = await postJson("/api/upload-plan", { filename: f.name, text: f.text });
    await loadPlanFiles(data.path);
  } catch (e) {
    $("plan-meta").textContent = `Could not use that plan: ${e.message}`;
  }
  $("plan-file").value = "";
});

// ------------------------------------------------------------------
// Anomaly builder: offers only valid choices for this problem and adds a
// correctly formatted line to the "Manual anomalies" box (added)
// ------------------------------------------------------------------

let newPackageCounter = 1;

function abSelect(id, labelText, options) {
  const label = document.createElement("label");
  label.htmlFor = id;
  label.textContent = labelText;
  const select = document.createElement("select");
  select.id = id;
  for (const [value, text] of options) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = text;
    select.appendChild(opt);
  }
  return [label, select];
}

function renderAnomalyBuilder() {
  const box = $("ab-fields");
  box.innerHTML = "";
  $("ab-error").textContent = "";
  if (!problemInfo) return;
  const info = problemInfo;
  const locs = (info.locations || []).slice().sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const type = $("ab-type").value;
  const parts = [];

  if (type === "road_closure") {
    const roads = (info.roads || []).filter(r => !r.closed)
      .map(r => [`${r.from}:${r.to}`, `${r.from} ↔ ${r.to}` + (r.distance != null ? ` (${r.distance} mi)` : "")]);
    parts.push(...abSelect("ab-road", "Road", roads));
  } else if (type === "truck_breakdown") {
    parts.push(...abSelect("ab-truck", "Truck", (info.all_trucks || []).map(t => [t, t])));
  } else if (type === "new_delivery") {
    const label = document.createElement("label");
    label.htmlFor = "ab-pkg";
    label.textContent = "New package name";
    const input = document.createElement("input");
    input.type = "text";
    input.id = "ab-pkg";
    input.value = `package_new${newPackageCounter}`;
    parts.push(label, input);
    parts.push(...abSelect("ab-origin", "From", locs.map(l => [l, l])));
    parts.push(...abSelect("ab-dest", "To", locs.map(l => [l, l])));
  } else if (type === "deadline_change") {
    parts.push(...abSelect("ab-package", "Package", (info.all_packages || []).map(p => [p, p])));
    parts.push(...abSelect("ab-deadline", "New deadline", (info.time_steps || []).map(t => [t, `${t} (hour ${t.slice(1)})`])));
  }
  parts.forEach(p => box.appendChild(p));
  if ($("ab-dest") && locs.length > 1) $("ab-dest").value = locs[1];
}

$("ab-type").addEventListener("change", renderAnomalyBuilder);

$("ab-add").addEventListener("click", () => {
  const err = $("ab-error");
  err.textContent = "";
  const type = $("ab-type").value;
  const step = $("ab-step").value.trim();
  const info = problemInfo || {};

  if (!/^\d+$/.test(step) || Number(step) < 1) { err.textContent = "Step must be a whole number, 1 or more."; return; }
  if (planSource() === "load" && planLength && Number(step) > planLength) {
    err.textContent = `This plan has ${planLength} actions, so step ${step} would never happen.`;
    return;
  }
  const existing = $("anomaly-input").value.split("\n").map(s => s.trim()).filter(Boolean);
  if (existing.some(line => line.split(":")[1] === step)) { err.textContent = `Step ${step} already has an anomaly.`; return; }

  let line = "";
  if (type === "road_closure") {
    if (!$("ab-road") || !$("ab-road").value) { err.textContent = "This problem has no open roads."; return; }
    line = `road_closure:${step}:${$("ab-road").value}`;
  } else if (type === "truck_breakdown") {
    if ((info.all_trucks || []).length < 2) { err.textContent = "Needs at least 2 trucks: the last truck cannot break down."; return; }
    line = `truck_breakdown:${step}:${$("ab-truck").value}`;
  } else if (type === "new_delivery") {
    const pkg = $("ab-pkg").value.trim();
    if (!/^[a-z][a-z0-9_]*$/.test(pkg)) { err.textContent = "Package name: lowercase letters, digits and _ (start with a letter)."; return; }
    if ((info.all_packages || []).includes(pkg) || existing.some(l => l.split(":")[2] === pkg)) {
      err.textContent = `A package named ${pkg} already exists.`; return;
    }
    if ($("ab-origin").value === $("ab-dest").value) { err.textContent = "From and To must be different."; return; }
    line = `new_delivery:${step}:${pkg}:${$("ab-origin").value}:${$("ab-dest").value}`;
    newPackageCounter += 1;
  } else if (type === "deadline_change") {
    line = `deadline_change:${step}:${$("ab-package").value}:${$("ab-deadline").value}`;
  }

  $("anomaly-input").value = [...existing, line].join("\n");
  renderAnomalyBuilder();
});

// ------------------------------------------------------------------
// Boot
// ------------------------------------------------------------------

fitCanvas();
loadProblems();
checkFdStatus();
