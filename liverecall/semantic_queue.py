"""Per-client pending-caption queues.

``SemanticQueue`` is the queue used by the real server. Pending captions are
grouped by segment, in segment order:

* While the client keeps up (NORMAL mode) every revision is kept, so a burst
  of revisions that arrives faster than one event-loop turn is still
  delivered in full (normal update coverage).
* ``collapse()`` keeps only the newest pending revision of each segment
  (semantic coalescing). The channel calls it while the client is
  CONGESTED, so obsolete provisional revisions are never sent to a client
  that cannot keep up.
* A final supersedes every pending provisional of its segment as soon as it
  is collapsed or batched, and nothing ever supersedes a final.

Bounds:
* at most ``max_revisions`` pending revisions per segment: beyond that the
  oldest provisional is coalesced away even in NORMAL mode;
* at most ``max_segments`` segments: beyond that ``offer`` reports OVERFLOW
  and the channel forces a resync (reconnect + HISTORY) instead of growing.

``FifoQueue`` is the naive "queue every revision" design. It is kept only so
experiments can quantify the improvement (``--policy fifo``).
"""

from __future__ import annotations

from collections import OrderedDict, deque

from .protocol import Caption

QUEUED = "queued"
COALESCED = "coalesced"
DROPPED = "dropped"        # stale/duplicate for this client
OVERFLOW = "overflow"


class SemanticQueue:
    def __init__(self, max_segments: int = 256, max_revisions: int = 16,
                 remember_segments: int = 512) -> None:
        self.max_segments = max_segments
        self.max_revisions = max_revisions
        # segment -> pending revisions of that segment, oldest first.
        self._pending: dict[int, list[Caption]] = {}
        # segment -> time its oldest pending revision was queued. Kept across
        # coalescing: it says how long the student has been waiting.
        self._since: dict[int, float] = {}
        self._size = 0
        self._finals_pending = 0
        # segment -> highest revision already delivered to this client. Used
        # so a caption that was sent in HISTORY is never sent again live.
        self._delivered: OrderedDict[int, int] = OrderedDict()
        self._remember = remember_segments
        self.coalesced = 0

    def __len__(self) -> int:
        return self._size

    @property
    def finals_pending(self) -> int:
        return self._finals_pending

    @property
    def segments_pending(self) -> int:
        return len(self._pending)

    # ------------------------------------------------------------ producer
    def offer(self, caption: Caption, now: float = 0.0) -> str:
        seg = caption.segment
        if self._delivered.get(seg, 0) >= caption.revision:
            return DROPPED
        revs = self._pending.get(seg)
        if revs is None:
            if len(self._pending) >= self.max_segments:
                return OVERFLOW
            self._pending[seg] = [caption]
            self._since[seg] = now
        else:
            newest = revs[-1]
            if newest.final or caption.revision <= newest.revision:
                return DROPPED
            revs.append(caption)
            if len(revs) > self.max_revisions:
                del revs[0]
                self._size -= 1
                self.coalesced += 1
        self._size += 1
        if caption.final:
            self._finals_pending += 1
        return QUEUED

    # ------------------------------------------------------------ consumer
    def collapse(self) -> int:
        """Keep only the newest pending revision of every segment."""
        dropped = 0
        for revs in self._pending.values():
            if len(revs) > 1:
                dropped += len(revs) - 1
                del revs[:-1]
        self._size -= dropped
        self.coalesced += dropped
        return dropped

    def pop(self) -> Caption:
        """Remove and return the oldest pending revision (segment order)."""
        seg = next(iter(self._pending))
        revs = self._pending[seg]
        caption = revs.pop(0)
        if not revs:
            del self._pending[seg]
            del self._since[seg]
        self._size -= 1
        if caption.final:
            self._finals_pending -= 1
        return caption

    def pop_finals(self) -> list[Caption]:
        """Remove every segment whose final is pending; return the finals.

        Pending provisionals of those segments are superseded by the final.
        """
        finals = []
        for seg, revs in list(self._pending.items()):
            if revs[-1].final:
                finals.append(revs[-1])
                self._size -= len(revs)
                self.coalesced += len(revs) - 1
                del self._pending[seg]
                del self._since[seg]
        self._finals_pending = 0
        finals.sort(key=lambda c: c.segment)
        return finals

    def oldest_wait(self, now: float) -> float:
        """How long the longest-waiting pending caption has waited."""
        if not self._since:
            return 0.0
        return now - min(self._since.values())

    def mark_delivered(self, caption: Caption) -> None:
        seg = caption.segment
        if self._delivered.get(seg, 0) < caption.revision:
            self._delivered[seg] = caption.revision
            self._delivered.move_to_end(seg)
            while len(self._delivered) > self._remember:
                self._delivered.popitem(last=False)


class FifoQueue:
    """Baseline: every accepted revision is queued, nothing is coalesced.

    Unbounded on purpose; used only for before/after experiments.
    """

    def __init__(self) -> None:
        self._items: deque[Caption] = deque()
        self.coalesced = 0

    def __len__(self) -> int:
        return len(self._items)

    @property
    def finals_pending(self) -> int:
        return 0  # never batch in the baseline

    def offer(self, caption: Caption, now: float = 0.0) -> str:
        self._items.append(caption)
        return QUEUED

    def collapse(self) -> int:
        return 0

    def pop(self) -> Caption:
        return self._items.popleft()

    def pop_finals(self) -> list[Caption]:
        return []

    def oldest_wait(self, now: float) -> float:
        return 0.0

    def mark_delivered(self, caption: Caption) -> None:
        pass
