import assert from "node:assert/strict";
import { SiteEdit } from "../../.tmp-problem-snapshot/map/site_edit.js";
import { EDIT_OP_KINDS, applyOps, describeOps, proposalPreview } from "../../.tmp-problem-snapshot/agent/edit_ops.js";
import { snapshotStamp, toSnapshot } from "../../.tmp-problem-snapshot/agent/workspace_snapshot.js";

const ring = [{ x: 1, y: 1 }, { x: 4, y: 1 }, { x: 4, y: 4 }, { x: 1, y: 4 }];
const before = new SiteEdit("cangnan", 77, 51.5).withPoses([
  { id: "a", x: 1, y: 1, theta: 0, demSoft: "1.5", roadDistance: "", demandDistance: "4" },
  { id: "b", x: 2, y: 2, theta: 0 },
  { id: "c", x: 120, y: 10, theta: 0 },
]);

const applied = applyOps(before, [
  { kind: "set_building", width_m: 80, height_m: 50 },
  { kind: "set_policies", mountain_policy: "blocked", field_cost: 0.25 },
  { kind: "set_origin", x: 10, y: 20 },
  { kind: "add_region", region_kind: "exclusion", ring },
  { kind: "update_pose", pose_id: "c", x: 135 },
  { kind: "select_pose", pose_id: "c" },
  { kind: "run_search", plugin_id: "site.nsga2" },
]);

assert.equal(applied.runSearch, true);
assert.equal(applied.edit.widthM, 80);
assert.equal(applied.edit.heightM, 50);
assert.equal(applied.edit.mountainPolicy, "blocked");
assert.equal(applied.edit.fieldPolicy, "allowed");
assert.equal(applied.edit.fieldCost, 0.25);
assert.deepEqual(applied.edit.origin, { x: 10, y: 20 });
assert.equal(applied.edit.regions.length, 1);
assert.equal(applied.edit.regions[0].kind, "exclusion");
assert.equal(applied.edit.poses[2].x, 135);
assert.equal(applied.edit.selectedPoseId, "c");
assert.equal(applied.edit.poses.length, 3);

const lines = describeOps(before, applied.edit, [
  { kind: "run_search", plugin_id: "site.nsga2" },
]);
assert.ok(lines.includes("建筑 77×51.5 → 80×50"));
assert.ok(lines.includes("新增禁区 4 点"));
assert.ok(lines.includes("方案 #3 x 120→135"));
assert.ok(lines.includes("开始一次 NSGA-II 搜索"));

const cleared = applyOps(applied.edit, [{ kind: "clear_origin" }, { kind: "remove_region", region_id: applied.edit.regions[0].id }]);
assert.equal(cleared.edit.origin, null);
assert.equal(cleared.edit.regions.length, 0);
assert.equal(cleared.runSearch, false);
assert.deepEqual(describeOps(applied.edit, cleared.edit), ["清除进货原点", `删除范围 ${applied.edit.regions[0].id}`]);

const preview = proposalPreview(before, applied.edit);
assert.equal(preview.regions.length, 1);
assert.equal(preview.poses.length, 1);
assert.equal(preview.poses[0].id, "c");
assert.deepEqual(preview.origin, { x: 10, y: 20 });

assert.throws(() => applyOps(before, [{ kind: "nope" }]), /不认识的操作/);
assert.throws(() => applyOps(before, [{ kind: "remove_region", region_id: "missing" }]), /没有这个范围/);
assert.throws(() => applyOps(before, [{ kind: "set_building", width_m: 0, height_m: 10 }]), /大于 0/);

const snapshot = toSnapshot(applied.edit, { experimentId: "case-1" });
assert.equal(snapshot.scene_name, "cangnan");
assert.equal(snapshot.site.width_m, 1800);
assert.equal(snapshot.building.width_m, 80);
assert.equal(snapshot.experiment_id, "case-1");
assert.equal(snapshot.poses[0].objectives.dem_soft, 1.5);
assert.equal(snapshot.poses[0].objectives.demand_distance, 4);
assert.equal("road_distance" in snapshot.poses[0].objectives, false);
assert.equal(snapshot.regions[0].ring.length, 4);
assert.notEqual(snapshotStamp(snapshot), snapshotStamp(toSnapshot(before)));
assert.equal(EDIT_OP_KINDS.length, 9);
console.log("edit op assertions passed");
