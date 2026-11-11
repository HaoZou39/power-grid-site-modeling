import assert from "node:assert/strict";
import { SiteEdit } from "../../.tmp-problem-snapshot/map/site_edit.js";
import { restoreSitePlanningConfig, serializeSitePlanningConfig } from "../../.tmp-problem-snapshot/map/site_plan.js";

const posed = new SiteEdit(
  "demo", 77, 51.5, "blocked", "costly", 0.3, [], [],
  [{ id: "pose-1", x: 12, y: 14, theta: 0.2 }], "pose-1", [{ x: 0.125, y: 0.125 }],
  false, false, 8, 9, 11, true, "12.50",
).addExclusion([{ x: 1.25, y: 2 }, { x: 8.5, y: 2 }, { x: 8.5, y: 9.75 }])
  .addFeasible([{ x: 20, y: 20 }, { x: 30.5, y: 20 }, { x: 30.5, y: 40 }, { x: 20, y: 40 }])
  .putOrigin({ x: 3.5, y: 4.25 });

assert.throws(() => serializeSitePlanningConfig(posed, { rectW: "", rectH: "200" }));
const saved = serializeSitePlanningConfig(posed, { rectW: "210", rectH: "200" });
assert.equal(saved.rect_w_m, 210);
assert.equal(saved.rect_h_m, 200);
assert.equal(saved.field_policy, "allowed");
assert.equal(saved.field_cost, 0.5);
assert.equal(saved.include_demand, false);
assert.notEqual(saved.rect_w_m, posed.widthM);
assert.equal(saved.elevation_enabled, true);
assert.equal(saved.elevation_draft, "12.50");
assert.deepEqual(saved.origin, { x: 3.5, y: 4.25 });
assert.equal(saved.exclusion_zones[0].id, "zone-1");
assert.deepEqual(saved.exclusion_zones[0].points[0], [1.25, 2]);
assert.equal(saved.feasible_zones[0].points[1][0], 30.5);
const text = JSON.stringify(saved);
assert.equal(text.includes("pose-1"), false);
assert.equal(text.includes("0.125"), false);
assert.equal(text.includes("selectedPoseId"), false);

const restored = restoreSitePlanningConfig(posed, saved);
assert.equal(restored.edit.widthM, 77);
assert.equal(restored.edit.heightM, 51.5);
assert.equal(restored.rectW, "210");
assert.equal(restored.rectH, "200");
assert.equal(restored.edit.selectedPoseId, "pose-1");
assert.equal(restored.edit.poses.length, 1);
assert.equal(restored.edit.draft.length, 0);
assert.equal(restored.edit.fieldPolicy, "allowed");
assert.equal(restored.edit.fieldCost, 0.5);
assert.equal(restored.edit.includeDemand, false);
assert.equal(restored.edit.elevationEnabled, true);
assert.equal(restored.edit.elevationDraft, "12.50");
assert.deepEqual(restored.edit.origin, { x: 3.5, y: 4.25 });
assert.equal(restored.edit.regions[0].id, "zone-1");
assert.equal(restored.edit.regions[0].ring[2].y, 9.75);
assert.deepEqual(serializeSitePlanningConfig(restored.edit, restored), saved);
