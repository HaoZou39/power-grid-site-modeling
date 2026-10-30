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
const mapSource = fs.readFileSync(new URL("./world_map.tsx", import.meta.url), "utf8");
assert.equal(mapSource.includes("favorite-add"), false);
assert.equal(mapSource.includes("favorite-adjust"), false);
assert.equal(mapSource.includes("onCreateFavorite"), false);
assert.equal(mapSource.includes("onPreviewFavoriteMove"), false);
const selected = [], created = [];
const context = {
  tool: "pan",
  routingRef: { current: null },
  handlers: { current: {
    onSelectFavorite: (id) => selected.push(id),
    onCreatePose: (point) => created.push(point),
    onDrawOutside: () => { throw new Error("inside point"); },
  } },
  map: {
    getLayer: (name) => name === "favorite-fill",
    queryRenderedFeatures: () => [{ properties: { id: "saved-favorite" } }],
  },
  gesture: { current: { dragging: false, drawing: false, moved: false, skipClick: false, last: null, stroke: [], routingEndpoint: null } },
  frame: { lngLatToLocal: (point) => ({ x: point.lng, y: point.lat }), inside: () => true },
  isLoopTool: () => false,
  isBoxTool: () => false,
  landuseEditClass: () => null,
  isLanduseSketchTool: () => false,
  routingLoop: (mode) => mode === "no_tower" || mode === "no_cross",
  routingBox: (mode) => mode === "no_tower-box" || mode === "no_cross-box",
  routingCursor: { current: null },
};
const mouse = (x, y) => ({ originalEvent: { button: 0 }, point: { x, y }, lngLat: { lng: x, lat: y } });
const run = (name, event) => vm.runInNewContext(handlers.get(name), context)(event);
context.finishAdjustment = () => run("finishAdjustment");
run("onMouseDown", mouse(100, 120));
assert.equal(context.gesture.current.dragging, false);
run("onClick", mouse(100, 120));
assert.deepEqual(selected, ["saved-favorite"]);
assert.equal(context.gesture.current.dragging, false);
context.tool = "pose-add";
context.map.getLayer = () => false;
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
console.log("favorite gestures: click selects a saved favorite and does not drag or create one");

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
context.routingRef.current = { active: true, picking: true, mode: "start", onPick: (point) => routingPicks.push(point) };
run("onMouseDown", mouse(120, 140));
run("onClick", mouse(120, 140));
assert.equal(routingPicks.length, 1);
assert.equal(routingPicks[0].x, 120);
assert.deepEqual(erased, ["footprint-fill", "favorite-fill"], "routing picks must not erase site objects");
context.routingRef.current = { active: true, picking: false };
context.handlers.current.onDeleteLanduseEdit = (id) => erased.push(id);
run("onClick", mouse(120, 140));
assert.deepEqual(erased, ["footprint-fill", "favorite-fill", "patch"], "routing eraser edits shared landuse without touching site objects");
console.log("routing gestures: site editing is isolated while picking routing connections");

const strokes = [];
context.routingRef.current = { active: true, picking: true, mode: "no_tower",
  onPreviewStroke() {}, onFinishStroke: (points) => strokes.push(points) };
run("onMouseDown", mouse(10, 10));
run("onMouseMove", mouse(30, 10));
run("onMouseMove", mouse(30, 30));
run("onMouseUp", { button: 0 });
assert.equal(strokes.length, 1);
assert.equal(strokes[0].length, 3, "freehand points are passed to the routing region, not to site editing");
run("onClick", mouse(30, 30));

const corners = [];
context.routingRef.current = { active: true, picking: true, mode: "no_cross-box",
  onBoxClick: (point) => corners.push(point), onBoxMove() {} };
run("onClick", mouse(5, 7));
run("onClick", mouse(20, 30));
assert.equal(corners.length, 2);

const movedEndpoints = [];
context.routingRef.current = { active: true, picking: true, mode: "adjust-endpoints",
  onMoveEndpoint: (which, point) => movedEndpoints.push({ which, point }) };
context.map.queryRenderedFeatures = () => [{ properties: { kind: "endpoint", endpoint: "end" } }];
run("onMouseDown", mouse(20, 30));
run("onMouseMove", mouse(25, 35));
run("onMouseUp", { button: 0 });
assert.equal(movedEndpoints[0].which, "end");
assert.equal(movedEndpoints[0].point.x, 25);
assert.equal(context.gesture.current.routingEndpoint, null);
run("onClick", mouse(25, 35));

let cursorText = "";
let popupCount = 0;
context.maplibregl = { Popup: class {
  constructor() { popupCount++; }
  setLngLat() { return this; }
  setText(text) { cursorText = text; return this; }
  addTo() { return this; }
  remove() {}
} };
context.routingRef.current = { active: true, picking: true, mode: "start" };
run("onMouseMove", mouse(120.12345678, 27.12345678));
assert.match(cursorText, /起点：经度 120\.1234568°，纬度 27\.1234568°/);
run("onMouseMove", mouse(120.2, 27.5));
assert.match(cursorText, /经度 120\.2000000°，纬度 27\.5000000°/);
assert.equal(popupCount, 1, "cursor tooltip updates in place while the mouse moves");

const erasedRegions = [];
context.routingRef.current = { active: true, picking: false, onEraseRegion: (index) => erasedRegions.push(index) };
context.pointInLanduseRing = () => false;
context.map.queryRenderedFeatures = () => [{ properties: { kind: "zone", region_index: 2 } }];
run("onClick", mouse(10, 10));
assert.deepEqual(erasedRegions, [2], "eraser targets the selected routing region");
