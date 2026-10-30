/*
 * Working but deliberately naive LiveRecall browser starter.
 *
 * Provided mechanical behavior:
 *   - opens a WebSocket
 *   - sends CLIENT_HELLO
 *   - visibly appends every received CAPTION_UPDATE
 *   - displays whether an update is provisional/final
 *
 * Graded TODOs:
 *   - replace revisions rather than appending duplicates
 *   - maintain >=60 s of finalized local state
 *   - implement 30 s default recall + 15/30/60 s views
 *   - automatic reconnect + correct resume state
 *   - HISTORY merge/deduplication
 *   - usable final UI
 */

const WS_URL = "ws://127.0.0.1:8765";
const statusEl = document.getElementById("status");
const liveEl = document.getElementById("live");
const recallEl = document.getElementById("recall");
const segments = new Map();
const finalHistory = new Map(); // store finalised captions for the previous 60 seconds
const HISTORY_WINDOW_MS = 60 * 1000;
let recallWindowSeconds = null; // current displayed recall window (null = not opened)

let ws;
let reconnectTimer = null;
let reconnectAttempts = 0;
let lastFinalSegment = 0;
let lastFinalRevision = 0;

function numericClientId() {
  const key = "liverecall-client-id";
  let value = sessionStorage.getItem(key);
  if (!value) {
    value = String(Math.floor(100000 + Math.random() * 900000));
    sessionStorage.setItem(key, value);
  }
  return Number(value);
}

// function appendNaively(msg) {
//   const row = document.createElement("div"); // executed for every received update, creates duplicate caption line
//   row.className = "naive-line";
//   const state = msg.final ? "FINAL" : "PROVISIONAL";
//   row.textContent = `[${state}] segment ${msg.segment} rev ${msg.revision}: ${msg.text}`;
//   liveEl.appendChild(row);
//   liveEl.scrollTop = liveEl.scrollHeight;
// }
function pruneHistory() {
  const cutoff = Date.now() - HISTORY_WINDOW_MS;
  for (const [segment, caption] of finalHistory) {
    if (caption.captionTime < cutoff) {
      finalHistory.delete(segment);
    
      // remove expired finalised state
      segments.delete(segment);

      const row = document.getElementById(`segment-${segment}`);
      if (row) {
        row.remove();
      }
    }
  }
}


function updateFinalCursor(msg) {
  if (!msg.final) return;

  if (msg.segment > lastFinalSegment ||
    (msg.segment === lastFinalSegment &&
      msg.revision > lastFinalRevision)
  ) {lastFinalSegment = msg.segment;
    lastFinalRevision = msg.revision;}
}


function renderCaption(msg) {
  if (!Number.isFinite(msg.source_ts) || msg.source_ts * 1000 < Date.now() - HISTORY_WINDOW_MS) {
    return;
  }
  
  // retrieve the latest accepted revision for this segment
  const existing = segments.get(msg.segment);

  if (existing) {
    // final captions must never be overwritten
    if (existing.final) {
      return;
    }

    // ignore outdated or duplicate revisions.
    if (msg.revision <= existing.revision) {
      return;
    }
  }

  // find the HTML element for this segment
  let row = document.getElementById(`segment-${msg.segment}`);

  if (!row) {
    // create a new row only for a new segment
    row = document.createElement("div");
    row.id = `segment-${msg.segment}`;
    row.className = "naive-line";

    const nextRow = [...liveEl.children].find(
      child => {
        const id = Number(child.id.replace("segment-", ""));
        return Number.isFinite(id) && id > msg.segment;
      }
    );

    liveEl.insertBefore(row, nextRow ?? null);
  }

  // update the row using the latest revision
  const state = msg.final ? "FINAL" : "PROVISIONAL";

  row.textContent =
    `[${state}] segment ${msg.segment} rev ${msg.revision}: ${msg.text}`;

  // visually distinguish provisional and final captions
  row.style.opacity = msg.final ? "1" : "0.6";
  row.style.fontStyle = msg.final ? "normal" : "italic";

  // store the latest revision
  segments.set(msg.segment, msg);
  updateFinalCursor(msg);

  // save finalised captions to local history
  if (msg.final) {
    finalHistory.set(msg.segment, {
      segment: msg.segment,
      revision: msg.revision,
      text: msg.text,
      receivedAt: Date.now(),
      sourceTs: msg.source_ts,
      captionTime: msg.source_ts * 1000
    });
  }

  // remove captions older than 60s
  pruneHistory();

  // refresh recall if the user is currently viewing it
  if (recallWindowSeconds !== null) {
    showRecall(recallWindowSeconds);
  }

  // scroll to the latest caption
  liveEl.scrollTop = liveEl.scrollHeight;
}

function showRecall(seconds = 30) {
  recallWindowSeconds = seconds;

  // 1st remove expired history
  pruneHistory();

  const cutoff = Date.now() - seconds * 1000;

  // keep only finalised captions within the recall window
  const recentCaptions = [...finalHistory.values()]
    .filter(caption => caption.captionTime >= cutoff)
    .sort((a, b) => a.captionTime - b.captionTime);

  // clear the recall view
  recallEl.replaceChildren();

  const heading = document.createElement("h3");
  heading.textContent = `Previous ${seconds} seconds`;
  recallEl.appendChild(heading);

  if (recentCaptions.length === 0) {
    const empty = document.createElement("p");
    empty.textContent = "No finalized captions in this period.";
    recallEl.appendChild(empty);
    return;
  }

  // display the matching captions
  for (const caption of recentCaptions) {
    const row = document.createElement("div");
    row.className = "naive-line";
    row.textContent = caption.text;
    recallEl.appendChild(row);
  }
}


function connect() {
  statusEl.textContent = "connecting";
  ws = new WebSocket(WS_URL);

  ws.addEventListener("open", () => {
    reconnectAttempts = 0;
    clearTimeout(reconnectTimer);
    statusEl.textContent = "connected";
    ws.send(JSON.stringify({
      type: "CLIENT_HELLO",
      client_id: numericClientId(),
      session: "L1",
      last_segment: lastFinalSegment,
      last_revision: lastFinalRevision,
      history_seconds: 60
    }));
  });

  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "CAPTION_UPDATE") {
      renderCaption(msg);
    } else if (msg.type === "HISTORY") {
      console.log("Recovery HISTORY:", msg);
      const items = Array.isArray(msg.items) ? msg.items : [];

      // recover finalized captions in segment order
      items.sort((a, b) =>
        a.segment - b.segment || a.revision - b.revision
      );

      for (const caption of items) {
        if (caption.type === "CAPTION_UPDATE" && caption.final) {
          renderCaption(caption);
        }
      }

      console.log(`Processed ${items.length} recovery items`);
    }
  });

  
  ws.addEventListener("close", () => {
    statusEl.textContent = "disconnected — reconnecting";

    // exponential backoff, capped at 5s
    const delay = Math.min(
      1000 * (2 ** reconnectAttempts),
      5000
    );

    reconnectAttempts++;

    clearTimeout(reconnectTimer);

    reconnectTimer = setTimeout(() => {
      connect();
    }, delay);
  });

  ws.addEventListener("error", () => {
    statusEl.textContent = "connection error";
  });
}

for (const button of document.querySelectorAll("button[data-seconds]")) {
  button.addEventListener("click", () => {
    const seconds = Number(button.dataset.seconds);
    showRecall(seconds);
  });
}

// start browser connection
connect();

// keep 60s hisotry bounded as time passes, even when caption source is temp idle
setInterval(() => {
  pruneHistory();

  if (recallWindowSeconds !== null) {
    showRecall(recallWindowSeconds);
  }
}, 1000); 
