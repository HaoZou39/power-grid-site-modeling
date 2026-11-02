import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("./work_panel_resize.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const exports = {};
vm.runInNewContext(compiled, {
  exports,
  require(name) {
    if (name === "react") return { useRef: (current) => ({ current }) };
    if (name === "react/jsx-runtime") return { jsx: (type, props) => ({ type, props }) };
    throw new Error(`Unexpected dependency: ${name}`);
  },
});

assert.equal(exports.clampWorkPanelWidth(100, 1200), 260);
assert.equal(exports.clampWorkPanelWidth(900, 1200), 720);
assert.equal(exports.clampWorkPanelWidth(720, 901), 701);

const changes = [];
const handle = exports.WorkPanelResize({ width: 340, viewportWidth: 1200, onChange: (width) => changes.push(width) }).props;
const event = { isPrimary: true, button: 0, pointerId: 1, clientX: 340,
  preventDefault() {}, stopPropagation() {}, currentTarget: { setPointerCapture(id) { assert.equal(id, 1); } } };
handle.onPointerDown(event);
handle.onPointerMove({ ...event, clientX: 460 });
handle.onPointerMove({ ...event, clientX: 1200 });
handle.onPointerUp();
handle.onPointerMove({ ...event, clientX: 400 });
handle.onKeyDown({ ...event, key: "ArrowLeft" });
handle.onKeyDown({ ...event, key: "End" });
assert.deepEqual(changes, [460, 720, 324, 720]);
console.log("work panel resize: bounds, drag, release and keyboard passed");
