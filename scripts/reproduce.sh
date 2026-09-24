#!/usr/bin/env bash
# Regenerates every number and figure in results/SUMMARY.md.
# Runtime on one CPU core: ~25 min at the default N. Use N=200 for a smoke run.
# Add -w <cores> to the swap/sweep lines on a multi-core machine.
set -euo pipefail
cd "$(dirname "$0")/.."
N=${N:-1000}
OUT=${OUT:-results}
H=scenarios/hostomel_2022.yaml
M=scenarios/maleme_1941.yaml

battlelab lint "$H" "$M"
pytest -q

# 1. Is history typical inside the model? (both combat resolvers)
for S in "$H" "$M"; do
  battlelab anchors "$S" -n $((N * 2)) --out "$OUT"
  battlelab anchors "$S" -n $((N * 2)) --resolver crt --out "$OUT"
done

# 2. Which parameters does the record constrain? Which drive the outcome?
battlelab calibrate "$M" -n $((N * 6)) | tee "$OUT/calibrate_maleme_1941.txt"
battlelab screen "$H" -n $((N * 4)) --out "$OUT"
battlelab screen "$M" -n $((N * 4)) --out "$OUT"

# 3. Cross-battle factor swaps + Shapley (both directions, both resolvers)
battlelab swap "$H" "$M" --both -n "$N" --out "$OUT"
battlelab swap "$H" "$M" --both -n $((N * 2 / 5)) --resolver crt --out "$OUT"

# 4. Counterfactual surface: Russian risk tolerance vs Ukrainian fires timing
battlelab sweep "$H" --grid risk.tolerance=0:0.4:9 --grid denial.t_fires=1:12:12 \
    -n $((N * 3 / 10)) --out "$OUT"
