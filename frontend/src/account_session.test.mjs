import assert from "node:assert/strict";
import { resetAccountStorage } from "./account_storage.ts";

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
console.log("account session storage ok");
