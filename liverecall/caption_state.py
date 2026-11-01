"""Authoritative caption state for one session.

Responsibilities
----------------
* Revision ordering: a revision is accepted only if it is newer than the
  latest accepted revision of the same segment. Older/duplicate revisions are
  rejected, so they can never reach a client.
* Final durability: once a segment is final, every later update for that
  segment is rejected (an older revision can never overwrite a final).
* Bounded history: finalized captions are kept for ``retention_seconds``
  (default 90 s, i.e. the 60 s recovery requirement plus slack) and at most
  ``max_finals`` entries. Nothing grows with lecture length.
* Recovery queries: ``history_since`` answers CLIENT_HELLO resume/late-join
  requests from the bounded window.

Retention is measured with the server's own monotonic clock at the time a
final is accepted, so it does not depend on the source's wall clock.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

from .protocol import Caption

ACCEPTED = "accepted"
STALE = "stale"            # older than or equal to an accepted revision
FINALIZED = "finalized"    # segment already final (or already evicted)


class CaptionState:
    def __init__(
        self,
        retention_seconds: float = 90.0,
        max_finals: int = 4096,
        max_active: int = 64,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.retention_seconds = retention_seconds
        self.max_finals = max_finals
        self.max_active = max_active
        self._clock = clock

        # (accepted_at, caption) in arrival order.
        self._finals: deque[tuple[float, Caption]] = deque()
        # segment -> final revision, for every final still in the window.
        self._final_rev: dict[int, int] = {}
        # Highest segment evicted from the window. Updates for segments at or
        # below this floor are treated as already finalized.
        self._evicted_floor = 0
        # segment -> latest provisional revision (segments not yet final).
        self._active: dict[int, tuple[float, Caption]] = {}

        self.counters = {ACCEPTED: 0, STALE: 0, FINALIZED: 0}

    # ------------------------------------------------------------------ apply
    def apply(self, caption: Caption) -> str:
        """Apply one source update and return ACCEPTED, STALE or FINALIZED."""
        now = self._clock()
        self._prune(now)
        seg = caption.segment

        if seg in self._final_rev or seg <= self._evicted_floor:
            return self._count(FINALIZED)

        current = self._active.get(seg)
        if current is not None and caption.revision <= current[1].revision:
            return self._count(STALE)

        if caption.final:
            self._active.pop(seg, None)
            self._finals.append((now, caption))
            self._final_rev[seg] = caption.revision
            self._prune(now)
        else:
            self._active[seg] = (now, caption)
            if len(self._active) > self.max_active:
                # Abandoned provisional segments (source never finalized them)
                # must not accumulate: drop the oldest segment.
                del self._active[min(self._active)]
        return self._count(ACCEPTED)

    def _count(self, verdict: str) -> str:
        self.counters[verdict] += 1
        return verdict

    def _prune(self, now: float) -> None:
        cutoff = now - self.retention_seconds
        finals = self._finals
        while finals and (finals[0][0] < cutoff or len(finals) > self.max_finals):
            _, old = finals.popleft()
            if self._final_rev.get(old.segment) == old.revision:
                del self._final_rev[old.segment]
            if old.segment > self._evicted_floor:
                self._evicted_floor = old.segment
        if self._active:
            stale = [seg for seg, (t, _) in self._active.items() if t < cutoff]
            for seg in stale:
                del self._active[seg]

    # ---------------------------------------------------------------- queries
    def history_since(self, last_segment: int, last_revision: int,
                      seconds: float) -> list[Caption]:
        """Finalized captions newer than the client's cursor, oldest first.

        Only finals accepted within the last ``seconds`` are returned, and
        never a final the client already reported via its cursor.
        """
        now = self._clock()
        self._prune(now)
        cutoff = now - seconds
        cursor = (last_segment, last_revision)
        items = [
            c for (t, c) in self._finals
            if t >= cutoff and (c.segment, c.revision) > cursor
        ]
        items.sort(key=lambda c: c.segment)
        return items

    def active_captions(self) -> list[Caption]:
        """Latest provisional revision of every unfinished segment."""
        return [c for _, (_, c) in sorted(self._active.items())]

    def is_final(self, segment: int) -> bool:
        return segment in self._final_rev or segment <= self._evicted_floor

    def snapshot(self) -> dict[str, int]:
        return {
            "finals_retained": len(self._finals),
            "active_segments": len(self._active),
            **self.counters,
        }
