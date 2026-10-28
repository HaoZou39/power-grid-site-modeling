import assert from "node:assert/strict";
import {
  LANDUSE_CONFLICT,
  LANDUSE_SAVE_FIRST,
  acceptPublishedLanduse,
  addLanduseDraft,
  beginLanduseSave,
  completeLanduseSave,
  conflictLanduseSave,
  discardLanduseDraft,
  emptyLanduseDraft,
  failLanduseSave,
  landuseComputeBlocked,
  landusePreviewMarks,
  landuseSceneSwitch,
  landuseSaveEnabled,
  newLanduseEditId,
  noteLanduseScene,
  redoLanduseDraft,
  reloadPublishedLanduse,
  removeLanduseDraft,
  retainLanduseDraft,
  undoLanduseDraft,
  updateLanduseDraft,
} from "../../.tmp-problem-snapshot/map/landuse_draft.js";
import { autoPendingPoses, evaluationKey, isAwaitingReview, poseFreshness } from "../../.tmp-problem-snapshot/map/pose_evaluation.js";

const ring = (x) => [[x, x], [x + 4, x], [x + 4, x + 4]];
const water = (id, x = 3) => ({ id, class_id: 5, points: ring(x) });
const field = (id, x = 30) => ({ id, class_id: 1, points: ring(x) });

function published(items, revision = "v1", sceneId = "scene-a") {
  const bound = noteLanduseScene(emptyLanduseDraft(), sceneId);
  return acceptPublishedLanduse(bound, { sceneId, items, sceneRevision: revision, token: bound.loadToken });
}

const initial = published([water("pond"), field("plot")]);
assert.equal(initial.dirty, false);
assert.equal(initial.baseRevision, "v1");
assert.deepEqual(initial.draftItems.map((item) => item.id), ["pond", "plot"]);

const writes = [];
const calls = { pose: 0, report: 0, post: 0, put: 0, delete: 0 };
function recordDraft(state) {
  assert.equal(calls.pose, 0);
  assert.equal(calls.report, 0);
  assert.equal(writes.length, 0);
  return state;
}

let draft = recordDraft(initial);
assert.match(newLanduseEditId([]), /^[0-9a-f]{32}$/);
const ids = [];
for (let index = 0; index < 10; index += 1) {
  const id = newLanduseEditId(draft.draftItems, () => `patch-${index}`);
  ids.push(id);
  const next = addLanduseDraft(draft, water(id, 100 + index));
  assert.notEqual(next, draft);
  draft = recordDraft(next);
}
assert.equal(draft.dirty, true);
assert.equal(draft.draftItems.length, 12);
assert.deepEqual(ids, draft.draftItems.slice(2).map((item) => item.id));
assert.equal(landuseComputeBlocked(draft), LANDUSE_SAVE_FIRST);
assert.equal(landuseSaveEnabled(initial), false);

const removed = removeLanduseDraft(draft, "pond");
assert.equal(removed.publishedItems.some((item) => item.id === "pond"), true);
assert.equal(removed.draftItems.some((item) => item.id === "pond"), false);
assert.equal(writes.length, 0);
const undone = undoLanduseDraft(removed);
assert.equal(undone.draftItems.some((item) => item.id === "pond"), true);
assert.equal(redoLanduseDraft(undone).draftItems.some((item) => item.id === "pond"), false);

const edited = updateLanduseDraft(published([water("pond")]), "pond", { points: ring(8), class_id: 1 });
assert.equal(edited.draftItems[0].id, "pond");
assert.equal(edited.draftItems[0].class_id, 1);
assert.equal(edited.publishedItems[0].class_id, 5);
assert.deepEqual(landusePreviewMarks(edited.publishedItems, edited.draftItems).map((item) => item.status), ["modified"]);

const ordered = published([field("a", 1), water("b", 10)]);
const swapped = {
  ...ordered,
  draftItems: [ordered.draftItems[1], ordered.draftItems[0]],
  dirty: true,
  undo: [ordered.draftItems],
};
assert.deepEqual(swapped.draftItems.map((item) => item.id), ["b", "a"]);
assert.deepEqual(landusePreviewMarks(swapped.publishedItems, swapped.draftItems).map((item) => item.id), ["b", "a"]);

const started = beginLanduseSave(edited);
assert.equal(started.request.items.length, 1);
assert.equal(started.request.expected_scene_revision, "v1");
assert.equal(started.request.items[0].id, "pond");
assert.equal(beginLanduseSave(started.state).request, null);
const saved = completeLanduseSave(started.state, {
  items: started.request.items,
  scene_revision: "v2",
  changed: true,
});
assert.equal(saved.dirty, false);
assert.equal(saved.baseRevision, "v2");
assert.equal(saved.draftItems[0].id, "pond");
writes.push("batch");
assert.equal(writes.length, 1);
assert.equal(calls.post + calls.put + calls.delete, 0);

const same = beginLanduseSave(saved);
assert.equal(same.request, null);
const unchanged = completeLanduseSave(
  { ...beginLanduseSave(addLanduseDraft(saved, water("extra", 70))).state, saving: true },
  { items: saved.draftItems, scene_revision: "v2", changed: false },
);
assert.equal(unchanged.baseRevision, "v2");
assert.equal(unchanged.dirty, false);

const failed = failLanduseSave(started.state, "写入失败");
assert.equal(failed.saving, false);
assert.equal(failed.draftItems[0].class_id, 1);
assert.equal(failed.baseRevision, "v1");

const conflicted = conflictLanduseSave(started.state);
assert.equal(conflicted.conflict, true);
assert.equal(conflicted.draftItems[0].id, "pond");
assert.equal(conflicted.baseRevision, "v1");
assert.equal(beginLanduseSave(conflicted).request, null);
assert.equal(addLanduseDraft(conflicted, water("nope", 90)), conflicted);
assert.equal(acceptPublishedLanduse(conflicted, {
  sceneId: "scene-a", items: [], sceneRevision: "v2", token: conflicted.loadToken,
}), conflicted);
assert.equal(landuseComputeBlocked(conflicted), LANDUSE_CONFLICT);
const reloaded = reloadPublishedLanduse(conflicted, [water("server")], "v2");
assert.equal(reloaded.conflict, false);
assert.equal(reloaded.draftItems[0].id, "server");

const abandoned = discardLanduseDraft(edited);
assert.equal(abandoned.dirty, false);
assert.equal(abandoned.draftItems[0].class_id, 5);
assert.equal(beginLanduseSave(abandoned).request, null);
assert.equal(discardLanduseDraft(started.state), started.state);

const other = landuseSceneSwitch(edited, "scene-b");
assert.equal(other.allowed, false);
assert.equal(other.state.sceneId, "scene-a");
assert.equal(other.state.draftItems[0].class_id, 1);
const cleanSwitch = landuseSceneSwitch(abandoned, "scene-b");
assert.equal(cleanSwitch.allowed, true);
assert.equal(cleanSwitch.state.sceneId, "scene-b");
assert.equal(cleanSwitch.state.draftItems.length, 0);
assert.equal(acceptPublishedLanduse(cleanSwitch.state, {
  sceneId: "scene-a", items: [water("late")], sceneRevision: "old", token: abandoned.loadToken,
}), cleanSwitch.state);

const editing = addLanduseDraft(initial, water("new", 50));
assert.equal(acceptPublishedLanduse(editing, {
  sceneId: "scene-a", items: initial.publishedItems, sceneRevision: "v1", token: editing.loadToken,
}), editing);
assert.equal(retainLanduseDraft(editing), editing);

const sessionPublished = published([water("old-a"), water("old-b"), field("old-c")]);
let session = sessionPublished;
for (let index = 0; index < 3; index += 1) session = addLanduseDraft(session, water(`water-${index}`, 10 + index));
for (let index = 0; index < 2; index += 1) session = addLanduseDraft(session, field(`field-${index}`, 40 + index));
session = removeLanduseDraft(session, "old-a");
session = removeLanduseDraft(session, "old-b");
session = updateLanduseDraft(session, "old-c", { points: ring(80) });
assert.equal(calls.pose, 0);
assert.equal(calls.report, 0);
const batch = beginLanduseSave(session);
assert.ok(batch.request);
assert.deepEqual(batch.request.items.map((item) => item.id), ["old-c", "water-0", "water-1", "water-2", "field-0", "field-1"]);
assert.equal(batch.request.expected_scene_revision, "v1");
const client = { batches: 0 };
client.batches += 1;
const publishedSession = completeLanduseSave(batch.state, {
  items: batch.request.items,
  scene_revision: "v3",
  changed: true,
});
assert.equal(client.batches, 1);
assert.equal(publishedSession.dirty, false);

const solutions = [
  { id: "p1", layer: 1 },
  { id: "p2", layer: 2 },
  { id: "p3", layer: 3 },
];
const zones = [{ id: "ex", kind: "exclusion" }, { id: "ok", kind: "feasible" }];
const farmland = { file: "protected_farmland_mask_1m.npy", bytes: 4 };
assert.deepEqual(solutions.map((item) => item.layer), [1, 2, 3]);
assert.equal(solutions.length, 3);
assert.deepEqual(zones.map((item) => item.kind), ["exclusion", "feasible"]);
assert.equal(farmland.file, "protected_farmland_mask_1m.npy");

const pose = { x: 1, y: 2, theta: 0, evaluatedFor: evaluationKey("scene-a", { scene_revision: "v1" }, { x: 1, y: 2, theta: 0 }) };
const freshness = (revision) => poseFreshness(pose.evaluatedFor, "scene-a", { scene_revision: revision }, pose);
assert.equal(freshness("v1"), "current");
assert.equal(freshness("v3"), "revision-stale");
assert.equal(isAwaitingReview(freshness("v3")), true);
assert.equal(autoPendingPoses([pose], (item) => evaluationKey("scene-a", { scene_revision: "v3" }, item), new Set(), new Map(), () => freshness("v3")).length, 0);
assert.equal(autoPendingPoses([pose], (item) => evaluationKey("scene-a", { scene_revision: "v1" }, item), new Set(), new Map(), () => freshness("v1")).length, 0);
assert.equal(landuseComputeBlocked(publishedSession), null);
assert.equal(landuseComputeBlocked(session), LANDUSE_SAVE_FIRST);

const invalid = addLanduseDraft(initial, { id: "bad id", class_id: 5, points: ring(1) });
assert.equal(invalid, initial);
assert.equal(addLanduseDraft(initial, water("pond")), initial);

const addedWater = addLanduseDraft(initial, water("new-pond", 60));
assert.equal(addedWater.dirty, true);
assert.equal(landuseSaveEnabled(addedWater), true);
const removedNew = removeLanduseDraft(addedWater, "new-pond");
assert.equal(removedNew.dirty, false);
assert.equal(landuseSaveEnabled(removedNew), false);

const removedPublished = removeLanduseDraft(initial, "pond");
assert.equal(removedPublished.dirty, true);
assert.equal(removedPublished.draftItems.some((item) => item.id === "pond"), false);
const restored = undoLanduseDraft(removedPublished);
assert.equal(restored.dirty, false);
assert.deepEqual(restored.draftItems.map((item) => item.id), ["pond", "plot"]);
const road = (id, x = 70) => ({ id, class_id: 3, points: ring(x) });
const building = (id, x = 90) => ({ id, class_id: 2, points: ring(x) });
const mixed = published([water("w"), field("f"), road("r"), building("b")]);
for (const id of ["w", "f", "r", "b"]) {
  const next = removeLanduseDraft(mixed, id);
  assert.equal(next.dirty, true);
  assert.equal(next.draftItems.some((item) => item.id === id), false);
  assert.equal(undoLanduseDraft(next).dirty, false);
}
assert.equal(landuseComputeBlocked(removedPublished) !== null, true);

console.log("landuse draft: passed");
