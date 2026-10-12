import assert from "node:assert/strict";
import { BuildingFootprint } from "../../.tmp-problem-snapshot/map/building_footprint.js";
import { BuildingSize, Nsga2DecisionRun, JobFollowUp, ParetoSelection, angleDegreesToRadians, choiceStatus, formatObjective, isChoiceEdited, moveChoice, radiansToDegrees, restoreChoice, rotateChoice } from "../../.tmp-problem-snapshot/map/decision_run.js";
import { ExclusionSketch, simplifyStroke } from "../../.tmp-problem-snapshot/map/exclusion_sketch.js";
import { hiddenLanduseClasses, toolbarCommands } from "../../.tmp-problem-snapshot/map/toolbar_commands.js";
import { MapShortcuts } from "../../.tmp-problem-snapshot/map/map_shortcuts.js";

const size = BuildingSize.parse("80", "50");
assert.equal(size.widthM, 80);
assert.throws(() => BuildingSize.parse("0", "50"), /大于 0/);

const request = new Nsga2DecisionRun(unusedCatalog()).createRequest(size, "cangnan", new Date("2026-10-10T12:03:04"));
assert.equal(request.plugin_id, "site.nsga2");
assert.equal(request.config.experiment_name, "site-20261010-120304");
assert.equal(request.config.scene_name, "cangnan");
assert.equal(request.config.rect_w_m, 80);
assert.equal(request.config.rect_h_m, 50);
assert.equal(request.config.mountain_policy, "allowed");
assert.equal(request.config.field_policy, "allowed");
assert.equal(request.config.field_cost, 0.5);
assert.deepEqual(request.config.exclusion_zones, []);
assert.equal("objective_weights" in request.config, false);
assert.equal("seed" in request.config, false);
const withZone = new Nsga2DecisionRun(unusedCatalog()).createRequest(size, "cangnan", new Date("2026-10-10T12:03:04"), {
  fieldPolicy: "costly",
  mountainPolicy: "blocked",
  fieldCost: 0.5,
  exclusionZones: [{ points: [[1, 1], [3, 1], [2, 3]] }],
});
assert.equal(withZone.config.field_policy, "costly");
assert.equal(withZone.config.exclusion_zones.length, 1);

const solutions = [
  "run_id,x,y,theta,dem_soft,road_distance,demand_distance,is_feasible",
  "a,10,20,0.5,1.5,30,40,True",
  "b,1,2,0,9,9,9,False",
  "c,3,4,,1,1,1,True",
].join("\n");
const pareto = ["run_id", "a", "b", "c"].join("\n");
const loaded = await new Nsga2DecisionRun({
  async getExperiments() {
    return [{
      id: "site-1",
      artifacts: [
        { name: "solutions.csv", kind: "table", url: "solutions" },
        { name: "pareto_solutions.csv", kind: "table", url: "pareto" },
      ],
    }];
  },
  async fetchArtifactText(url) {
    return url === "pareto" ? pareto : solutions;
  },
}).loadPareto("site-1");
assert.equal(loaded.length, 1);
assert.equal(loaded[0].id, "a");
assert.equal(loaded[0].roadDistance, "30");
assert.equal(loaded[0].demSoft, "1.5");
assert.deepEqual(loaded[0].original, { x: 10, y: 20, theta: 0.5 });
assert.equal(formatObjective("38.9281005859375"), "38.9");
assert.equal(formatObjective("655.6527709960938"), "655.7");
assert.equal(formatObjective("26.49708366394043"), "26.5");
assert.equal(formatObjective("未提供"), "未提供");

const selection = new ParetoSelection(loaded, 0).step(1).step(-1).select("missing");
assert.equal(selection.selected?.id, "a");

const footprint = BuildingFootprint.layer(loaded, size, 0)[0];
assert.equal(footprint.selected, true);
const corners = footprint.corners();
assert.equal(corners.length, 4);
assert.ok(corners.every((corner) => Number.isFinite(corner.x) && Number.isFinite(corner.y)));

const follow = new JobFollowUp();
assert.equal(JobFollowUp.isActive("running"), true);
assert.equal(follow.claimExperiment(job("running")), null);
assert.equal(follow.claimExperiment(job("succeeded", { data: { experiment_id: "site-1" } })), "site-1");
assert.equal(follow.claimExperiment(job("succeeded", { data: { experiment_id: "site-1" } })), null);
assert.match(follow.failureNotice(job("failed")) ?? "", /CUDA/);

let called = "";
const shortcuts = new MapShortcuts(() => ({
  drawing: true,
  pan: () => { called = "pan"; },
  draw: () => { called = "draw"; },
  focus: () => { called = "focus"; },
  closeDraft: () => { called = "close"; },
  cancelDraft: () => { called = "cancel"; },
  undoPoint: () => { called = "undo"; },
  previous: () => { called = "previous"; },
  next: () => { called = "next"; },
  optimize: () => { called = "optimize"; },
}));
shortcuts.handle(keyEvent("p"));
assert.equal(called, "optimize");
shortcuts.handle(keyEvent("p", "INPUT"));
assert.equal(called, "optimize");
shortcuts.handle(keyEvent("["));
assert.equal(called, "previous");

const sketch = new ExclusionSketch().addPoint({ x: 1, y: 1 }).addPoint({ x: 2, y: 1 }).addPoint({ x: 2, y: 2 });
assert.equal(sketch.close().zones.length, 1);
assert.equal(sketch.addPoint({ x: 1.5, y: 1.2 }).zones.length, 1);
assert.throws(() => new ExclusionSketch().close(), /三个顶点/);
const stroke = [
  { x: 0, y: 0 }, { x: 1, y: 0.1 }, { x: 2, y: 0 }, { x: 10, y: 0 },
  { x: 10, y: 10 }, { x: 0, y: 10 }, { x: 0.2, y: 0.2 },
];
const loop = new ExclusionSketch().finishStroke(stroke);
assert.equal(loop.zones.length, 1);
assert.equal(loop.draft.length, 0);
assert.ok(loop.zones[0].points.length >= 3);
assert.ok(loop.zones[0].points.length < stroke.length);
assert.ok(simplifyStroke(stroke, 4).length < stroke.length);

assert.deepEqual(hiddenLanduseClasses(), { field: false, building: false, road: false, water: false });
let toolbarNote = "";
const shown = hiddenLanduseClasses();
const commands = toolbarCommands({
  tool: "pan",
  shownClasses: shown,
  notify: (message) => { toolbarNote = message; },
  focusSite: () => undefined,
  setTool: () => undefined,
  toggleClass: (id) => { shown[id] = !shown[id]; },
});
commands.find((command) => command.id === "import-data").run();
commands.find((command) => command.id === "import-case").run();
assert.match(toolbarNote, /尚未接入/);
commands.find((command) => command.id === "show-field").run();
assert.equal(shown.field, true);
assert.equal(shown.building, false);
assert.deepEqual([...new Set(commands.map((command) => command.group))], ["文件", "主页", "视图", "编辑"]);
assert.deepEqual(commands.filter((command) => command.quick).map((command) => command.id), ["focus-site", "pan", "draw", "pick"]);
assert.ok(commands.some((command) => command.id === "adjust" && command.label === "调整方案"));
let adjustTool = "pan";
commands.find((command) => command.id === "adjust").run();
assert.equal(adjustTool, "pan");
assert.match(toolbarNote, /先点一个方案矩形/);
const armed = toolbarCommands({
  tool: "pan",
  shownClasses: shown,
  notify: (message) => { toolbarNote = message; },
  focusSite: () => undefined,
  setTool: (next) => { adjustTool = next; },
  toggleClass: () => undefined,
  hasSelection: true,
});
armed.find((command) => command.id === "adjust").run();
assert.equal(adjustTool, "adjust");

const sample = {
  id: "a", x: 100, y: 120, theta: 0, demSoft: "1.5", roadDistance: "30",
  demandDistance: "40", roadHaul: "未提供", offroadHaul: "12", haulRise: "1", feasible: "可行",
  original: { x: 100, y: 120, theta: 0 },
};
const fromCsv = choiceStatus(sample, null);
assert.equal(fromCsv.filter((row) => row.label === "进场（m）").length, 1);
assert.equal(fromCsv.find((row) => row.label === "进场（m）").value, "12");
assert.equal(fromCsv.some((row) => row.label === "进场坡度（°）"), false);
const adjusted = moveChoice(sample, 5, -4, size);
const fromReport = choiceStatus(adjusted, {
  demSoft: 1.2,
  roadDistance: 26,
  demandDistance: 42,
  obstacleHardCount: 3,
  isFeasible: false,
  offroadHaulM: 8.2,
  haulRiseM: 0.4,
  accessSlopeDeg: 3.2,
  accessWarning: true,
});
assert.equal(fromReport.filter((row) => row.label === "进场（m）").length, 1);
assert.equal(fromReport.find((row) => row.label === "进场（m）").value, "12 → 8.2");
assert.equal(fromReport.find((row) => row.label === "进场高差（m）").value, "1 → 0.4");
assert.equal(fromReport.find((row) => row.label === "道路距离（m）").value, "30 → 26");
assert.equal(fromReport.find((row) => row.label === "可行性").value, "可行 → 不可行");
assert.equal(fromReport.find((row) => row.label === "禁建覆盖格数").value, "3");
assert.match(fromReport.find((row) => row.label === "进场坡度（°）").value, /偏陡/);

assert.equal(adjusted.x, 105);
assert.equal(adjusted.y, 116);
assert.equal(adjusted.theta, sample.theta);
assert.equal(isChoiceEdited(adjusted), true);
const clamped = moveChoice({ ...sample, x: 1790, y: 10 }, 50, -40, size);
assert.equal(clamped.x, 1760);
assert.equal(clamped.y, 25);

const rightAngle = angleDegreesToRadians(450);
assert.ok(Math.abs(rightAngle - Math.PI / 2) < 1e-12);
assert.ok(Math.abs(radiansToDegrees(rightAngle) - 90) < 1e-12);
const rotated = rotateChoice(sample, rightAngle, size);
assert.equal(rotated.theta, rightAngle);
assert.throws(
  () => rotateChoice({ ...sample, x: 30, y: 30 }, Math.PI / 4, size),
  /超出规划区域/,
);
assert.deepEqual(restoreChoice(adjusted), sample);
assert.equal(isChoiceEdited(restoreChoice(adjusted)), false);

const selectionEdit = new ParetoSelection([sample], 0)
  .moveSelected(5, -4, size)
  .rotateSelected(rightAngle, size)
  .restoreSelected();
assert.deepEqual(selectionEdit.selected, sample);

console.log("decision map assertions passed");

function unusedCatalog() {
  return {
    async getExperiments() { return []; },
    async fetchArtifactText() { return ""; },
  };
}

function job(status, result = null) {
  return {
    job_id: "job-1",
    status,
    message: status === "failed" ? "CUDA unavailable" : "",
    result,
    error: status === "failed" ? { message: "CUDA unavailable" } : null,
  };
}

function keyEvent(key, tagName = "DIV") {
  return { key, target: { tagName }, preventDefault() {} };
}
