import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { RoutingEdit } from "../../.tmp-routing/routing/routing_edit.js";
import { parseRoutingResult } from "../../.tmp-routing/routing/routing_result.js";
import { routingFeatures } from "../../.tmp-routing/routing/routing_layer.js";
import { siteFrameFromInfo } from "../../.tmp-routing/map/site_frame.js";
import { SolutionGeneration } from "../../.tmp-routing/map/solution_generation.js";

const defaults = JSON.parse(readFileSync(new URL("../../../config/default_config.json", import.meta.url), "utf8"));
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
const rrtEdit = referenceEdit.toggleRrt(true);
assert.equal(rrtEdit.rrtEnabled, true);
assert.deepEqual(rrtEdit.task("test", "rrt", frame).algorithm.pilot.enabled_mechanisms, ["rrt"]);
assert.equal(RoutingEdit.fromTask(rrtEdit.task("test", "rrt", frame)).rrtEnabled, true);
assert.equal(rrtEdit.algorithmParameter("search_strategy", "standard").rrtEnabled, false);
assert.equal(referenceEdit.rrtEnabled, false);
const legacy = { ...task, algorithm: { algorithm_name: "routing_nsga2", seed: 42 } };
assert.equal(RoutingEdit.fromTask(legacy).defaults(schema).task("test", "again", frame).algorithm.seed, 42);
assert.equal(RoutingEdit.fromTask(legacy).defaults(schema).algorithm.evolution_backend, defaults.routing.evolution_backend);
assert.throws(() => edit.copy({ algorithm: { ...edit.algorithm, seed: "" } }).task("test", "run", frame), /随机种子/);
assert.deepEqual(RoutingEdit.fromTask(task).task("test", "run", frame), task);
const smallBudget = edit.copy({ algorithm: { ...edit.algorithm, popsize: "48", max_evaluations: "768" } });
assert.equal(smallBudget.generationLimit, 16);
assert.equal(smallBudget.copy({ algorithm: { ...smallBudget.algorithm, max_evaluations: "769" } }).generationLimit, 17);
assert.equal(smallBudget.copy({ algorithm: { ...smallBudget.algorithm, popsize: "" } }).generationLimit, null);
const restored = smallBudget.resetAlgorithm();
assert.deepEqual(restored.algorithm, defaults.routing);
assert.deepEqual(restored.start, smallBudget.start);
assert.deepEqual(restored.end, smallBudget.end);
assert.deepEqual(restored.values, smallBudget.values);
assert.deepEqual(restored.regions, smallBudget.regions);
assert.equal(smallBudget.algorithm.max_evaluations, "768");
assert.throws(() => edit.connection("end", edit.start).task("test", "run", frame), /重合/);
assert.throws(() => edit.picked("start", { x: -1, y: 8 }, frame));

const solution = { id: "route-1", is_feasible: true, is_pareto: true, violations: {},
  objectives: { tower_count: 1, length_3d_m: 30, bend_sum_rad: .4, crossing_3d_m: 2 },
  points: [{ x: 4, y: 8, z: 0, role: "start" }, { x: 16, y: 12, z: 1, role: "tower" }, { x: 28, y: 8, z: 0, role: "end" }],
  spans: [], turns_deg: [], tower_slopes_deg: [] };
const bundle = { schema_version: 1, problem_type: "routing", scene_name: "test", frame: info, routes: [solution] };
assert.equal(parseRoutingResult(JSON.stringify(bundle), "test", info).routes.length, 1);
assert.throws(() => parseRoutingResult(JSON.stringify(bundle), "other", info), /当前场景/);
assert.throws(() => parseRoutingResult(JSON.stringify(bundle), "test", { ...info, width: 40 }), /网格/);
const state = { active: true, picking: false, start: { x: 4, y: 8 }, end: { x: 28, y: 8 }, regions: [], draft: [],
  routes: [solution], selectedId: solution.id, towerRadius: .4, onPick() {}, onSelect() {} };
const features = routingFeatures(frame, state).features;
assert.equal(features.filter((item) => item.geometry.type === "LineString").length, 1);
assert.equal(features.filter((item) => item.properties.kind === "footprint").length, 1);
assert.equal(routingFeatures(frame, { ...state, active: false }).features.length, 0);
assert.equal(solution.objectives.length_3d_m, 30);
const generation = new SolutionGeneration(); const previous = generation.capture(); generation.advance();
assert.equal(generation.isCurrent(previous), false);
console.log("routing: coordinate inputs, separate zones, task roundtrip, result identity and map features passed");
