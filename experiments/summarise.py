#!/usr/bin/env python3
"""Summarise result JSON files into a Markdown table (median of runs).

run_demo.py writes <stem>_runNN.json per run. This groups runs by stem and
prints the median of each metric, ready to paste into the report.

    python experiments/summarise.py experiments/data
    python experiments/summarise.py experiments/data --output experiments/data/SUMMARY.md
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

COLUMNS = [
    ("Runs", None, "{:d}"),
    ("P50 ms", "p50_ms", "{:.1f}"),
    ("P95 ms", "p95_ms", "{:.1f}"),
    ("P99 ms", "p99_ms", "{:.1f}"),
    ("Fresh %", "fresh_pct", "{:.2f}"),
    ("Fresh final %", "fresh_final_pct", "{:.2f}"),
    ("Final compl. %", "final_completeness_pct", "{:.2f}"),
    ("Coverage %", "normal_update_coverage_pct", "{:.2f}"),
    ("Normal P95 ms", "normal_clients.p95_ms", "{:.1f}"),
    ("Slow P50 ms", "slow_clients.p50_ms", "{:.1f}"),
    ("Slow P95 ms", "slow_clients.p95_ms", "{:.1f}"),
    ("Recovery P95 ms", "recovery_p95_ms", "{:.1f}"),
    ("Dup", "duplicates", "{:.0f}"),
    ("Stale", "stale", "{:.0f}"),
]


def get(d, path):
    for key in path.split("."):
        if not isinstance(d, dict) or key not in d:
            return None
        d = d[key]
    return d


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("directory", nargs="?", default="experiments/data")
    p.add_argument("--output")
    args = p.parse_args()

    groups: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(Path(args.directory).glob("*.json")):
        stem = re.sub(r"_run\d+$", "", path.stem)
        try:
            groups[stem].append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue

    header = "| Test | " + " | ".join(c[0] for c in COLUMNS) + " |"
    lines = [header, "|" + "---|" * (len(COLUMNS) + 1)]
    for stem, runs in groups.items():
        cells = []
        for label, key, fmt in COLUMNS:
            if key is None:
                cells.append(fmt.format(len(runs)))
                continue
            vals = [get(r, key) for r in runs]
            vals = [float(v) for v in vals if v is not None and not math.isnan(float(v))]
            cells.append(fmt.format(statistics.median(vals)) if vals else "–")
        lines.append(f"| {stem} | " + " | ".join(cells) + " |")

    table = "\n".join(lines)
    print(table)
    if args.output:
        Path(args.output).write_text(table + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
