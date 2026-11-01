#!/usr/bin/env bash
# T5 - network impairment on the loopback interface (Ubuntu, needs sudo).
#
# For every profile in network_profiles/ (except reset.sh) this applies the
# qdisc to lo, runs a 100-client test 3 times, and always resets lo
# afterwards (also on Ctrl-C).
#
#   bash experiments/run_netem.sh                    # all profiles
#   bash experiments/run_netem.sh delay_loss         # one profile
#   LIVERECALL_POLICY=fifo OUT_PREFIX=fifo_ bash experiments/run_netem.sh bandwidth_2mbit
set -euo pipefail
cd "$(dirname "$0")/.."

IFACE="${IFACE:-lo}"
RUNS="${RUNS:-3}"
CLIENTS="${CLIENTS:-100}"
DURATION="${DURATION:-40}"
OUT="experiments/data"
PREFIX="${OUT_PREFIX:-}"
PY="${PYTHON:-python3}"
mkdir -p "$OUT"

reset() { sudo bash ./network_profiles/reset.sh "$IFACE" >/dev/null || true; }
trap reset EXIT INT TERM

profiles=("$@")
if [ ${#profiles[@]} -eq 0 ]; then
  for f in network_profiles/*.sh; do
    name="$(basename "$f" .sh)"
    [ "$name" = reset ] || profiles+=("$name")
  done
fi

for profile in "${profiles[@]}"; do
  echo "=== T5 ${profile} (policy=${LIVERECALL_POLICY:-adaptive}) ==="
  reset
  sudo bash "./network_profiles/${profile}.sh" "$IFACE"
  tc qdisc show dev "$IFACE" | tee "$OUT/${PREFIX}t5_${profile}.qdisc"
  "$PY" run_demo.py --clients "$CLIENTS" --duration "$DURATION" --runs "$RUNS" \
      --quiet-server --output-stem "$OUT/${PREFIX}t5_${profile}" \
      | tee "$OUT/${PREFIX}t5_${profile}.log"
  reset
done

"$PY" experiments/summarise.py "$OUT"
