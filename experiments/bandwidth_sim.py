#!/usr/bin/env python3
"""Constrained-bandwidth experiment that works without Linux tc.

Starts solution_server.py, experiments/bw_proxy.py in front of it, the
supplied load_clients.py (connected through the proxy) and caption_source.py
(connected directly), then analyses the CSV with the supplied
analyse_results.py. Measurement logic is not modified.

    python experiments/bandwidth_sim.py --rate-kbit 400 --policy adaptive
    python experiments/bandwidth_sim.py --rate-kbit 400 --policy fifo

Results (CSV + JSON summary) go to experiments/data/.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analyse_results import analyse_file, print_summary  # noqa: E402


def wait_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise SystemExit(f"nothing listening on {port}")


def stop(proc) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--clients", type=int, default=100)
    p.add_argument("--duration", type=float, default=40)
    p.add_argument("--rate-kbit", type=float, default=400)
    p.add_argument("--policy", default="adaptive", choices=("adaptive", "coalesce", "fifo"))
    p.add_argument("--port", type=int, default=8865)
    p.add_argument("--output-stem", default="experiments/data/bandwidth")
    p.add_argument("--slow-percent", type=float, default=0)
    args = p.parse_args()

    server_port, proxy_port = args.port, args.port + 1
    out_csv = ROOT / f"{args.output_stem}_{args.policy}_{int(args.rate_kbit)}k.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    segments = max(4, math.floor((args.duration - 3.0) / 0.75))
    env = {**os.environ, "LIVERECALL_POLICY": args.policy}

    server = proxy = clients = None
    try:
        server = subprocess.Popen(
            [sys.executable, "-u", "solution_server.py", "--port", str(server_port)],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        wait_port(server_port)
        proxy = subprocess.Popen(
            [sys.executable, "-u", "experiments/bw_proxy.py", "--listen", str(proxy_port),
             "--target", str(server_port), "--rate-kbit", str(args.rate_kbit)],
            cwd=ROOT)
        wait_port(proxy_port)
        clients = subprocess.Popen(
            [sys.executable, "-u", "load_clients.py", "--uri", f"ws://127.0.0.1:{proxy_port}",
             "--clients", str(args.clients), "--duration", str(args.duration),
             "--slow-percent", str(args.slow_percent), "--output", str(out_csv)],
            cwd=ROOT)
        time.sleep(1.0)
        subprocess.run(
            [sys.executable, "-u", "caption_source.py", "--uri", f"ws://127.0.0.1:{server_port}",
             "--segments", str(segments), "--quiet"],
            cwd=ROOT, check=True)
        clients.wait()
    finally:
        stop(clients)
        stop(proxy)
        stop(server)

    summary = analyse_file(out_csv, expected_finals=segments, expected_updates=segments * 3)
    summary["policy"] = args.policy
    summary["rate_kbit"] = args.rate_kbit
    print(f"\npolicy={args.policy} rate={args.rate_kbit} kbit/s")
    print_summary(summary)
    out_csv.with_suffix(".json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
