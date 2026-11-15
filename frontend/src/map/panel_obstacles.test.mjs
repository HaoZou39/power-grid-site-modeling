import assert from "node:assert/strict";
import { observePanelObstacles } from "../../.tmp-scheme-panels/map/panel_obstacles.js";

const frames = new Map();
let frameId = 0;
const listeners = new Map();
globalThis.requestAnimationFrame = (callback) => { frames.set(++frameId, callback); return frameId; };
globalThis.cancelAnimationFrame = (id) => frames.delete(id);
globalThis.window = {
  addEventListener: (name, callback) => listeners.set(name, callback),
  removeEventListener: (name) => listeners.delete(name),
};
class Element {
  constructor(box, root = null) { this.box = box; this.root = root; this.children = []; this.hidden = false; }
  closest(selector) { return selector === ".map-app" ? this.root : this.panel ? this : null; }
  contains(node) { return node === this || this.children.includes(node); }
  querySelectorAll() { return this.children; }
  getBoundingClientRect() { return { ...this.box, width: this.box.right - this.box.left, height: this.box.bottom - this.box.top }; }
}
globalThis.Element = Element;
globalThis.getComputedStyle = (element) => ({ display: element.hidden ? "none" : "block", visibility: "visible" });
let resize, mutation;
class ResizeObserver {
  constructor(callback) { this.callback = callback; this.observed = new Set(); this.pending = false; this.observeCalls = 0; resize = this; }
  observe(element) { this.observed.add(element); this.pending = true; this.observeCalls++; }
  unobserve(element) { this.observed.delete(element); }
  disconnect() { this.observed.clear(); }
}
globalThis.ResizeObserver = ResizeObserver;
globalThis.MutationObserver = class {
  constructor(callback) { this.callback = callback; mutation = this; }
  observe() {}
  disconnect() { this.disconnected = true; }
};
function settle() {
  for (let i = 0; i < 10; i++) {
    if (resize.pending) { resize.pending = false; resize.callback(); }
    if (!frames.size) return;
    const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach((callback) => callback());
  }
  assert.fail("observer must become idle without continuously re-observing unchanged elements");
}
const root = new Element({ left: 0, top: 0, right: 1400, bottom: 900 });
const node = new Element({ left: 20, top: 150, right: 380, bottom: 690 }, root);
const results = new Element({ left: 900, top: 400, right: 1380, bottom: 880 }, root);
results.panel = true;
root.children = [results];
const published = [];
const stop = observePanelObstacles(node, (boxes) => published.push(boxes));
settle();
assert.equal(resize.observeCalls, 2, "observe root and results once");
assert.equal(frames.size, 0);
assert.deepEqual(published.at(-1), [results.box]);
results.box.left = 700;
mutation.callback([{ target: results, type: "attributes" }]);
settle();
assert.equal(published.at(-1)[0].left, 700, "track panel movement without a resize");
results.hidden = true;
mutation.callback([{ target: results, type: "attributes" }]);
settle();
assert.deepEqual(published.at(-1), []);
root.children = [];
mutation.callback([{ target: root, type: "childList" }]);
settle();
assert.equal(resize.observed.has(results), false, "removed panels must be unobserved");
mutation.callback([{ target: node, type: "attributes" }]);
assert.equal(frames.size, 0, "moving the detail panel itself must not retrigger obstacle measurement");
stop();
assert.equal(resize.observed.size, 0);
assert.equal(listeners.size, 0);
assert.equal(mutation.disconnected, true);
assert.equal(frames.size, 0);
console.log("panel observers: idle stability, movement, hiding, removal and cleanup passed");
