import assert from 'node:assert/strict';
import { captureFastSaveProvenance, experimentSaveBody, fastSaveSourceExperimentId } from '../../.tmp-problem-snapshot/map/save_experiment.js';
import { GuidedDecisionRun, manualChoice, restoreChoice } from '../../.tmp-problem-snapshot/map/decision_run.js';
import { SiteEdit } from '../../.tmp-problem-snapshot/map/site_edit.js';

const a = { ...manualChoice('a', { x: 100, y: 100 }, 0), manual: undefined, paretoLayer: 1 };
const hidden = { ...a, id: 'hidden', paretoLayer: 3 };
const moved = { ...a, x: 110, theta: .7 };
const manual = manualChoice('manual-1', { x: 200, y: 200 }, .2);
const edit = new SiteEdit().withPoses([moved, manual]);
const body = experimentSaveBody('  筛选后的实验  ', edit, [a, hidden], 'original-run');
assert.equal(body.name, '筛选后的实验');
assert.deepEqual(body.poses.map(p => p.id), ['a', 'hidden', 'manual-1']);
assert.equal(body.poses[0].x, 110);
assert.equal(body.poses[0].theta, .7);
assert.equal(body.poses[1].pareto_layer, 3);
assert.equal(body.poses[2].manual, true);
assert.equal(body.source_experiment_id, 'original-run');
assert.equal(body.fast_save_source_experiment_id, undefined);
assert.equal(body.rect_w_m, edit.widthM);
assert.equal('dem_soft' in body.poses[0], false);
assert.throws(() => experimentSaveBody(' ', edit, [], null));
assert.throws(() => experimentSaveBody('empty', edit.clearPoses(), [], null));
for (const draft of ['', ' ', 'NaN', 'Infinity']) {
  assert.throws(() => experimentSaveBody('invalid elevation', edit.withElevation(true, draft), [], null), /海拔/);
}
assert.equal(experimentSaveBody('limited', edit.withElevation(true, '-2.5'), [], null).max_elevation_m, -2.5);
assert.equal(experimentSaveBody('unlimited', edit.withElevation(false, ''), [], null).max_elevation_m, null);
// After deleting the last visible pose, an undeleted hidden pose is still saveable.
assert.deepEqual(experimentSaveBody('hidden only', edit.clearPoses(), [hidden], null).poses.map(p => p.id), ['hidden']);

const solutions = body.poses.map((p, i) => ({ ...p, dem_soft: i + 1, road_distance: 2, demand_distance: 3,
  road_haul_m: '', offroad_haul_m: 4, haul_rise_m: 5, obstacle_hard_count: i === 1 ? 12 : 0, is_feasible: i !== 1 }));
const run = new GuidedDecisionRun({
  getExperiments: async () => [{ id: 'saved', artifacts: [{ name: 'workspace_solutions.json', url: '/workspace' }] }],
  fetchArtifactText: async () => JSON.stringify({ format: 'workspace-solutions-v1', solutions }),
});
const loaded = await run.loadPareto('saved', true);
assert.deepEqual(loaded.map(p => p.id), ['a', 'hidden', 'manual-1']);
assert.equal(loaded[1].feasible, '不可行');
assert.equal(loaded[1].paretoLayer, 3);
assert.equal(loaded[2].manual, true);
assert.equal(loaded[0].manual, undefined);
assert.equal(loaded[0].baseline.demSoft, loaded[0].demSoft);
assert.equal(restoreChoice({ ...loaded[0], x: 500 }).x, 110);
assert.deepEqual((await run.loadPareto('saved')).map(p => p.id), ['a', 'manual-1']);
const layer1 = { ...a, id: 'a', x: 1, y: 2, theta: .1, paretoLayer: 1 };
const layer2 = { ...layer1, id: 'b', x: 3, paretoLayer: 2 };
const layer3 = { ...layer1, id: 'c', x: 4, paretoLayer: 3 };
const retained = new SiteEdit().withPoses([layer1]);
const retainedPool = [layer1, layer2, layer3];
const loadedScene = { sceneId: retained.sceneName, frameId: 'frame', sceneRevision: 'rev' };
const provenance = captureFastSaveProvenance(retained, retainedPool, {
  experimentId: 'run-1', jobId: 'job-1', sceneId: retained.sceneName, frameId: 'frame', sceneRevision: 'rev',
});
assert.equal(provenance.poses.length, 3);
assert.equal(fastSaveSourceExperimentId(provenance, retained, retainedPool, loadedScene, false), 'run-1');
assert.equal(fastSaveSourceExperimentId(provenance, retained.withPoses([layer1, layer2, layer3]), retainedPool, loadedScene, false), 'run-1');
assert.equal(fastSaveSourceExperimentId(provenance, retained.withPoses([{ ...layer1, x: 9 }]), retainedPool, loadedScene, false), null);
assert.equal(fastSaveSourceExperimentId(provenance, retained.withBuilding(80, 40), retainedPool, loadedScene, false), null);
assert.equal(fastSaveSourceExperimentId(provenance, retained.withPoses([{ ...layer1, theta: 1 }]), retainedPool, loadedScene, false), null);
assert.equal(fastSaveSourceExperimentId(provenance, retained, [layer1, layer3], loadedScene, false), null);
assert.equal(fastSaveSourceExperimentId(provenance, retained.withPoses([layer1, manual]), [...retainedPool, manual], loadedScene, false), null);
const derived = { ...layer2, id: 'local', derivedFrom: 'a' };
assert.equal(fastSaveSourceExperimentId(provenance, retained.withPoses([layer1, derived]), [...retainedPool, derived], loadedScene, false), null);
assert.equal(fastSaveSourceExperimentId(provenance, retained, retainedPool, loadedScene, true), null);
assert.equal(fastSaveSourceExperimentId(provenance, retained, retainedPool, { ...loadedScene, sceneRevision: 'next' }, false), null);
assert.equal(fastSaveSourceExperimentId(null, retained, retainedPool, loadedScene, false), null);
const fastBody = experimentSaveBody('未修改', retained, retainedPool, 'run-1', 'run-1');
assert.equal(fastBody.fast_save_source_experiment_id, 'run-1');
assert.deepEqual(fastBody.poses.map((pose) => pose.id), ['a', 'b', 'c']);
assert.deepEqual(fastBody.poses.map((pose) => pose.pareto_layer), [1, 2, 3]);
console.log('named workspace saving and complete retained pose reload: passed');
