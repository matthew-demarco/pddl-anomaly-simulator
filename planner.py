"""
Fast Downward Planner Integration.

Invokes Fast Downward to solve a PDDL problem and parses the resulting plan.
"""                                                                         # Explains that this module runs Fast Downward and converts the resulting plan into simulator actions.

import json                                                                    # Imports JSON utilities so the Fast Downward path can be read from an optional config file.
import os                                                                    # Imports operating-system utilities for environment-variable access.
import re                                                                    # Imports regular-expression utilities; this import is present in the original file but is not currently used.
import subprocess                                                            # Allows the simulator to launch Fast Downward as an external command-line process.
import sys                                                                   # Provides access to the Python interpreter currently running the simulator.
from pathlib import Path                                                     # Provides platform-independent tools for constructing, resolving, reading, checking, and deleting file paths.
from typing import List, Optional                                            # Imports type hints for lists and values that may be None.

from state import PlanAction                                                 # Imports the class that stores one grounded planner action and its ordered arguments.


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Directory containing this file (the project root)
_THIS_DIR = Path(__file__).resolve().parent                                  # Finds the absolute directory containing planner.py so paths do not depend on where the terminal was opened.

# Fallback: the repo bundles the Fast Downward *driver* only (no planner engine).
# A real Fast Downward installation is resolved in this order:
#   1. The FAST_DOWNWARD_DIR environment variable
#   2. fd_config.json in the project root ("fast_downward_dir" key)
#   3. Common local paths (./fast-downward, ~/FastDownward/downward, C:\fast-downward\downward, ...)
#   4. The bundled fast-downward-24.06.1 folder (last resort)
FAST_DOWNWARD_DIR = _THIS_DIR / "fast-downward-24.06.1"                      # Uses the bundled driver-only copy as the final fallback location.

_FD_CANDIDATES = [                                                           # Lists common Fast Downward installation locations to probe automatically.
    _THIS_DIR / "fast-downward",
    _THIS_DIR / "downward",
    Path.home() / "FastDownward" / "downward",
    Path.home() / "downward",
    Path.home() / "fast-downward",
    Path("C:/fast-downward/downward"),
    Path("C:/fast-downward"),
    Path("C:/FastDownward/downward"),
    Path("C:/FastDownward"),
    Path("C:/downward"),
    FAST_DOWNWARD_DIR,
]


def _looks_like_fast_downward(path: Path) -> bool:                            # Defines a helper that checks whether a directory contains a usable Fast Downward.
    """Return True when the directory holds fast-downward.py plus the translator."""
    return (path / "fast-downward.py").exists() and (path / "src" / "translate").is_dir()  # Checks for the launcher script and the Python translator component.


# Folders never worth descending into while searching for Fast Downward.
_SEARCH_SKIP = {                                                              # Lists directory names that are skipped during the disk search.
    "appdata", "node_modules", ".git", "__pycache__", "windows", "program files",
    "program files (x86)", "programdata", "$recycle.bin", "site-packages",
    "venv", ".venv", "ms-playwright", "musictmp", "pictures", "music", "videos",
    "onedrivetemp", "android", "docker", "scoop", "nuget", "cache",
}


def search_fast_downward(max_seconds: float = 25.0) -> Path:                  # Defines a bounded disk search for a Fast Downward installation.
    """Search common user folders for Fast Downward; return its directory or None."""
    import time                                                              # Imports the clock used to bound the search duration.
    home = Path.home()                                                       # Starts from the user profile folder.
    roots = [                                                                 # Collects the search roots with a depth budget for each.
        (home, 6),                                                           # Covers the user profile (Desktop, Documents, Downloads, OneDrive).
        (_THIS_DIR.parent, 5),                                                # Covers the folder that contains this project.
        (Path("C:/"), 2),                                                     # Only a shallow look at the drive root.
    ]
    deadline = time.time() + max_seconds                                     # Computes the time at which the search gives up.
    for root, max_depth in roots:                                            # Loops through each search root.
        if not root.exists():                                                # Skips roots that do not exist on this machine.
            continue
        stack = [(root, 0)]                                                   # Uses an explicit stack so huge trees cannot recurse deeply.
        while stack:                                                          # Keeps walking until the stack is empty.
            if time.time() > deadline:                                        # Stops the whole search once the time budget is spent.
                return None
            folder, depth = stack.pop()                                       # Takes the next folder to examine.
            try:                                                             # Guards against permission errors on locked folders.
                with os.scandir(folder) as entries:                          # Lists the folder contents without loading them all at once.
                    for entry in entries:                                     # Examines each entry in turn.
                        if entry.is_dir(follow_symlinks=False):               # Handles subdirectories.
                            if entry.name.lower() in _SEARCH_SKIP:            # Skips directories that are never worth searching.
                                continue
                            if depth < max_depth:                             # Only descends while the depth budget allows.
                                stack.append((Path(entry.path), depth + 1))    # Queues the subdirectory for a later pass.
                        elif entry.name == "fast-downward.py":                 # Handles the launcher script that marks an installation.
                            if _looks_like_fast_downward(folder):             # Confirms the folder also holds the translator.
                                return folder                                 # Returns the Fast Downward directory that was found.
            except (PermissionError, OSError):                                # Ignores folders that cannot be read.
                continue
    return None                                                              # Reports that no installation was found.


def resolve_fast_downward_dir() -> Path:                                     # Defines the function that decides which Fast Downward installation to use.
    """Resolve the Fast Downward directory.

    Order: FAST_DOWNWARD_DIR env var, fd_config.json, common paths,
    then the bundled driver-only folder as a last resort.
    """
    env_dir = os.environ.get("FAST_DOWNWARD_DIR", "").strip()                # Reads the FAST_DOWNWARD_DIR environment variable if the user set one.

    if env_dir:
        env_path = Path(env_dir).expanduser()                                 # Expands a leading ~ in the environment-variable path.

        if _looks_like_fast_downward(env_path):
            return env_path                                                    # Uses the environment-variable location when it is valid.

        raise FileNotFoundError(                                               # Raises a clear error when the environment variable points somewhere invalid.
            f"FAST_DOWNWARD_DIR is set to '{env_dir}' but no fast-downward.py + "
            f"src/translate was found there. Fix the variable or unset it."
        )

    config_file = _THIS_DIR / "fd_config.json"                               # Builds the path of the optional project configuration file.

    if config_file.exists():                                                 # Checks whether the user created a config file.
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))      # Reads and parses the JSON configuration file.
            cfg_dir = str(config.get("fast_downward_dir", "")).strip()        # Gets the configured Fast Downward directory, if any.

            if cfg_dir:
                cfg_path = Path(cfg_dir).expanduser()                          # Expands a leading ~ in the configured path.

                if _looks_like_fast_downward(cfg_path):
                    return cfg_path                                            # Uses the configured location when it is valid.

                raise FileNotFoundError(                                       # Raises a clear error when the configured path is invalid.
                    f"fd_config.json points at '{cfg_dir}' but no fast-downward.py + "
                    f"src/translate was found there. Fix the config file or delete it."
                )
        except json.JSONDecodeError:
            pass                                                               # Ignores a malformed config file and falls through to auto-detection.

    for candidate in _FD_CANDIDATES:                                         # Loops through each common installation location.
        if _looks_like_fast_downward(candidate):
            return candidate                                                   # Uses the first valid installation that is found.

    return FAST_DOWNWARD_DIR                                                  # Falls back to the bundled driver-only copy, which will fail with instructions.


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------

def parse_plan(plan_path: str) -> List[PlanAction]:                          # Defines a function that reads a sas_plan file and returns its actions as PlanAction objects.
    """
    Parse a sas_plan file into a list of PlanAction objects.

    Each line looks like: (drive truck1 l3 l2 t0 t1)
    Comment lines starting with ';' are ignored.
    """                                                                      # Documents the expected Fast Downward plan format and explains which lines are ignored.
    actions = []                                                             # Creates an empty list that will hold the parsed actions in their original execution order.
    text = Path(plan_path).read_text(encoding='utf-8')                       # Reads the complete plan file as UTF-8 text.
    for line in text.strip().split('\n'):                                   # Removes outer whitespace, separates the file into lines, and examines each line in order.
        line = line.strip()                                                  # Removes leading and trailing whitespace from the current plan line.
        if not line or line.startswith(';'):                                # Checks whether the line is empty or is a Fast Downward comment or summary line.
            continue                                                        # Skips the current line because it does not represent an executable plan action.
        # Remove surrounding parens
        inner = line.strip('()')                                             # Removes the outer parentheses from a grounded action line.
        tokens = inner.split()                                               # Separates the action name and all of its arguments into individual strings.
        if tokens:                                                          # Confirms that the line produced at least one token before creating an action.
            actions.append(PlanAction(name=tokens[0], args=tokens[1:]))      # Stores the first token as the action name and the remaining tokens as its ordered arguments.
    return actions                                                          # Returns the complete ordered list of parsed PlanAction objects to the simulator.


# ---------------------------------------------------------------------------
# Fast Downward invocation
# ---------------------------------------------------------------------------

def run_fast_downward(                                                       # Defines the main function that launches Fast Downward and retrieves a usable plan.
    domain_path: str,                                                        # Receives the path to the PDDL domain file containing the available actions and predicates.
    problem_path: str,                                                       # Receives the path to the PDDL problem file containing the current state, objects, and goals.
    search: str = "eager_greedy([ff()])",                                   # Uses eager greedy search with the FF heuristic unless another Fast Downward search string is supplied.
    timeout: int = 120,                                                      # Limits the planner to 120 seconds by default so it cannot block the simulator indefinitely.
    plan_file: Optional[str] = None,                                         # Allows a caller to provide a custom plan-output path or use the default sas_plan location.
) -> Optional[List[PlanAction]]:                                             # Returns a list of PlanAction objects when a plan is available or None when planning fails.
    """
    Run Fast Downward on the given domain and problem files.

    Args:
        domain_path: Path to the domain PDDL file.
        problem_path: Path to the problem PDDL file.
        search: Search algorithm string for Fast Downward.
        timeout: Maximum time in seconds.
        plan_file: Optional explicit path for the plan output file.

    Returns:
        List of PlanAction objects if a plan was found, None otherwise.
    """                                                                      # Documents the planner inputs, configurable settings, and possible return values.
    # Find the Python interpreter
    python_exe = sys.executable or "python"                                  # Uses the same Python interpreter running the simulator and falls back to the command "python" if necessary.

    # Resolve all paths to absolute (FD runs with a different cwd)
    fd_dir = resolve_fast_downward_dir()                                    # Chooses the Fast Downward installation to use.
    fd_script = fd_dir / "fast-downward.py"                                  # Creates the full path to the Python script used to start Fast Downward.

    if not _looks_like_fast_downward(fd_dir):                               # Checks whether the resolved directory actually contains a working planner.
        print("  [Planner] ERROR: no usable Fast Downward installation was found.")  # Reports that planning cannot proceed without the engine.
        print("  [Planner] Fix this by doing ONE of the following:")        # Begins listing the supported solutions.
        print("    1. Set the FAST_DOWNWARD_DIR environment variable to your Fast Downward folder")  # Describes the environment-variable option.
        print("       (the folder that contains fast-downward.py and src/translate).")  # Clarifies which folder is expected.
        print("    2. Create fd_config.json next to planner.py containing:")  # Describes the config-file option.
        print("       {\"fast_downward_dir\": \"C:\\path\\to\\your\\fast-downward\"}")  # Shows the exact JSON format to use.
        print("    3. Place Fast Downward in one of these folders:")          # Describes the auto-detected locations.

        for candidate in _FD_CANDIDATES[:-1]:                                # Lists every auto-detection candidate except the bundled fallback.
            print(f"       {candidate}")                                     # Prints one candidate location per line.

        return None                                                          # Signals that planning could not be started.

    domain_abs = str(Path(domain_path).resolve())                            # Converts the domain-file path to an absolute path because Fast Downward runs from another working directory.
    problem_abs = str(Path(problem_path).resolve())                          # Converts the problem-file path to an absolute path so it remains valid after the working directory changes.

    # Planner outputs live in a project-owned folder so the user's Fast Downward
    # installation is never touched by cleanup.
    output_dir = _THIS_DIR / ".planner-output"                              # Builds the project-local planner output directory.
    output_dir.mkdir(exist_ok=True)                                         # Creates the output directory when it does not exist yet.
    plan_abs = str(Path(plan_file).resolve()) if plan_file else str(output_dir / "sas_plan")  # Uses the requested output path when provided or the project-local default otherwise.

    # Build the command
    cmd = [                                                                  # Begins the ordered list of command-line arguments that will be passed to subprocess.
        python_exe,                                                          # Specifies the Python interpreter that will execute Fast Downward.
        str(fd_script),                                                      # Specifies the fast-downward.py script that performs translation and search.
        "--plan-file", plan_abs,                                             # Tells Fast Downward where to write the generated plan.
        domain_abs,                                                          # Supplies the absolute path to the PDDL domain file.
        problem_abs,                                                         # Supplies the absolute path to the PDDL problem file.
        "--search", search,                                                  # Supplies the selected search algorithm and heuristic configuration.
    ]

    print(f"  [Planner] Running Fast Downward...")                           # Prints a status message showing that a planning or replanning run has started.
    print(f"  [Planner] Command: {' '.join(cmd)}")                           # Prints the exact command for debugging and manual reproduction.

    try:                                                                     # Starts protected execution so expected planner errors do not crash the entire simulator.
        result = subprocess.run(                                             # Launches Fast Downward as a separate process and waits for it to finish.
            cmd,                                                             # Passes the complete Fast Downward command and all of its arguments.
            capture_output=True,                                             # Captures standard output and standard error instead of printing them automatically.
            text=True,                                                       # Returns captured output as normal Python strings rather than bytes.
            timeout=timeout,                                                 # Stops waiting and raises TimeoutExpired if the planner exceeds the allowed time.
            cwd=str(fd_dir),                                                 # Runs Fast Downward from its own directory so its relative internal paths work correctly.
        )

        # Fast Downward exit codes:
        # 0  = solution found
        # 12 = no solution (unsolvable)
        # Other = error
        if result.returncode in (0,):                                        # Checks whether Fast Downward returned the normal success exit code.
            if Path(plan_abs).exists():                                      # Verifies that the expected plan file was actually created.
                actions = parse_plan(plan_abs)                               # Converts the generated sas_plan file into an ordered list of PlanAction objects.
                print(f"  [Planner] Plan found with {len(actions)} actions.")  # Reports how many actions were found in the completed plan.
                return actions                                               # Returns the parsed plan so the simulator can execute it.
            else:                                                           # Handles a success code that did not produce the expected plan file.
                print(f"  [Planner] Plan file not found at {plan_abs}")      # Reports the exact missing output location to help diagnose the issue.
                return None                                                  # Signals that no usable plan is available.
        else:                                                               # Handles unsolvable problems and all other nonzero planner exit codes.
            # Check if a plan was still generated despite non-zero exit
            if Path(plan_abs).exists():                                      # Checks whether Fast Downward still created a plan file despite returning a nonzero code.
                actions = parse_plan(plan_abs)                               # Attempts to parse any plan file that was produced.
                if actions:                                                  # Confirms that the parsed file contains at least one executable action.
                    print(f"  [Planner] Plan found with {len(actions)} actions (exit code {result.returncode}).")  # Reports the recovered plan and preserves the nonzero exit code for debugging.
                    return actions                                           # Returns the usable recovered plan to the simulator.

            print(f"  [Planner] Fast Downward failed (exit code {result.returncode}).")  # Reports that Fast Downward did not produce a usable plan.
            if result.stderr:                                                # Checks whether Fast Downward provided detailed error output.
                # Only print last few lines of stderr
                err_lines = result.stderr.strip().split('\n')              # Removes outer whitespace and separates the captured error message into individual lines.
                for line in err_lines[-5:]:                                 # Selects only the last five lines, which normally contain the most relevant failure details.
                    print(f"  [Planner] {line}")                             # Prints each selected error line with a planner label.
            return None                                                      # Signals that no usable plan was produced.

    except subprocess.TimeoutExpired:                                        # Handles the exception raised when Fast Downward runs longer than the configured timeout.
        print(f"  [Planner] Fast Downward timed out after {timeout}s.")      # Reports the number of seconds allowed before the planner was stopped.
        return None                                                          # Signals that planning did not finish successfully.
    except FileNotFoundError as e:                                           # Handles missing executables, scripts, directories, or other required paths.
        print(f"  [Planner] Could not find Fast Downward: {e}")              # Prints the exact missing-file error returned by the operating system.
        return None                                                          # Signals that Fast Downward could not be started.


def cleanup_planner_files():                                                 # Defines a helper that removes temporary and output files left by Fast Downward.
    """Remove transient Fast Downward artifacts.

    The plan file lives in the project-owned .planner-output folder. Fast
    Downward also drops regenerable translate outputs (output.sas, output)
    in its own working directory during a run; those are removed too so the
    user's installation is left as it was found.
    """
    output_dir = _THIS_DIR / ".planner-output"                              # Targets the project-owned planner output directory.

    for fname in ["output.sas", "output", "sas_plan"]:                       # Loops through the standard intermediate, output, and plan filenames created by Fast Downward.
        fpath = output_dir / fname                                           # Builds the complete path to the current temporary file.

        if fpath.exists():                                                   # Checks whether the file exists before trying to delete it.
            try:                                                             # Protects the simulator from file-system errors during nonessential cleanup.
                fpath.unlink()                                               # Deletes the temporary or generated planner file.
            except OSError:                                                  # Handles permission errors, file locks, and other operating-system deletion failures.
                pass                                                         # Ignores cleanup failures because they should not stop the simulator.

    try:
        fd_dir = resolve_fast_downward_dir()                                # Chooses the Fast Downward installation that was used.
    except FileNotFoundError:
        return                                                               # Leaves everything alone when no installation can be resolved.

    if not _looks_like_fast_downward(fd_dir):
        return                                                               # Skips folders without a full engine, which contain no artifacts.

    for fname in ["output.sas", "output"]:                                  # Loops through FD's regenerable translate outputs in its own folder.
        fpath = fd_dir / fname                                               # Builds the path inside the Fast Downward directory.

        if fpath.exists():                                                   # Checks whether the file exists before trying to delete it.
            try:                                                             # Protects the simulator from file-system errors during nonessential cleanup.
                fpath.unlink()                                               # Deletes the regenerable translate output.
            except OSError:                                                  # Handles permission errors, file locks, and other operating-system deletion failures.
                pass                                                         # Ignores cleanup failures because they should not stop the simulator.
