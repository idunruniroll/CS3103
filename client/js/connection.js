/*
 * LiveConnection: WebSocket lifecycle with automatic reconnect and resume.
 *
 *  - On every (re)connect sends CLIENT_HELLO with the store's resume cursor
 *    (latest FINALIZED segment/revision held), so the server's HISTORY reply
 *    contains only finals we genuinely missed.
 *  - Reconnects automatically with capped exponential back-off plus jitter,
 *    so a classroom of browsers does not reconnect in lock-step after a
 *    server/network blip.
 *  - Reports state changes ("connecting", "connected", "reconnecting",
 *    "offline") so the UI can show them.
 *  - simulateOutage(ms) closes the socket and suppresses reconnects for a
 *    while; used to demonstrate disconnect -> reconnect -> recovery.
 */
(function (LR) {
  "use strict";

  const BASE_DELAY_MS = 250;
  const MAX_DELAY_MS = 5000;

  class LiveConnection {
    constructor(options) {
      this.url = options.url;
      this.session = options.session ?? "L1";
      this.clientId = options.clientId;
      this.historySeconds = options.historySeconds ?? 60;
      this.getCursor = options.getCursor;
      this.onMessage = options.onMessage;
      this.onStatus = options.onStatus ?? (() => {});

      this.ws = null;
      this.attempt = 0;
      this.connections = 0;
      this.timer = null;
      this.pausedUntil = 0;
      this.stopped = false;

      window.addEventListener("online", () => this.reconnectNow());
      window.addEventListener("offline", () => this.onStatus("offline", {}));
    }

    start() {
      this.stopped = false;
      this.open();
    }

    open() {
      clearTimeout(this.timer);
      this.timer = null;
      this.onStatus(this.connections ? "reconnecting" : "connecting", { attempt: this.attempt });

      let ws;
      try {
        ws = new WebSocket(this.url);
      } catch (err) {
        this.scheduleReconnect();
        return;
      }
      this.ws = ws;

      ws.addEventListener("open", () => {
        if (ws !== this.ws) return;
        const cursor = this.getCursor();
        ws.send(JSON.stringify({
          type: "CLIENT_HELLO",
          client_id: this.clientId,
          session: this.session,
          last_segment: cursor.segment,
          last_revision: cursor.revision,
          history_seconds: this.historySeconds,
        }));
        this.attempt = 0;
        this.connections++;
        this.onStatus("connected", { reconnect: this.connections > 1, cursor });
      });

      ws.addEventListener("message", (event) => {
        if (ws !== this.ws) return;
        let msg;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return; // ignore malformed frames
        }
        this.onMessage(msg);
      });

      ws.addEventListener("close", () => {
        if (ws !== this.ws) return;
        this.ws = null;
        this.scheduleReconnect();
      });
      // "error" is always followed by "close"; reconnect is handled there.
    }

    scheduleReconnect() {
      if (this.stopped || this.timer) return;
      const backoff = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** this.attempt);
      const jitter = Math.random() * backoff * 0.3;
      const waitForOutage = Math.max(0, this.pausedUntil - Date.now());
      const delay = Math.max(backoff + jitter, waitForOutage);
      this.attempt++;
      this.onStatus("reconnecting", { attempt: this.attempt, inMs: delay });
      this.timer = setTimeout(() => {
        this.timer = null;
        this.open();
      }, delay);
    }

    reconnectNow() {
      if (this.stopped || Date.now() < this.pausedUntil) return;
      if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;
      this.attempt = 0;
      this.open();
    }

    simulateOutage(ms) {
      this.pausedUntil = Date.now() + ms;
      if (this.ws) {
        const ws = this.ws;
        this.ws = null;
        ws.close(4000, "simulated outage");
      }
      clearTimeout(this.timer);
      this.timer = null;
      this.scheduleReconnect();
    }
  }

  LR.LiveConnection = LiveConnection;
})(window.LiveRecall = window.LiveRecall || {});
