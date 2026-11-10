import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { BuildingFootprint } from "../../.tmp-problem-snapshot/map/building_footprint.js";
import { BuildingSize, GuidedDecisionRun, JobFollowUp, ParetoSelection, angleDegreesToRadians, buildingSizeFromResolvedConfig, choiceStatus, classifySiteRun, compareChart, formatHaulMetric, formatObjective, isChoiceEdited, measuredChoice, moveChoice, presentSiteOutcome, radiansToDegrees, readSiteResultSummary, restoreChoice, rotateChoice, schemeCard, siteSummaryFromFields, widthAzimuthDeg } from "../../.tmp-problem-snapshot/map/decision_run.js";
import { ExclusionSketch, simplifyStroke } from "../../.tmp-problem-snapshot/map/exclusion_sketch.js";
import { SiteEdit, defaultMaxElevationDraft, elevationLimitNote, elevationSliderEnds } from "../../.tmp-problem-snapshot/map/site_edit.js";
import { CLEAR_CLASS_TARGETS, hiddenLanduseClasses, isLanduseSketchTool, landuseEditClass, landuseModeNotice, landuseOperationOf, nextLanduseSelection, toolbarCommands } from "../../.tmp-problem-snapshot/map/toolbar_commands.js";
import { MapShortcuts } from "../../.tmp-problem-snapshot/map/map_shortcuts.js";
import { SolutionGeneration } from "../../.tmp-problem-snapshot/map/solution_generation.js";
import { mergeDisplayedChoices } from "../../.tmp-problem-snapshot/map/solution_diversity.js";
import vm from "node:vm";
import ts from "typescript";

const layerPanelSource = readFileSync(new URL("./layer_panel.tsx", import.meta.url), "utf8");
const mapWorkspaceSource = readFileSync(new URL("./map_workspace.tsx", import.meta.url), "utf8").replaceAll("\r\n", "\n");
{
  const ast = ts.createSourceFile("workspace.tsx", mapWorkspaceSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let callback;
  function findCadImport(node) {
    if (ts.isJsxAttribute(node) && node.name.getText(ast) === "onCadFeasible") callback = node.initializer.expression.getText(ast);
    ts.forEachChild(node, findCadImport);
  }
  findCadImport(ast);
  assert.ok(callback);
  const oldRing = [{ x: 10, y: 10 }, { x: 40, y: 10 }, { x: 10, y: 40 }];
  const excluded = [{ x: 15, y: 15 }, { x: 20, y: 15 }, { x: 15, y: 20 }];
  let state = new SiteEdit().addFeasible(oldRing).addExclusion(excluded).withPoses([{ id: "old", x: 25, y: 25, theta: 0 }]);
  let visibility = { feasible: false, exclusion: true };
  const apply = vm.runInNewContext(`(${callback})`, {
    setEdit: (update) => { state = update(state); },
    setRegionVisibility: (update) => { visibility = update(visibility); }, setNotice: () => {},
  });
  const cad = [{ points: [[80, 80], [120, 80], [80, 120]] }, { points: [[160, 160], [180, 160], [160, 180]] }];
  apply(cad);
  assert.equal(state.regions.filter((region) => region.kind === "feasible").length, 3);
  assert.deepEqual(state.regions[0].ring, oldRing);
  assert.deepEqual(state.regions[1].ring, excluded);
  assert.equal(state.poses[0].id, "old");
  assert.equal(visibility.feasible, true);
  assert.equal(visibility.exclusion, true);
  const form = state.searchConfig();
  assert.equal(form.feasible_zones.length, 3);
  assert.equal(form.exclusion_zones.length, 1);
  assert.deepEqual(form.feasible_zones.slice(1), cad);
  state = state.removeRegion(state.regions[2].id);
  assert.equal(state.searchConfig().feasible_zones.length, 2);
}
{
  const ast = ts.createSourceFile("workspace.tsx", mapWorkspaceSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let eraseSource, deleteSource;
  function findErase(node) {
    if (ts.isFunctionDeclaration(node) && node.name?.text === "erasePose") eraseSource = node.getText(ast);
    if (ts.isFunctionDeclaration(node) && node.name?.text === "deleteDisplayedSolution") deleteSource = node.getText(ast);
    ts.forEachChild(node, findErase);
  }
  findErase(ast);
  assert.ok(eraseSource);
  assert.ok(deleteSource);
  const poses = [{ id: "a", x: 1, y: 1, theta: 0 }, { id: "b", x: 2, y: 2, theta: 0 }];
  const hidden = { id: "hidden", x: 3, y: 3, theta: 0, paretoLayer: 2 };
  const state = {
    compared: ["a", "b"], recommended: ["a", "b"], report: { id: "a" }, card: true,
  };
  const ctx = {
    optimizationActive: () => false, adjusting: false, evaluationState: "idle",
    editRef: { current: new SiteEdit().withPoses(poses) },
    diversityPool: { current: [...poses, hidden] }, mergeDisplayedChoices,
    solutionGeneration: { current: new SolutionGeneration() }, dragStart: { current: null },
    setEdit: () => {}, setNotice: () => {},
    setComparedIds: (f) => state.compared = f(state.compared),
    setRecommendedIds: (f) => state.recommended = f(state.recommended),
    setReport: (v) => state.report = v, setSchemeCardOpen: (v) => state.card = v,
    setPreviewOps: () => {}, setAskPose: () => {}, setSchemeAnchor: () => {},
    setSchemeTarget: () => {}, setSchemeCardBounds: () => {}, setAzimuthDeg: () => {},
  };
  const deletion = ts.transpileModule(`(${deleteSource})`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  ctx.deleteDisplayedSolution = vm.runInNewContext(deletion, ctx);
  const js = ts.transpileModule(`(${eraseSource})`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const erase = (id) => vm.runInNewContext(js, ctx)(id);
  const oldGeneration = ctx.solutionGeneration.current.capture();
  ctx.optimizationActive = () => true;
  erase("a");
  assert.equal(ctx.editRef.current.poses.length, 2);
  ctx.optimizationActive = () => false;
  ctx.adjusting = true;
  erase("a");
  assert.equal(ctx.editRef.current.poses.length, 2);
  ctx.adjusting = false;
  ctx.evaluationState = "loading";
  erase("a");
  assert.equal(ctx.editRef.current.poses.length, 2);
  ctx.evaluationState = "idle";
  erase("a");
  assert.equal(ctx.editRef.current.selectedPoseId, "b");
  assert.deepEqual(state.compared, ["b"]);
  assert.deepEqual(state.recommended, ["b"]);
  assert.equal(state.report, null);
  assert.equal(state.card, false);
  assert.equal(ctx.solutionGeneration.current.isCurrent(oldGeneration), false);
  assert.deepEqual(ctx.diversityPool.current.map((p) => p.id), ["b", "hidden"]);
  erase("b");
  assert.equal(ctx.editRef.current.selectedPoseId, null);
  assert.deepEqual(mergeDisplayedChoices(ctx.diversityPool.current, ctx.editRef.current.poses).map((p) => p.id), ["hidden"]);
  // Both entries share deletion, including non-selected poses and the final retained pose.
  ctx.editRef.current = new SiteEdit().withPoses(poses).selectPose("b");
  ctx.diversityPool.current = [...poses, hidden];
  state.report = { id: "b" };
  state.card = true;
  const currentGeneration = ctx.solutionGeneration.current.capture();
  ctx.deleteDisplayedSolution("a");
  assert.equal(ctx.editRef.current.selectedPoseId, "b");
  assert.deepEqual(state.report, { id: "b" });
  assert.equal(state.card, true);
  assert.equal(ctx.solutionGeneration.current.isCurrent(currentGeneration), true);
  let clearCount = 0;
  ctx.clearDisplayedSolutions = () => {
    clearCount++;
    ctx.diversityPool.current = [];
    ctx.editRef.current = ctx.editRef.current.clearPoses();
  };
  ctx.diversityPool.current = [poses[1]];
  ctx.deleteDisplayedSolution("b");
  assert.equal(clearCount, 1);
  assert.equal(ctx.editRef.current.selectedPoseId, null);
  assert.deepEqual(ctx.diversityPool.current, []);
}
const worldMapSource = readFileSync(new URL("./world_map.tsx", import.meta.url), "utf8");
const siteOverlaySource = readFileSync(new URL("./site_overlay.tsx", import.meta.url), "utf8");
const stylesSource = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
assert.equal(layerPanelSource.includes("原始 DEM 空间分辨率"), false);
assert.equal(layerPanelSource.includes("formatResolution"), false);
assert.equal(layerPanelSource.includes('className="landuse-layer-grid"'), true);
assert.match(stylesSource, /\.landuse-layer-grid \{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/);
assert.match(stylesSource, /@media \(max-width: 520px\) \{ \.landuse-layer-grid \{ grid-template-columns: 1fr; \} \}/);
assert.match(stylesSource, /\.hud-panel-body \{[^}]*min-width: 0[^}]*overflow-x: clip/);
assert.match(stylesSource, /\.hud-optimize-actions \{[^}]*flex-wrap: wrap/);
assert.equal(stylesSource.includes(".landuse-draft-footer { flex: none; margin: 8px -16px"), false);
assert.equal(layerPanelSource.includes('title="建设约束分析"'), true);
assert.equal(layerPanelSource.includes('label="建设可行性"'), true);
assert.equal(layerPanelSource.includes('label="手绘禁区"'), true);
assert.equal(layerPanelSource.includes('label="手绘可行域"'), true);
assert.equal(layerPanelSource.includes('基于当前建设规则的 1 m 格网，不代表完整站址可行。'), false);
assert.match(mapWorkspaceSource, /useState\(false\).*feasibilityVisible|feasibilityVisible.*useState\(false\)/s);
assert.match(mapWorkspaceSource, /const \[farmlandVisible, setFarmlandVisible\] = useState\(false\)/);
{
  const switchStart = mapWorkspaceSource.indexOf("function switchScene(");
  const switchBody = mapWorkspaceSource.slice(switchStart, mapWorkspaceSource.indexOf("function activeKind("));
  assert.equal(switchBody.includes("setFarmlandVisible(false)"), true);
  assert.equal(switchBody.includes("setFarmlandVisible(true)"), false);
}
assert.equal(mapWorkspaceSource.includes("fetchConstructionFeasibilityOverlay"), true);
assert.equal(mapWorkspaceSource.includes("URL.revokeObjectURL"), true);
assert.equal(siteOverlaySource.includes("source.updateImage"), true);
assert.equal(siteOverlaySource.includes('map.getLayer("forbidden-fill") ? "forbidden-fill" : "site-frame-fill"'), true);
assert.equal(mapWorkspaceSource.includes("originPlace.lng"), true);
assert.equal(mapWorkspaceSource.includes("originPlace.lat"), true);
assert.equal(mapWorkspaceSource.includes("已清除进货原点，按 Ctrl+Z 可恢复。"), true);
assert.equal(mapWorkspaceSource.includes("JSON.stringify(latestConfig) !== configKey"), false);
assert.equal(mapWorkspaceSource.includes("function clearDisplayedSolutions("), true);
assert.equal(mapWorkspaceSource.includes('setNotice("已清空当前方案。")'), true);
assert.equal(mapWorkspaceSource.includes("setSiteOutcome(null)"), true);
assert.equal(mapWorkspaceSource.includes('onClearSolutions={problemType === "routing" ? routing.clearRoutes : clearDisplayedSolutionsFromUi}'), true);
assert.equal(mapWorkspaceSource.includes("onClick={clearDisplayedSolutionsFromUi}"), true);
assert.equal(mapWorkspaceSource.includes("solutionGeneration.current.isCurrent"), true);
assert.match(mapWorkspaceSource, /if \(applied\.clearPoses\) \{\s+clearDisplayedSolutions\(\);/);
assert.equal(mapWorkspaceSource.includes('clearSolutionsDisabled={problemType === "routing" ? routingBusy || !routing.bundle : running || retainedCount === 0}'), true);
assert.equal(mapWorkspaceSource.includes("disabled={running || retainedCount === 0}>清空方案"), true);
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
assert.equal(mapWorkspaceSource.includes("function switchScene("), true);
assert.equal(mapWorkspaceSource.includes("historyScene !== scene?.id"), true);
assert.equal(mapWorkspaceSource.includes("frame={sceneFrame}"), true);
assert.equal(worldMapSource.includes("frame.lngLatToLocal"), true);
assert.equal(siteOverlaySource.includes("frame.localToLngLat"), true);

const size = BuildingSize.parse("80", "50");
assert.equal(size.widthM, 80);
assert.throws(() => BuildingSize.parse("0", "50"), /大于 0/);

const blank = new SiteEdit("cangnan", size.widthM, size.heightM);
const { siteExperimentName, routingExperimentName } = await import("../../.tmp-problem-snapshot/experiment_name.js");
assert.equal(siteExperimentName("苍南", 80, 50), "苍南_变电站_80×50m");
assert.equal(siteExperimentName("场景/一", 80, 50), "场景_一_变电站_80×50m");
assert.equal(routingExperimentName("苍南", { lng: 120.1234567, lat: 27.1 }, { lng: 120.2, lat: 27.2345678 }),
  "苍南_起点120.123457,27.100000_终点120.200000,27.234568");
const request = new GuidedDecisionRun(unusedCatalog()).createRequest(blank, new Date("2026-10-10T12:03:04"));
assert.equal(request.plugin_id, "site.guided_search");
assert.equal(request.config.experiment_name, "cangnan_变电站_80×50m_20261010-120304");
assert.equal(request.config.scene_name, "cangnan");
assert.equal(request.config.rect_w_m, 80);
assert.equal(request.config.rect_h_m, 50);
assert.equal(request.config.mountain_policy, "allowed");
assert.equal(request.config.field_policy, "allowed");
assert.equal(request.config.field_cost, 0.5);
assert.deepEqual(request.config.exclusion_zones, []);
assert.deepEqual(request.config.feasible_zones, []);
assert.equal(request.config.include_demand, false);
assert.equal(request.config.diagonal_access, true);
const jsonDefaults = new SiteEdit().withFormDefaults({
  rect_w_m: { default: 90 },
  road_setback_m: { default: 7 },
  water_setback_m: { default: 8 },
  highway_setback_m: { default: 9 },
  rect_h_m: { default: 60 },
  include_demand: { default: true },
  diagonal_access: { default: true },
}).searchConfig();
assert.equal(jsonDefaults.rect_w_m, 90);
assert.equal(jsonDefaults.rect_h_m, 60);
assert.equal(jsonDefaults.include_demand, true);
assert.equal(jsonDefaults.diagonal_access, true);
assert.equal(jsonDefaults.road_setback_m, 7);
assert.equal(jsonDefaults.water_setback_m, 8);
assert.equal(jsonDefaults.highway_setback_m, 9);
assert.throws(() => new SiteEdit().withFormDefaults({ rect_w_m: { default: 90 } }), /默认值/);
assert.equal(mapWorkspaceSource.includes("withFormDefaults(plugin.config_schema.properties"), true);
const importedForm = blank.withIncludeDemand(true).putOrigin({ x: 1, y: 1 }).withImportedSiteForm({
  mountain_policy: "blocked",
  field_policy: "costly",
  field_cost: 0.2,
  exclusion_zones: [{ points: [[10, 10], [20, 10], [15, 20]] }],
  feasible_zones: [],
  include_demand: false,
  diagonal_access: false,
  origin_x: null,
  origin_y: null,
});
assert.equal(importedForm.mountainPolicy, "blocked");
assert.equal(importedForm.fieldPolicy, "costly");
assert.equal(importedForm.fieldCost, 0.2);
assert.equal(importedForm.includeDemand, false);
assert.equal(importedForm.diagonalAccess, true);
assert.equal(importedForm.searchConfig().exclusion_zones.length, 1);
assert.equal(importedForm.searchConfig().feasible_zones.length, 0);
assert.equal(importedForm.origin, null);
assert.equal(importedForm.searchConfig().max_elevation_m, null);
assert.equal(blank.withElevation(true, "200").searchConfig().max_elevation_m, 200);
assert.equal(blank.withElevation(true, "200").withElevation(false).elevationDraft, "200");
assert.equal(blank.withElevation(false).searchConfig().max_elevation_m, null);
assert.equal(blank.withElevation(true, "").elevationProblem(), "请输入有效的最高允许海拔（m）。");
assert.equal(blank.withElevation(true, "-12.5").searchConfig().max_elevation_m, -12.5);
assert.equal(blank.withElevation(true, "200").withImportedSiteForm({}).elevationEnabled, false);
assert.equal(defaultMaxElevationDraft(428.276062), "428.3");
assert.equal(defaultMaxElevationDraft(428.3), "428.3");
assert.equal(defaultMaxElevationDraft(428), "428");
assert.equal(defaultMaxElevationDraft(428.2000001), "428.3");
assert.equal(defaultMaxElevationDraft(0), "0");
assert.equal(defaultMaxElevationDraft(0.01), "0.1");
assert.equal(defaultMaxElevationDraft(-0.01), "0");
assert.equal(defaultMaxElevationDraft(-1.21), "-1.2");
assert.equal(defaultMaxElevationDraft(-1.2), "-1.2");
assert.equal(defaultMaxElevationDraft(-12.5), "-12.5");
const sceneRange = { min: 12.24, max: 428.276062 };
assert.equal(elevationLimitNote(true, defaultMaxElevationDraft(sceneRange.max), sceneRange), null);
assert.equal(elevationLimitNote(true, "428.3", sceneRange), null);
assert.equal(elevationLimitNote(true, "428.276062", sceneRange), null);
assert.equal(elevationLimitNote(true, "428.4", sceneRange), "当前阈值高于场景最高海拔");
assert.equal(elevationLimitNote(true, "429", sceneRange), "当前阈值高于场景最高海拔");
assert.equal(elevationLimitNote(true, "12.2", sceneRange), "当前阈值低于场景最低海拔");
assert.equal(elevationLimitNote(false, "500", sceneRange), null);
assert.equal(elevationLimitNote(true, "428.3", { min: 12, max: 428.21 }), null);
assert.equal(elevationLimitNote(true, "428.4", { min: 12, max: 428.21 }), "当前阈值高于场景最高海拔");
const typedLimit = blank.withElevation(true, "428.276062");
assert.equal(typedLimit.elevationDraft, "428.276062");
assert.equal(typedLimit.searchConfig().max_elevation_m, 428.276062);
const importedLimit = blank.withImportedSiteForm({ max_elevation_m: 428.276062 });
assert.equal(importedLimit.elevationEnabled, true);
assert.equal(importedLimit.elevationDraft, "428.276062");
assert.equal(importedLimit.searchConfig().max_elevation_m, 428.276062);
assert.equal(importedLimit.withElevation(false).elevationDraft, "428.276062");
assert.equal(mapWorkspaceSource.includes("String(range.max)"), false);
assert.equal(mapWorkspaceSource.includes("defaultMaxElevationDraft(range.max)"), true);
assert.equal(mapWorkspaceSource.includes("elevationLimitNote("), true);
assert.deepEqual(elevationSliderEnds(23.6, 386.4), { min: 23, max: 387, flat: false });
assert.deepEqual(elevationSliderEnds(-3.2, -0.4), { min: -4, max: 0, flat: false });
assert.deepEqual(elevationSliderEnds(12, 12), { min: 12, max: 12, flat: true });
assert.equal(elevationSliderEnds(Number.NaN, 10), null);
assert.equal(mapWorkspaceSource.includes("当前场景暂无可用 DEM 高程范围"), true);
assert.equal(mapWorkspaceSource.includes("formatSceneElevation"), true);
assert.equal(mapWorkspaceSource.includes("publishElevationPreview(false, \"\")"), true);
assert.equal(mapWorkspaceSource.includes("retainPriorPoses"), true);
assert.equal(mapWorkspaceSource.includes("setSiteOutcome(null)"), true);
const found = readSiteResultSummary({ data: { result_summary: { n_solutions: 20, n_feasible: 4, n_pareto: 2, no_feasible_solution: false } } });
assert.equal(classifySiteRun(found), "success_with_solutions");
assert.equal(presentSiteOutcome("success_with_solutions", found).title, "优化完成 · 找到 4 个可行站址");
const none = readSiteResultSummary({ data: { result_summary: { n_solutions: 12, n_feasible: 0, n_pareto: 0, no_feasible_solution: true } } });
assert.equal(classifySiteRun(none), "completed_no_feasible");
const emptyView = presentSiteOutcome("completed_no_feasible", none, { retainedPrior: true });
assert.equal(emptyView.title, "计算已完成 · 未找到可行站址");
assert.equal(emptyView.lines[1], "候选方案 12 · 可行方案 0 · Pareto 方案 0");
assert.match(emptyView.lines.join("\n"), /此前的方案/);
const paretoMissing = readSiteResultSummary({ data: { result_summary: { n_solutions: 8, n_feasible: 3, n_pareto: 0, no_feasible_solution: false } } });
assert.equal(classifySiteRun(paretoMissing), "completed_no_pareto");
assert.equal(presentSiteOutcome("completed_no_pareto", paretoMissing).title.includes("未找到可行站址"), false);
assert.equal(presentSiteOutcome("job_failed", null, { message: "CUDA unavailable" }).title, "优化失败");
assert.equal(presentSiteOutcome("job_failed", null, { message: "CUDA unavailable" }).title.includes("计算已完成"), false);
assert.equal(presentSiteOutcome("cancelled", null).title, "任务已终止");
const failedLoad = presentSiteOutcome("result_load_failed", null, { message: "这次实验没有方案表。" });
assert.equal(failedLoad.title, "计算已完成，但结果加载失败。");
assert.equal(failedLoad.retry, true);
assert.equal(readSiteResultSummary({ data: {} }), null);
assert.equal(readSiteResultSummary({ data: { result_summary: { n_solutions: 1, n_feasible: 1, n_pareto: 1, no_feasible_solution: true } } }), null);
assert.equal(classifySiteRun(siteSummaryFromFields({ n_solutions: 9, n_feasible: 0, n_pareto: 0, no_feasible_solution: true, algorithm: "guided_search" })), "completed_no_feasible");
assert.equal(classifySiteRun(null), "stats_unavailable");
assert.equal(presentSiteOutcome("stats_unavailable", null).title.includes("未找到可行站址"), false);
assert.equal(presentSiteOutcome("refine_no_feasible", null).title, "本次局部优化未找到新的可行站址");
assert.equal(layerPanelSource.includes("可行性图更新中"), true);
const keptForm = blank.putOrigin({ x: 3, y: 4 }).withImportedSiteForm({ field_cost: 0.2 });
assert.equal(keptForm.origin.x, 3);
assert.equal(keptForm.fieldCost, blank.fieldCost);
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
assert.equal(loaded[0].roadDistance, "30.000");
assert.equal(loaded[0].demSoft, "1.500");
assert.deepEqual(loaded[0].original, { x: 10, y: 20, theta: 0.5 });
assert.equal(formatObjective("38.9281005859375"), "38.928");
assert.equal(formatObjective("655.6527709960938"), "655.653");
assert.equal(formatObjective("26.49708366394043"), "26.497");
assert.equal(formatObjective("未提供"), "未提供");
assert.equal(formatHaulMetric(0.0384), "0.038");
assert.equal(formatHaulMetric(118.5244), "118.524");

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
assert.equal(commands.find((command) => command.id === "new-scene").label, "新建场景…");
assert.equal(commands.find((command) => command.id === "new-scene").group, "文件");
assert.deepEqual(commands.filter((command) => command.group === "文件").map((command) => command.id), [
  "new-scene", "import-data", "import-case", "save-experiment", "export-solutions-csv", "export-solutions-json", "export-scene-png",
]);
assert.equal(commands.find((command) => command.id === "prepare-scene").label, "准备当前场景数据");
assert.equal(commands.find((command) => command.id === "prepare-scene").group, "主页");
let openedScene = false;
const withNewScene = toolbarCommands({
  tool: "pan",
  notify: () => undefined,
  focusSite: () => undefined,
  setTool: () => undefined,
  onNewScene: () => { openedScene = true; },
});
withNewScene.find((command) => command.id === "new-scene").run();
assert.equal(openedScene, true);
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
assert.equal(commands.some((command) => command.id === "favorite-add" || command.id === "favorite-adjust"), false);
{
  const editIds = commands.filter((command) => command.group === "编辑").map((command) => command.id);
  assert.deepEqual(editIds, [
    "pan", "exclusion", "exclusion-box", "feasible", "feasible-box",
    "landuse-field", "landuse-building", "landuse-road", "landuse-water", "landuse-clear-class",
    "erase", "origin", "pose-add", "adjust",
  ]);
}
assert.equal(landuseEditClass("landuse-field"), "field");
assert.equal(landuseEditClass("landuse-building"), "building");
assert.equal(landuseEditClass("landuse-road"), "road");
assert.equal(landuseEditClass("landuse-water"), "water");
assert.equal(landuseEditClass("pan"), null);
assert.equal(mapWorkspaceSource.includes("clearLanduseEdits("), false);
assert.equal(mapWorkspaceSource.includes("showLanduseOutlines={tool === \"erase\" || landuseSketchActive || (!landuseState.dirty && (currentLanduseEditClass !== null || previewOps !== null))}"), true);
{
  const toolbarFile = readFileSync(new URL("./toolbar_commands.ts", import.meta.url), "utf8");
  assert.equal(toolbarFile.includes('id: "landuse-clear-class"'), true);
  assert.equal(toolbarFile.includes("清除指定类别"), true);
  assert.equal(toolbarFile.includes("去除类别"), false);
  assert.equal(toolbarFile.includes("landuse-clear-water"), false);
  assert.equal(landuseEditClass("landuse-clear-class"), null);
  assert.equal(isLanduseSketchTool("landuse-clear-class"), true);
  assert.equal(isLanduseSketchTool("erase"), false);
  assert.equal(isLanduseSketchTool("pan"), false);
  assert.equal(landuseOperationOf("erase"), null);
  assert.equal(landuseOperationOf("landuse-building"), "paint");
  assert.deepEqual(CLEAR_CLASS_TARGETS.map((item) => item.label), ["农田", "建筑", "道路", "水体"]);
  const paintBuilding = nextLanduseSelection({ operation: "paint", target: "field" }, { target: "building" });
  assert.deepEqual(paintBuilding, { operation: "paint", target: "building", tool: "landuse-building" });
  const clearBuilding = nextLanduseSelection(paintBuilding, { operation: "clear" });
  assert.deepEqual(clearBuilding, { operation: "clear", target: "building", tool: "landuse-clear-class" });
  const clearWater = nextLanduseSelection(clearBuilding, { target: "water" });
  assert.equal(clearWater.operation, "clear");
  assert.equal(clearWater.target, "water");
  assert.equal(clearWater.tool, "landuse-clear-class");
  const backToPaint = nextLanduseSelection(clearWater, { operation: "paint" });
  assert.equal(backToPaint.target, "water");
  assert.equal(backToPaint.tool, "landuse-water");
  assert.equal(landuseModeNotice("paint", "building"), "设置类别：圈选范围将设置为【建筑】。");
  assert.equal(landuseModeNotice("clear", "building").includes("【建筑】"), true);
  assert.equal(landuseModeNotice("clear", "building").includes("水体"), false);
  assert.equal(landuseModeNotice("clear", "water").includes("【水体】"), true);
}
{
  const toolbarUi = readFileSync(new URL("./map_toolbar.tsx", import.meta.url), "utf8");
  assert.equal(toolbarUi.includes("土地分类编辑"), false);
  assert.equal(toolbarUi.includes(">土地分类<"), true);
  assert.equal(toolbarUi.includes("landuse-editor"), false);
  assert.equal(toolbarUi.includes('short: "设置"'), true);
  assert.equal(toolbarUi.includes('short: "清除"'), true);
  assert.equal(toolbarUi.includes("设置类别"), true);
  assert.equal(toolbarUi.includes("清除指定类别"), true);
  assert.equal(toolbarUi.includes("去除类别"), false);
  assert.equal(toolbarUi.includes("土地类型"), false);
  assert.equal((toolbarUi.match(/CLEAR_CLASS_TARGETS\.map/g) ?? []).length, 1);
  assert.equal(toolbarUi.includes('">农田<'), false);
  assert.equal(toolbarUi.includes("loose = [\"erase\""), true);
}
assert.equal(mapWorkspaceSource.includes("const landuseFooter = landuseState.dirty && ("), true);
assert.equal(mapWorkspaceSource.includes("currentLanduseEditClass !== null && landuseState.dirty"), false);
assert.equal(siteOverlaySource.includes("showOutlines ? landuseCorrectionCollection(edits, frame) : emptyCollection"), true);
assert.equal(worldMapSource.includes('map.on("contextmenu"'), false);
assert.equal(worldMapSource.includes('target?.kind === "landuse") action.onDeleteLanduseEdit(target.id)'), true);
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
assert.equal(fromReport.some((row) => row.label === "道路距离（m）"), false);
assert.equal(schemeCard(adjustedMeasured, {
  offroadHaulM: 8.2,
  haulRiseM: 0.4,
  accessSlopeDeg: 3.2,
  accessWarning: true,
}, false).objectives.some((row) => row.label === "道路距离（m）"), false);
assert.equal(fromReport.find((row) => row.label === "可行性").value, "可行 → 不可行");
assert.equal(fromReport.find((row) => row.label === "禁建覆盖格数").value, "0 → 3.000");
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
assert.deepEqual(chart.labels, ["地形", "进站长度", "进站累计高差"]);
assert.equal(chart.labels.includes("道路"), false);
assert.equal(chart.labels.includes("沿路"), false);
assert.equal(chart.labels.includes("需求"), false);
assert.equal(chart.series[0].values[0], 0);
assert.equal(chart.series[1].values[0], 1);
assert.equal(chart.series[0].values[chart.labels.indexOf("进站累计高差")], 0);
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
assert.deepEqual(report.exclusion_zones, posed.searchConfig().exclusion_zones);
assert.deepEqual(report.feasible_zones, []);
assert.equal(report.field_policy, posed.fieldPolicy);
assert.equal(report.mountain_policy, posed.mountainPolicy);
assert.equal(report.field_cost, posed.fieldCost);
const selectedSecond = posed
  .withPoses([sample, { ...sample, id: "b", x: 245, y: 360 }])
  .selectPose("b")
  .reportRequest();
assert.equal(selectedSecond.x, 245);
assert.equal(selectedSecond.y, 360);
assert.deepEqual(selectedSecond.exclusion_zones, report.exclusion_zones);
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

const submitStart = mapWorkspaceSource.indexOf("async function submitSearch(");
const submitBody = mapWorkspaceSource.slice(submitStart, mapWorkspaceSource.indexOf("async function submitRefine(", submitStart));
assert.equal(submitBody.includes("fetchPoseObjectives"), false);
assert.equal(submitBody.includes("reevaluateStaleSolutions"), false);
const optimizeStart = mapWorkspaceSource.indexOf("async function startOptimization(");
const optimizeBody = mapWorkspaceSource.slice(optimizeStart, mapWorkspaceSource.indexOf("function changeAzimuth(", optimizeStart));
assert.equal(optimizeBody.includes("fetchPoseObjectives"), false);
assert.equal(optimizeBody.includes("reevaluateStaleSolutions"), false);
assert.equal(mapWorkspaceSource.includes("autoPendingPoses("), true);
assert.equal(mapWorkspaceSource.includes("重新评价旧方案"), true);
const effectStart = mapWorkspaceSource.indexOf("const pending = autoPendingPoses(");
const effectBody = mapWorkspaceSource.slice(effectStart, mapWorkspaceSource.indexOf("function retrySelectedEvaluation(", effectStart));
assert.equal(effectBody.includes("fetchPoseObjectives"), true);
assert.equal(effectBody.includes("poseFreshness"), true);
assert.equal(mapWorkspaceSource.includes("当前禁区或可行域已变化，本方案目标值尚未按新约束评价。"), true);
const importStart = mapWorkspaceSource.indexOf("async function importHistory(");
const importBody = mapWorkspaceSource.slice(importStart, mapWorkspaceSource.indexOf("async function saveCurrentExperiment(", importStart));
assert.equal(importBody.includes("acceptImportedPoses"), true);
assert.equal(importBody.includes("HISTORY_EVALUATION"), false);
assert.equal(importBody.includes("fetchPoseObjectives"), false);

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
  assert.deepEqual([scored.demSoft, scored.roadHaul, scored.offroadHaul, scored.feasible], ["1.234", "未提供", "55.550", "不可行"]);

  const refine = new GuidedDecisionRun(unusedCatalog()).createRefineRequest(
    blank.addRegion("feasible", [{ x: 1, y: 1 }, { x: 9, y: 1 }, { x: 9, y: 9 }]),
    { x: 900, y: 900 },
    100,
    new Date("2026-10-10T12:03:04"),
  );
  assert.equal(refine.config.experiment_name, "cangnan_变电站_80×50m_局部优化_20261010-120304");
  assert.deepEqual(refine.config.feasible_zones, [{ points: [[800, 800], [1000, 800], [1000, 1000], [800, 1000]] }]);
}
