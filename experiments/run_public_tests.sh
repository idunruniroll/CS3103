#!/usr/bin/env bash
# Run the mandatory public tests T1-T4 (3 independent runs each, median
# reported by run_demo.py). Results: experiments/data/<test>_runNN.{csv,json}
#
#   bash experiments/run_public_tests.sh            # all of T1..T4
#   bash experiments/run_public_tests.sh t3 t4      # a subset
#   RUNS=1 bash experiments/run_public_tests.sh t1  # quick check
#   LIVERECALL_POLICY=fifo OUT_PREFIX=fifo_ bash experiments/run_public_tests.sh t3
set -euo pipefail
cd "$(dirname "$0")/.."

RUNS="${RUNS:-3}"
OUT="experiments/data"
PREFIX="${OUT_PREFIX:-}"
mkdir -p "$OUT"
PY="${PYTHON:-python3}"

run() {
  local name="$1"; shift
  echo "=== ${PREFIX}${name} (policy=${LIVERECALL_POLICY:-adaptive}) ==="
  "$PY" run_demo.py --runs "$RUNS" --quiet-server \
      --output-stem "$OUT/${PREFIX}${name}" "$@" | tee "$OUT/${PREFIX}${name}.log"
}

tests=("$@")
[ ${#tests[@]} -eq 0 ] && tests=(t1 t2 t3 t4)

for t in "${tests[@]}"; do
  case "$t" in
    t1) run t1 --clients 20 --duration 20 ;;
    t2) run t2 --clients 100 --duration 40 ;;
    t3) run t3 --clients 100 --duration 60 --slow-percent 10 --slow-ms 500 ;;
    t4) run t4 --clients 100 --duration 60 \
              --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5 ;;
    *) echo "unknown test $t" >&2; exit 2 ;;
  esac
done

"$PY" experiments/summarise.py "$OUT"
