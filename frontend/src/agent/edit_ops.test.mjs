import assert from "node:assert/strict";
import { SiteEdit } from "../../.tmp-problem-snapshot/map/site_edit.js";
import { EDIT_OP_KINDS, applyOps, describeOps, proposalPreview } from "../../.tmp-problem-snapshot/agent/edit_ops.js";
import { preferenceChoice, snapshotStamp, toSnapshot } from "../../.tmp-problem-snapshot/agent/workspace_snapshot.js";

const ring = [{ x: 1, y: 1 }, { x: 4, y: 1 }, { x: 4, y: 4 }, { x: 1, y: 4 }];
const before = new SiteEdit("cangnan", 77, 51.5).withPoses([
  { id: "a", x: 1, y: 1, theta: 0, demSoft: "1.5", roadDistance: "", demandDistance: "4" },
  { id: "b", x: 2, y: 2, theta: 0 },
  { id: "c", x: 120, y: 100, theta: 0 },
]);
const layers = {
  panel_open: false,
  scene_ready: true,
  dem: { visible: false, opacity: 0.6, available: true },
  landuse: {
    field: { visible: true, available: true },
    building: { visible: true, available: true },
    road: { visible: true, available: true },
    water: { visible: true, available: true },
  },
  osm_roads: { visible: false, available: true },
  regions: { exclusion: true, feasible: true },
};

const applied = applyOps(before, [
  { kind: "set_building", width_m: 80, height_m: 50 },
  { kind: "set_policies", mountain_policy: "blocked", field_cost: 0.25 },
  { kind: "set_origin", x: 10, y: 20 },
  { kind: "add_region", region_kind: "exclusion", ring },
  { kind: "update_pose", pose_id: "c", x: 135 },
  { kind: "select_pose", pose_id: "c" },
  { kind: "run_search", plugin_id: "site.guided_search" },
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

const layerApplied = applyOps(before, [
  { kind: "set_layer_visibility", layer: "dem", visible: true },
  { kind: "set_dem_opacity", opacity: 0.4 },
  { kind: "set_layer_visibility", layer: "field", visible: false },
  { kind: "set_layer_visibility", layer: "building", visible: false },
  { kind: "set_layer_visibility", layer: "exclusion", visible: false },
], layers);
assert.equal(layerApplied.edit, before);
assert.equal(layerApplied.runSearch, false);
assert.equal(layerApplied.refine, null);
assert.equal(layerApplied.layerChanges.length, 5);
assert.equal(layerApplied.layers.dem.visible, true);
assert.equal(layerApplied.layers.dem.opacity, 0.4);
assert.equal(layerApplied.layers.landuse.field.visible, false);
assert.equal(layerApplied.layers.landuse.building.visible, false);
assert.equal(layerApplied.layers.regions.exclusion, false);
assert.equal(layers.dem.visible, false);
assert.equal(layers.dem.opacity, 0.6);
assert.equal(before.regions.length, 0);
assert.deepEqual(describeOps(before, layerApplied.edit, layerApplied.layerChanges, layers), [
  "显示 DEM 高程",
  "DEM 透明度 60% → 40%",
  "隐藏农田",
  "隐藏建筑用地",
  "隐藏禁区",
]);

const panelOpened = applyOps(before, [{ kind: "set_layer_panel_open", open: true }], layers);
assert.equal(panelOpened.edit, before);
assert.equal(panelOpened.layers.panel_open, true);
assert.equal(layers.panel_open, false);
assert.deepEqual(panelOpened.layers.dem, layers.dem);
assert.deepEqual(panelOpened.layers.landuse, layers.landuse);
assert.deepEqual(panelOpened.layers.osm_roads, layers.osm_roads);
assert.deepEqual(panelOpened.layers.regions, layers.regions);
assert.deepEqual(describeOps(before, panelOpened.edit, panelOpened.layerChanges, layers), ["打开 GIS 图层面板"]);

const openLayers = { ...layers, panel_open: true };
const panelClosed = applyOps(before, [{ kind: "set_layer_panel_open", open: false }], openLayers);
assert.equal(panelClosed.layers.panel_open, false);
assert.equal(openLayers.panel_open, true);
assert.deepEqual(panelClosed.layers.dem, openLayers.dem);
assert.deepEqual(describeOps(before, panelClosed.edit, panelClosed.layerChanges, openLayers), ["关闭 GIS 图层面板"]);

const mixed = applyOps(before, [
  { kind: "set_building", width_m: 80, height_m: 51.5 },
  { kind: "set_layer_panel_open", open: true },
  { kind: "set_layer_visibility", layer: "dem", visible: true },
], layers);
assert.equal(mixed.edit.widthM, 80);
assert.equal(mixed.layers.panel_open, true);
assert.equal(mixed.layers.dem.visible, true);
assert.throws(() => applyOps(before, [
  { kind: "set_layer_visibility", layer: "dem", visible: true },
], { ...layers, dem: { ...layers.dem, available: false } }), /没有可用的 DEM/);

const lines = describeOps(before, applied.edit, [
  { kind: "run_search", plugin_id: "site.guided_search" },
]);
assert.ok(lines.includes("建筑 77×51.5 → 80×50"));
assert.ok(lines.includes("新增禁区 4 点"));
assert.ok(lines.includes("方案 #3 x 120→135"));
assert.ok(lines.includes("开始一次引导式多目标搜索"));

const cleared = applyOps(applied.edit, [{ kind: "clear_origin" }, { kind: "remove_region", region_id: applied.edit.regions[0].id }]);
assert.equal(cleared.edit.origin, null);
assert.equal(cleared.edit.regions.length, 0);
assert.equal(cleared.runSearch, false);
assert.deepEqual(describeOps(applied.edit, cleared.edit), ["清除进货原点", `删除范围 ${applied.edit.regions[0].id}`]);

const swapped = applyOps(applied.edit, [
  { kind: "remove_region", region_id: "zone-1" },
  { kind: "add_region", region_kind: "feasible", ring },
]);
assert.equal(swapped.edit.regions[0].id, "zone-1");
assert.deepEqual(describeOps(applied.edit, swapped.edit), ["删除范围 zone-1", "新增可行域 4 点"]);

const preview = proposalPreview(before, applied.edit);
assert.equal(preview.regions.length, 1);
assert.equal(preview.poses.length, 1);
assert.equal(preview.poses[0].id, "c");
assert.deepEqual(preview.origin, { x: 10, y: 20 });

assert.throws(() => applyOps(before, [{ kind: "nope" }]), /不认识的操作/);
assert.throws(() => applyOps(before, [{ kind: "remove_region", region_id: "missing" }]), /没有这个范围/);
assert.throws(() => applyOps(before, [{ kind: "set_building", width_m: 0, height_m: 10 }]), /大于 0/);
assert.throws(
  () => applyOps(before, [{ kind: "update_pose", pose_id: "c", x: 10, y: 10, theta: Math.PI / 4 }]),
  /完整建筑会超出/,
);

const snapshot = toSnapshot(applied.edit, { experimentId: "case-1" });
assert.equal(snapshot.scene_name, "cangnan");
assert.equal(snapshot.site.width_m, 1800);
assert.equal(snapshot.building.width_m, 80);
assert.equal(snapshot.experiment_id, "case-1");
assert.equal(snapshot.layers.scene_ready, false);
const layerSnapshot = toSnapshot(before, { layers });
assert.equal(layerSnapshot.layers.dem.opacity, 0.6);
assert.notEqual(snapshotStamp(layerSnapshot), snapshotStamp(toSnapshot(before)));
assert.equal(snapshot.poses[0].objectives.dem_soft, 1.5);
assert.equal("demand_distance" in snapshot.poses[0].objectives, false);
assert.equal(toSnapshot(applied.edit.withIncludeDemand(true)).poses[0].objectives.demand_distance, 4);
assert.equal("road_distance" in snapshot.poses[0].objectives, false);
assert.equal(snapshot.regions[0].ring.length, 4);
assert.notEqual(snapshotStamp(snapshot), snapshotStamp(toSnapshot(before)));
const menu = { ...snapshot, poses: [...snapshot.poses, { id: "d", x: 0, y: 0, theta: 0, objectives: { dem_soft: 2 } }, { id: "e", x: 0, y: 0, theta: 0 }] };
assert.deepEqual(preferenceChoice(menu, "d").candidates.map((candidate) => candidate.id), [snapshot.poses[0].id, "d"]);
assert.equal(preferenceChoice(menu, "d").experiment_id, "case-1");
assert.throws(() => preferenceChoice(menu, "e"), /还没有目标值/);
assert.throws(() => preferenceChoice(snapshot, snapshot.poses[0].id), /两个/);
assert.equal(EDIT_OP_KINDS.length, 13);
console.log("edit op assertions passed");

{
  const refined = applyOps(before, [{ kind: "refine_pose", pose_id: "c" }]);
  assert.deepEqual(refined.refine, { poseId: "c", halfWidthM: 150 });
  assert.equal(refined.runSearch, false);
  assert.equal(refined.edit, before);
  assert.deepEqual(describeOps(before, refined.edit, [{ kind: "refine_pose", pose_id: "c", half_width_m: 100 }]), [
    "在方案 #3 周围 200×200 m 内局部优化，新方案加到地图上，原方案保留",
  ]);
  assert.throws(() => applyOps(before, [{ kind: "refine_pose", pose_id: "zz" }]), /没有这个方案/);
  assert.throws(() => applyOps(before, [{ kind: "refine_pose", pose_id: "c", half_width_m: 10 }]), /30 到 400/);
  assert.throws(() => applyOps(before, [
    { kind: "refine_pose", pose_id: "c" },
    { kind: "run_search", plugin_id: "site.guided_search" },
  ]), /同一个提案/);

  const snap = toSnapshot(before.withPoses([{ id: "r/1", x: 5, y: 5, theta: 0, demSoft: "1", feasible: "不可行", derivedFrom: "c" }]));
  assert.deepEqual(snap.poses[0], { id: "r/1", x: 5, y: 5, theta: 0, objectives: { dem_soft: 1 }, feasible: false, derived_from: "c" });
  const pending = toSnapshot(before.withPoses([{ id: "p", x: 5, y: 5, theta: 0, demSoft: "重算中", feasible: "重算中" }]));
  assert.deepEqual(pending.poses[0], { id: "p", x: 5, y: 5, theta: 0 });
}
