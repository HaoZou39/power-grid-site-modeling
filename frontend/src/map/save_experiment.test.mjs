import assert from 'node:assert/strict';
import { experimentSaveBody } from '../../.tmp-problem-snapshot/map/save_experiment.js';
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
assert.equal(body.rect_w_m, edit.widthM);
assert.equal('dem_soft' in body.poses[0], false);
assert.throws(() => experimentSaveBody(' ', edit, [], null));
assert.throws(() => experimentSaveBody('empty', edit.clearPoses(), [], null));
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
console.log('named workspace saving and complete retained pose reload: passed');
