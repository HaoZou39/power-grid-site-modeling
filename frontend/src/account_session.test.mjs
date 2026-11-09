import assert from "node:assert/strict";
import { resetAccountStorage } from "./account_storage.ts";
import { readRoutingPreference, writeRoutingPreference } from "./agent/routing_preference.ts";
import { recallUpdate, rememberUpdate } from "./map/software_update.ts";
import { readMapTheme, writeMapTheme } from "./map/theme.ts";

const storage = {
  values: new Map(),
  clear() { this.values.clear(); },
};
storage.values.set("routing-job:cangnan", "job-a");
storage.values.set("active-account", "user-a");
resetAccountStorage(storage, "user-a", "user-a");
assert.equal(storage.values.size, 2);
resetAccountStorage(storage, "user-a", "user-b");
assert.equal(storage.values.size, 0);

const local = {
  values: new Map(),
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; },
  setItem(key, value) { this.values.set(key, value); },
  removeItem(key) { this.values.delete(key); },
};
const preference = { tower_count: 4, length_3d_m: 1, bend_sum_rad: 2, crossing_3d_m: 0 };
writeRoutingPreference(local, "user-a", preference);
rememberUpdate(local, "user-a", { id: "run-a", phase: "waiting", message: "更新中", startedAt: 1 });
writeMapTheme(local, "light");
assert.deepEqual(readRoutingPreference(local, "user-b"), null);
assert.equal(recallUpdate(local, "user-b"), null);
assert.deepEqual(readRoutingPreference(local, "user-a"), preference);
assert.equal(recallUpdate(local, "user-a").id, "run-a");
assert.equal(readMapTheme(local), "light");
assert.equal(local.values.has("power-grid.routing-preference.v1"), false);
assert.equal(local.values.has("software-update-pending"), false);
console.log("account session storage ok");
