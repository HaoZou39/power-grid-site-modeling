import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { SiteEdit } from "../../.tmp-problem-snapshot/map/site_edit.js";
import { activateSiteFrame, siteFrame, footprintCorners, uprightRectangleRing } from "../../.tmp-problem-snapshot/map/site_frame.js";
import { applyOps, proposalPreview } from "../../.tmp-problem-snapshot/agent/edit_ops.js";
import { refineSquare } from "../../.tmp-problem-snapshot/map/decision_run.js";
import { sceneSquareRing } from "../../.tmp-problem-snapshot/map/scene_rect_select.js";
import * as viewport from "../../.tmp-problem-snapshot/map/site_viewport.js";
import * as sceneExport from "../../.tmp-problem-snapshot/map/scene_export.js";

const source = (file) => readFileSync(new URL(file, import.meta.url), "utf8");
const compile = (text) => ts.transpileModule(text, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
function nodes(file, predicate) {
  const tree = ts.createSourceFile(file, source(file), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found = [];
  function visit(node) {
    if (predicate(node)) found.push(node.getText(tree));
    ts.forEachChild(node, visit);
  }
  visit(tree);
  return found;
}
const area = (ring) => Math.abs(ring.reduce((sum, p, i) => {
  const q = ring[(i + 1) % ring.length];
  return sum + p.x * q.y - p.y * q.x;
}, 0)) / 2;

test("assistant rectangles enclose all four corners in either study frame", () => {
  for (const angle of [0, 0.23]) {
    const study = footprintCorners(900, 900, angle, 1400, 1400);
    activateSiteFrame({ crs: "EPSG:3857", transform: [1, 0, 0, 0, -1, 0], width: 1800, height: 1800,
      study_domain: { ring: study.map(p => [p.x, p.y]), window: [0, 0, 1800, 1800], side_m: 1400 } });
    const ring = footprintCorners(700, 700, Math.PI / 4 + angle, Math.sqrt(80000), Math.sqrt(80000));
    assert.ok(Math.abs(area(ring) - 80000) < 1e-6);
    for (const input of [ring, [...ring].reverse(), [ring[2], ring[0], ring[3], ring[1]]]) {
      for (const kind of ["exclusion", "feasible"]) {
        const before = new SiteEdit();
        const after = applyOps(before, [{ kind: "add_region", region_kind: kind, ring: input }]).edit;
        const output = after.regions[0].ring;
        assert.ok(Math.abs(area(output) - 160000) < 1e-6);
        const { u, v } = siteFrame.studyBox();
        for (const axis of [u, v]) {
          const project = p => p.x * axis.x + p.y * axis.y;
          const lo = Math.min(...output.map(project)), hi = Math.max(...output.map(project));
          assert.ok(input.every(p => project(p) >= lo - 1e-6 && project(p) <= hi + 1e-6));
          assert.ok(hi - lo >= 1);
        }
        const edge = { x: output[1].x - output[0].x, y: output[1].y - output[0].y };
        assert.ok(Math.abs(edge.x * u.y - edge.y * u.x) < 1e-6);
        assert.deepEqual(proposalPreview(before, after).regions[0].ring, output);
      }
    }
    for (const ring of [footprintCorners(700, 700, angle, 0.1, 0.1), footprintCorners(700, 700, angle, 1e-5, 1e-5),
      [{ x: 10, y: 10 }, { x: 20, y: 10 }, { x: 30, y: 10 }, { x: 40, y: 10 }],
      [{ x: 10, y: 10 }, { x: 20, y: 10 }, { x: 20, y: 20 }, { x: 10, y: 10 }],
      [{ x: NaN, y: 10 }, { x: 20, y: 10 }, { x: 20, y: 20 }, { x: 10, y: 20 }]]) {
      assert.throws(() => applyOps(new SiteEdit(), [{ kind: "add_region", region_kind: "exclusion", ring }]));
    }
    const irregular = [{x: 20, y: 20}, {x: 90, y: 25}, {x: 70, y: 90}, {x: 30, y: 70}];
    assert.equal(uprightRectangleRing(siteFrame, irregular), null);
    assert.deepEqual(applyOps(new SiteEdit(), [{kind: "add_region", region_kind: "feasible", ring: irregular}]).edit.regions[0].ring, irregular);
  }
  // All input corners are inside; the study-aligned envelope crosses the grid edge.
  const ring = footprintCorners(65, 900, 0, 120, 600);
  assert.ok(ring.every(p => siteFrame.inside(p)));
  assert.throws(() => applyOps(new SiteEdit(), [{kind: "add_region", region_kind: "exclusion", ring}]), /范围/);
});

test("drawn and refinement boxes follow the study domain through request serialization", () => {
  const study = footprintCorners(900, 900, 0.23, 1400, 1400);
  activateSiteFrame({ crs: "EPSG:3857", transform: [1, 0, 0, 0, -1, 0], width: 1800, height: 1800,
    study_domain: { ring: study.map(p => [p.x, p.y]), window: [0, 0, 1800, 1800], side_m: 1400 } });
  const { center, u, v, halfU } = siteFrame.studyBox();
  const point = (s, t) => ({x: center.x + s * u.x + t * v.x, y: center.y + s * u.y + t * v.y});
  const first = point(-100, -200), second = point(200, 150);
  const before = new SiteEdit();
  for (const kind of ["exclusion", "feasible"]) {
    const after = before.addRectangle(kind, first, second);
    const output = after.regions[0].ring;
    assert.deepEqual(before.addRectangle(kind, second, first).regions[0].ring, output);
    assert.ok(Math.abs(area(output) - 105000) < 1e-6);
    for (const corner of [first, second]) assert.ok(output.some(p => Math.hypot(p.x - corner.x, p.y - corner.y) < 1e-8));
    const serialized = after.searchConfig()[`${kind}_zones`][0].points;
    assert.deepEqual(serialized, output.map(p => [p.x, p.y]));
    assert.ok(serialized.every(([x, y]) => siteFrame.insideStudy({x, y})));
    assert.throws(() => before.addRectangle(kind, point(0, 0), point(0.5, 100)), /1 米/);
  }
  for (const [location, expectedArea] of [[center, 90000], [point(halfU - 20, 0), 51000]]) {
    const ring = refineSquare(location, 150).map(([x, y]) => ({x, y}));
    assert.ok(Math.abs(area(ring) - expectedArea) < 1e-6);
    assert.ok(ring.every(p => siteFrame.insideStudy(p, 1e-7)));
    const edge = {x: ring[1].x - ring[0].x, y: ring[1].y - ring[0].y};
    assert.ok(Math.abs(edge.x * u.y - edge.y * u.x) < 1e-7);
  }
});

test("dateline preview bounds and rendered polygon use a local continuous interval", () => {
  const effects = nodes("./world_map.tsx", n => ts.isCallExpression(n) && n.expression.getText() === "useEffect"
    && n.arguments[1]?.getText().includes("buildPreviewRing"));
  assert.equal(effects.length, 2);
  for (const lon of [180, -180, 179.999, -179.999, 120.2]) {
    const ring = sceneSquareRing(27.5, lon, 1800);
    const bounds = viewport.siteLngLatBounds(ring);
    assert.ok(bounds[1][0] - bounds[0][0] < 0.1, `longitude ${lon}`);
    const paints = [], fits = [], cleanups = [];
    let stops = 0;
    const map = { getSource: () => ({setData: data => paints.push(data)}), fitBounds: b => fits.push(b), on() {}, off() {}, stop() { stops++; } };
    const context = { ...viewport, mapRef: {current: map}, containerRef: {current: {clientWidth: 1000, clientHeight: 800}},
      ready: true, buildPreviewRing: ring, buildPreviewFocusToken: 1, framing: {current: false}, measureMapPadding: () => ({}),
      useEffect: fn => { const cleanup = fn(); if (cleanup) cleanups.push(cleanup); } };
    for (const effect of effects) runInNewContext(compile(effect), context);
    assert.equal(fits.length, 1);
    const painted = paints[0].features[0].geometry.coordinates[0];
    assert.ok(Math.max(...painted.map(p => p[0])) - Math.min(...painted.map(p => p[0])) < 0.1);
    assert.deepEqual(JSON.parse(JSON.stringify(fits[0])), viewport.siteLngLatBounds(painted));
    cleanups.forEach(cleanup => cleanup());
    assert.equal(stops, 1, "unmount interrupts the old preview animation");
    assert.equal(context.framing.current, false);
  }
});

test("actual scene switch clears preview only after the switch gates pass", () => {
  const [body] = nodes("./map_workspace.tsx", n => ts.isFunctionDeclaration(n) && n.name?.text === "switchScene");
  for (const mode of ["switch", "reload", "same", "export", "optimize", "saving", "dirty"]) {
    const values = { buildPreviewRing: [[1,2],[3,4],[5,6],[1,2]], buildPreviewFocus: 3 };
    const original = values.buildPreviewRing;
    const context = {
      SiteEdit, activateSiteFrame, scene: {id: "a"}, sceneRef: {current: {id: "a"}}, optimizationActive: () => mode === "optimize",
      exportingSceneRef: {current: mode === "export"}, landuseStateRef: {current: {saving: mode === "saving"}},
      landuseSceneSwitch: () => ({allowed: mode !== "dirty", state: {}}), editRef: {current: new SiteEdit()},
      solutionGeneration: {current: {advance() {}}}, evaluationFailed: {current: new Set()}, hiddenLanduseClasses: () => ({}),
      showFeasibilityUrl() {},
    };
    // Unrelated workspace setters are observed, not reimplemented.
    for (const name of body.matchAll(/\b(set\w+)\(/g)) context[name[1]] = value => {
      const key = name[1][3].toLowerCase() + name[1].slice(4);
      values[key] = typeof value === "function" ? value(values[key] ?? 0) : value;
    };
    for (const name of body.matchAll(/\b(\w+)\.current/g)) if (!(name[1] in context)) context[name[1]] = {current: null};
    const switchScene = runInNewContext(compile(body) + "\nswitchScene", context);
    switchScene({id: mode === "reload" || mode === "same" ? "a" : "b", title: "B", ready: true}, mode === "reload" ? {reload: true} : undefined);
    if (mode === "switch" || mode === "reload") {
      assert.equal(values.buildPreviewRing, null, mode);
      assert.equal(values.buildPreviewFocus, 0, mode);
    } else assert.equal(values.buildPreviewRing, original, mode);
    if (mode === "dirty") {
      context.landuseSceneSwitch = () => ({allowed: true, state: {}});
      switchScene(values.pendingSceneSwitch.next, values.pendingSceneSwitch.options);
      assert.equal(values.buildPreviewRing, null, "deferred switch");
    }
  }
});

test("actual PNG capture hides preview and restores exact visibility on every exit", async () => {
  const overlay = new Proxy({emptyAgentPreview: {}}, {get: (target, key) => target[key] ?? (() => {})});
  for (const failure of [null, "resource", "blob"]) {
    for (const initial of [undefined, "visible", "none"]) {
      const visibility = new Map([["scene-build-preview-fill", initial], ["scene-build-preview-line", initial]]);
      const listeners = new Map(), samples = [];
      const controls = {enable() {}, disable() {}};
      const map = {getLayer: id => visibility.has(id), getLayoutProperty: id => visibility.get(id),
        setLayoutProperty: (id, key, value) => visibility.set(id, value ?? undefined),
        on: (event, fn) => listeners.set(event, fn), off: event => listeners.delete(event),
        getContainer: () => ({querySelectorAll: () => [], clientWidth: 200}),
        getCenter: () => ({lng: 120, lat: 27}), getZoom: () => 10, getBearing: () => 0, getPitch: () => 0,
        jumpTo() {}, getCanvas: () => ({width: 200, height: 100}),
        triggerRepaint: () => queueMicrotask(() => {
          if (failure === "resource") listeners.get("error")?.({error: {message: "resource failure"}});
          listeners.get("idle")?.();
        }), dragPan: controls, scrollZoom: controls, boxZoom: controls, doubleClickZoom: controls, keyboard: controls, touchZoomRotate: controls };
      const drawing = new Proxy({getImageData: () => ({data: [20,30,40,255]})}, {get: (target, key) => target[key] ?? (() => {})});
      const exports = {};
      const modules = {"./scene_export": sceneExport, "./site_overlay": overlay, "./site_viewport": viewport,
        "./basemap": {worldBasemap: {}}, "../routing/routing_layer": {syncRoutingLayer() {}}};
      const context = {exports, require: name => { assert.ok(name in modules, name); return modules[name]; },
        window: {setTimeout, clearTimeout, requestAnimationFrame: fn => queueMicrotask(fn)},
        document: {createElement: () => ({getContext: () => drawing, toBlob: fn => {
          samples.push([...visibility.values()]);
          fn(failure === "blob" ? null : new Blob(["x".repeat(40)]));
        }})}, Blob,
      };
      runInNewContext(compile(source("./scene_export_map.ts")), context);
      const paint = {frame: siteFrame, landuseLayers: [], landuseEdits: [], landuseDraft: [], landusePreview: [], roadSegments: []};
      const request = {extent: "view", title: "test", landuseVisible: {}, footprints: [], ranks: [], legend: []};
      const capture = exports.captureMapScene(map, () => paint, request);
      if (failure) await assert.rejects(capture, failure === "blob" ? /PNG/ : /resource failure/);
      else await capture;
      for (const sample of samples) assert.deepEqual(sample, ["none", "none"], "capture must exclude both preview layers");
      assert.deepEqual([...visibility.values()], [initial, initial], "restore original visibility");
      assert.equal(listeners.size, 0);
    }
  }
});
