"""
Fast Downward Planner Integration.

Finds Fast Downward, invokes it to solve a PDDL problem, and parses the
resulting plan. Plans can also be loaded from pre-made files (parse_plan).
"""                                                                         # Explains that this module runs Fast Downward and converts the resulting plan into simulator actions.

import json                                                                  # Reads the optional fd_config.json written by the Tkinter GUI / older browser page.
import os                                                                    # Imports operating-system utilities for environment variables and OS detection.
import time                                                                  # Bounds the disk search for Fast Downward.
import subprocess                                                            # Allows the simulator to launch Fast Downward as an external command-line process.
import sys                                                                   # Provides access to the Python interpreter currently running the simulator.
from pathlib import Path                                                     # Provides platform-independent tools for constructing, resolving, reading, checking, and deleting file paths.
from typing import Dict, List, Optional                                      # Imports type hints.

from state import PlanAction                                                 # Imports the class that stores one grounded planner action and its ordered arguments.


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Path to the fast-downward directory (relative to this file's location)
_THIS_DIR = Path(__file__).resolve().parent                                  # Finds the absolute directory containing planner.py so paths do not depend on where the terminal was opened.
FAST_DOWNWARD_DIR = _THIS_DIR / "fast-downward-24.06.1"                     # The Fast Downward installation bundled beside the simulator files.
FAST_DOWNWARD_SCRIPT = FAST_DOWNWARD_DIR / "fast-downward.py"               # The Python script used to start Fast Downward.
FAST_DOWNWARD_CONFIG = _THIS_DIR / ".fast-downward-path"                    # One-line file holding a saved path (written by configure_fast_downward.py or the browser).
FAST_DOWNWARD_JSON_CONFIG = _THIS_DIR / "fd_config.json"                    # {"fast_downward_dir": ...} (Tomas's config file; still honored).
FAST_DOWNWARD_ENV_VAR = "FAST_DOWNWARD_PATH"                                # Environment variable that overrides the saved path.
FAST_DOWNWARD_DIR_ENV_VAR = "FAST_DOWNWARD_DIR"                             # Same, folder form (Tomas's name; still honored).
PLANNER_OUTPUT_DIR = _THIS_DIR / ".planner-output"                          # Project-owned folder for generated plan files (keeps the Fast Downward folder clean).

# Extra places checked automatically when nothing is configured and the bundled
# copy is not usable on this operating system.
_FD_CANDIDATES = [
    _THIS_DIR / "fast-downward",
    _THIS_DIR / "downward",
    Path.home() / "FastDownward" / "downward",
    Path.home() / "downward",
    Path.home() / "fast-downward",
    Path("C:/fast-downward/downward"),
    Path("C:/fast-downward"),
    Path("C:/FastDownward/downward"),
    Path("C:/downward"),
]


def _normalize_fast_downward_path(value: str) -> Path:
    """Resolve either a Fast Downward directory or fast-downward.py path."""
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = (_THIS_DIR / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if candidate.is_dir():
        candidate = candidate / "fast-downward.py"
    return candidate


def validate_fast_downward_installation(script_path: Path) -> tuple[bool, str]:
    """Check that the selected checkout has a binary for this operating system."""
    if not script_path.is_file():
        return False, f"Fast Downward script not found: {script_path}"

    binary_name = "downward.exe" if os.name == "nt" else "downward"
    binary_path = script_path.parent / "builds" / "release" / "bin" / binary_name
    if binary_path.is_file():
        return True, f"Fast Downward ready: {script_path}"

    other_binary = "downward" if os.name == "nt" else "downward.exe"
    other_path = script_path.parent / "builds" / "release" / "bin" / other_binary
    if other_path.is_file():
        platform_name = "Windows" if os.name == "nt" else "macOS/Linux"
        return False, (
            f"This Fast Downward checkout contains {other_binary}, which is not "
            f"compatible with {platform_name}."
        )

    return False, (
        f"Fast Downward is not compiled for this system. Missing: {binary_path}"
    )


def _looks_like_fast_downward(path: Path) -> bool:
    """True when the folder holds a fast-downward.py that can run on this OS (kept for older callers)."""
    return validate_fast_downward_installation(Path(path) / "fast-downward.py")[0]


# Folders never worth descending into while searching the disk for Fast Downward.
_SEARCH_SKIP = {
    "appdata", "node_modules", ".git", "__pycache__", "windows", "program files",
    "program files (x86)", "programdata", "$recycle.bin", "site-packages",
    "venv", ".venv", "pictures", "music", "videos", "onedrivetemp", "cache",
}


def search_fast_downward(max_seconds: float = 25.0) -> Optional[Path]:
    """Search the user's folders (bounded in depth and time) for a usable Fast Downward folder."""
    roots = [(Path.home(), 6), (_THIS_DIR.parent, 5), (Path("C:/"), 2)]
    deadline = time.time() + max_seconds
    for root, max_depth in roots:
        if not root.exists():
            continue
        stack = [(root, 0)]
        while stack:
            if time.time() > deadline:
                return None
            folder, depth = stack.pop()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.lower() not in _SEARCH_SKIP and depth < max_depth:
                                stack.append((Path(entry.path), depth + 1))
                        elif entry.name == "fast-downward.py" and _looks_like_fast_downward(folder):
                            return folder
            except (PermissionError, OSError):
                continue
    return None


def _saved_path() -> Optional[str]:
    """A path saved in .fast-downward-path, or else in fd_config.json."""
    if FAST_DOWNWARD_CONFIG.is_file():
        saved = FAST_DOWNWARD_CONFIG.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    if FAST_DOWNWARD_JSON_CONFIG.is_file():
        try:
            saved = str(json.loads(FAST_DOWNWARD_JSON_CONFIG.read_text(encoding="utf-8")).get("fast_downward_dir", "")).strip()
        except (json.JSONDecodeError, OSError, AttributeError):
            saved = ""
        if saved:
            return saved
    return None


def find_fast_downward() -> Optional[Path]:
    """Return the first usable fast-downward.py among the bundled copy and common folders."""
    for folder in [FAST_DOWNWARD_DIR, *_FD_CANDIDATES]:
        script = folder / "fast-downward.py"
        ok, _ = validate_fast_downward_installation(script)
        if ok:
            return script
    return None


def resolve_fast_downward_script(explicit_path: Optional[str] = None) -> Path:
    """Choose Fast Downward: CLI path, FAST_DOWNWARD_PATH / FAST_DOWNWARD_DIR,
    .fast-downward-path / fd_config.json, then the bundled copy or common folders.

    An explicit path, the environment variable, or a saved path is always
    returned as-is (even if broken) so the user sees an error about the path
    they chose. Only when nothing is configured are the bundled copy and the
    common folders searched.
    """
    if explicit_path:
        return _normalize_fast_downward_path(explicit_path)

    environment_path = os.environ.get(FAST_DOWNWARD_ENV_VAR) or os.environ.get(FAST_DOWNWARD_DIR_ENV_VAR)
    if environment_path:
        return _normalize_fast_downward_path(environment_path)

    saved_path = _saved_path()
    if saved_path:
        return _normalize_fast_downward_path(saved_path)

    return find_fast_downward() or FAST_DOWNWARD_SCRIPT


def resolve_fast_downward_dir() -> Path:
    """Folder form of resolve_fast_downward_script() (kept for older callers)."""
    return resolve_fast_downward_script().parent


def fast_downward_status(explicit_path: Optional[str] = None) -> Dict[str, object]:
    """Summarize which Fast Downward will be used and whether it works (for the UI and check_setup)."""
    script = resolve_fast_downward_script(explicit_path)
    ok, message = validate_fast_downward_installation(script)
    if explicit_path:
        source = "given"
    elif os.environ.get(FAST_DOWNWARD_ENV_VAR):
        source = f"{FAST_DOWNWARD_ENV_VAR} environment variable"
    elif os.environ.get(FAST_DOWNWARD_DIR_ENV_VAR):
        source = f"{FAST_DOWNWARD_DIR_ENV_VAR} environment variable"
    elif FAST_DOWNWARD_CONFIG.is_file() and FAST_DOWNWARD_CONFIG.read_text(encoding="utf-8").strip():
        source = ".fast-downward-path"
    elif _saved_path():
        source = "fd_config.json"
    else:
        source = "automatic"
    return {"ok": ok, "message": message, "script": str(script), "source": source}


def save_fast_downward_path(value: str) -> Dict[str, object]:
    """Validate a folder or fast-downward.py path and save it to .fast-downward-path if it works."""
    script = _normalize_fast_downward_path(value)
    ok, message = validate_fast_downward_installation(script)
    if ok:
        FAST_DOWNWARD_CONFIG.write_text(str(script), encoding="utf-8")
    return {"ok": ok, "message": message, "script": str(script), "saved": ok}


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------

def parse_plan(plan_path: str) -> List[PlanAction]:                          # Reads a plan file and returns its actions as PlanAction objects.
    """
    Parse a sas_plan file into a list of PlanAction objects.

    Each line looks like: (drive truck1 l3 l2 t0 t1)
    Comment lines starting with ';' are ignored.
    """
    return parse_plan_text(Path(plan_path).read_text(encoding='utf-8'))


def parse_plan_text(text: str) -> List[PlanAction]:
    """Parse plan text (used for files and for browser uploads)."""
    actions = []
    for line_number, line in enumerate(text.splitlines(), start=1):          # Keeps line numbers for useful errors.
        line = line.split(';', 1)[0].strip()                                 # Removes Fast Downward comments and surrounding whitespace.
        if not line:
            continue
        if not (line.startswith('(') and line.endswith(')')):               # Rejects malformed input instead of silently treating it as an action.
            raise ValueError(
                f"Invalid plan syntax on line {line_number}: {line}"
            )
        inner = line[1:-1].strip()                                           # Removes exactly one pair of surrounding parentheses.
        tokens = inner.split()
        if not tokens:
            raise ValueError(f"Empty action on line {line_number}.")
        actions.append(PlanAction(name=tokens[0].lower(), args=tokens[1:]))  # Fast Downward writes lowercase; lowering makes hand-written plans match too.
    return actions


# ---------------------------------------------------------------------------
# Fast Downward invocation
# ---------------------------------------------------------------------------

def run_fast_downward(                                                       # Launches Fast Downward and retrieves a usable plan.
    domain_path: str,
    problem_path: str,
    search: str = "eager_greedy([ff()])",
    timeout: int = 120,
    plan_file: Optional[str] = None,                                         # Where to write the plan; defaults to .planner-output/sas_plan.
    fast_downward_script: Optional[str] = None,                              # Optional one-run override of the Fast Downward location.
) -> Optional[List[PlanAction]]:
    """
    Run Fast Downward on the given domain and problem files.

    Returns:
        List of PlanAction objects if a plan was found, None otherwise.
    """
    python_exe = sys.executable or "python"

    # Resolve all paths to absolute (FD runs with a different cwd)
    domain_abs = str(Path(domain_path).resolve())
    problem_abs = str(Path(problem_path).resolve())
    selected_script = resolve_fast_downward_script(fast_downward_script)
    selected_dir = selected_script.parent

    PLANNER_OUTPUT_DIR.mkdir(exist_ok=True)
    plan_abs = str(Path(plan_file).resolve()) if plan_file else str(PLANNER_OUTPUT_DIR / "sas_plan")
    Path(plan_abs).parent.mkdir(parents=True, exist_ok=True)

    # A plan left over from an earlier run must never be mistaken for this run's result.
    try:
        Path(plan_abs).unlink()
    except FileNotFoundError:
        pass

    installation_ok, installation_message = validate_fast_downward_installation(selected_script)
    if not installation_ok:
        print(f"  [Planner] {installation_message}")
        if os.name != "nt":
            print("  [Planner] Run: python3 configure_fast_downward.py /path/to/fast-downward.py")
        return None

    cmd = [
        python_exe,
        str(selected_script),
        "--plan-file", plan_abs,
        domain_abs,
        problem_abs,
        "--search", search,
    ]

    print(f"  [Planner] Running Fast Downward...")
    print(f"  [Planner] Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PLANNER_OUTPUT_DIR),                                     # Translator scratch files (output.sas) land here, not in the Fast Downward folder.
        )

        # Fast Downward exit codes: 0 = solution found, 12 = unsolvable, other = error
        if result.returncode == 0:
            if Path(plan_abs).exists():
                actions = parse_plan(plan_abs)
                print(f"  [Planner] Plan found with {len(actions)} actions.")
                return actions
            print(f"  [Planner] Plan file not found at {plan_abs}")
            return None

        # Check if a plan was still generated despite a non-zero exit
        if Path(plan_abs).exists():
            actions = parse_plan(plan_abs)
            if actions:
                print(f"  [Planner] Plan found with {len(actions)} actions (exit code {result.returncode}).")
                return actions

        if result.returncode == 12:
            print("  [Planner] Fast Downward proved the problem unsolvable (exit code 12).")
        else:
            print(f"  [Planner] Fast Downward failed (exit code {result.returncode}).")
        output = (result.stderr or "").strip() or (result.stdout or "").strip()
        for line in output.split('\n')[-5:]:                                 # The last lines normally hold the failure details.
            if line.strip():
                print(f"  [Planner] {line}")
        return None

    except subprocess.TimeoutExpired:
        print(f"  [Planner] Fast Downward timed out after {timeout}s.")
        return None
    except FileNotFoundError as e:
        print(f"  [Planner] Could not find Fast Downward: {e}")
        return None


def cleanup_planner_files():                                                 # Removes temporary and output files left by Fast Downward.
    """Remove transient Fast Downward files from the project's planner output folder."""
    for fname in ["output.sas", "output", "sas_plan"]:
        fpath = PLANNER_OUTPUT_DIR / fname
        if fpath.exists():
            try:
                fpath.unlink()
            except OSError:
                pass
