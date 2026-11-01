import unittest

from liverecall.semantic_queue import (
    DROPPED,
    OVERFLOW,
    QUEUED,
    FifoQueue,
    SemanticQueue,
)
from tests.helpers import cap


class SemanticQueueTest(unittest.TestCase):
    def setUp(self):
        self.q = SemanticQueue(max_segments=8)

    def test_all_revisions_kept_while_not_collapsed(self):
        for rev in (1, 2, 3):
            self.assertEqual(self.q.offer(cap(1, rev, final=rev == 3)), QUEUED)
        self.assertEqual([self.q.pop().revision for _ in range(3)], [1, 2, 3])

    def test_collapse_keeps_newest_revision_per_segment(self):
        self.q.offer(cap(1, 1))
        self.q.offer(cap(1, 2))
        self.q.offer(cap(2, 1))
        self.assertEqual(self.q.collapse(), 1)
        self.assertEqual(len(self.q), 2)
        self.assertEqual([self.q.pop().key, self.q.pop().key], [(1, 2), (2, 1)])
        self.assertEqual(self.q.coalesced, 1)

    def test_final_supersedes_provisionals_on_collapse(self):
        self.q.offer(cap(1, 1))
        self.q.offer(cap(1, 3, final=True))
        self.q.collapse()
        self.assertEqual(self.q.finals_pending, 1)
        self.assertTrue(self.q.pop().final)
        self.assertEqual(self.q.finals_pending, 0)

    def test_nothing_replaces_pending_final(self):
        self.q.offer(cap(1, 3, final=True))
        self.assertEqual(self.q.offer(cap(1, 4)), DROPPED)
        self.assertEqual(self.q.offer(cap(1, 2)), DROPPED)
        self.assertEqual(self.q.pop().key, (1, 3))

    def test_per_segment_revisions_are_bounded(self):
        q = SemanticQueue(max_revisions=3)
        for rev in range(1, 11):
            q.offer(cap(1, rev))
        self.assertEqual(len(q), 3)
        self.assertEqual([q.pop().revision for _ in range(3)], [8, 9, 10])

    def test_order_is_preserved_across_segments(self):
        self.q.offer(cap(1, 1))
        self.q.offer(cap(2, 1))
        self.q.offer(cap(1, 2, final=True))
        self.assertEqual([self.q.pop().key for _ in range(3)], [(1, 1), (1, 2), (2, 1)])

    def test_delivered_captions_are_never_sent_again(self):
        self.q.mark_delivered(cap(5, 3, final=True))   # e.g. sent in HISTORY
        self.assertEqual(self.q.offer(cap(5, 3, final=True)), DROPPED)
        self.assertEqual(self.q.offer(cap(5, 2)), DROPPED)
        self.assertEqual(len(self.q), 0)

    def test_pop_finals_batches_in_segment_order(self):
        for seg in (3, 1, 2):
            self.q.offer(cap(seg, 2, final=True))
        self.q.offer(cap(4, 1))
        self.q.offer(cap(5, 1))
        self.q.offer(cap(5, 2, final=True))   # provisional 5/1 is superseded
        finals = self.q.pop_finals()
        self.assertEqual([c.segment for c in finals], [1, 2, 3, 5])
        self.assertEqual(len(self.q), 1)
        self.assertEqual(self.q.finals_pending, 0)

    def test_queue_is_bounded(self):
        for seg in range(1, 9):
            self.assertEqual(self.q.offer(cap(seg, 1, final=True)), QUEUED)
        self.assertEqual(self.q.offer(cap(9, 1, final=True)), OVERFLOW)
        self.assertEqual(len(self.q), 8)

    def test_oldest_wait_survives_coalescing(self):
        self.q.offer(cap(1, 1), now=10.0)
        self.q.offer(cap(1, 2), now=10.6)
        self.q.collapse()
        self.assertAlmostEqual(self.q.oldest_wait(11.0), 1.0)


class FifoQueueTest(unittest.TestCase):
    def test_baseline_keeps_every_revision(self):
        q = FifoQueue()
        for rev in (1, 2, 3):
            q.offer(cap(1, rev, final=rev == 3))
        self.assertEqual([q.pop().revision for _ in range(3)], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
