"""Periodic server statistics for the demo and load tests."""

from __future__ import annotations

import asyncio
import logging
import os

from .hub import LiveRecallHub

log = logging.getLogger("liverecall.stats")


def rss_mb() -> float | None:
    """Resident memory of this process in MiB (Linux only)."""
    try:
        with open("/proc/self/statm", encoding="ascii") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except (OSError, ValueError, AttributeError):
        return None


def snapshot(hub: LiveRecallHub) -> dict[str, float]:
    channels = hub.channels()
    live = {
        "frames_sent": sum(ch.frames_sent for ch in channels),
        "batches_sent": sum(ch.batches_sent for ch in channels),
        "coalesced": sum(ch.queue.coalesced for ch in channels),
        "congestion_events": sum(ch.flow.congestion_events for ch in channels),
    }
    finals = active = 0
    for session in hub.sessions.values():
        state = session.state.snapshot()
        finals += state["finals_retained"]
        active += state["active_segments"]
    pending = [ch.pending for ch in channels]
    result = {
        "clients": len(channels),
        "congested": sum(ch.congested for ch in channels),
        "pending": sum(pending),
        "max_pending": max(pending, default=0),
        "finals": finals,
        "active": active,
        "frames": hub.totals["frames_sent"] + live["frames_sent"],
        "batches": hub.totals["batches_sent"] + live["batches_sent"],
        "coalesced": hub.totals["coalesced"] + live["coalesced"],
        "congestion": hub.totals["congestion_events"] + live["congestion_events"],
    }
    rss = rss_mb()
    if rss is not None:
        result["rss_mb"] = round(rss, 1)
    return result


async def report_forever(hub: LiveRecallHub, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        snap = snapshot(hub)
        log.info("stats " + " ".join(f"{k}={v}" for k, v in snap.items()))
