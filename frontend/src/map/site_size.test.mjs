import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { SiteEdit } from "../../.tmp-problem-snapshot/map/site_edit.js";
import { installSearchSolutions, preserveDisplayedSize, submittedBuildingSize } from "../../.tmp-problem-snapshot/map/site_size.js";
import { BuildingFootprint } from "../../.tmp-problem-snapshot/map/building_footprint.js";
import {
  BuildingSize,
  GuidedDecisionRun,
  buildingSizeFromResolvedConfig,
  manualChoice,
  moveChoice,
  rotateChoice,
} from "../../.tmp-problem-snapshot/map/decision_run.js";
import { autoPendingPoses, evaluationKey, poseFreshness } from "../../.tmp-problem-snapshot/map/pose_evaluation.js";
import { experimentSaveBody } from "../../.tmp-problem-snapshot/map/save_experiment.js";
import { exportSolutionsJson } from "../../.tmp-problem-snapshot/map/solution_export.js";
import { applyOps } from "../../.tmp-problem-snapshot/agent/edit_ops.js";

const workspace = readFileSync(new URL("./map_workspace.tsx", import.meta.url), "utf8");
assert.equal(workspace.includes("preserveDisplayedSize("), true);
assert.equal(workspace.includes("installSearchSolutions("), true);

const pending = BuildingSize.parse("500", "300");
const center = { x: 900, y: 900 };
const pose = manualChoice("kept", center, 0);
const displayed = new SiteEdit("xiaojiang", 77, 51.5).withPoses([pose]).selectPose(pose.id);
const oldSpan = footprintSpan(displayed);

// T1. Typing a new size does not resize the solutions already on the map.
assert.equal(pending.widthM, 500);
assert.equal(pending.heightM, 300);
assert.equal(displayed.widthM, 77);
assert.equal(displayed.heightM, 51.5);
assert.deepEqual(footprintSpan(displayed), oldSpan);

// T2–T3. The submitted task uses the pending size. The map keeps the old size while it runs.
const requestEdit = displayed.withBuilding(pending.widthM, pending.heightM);
const mapWhileRunning = preserveDisplayedSize(requestEdit, displayed);
const request = new GuidedDecisionRun(unusedCatalog()).createRequest(mapWhileRunning.withBuilding(pending.widthM, pending.heightM));
assert.equal(request.config.rect_w_m, 500);
assert.equal(request.config.rect_h_m, 300);
assert.equal(mapWhileRunning.widthM, 77);
assert.equal(mapWhileRunning.heightM, 51.5);
assert.deepEqual(mapWhileRunning.poses.map((item) => item.id), ["kept"]);
assert.deepEqual(footprintSpan(mapWhileRunning), oldSpan);
const submitted = submittedBuildingSize("job-size", requestEdit);

// T7. The pending size is not part of the displayed evaluation key, so old solutions are not resent.
const key = evaluationKey("xiaojiang", mapWhileRunning.searchConfig(), pose);
const scored = { ...pose, evaluatedFor: key };
const freshness = poseFreshness(scored.evaluatedFor, "xiaojiang", mapWhileRunning.searchConfig(), scored);
assert.equal(freshness, "current");
assert.equal(autoPendingPoses(
  [scored],
  (item) => evaluationKey("xiaojiang", mapWhileRunning.searchConfig(), item),
  new Set(),
  new Map(),
  () => freshness,
).length, 0);

function finish(status, poses) {
  if (status !== "succeeded") return mapWhileRunning;
  return installSearchSolutions(mapWhileRunning, submitted, submitted.jobId, poses);
}

// T5–T6. Failure, cancellation, and an empty result leave the old geometry in place.
for (const status of ["failed", "cancelled", "no_feasible"]) {
  const kept = finish(status, [manualChoice("new", center, 0)]);
  assert.equal(kept, mapWhileRunning);
  assert.equal(kept.widthM, 77);
  assert.equal(kept.heightM, 51.5);
  assert.deepEqual(footprintSpan(kept), oldSpan);
}

// T4. A successful load switches the displayed size together with the new solutions.
const loaded = finish("succeeded", [manualChoice("new", center, 0)]);
assert.equal(loaded.widthM, 500);
assert.equal(loaded.heightM, 300);
assert.deepEqual(loaded.poses.map((item) => item.id), ["new"]);
assert.deepEqual(footprintSpan(loaded), { width: 500, height: 300 });
assert.equal(installSearchSolutions(mapWhileRunning, submitted, "other-job", loaded.poses).widthM, 77);

// T8. Save, JSON, and the PNG footprint use the size still on the map.
const save = experimentSaveBody("旧尺寸", mapWhileRunning, mapWhileRunning.poses, null);
assert.equal(save.rect_w_m, 77);
assert.equal(save.rect_h_m, 51.5);
const exported = JSON.parse(exportSolutionsJson("xiaojiang", mapWhileRunning.widthM, mapWhileRunning.heightM, mapWhileRunning.poses, "2026-11-05T00:00:00.000Z"));
assert.deepEqual(exported.building_size_m, { length: 77, width: 51.5 });
assert.deepEqual(footprintSpan(mapWhileRunning), oldSpan);

// T9. Import restores the case size from resolved_config, not the pending inputs.
const history = buildingSizeFromResolvedConfig({ modeling: { rect_w_m: 77, rect_h_m: 51.5 } });
assert.equal(history.widthM, 77);
assert.equal(history.heightM, 51.5);
const imported = requestEdit.withBuilding(history.widthM, history.heightM).withPoses([pose]);
assert.equal(imported.widthM, 77);
assert.equal(imported.heightM, 51.5);
assert.deepEqual(footprintSpan(imported), oldSpan);
assert.equal(pending.widthM, 500);

// T10. Manual add, move, rotate, and local search stay on the displayed size.
const movedChoice = moveChoice(mapWhileRunning.selected, 4, -3, new BuildingSize(mapWhileRunning.widthM, mapWhileRunning.heightM));
const moved = mapWhileRunning.updateSelected(() => movedChoice);
assert.equal(moved.widthM, 77);
assert.equal(moved.selected.x, 904);
assert.equal(moved.selected.y, 897);
const rotatedChoice = rotateChoice(moved.selected, 0.2, new BuildingSize(moved.widthM, moved.heightM));
const rotated = moved.updateSelected(() => rotatedChoice);
assert.equal(rotated.widthM, 77);
assert.equal(rotated.selected.theta, 0.2);
const manual = rotated.addPose(manualChoice("manual-1", { x: 700, y: 700 }, 0));
assert.equal(manual.widthM, 77);
assert.equal(manual.poses[0].x, 904);
const refine = new GuidedDecisionRun(unusedCatalog()).createRefineRequest(manual, manual.poses[0], 150);
assert.equal(refine.config.rect_w_m, 77);
assert.equal(refine.config.rect_h_m, 51.5);
const merged = manual.withPoses([...manual.poses, manualChoice("local", center, 0)]);
assert.equal(merged.widthM, 77);
assert.equal(merged.poses.length, 3);

// T11. The assistant can set the next search size without resizing current solutions.
const assisted = applyOps(displayed, [
  { kind: "set_building", width_m: 500, height_m: 300 },
  { kind: "run_search", plugin_id: "site.guided_search" },
]);
assert.equal(assisted.edit.widthM, 77);
assert.equal(assisted.edit.heightM, 51.5);
assert.deepEqual(assisted.pendingBuilding, { widthM: 500, heightM: 300 });
assert.deepEqual(footprintSpan(assisted.edit), oldSpan);
const assistedRequest = assisted.edit.withBuilding(assisted.pendingBuilding.widthM, assisted.pendingBuilding.heightM);
const assistedMap = preserveDisplayedSize(assistedRequest, assisted.edit);
assert.equal(assistedRequest.widthM, 500);
assert.equal(assistedMap.widthM, 77);
assert.equal(new GuidedDecisionRun(unusedCatalog()).createRequest(assistedRequest).config.rect_w_m, 500);

// T12. Clearing solutions and switching scenes keep the displayed size, not the pending input.
const cleared = displayed.clearPoses();
assert.equal(cleared.poses.length, 0);
assert.equal(cleared.widthM, 77);
assert.equal(cleared.heightM, 51.5);
const switched = new SiteEdit("other-scene", displayed.widthM, displayed.heightM);
assert.equal(switched.sceneName, "other-scene");
assert.equal(switched.widthM, 77);
assert.equal(switched.heightM, 51.5);
assert.equal(switched.poses.length, 0);

console.log("site size isolation assertions passed");

function footprintSpan(edit) {
  const layer = BuildingFootprint.layer(edit.poses, { widthM: edit.widthM, heightM: edit.heightM }, 0);
  const corners = layer[0].corners();
  const xs = corners.map((point) => point.x);
  const ys = corners.map((point) => point.y);
  return { width: Math.max(...xs) - Math.min(...xs), height: Math.max(...ys) - Math.min(...ys) };
}

function unusedCatalog() {
  return {
    async getExperiments() { return []; },
    async fetchArtifactText() { return ""; },
  };
}
