#!/usr/bin/env bash
# Regenerates every number and figure in results/SUMMARY.md.
# N=1000 (default) takes ~30 min on 4 cores; N=200 is a smoke run.
# W sets the number of worker processes (default: all cores but one).
set -euo pipefail
cd "$(dirname "$0")/.."
N=${N:-1000}
OUT=${OUT:-results}
W=${W:-$(python -c "import os; print(max(1, (os.cpu_count() or 1) - 1))")}

battlelab lint scenarios/*.yaml
python -m pytest -q
battlelab report scenarios/*.yaml -n "$N" -w "$W" --out "$OUT" \
    --sweep hostomel_2022 --go-pair hostomel_2022,maleme_1941
