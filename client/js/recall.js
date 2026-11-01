/*
 * "What did I miss?" panel.
 *
 * Reads ONLY the local CaptionStore: opening the panel or switching between
 * the 15/30/60 s windows never contacts the server. Captions that the client
 * genuinely missed (late join, disconnect) have already been merged into the
 * store from HISTORY and are marked "recovered".
 */
(function (LR) {
  "use strict";

  const WINDOWS = [15, 30, 60];
  const DEFAULT_WINDOW = 30;

  class RecallPanel {
    constructor(store, els) {
      this.store = store;
      this.panel = els.panel;
      this.list = els.list;
      this.summary = els.summary;
      this.title = els.title;
      this.buttons = els.windowButtons; // NodeList of [data-window]
      this.seconds = DEFAULT_WINDOW;
      this.isOpen = false;

      for (const btn of this.buttons) {
        btn.addEventListener("click", () => this.setWindow(Number(btn.dataset.window)));
      }
    }

    open(seconds = DEFAULT_WINDOW) {
      this.isOpen = true;
      this.panel.hidden = false;
      this.setWindow(seconds);
    }

    close() {
      this.isOpen = false;
      this.panel.hidden = true;
    }

    toggle() {
      if (this.isOpen) this.close(); else this.open();
    }

    setWindow(seconds) {
      if (!WINDOWS.includes(seconds)) seconds = DEFAULT_WINDOW;
      this.seconds = seconds;
      for (const btn of this.buttons) {
        const active = Number(btn.dataset.window) === seconds;
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-pressed", String(active));
      }
      this.render();
    }

    /** Called every second and after every final so the window slides. */
    refresh() {
      if (this.isOpen) this.render();
    }

    render(nowMs = Date.now()) {
      const items = this.store.finalsWithin(this.seconds, nowMs);
      this.title.textContent = `Previous ${this.seconds} seconds`;

      const frag = document.createDocumentFragment();
      if (items.length === 0) {
        const empty = document.createElement("li");
        empty.className = "recall-empty";
        empty.textContent = "No finalized captions in this period yet.";
        frag.appendChild(empty);
      }
      let recovered = 0;
      for (const entry of items) {
        const li = document.createElement("li");
        li.className = "recall-item";
        const ago = Math.max(0, Math.round((nowMs - this.store.localTime(entry)) / 1000));
        const time = document.createElement("span");
        time.className = "recall-time";
        time.textContent = `${ago}s ago`;
        const text = document.createElement("span");
        text.className = "recall-text";
        text.textContent = entry.text;
        li.append(time, text);
        if (entry.recovered) {
          recovered++;
          const tag = document.createElement("span");
          tag.className = "tag tag-recovered";
          tag.textContent = "recovered";
          tag.title = "Missed while disconnected and recovered from the server";
          li.appendChild(tag);
        }
        frag.appendChild(li);
      }
      this.list.replaceChildren(frag);

      const n = items.length;
      let summary = `${n} caption${n === 1 ? "" : "s"} from local history`;
      if (recovered) summary += ` · ${recovered} recovered after a gap`;
      this.summary.textContent = summary;
    }
  }

  LR.RecallPanel = RecallPanel;
  LR.RECALL_WINDOWS = WINDOWS;
})(window.LiveRecall = window.LiveRecall || {});
