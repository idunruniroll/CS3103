#!/usr/bin/env python3
"""LiveRecall's WebSocket server.

Start it with ``python solution_server.py --port 8765``. Environment variables
can set the policy, lag threshold, statistics interval, and compression mode.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from websockets.asyncio.server import serve

from liverecall.client_channel import POLICIES
from liverecall.flow_control import FlowConfig
from liverecall.hub import LiveRecallHub, ServerConfig
from liverecall.stats import report_forever


def raise_fd_limit() -> None:
    """Allow more simultaneous clients than the common 1024 fd soft limit."""
    try:
        import resource
    except ImportError:  # not available on Windows
        return
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft != resource.RLIM_INFINITY and (hard == resource.RLIM_INFINITY or soft < hard):
        target = 65536 if hard == resource.RLIM_INFINITY else hard
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
        except (ValueError, OSError):
            pass


def build_parser() -> argparse.ArgumentParser:
    env = os.environ.get
    p = argparse.ArgumentParser(description="LiveRecall caption server")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--policy", choices=POLICIES,
                   default=env("LIVERECALL_POLICY", "adaptive"),
                   help="overload policy (adaptive is the submitted design)")
    p.add_argument("--retention", type=float, default=90.0,
                   help="seconds of finalized captions kept for recovery")
    p.add_argument("--max-pending", type=int, default=256,
                   help="per-client pending segments before forcing a resync")
    p.add_argument("--lag-threshold", type=float,
                   default=float(env("LIVERECALL_LAG_THRESHOLD", "0.3")),
                   help="extra ping delay (s) that marks a client as lagging")
    p.add_argument("--slow-interval", type=float, default=0.5,
                   help="seconds between frames for a congested client")
    p.add_argument("--compression", choices=("deflate", "none"),
                   default=env("LIVERECALL_COMPRESSION", "deflate"))
    p.add_argument("--stats-interval", type=float,
                   default=float(env("LIVERECALL_STATS_INTERVAL", "10")),
                   help="seconds between stats log lines (0 disables)")
    p.add_argument("--verbose", action="store_true",
                   help="log every client connect/disconnect")
    return p


async def main_async(args: argparse.Namespace) -> None:
    config = ServerConfig(
        policy=args.policy,
        retention_seconds=args.retention,
        max_pending=args.max_pending,
        flow=FlowConfig(
            adaptive=args.policy == "adaptive",
            lag_threshold=args.lag_threshold,
            slow_interval=args.slow_interval,
        ),
    )
    hub = LiveRecallHub(config)
    async with serve(
        hub.handler,
        args.host,
        args.port,
        max_size=2**20,
        ping_interval=20,
        ping_timeout=30,
        compression=None if args.compression == "none" else "deflate",
    ):
        logging.getLogger("liverecall").info(
            "LiveRecall listening on ws://%s:%d (policy=%s, compression=%s)",
            args.host, args.port, args.policy, args.compression)
        stats_task = None
        if args.stats_interval > 0:
            stats_task = asyncio.create_task(report_forever(hub, args.stats_interval))
        try:
            await asyncio.Future()
        finally:
            if stats_task is not None:
                stats_task.cancel()


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    # Keep normal connection handshakes out of the application log.
    logging.getLogger("websockets").setLevel(logging.WARNING)
    raise_fd_limit()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
