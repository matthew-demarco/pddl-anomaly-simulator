"""
Fast Downward Planner Integration.

Invokes Fast Downward to solve a PDDL problem and parses the resulting plan.
"""                                                                         # Explains that this module runs Fast Downward and converts the resulting plan into simulator actions.

import os                                                                    # Imports operating-system utilities; this import is present in the original file but is not currently used.
import re                                                                    # Imports regular-expression utilities; this import is present in the original file but is not currently used.
import subprocess                                                            # Allows the simulator to launch Fast Downward as an external command-line process.
import sys                                                                   # Provides access to the Python interpreter currently running the simulator.
from pathlib import Path                                                     # Provides platform-independent tools for constructing, resolving, reading, checking, and deleting file paths.
from typing import List, Optional                                            # Imports type hints for lists and values that may be None.

from state import PlanAction                                                 # Imports the class that stores one grounded planner action and its ordered arguments.


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Path to the fast-downward directory (relative to this file's location)
_THIS_DIR = Path(__file__).resolve().parent                                  # Finds the absolute directory containing planner.py so paths do not depend on where the terminal was opened.
FAST_DOWNWARD_DIR = _THIS_DIR / "fast-downward-24.06.1"                     # Creates the path to the Fast Downward installation stored beside the simulator files.
FAST_DOWNWARD_SCRIPT = FAST_DOWNWARD_DIR / "fast-downward.py"               # Creates the full path to the Python script used to start Fast Downward.


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
    domain_abs = str(Path(domain_path).resolve())                            # Converts the domain-file path to an absolute path because Fast Downward runs from another working directory.
    problem_abs = str(Path(problem_path).resolve())                          # Converts the problem-file path to an absolute path so it remains valid after the working directory changes.
    plan_abs = str(Path(plan_file).resolve()) if plan_file else str(FAST_DOWNWARD_DIR / "sas_plan")  # Uses the requested output path when provided or the default sas_plan file inside Fast Downward otherwise.

    # Build the command
    cmd = [                                                                  # Begins the ordered list of command-line arguments that will be passed to subprocess.
        python_exe,                                                          # Specifies the Python interpreter that will execute Fast Downward.
        str(FAST_DOWNWARD_SCRIPT),                                           # Specifies the fast-downward.py script that performs translation and search.
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
            cwd=str(FAST_DOWNWARD_DIR),                                      # Runs Fast Downward from its own directory so its relative internal paths work correctly.
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
    """Remove temporary files left by Fast Downward."""                      # Documents the purpose of the cleanup function.
    for fname in ["output.sas", "output", "sas_plan"]:                       # Loops through the standard intermediate, output, and plan filenames created by Fast Downward.
        fpath = FAST_DOWNWARD_DIR / fname                                    # Builds the complete path to the current temporary file.
        if fpath.exists():                                                   # Checks whether the file exists before trying to delete it.
            try:                                                             # Protects the simulator from file-system errors during nonessential cleanup.
                fpath.unlink()                                               # Deletes the temporary or generated planner file.
            except OSError:                                                  # Handles permission errors, file locks, and other operating-system deletion failures.
                pass                                                         # Ignores cleanup failures because they should not stop the simulator.
