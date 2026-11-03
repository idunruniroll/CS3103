// Logic checks only; the mandatory visual browser demo remains separate.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let now = 1000000;
let timer;
class FakeSocket {
  static OPEN = 1;
  constructor(url) { this.url = url; this.handlers = {}; this.readyState = 0; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  send(value) { this.sent = JSON.parse(value); }
  close() { this.readyState = 3; this.handlers.close?.(); }
}
function element() {
  return { hidden: true, children: [], dataset: {}, classList: { toggle() {} },
    setAttribute() {}, addEventListener() {},
    append(...items) { this.children.push(...items); },
    appendChild(item) { this.children.push(item); },
    replaceChildren(...items) { this.children = items; } };
}
const context = vm.createContext({
  window: { addEventListener() {} },
  document: { createElement: element, createDocumentFragment: element },
  Date: { now: () => now }, Math, WebSocket: FakeSocket,
  setTimeout(fn, delay) { timer = { fn, delay }; return timer; },
  clearTimeout() { timer = null; },
});
for (const file of ['caption_store', 'connection', 'recall']) {
  vm.runInContext(fs.readFileSync(`client/js/${file}.js`, 'utf8'), context);
}
const LR = context.window.LiveRecall;
const store = new LR.CaptionStore();
const caption = (segment, revision, final, source_ts = 1000) =>
  ({ segment, revision, final, source_ts, text: `${segment}/${revision}` });
assert.equal(store.apply(caption(1, 1, false)).status, 'new');
assert.equal(store.apply(caption(1, 2, false)).status, 'updated');
assert.equal(store.apply(caption(1, 1, false)).status, 'stale');
assert.equal(store.apply(caption(1, 3, true)).status, 'finalized');
assert.equal(store.apply(caption(1, 3, true), { recovered: true }).status, 'duplicate');
assert.equal(store.apply(caption(1, 4, false)).status, 'stale');
assert.equal(store.cursor.segment, 1);
assert.equal(store.cursor.revision, 3);
// Learn a fixed source/browser clock difference, then exercise recall windows.
const history = new LR.CaptionStore();
history.apply(caption(1, 1, true, 900));
now += 20000;
history.apply(caption(2, 1, true, 920));
now += 20000;
history.apply(caption(3, 1, true, 940));
assert.equal(history.finalsWithin(15).length, 1);
assert.equal(history.finalsWithin(30).length, 2);
assert.equal(history.finalsWithin(60).length, 3);
const buttons = [15, 30, 60].map(value => Object.assign(element(), { dataset: { window: value } }));
const panel = new LR.RecallPanel(history, {
  panel: element(), list: element(), summary: element(), title: element(), windowButtons: buttons,
});
panel.open(); assert.equal(panel.seconds, 30);
panel.setWindow(15); assert.equal(panel.seconds, 15);
panel.setWindow(60); assert.equal(panel.seconds, 60);
panel.close(); assert.equal(panel.isOpen, false);
now += 91000; history.prune(); assert.equal(history.segments.size, 0);
const bounded = new LR.CaptionStore({ maxSegments: 3 });
for (let i = 1; i <= 10; i++) bounded.apply(caption(i, 1, true));
bounded.prune(); assert.equal(bounded.segments.size, 3);
assert.equal(bounded.apply(caption(1, 1, true)).status, 'stale');
const connection = new LR.LiveConnection({
  url: 'ws://test', clientId: 1, getCursor: () => store.cursor, onMessage() {},
});
connection.start(); connection.ws.handlers.open();
assert.equal(connection.ws.sent.last_segment, 1);
assert.equal(connection.ws.sent.last_revision, 3);
assert.equal(connection.ws.sent.history_seconds, 60);
connection.ws.close(); assert.ok(timer.delay >= 250 && timer.delay <= 325);
timer.fn(); connection.ws.handlers.open(); assert.equal(connection.connections, 2);
connection.attempt = 30; connection.timer = null; connection.scheduleReconnect();
assert.ok(timer.delay >= 5000 && timer.delay <= 6500);
connection.simulateOutage(5000); assert.ok(timer.delay >= 5000);
console.log('PASS: browser state, final deduplication, 15/30/60 recall, clock offset, pruning, resume and reconnect timing');
