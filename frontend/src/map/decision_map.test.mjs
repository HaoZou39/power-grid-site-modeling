import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { BuildingFootprint } from "../../.tmp-problem-snapshot/map/building_footprint.js";
import { BuildingSize, GuidedDecisionRun, JobFollowUp, ParetoSelection, angleDegreesToRadians, buildingSizeFromResolvedConfig, choiceStatus, compareChart, formatObjective, isChoiceEdited, measuredChoice, moveChoice, radiansToDegrees, restoreChoice, rotateChoice, schemeCard, widthAzimuthDeg } from "../../.tmp-problem-snapshot/map/decision_run.js";
import { ExclusionSketch, simplifyStroke } from "../../.tmp-problem-snapshot/map/exclusion_sketch.js";
import { SiteEdit } from "../../.tmp-problem-snapshot/map/site_edit.js";
import { hiddenLanduseClasses, landuseEditClass, toolbarCommands } from "../../.tmp-problem-snapshot/map/toolbar_commands.js";
import { MapShortcuts } from "../../.tmp-problem-snapshot/map/map_shortcuts.js";
import { SolutionGeneration } from "../../.tmp-problem-snapshot/map/solution_generation.js";

const layerPanelSource = readFileSync(new URL("./layer_panel.tsx", import.meta.url), "utf8");
const mapWorkspaceSource = readFileSync(new URL("./map_workspace.tsx", import.meta.url), "utf8");
const worldMapSource = readFileSync(new URL("./world_map.tsx", import.meta.url), "utf8");
const siteOverlaySource = readFileSync(new URL("./site_overlay.tsx", import.meta.url), "utf8");
const stylesSource = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
assert.equal(layerPanelSource.includes("原始 DEM 空间分辨率"), false);
assert.equal(layerPanelSource.includes("formatResolution"), false);
assert.equal(layerPanelSource.includes('className="landuse-layer-grid"'), true);
assert.match(stylesSource, /\.landuse-layer-grid \{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/);
assert.match(stylesSource, /@media \(max-width: 520px\) \{ \.landuse-layer-grid \{ grid-template-columns: 1fr; \} \}/);
assert.equal(layerPanelSource.includes('title="建设约束分析"'), true);
assert.equal(layerPanelSource.includes('label="建设可行性"'), true);
assert.equal(layerPanelSource.includes('label="手绘禁区"'), true);
assert.equal(layerPanelSource.includes('label="手绘可行域"'), true);
assert.equal(layerPanelSource.includes('基于当前建设规则的 1 m 格网，不代表完整站址可行。'), false);
assert.match(mapWorkspaceSource, /useState\(false\).*feasibilityVisible|feasibilityVisible.*useState\(false\)/s);
assert.equal(mapWorkspaceSource.includes("fetchConstructionFeasibilityOverlay"), true);
assert.equal(mapWorkspaceSource.includes("URL.revokeObjectURL"), true);
assert.equal(siteOverlaySource.includes("source.updateImage"), true);
assert.equal(siteOverlaySource.includes('map.getLayer("forbidden-fill") ? "forbidden-fill" : "site-frame-fill"'), true);
assert.equal(mapWorkspaceSource.includes("originPlace.lng"), true);
assert.equal(mapWorkspaceSource.includes("originPlace.lat"), true);
assert.equal(mapWorkspaceSource.includes("已清除进货原点，按 Ctrl+Z 可恢复。"), true);
assert.equal(mapWorkspaceSource.includes("JSON.stringify(latestConfig) !== configKey"), true);
assert.equal(mapWorkspaceSource.includes("function clearDisplayedSolutions("), true);
assert.equal(mapWorkspaceSource.includes('setNotice("已清空当前方案，历史优化结果已保留。")'), true);
assert.equal(mapWorkspaceSource.includes("onClearSolutions={clearDisplayedSolutionsFromUi}"), true);
assert.equal(mapWorkspaceSource.includes("onClick={clearDisplayedSolutionsFromUi}"), true);
assert.equal(mapWorkspaceSource.includes("solutionGeneration.current.isCurrent"), true);
assert.equal(mapWorkspaceSource.includes("if (applied.clearPoses) {\n      clearDisplayedSolutions();"), true);
assert.equal(mapWorkspaceSource.includes("clearSolutionsDisabled={running || edit.poses.length === 0}"), true);
assert.equal(mapWorkspaceSource.includes("disabled={running || edit.poses.length === 0}>清空方案"), true);
const clearBody = mapWorkspaceSource.slice(
  mapWorkspaceSource.indexOf("function clearDisplayedSolutions("),
  mapWorkspaceSource.indexOf("function finishStroke("),
);
for (const preservedStateSetter of [
  "setScene(", "setShownClasses(", "setLanduseEdits(", "setRegionVisibility(", "setDemVisible(", "setRoadsVisible(",
  "clearLanduseEdits(", "deleteExperiment(",
]) {
  assert.equal(clearBody.includes(preservedStateSetter), false);
}
assert.ok(worldMapSource.indexOf('map.getLayer("origin-dot")') < worldMapSource.indexOf('map.getLayer("forbidden-fill")'));
assert.equal(worldMapSource.includes("点击删除进货原点"), true);
assert.equal(siteOverlaySource.includes("originHovered"), true);

const size = BuildingSize.parse("80", "50");
assert.equal(size.widthM, 80);
assert.throws(() => BuildingSize.parse("0", "50"), /大于 0/);

const blank = new SiteEdit("cangnan", size.widthM, size.heightM);
const request = new GuidedDecisionRun(unusedCatalog()).createRequest(blank, new Date("2026-10-10T12:03:04"));
assert.equal(request.plugin_id, "site.guided_search");
assert.equal(request.config.experiment_name, "site-20261010-120304");
assert.equal(request.config.scene_name, "cangnan");
assert.equal(request.config.rect_w_m, 80);
assert.equal(request.config.rect_h_m, 50);
assert.equal(request.config.mountain_policy, "allowed");
assert.equal(request.config.field_policy, "allowed");
assert.equal(request.config.field_cost, 0.5);
assert.deepEqual(request.config.exclusion_zones, []);
assert.deepEqual(request.config.feasible_zones, []);
assert.equal(request.config.include_demand, false);
assert.equal("objective_weights" in request.config, false);
assert.equal("seed" in request.config, false);
const withZone = new GuidedDecisionRun(unusedCatalog()).createRequest(
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
const loaded = await new GuidedDecisionRun({
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
  undoErase: () => { called = "undo-erase"; },
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
shortcuts.handle({ ...keyEvent("z"), ctrlKey: true });
assert.equal(called, "undo-erase");
shortcuts.handle({ ...keyEvent("z", "INPUT"), ctrlKey: true });
assert.equal(called, "undo-erase");

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
  notify: (message) => { toolbarNote = message; },
  focusSite: () => undefined,
  setTool: () => undefined,
});
commands.find((command) => command.id === "import-data").run();
commands.find((command) => command.id === "import-case").run();
assert.match(toolbarNote, /尚未接入/);
let imported = false;
const withImport = toolbarCommands({
  tool: "pan",
  notify: () => undefined,
  focusSite: () => undefined,
  setTool: () => undefined,
  historyOpen: true,
  onImportCase: () => { imported = true; },
});
assert.equal(withImport.find((command) => command.id === "import-case").active, true);
withImport.find((command) => command.id === "import-case").run();
assert.equal(imported, true);
let clearedSolutions = false;
const withClear = toolbarCommands({
  tool: "pan",
  notify: () => undefined,
  focusSite: () => undefined,
  setTool: () => undefined,
  clearSolutionsDisabled: false,
  onClearSolutions: () => { clearedSolutions = true; },
});
const clearCommand = withClear.find((command) => command.id === "clear-solutions");
assert.equal(clearCommand.label, "清空方案");
assert.equal(clearCommand.group, "主页");
assert.equal(clearCommand.disabled, false);
clearCommand.run();
assert.equal(clearedSolutions, true);
assert.equal(toolbarCommands({
  tool: "pan",
  notify: () => undefined,
  focusSite: () => undefined,
  setTool: () => undefined,
  clearSolutionsDisabled: true,
}).find((command) => command.id === "clear-solutions").disabled, true);
const importedSize = buildingSizeFromResolvedConfig({ modeling: { rect_w_m: 77, rect_h_m: 51.5 } });
assert.equal(importedSize.widthM, 77);
assert.equal(importedSize.heightM, 51.5);
assert.equal(buildingSizeFromResolvedConfig({}), null);
assert.equal(buildingSizeFromResolvedConfig({ modeling: { rect_w_m: 0, rect_h_m: 10 } }), null);
assert.equal(commands.some((command) => command.id.startsWith("show-")), false);
assert.deepEqual([...new Set(commands.map((command) => command.group))], ["文件", "主页", "视图", "编辑", "设置"]);
assert.deepEqual(commands.filter((command) => command.quick).map((command) => command.id), ["focus-site", "pan"]);
assert.equal(commands.some((command) => command.id === "pick"), false);
assert.equal(commands.find((command) => command.id === "software-update").group, "设置");
assert.equal(commands.find((command) => command.id === "software-update").quick, false);
assert.equal(commands.find((command) => command.id === "agent-settings").group, "设置");
assert.equal(commands.find((command) => command.id === "agent-settings").quick, false);
assert.ok(commands.some((command) => command.id === "exclusion" && command.label === "画圈"));
assert.ok(commands.some((command) => command.id === "exclusion-box" && command.label === "方框"));
assert.ok(commands.some((command) => command.id === "feasible" && command.label === "画圈"));
assert.ok(commands.some((command) => command.id === "feasible-box" && command.label === "方框" && command.active === false));
assert.equal(commands.filter((command) => command.label === "画圈").length, 2);
assert.equal(commands.filter((command) => command.label === "方框").length, 2);
assert.equal(commands.some((command) => command.id === "box"), false);
const feasibleBox = toolbarCommands({
  tool: "feasible-box",
  notify: () => undefined,
  focusSite: () => undefined,
  setTool: () => undefined,
});
assert.equal(feasibleBox.find((command) => command.id === "feasible-box").active, true);
assert.equal(feasibleBox.find((command) => command.id === "feasible").active, false);
assert.ok(commands.some((command) => command.id === "erase" && command.label === "橡皮擦"));
assert.ok(commands.some((command) => command.id === "adjust" && command.label === "调整方案"));
assert.equal(landuseEditClass("landuse-field"), "field");
assert.equal(landuseEditClass("landuse-building"), "building");
assert.equal(landuseEditClass("landuse-water"), "water");
assert.equal(landuseEditClass("pan"), null);
const unavailableLanduse = toolbarCommands({
  tool: "landuse-building",
  notify: () => undefined,
  focusSite: () => undefined,
  setTool: () => undefined,
  landuseEditDisabled: { field: true, building: true, water: false },
});
assert.equal(unavailableLanduse.find((command) => command.id === "landuse-building").active, true);
assert.equal(unavailableLanduse.find((command) => command.id === "landuse-building").disabled, true);
assert.equal(unavailableLanduse.find((command) => command.id === "landuse-water").disabled, false);
let adjustTool = "pan";
commands.find((command) => command.id === "adjust").run();
assert.equal(adjustTool, "pan");
assert.match(toolbarNote, /先点一个方案矩形/);
const armed = toolbarCommands({
  tool: "pan",
  notify: (message) => { toolbarNote = message; },
  focusSite: () => undefined,
  setTool: (next) => { adjustTool = next; },
  hasSelection: true,
});
armed.find((command) => command.id === "adjust").run();
assert.equal(adjustTool, "adjust");

const sample = {
  id: "a", x: 100, y: 120, theta: 0, demSoft: "1.5", roadDistance: "30",
  demandDistance: "40", roadHaul: "未提供", offroadHaul: "12", haulRise: "1", obstacleHardCount: "0", feasible: "可行",
  original: { x: 100, y: 120, theta: 0 },
  baseline: {
    demSoft: "1.5", roadDistance: "30", demandDistance: "40", roadHaul: "未提供",
    offroadHaul: "12", haulRise: "1", obstacleHardCount: "0", feasible: "可行",
  },
};
const fromCsv = choiceStatus(sample, null);
assert.equal(fromCsv.filter((row) => row.label === "进站长度（m）").length, 1);
assert.equal(fromCsv.find((row) => row.label === "进站长度（m）").value, "12");
assert.equal(fromCsv.some((row) => row.label === "进站坡度（°）"), false);
const card = schemeCard(sample, null, false);
assert.equal(card.decisions.some((row) => row.label === "中心位置（m）"), false);
assert.equal(card.decisions.some((row) => row.label === "旋转角度"), false);
assert.equal(card.decisions.find((row) => row.label === "方位角（宽边）").value, "90.0°");
const adjusted = moveChoice(sample, 5, -4, size);
const adjustedMeasured = measuredChoice(adjusted, {
  dem_soft: 1.2,
  road_distance: 26,
  demand_distance: 42,
  road_haul_m: "",
  offroad_haul_m: 8.2,
  haul_rise_m: 0.4,
  obstacle_hard_count: 3,
  is_feasible: false,
});
const fromReport = choiceStatus(adjustedMeasured, {
  offroadHaulM: 8.2,
  haulRiseM: 0.4,
  accessSlopeDeg: 3.2,
  accessWarning: true,
});
assert.equal(fromReport.filter((row) => row.label === "进站长度（m）").length, 1);
assert.equal(fromReport.find((row) => row.label === "进站长度（m）").value, "12 → 8.2");
assert.equal(fromReport.find((row) => row.label === "进站累计高差（m）").value, "1 → 0.4");
assert.equal(fromReport.find((row) => row.label === "道路距离（m）").value, "30 → 26");
assert.equal(fromReport.find((row) => row.label === "可行性").value, "可行 → 不可行");
assert.equal(fromReport.find((row) => row.label === "禁建覆盖格数").value, "0 → 3");
assert.match(fromReport.find((row) => row.label === "进站坡度（°）").value, /偏陡/);

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

assert.ok(Math.abs(widthAzimuthDeg(0) - 90) < 1e-9);
assert.ok(Math.abs(widthAzimuthDeg(Math.PI / 2) - 180) < 1e-9);
assert.ok(Math.abs(widthAzimuthDeg(-Math.PI / 2)) < 1e-9);
const chartItems = [
  { id: "a", name: "方案 1", choice: { ...sample, demSoft: "1", demandDistance: "10", offroadHaul: "3", haulRise: "2", roadHaul: "未提供", roadDistance: "5" } },
  { id: "b", name: "方案 2", choice: { ...sample, id: "b", demSoft: "3", demandDistance: "4", offroadHaul: "9", haulRise: "2", roadHaul: "未提供", roadDistance: "8" } },
];
const chart = compareChart(chartItems);
assert.equal(chart.labels.includes("沿路"), false);
assert.equal(chart.labels.includes("需求"), false);
assert.equal(chart.series[0].values[0], 0);
assert.equal(chart.series[1].values[0], 1);
assert.equal(chart.series[0].values[chart.labels.indexOf("高差")], 0);
const withDemand = compareChart(chartItems, chartItems.map((item) => item.choice), true);
assert.equal(withDemand.labels.includes("需求"), true);
assert.equal(withDemand.series[1].values[withDemand.labels.indexOf("需求")], 0);
const roadItems = chartItems.map((item, index) => ({
  ...item,
  choice: { ...item.choice, roadHaul: String(20 + index * 5) },
}));
assert.equal(compareChart(roadItems, roadItems.map((item) => item.choice), false, true).labels.includes("沿路"), true);
assert.equal(compareChart(roadItems, roadItems.map((item) => item.choice), false, false).labels.includes("沿路"), false);
const scale = chartItems.map((item) => item.choice);
const firstOnly = compareChart([chartItems[0]], scale);
const withSecondLine = compareChart(chartItems, scale);
assert.deepEqual(firstOnly.series[0].values, withSecondLine.series[0].values);

const drawn = blank.finishStroke([
  { x: 10, y: 10 }, { x: 11, y: 10 }, { x: 40, y: 10 }, { x: 40, y: 40 }, { x: 10, y: 40 },
]);
const picked = drawn.addExclusion([{ x: 80, y: 80 }, { x: 100, y: 80 }, { x: 90, y: 110 }]);
const mixed = new GuidedDecisionRun(unusedCatalog()).createRequest(picked, new Date("2026-10-10T12:03:04"));
assert.equal(mixed.config.exclusion_zones.length, 2);
assert.equal("kind" in mixed.config.exclusion_zones[0], false);
assert.equal("kind" in mixed.config.exclusion_zones[1], false);
assert.equal(picked.replaceDraft([{ x: 1, y: 1 }, { x: 2, y: 2 }]).searchConfig().exclusion_zones.length, 2);
const erased = picked.removeRegion(picked.zones[0].id);
assert.equal(erased.zones.length, 1);
assert.equal(erased.searchConfig().exclusion_zones.length, 1);
const restored = erased.restoreRegion(picked.regions[0]);
assert.equal(restored.zones.length, 2);
assert.deepEqual(restored.regions.at(-1).ring, picked.regions[0].ring);
const boxed = blank.addRectangle("exclusion", { x: 30, y: 40 }, { x: 10, y: 20 });
assert.deepEqual(boxed.zones[0].points, [
  { x: 10, y: 20 }, { x: 30, y: 20 }, { x: 30, y: 40 }, { x: 10, y: 40 },
]);
assert.equal(boxed.searchConfig().exclusion_zones.length, 1);
assert.equal(boxed.searchConfig().feasible_zones.length, 0);
assert.equal(blank.addRectangle("feasible", { x: 10, y: 10 }, { x: 40, y: 50 }).searchConfig().feasible_zones.length, 1);
assert.throws(() => blank.addRectangle("exclusion", { x: 10, y: 10 }, { x: 10.4, y: 30 }), /1 米/);
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
assert.equal(posed.selected?.id, sample.id);
const report = posed.reportRequest();
assert.equal(report.x, 100);
assert.equal(report.theta, 0);
assert.equal(report.origin_x, 100);
assert.equal("exclusion_zones" in report, false);
assert.equal("feasible_zones" in report, false);
assert.equal("field_policy" in report, false);
const clearedOrigin = posed.clearOrigin();
assert.equal(clearedOrigin.origin, null);
assert.equal("origin_x" in clearedOrigin.searchConfig(), false);
assert.deepEqual(clearedOrigin.poses, posed.poses);
assert.deepEqual(clearedOrigin.regions, posed.regions);
const clearedPoses = posed.clearPoses();
assert.equal(clearedPoses.poses.length, 0);
assert.equal(clearedPoses.selectedPoseId, null);
assert.deepEqual(clearedPoses.origin, posed.origin);
assert.deepEqual(clearedPoses.regions, posed.regions);
assert.equal(clearedPoses.widthM, posed.widthM);
assert.equal(clearedPoses.heightM, posed.heightM);
assert.equal(clearedPoses.fieldPolicy, posed.fieldPolicy);
assert.equal(clearedPoses.withPoses([sample]).poses.length, 1);
const dragged = posed.moveSelected(5, -4);
assert.equal(dragged.reportRequest().x, 105);
assert.equal(dragged.reportRequest().y, 116);
assert.equal(dragged.poses[0].theta, sample.theta);
assert.equal(dragged.poses[0].demSoft, sample.demSoft);

assert.throws(() => blank.putOrigin({ x: -1, y: 10 }), /选址范围/);
assert.throws(() => blank.addExclusion([{ x: 1, y: 1 }, { x: 2, y: 2 }]), /三个顶点/);
assert.throws(() => new SiteEdit("cangnan", 80, 50, "allowed", "allowed", 0.5, [{ id: "m", kind: "depot", x: 1, y: 1 }]).searchConfig(), /不认识的标记/);
assert.throws(() => new SiteEdit("cangnan", 80, 50, "allowed", "allowed", 0.5, [], [{ id: "z", kind: "buffer", ring: [{ x: 1, y: 1 }, { x: 2, y: 1 }, { x: 2, y: 2 }] }]).searchConfig(), /不认识的范围/);

const solutionGeneration = new SolutionGeneration();
const staleImport = solutionGeneration.capture();
solutionGeneration.advance();
assert.equal(solutionGeneration.isCurrent(staleImport), false);
assert.equal(solutionGeneration.isCurrent(solutionGeneration.capture()), true);

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

{
  const { comparedFields, measuredChoice, refineSquare, refinedChoices, unmeasured, UNMEASURED } = await import("../../.tmp-problem-snapshot/map/decision_run.js");
  const choice = (id, demSoft, offroadHaul, haulRise) => ({
    id, x: 0, y: 0, theta: 0, demSoft, roadDistance: "1", demandDistance: "1", roadHaul: "未提供", offroadHaul, haulRise, feasible: "可行",
  });
  const fields = comparedFields(false, false);
  assert.deepEqual(fields, ["demSoft", "offroadHaul", "haulRise"]);
  assert.deepEqual(comparedFields(true, true), ["demSoft", "demandDistance", "offroadHaul", "haulRise", "roadHaul"]);

  const original = choice("o", "5", "50", "3");
  const local = [choice("a", "4", "50", "3"), choice("b", "5", "40", "2"), choice("c", "1", "90", "9"), choice("d", "6", "10", "1")];
  // a and b are no worse anywhere, so they cost nothing and win their objectives.
  const picked = refinedChoices(original, local, fields);
  assert.equal(picked.improved, true);
  assert.deepEqual(picked.choices.map((item) => item.id), ["a", "b"]);
  // Nothing beats (5, 30, 2) everywhere. Flatness: a rises 20/80 on haul, c rises 7/8 on rise, so a. Haul and rise: d.
  const tradeoff = refinedChoices(choice("o", "5", "30", "2"), local, fields);
  assert.equal(tradeoff.improved, false);
  assert.deepEqual(tradeoff.choices.map((item) => item.id), ["a", "d"]);
  assert.deepEqual(refinedChoices(choice("o", "0", "0", "0"), local, fields).choices, []);
  // A scheme still being recomputed cannot be compared, so each objective takes its local best.
  const blind = refinedChoices(unmeasured(original), local, fields);
  assert.deepEqual([blind.improved, blind.choices.map((item) => item.id)], [false, ["c", "d"]]);

  assert.deepEqual(refineSquare({ x: 100, y: 50 }, 150), [[0, 0], [250, 0], [250, 200], [0, 200]]);
  const pending = unmeasured(original);
  assert.equal(pending.demSoft, UNMEASURED);
  assert.equal(pending.feasible, UNMEASURED);
  const scored = measuredChoice(pending, {
    dem_soft: 1.234, road_distance: 30, demand_distance: 400, road_haul_m: "", offroad_haul_m: 55.55, haul_rise_m: 2, obstacle_hard_count: 4, is_feasible: false,
  });
  assert.deepEqual([scored.demSoft, scored.roadHaul, scored.offroadHaul, scored.feasible], ["1.2", "未提供", "55.5", "不可行"]);

  const refine = new GuidedDecisionRun(unusedCatalog()).createRefineRequest(
    blank.addRegion("feasible", [{ x: 1, y: 1 }, { x: 9, y: 1 }, { x: 9, y: 9 }]),
    { x: 900, y: 900 },
    100,
    new Date("2026-10-10T12:03:04"),
  );
  assert.equal(refine.config.experiment_name, "refine-20261010-120304");
  assert.deepEqual(refine.config.feasible_zones, [{ points: [[800, 800], [1000, 800], [1000, 1000], [800, 1000]] }]);
}
