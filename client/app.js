/*
 * LiveRecall browser client: wires CaptionStore, LiveConnection and
 * RecallPanel to the page.
 *
 * Server address: ws://<page host>:8765 by default. Override with
 *   index.html?server=ws://10.0.0.5:8765   or   index.html?port=9000
 */
(function (LR) {
  "use strict";

  const params = new URLSearchParams(location.search);
  const SESSION = params.get("session") || "L1";
  const HOST = location.hostname || "127.0.0.1";
  const SERVER_URL = params.get("server") || `ws://${HOST}:${params.get("port") || 8765}`;

  const $ = (id) => document.getElementById(id);
  const els = {
    status: $("status"),
    statusText: $("status-text"),
    transcript: $("transcript"),
    jump: $("jump-live"),
    details: $("show-details"),
    toast: $("toast"),
    info: {
      server: $("info-server"),
      last: $("info-last"),
      age: $("info-age"),
      finals: $("info-finals"),
      cursor: $("info-cursor"),
      reconnects: $("info-reconnects"),
    },
  };

  const store = new LR.CaptionStore();
  const recall = new LR.RecallPanel(store, {
    panel: $("recall-panel"),
    list: $("recall-list"),
    summary: $("recall-summary"),
    title: $("recall-title"),
    windowButtons: document.querySelectorAll("#recall-panel [data-window]"),
  });

  const rows = new Map(); // segment -> <li>
  let followLive = true;
  let lastMessageAt = 0;
  let lastAgeMs = null;
  let reconnects = 0;
  let expectingHistory = false; // first HISTORY after (re)connect = recovery
  let isReconnect = false;

  function clientId() {
    const key = "liverecall-client-id";
    let value = sessionStorage.getItem(key);
    if (!value) {
      value = String(Math.floor(100000 + Math.random() * 900000));
      sessionStorage.setItem(key, value);
    }
    return Number(value);
  }

  // ------------------------------------------------------------ rendering
  function rowFor(segment) {
    let li = rows.get(segment);
    if (li) return li;
    li = document.createElement("li");
    li.className = "caption";
    li.dataset.segment = String(segment);
    const meta = document.createElement("span");
    meta.className = "meta";
    const text = document.createElement("span");
    text.className = "text";
    li.append(meta, text);

    // Keep rows ordered by segment. New segments almost always go last.
    const last = els.transcript.lastElementChild;
    if (!last || Number(last.dataset.segment) < segment) {
      els.transcript.appendChild(li);
    } else {
      const next = [...els.transcript.children].find(r => Number(r.dataset.segment) > segment);
      els.transcript.insertBefore(li, next ?? null);
    }
    rows.set(segment, li);
    return li;
  }

  function render(entry, flash) {
    const li = rowFor(entry.segment);
    li.classList.toggle("final", entry.final);
    li.classList.toggle("provisional", !entry.final);
    li.querySelector(".meta").textContent =
      `#${entry.segment} · rev ${entry.revision}${entry.final ? " · final" : ""}`;
    li.querySelector(".text").textContent = entry.text;
    if (flash) {
      li.classList.remove("flash");
      void li.offsetWidth; // restart the animation
      li.classList.add("flash");
    }
  }

  function removeRows(segments) {
    for (const seg of segments) {
      rows.get(seg)?.remove();
      rows.delete(seg);
    }
  }

  function scrollToLive() {
    els.transcript.scrollTop = els.transcript.scrollHeight;
    els.jump.hidden = true;
  }

  function afterRender() {
    if (followLive) scrollToLive();
    else els.jump.hidden = false;
  }

  // ------------------------------------------------------------- messages
  const SHOWN = new Set(["new", "updated", "finalized"]);

  function applyCaption(msg, recovered) {
    const { status, entry } = store.apply(msg, { recovered });
    if (SHOWN.has(status)) render(entry, recovered);
    return status;
  }

  function onMessage(msg) {
    lastMessageAt = Date.now();
    if (msg.type === "CAPTION_UPDATE") {
      const status = applyCaption(msg, false);
      if (SHOWN.has(status)) {
        lastAgeMs = Date.now() - (msg.source_ts + (store.clockOffset ?? 0)) * 1000;
        afterRender();
        if (msg.final) recall.refresh();
      }
    } else if (msg.type === "HISTORY") {
      // The first HISTORY after connecting answers our CLIENT_HELLO. Any
      // later HISTORY is a batch of finals the server sent while this client
      // was congested; those are ordinary live captions.
      const recovery = expectingHistory;
      expectingHistory = false;
      const markRecovered = recovery && isReconnect; // late-join context is not "missed"
      const items = Array.isArray(msg.items) ? [...msg.items] : [];
      items.sort((a, b) => a.segment - b.segment);
      let added = 0;
      for (const item of items) {
        if (!item || item.final !== true) continue; // HISTORY carries finals only
        if (SHOWN.has(applyCaption(item, markRecovered))) added++;
      }
      if (added) {
        afterRender();
        recall.refresh();
      }
      if (recovery) announceRecovery(added);
    }
    // Unknown message types are ignored (forward compatibility).
  }

  function announceRecovery(added) {
    if (isReconnect) {
      toast(added
        ? `Back online: recovered ${added} missed caption${added === 1 ? "" : "s"}`
        : "Back online: nothing was missed");
    } else if (added) {
      toast(`Joined late: loaded ${added} recent caption${added === 1 ? "" : "s"}`);
    }
  }

  // --------------------------------------------------------------- status
  const STATUS_TEXT = {
    connecting: () => "Connecting…",
    connected: () => "Live",
    reconnecting: (info) => info.inMs
      ? `Reconnecting in ${(info.inMs / 1000).toFixed(1)} s…`
      : "Reconnecting…",
    offline: () => "Offline",
  };

  function onStatus(state, info) {
    els.status.className = `status ${state}`;
    els.statusText.textContent = STATUS_TEXT[state](info);
    if (state === "connected") {
      expectingHistory = true;
      isReconnect = info.reconnect;
      if (info.reconnect) reconnects++;
    }
  }

  let toastTimer = null;
  function toast(text) {
    els.toast.textContent = text;
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { els.toast.hidden = true; }, 4000);
  }

  function updateInfo() {
    const now = Date.now();
    const i = els.info;
    i.last.textContent = lastMessageAt ? `${((now - lastMessageAt) / 1000).toFixed(1)} s ago` : "–";
    i.age.textContent = lastAgeMs === null ? "–" : `~${Math.max(0, Math.round(lastAgeMs))} ms`;
    let finals = 0;
    for (const e of store.segments.values()) if (e.final) finals++;
    i.finals.textContent = String(finals);
    i.cursor.textContent = `${store.cursor.segment} / ${store.cursor.revision}`;
    i.reconnects.textContent = String(reconnects);
    if (els.status.classList.contains("connected")) {
      const idle = lastMessageAt && now - lastMessageAt > 10000;
      els.statusText.textContent = idle ? "Live · waiting for captions" : "Live";
    }
  }

  // ------------------------------------------------------------------ UI
  els.transcript.addEventListener("scroll", () => {
    const t = els.transcript;
    followLive = t.scrollTop + t.clientHeight >= t.scrollHeight - 40;
    if (followLive) els.jump.hidden = true;
  });
  els.jump.addEventListener("click", () => { followLive = true; scrollToLive(); });
  els.details.addEventListener("change", () => {
    document.body.classList.toggle("show-details", els.details.checked);
  });
  $("recall-open").addEventListener("click", () => recall.open(30));
  $("recall-close").addEventListener("click", () => recall.close());
  document.addEventListener("keydown", (e) => {
    if (e.target instanceof HTMLInputElement || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "m" || e.key === "M") recall.toggle();
    if (e.key === "Escape") recall.close();
  });

  els.info.server.textContent = SERVER_URL;
  $("session-label").textContent = `Lecture ${SESSION}`;

  const connection = new LR.LiveConnection({
    url: SERVER_URL,
    session: SESSION,
    clientId: clientId(),
    historySeconds: 60, // late join / reconnect: fetch enough for the 60 s view
    getCursor: () => store.cursor,
    onMessage,
    onStatus,
  });
  $("simulate-outage").addEventListener("click", () => {
    connection.simulateOutage(5000);
    toast("Disconnected for 5 s (simulated)");
  });

  // Slide the bounded local history and the recall window once a second,
  // even when no captions are arriving.
  setInterval(() => {
    removeRows(store.prune());
    recall.refresh();
    updateInfo();
  }, 1000);

  connection.start();
  LR.app = { store, connection, recall }; // handy for debugging in DevTools
})(window.LiveRecall = window.LiveRecall || {});
