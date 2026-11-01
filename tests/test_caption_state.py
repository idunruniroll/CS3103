import unittest

from liverecall.caption_state import ACCEPTED, FINALIZED, STALE, CaptionState
from tests.helpers import FakeClock, cap


class RevisionOrderingTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.state = CaptionState(clock=self.clock)

    def test_newer_revisions_are_accepted_in_order(self):
        self.assertEqual(self.state.apply(cap(1, 1)), ACCEPTED)
        self.assertEqual(self.state.apply(cap(1, 2)), ACCEPTED)
        self.assertEqual(self.state.apply(cap(1, 3, final=True)), ACCEPTED)

    def test_older_and_duplicate_revisions_are_rejected(self):
        self.state.apply(cap(1, 2))
        self.assertEqual(self.state.apply(cap(1, 1)), STALE)
        self.assertEqual(self.state.apply(cap(1, 2)), STALE)

    def test_nothing_overwrites_a_final(self):
        self.state.apply(cap(1, 3, final=True))
        self.assertEqual(self.state.apply(cap(1, 2)), FINALIZED)
        self.assertEqual(self.state.apply(cap(1, 4)), FINALIZED)
        self.assertEqual(self.state.apply(cap(1, 3, final=True)), FINALIZED)
        self.assertTrue(self.state.is_final(1))

    def test_revision_count_is_not_assumed(self):
        for rev in range(1, 8):
            self.assertEqual(self.state.apply(cap(5, rev)), ACCEPTED)
        self.assertEqual(self.state.apply(cap(5, 8, final=True)), ACCEPTED)

    def test_active_captions_report_latest_provisional(self):
        self.state.apply(cap(7, 1))
        self.state.apply(cap(7, 2))
        self.assertEqual([c.key for c in self.state.active_captions()], [(7, 2)])
        self.state.apply(cap(7, 3, final=True))
        self.assertEqual(self.state.active_captions(), [])


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.state = CaptionState(retention_seconds=90, clock=self.clock)
        # One final per second for segments 1..80.
        for seg in range(1, 81):
            self.state.apply(cap(seg, 1))
            self.state.apply(cap(seg, 2, final=True))
            self.clock.advance(1.0)

    def test_late_join_gets_requested_window_oldest_first(self):
        items = self.state.history_since(0, 0, 30)
        segs = [c.segment for c in items]
        self.assertEqual(segs, sorted(segs))
        self.assertEqual(segs[-1], 80)
        self.assertEqual(len(segs), 30)
        self.assertTrue(all(c.final for c in items))

    def test_resume_excludes_finals_the_client_already_has(self):
        items = self.state.history_since(75, 2, 60)
        self.assertEqual([c.segment for c in items], [76, 77, 78, 79, 80])

    def test_up_to_date_client_gets_nothing(self):
        self.assertEqual(self.state.history_since(80, 2, 60), [])

    def test_history_is_bounded_by_time(self):
        self.clock.advance(200)
        self.state.apply(cap(81, 1, final=True))
        self.assertEqual([c.segment for c in self.state.history_since(0, 0, 60)], [81])
        self.assertEqual(self.state.snapshot()["finals_retained"], 1)
        # Evicted segments are still known to be final.
        self.assertEqual(self.state.apply(cap(10, 9)), FINALIZED)

    def test_history_is_bounded_by_count(self):
        clock = FakeClock()
        state = CaptionState(max_finals=10, clock=clock)
        for seg in range(1, 51):
            state.apply(cap(seg, 1, final=True))
        self.assertEqual(state.snapshot()["finals_retained"], 10)
        self.assertEqual(state.history_since(0, 0, 60)[0].segment, 41)

    def test_abandoned_provisional_segments_are_bounded(self):
        state = CaptionState(max_active=4, clock=FakeClock())
        for seg in range(1, 20):
            state.apply(cap(seg, 1))
        self.assertEqual(len(state.active_captions()), 4)


if __name__ == "__main__":
    unittest.main()
