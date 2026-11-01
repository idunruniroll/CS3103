#!/usr/bin/env bash
# Required before/after comparison: same workload, three server policies.
#
#   fifo      naive per-client FIFO, every revision queued (the "before")
#   coalesce  coalescing only when send() blocks, no lag detection
#   adaptive  submitted design (lag detection + drain + paced batches)
#
# Default workload is T3 (slow readers). With WITH_BANDWIDTH=1 the 2 Mbit/s
# tc profile (Ubuntu + sudo) is also compared.
set -euo pipefail
cd "$(dirname "$0")/.."
RUNS="${RUNS:-3}"
PY="${PYTHON:-python3}"
OUT="experiments/data"
mkdir -p "$OUT"

for policy in fifo coalesce adaptive; do
  echo "=== T3 slow readers, policy=$policy ==="
  LIVERECALL_POLICY="$policy" "$PY" run_demo.py --runs "$RUNS" --quiet-server \
      --clients 100 --duration 60 --slow-percent 10 --slow-ms 500 \
      --output-stem "$OUT/cmp_t3_${policy}" | tee "$OUT/cmp_t3_${policy}.log"
done

if [ "${WITH_BANDWIDTH:-0}" = 1 ]; then
  trap 'sudo bash ./network_profiles/reset.sh lo >/dev/null || true' EXIT INT TERM
  for policy in fifo coalesce adaptive; do
    echo "=== 2 Mbit/s bottleneck, policy=$policy ==="
    sudo bash ./network_profiles/bandwidth_2mbit.sh lo
    LIVERECALL_POLICY="$policy" "$PY" run_demo.py --runs "$RUNS" --quiet-server \
        --clients 100 --duration 40 \
        --output-stem "$OUT/cmp_bw_${policy}" | tee "$OUT/cmp_bw_${policy}.log"
    sudo bash ./network_profiles/reset.sh lo
  done
fi

"$PY" experiments/summarise.py "$OUT"
