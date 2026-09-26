#!/usr/bin/env bash
# Regenerates every number and figure in results/SUMMARY.md.
# N=1000 (default) takes ~45 min on 4 cores; N=200 is a smoke run.
# W sets the number of worker processes (default: all cores but one).
# PAIRS limits the factor swaps to the comparisons the notes discuss
# (both directions each); set PAIRS="" to run every pair in the family.
set -euo pipefail
cd "$(dirname "$0")/.."
N=${N:-1000}
OUT=${OUT:-results}
W=${W:-$(python -c "import os; print(max(1, (os.cpu_count() or 1) - 1))")}
PAIRS=${PAIRS-hostomel_2022:maleme_1941,hostomel_2022:ypenburg_1940,maleme_1941:heraklion_1941,maleme_1941:rethymno_1941,maleme_1941:ypenburg_1940,ypenburg_1940:valkenburg_1940}

battlelab lint scenarios/*.yaml
python -m pytest -q
battlelab report scenarios/*.yaml -n "$N" -w "$W" --out "$OUT" \
    --sweep hostomel_2022 --go-pair hostomel_2022,maleme_1941 ${PAIRS:+--pairs "$PAIRS"}
