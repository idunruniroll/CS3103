/*
 * CaptionStore: the browser's local caption state.
 *
 *  - Revision replacement: one entry per segment; a newer revision replaces
 *    the older one, an older/duplicate revision is ignored.
 *  - Final durability: once a segment is final nothing can change it, so a
 *    final can never be shown twice (live + HISTORY, or after reconnect).
 *  - Resume cursor: the latest finalized (segment, revision) held, sent in
 *    CLIENT_HELLO so the server only returns captions we genuinely missed.
 *  - Bounded local history: finals are kept for 90 s (>= the 60 s needed by
 *    "What did I miss?") and at most MAX_SEGMENTS entries.
 *
 * Time base: captions carry source_ts (the source's clock). The browser may
 * run on another machine with a different clock, so we estimate
 * offset = local clock - source clock as the minimum observed
 * (receive time - source_ts); the minimum is the sample with the least
 * network delay. Recall windows are computed on the local clock.
 */
(function (LR) {
  "use strict";

  const HISTORY_MS = 90 * 1000;
  const MAX_SEGMENTS = 1000;

  function isPositiveInt(v) {
    return Number.isInteger(v) && v > 0;
  }

  class CaptionStore {
    constructor(options = {}) {
      this.historyMs = options.historyMs ?? HISTORY_MS;
      this.maxSegments = options.maxSegments ?? MAX_SEGMENTS;
      this.segments = new Map(); // segment -> entry
      this.cursor = { segment: 0, revision: 0 };
      this.prunedFloor = 0; // finals at or below this were pruned locally
      this.clockOffset = null; // seconds, local - source
    }

    /**
     * Apply one CAPTION_UPDATE (live or from HISTORY).
     * Returns { status, entry } where status is one of
     * "new", "updated", "finalized", "duplicate", "stale", "invalid".
     */
    apply(msg, { recovered = false, nowMs = Date.now() } = {}) {
      const seg = msg.segment;
      const rev = msg.revision;
      if (!isPositiveInt(seg) || !isPositiveInt(rev) ||
          typeof msg.text !== "string" || !Number.isFinite(msg.source_ts)) {
        return { status: "invalid" };
      }
      this.observeClock(msg.source_ts, nowMs);

      if (seg <= this.prunedFloor) return { status: "stale" };
      const existing = this.segments.get(seg);
      if (existing) {
        if (existing.final) {
          return { status: rev === existing.revision ? "duplicate" : "stale", entry: existing };
        }
        if (rev < existing.revision) return { status: "stale", entry: existing };
        if (rev === existing.revision) return { status: "duplicate", entry: existing };
      }

      const entry = {
        segment: seg,
        revision: rev,
        final: msg.final === true,
        text: msg.text,
        sourceTs: msg.source_ts,
        receivedAt: nowMs,
        recovered,
      };
      this.segments.set(seg, entry);
      if (entry.final) this.advanceCursor(seg, rev);
      return { status: !existing ? "new" : entry.final ? "finalized" : "updated", entry };
    }

    advanceCursor(seg, rev) {
      const c = this.cursor;
      if (seg > c.segment || (seg === c.segment && rev > c.revision)) {
        this.cursor = { segment: seg, revision: rev };
      }
    }

    observeClock(sourceTs, nowMs) {
      const offset = nowMs / 1000 - sourceTs;
      if (this.clockOffset === null || offset < this.clockOffset) {
        this.clockOffset = offset;
      }
    }

    /** Caption time on the local clock (ms since epoch). */
    localTime(entry) {
      return (entry.sourceTs + (this.clockOffset ?? 0)) * 1000;
    }

    /** All entries ordered by segment (for the live transcript). */
    ordered() {
      return [...this.segments.values()].sort((a, b) => a.segment - b.segment);
    }

    /** Finalized captions from the last `seconds`, oldest first. */
    finalsWithin(seconds, nowMs = Date.now()) {
      const cutoff = nowMs - seconds * 1000;
      return this.ordered().filter(e => e.final && this.localTime(e) >= cutoff);
    }

    /** Drop expired state. Returns the list of removed segment numbers. */
    prune(nowMs = Date.now()) {
      const removed = [];
      const cutoff = nowMs - this.historyMs;
      for (const [seg, entry] of this.segments) {
        if (this.localTime(entry) < cutoff) removed.push(seg);
      }
      if (this.segments.size - removed.length > this.maxSegments) {
        const keep = new Set(removed);
        const extra = this.ordered()
          .filter(e => !keep.has(e.segment))
          .slice(0, this.segments.size - removed.length - this.maxSegments);
        for (const e of extra) removed.push(e.segment);
      }
      for (const seg of removed) {
        const entry = this.segments.get(seg);
        if (entry && entry.final && seg > this.prunedFloor) this.prunedFloor = seg;
        this.segments.delete(seg);
      }
      return removed;
    }
  }

  LR.CaptionStore = CaptionStore;
})(window.LiveRecall = window.LiveRecall || {});
