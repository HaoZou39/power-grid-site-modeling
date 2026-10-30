import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { RoutingEdit } from "../../.tmp-routing/routing/routing_edit.js";
import { nextRoutingSort, parseRoutingResult, sortRoutingSolutions } from "../../.tmp-routing/routing/routing_result.js";
import { routingFeatures, syncRoutingLayer } from "../../.tmp-routing/routing/routing_layer.js";
import { siteFrameFromInfo } from "../../.tmp-routing/map/site_frame.js";
import { SolutionGeneration } from "../../.tmp-routing/map/solution_generation.js";
import { readRoutingExperiment } from "../../.tmp-routing/routing/routing_experiment.js";
import { routingCsv, routingJson } from "../../.tmp-routing/routing/routing_export.js";
import { routingToolbarCommands } from "../../.tmp-routing/routing/routing_toolbar.js";
import { routingRectangle, routingRegionKind, routingStroke } from "../../.tmp-routing/routing/routing_interaction.js";
import { validateRoutingPolygon } from "../../.tmp-routing/routing/routing_polygon.js";
import { nearestRoutingSpan, routingHoverText } from "../../.tmp-routing/routing/routing_hover.js";
import { routingAttachment, routingContext, routingMessages } from "../../.tmp-routing/agent/routing_context.js";
import { defaultRoutingPreference, readRoutingPreference, writeRoutingPreference } from "../../.tmp-routing/agent/routing_preference.js";
import { toolbarCommands } from "../../.tmp-routing/map/toolbar_commands.js";

const defaults = JSON.parse(readFileSync(new URL("../../../config/default_config.json", import.meta.url), "utf8"));
const defaultMechanisms = defaults.routing.pilot.enabled_mechanisms;
const info = { crs: "EPSG:32651", transform: [1, 0, 221000, 0, -1, 3046000], width: 32, height: 32 };
const frame = siteFrameFromInfo(info);
const schema = { properties: { road_setback_m: { default: defaults.modeling.road_setback_m },
  highway_setback_m: { default: defaults.modeling.highway_setback_m }, algorithm: { default: defaults.routing } } };
let edit = new RoutingEdit().defaults(schema);
assert.equal(edit.values.max_span_m, "");
assert.throws(() => edit.task("test", "run", frame));
edit = edit.picked("start", { x: 4, y: 8 }, frame).picked("end", { x: 28, y: 8 }, frame);
assert.ok(Math.abs(edit.localPoint("start", frame).x - 4) < .001);
edit = edit.copy({ values: { ...edit.values, max_span_m: "30", tower_radius_m: ".4", max_turn_deg: "90" }, regions: [
  { kind: "no_tower", points: [{ x: 10, y: 10 }, { x: 15, y: 10 }, { x: 15, y: 15 }] },
  { kind: "no_cross", points: [{ x: 20, y: 20 }, { x: 25, y: 20 }, { x: 25, y: 25 }] },
] });
const task = edit.task("test", "run", frame);
assert.equal(task.no_tower_zones.length, 1);
assert.equal(task.no_cross_zones.length, 1);
assert.deepEqual(task.no_tower_zones[0], [[10, 10], [15, 10], [15, 15]]);
assert.deepEqual(task.no_cross_zones[0], [[20, 20], [25, 20], [25, 25]]);
assert.deepEqual(task.algorithm, defaults.routing);
const typed = edit.copy({ algorithm: { ...edit.algorithm, mutation_scale: "0.25", seed: "42" } });
assert.equal(typed.task("test", "run", frame).algorithm.mutation_scale, .25);
assert.equal(typed.task("test", "run", frame).algorithm.seed, 42);
const execution = edit.copy({ algorithm: { ...edit.algorithm, evolution_backend: "tensor", devices: "cuda:0, cuda:1" } }).task("test", "run", frame);
assert.equal(execution.algorithm.evolution_backend, "tensor");
assert.deepEqual(execution.algorithm.devices, ["cuda:0", "cuda:1"]);
const referenceEdit = edit.algorithmParameter("search_strategy", "pilot_reference");
assert.equal(referenceEdit.algorithm.evolution_backend, "numpy");
assert.equal(referenceEdit.algorithm.evaluation_backend, "compiled_cpu");
assert.deepEqual(referenceEdit.algorithm.devices, ["cpu"]);
assert.deepEqual(referenceEdit.values, edit.values);
assert.deepEqual(referenceEdit.regions, edit.regions);
assert.equal(referenceEdit.task("test", "cpu", frame).algorithm.search_strategy, "pilot_reference");
const tensorPilot = referenceEdit.algorithmParameter("evolution_backend", "tensor").algorithmParameter("devices", "cuda:0, cuda:1");
assert.equal(tensorPilot.algorithm.evaluation_backend, "tensor");
const tensorTask = tensorPilot.task("test", "gpu", frame);
assert.deepEqual(tensorTask.algorithm.devices, ["cuda:0", "cuda:1"]);
assert.equal(RoutingEdit.fromTask(tensorTask).algorithm.evolution_backend, "tensor");
const backToCpu = tensorPilot.algorithmParameter("evaluation_backend", "compiled_cpu");
assert.equal(backToCpu.algorithm.evolution_backend, "numpy");
assert.deepEqual(backToCpu.algorithm.devices, ["cpu"]);
const rrtEdit = referenceEdit.toggleRrt(true);
assert.equal(rrtEdit.rrtEnabled, true);
assert.deepEqual(rrtEdit.task("test", "rrt", frame).algorithm.pilot.enabled_mechanisms, defaultMechanisms);
assert.equal(RoutingEdit.fromTask(rrtEdit.task("test", "rrt", frame)).rrtEnabled, true);
const standardEdit = rrtEdit.algorithmParameter("search_strategy", "standard");
assert.equal(standardEdit.rrtEnabled, false);
assert.equal(referenceEdit.rrtEnabled, true);
const boundedEdit = rrtEdit.pilotParameter("initialization_mode", "bounded");
assert.equal(boundedEdit.task("test", "bounded", frame).algorithm.pilot.initialization_mode, "bounded");
assert.equal(RoutingEdit.fromTask(boundedEdit.task("test", "bounded", frame)).pilotParameters.initialization_mode, "bounded");
assert.equal(boundedEdit.algorithmParameter("search_strategy", "standard").pilotParameters.initialization_mode, "legacy");
assert.equal(referenceEdit.pilotParameters.initialization_mode, defaults.routing.pilot.initialization_mode);
assert.equal(boundedEdit.pilotParameter("rrt_goal_bias", .95).task("test", "calibration", frame).algorithm.pilot.rrt_goal_bias, .95);
const legacy = { ...task, algorithm: { algorithm_name: "routing_nsga2", seed: 42 } };
assert.equal(RoutingEdit.fromTask(legacy).defaults(schema).task("test", "again", frame).algorithm.seed, 42);
assert.equal(RoutingEdit.fromTask(legacy).defaults(schema).algorithm.evolution_backend, defaults.routing.evolution_backend);
assert.throws(() => edit.copy({ algorithm: { ...edit.algorithm, seed: "" } }).task("test", "run", frame), /随机种子/);
assert.deepEqual(RoutingEdit.fromTask(task).task("test", "run", frame), task);
const smallBudget = edit.copy({ algorithm: { ...edit.algorithm, popsize: "48", max_generations: "16" } });
assert.equal(smallBudget.generationLimit, 16);
assert.equal(smallBudget.copy({ algorithm: { ...smallBudget.algorithm, max_generations: "17" } }).generationLimit, 17);
assert.equal(smallBudget.copy({ algorithm: { ...smallBudget.algorithm, max_generations: "" } }).generationLimit, null);
const restored = smallBudget.resetAlgorithm();
assert.deepEqual(restored.algorithm, defaults.routing);
assert.deepEqual(restored.start, smallBudget.start);
assert.deepEqual(restored.end, smallBudget.end);
assert.deepEqual(restored.values, smallBudget.values);
assert.deepEqual(restored.regions, smallBudget.regions);
assert.equal(smallBudget.algorithm.max_generations, "16");
assert.throws(() => edit.connection("end", edit.start).task("test", "run", frame), /重合/);
assert.throws(() => edit.picked("start", { x: -1, y: 8 }, frame));
const crossingRing = [{ x: 0, y: 0 }, { x: 20, y: 20 }, { x: 0, y: 20 }, { x: 20, y: 0 }];
const lineRing = [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 20, y: 0 }];
const validConcave = [{ x: 0, y: 0 }, { x: 20, y: 0 }, { x: 20, y: 20 }, { x: 10, y: 10 }, { x: 0, y: 20 }];
assert.doesNotThrow(() => validateRoutingPolygon([...validConcave, validConcave[0]]));
assert.throws(() => validateRoutingPolygon(crossingRing), /边界不能重叠或交叉/);
assert.throws(() => validateRoutingPolygon(lineRing), /面积|重叠/);
assert.throws(() => routingStroke(crossingRing), /边界不能重叠或交叉/);
assert.throws(() => edit.copy({ regions: [...edit.regions, { kind: "no_cross", points: crossingRing }] }).task("test", "run", frame), /禁跨越区域 3 无效/);
assert.throws(() => edit.copy({ regions: [{ kind: "no_tower", points: lineRing }] }).task("test", "run", frame), /禁落塔区域 1 无效/);

const solution = { id: "route-1", is_feasible: true, is_pareto: true, violations: {},
  objectives: { tower_count: 1, length_3d_m: 30, bend_sum_rad: .4, crossing_3d_m: 2 },
  points: [{ x: 4, y: 8, z: 0, role: "start" }, { x: 16, y: 12, z: 1, role: "tower" }, { x: 28, y: 8, z: 0, role: "end" }],
  spans: [], turns_deg: [], tower_slopes_deg: [] };
const bundle = { schema_version: 1, problem_type: "routing", scene_name: "test", frame: info, routes: [solution] };
const unsortedRoutes = [solution,
  { ...solution, id: "route-2", objectives: { tower_count: 2, length_3d_m: 20, bend_sum_rad: .8, crossing_3d_m: 1 } },
  { ...solution, id: "route-3", objectives: { tower_count: 1, length_3d_m: 40, bend_sum_rad: .2, crossing_3d_m: 3 } }];
const orderedIds = (sort) => sortRoutingSolutions(unsortedRoutes, sort).map(({ route }) => route.id);
assert.deepEqual(orderedIds(null), ["route-1", "route-2", "route-3"]);
assert.deepEqual(orderedIds({ objective: "tower_count", direction: "ascending" }), ["route-1", "route-3", "route-2"]);
assert.deepEqual(orderedIds({ objective: "tower_count", direction: "descending" }), ["route-2", "route-1", "route-3"]);
assert.deepEqual(orderedIds({ objective: "length_3d_m", direction: "ascending" }), ["route-2", "route-1", "route-3"]);
assert.deepEqual(orderedIds({ objective: "bend_sum_rad", direction: "ascending" }), ["route-3", "route-1", "route-2"]);
assert.deepEqual(orderedIds({ objective: "crossing_3d_m", direction: "descending" }), ["route-3", "route-1", "route-2"]);
assert.deepEqual(sortRoutingSolutions(unsortedRoutes, { objective: "length_3d_m", direction: "ascending" }).map((row) => row.index), [1, 0, 2]);
assert.deepEqual(unsortedRoutes.map((route) => route.id), ["route-1", "route-2", "route-3"]);
assert.deepEqual(nextRoutingSort(null, "tower_count"), { objective: "tower_count", direction: "ascending" });
assert.deepEqual(nextRoutingSort({ objective: "tower_count", direction: "ascending" }, "tower_count"), { objective: "tower_count", direction: "descending" });
assert.deepEqual(nextRoutingSort({ objective: "tower_count", direction: "descending" }, "length_3d_m"), { objective: "length_3d_m", direction: "ascending" });
const assistantContext = routingContext({ sceneName: "test", edit, selected: solution, resultStale: true,
  jobStatus: "succeeded", regionVisibility: { no_tower: false, no_cross: true } });
assert.equal(assistantContext.no_tower_count, 1);
assert.equal(assistantContext.no_cross_count, 1);
assert.equal(assistantContext.region_visibility.no_tower, false);
assert.equal(assistantContext.regions_local_m[0].kind, "no_tower");
assert.deepEqual(assistantContext.regions_local_m[0].points, edit.regions[0].points);
assert.equal(assistantContext.selected_route.result_stale, true);
assert.equal(assistantContext.selected_route.points_local_m.length, 3);
assert.equal(assistantContext.objective_units.bend_sum_rad, "弧度");
const attachedRoute = routingAttachment(assistantContext, { kind: "tower", pointIndex: 1 });
assistantContext.selected_route.points_local_m[1].x = 999;
assert.equal(attachedRoute.selected_route.points_local_m[1].x, 16, "attachment keeps the route as it was when clicked");
assert.deepEqual(attachedRoute.inspected_target, { kind: "tower", point_index: 1 });
assistantContext.selected_route.points_local_m[1].x = 16;
const chatTurns = [{ role: "user", content: "这个线路的指标是什么？", pose_id: "site-only" }];
const routedTurns = routingMessages(chatTurns, assistantContext);
assert.match(routingMessages(chatTurns, attachedRoute)[0].content, /"inspected_target":\{"kind":"tower","point_index":1\}/);
assert.equal(chatTurns[0].content, "这个线路的指标是什么？");
assert.equal(routedTurns[0].pose_id, undefined);
assert.match(routedTurns[0].content, /"tower_count":1/);
assert.match(routedTurns[0].content, /站址字段|站址策略/);
assert.match(routedTurns[0].content, /result_stale/);
const savedPreferences = new Map();
const preferenceStorage = { getItem: (key) => savedPreferences.get(key) ?? null, setItem: (key, value) => savedPreferences.set(key, value) };
assert.equal(readRoutingPreference(preferenceStorage), null);
const routePreference = { ...defaultRoutingPreference(), tower_count: 5, crossing_3d_m: 0 };
writeRoutingPreference(preferenceStorage, routePreference);
assert.deepEqual(readRoutingPreference(preferenceStorage), routePreference);
const preferenceTurns = routingMessages(chatTurns, assistantContext, readRoutingPreference(preferenceStorage));
assert.match(preferenceTurns[0].content, /用户设置的选线目标重要程度/);
assert.match(preferenceTurns[0].content, /"tower_count":5/);
assert.match(preferenceTurns[0].content, /不会改变搜索或自动排序/);
assert.doesNotMatch(routedTurns[0].content, /用户设置的选线目标重要程度/);
assert.throws(() => readRoutingPreference({ getItem: () => '{"tower_count":6}' }), /格式无效/);
assert.equal(parseRoutingResult(JSON.stringify(bundle), "test", info).routes.length, 1);
assert.throws(() => parseRoutingResult(JSON.stringify(bundle), "other", info), /当前场景/);
assert.throws(() => parseRoutingResult(JSON.stringify(bundle), "test", { ...info, width: 40 }), /网格/);
assert.throws(() => parseRoutingResult(JSON.stringify({ ...bundle, routes: [{ ...solution, spans: null }] }), "test", info), /报告无效/);
assert.throws(() => parseRoutingResult(JSON.stringify({ ...bundle, routes: [solution, solution] }), "test", info), /接点数据无效/);
const record = { name: "历史线路", summary: {}, artifacts: [
  { name: "routes.json", url: "/routes" }, { name: "resolved_config.json", url: "/config" },
] };
const scene = { id: "test", frame: info };
const texts = { "/routes": JSON.stringify(bundle), "/config": JSON.stringify(task) };
const loaded = await readRoutingExperiment(record, scene, async (url) => texts[url]);
assert.deepEqual(loaded.edit.defaults(schema).task("test", "run", frame), task);
assert.deepEqual(loaded.bundle, bundle);
assert.deepEqual(JSON.parse(routingJson(bundle, task)).task, task);
assert.match(routingCsv(bundle), /^\ufeff"线路编号"/);
assert.match(routingCsv(bundle), /"route-1"/);
assert.match(routingCsv(bundle), /""role"":""tower""/);
let picked = "";
let saved = false;
const commands = toolbarCommands({ tool: "pan", notify() {}, focusSite() {}, setTool() {},
  exportDisabled: false, onExportJson() { saved = true; } });
const routingCommands = routingToolbarCommands(commands, { busy: false, editDisabled: false, picking: null, beginPick: (kind) => { picked = kind; } });
assert.ok(routingCommands.some((item) => item.id === "new-scene"));
assert.ok(routingCommands.some((item) => item.id === "landuse-water"));
assert.ok(!routingCommands.some((item) => item.id === "pose-add"));
routingCommands.find((item) => item.id === "routing-no_cross").run();
assert.equal(picked, "no_cross");
const drawingCommands = routingToolbarCommands(commands, { busy: false, editDisabled: false, picking: "no_cross-box", beginPick() {} });
assert.equal(drawingCommands.find((item) => item.id === "pan").active, false);
assert.equal(drawingCommands.find((item) => item.id === "routing-no_cross-box").active, true);
assert.equal(routingCommands.find((item) => item.id === "pan").active, true);
assert.equal(routingRegionKind("no_cross-box"), "no_cross");
assert.deepEqual(routingRectangle({ x: 20, y: 12 }, { x: 10, y: 4 }),
  [{ x: 10, y: 4 }, { x: 20, y: 4 }, { x: 20, y: 12 }, { x: 10, y: 12 }]);
assert.throws(() => routingRectangle({ x: 3, y: 2 }, { x: 3, y: 5 }), /宽度和高度/);
assert.ok(routingStroke([{ x: 0, y: 0 }, { x: 20, y: 0 }, { x: 20, y: 20 }, { x: 0, y: 0 }]).length >= 3);
assert.throws(() => routingStroke([{ x: 0, y: 0 }, { x: 1, y: 1 }]), /画一圈/);
routingCommands.find((item) => item.id === "save-experiment").run();
assert.equal(saved, true);
const lockedCommands = routingToolbarCommands(commands, { busy: true, editDisabled: false, picking: null, beginPick() {} });
for (const id of ["import-data", "prepare-scene", "routing-start", "landuse-water"]) {
  assert.equal(lockedCommands.find((item) => item.id === id).disabled, true);
}
const preparingCommands = routingToolbarCommands(commands, { busy: true, allowStopPrepare: true, editDisabled: false, picking: null, beginPick() {} });
assert.equal(preparingCommands.find((item) => item.id === "prepare-scene").disabled, false);
assert.equal(preparingCommands.find((item) => item.id === "new-scene").disabled, true);
await assert.rejects(readRoutingExperiment(record, scene, async (url) =>
  url === "/config" ? JSON.stringify({ ...task, start: null }) : texts[url]), /接入点无效/);
await assert.rejects(readRoutingExperiment(record, scene, async (url) =>
  url === "/config" ? JSON.stringify({ ...task, scene_name: "other" }) : texts[url]), /当前场景不一致/);
await assert.rejects(readRoutingExperiment({ ...record, artifacts: record.artifacts.slice(0, 1) }, scene, async () => ""), /产物不完整/);
const state = { active: true, picking: false, start: { x: 4, y: 8 }, end: { x: 28, y: 8 }, regions: [], draft: [],
  routes: [solution], selectedId: solution.id, towerRadius: .4, onPick() {}, onSelect() {} };
const features = routingFeatures(frame, state).features;
assert.equal(features.filter((item) => item.geometry.type === "LineString").length, 1);
assert.equal(features.filter((item) => item.properties.kind === "footprint").length, 1);
const towerFeature = features.find((item) => item.properties.kind === "tower");
assert.equal(towerFeature.properties.route_id, solution.id);
assert.equal(towerFeature.properties.point_index, 1);
const hoverRoute = { ...solution, spans: [
  { horizontal_m: 12, length_3d_m: 12.5, crossing_3d_m: 1 },
  { horizontal_m: 12, length_3d_m: 13, crossing_3d_m: 2 },
], turns_deg: [8], tower_slopes_deg: [3] };
const hoverState = { ...state, routes: [hoverRoute], routeNumbers: { [solution.id]: 4 }, resultStale: true };
const project = (point) => point;
assert.equal(nearestRoutingSpan(hoverRoute, { x: 7, y: 9 }, project), 0);
assert.equal(nearestRoutingSpan(hoverRoute, { x: 25, y: 9 }, project), 1);
assert.equal(nearestRoutingSpan(solution, { x: 7, y: 9 }, project), null);
assert.match(routingHoverText({ kind: "route", route_id: solution.id }, hoverState, frame, 1), /线路 4[\s\S]*第 2 档[\s\S]*修改前[\s\S]*净空未校核/);
assert.match(routingHoverText(towerFeature.properties, hoverState, frame), /塔位 1[\s\S]*地面高程 1.0 m[\s\S]*水平转角 8.0°[\s\S]*塔基最大坡度 3.0°/);
assert.match(routingHoverText({ kind: "endpoint", endpoint: "start" }, hoverState, frame), /起点（当前接入点）[\s\S]*经度[\s\S]*纬度/);
assert.equal(routingHoverText({ kind: "tower", route_id: "missing", point_index: 1 }, hoverState, frame), null);
assert.equal(routingFeatures(frame, { ...state, active: false }).features.length, 0);
const regionFeatures = routingFeatures(frame, { ...state, regions: [{ kind: "no_cross", index: 3,
  points: [{ x: 2, y: 2 }, { x: 8, y: 2 }, { x: 8, y: 8 }] }] }).features;
assert.equal(regionFeatures.find((feature) => feature.properties.kind === "zone").properties.region_index, 3);
assert.equal(regionFeatures.find((feature) => feature.properties.kind === "zone").properties.color, "#ff5a6a");
for (const kind of ["no_tower", "no_cross"]) {
  const zone = routingFeatures(frame, { ...state, mode: kind, draft: [{ x: 1, y: 1 }, { x: 2, y: 2 }],
    regions: [{ kind, index: 0, points: [{ x: 2, y: 2 }, { x: 8, y: 2 }, { x: 8, y: 8 }] }] }).features;
  const color = kind === "no_tower" ? "#a96432" : "#ff5a6a";
  assert.ok(zone.filter((feature) => feature.properties.kind === "zone").every((feature) => feature.properties.color === color));
}
assert.deepEqual(regionFeatures.filter((feature) => feature.properties.kind === "endpoint").map((feature) => feature.properties.endpoint), ["start", "end"]);
let painted;
const source = { setData(data) { painted = data; } };
const fakeMap = {
  getSource() { return source; },
};
syncRoutingLayer(fakeMap, frame, state);
assert.equal(painted.features.filter((item) => item.properties.kind === "route").length, 1);
syncRoutingLayer(fakeMap, frame, null);
assert.equal(painted.features.length, 0, "clearing a routing layer must not leave a line on the shared map");
assert.equal(solution.objectives.length_3d_m, 30);
const generation = new SolutionGeneration(); const previous = generation.capture(); generation.advance();
assert.equal(generation.isCurrent(previous), false);
console.log("routing: coordinate inputs, separate zones, task roundtrip, result identity and map features passed");

const hybrid = new RoutingEdit().defaults(schema).algorithmParameter("search_strategy", "pilot_reference")
  .pilotParameter("initialization_mode", "hybrid").toggleRrt(true).toggleRrt(false);
assert.deepEqual(hybrid.pilotParameters.enabled_mechanisms, defaultMechanisms.filter((item) => item !== "rrt"));
assert.deepEqual(hybrid.pilotParameter("initialization_mode", "legacy").pilotParameters.enabled_mechanisms,
  defaultMechanisms.filter((item) => item !== "rrt" && item !== "astar"));

const fullEdit = RoutingEdit.fromTask({ ...task, algorithm: { ...referenceEdit.algorithm, pilot: {
  ...referenceEdit.pilotParameters, initialization_mode: "hybrid", enabled_mechanisms: ["astar", "rrt", "elite_local_search", "global_injection"] } } });
assert.match(fullEdit.mechanismSummary, /多尺度 A\*、RRT、精英 VNS、全局注入/);
assert.deepEqual(fullEdit.toggleRrt(false).pilotParameters.enabled_mechanisms, ["astar", "elite_local_search", "global_injection"]);
assert.equal(fullEdit.algorithmParameter("search_strategy", "standard").mechanismSummary, "未启用迁移组件");
