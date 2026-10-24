import assert from "node:assert/strict";
import { LatestOverlayRequest, feasibilityRequest, replaceOverlayObjectUrl } from "../../.tmp-problem-snapshot/map/feasibility_overlay.js";
import { SiteEdit } from "../../.tmp-problem-snapshot/map/site_edit.js";

const edit = new SiteEdit()
  .withPolicies("blocked", "costly", 0.7)
  .addExclusion([{ x: 1, y: 1 }, { x: 4, y: 1 }, { x: 1, y: 4 }]);
const body = feasibilityRequest(edit.searchConfig());
assert.deepEqual(Object.keys(body), [
  "mountain_policy",
  "field_policy",
  "field_cost",
  "exclusion_zones",
  "feasible_zones",
  "road_setback_m",
  "water_setback_m",
]);
assert.equal(body.road_setback_m, 5);
assert.equal(body.water_setback_m, 5);
assert.equal(body.mountain_policy, "blocked");
assert.equal(body.field_policy, "costly");
assert.equal(body.field_cost, 0.7);
assert.equal(body.exclusion_zones.length, 1);

const gate = new LatestOverlayRequest();
const oldRequest = gate.begin();
const currentRequest = gate.begin();
assert.equal(gate.isCurrent(oldRequest), false);
assert.equal(gate.isCurrent(currentRequest), true);

const revoked = [];
let url = replaceOverlayObjectUrl(null, "blob:first", (value) => revoked.push(value));
url = replaceOverlayObjectUrl(url, "blob:second", (value) => revoked.push(value));
assert.equal(url, "blob:second");
assert.deepEqual(revoked, ["blob:first"]);
url = replaceOverlayObjectUrl(url, null, (value) => revoked.push(value));
assert.equal(url, null);
assert.deepEqual(revoked, ["blob:first", "blob:second"]);
