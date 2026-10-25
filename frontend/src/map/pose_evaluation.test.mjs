import assert from 'node:assert/strict';
import { evaluationKey, pendingPoses, batches } from '../../.tmp-problem-snapshot/map/pose_evaluation.js';
import { manualChoice, measuredChoice, restoreChoice, unmeasured } from '../../.tmp-problem-snapshot/map/decision_run.js';
import { SiteEdit } from '../../.tmp-problem-snapshot/map/site_edit.js';
import { visibleAtLevel } from '../../.tmp-problem-snapshot/map/solution_diversity.js';
import { paretoLayerCounts, selectExportPoses } from '../../.tmp-problem-snapshot/map/scene_export.js';
import { toolbarCommands } from '../../.tmp-problem-snapshot/map/toolbar_commands.js';
import { toSnapshot } from '../../.tmp-problem-snapshot/agent/workspace_snapshot.js';

const edit = new SiteEdit();
const pose = manualChoice('manual-1', { x: 900, y: 900 }, 0);
const config = edit.searchConfig();
const key = evaluationKey('scene', config, pose);
assert.equal(evaluationKey('scene', { ...config, include_demand: true, scene_name: 'ignored' }, pose), key);
for (const change of [{ road_setback_m: 17 }, { road_product_id: 'new' }, { farmland_content_sha256: 'new' }, { origin_x: 10 }, { field_policy: 'blocked' }]) {
  assert.notEqual(evaluationKey('scene', { ...config, ...change }, pose), key);
}
const landInputs = { ...config, road_product_id: 'same', farmland_content_sha256: 'same', landuse_revision: 1 };
const beforeLandEdit = { ...pose, evaluatedFor: evaluationKey('scene', landInputs, pose) };
const afterLandEdit = { ...landInputs, landuse_revision: 2 };
const landKeyOf = (p) => evaluationKey('scene', afterLandEdit, p);
assert.notEqual(landKeyOf(beforeLandEdit), beforeLandEdit.evaluatedFor);
assert.deepEqual(pendingPoses([beforeLandEdit], landKeyOf, new Set(), new Map()), [beforeLandEdit]);
// Requests and failures from the old revision must not suppress the new evaluation.
assert.deepEqual(pendingPoses([beforeLandEdit], landKeyOf,
  new Set([beforeLandEdit.evaluatedFor]), new Map([[beforeLandEdit.evaluatedFor, 'old failure']])), [beforeLandEdit]);
const moved = { ...pose, x: 901 };
assert.notEqual(evaluationKey('scene', config, moved), key);
assert.deepEqual(batches(Array.from({ length: 201 }, (_, i) => i)).map((batch) => batch.length), [200, 1]);
const keyOf = (p) => evaluationKey('scene', config, p);
assert.deepEqual(pendingPoses([pose], keyOf, new Set([key]), new Map()), []);
assert.deepEqual(pendingPoses([pose], keyOf, new Set(), new Map([[key, 'failed']])), []);
assert.deepEqual(pendingPoses([{ ...moved, evaluatedFor: key }], keyOf, new Set(), new Map()), [{ ...moved, evaluatedFor: key }]);
const row = { dem_soft: 1, road_distance: 2, demand_distance: 3, road_haul_m: '', offroad_haul_m: 4, haul_rise_m: 5, obstacle_hard_count: 0, is_feasible: true };
const measured = measuredChoice(pose, row, key);
assert.equal(measured.baseline.demSoft, measured.demSoft);
assert.equal(measured.evaluatedFor, key);
assert.equal(unmeasured(measured).evaluatedFor, undefined);
const pendingSnapshot = toSnapshot(edit.withPoses([unmeasured(measured)])).poses[0];
assert.equal(pendingSnapshot.objectives, undefined);
assert.equal(pendingSnapshot.feasible, undefined);
assert.equal(toSnapshot(edit.withPoses([measuredChoice(pose, { ...row, is_feasible: false }, landKeyOf(pose))])).poses[0].feasible, false);
assert.equal(pendingPoses([unmeasured(measured)], keyOf, new Set(), new Map()).length, 1);
assert.equal(restoreChoice(measured).evaluatedFor, undefined);
const again = measuredChoice({ ...measured, x: 910 }, { ...row, dem_soft: 9 }, 'second');
assert.equal(again.baseline.demSoft, measured.demSoft);
const choices = edit.addPose(pose).addPose({ ...pose, id: 'b' }).addPose({ ...pose, id: 'c' }).selectPose('b');
assert.equal(choices.removePose('b').selectedPoseId, 'c');
assert.equal(choices.removePose('c').selectedPoseId, 'b');
assert.equal(choices.selectPose('c').removePose('c').selectedPoseId, 'b');
assert.equal(edit.addPose(pose).removePose(pose.id).selectedPoseId, null);
assert.equal(visibleAtLevel(pose, 1), true);
assert.deepEqual(paretoLayerCounts([pose]), { 1: 0, 2: 0, 3: 0 });
assert.deepEqual(selectExportPoses([pose], { 1: false, 2: false, 3: false }), [pose]);
const commands = toolbarCommands({ tool: 'pan', setTool() {}, focusSite() {}, notify() {}, poseAddDisabled: true });
assert.equal(commands.find((item) => item.id === 'pose-add').disabled, true);
console.log('pose evaluation and manual schemes: passed');
