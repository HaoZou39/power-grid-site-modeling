import assert from "node:assert/strict";
import maplibre from "maplibre-gl";
import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import { readFileSync } from "node:fs";
import { RoutingEdit, commitExistingLine, nextExistingLineId } from "../../.tmp-routing/routing/routing_edit.js";
import { finiteEntries, formatFinite, horizontalTortuosity, nextRoutingSort, parseRoutingResult, retainedRoutingChoices, routingRouteNumbers, routeTortuosity, sortRoutingSolutions, visibleSpanColumns } from "../../.tmp-routing/routing/routing_result.js";
import { routingFeatures, syncRoutingLayer } from "../../.tmp-routing/routing/routing_layer.js";
import { siteFrameFromInfo } from "../../.tmp-routing/map/site_frame.js";
import { SolutionGeneration } from "../../.tmp-routing/map/solution_generation.js";
import { readRoutingExperiment } from "../../.tmp-routing/routing/routing_experiment.js";
import { routingCsv, routingJson } from "../../.tmp-routing/routing/routing_export.js";
import { routingToolbarCommands } from "../../.tmp-routing/routing/routing_toolbar.js";
import { routingRectangle, routingRegionKind, routingStroke } from "../../.tmp-routing/routing/routing_interaction.js";
import { validateRoutingPolygon } from "../../.tmp-routing/routing/routing_polygon.js";
import { routingCompareColor, routingComparison } from "../../.tmp-routing/routing/routing_compare.js";
import { nearestRoutingSpan, routingHoverText } from "../../.tmp-routing/routing/routing_hover.js";
import { routingAttachment, routingContext, routingMessages } from "../../.tmp-routing/agent/routing_context.js";
import { defaultRoutingPreference, readRoutingPreference, writeRoutingPreference } from "../../.tmp-routing/agent/routing_preference.js";
import { toolbarCommands } from "../../.tmp-routing/map/toolbar_commands.js";
import { DEFAULT_ROUTING_MODE, FILTERED_EMPTY_MESSAGE, HISTORICAL_FILTER_MESSAGE, LEGACY_PORTFOLIO_MESSAGE, ROUTING_MODES, parseRoutingPortfolio, readRoutingPortfolio, routingModeContent, routingFileRoutes } from "../../.tmp-routing/routing/routing_portfolio.js";
import { corridorMapRouteIds, groupRoutingCorridors, readCorridorSnapshot } from "../../.tmp-routing/routing/corridor_groups.js";

const defaults = JSON.parse(readFileSync(new URL("../../../config/default_config.json", import.meta.url), "utf8"));
const corridorRoute = (id, y, towerX) => ({ id, points: [{ x: 0, y: 0 }, { x: towerX, y }, { x: 100, y: 0 }] });
const corridorRoutes = [corridorRoute("a", 4, 45), corridorRoute("b", 5, 60), corridorRoute("c", 120, 50)];
const corridors = groupRoutingCorridors(corridorRoutes, { ...defaults.routing_result, corridor_max_diameter_m: 20 });
assert.deepEqual(corridors.groups.map((group) => group.member_route_ids), [["a", "b"], ["c"]]);
assert.equal(corridors.groups.length, 2);
assert.deepEqual(corridorMapRouteIds(corridors.groups, ["a", "b", "c"], "b", []), ["b", "c"]);
assert.deepEqual(corridorMapRouteIds(corridors.groups, ["a", "c"], "b", ["a"]), ["a", "c"]);
assert.deepEqual(corridorMapRouteIds(corridors.groups, ["a", "b", "c"], "b", ["c"], corridors.groups[0].id), ["a", "b"]);
assert.deepEqual(corridorMapRouteIds(corridors.groups, ["c"], "b", ["a"]), ["c"]);
assert.deepEqual(readCorridorSnapshot(corridors, corridorRoutes)?.groups, corridors.groups);
assert.equal(readCorridorSnapshot(corridors, corridorRoutes.slice(1)), null);
const cappedCorridors = groupRoutingCorridors(corridorRoutes, { ...defaults.routing_result, corridor_max_groups: 1, corridor_max_diameter_m: 1 });
assert.equal(cappedCorridors.groups.length, 1);
assert.ok(cappedCorridors.groups[0].max_pair_distance_m > 1);
const manyCorridors = Array.from({ length: 12 }, (_, index) => corridorRoute(`route-${index}`, index * 40, 50));
assert.equal(groupRoutingCorridors(manyCorridors, { ...defaults.routing_result, corridor_max_diameter_m: 1 }).groups.length, 6);
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
assert.equal(task.existing_line_crossing_buffer_m, defaults.routing.existing_line_crossing_buffer_m);
assert.deepEqual(task.existing_power_lines, []);
const openLine = commitExistingLine([{ x: 1, y: 1 }, { x: 1, y: 1 }, { x: 8, y: 4 }], frame);
assert.deepEqual(openLine, [{ x: 1, y: 1 }, { x: 8, y: 4 }]);
assert.throws(() => commitExistingLine([{ x: 1, y: 1 }], frame), /两个不同/);
assert.throws(() => commitExistingLine([{ x: 1, y: 1 }, { x: -1, y: 1 }], frame), /场景范围/);
const drawn = edit.copy({ existingLineBuffer: "0", existingLines: [
  { id: nextExistingLineId([]), points: openLine },
  { id: "existing-line-002", points: [{ x: 10, y: 2 }, { x: 12, y: 6 }, { x: 18, y: 6 }] },
] });
const savedLines = drawn.task("test", "lines", frame);
assert.equal(savedLines.existing_power_lines.length, 2);
assert.equal(savedLines.existing_line_crossing_buffer_m, 0);
assert.deepEqual(RoutingEdit.fromTask(savedLines).existingLines.map((line) => line.id), ["existing-line-001", "existing-line-002"]);
const previousTask = { ...task };
delete previousTask.existing_power_lines;
delete previousTask.existing_line_crossing_buffer_m;
assert.deepEqual(RoutingEdit.fromTask(previousTask).existingLines, []);
assert.equal(RoutingEdit.fromTask(previousTask).defaults(schema).existingLineBuffer, String(defaults.routing.existing_line_crossing_buffer_m));
assert.throws(() => edit.copy({ existingLineBuffer: "-1" }).task("test", "run", frame), /不能小于零/);
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
const chartOne = routingComparison(unsortedRoutes, ["route-1"]);
const chartTwo = routingComparison(unsortedRoutes, ["route-1", "route-2"]);
assert.deepEqual(chartOne[0].values, chartTwo[0].values, "adding a route must not change the chart scale");
assert.deepEqual(chartTwo[0].values, [0, .5, 1 / 3, .5]);
assert.deepEqual(chartTwo[1].values, [1, 0, 1, 0]);
assert.equal(chartTwo[0].color, routingCompareColor(0));
assert.deepEqual(routingComparison([solution], [solution.id])[0].values, [0, 0, 0, 0], "equal values must not divide by zero");
assert.deepEqual(routingComparison(unsortedRoutes, ["missing"]), []);
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
assert.match(routedTurns[0].content, /已有线路时必须先清空线路才能调整起终点/);
assert.match(routedTurns[0].content, /另存按当前约束重新评价/);
assert.match(routedTurns[0].content, /对比折线按全部可行线路逐目标归一化/);
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
assert.equal(parseRoutingResult(JSON.stringify({ ...bundle, routes: [{ ...solution, spans: null }] }), "test", info).routes[0].spans.length, 0);
assert.throws(() => parseRoutingResult(JSON.stringify({ ...bundle, routes: [{ ...solution, spans: { horizontal_m: 1 } }] }), "test", info), /报告无效/);
assert.throws(() => parseRoutingResult(JSON.stringify({ ...bundle, routes: [solution, solution] }), "test", info), /接点数据无效/);
const record = { name: "历史线路", summary: {}, artifacts: [
  { name: "routes.json", url: "/routes" }, { name: "resolved_config.json", url: "/config" },
] };
const scene = { id: "test", frame: info };
const texts = { "/routes": JSON.stringify(bundle), "/config": JSON.stringify(task) };
const loaded = await readRoutingExperiment(record, scene, async (url) => texts[url]);
assert.deepEqual(loaded.edit.defaults(schema).task("test", "run", frame), task);
assert.deepEqual(loaded.bundle, bundle);
const filterSnapshot = {
  schema_version: 1, problem_type: "routing", scene_name: "test", source_experiment_id: "removed-source",
  scene_version: { scene_revision: "old-revision" }, captured_at: "2026-11-19T00:00:00Z", scope: { display_mode: "all" },
  context: { frame: info, task }, candidates: [{ id: solution.id, original_number: 1, data: solution,
    geometry: { points: solution.points }, metrics: solution.objectives }], retained_ids: [solution.id],
  stages: [], display_sort: null,
};
const restoredFilter = await readRoutingExperiment({ artifacts: [{ name: "filter_snapshot.json", url: "/filter" }] }, scene,
  async (url) => { assert.equal(url, "/filter"); return JSON.stringify(filterSnapshot); });
assert.deepEqual(restoredFilter.bundle.routes, bundle.routes.map((route, index) => ({ ...route, number: index + 1 })));
assert.deepEqual(restoredFilter.filterSnapshot, filterSnapshot);
assert.deepEqual(restoredFilter.edit.defaults(schema).task("test", "run", frame), task);
await assert.rejects(readRoutingExperiment({ artifacts: [{ name: "filter_snapshot.json", url: "/filter" }] },
  { ...scene, frame: { ...info, width: 40 } }, async () => JSON.stringify(filterSnapshot)), /网格/);
const multiFilter = {
  ...filterSnapshot,
  candidates: [
    { id: "route-keep", original_number: 1, data: { ...solution, id: "route-keep", objectives: { ...solution.objectives, tower_count: 10 } },
      geometry: { points: solution.points }, metrics: { ...solution.objectives, tower_count: 10 } },
    { id: "route-drop", original_number: 2, data: { ...solution, id: "route-drop", objectives: { ...solution.objectives, tower_count: 40 } },
      geometry: { points: solution.points }, metrics: { ...solution.objectives, tower_count: 40 } },
  ],
  retained_ids: ["route-keep"],
  stages: [{ key: "tower_count", direction: "ascending", lower: 10, upper: 20, retained_count: 1 }],
  scope: { display_mode: "filtered", query: "" },
};
const multiRestored = await readRoutingExperiment({ artifacts: [{ name: "filter_snapshot.json", url: "/filter-multi" }] }, scene,
  async () => JSON.stringify(multiFilter));
assert.equal(multiRestored.bundle.routes.length, 2);
assert.deepEqual(multiRestored.filterSnapshot.retained_ids, ["route-keep"]);
assert.equal(multiRestored.filterSnapshot.scope.display_mode, "filtered");
assert.deepEqual(JSON.parse(routingJson(bundle, task)).task, task);
assert.match(routingCsv(bundle), /^\ufeff"线路编号"/);
assert.doesNotMatch(routingCsv(bundle), /route-1/);
assert.equal(JSON.parse(routingJson(bundle, task)).routes[0].number, 1);
assert.match(routingCsv(bundle), /""role"":""tower""/);
let picked = "";
let saved = false;
const commands = toolbarCommands({ tool: "pan", notify() {}, focusSite() {}, setTool() {},
  exportDisabled: false, saveExperimentDisabled: false, onSaveExperiment() { saved = true; } });
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
const fixedEndpoints = routingToolbarCommands(commands, { busy: false, editDisabled: false, endpointsLocked: true, picking: null, beginPick() {} });
for (const id of ["routing-start", "routing-end", "routing-adjust-endpoints"]) assert.equal(fixedEndpoints.find((item) => item.id === id).disabled, true);
assert.equal(fixedEndpoints.find((item) => item.id === "routing-no_cross").disabled, false);
const controlsSource = readFileSync(new URL("./routing_controls.tsx", import.meta.url), "utf8");
assert.match(controlsSource, /className="routing-pair"/, "保留新版双列布局");
assert.equal((controlsSource.match(/disabled=\{endpointsLocked\}/g) ?? []).length, 4, "起终点输入、点选和调整均受锁定控制");
const startButton = controlsSource.indexOf('className="primary" onClick={() => void start()}');
const clearButton = controlsSource.indexOf('<button type="button" onClick={clearRoutes} disabled={clearRoutesDisabled}>清空方案</button>');
assert.ok(startButton >= 0 && clearButton > startButton, "清空方案紧挨开始选线，并复用 clearRoutes");
assert.equal(controlsSource.includes('className="primary" onClick={clearRoutes}'), false);
assert.doesNotMatch(controlsSource, /读取选线历史/, "案例从文件菜单导入");
const controllerSource = readFileSync(new URL("./use_routing_controller.ts", import.meta.url), "utf8");
const clearBody = controllerSource.slice(controllerSource.indexOf("function clearRoutes()"), controllerSource.indexOf("function toggleCompared"));
assert.equal(controllerSource.includes("const clearRoutesDisabled = routingBusy || !endpointsLocked"), true);
assert.equal(clearBody.includes("setBundle(null)"), true);
assert.equal(clearBody.includes("setSelectedId(null)"), true);
assert.equal(clearBody.includes("setCompared([])"), true);
assert.equal(clearBody.includes("setEdit"), false);
assert.equal(clearBody.includes("deleteExperiment"), false);
const deselectBody = controllerSource.slice(controllerSource.indexOf("const deselectRoute = useCallback"), controllerSource.indexOf("const layer = useMemo"));
assert.equal(deselectBody.includes("setSelectedId(null)"), true);
assert.equal(deselectBody.includes("setInspection(null)"), true);
assert.equal(deselectBody.includes("setCompared"), false);
assert.equal(deselectBody.includes("setBundle"), false);
assert.equal(controllerSource.includes("setSelectedId(null);\n    setEdit(restored)"), true);
assert.equal(controllerSource.includes("setSelectedId(opening"), false);
assert.equal(controllerSource.includes("closeInspection: () => setInspection(null)"), true);
const resultsSource = readFileSync(new URL("./routing_results.tsx", import.meta.url), "utf8");
assert.equal(resultsSource.includes("state.deselectRoute()"), true);
assert.equal(resultsSource.includes("if (selectedId && !members.has(selectedId)) state.deselectRoute()"), true);
assert.doesNotMatch(resultsSource, /if \(selectedId && !members\.has\(selectedId\)\) state\.closeInspection\(\)/);
const worldMapSource = readFileSync(new URL("../map/world_map.tsx", import.meta.url), "utf8");
assert.equal(worldMapSource.includes("currentRouting.onDeselect?.()"), true);
const workspaceSource = readFileSync(new URL("../map/map_workspace.tsx", import.meta.url), "utf8");
assert.match(workspaceSource, /if \(routing\.pick \|\| tool !== "pan"\) \{ routing\.beginPick\(null\); selectTool\("pan"\); \}\s*else routing\.deselectRoute\(\);/);
const unavailable = toolbarCommands({ tool: "pan", notify() {}, focusSite() {}, setTool() {}, saveExperimentDisabled: true,
  saveExperimentDisabledReason: "结果尚未读取成功" }).find((item) => item.id === "save-experiment");
assert.equal(unavailable.title, "结果尚未读取成功");
const infeasible = { ...solution, id: "infeasible", is_feasible: false, is_pareto: false };
const retained = { ...bundle, routes: [solution, infeasible] };
assert.equal(retainedRoutingChoices(retained, { algorithm: "routing_nsga2" }).length, 1);
assert.equal(retainedRoutingChoices(retained, { algorithm: "routing_workspace_v2", is_case: true }).length, 2);
assert.equal(retainedRoutingChoices(retained, { algorithm: "routing_workspace" }).length, 2);
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
const existingFeatures = routingFeatures(frame, { ...state, mode: "existing_line", existingLines: [{ id: "existing-line-001", points: openLine }],
  draft: [{ x: 2, y: 2 }], cursor: { x: 6, y: 3 } }).features;
assert.equal(existingFeatures.filter((item) => item.properties.kind === "existing-line").length, 2);
assert.equal(existingFeatures.find((item) => item.properties.line_id === "existing-line-001").properties.color, "#e6a817");
assert.equal(features.filter((item) => item.geometry.type === "LineString").length, 1);
assert.equal(features.filter((item) => item.properties.kind === "footprint").length, 1);
const towerFeature = features.find((item) => item.properties.kind === "tower");
assert.equal(towerFeature.properties.route_id, solution.id);
assert.equal(towerFeature.properties.point_index, 1);
const allFeatures = routingFeatures(frame, { ...state, routes: unsortedRoutes, selectedId: "route-1", compared: ["route-2", "route-3"] }).features;
const allLines = allFeatures.filter((item) => item.properties.kind === "route");
assert.equal(allLines.length, unsortedRoutes.length, "every feasible route is drawn without being selected");
assert.equal(allLines.find((item) => item.properties.route_id === "route-2").properties.color, routingCompareColor(0));
assert.equal(allLines.find((item) => item.properties.route_id === "route-3").properties.color, routingCompareColor(1));
assert.equal(allLines.at(-1).properties.route_id, "route-1", "selected line is drawn above others");
const selectedWithCrossing = { ...solution, existing_line_crossings: [{ x: 12, y: 8 }] };
const selectedPaint = routingFeatures(frame, { ...state, routes: [selectedWithCrossing], selectedId: solution.id,
  towerRouteIds: [] }).features;
assert.equal(selectedPaint.find((item) => item.properties.kind === "route").properties.color, "#49e4cf");
assert.equal(selectedPaint.filter((item) => item.properties.kind === "tower").length, 1);
assert.equal(selectedPaint.filter((item) => item.properties.kind === "existing-crossing").length, 1);
const clearedPaint = routingFeatures(frame, { ...state, routes: [selectedWithCrossing], selectedId: null,
  towerRouteIds: [] }).features;
assert.equal(clearedPaint.find((item) => item.properties.kind === "route").properties.color, "#ba9cfa");
assert.equal(clearedPaint.filter((item) => item.properties.kind === "tower").length, 0);
assert.equal(clearedPaint.filter((item) => item.properties.kind === "existing-crossing").length, 0);
assert.equal(routingFeatures(frame, { ...state, routes: [selectedWithCrossing], selectedId: null,
  towerRouteIds: [solution.id] }).features.filter((item) => item.properties.kind === "tower").length, 1);
const corridorFeatures = routingFeatures(frame, { ...state, routes: unsortedRoutes, selectedId: null, compared: [],
  corridorView: { bands: [{ id: "a", routes: [{ id: solution.id, points: solution.points }] }],
    paddingM: 12, focusedGroupId: "a", showTowerDensity: true } }).features;
assert.equal(corridorFeatures.filter((feature) => feature.properties.kind === "corridor-density").length, 1);
assert.equal(corridorFeatures.filter((feature) => feature.properties.kind === "corridor-tower-density").length, 1);
assert.equal(corridorFeatures.find((feature) => feature.properties.route_id === "route-2" && feature.properties.kind === "route").properties.opacity, .8);
const focusedTowers = routingFeatures(frame, { ...state, routes: unsortedRoutes.slice(0, 2), selectedId: null,
  towerRouteIds: ["route-1", "route-2"], corridorView: {
    bands: [], paddingM: 12, focusedGroupId: "a", showTowerDensity: false,
  } }).features.filter((feature) => feature.properties.kind === "tower");
assert.deepEqual(focusedTowers.map((feature) => feature.properties.route_id), ["route-1", "route-2"]);
const hoverRoute = { ...solution, spans: [
  { horizontal_m: 12, length_3d_m: 12.5, crossing_3d_m: 1 },
  { horizontal_m: 12, length_3d_m: 13, crossing_3d_m: 2 },
], turns_deg: [8], tower_slopes_deg: [3] };
const hoverState = { ...state, routes: [hoverRoute], routeNumbers: { [solution.id]: 4 }, resultStale: true };
const project = (point) => point;
assert.equal(nearestRoutingSpan(hoverRoute, { x: 7, y: 9 }, project), 0);
assert.equal(nearestRoutingSpan(hoverRoute, { x: 25, y: 9 }, project), 1);
assert.equal(nearestRoutingSpan(solution, { x: 7, y: 9 }, project), null);
const hoverText = routingHoverText({ kind: "route", route_id: solution.id }, hoverState, frame, 1);
assert.match(hoverText, /线路 4[\s\S]*第 2 档[\s\S]*修改前/);
assert.equal(hoverText.includes("净空未校核"), false);
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
const mapLayers = new Map([
  ["routing-boundaries", { filter: ["!=", ["get", "kind"], "route"] }],
  ["routing-points", { filter: ["==", ["geometry-type"], "Point"] }],
]);
const fakeMap = {
  getSource() { return source; },
  getLayer(id) { return mapLayers.get(id); },
  addLayer(layer, before) { assert.equal(before, "routing-boundaries"); mapLayers.set(layer.id, layer); },
  getFilter(id) { return mapLayers.get(id).filter; },
  setFilter(id, filter) { mapLayers.get(id).filter = filter; },
  getPaintProperty(id, key) { return mapLayers.get(id).paint?.[key]; },
  setPaintProperty(id, key, value) { (mapLayers.get(id).paint ??= {})[key] = value; },
};
syncRoutingLayer(fakeMap, frame, { ...state, corridorView: { bands: [], paddingM: 12, focusedGroupId: null, showTowerDensity: false } });
const densityWidth = fakeMap.getPaintProperty("routing-corridor-density", "line-width");
const leftWorld = maplibre.MercatorCoordinate.fromLngLat(frame.localToLngLat({ x: 0, y: 0 }));
const rightWorld = maplibre.MercatorCoordinate.fromLngLat(frame.localToLngLat({ x: 24, y: 0 }));
const projectedDiameter = Math.hypot(rightWorld.x - leftWorld.x, rightWorld.y - leftWorld.y) * 512 * 2 ** 8;
assert.ok(Math.abs(densityWidth[4] / projectedDiameter - 1) < .005, "corridor diameter agrees with 24 local metres in MapLibre pixels");
assert.ok(JSON.stringify(fakeMap.getFilter("routing-boundaries")).includes("corridor-density"), "hot reload excludes density bands from outlines");
assert.ok(JSON.stringify(fakeMap.getFilter("routing-points")).includes("corridor-tower-density"), "hot reload keeps heatmap samples out of tower markers");
assert.deepEqual(validateStyleMin({ version: 8,
  sources: { routing: { type: "geojson", data: { type: "FeatureCollection", features: [] } } },
  layers: [mapLayers.get("routing-tower-density"), mapLayers.get("routing-corridor-density")],
}), [], "corridor density layers pass MapLibre style validation");
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

function previewRoute(id, x, tower) {
  return { id, objectives: { tower_count: tower, length_3d_m: 1000 + x, bend_sum_rad: 0.1, crossing_3d_m: 10 + x },
    is_feasible: true, is_pareto: true, violations: {}, points: [{ x, y: 0, z: null, role: "start" }, { x, y: 8, z: null, role: "tower" }, { x, y: 16, z: null, role: "end" }],
    spans: [{ horizontal_m: 8, length_3d_m: null, crossing_3d_m: null }, { horizontal_m: 8, length_3d_m: null, crossing_3d_m: null }],
    turns_deg: [1], tower_slopes_deg: [null] };
}
const previewRoutes = [previewRoute("E1-151929", 0, 9), previewRoute("E1-145323", 90, 9), previewRoute("E1-119812", 200, 5)];
const previewText = JSON.stringify({ schema_version: 1, problem_type: "routing", scene_name: "scene", frame: info, routes: previewRoutes });
const groupsText = JSON.stringify({ groups: [
  { group_id: "group-E1-151929", representative_route_id: "E1-151929", member_route_ids: ["E1-151929", "E1-145323"], member_count: 2, group_risk_flags: ["TOWER_OFFSET", "CROSSING_OBJECTS_DATA_MISSING"], engineering_review_status: "NOT_REVIEWED", max_tower_offset_m: 93.4 },
  { group_id: "group-E1-119812", representative_route_id: "E1-119812", member_route_ids: ["E1-119812"], member_count: 1, group_risk_flags: ["CROSSING_OBJECTS_DATA_MISSING"], engineering_review_status: "NOT_REVIEWED", max_tower_offset_m: 0 },
] });
const manifestText = JSON.stringify({
  schema_version: 1, status: "complete", all_pareto_count: 3, a5_group_count: 2,
  filtered_count: 2, filtered_route_ids: ["E1-151929", "E1-119812"], max_tortuosity: 1.5,
});
const portfolio = parseRoutingPortfolio(manifestText, previewText, groupsText, null, "scene", info);
assert.equal(portfolio.counts.filtered, 2);
assert.equal(routingFileRoutes(portfolio, bundle.routes).length, 2);
assert.equal(routingFileRoutes({ ...portfolio, filteredRouteIds: [] }, bundle.routes).length, 0);
assert.equal(routingFileRoutes({ ...portfolio, filteredRouteIds: null }, bundle.routes).length, 0);
assert.equal(routingFileRoutes({ ...portfolio, status: "failed" }, bundle.routes).length, 0);
assert.equal(routingFileRoutes(null, bundle.routes).length, bundle.routes.length);
const numbers = routingRouteNumbers(portfolio.routes);
assert.deepEqual(Object.values(numbers), [1, 2, 3]);
const fileRoutes = routingFileRoutes(portfolio, bundle.routes);
assert.deepEqual(fileRoutes.map((route) => route.id), portfolio.filteredRouteIds);
const imageFeatures = routingFeatures(frame, { ...state, active: true, routes: fileRoutes, start: null, end: null, regions: [], draft: [], towerRouteIds: fileRoutes.map((route) => route.id) });
assert.deepEqual(new Set(imageFeatures.features.filter((feature) => feature.properties.kind === "route").map((feature) => feature.properties.route_id)), new Set(portfolio.filteredRouteIds));
const fileBundle = { ...bundle, routes: fileRoutes };
const fileJson = JSON.parse(routingJson(fileBundle, task));
assert.deepEqual(fileJson.routes.map((route) => route.number), fileRoutes.map((route) => numbers[route.id]));
assert.deepEqual(routingCsv(fileBundle).trim().split("\r\n").slice(1).map((row) => Number(row.split(",")[0].replaceAll('"', ''))), fileRoutes.map((route) => numbers[route.id]));
assert.deepEqual(routingRouteNumbers(fileJson.routes), Object.fromEntries(fileRoutes.map((route) => [route.id, route.number])));
const numberedBundle = { ...bundle, routes: [{ ...bundle.routes[0], number: 38 }] };
assert.equal(JSON.parse(routingJson(numberedBundle, task)).routes[0].number, 38);
assert.equal(routingRouteNumbers(parseRoutingResult(routingJson(numberedBundle, task), bundle.scene_name, info).routes)[numberedBundle.routes[0].id], 38);
assert.match(routingCsv(numberedBundle).split("\r\n")[1], /^"38",/);
assert.deepEqual(routingRouteNumbers([portfolio.routes[2]], [{ id: portfolio.routes[2].id, original_number: 42 }]), { [portfolio.routes[2].id]: 42 });
assert.deepEqual(routingModeContent(portfolio, "all", { query: "线路 2", page: 0, sort: null, pinnedIds: [] }).allRoutes.map((route) => route.id), [portfolio.routes[1].id]);
assert.equal(portfolio.counts.all, 3);
const filtered = routingModeContent(portfolio, "filtered", { query: "", page: 0, sort: null, pinnedIds: ["E1-119812"] });
assert.deepEqual(filtered.rows.map((route) => route.id), ["E1-151929", "E1-119812"]);
assert.equal(filtered.rows.some((route) => route.id === "E1-145323"), false);
assert.equal(filtered.mapRoutes.find((route) => route.id === "E1-151929").points[1].x, 0);
const many = Array.from({ length: 1000 }, (_, index) => previewRoute(`route-${index}`, index, index));
const filteredIds = many.slice(0, 60).map((route) => route.id);
const manyPortfolio = parseRoutingPortfolio(
  JSON.stringify({ schema_version: 1, status: "complete", all_pareto_count: 1000, a5_group_count: 60, filtered_count: 60, filtered_route_ids: filteredIds, max_tortuosity: 1.5 }),
  JSON.stringify({ schema_version: 1, problem_type: "routing", scene_name: "scene", frame: info, routes: many }),
  JSON.stringify({ groups: filteredIds.map((id) => ({ group_id: `group-${id}`, representative_route_id: id, member_route_ids: [id], member_count: 1, group_risk_flags: [], engineering_review_status: "NOT_REVIEWED", max_tower_offset_m: 0 })) }),
  null,
  "scene", info,
);
const started = performance.now();
const page = routingModeContent(manyPortfolio, "all", { query: "route-999", page: 0, sort: null, pinnedIds: ["route-0"] });
assert.ok(performance.now() - started < 200);
assert.equal(page.matchedCount, 1);
assert.equal(page.mapRoutes.length, 2);
const filteredStarted = performance.now();
const filteredPage = routingModeContent(manyPortfolio, "filtered", { query: "", page: 0, sort: null, pinnedIds: ["route-999"] });
assert.ok(performance.now() - filteredStarted < 200);
assert.equal(filteredPage.matchedCount, 60);
assert.equal(filteredPage.pageCount, 2);
assert.equal(filteredPage.mapRoutes.length, 51);
assert.equal(filteredPage.rows.some((route) => route.id === "route-60"), false);
const legacyPortfolio = parseRoutingPortfolio(JSON.stringify({ schema_version: 1, status: "legacy_published_only", message: "旧文案" }), null, null, null, "scene", info);
assert.equal(legacyPortfolio.routes.length, 0);
assert.equal(legacyPortfolio.message, LEGACY_PORTFOLIO_MESSAGE);
assert.equal(legacyPortfolio.counts.all, null);
assert.equal(legacyPortfolio.counts.filtered, null);
const historical = parseRoutingPortfolio(
  JSON.stringify({ schema_version: 1, status: "complete", all_pareto_count: 3, a5_group_count: 2, recommended_count: 1 }),
  previewText, groupsText, null, "scene", info,
);
assert.equal(historical.counts.all, 3);
assert.equal(historical.counts.filtered, null);
assert.equal(historical.filteredRouteIds, null);
assert.equal(routingModeContent(historical, "all", { query: "", page: 0, sort: null, pinnedIds: [] }).matchedCount, 3);
assert.equal(HISTORICAL_FILTER_MESSAGE.includes("不能把当时的相似线路组当作筛选方案"), true);
assert.equal(FILTERED_EMPTY_MESSAGE, "当前条件下无符合要求的线路");
const missingManifest = await readRoutingPortfolio({ artifacts: [] }, { id: "scene", frame: info }, async () => { throw new Error("不应读取"); });
assert.equal(missingManifest.status, "legacy_published_only");
assert.equal(missingManifest.message, LEGACY_PORTFOLIO_MESSAGE);
assert.deepEqual(ROUTING_MODES.map((mode) => mode.label), ["筛选方案", "帕累托解"]);
assert.equal(DEFAULT_ROUTING_MODE, "filtered");
assert.equal(ROUTING_MODES[0].id, DEFAULT_ROUTING_MODE);
const resultsUi = readFileSync(new URL("./routing_results.tsx", import.meta.url), "utf8");
assert.equal(resultsUi.includes("推荐方案"), false);
assert.equal(resultsUi.includes("查看组内"), false);
assert.equal(resultsUi.includes("组成员"), false);
assert.equal(resultsUi.includes("仅展示曲折系数"), false);
assert.equal(resultsUi.includes("线路曲折系数"), false);
const idsBefore = portfolio.routes.map((route) => route.id);
const pointsBefore = JSON.stringify(portfolio.routes.map((route) => route.points));
for (const mode of ROUTING_MODES) {
  const view = routingModeContent(portfolio, mode.id, { query: "", page: 0, sort: null, pinnedIds: [] });
  assert.ok(view.rows.every((route) => idsBefore.includes(route.id)));
  assert.deepEqual(portfolio.routes.map((route) => route.id), idsBefore);
  assert.equal(JSON.stringify(portfolio.routes.map((route) => route.points)), pointsBefore);
}
const pareto = routingModeContent(portfolio, "all", { query: "", page: 0, sort: null, pinnedIds: [] });
assert.equal(pareto.matchedCount, 3);
assert.deepEqual(pareto.rows.map((route) => route.id), idsBefore);
const limitHeight = 25 * Math.sqrt(5);
assert.equal(horizontalTortuosity([{ x: 0, y: 0 }, { x: 100, y: 0 }]), 1);
assert.ok(Math.abs(horizontalTortuosity([{ x: 0, y: 0 }, { x: 50, y: limitHeight }, { x: 100, y: 0 }]) - 1.5) < 1e-12);
assert.ok(horizontalTortuosity([{ x: 0, y: 0 }, { x: 0, y: 80 }, { x: 100, y: 0 }]) > 1.5);
assert.equal(horizontalTortuosity([{ x: 0, y: 0 }, { x: 0, y: 0 }]), null);
assert.deepEqual(routeTortuosity({ ...previewRoutes[0], tortuosity_status: "invalid", tortuosity_k: null }), { status: "invalid", k: null });
assert.equal(routeTortuosity(previewRoutes[0]).k, 1);
const straight = previewRoute("straight", 0, 4);
straight.points = [{ x: 0, y: 0, z: null, role: "start" }, { x: 100, y: 0, z: null, role: "end" }];
const bent = previewRoute("bent", 1, 8);
bent.points = [{ x: 0, y: 0, z: null, role: "start" }, { x: 0, y: 80, z: null, role: "tower" }, { x: 100, y: 0, z: null, role: "end" }];
const invalid = { ...previewRoute("invalid", 2, 3), tortuosity_status: "invalid", tortuosity_k: null };
assert.deepEqual(sortRoutingSolutions([bent, invalid, straight], { objective: "tortuosity_k", direction: "ascending" }).map((row) => row.route.id), ["straight", "bent", "invalid"]);
assert.deepEqual(sortRoutingSolutions([straight, bent], { objective: "tortuosity_k", direction: "descending" }).map((row) => row.route.id), ["bent", "straight"]);
assert.deepEqual(nextRoutingSort({ objective: "tortuosity_k", direction: "ascending" }, "tortuosity_k"), { objective: "tortuosity_k", direction: "descending" });
const partialSpans = [
  { horizontal_m: 165.4, length_3d_m: null, crossing_3d_m: null },
  { horizontal_m: 0, length_3d_m: null, crossing_3d_m: 12 },
];
assert.deepEqual(visibleSpanColumns(partialSpans).map((column) => column.key), ["horizontal_m", "crossing_3d_m"]);
assert.deepEqual(visibleSpanColumns([{ horizontal_m: 1, length_3d_m: null, crossing_3d_m: undefined }]).map((column) => column.label), ["水平 m"]);
assert.equal(formatFinite(0), "0.0");
assert.equal(formatFinite(null), "");
assert.equal(formatFinite(undefined), "");
assert.equal(formatFinite(Number.NaN), "");
assert.deepEqual(finiteEntries([null, 0, undefined, Number.NaN, 12.5]), [{ index: 2, text: "0.0" }, { index: 5, text: "12.5" }]);
assert.equal(finiteEntries([null, undefined, Number.NaN]).length, 0);
const sparse = JSON.parse(previewText);
sparse.routes[0].spans = partialSpans;
sparse.routes[0].turns_deg = [0, null];
sparse.routes[0].tower_slopes_deg = [null, null];
delete sparse.routes[1].spans;
delete sparse.routes[1].turns_deg;
delete sparse.routes[1].tower_slopes_deg;
const parsedSparse = parseRoutingResult(JSON.stringify(sparse), "scene", info);
assert.equal(parsedSparse.routes[0].spans[1].horizontal_m, 0);
assert.equal(parsedSparse.routes[0].spans[0].length_3d_m, null);
assert.deepEqual(parsedSparse.routes[1].spans, []);
assert.deepEqual(parsedSparse.routes[0].turns_deg, [0, null]);
sparse.routes[0].spans[0].length_3d_m = "缺失";
assert.throws(() => parseRoutingResult(JSON.stringify(sparse), "scene", info), /逐档或塔基/);
const bareHover = { ...hoverRoute, spans: [{ horizontal_m: 165.4, length_3d_m: null, crossing_3d_m: null }], turns_deg: [0], tower_slopes_deg: [null] };
const bareText = routingHoverText({ kind: "route", route_id: solution.id }, { ...hoverState, routes: [bareHover] }, frame, 0);
assert.equal(bareText.split("\n").find((line) => line.startsWith("第 1 档")), "第 1 档：水平 165.4 m");
assert.doesNotMatch(bareText, /无数据|缺失/);
const bareTower = routingHoverText(towerFeature.properties, { ...hoverState, routes: [bareHover] }, frame);
assert.match(bareTower, /水平转角 0.0°/);
assert.doesNotMatch(bareTower, /无数据|缺失|坡度/);
