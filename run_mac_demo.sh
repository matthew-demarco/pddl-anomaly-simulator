#!/bin/sh
set -e
cd "$(dirname "$0")"

python3 check_setup.py
python3 main.py --problem p01 --plan plans/p01.plan \
  --anomaly-id 1 --step-id 2 --anomaly-args l1 l3
