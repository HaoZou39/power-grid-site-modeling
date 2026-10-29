import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

// Run the registered gesture handlers without WebGL; React selection commits later.
const source = ts.createSourceFile("world_map.tsx", fs.readFileSync(new URL("./world_map.tsx", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const handlers = new Map();
function find(node) {
  if (ts.isVariableDeclaration(node) && ["onMouseDown", "onMouseMove", "onMouseUp", "onClick", "eraseTargetAt", "finishAdjustment"].includes(node.name.getText(source))) {
    handlers.set(node.name.getText(source), ts.transpileModule(`(${node.initializer.getText(source)})`, {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
    }).outputText);
  }
  ts.forEachChild(node, find);
}
find(source);
const selected = [], moves = [], created = [];
let finished = 0;
const context = {
  tool: "favorite-adjust",
  routingRef: { current: null },
  handlers: { current: {
    onSelectFavorite: (id) => selected.push(id),
    onPreviewFavoriteMove: (...args) => moves.push(args),
    onFinishFavoriteEdit: () => finished++,
    onCreateFavorite: (point) => created.push(point),
  } },
  map: { queryRenderedFeatures: () => [{ properties: { id: "new-favorite" } }] },
  selectedFavoriteRef: { current: { id: "previous-favorite" } },
  gesture: { current: { favoriteEditing: null, skipClick: true } },
  frame: { lngLatToLocal: (point) => ({ x: point.lng, y: point.lat }), inside: () => true },
  isLoopTool: () => false,
  landuseEditClass: () => null,
  isLanduseSketchTool: () => false,
};
const mouse = (x, y) => ({ originalEvent: { button: 0 }, point: { x, y }, lngLat: { lng: x, lat: y } });
const run = (name, event) => vm.runInNewContext(handlers.get(name), context)(event);
context.finishAdjustment = () => run("finishAdjustment");
run("onMouseDown", mouse(100, 120));
assert.deepEqual(selected, ["new-favorite"]);
assert.equal(context.gesture.current.favoriteEditing?.id, "new-favorite");
run("onMouseMove", mouse(110, 135));
assert.deepEqual(moves, [["new-favorite", 10, 15]]);
run("onMouseUp", { button: 0 });
assert.equal(finished, 1);
context.tool = "favorite-add";
run("onMouseDown", mouse(300, 400));
assert.equal(context.gesture.current.skipClick, false, "an old drag must not swallow the next manual add click");
run("onClick", mouse(300, 400));
assert.equal(created[0].x, 300);
assert.equal(created[0].y, 400);
let moveFinished = 0;
context.handlers.current.onFinishMove = () => moveFinished++;
context.gesture.current.dragging = true;
context.gesture.current.moved = true;
run("finishAdjustment");
assert.equal(moveFinished, 1);
assert.equal(context.gesture.current.dragging, false);
run("finishAdjustment");
assert.equal(moveFinished, 1, "cleanup and mouseup finalize a gesture once");
console.log("favorite gestures: first-gesture selection/drag and subsequent manual add passed");

// Overlapping solutions must be hit before underlying landuse/regions, but after favorites.
const erased = [];
let hitLayers = new Set(["footprint-fill", "forbidden-fill"]);
context.map = {
  getLayer: () => true,
  queryRenderedFeatures: (_point, { layers }) => hitLayers.has(layers[0]) ? [{ properties: { id: layers[0] } }] : [],
};
context.landuseEditsRef = { current: [{ id: "patch", points: [] }] };
context.pointInLanduseRing = () => true;
context.tool = "erase";
context.isBoxTool = () => false;
context.setEraseHover = () => {};
context.eraseTargetAt = (event) => run("eraseTargetAt", event);
context.handlers.current.onErasePose = (id) => erased.push(id);
context.handlers.current.onEraseFavorite = (id) => erased.push(id);
run("onClick", mouse(300, 400));
assert.deepEqual(erased, ["footprint-fill"]);
assert.equal(context.tool, "erase");
hitLayers.add("favorite-fill");
run("onClick", mouse(300, 400));
assert.deepEqual(erased, ["footprint-fill", "favorite-fill"]);
hitLayers.clear();
assert.equal(run("eraseTargetAt", mouse(300, 400)).kind, "landuse");
console.log("eraser gestures: solution deletion and overlapping-target priority passed");

const routingPicks = [];
context.routingRef.current = { active: true, picking: true, onPick: (point) => routingPicks.push(point) };
run("onMouseDown", mouse(120, 140));
run("onClick", mouse(120, 140));
assert.equal(routingPicks.length, 1);
assert.equal(routingPicks[0].x, 120);
assert.deepEqual(erased, ["footprint-fill", "favorite-fill"], "routing picks must not erase site objects");
console.log("routing gestures: site editing is isolated while picking routing connections");
