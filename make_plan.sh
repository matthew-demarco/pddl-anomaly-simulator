#!/bin/sh
set -e
cd "$(dirname "$0")"
PROBLEM="$1"
FD="$(cat .fast-downward-path)"

python3 "$FD" \
  --plan-file "plans/${PROBLEM}.plan" \
  fast-downward-24.06.1/trucks/domain.pddl \
  "fast-downward-24.06.1/trucks/${PROBLEM}.pddl" \
  --search "eager_greedy([ff()])"

echo "Saved plans/${PROBLEM}.plan"