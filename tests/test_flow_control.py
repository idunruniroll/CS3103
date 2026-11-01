import unittest

from liverecall.flow_control import CONGESTED, NORMAL, FlowConfig, FlowController


class FlowControlTest(unittest.TestCase):
    def setUp(self):
        self.cfg = FlowConfig()
        self.t = 0.0
        self.flow = FlowController(self.cfg, self.t)

    def step(self, seconds):
        self.t += seconds
        self.flow.update(self.t)

    def ping_pong(self, rtt):
        self.flow.on_ping_sent(self.t)
        self.t += rtt
        self.flow.on_pong(self.t)

    def make_congested(self):
        self.ping_pong(0.002)
        self.flow.on_ping_sent(self.t)
        self.step(self.cfg.lag_threshold + 0.1)
        self.assertEqual(self.flow.mode, CONGESTED)

    def test_fast_client_stays_normal_and_unpaced(self):
        for _ in range(50):
            self.ping_pong(0.002)
            self.step(0.2)
        self.assertEqual(self.flow.mode, NORMAL)
        self.assertEqual(self.flow.send_delay(self.t), 0.0)

    def test_network_delay_alone_is_not_lag(self):
        # 250 ms base RTT (e.g. netem delay) is learned as the baseline.
        for _ in range(10):
            self.ping_pong(0.25)
        self.flow.on_ping_sent(self.t)
        self.step(0.25 + self.cfg.lag_threshold - 0.05)  # below baseline + threshold
        self.assertEqual(self.flow.mode, NORMAL)

    def test_unanswered_ping_triggers_congested_mode_and_drain(self):
        self.make_congested()
        self.assertTrue(self.flow.draining)
        self.assertGreater(self.flow.send_delay(self.t), 0)

    def test_pong_ends_drain_then_paces(self):
        self.make_congested()
        self.t += 3.0
        self.flow.on_pong(self.t)
        self.assertFalse(self.flow.draining)
        self.assertAlmostEqual(self.flow.send_delay(self.t), self.cfg.slow_interval)
        self.t += self.cfg.slow_interval
        self.assertEqual(self.flow.send_delay(self.t), 0.0)
        self.flow.on_frame_sent(self.t)
        self.assertAlmostEqual(self.flow.send_delay(self.t), self.cfg.slow_interval)

    def test_repeated_lag_backs_off_multiplicatively(self):
        self.make_congested()
        self.t += 1.0
        self.flow.on_pong(self.t)
        self.flow.on_ping_sent(self.t)
        self.step(self.cfg.lag_threshold + 0.1)
        self.assertAlmostEqual(self.flow.interval, 2 * self.cfg.slow_interval)
        self.assertTrue(self.flow.draining)

    def test_brief_stall_returns_to_normal_quickly(self):
        # e.g. one TCP retransmission on a lossy link
        self.make_congested()
        self.t += 0.1
        self.flow.on_pong(self.t)
        stall = self.cfg.lag_threshold + 0.2     # how long the ping was out
        wait = self.flow.probe_wait(stall)
        self.assertLess(wait, 10)
        self.step(wait - 0.2)
        self.assertEqual(self.flow.mode, CONGESTED)
        self.step(0.4)
        self.assertEqual(self.flow.mode, NORMAL)

    def test_long_stall_waits_full_probe_period(self):
        # e.g. a slow reader whose receive buffer took 7 s to drain
        self.make_congested()
        self.t += 7.0
        self.flow.on_pong(self.t)
        self.step(self.cfg.probe_after - 1)
        self.assertEqual(self.flow.mode, CONGESTED)
        self.step(1.5)
        self.assertEqual(self.flow.mode, NORMAL)

    def test_short_restall_keeps_long_probe_wait(self):
        self.make_congested()
        self.t += 7.0
        self.flow.on_pong(self.t)                 # severe stall: 7 s
        self.step(1.0)
        self.flow.on_ping_sent(self.t)
        self.step(self.cfg.lag_threshold + 0.1)   # brief re-lag while paced
        self.t += 0.1
        self.flow.on_pong(self.t)
        self.step(self.cfg.probe_after - 1)
        self.assertEqual(self.flow.mode, CONGESTED)

    def test_failed_probe_doubles_wait_successful_probe_resets_it(self):
        self.make_congested()
        self.t += 7.0
        self.flow.on_pong(self.t)
        self.step(self.cfg.probe_after + 0.1)    # probe starts
        self.assertEqual(self.flow.mode, NORMAL)
        self.flow.on_ping_sent(self.t)
        self.step(self.cfg.lag_threshold + 0.1)  # lag during probe
        self.assertEqual(self.flow.mode, CONGESTED)
        self.assertEqual(self.flow.probe_backoff, 2)

        self.t += 7.0
        self.flow.on_pong(self.t)
        self.step(self.cfg.probe_after + 0.1)
        self.assertEqual(self.flow.mode, CONGESTED)   # still waiting (2x)
        self.step(self.cfg.probe_after)
        self.assertEqual(self.flow.mode, NORMAL)
        self.step(self.cfg.probe_confirm + 0.1)    # and survives
        self.assertEqual(self.flow.probe_backoff, 1)

    def test_silent_peer_does_not_stall_forever(self):
        self.make_congested()
        self.step(self.cfg.drain_timeout + 0.1)
        self.assertFalse(self.flow.draining)
        self.t += self.cfg.slow_interval
        self.assertEqual(self.flow.send_delay(self.t), 0.0)

    def test_large_write_buffer_counts_as_lag(self):
        self.flow.update(self.t, write_backlog=self.cfg.write_buffer_limit + 1)
        self.assertEqual(self.flow.mode, CONGESTED)

    def test_disabled_controller_never_paces(self):
        flow = FlowController(FlowConfig(adaptive=False), 0.0)
        flow.on_ping_sent(0.0)
        flow.update(100.0)
        self.assertEqual(flow.mode, NORMAL)
        self.assertEqual(flow.send_delay(100.0), 0.0)


if __name__ == "__main__":
    unittest.main()
