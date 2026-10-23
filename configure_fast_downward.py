"""Save a one-time Fast Downward path for macOS/Linux replanning."""

import argparse

from planner import (
    FAST_DOWNWARD_CONFIG,
    resolve_fast_downward_script,
    validate_fast_downward_installation,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Configure the Fast Downward checkout used for replanning."
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="Path to fast-downward.py or the directory containing it",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show the currently selected Fast Downward installation",
    )
    args = parser.parse_args()

    if args.show:
        selected = resolve_fast_downward_script()
        valid, message = validate_fast_downward_installation(selected)
        print(f"Selected path: {selected}")
        print(message)
        return 0 if valid else 1

    if not args.path:
        parser.error("provide a Fast Downward path or use --show")

    selected = resolve_fast_downward_script(args.path)
    valid, message = validate_fast_downward_installation(selected)
    if not valid:
        print(f"ERROR: {message}")
        return 1

    FAST_DOWNWARD_CONFIG.write_text(str(selected) + "\n", encoding="utf-8")
    print(message)
    print(f"Saved configuration in: {FAST_DOWNWARD_CONFIG}")
    print("You can now run main.py without --fast-downward.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
