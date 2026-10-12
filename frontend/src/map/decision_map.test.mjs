import assert from "node:assert/strict";
import { BuildingFootprint } from "../../.tmp-problem-snapshot/map/building_footprint.js";
import { BuildingSize, Nsga2DecisionRun, JobFollowUp, ParetoSelection, buildingSizeFromResolvedConfig, choiceStatus, formatObjective, moveChoice } from "../../.tmp-problem-snapshot/map/decision_run.js";
import { ExclusionSketch, simplifyStroke } from "../../.tmp-problem-snapshot/map/exclusion_sketch.js";
import { SiteEdit } from "../../.tmp-problem-snapshot/map/site_edit.js";
import { hiddenLanduseClasses, toolbarCommands } from "../../.tmp-problem-snapshot/map/toolbar_commands.js";
import { MapShortcuts } from "../../.tmp-problem-snapshot/map/map_shortcuts.js";

const size = BuildingSize.parse("80", "50");
assert.equal(size.widthM, 80);
assert.throws(() => BuildingSize.parse("0", "50"), /大于 0/);

const blank = new SiteEdit("cangnan", size.widthM, size.heightM);
const request = new Nsga2DecisionRun(unusedCatalog()).createRequest(blank, new Date("2026-10-10T12:03:04"));
assert.equal(request.plugin_id, "site.nsga2");
assert.equal(request.config.experiment_name, "site-20261010-120304");
assert.equal(request.config.scene_name, "cangnan");
assert.equal(request.config.rect_w_m, 80);
assert.equal(request.config.rect_h_m, 50);
assert.equal(request.config.mountain_policy, "allowed");
assert.equal(request.config.field_policy, "allowed");
assert.equal(request.config.field_cost, 0.5);
assert.deepEqual(request.config.exclusion_zones, []);
assert.deepEqual(request.config.feasible_zones, []);
assert.equal("objective_weights" in request.config, false);
assert.equal("seed" in request.config, false);
const withZone = new Nsga2DecisionRun(unusedCatalog()).createRequest(
  blank.withPolicies("blocked", "costly", 0.5).addExclusion([{ x: 1, y: 1 }, { x: 3, y: 1 }, { x: 2, y: 3 }]),
  new Date("2026-10-10T12:03:04"),
);
assert.equal(withZone.config.field_policy, "costly");
assert.equal(withZone.config.mountain_policy, "blocked");
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
let imported = false;
const withImport = toolbarCommands({
  tool: "pan",
  shownClasses: shown,
  notify: () => undefined,
  focusSite: () => undefined,
  setTool: () => undefined,
  toggleClass: () => undefined,
  historyOpen: true,
  onImportCase: () => { imported = true; },
});
assert.equal(withImport.find((command) => command.id === "import-case").active, true);
withImport.find((command) => command.id === "import-case").run();
assert.equal(imported, true);
const importedSize = buildingSizeFromResolvedConfig({ modeling: { rect_w_m: 77, rect_h_m: 51.5 } });
assert.equal(importedSize.widthM, 77);
assert.equal(importedSize.heightM, 51.5);
assert.equal(buildingSizeFromResolvedConfig({}), null);
assert.equal(buildingSizeFromResolvedConfig({ modeling: { rect_w_m: 0, rect_h_m: 10 } }), null);
commands.find((command) => command.id === "show-field").run();
assert.equal(shown.field, true);
assert.equal(shown.building, false);
assert.deepEqual([...new Set(commands.map((command) => command.group))], ["文件", "主页", "视图", "编辑"]);
assert.deepEqual(commands.filter((command) => command.quick).map((command) => command.id), ["focus-site", "pan", "pick"]);
assert.ok(commands.some((command) => command.id === "exclusion" && command.label === "禁区" && command.quick === false));
assert.ok(commands.some((command) => command.id === "feasible" && command.label === "可行域" && command.quick === false));
assert.ok(commands.some((command) => command.id === "erase" && command.label === "橡皮擦" && command.quick === false));
assert.equal(commands.some((command) => command.label === "画圈"), false);
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
  id: "a", x: 10, y: 20, theta: 0.5, demSoft: "1.5", roadDistance: "30",
  demandDistance: "40", roadHaul: "未提供", offroadHaul: "12", haulRise: "1", feasible: "可行",
};
const fromCsv = choiceStatus(sample, null);
assert.equal(fromCsv.filter((row) => row.label === "进场（m）").length, 1);
assert.equal(fromCsv.find((row) => row.label === "进场（m）").value, "12");
assert.equal(fromCsv.some((row) => row.label === "进场坡度（°）"), false);
const fromReport = choiceStatus(sample, { offroadHaulM: 8.2, haulRiseM: 0.4, accessSlopeDeg: 3.2, accessWarning: true });
assert.equal(fromReport.filter((row) => row.label === "进场（m）").length, 1);
assert.equal(fromReport.find((row) => row.label === "进场（m）").value, "8.2");
assert.equal(fromReport.find((row) => row.label === "进场高差（m）").value, "0.4");
assert.match(fromReport.find((row) => row.label === "进场坡度（°）").value, /偏陡/);

const moved = moveChoice(sample, 5, -4);
assert.equal(moved.x, 15);
assert.equal(moved.y, 16);
assert.equal(moved.theta, sample.theta);
const clamped = moveChoice({ ...sample, x: 1790, y: 10 }, 50, -40);
assert.equal(clamped.x, 1800);
assert.equal(clamped.y, 0);

const drawn = blank.finishStroke([
  { x: 10, y: 10 }, { x: 11, y: 10 }, { x: 40, y: 10 }, { x: 40, y: 40 }, { x: 10, y: 40 },
]);
const picked = drawn.addExclusion([{ x: 80, y: 80 }, { x: 100, y: 80 }, { x: 90, y: 110 }]);
const mixed = new Nsga2DecisionRun(unusedCatalog()).createRequest(picked, new Date("2026-10-10T12:03:04"));
assert.equal(mixed.config.exclusion_zones.length, 2);
assert.equal("kind" in mixed.config.exclusion_zones[0], false);
assert.equal("kind" in mixed.config.exclusion_zones[1], false);
assert.equal(picked.replaceDraft([{ x: 1, y: 1 }, { x: 2, y: 2 }]).searchConfig().exclusion_zones.length, 2);
const erased = picked.removeRegion(picked.zones[0].id);
assert.equal(erased.zones.length, 1);
assert.equal(erased.searchConfig().exclusion_zones.length, 1);
const limited = blank.addFeasible([{ x: 10, y: 10 }, { x: 40, y: 10 }, { x: 20, y: 40 }]);
const both = limited.addExclusion([{ x: 80, y: 80 }, { x: 100, y: 80 }, { x: 90, y: 110 }]);
assert.equal(both.searchConfig().feasible_zones.length, 1);
assert.equal(both.searchConfig().exclusion_zones.length, 1);
const droppedFeasible = both.removeRegion(both.zones.find((zone) => zone.kind === "feasible").id);
assert.equal(droppedFeasible.searchConfig().feasible_zones.length, 0);
assert.equal(droppedFeasible.searchConfig().exclusion_zones.length, 1);
const again = erased.addExclusion([{ x: 2, y: 2 }, { x: 6, y: 2 }, { x: 4, y: 6 }]);
assert.equal(again.zones.length, 2);
assert.equal(new Set(again.zones.map((zone) => zone.id)).size, 2);

const marked = blank.putOrigin({ x: 100, y: 200 });
assert.equal(marked.searchConfig().origin_x, 100);
assert.equal(marked.searchConfig().origin_y, 200);
assert.equal("origin_x" in blank.searchConfig(), false);

const posed = marked.withPoses([sample]).addExclusion([{ x: 4, y: 4 }, { x: 8, y: 4 }, { x: 6, y: 9 }]);
const report = posed.reportRequest();
assert.equal(report.x, 10);
assert.equal(report.theta, 0.5);
assert.equal(report.origin_x, 100);
assert.equal("exclusion_zones" in report, false);
const dragged = posed.moveSelected(5, -4);
assert.equal(dragged.reportRequest().x, 15);
assert.equal(dragged.reportRequest().y, 16);
assert.equal(dragged.poses[0].theta, sample.theta);
assert.equal(dragged.poses[0].demSoft, sample.demSoft);

assert.throws(() => blank.putOrigin({ x: -1, y: 10 }), /选址范围/);
assert.throws(() => blank.addExclusion([{ x: 1, y: 1 }, { x: 2, y: 2 }]), /三个顶点/);
assert.throws(() => new SiteEdit("cangnan", 80, 50, "allowed", "allowed", 0.5, [{ id: "m", kind: "depot", x: 1, y: 1 }]).searchConfig(), /不认识的标记/);
assert.throws(() => new SiteEdit("cangnan", 80, 50, "allowed", "allowed", 0.5, [], [{ id: "z", kind: "buffer", ring: [{ x: 1, y: 1 }, { x: 2, y: 1 }, { x: 2, y: 2 }] }]).searchConfig(), /不认识的范围/);

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
