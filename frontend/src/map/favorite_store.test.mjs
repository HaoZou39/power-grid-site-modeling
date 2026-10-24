import assert from "node:assert/strict";
import { FavoriteStore } from "../../.tmp-problem-snapshot/map/favorite_store.js";
import { favoritePointPose, favoritePoseSnapshot } from "../../.tmp-problem-snapshot/map/favorite_points.js";
import { SiteFrame } from "../../.tmp-problem-snapshot/map/site_frame.js";

const frame = new SiteFrame(13379105, 3187189, 1, -1, 600, 600);
const manual = favoritePoseSnapshot({ x: 100, y: 120 }, -Math.PI / 2, 77, 51.5, frame);
const optimized = favoritePoseSnapshot({ x: 350, y: 350 }, 0.73, 65, 42, frame);
const database = new Map();
let creates = 0;
let sequence = 0;
const api = {
  async list(scene) { return structuredClone(database.get(scene) ?? []); },
  async create(scene, input) {
    creates++;
    const saved = { ...input, id: `favorite-${++sequence}`, scene_id: scene, created_at: "now", updated_at: "now" };
    database.set(scene, [...(database.get(scene) ?? []), saved]);
    return structuredClone(saved);
  },
  async update(scene, id, input) {
    const rows = database.get(scene);
    const saved = { ...rows.find((item) => item.id === id), ...input, updated_at: "updated" };
    database.set(scene, rows.map((item) => item.id === id ? saved : item));
    return structuredClone(saved);
  },
  async remove(scene, id) { database.set(scene, database.get(scene).filter((item) => item.id !== id)); },
};
const store = new FavoriteStore(api);
await store.load("cangnan");
const first = await store.create(manual);
const second = await store.create(optimized);
assert.equal(creates, 2);
assert.equal(store.snapshot().selectedId, second.id);
await store.create(optimized);
assert.equal(creates, 2, "same optimization result must not be saved twice");
assert.equal(store.snapshot().items[1].width_m, 65);

store.select(first.id);
store.previewMove(second.id, 12, -8, frame);
assert.equal(store.snapshot().selectedId, second.id, "a different favorite moves on the first gesture");
assert.ok(Math.abs(store.snapshot().preview.center.x - 362) < 1e-6);
assert.ok(Math.abs(store.snapshot().preview.center.y - 342) < 1e-6);
assert.equal(store.snapshot().items[1].longitude, second.longitude, "drag preview must not change saved records");
await store.finishMove(frame);
let moved = favoritePointPose(store.snapshot().items[1], frame);
assert.ok(Math.abs(moved.center.x - 362) < 1e-6);
assert.ok(Math.abs(moved.center.y - 342) < 1e-6);
await store.updatePose(second.id, moved.center, 45, frame);
assert.equal(store.snapshot().items[1].bearing_deg, 45);
assert.equal(store.snapshot().preview, null);

const reopened = new FavoriteStore(api);
await reopened.load("cangnan");
assert.deepEqual(reopened.snapshot().items, store.snapshot().items);
await reopened.load("yongjia");
assert.equal(reopened.snapshot().items.length, 0);
await reopened.load("cangnan");
assert.equal(reopened.snapshot().items.length, 2);
await reopened.remove(first.id);
assert.equal(reopened.snapshot().items.length, 1);

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

// A slow initial list cannot erase a successfully saved new favorite.
const list = deferred();
const loading = new FavoriteStore({ ...api, list: () => list.promise });
const initial = loading.load("slow");
await assert.rejects(loading.create(manual), /正在读取收藏/);
list.resolve([]);
await initial;
await loading.create(manual);
assert.equal(loading.snapshot().items.length, 1);
assert.equal(loading.snapshot().error, "");

// Serialize writes and retain confirmed data on a rejected update/delete.
const write = deferred();
const serialized = new FavoriteStore({ ...api, update: () => write.promise, remove: async () => { throw new Error("delete rejected"); } });
await serialized.load("cangnan");
const saved = serialized.snapshot().items[0];
serialized.previewMove(saved.id, 3, 2, frame);
const finishing = serialized.finishMove(frame);
await assert.rejects(serialized.create(manual), /正在保存收藏/);
write.reject(new Error("update rejected"));
await assert.rejects(finishing, /update rejected/);
assert.equal(serialized.snapshot().preview, null);
assert.deepEqual(serialized.snapshot().items[0], saved);
await assert.rejects(serialized.remove(saved.id), /delete rejected/);
assert.deepEqual(serialized.snapshot().items[0], saved);
assert.equal(serialized.snapshot().saving, false);

// A -> B -> A must reject responses from the previous visit to A.
const oldList = deferred();
let lists = 0;
const scoped = new FavoriteStore({ ...api, list: async () => ++lists === 1 ? oldList.promise : [] });
const oldLoad = scoped.load("A");
await scoped.load("B");
await scoped.load("A");
oldList.resolve([first]);
await oldLoad;
assert.deepEqual(scoped.snapshot().items, []);
const oldWrite = deferred();
const scopedWrite = new FavoriteStore({ ...api, create: () => oldWrite.promise });
await scopedWrite.load("A");
const oldSave = scopedWrite.create(manual);
await scopedWrite.load("B");
await scopedWrite.load("A");
oldWrite.resolve({ ...first, scene_id: "A" });
assert.equal(await oldSave, null);
assert.deepEqual(scopedWrite.snapshot().items, []);
assert.equal(scopedWrite.snapshot().saving, false);

await assert.rejects(store.updatePose(second.id, { x: 0, y: 0 }, 45, frame), /数据覆盖范围/);
console.log("favorite store: both entries, reload, movement, write ordering and failures passed");
