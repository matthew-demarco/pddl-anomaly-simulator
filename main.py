```python
"""
Trucks Domain — Anomaly Replanning Simulator
=============================================

Main entry point. Simulates truck plan execution with random anomaly
injection and automated replanning via Case-Based Reasoning.

Usage:
    python main.py --problem p01 [--anomaly-chance 0.2] [--seed 42] [--verbose]
    python main.py --list          # List available problems
    python main.py --help
"""                                                                 # Module docstring explaining the purpose of main.py and showing example terminal commands.


import argparse                                                       # Imports tools for reading command-line arguments such as --problem and --seed.
import sys                                                            # Imports system tools; this file uses sys.exit() to end the program with a success or failure code.
from pathlib import Path                                              # Imports Path for creating and working with file and folder paths.

from simulator import Simulator                                       # Imports the Simulator class so main.py can create and run a simulation.


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent                         # Finds the absolute path of the folder containing this main.py file.
TRUCKS_DIR = PROJECT_DIR / "fast-downward-24.06.1" / "trucks"        # Builds the path to the folder containing the trucks PDDL domain and problem files.
DOMAIN_FILE = TRUCKS_DIR / "domain.pddl"                              # Builds the complete path to the trucks PDDL domain file.


def get_problem_path(problem_id: str) -> Path:                        # Defines a function that converts a problem ID such as "1" or "p01" into a complete PDDL file path.
    """Resolve a problem ID like 'p01' or '1' to a full path."""       # Docstring explaining the purpose of get_problem_path().

    # Accept 'p01', 'p1', '1', '01', etc.
    problem_id = problem_id.strip().lower()                           # Removes spaces from the beginning and end and converts the problem ID to lowercase.

    if not problem_id.startswith('p'):                               # Checks whether the supplied problem ID does not already begin with the letter "p".

        # Pad with leading zero if single digit
        try:                                                         # Attempts to convert the supplied problem ID into an integer.
            num = int(problem_id)                                    # Converts values such as "1" or "01" into the integer 1.
            problem_id = f"p{num:02d}"                               # Formats the number with the letter p and at least two digits, so 1 becomes "p01".
        except ValueError:                                           # Runs if the problem ID cannot be converted into an integer.
            pass                                                     # Leaves the problem ID unchanged and allows later file validation to handle it.

    filename = f"{problem_id}.pddl"                                  # Creates the expected problem filename, such as "p01.pddl".
    path = TRUCKS_DIR / filename                                     # Combines the trucks folder and problem filename into a complete Path object.
    return path                                                      # Returns the completed problem-file path to the code that called this function.


def list_problems():                                                 # Defines a function that finds and displays all available trucks problem files.
    """List all available truck problem files."""                    # Docstring explaining the purpose of list_problems().

    problems = sorted(TRUCKS_DIR.glob("p*.pddl"))                    # Finds every .pddl file beginning with "p" in the trucks folder and sorts them by name.
    print(f"\nAvailable problems in {TRUCKS_DIR}:\n")                 # Prints the trucks directory and a heading for the problem list.

    for p in problems:                                               # Loops through each available problem Path one at a time.

        # Quick peek at object counts
        text = p.read_text(encoding='utf-8')                         # Reads the current PDDL problem file as UTF-8 text.
        trucks = text.count(" - truck")                              # Counts occurrences of " - truck" to estimate the number of truck object declarations.
        packages = text.count(" - package")                          # Counts occurrences of " - package" to estimate the number of package object declarations.
        locations = text.count(" - location")                        # Counts occurrences of " - location" to estimate the number of location object declarations.
        print(f"  {p.stem:6s}  |  {trucks} truck(s), {packages} packages, {locations} locations")  # Prints the problem name and estimated object counts.

    print(f"\nTotal: {len(problems)} problems")                      # Prints the total number of problem files found.


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():                                                          # Defines the main function that reads user options, validates files, creates the Simulator, and starts the simulation.

    parser = argparse.ArgumentParser(                                 # Creates the command-line argument parser used to understand options entered by the user.
        description="Trucks Domain — Anomaly Replanning Simulator",   # Sets the short description shown when the user runs python main.py --help.
        formatter_class=argparse.RawDescriptionHelpFormatter,         # Preserves the spacing and line breaks in the help text written below.
        epilog="""
Examples:
  python main.py --problem p01                  # Run p01 with default settings
  python main.py --problem p01 --no-anomalies   # Run p01 without anomalies
  python main.py --problem 3 --seed 42          # Run p03 with fixed seed
  python main.py --problem p07 --anomaly-chance 0.5
  python main.py --list                         # List available problems
        """,                                                           # Adds example commands to the bottom of the --help output.
    )

    parser.add_argument(                                               # Adds the command-line option used to select a PDDL problem.
        "--problem", "-p",                                             # Allows the user to write either --problem or the shorter -p.
        type=str,                                                      # Requires the supplied problem ID to be treated as a string.
        help="Problem ID (e.g., 'p01', '1', '03')",                    # Describes this option in the --help output.
    )

    parser.add_argument(                                               # Adds the command-line option controlling the random anomaly probability.
        "--anomaly-chance", "-a",                                      # Allows either --anomaly-chance or the shorter -a.
        type=float,                                                    # Converts the supplied value into a decimal number.
        default=0.2,                                                   # Uses a 20% anomaly probability when the user does not provide a value.
        help="Probability of anomaly per drive action (0.0-1.0, default: 0.2)",  # Describes the accepted range and default value.
    )

    parser.add_argument(                                               # Adds the command-line option for setting the random-number seed.
        "--seed", "-s",                                                # Allows either --seed or the shorter -s.
        type=int,                                                      # Converts the supplied seed into an integer.
        default=None,                                                  # Uses no specific seed when the user does not provide one.
        help="Random seed for reproducibility",                        # Explains that a seed can help repeat the same random behavior.
    )

    parser.add_argument(                                               # Adds a flag that disables random anomalies.
        "--no-anomalies",                                              # Defines the command-line spelling of the flag.
        action="store_true",                                           # Sets args.no_anomalies to True when the flag appears and False otherwise.
        help="Run without any anomalies (clean execution)",            # Describes the flag in the --help output.
    )

    parser.add_argument(                                               # Adds the option controlling the maximum number of random anomalies.
        "--max-anomalies",                                             # Defines the command-line spelling of the option.
        type=int,                                                      # Converts the supplied maximum into an integer.
        default=5,                                                     # Allows at most five anomalies when the user does not provide another value.
        help="Maximum number of anomalies per run (default: 5)",       # Describes the option and its default value.
    )

    parser.add_argument(                                               # Adds a flag intended to enable detailed state output.
        "--verbose", "-v",                                             # Allows either --verbose or the shorter -v.
        action="store_true",                                           # Sets args.verbose to True when the flag is present.
        default=True,                                                  # Makes args.verbose True even when the flag is not supplied.
        help="Show detailed state after each action (default: True)",  # Explains that detailed state output is enabled by default.
    )

    parser.add_argument(                                               # Adds a flag that suppresses detailed simulator output.
        "--quiet", "-q",                                               # Allows either --quiet or the shorter -q.
        action="store_true",                                           # Sets args.quiet to True when this flag is supplied.
        help="Suppress verbose output",                                # Describes the quiet flag in the --help output.
    )

    parser.add_argument(                                               # Adds a flag for listing problem files instead of running a simulation.
        "--list", "-l",                                                # Allows either --list or the shorter -l.
        action="store_true",                                           # Sets args.list to True when the user includes this flag.
        help="List available problem files",                           # Describes the flag in the --help output.
    )

    parser.add_argument(                                               # Adds the option for changing the Fast Downward search strategy.
        "--search",                                                    # Defines the command-line spelling of the option.
        type=str,                                                      # Treats the supplied search configuration as text.
        default="eager_greedy([ff()])",                                # Uses eager greedy search with the FF heuristic by default.
        help="Fast Downward search strategy (e.g., eager_greedy([ff()]), astar(blind()))",  # Provides example Fast Downward search configurations.
    )

    parser.add_argument(                                               # Adds the option for exporting each simulation state to a folder.
        "--export-states",                                             # Defines the command-line spelling of the option.
        type=str,                                                      # Treats the supplied directory path as text.
        default=None,                                                  # Disables state exporting when no directory is provided.
        help="Directory to save the state of each problem step (e.g. 'state_history')",  # Explains what the supplied directory will contain.
    )

    parser.add_argument(                                               # Adds a flag for printing state information as JSON for the graphical interface.
        "--json-output",                                               # Defines the command-line spelling of the flag.
        action="store_true",                                           # Sets args.json_output to True when the flag is supplied.
        help="Emit JSON state dynamically for UI parsing",             # Explains that the JSON output can be read by the user interface.
    )

    args = parser.parse_args()                                        # Reads the actual command-line input and stores the resulting values inside args.

    if args.list:                                                      # Checks whether the user requested the list of available problems.
        list_problems()                                                # Calls list_problems() to print the available problem files.
        return                                                         # Ends main() without creating or running a Simulator.

    if not args.problem:                                               # Checks whether the user failed to provide the required --problem option.
        parser.print_help()                                            # Prints the complete command-line help information.
        print("\nError: --problem is required (e.g., --problem p01)")  # Prints a specific message explaining which option is missing.
        sys.exit(1)                                                    # Ends the program with exit code 1, indicating an error.

    # Resolve paths
    problem_path = get_problem_path(args.problem)                      # Converts the user's problem ID into the complete expected PDDL problem path.

    if not problem_path.exists():                                     # Checks whether the selected PDDL problem file actually exists.
        print(f"Error: Problem file not found: {problem_path}")        # Prints the missing file's expected location.
        sys.exit(1)                                                    # Ends the program with an error exit code.

    if not DOMAIN_FILE.exists():                                      # Checks whether the trucks PDDL domain file exists.
        print(f"Error: Domain file not found: {DOMAIN_FILE}")          # Prints the missing domain file's expected location.
        sys.exit(1)                                                    # Ends the program with an error exit code.

    # Configure
    anomaly_chance = 0.0 if args.no_anomalies else args.anomaly_chance  # Uses 0% anomaly probability when --no-anomalies is supplied; otherwise uses the selected probability.
    verbose = not args.quiet                                           # Enables detailed output unless the user supplied --quiet.

    # Run simulation
    sim = Simulator(                                                   # Creates a Simulator object and automatically runs Simulator.__init__().
        domain_path=str(DOMAIN_FILE),                                  # Passes the PDDL domain file path to the Simulator as a string.
        problem_path=str(problem_path),                                # Passes the selected PDDL problem file path to the Simulator as a string.
        anomaly_chance=anomaly_chance,                                 # Passes the configured random anomaly probability.
        seed=args.seed,                                                # Passes the optional random-number seed.
        verbose=verbose,                                               # Passes whether detailed output should be displayed.
        max_anomalies=args.max_anomalies,                              # Passes the maximum number of random anomalies allowed.
        search=args.search,                                            # Passes the selected Fast Downward search strategy.
        export_states_dir=args.export_states,                          # Passes the optional folder where state-history PDDL files should be saved.
        json_output=args.json_output,                                  # Passes whether JSON state output should be generated for the GUI.
    )

    result = sim.run()                                                 # Calls the Simulator's run() method and stores the returned SimulationResult.

    # Exit code
    sys.exit(0 if result.success else 1)                               # Ends with code 0 when the simulation succeeded or code 1 when it failed.


if __name__ == "__main__":                                             # Checks whether this file was run directly instead of imported by another Python file.
    main()                                                             # Calls main() only when main.py is executed directly.
```
