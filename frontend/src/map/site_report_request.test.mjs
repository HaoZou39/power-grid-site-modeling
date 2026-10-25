import assert from "node:assert/strict";

import { SiteEdit } from "../../.tmp-problem-snapshot/map/site_edit.js";

const edit = new SiteEdit(
  "cangnan",
  77,
  51.5,
  "blocked",
  "costly",
  0.35,
  [{ id: "origin", kind: "origin", x: 12, y: 14 }],
  [
    { id: "excluded", kind: "exclusion", ring: [{ x: 1, y: 1 }, { x: 4, y: 1 }, { x: 2, y: 4 }] },
    { id: "feasible", kind: "feasible", ring: [{ x: 0, y: 0 }, { x: 20, y: 0 }, { x: 10, y: 20 }] },
  ],
  [{ id: "a", x: 100, y: 120, theta: 0 }, { id: "b", x: 240, y: 360, theta: 0.5 }],
  "b",
);
const report = edit.reportRequest();

assert.equal(report.x, 240);
assert.equal(report.y, 360);
assert.equal(report.theta, 0.5);
assert.equal(report.field_policy, "costly");
assert.equal(report.mountain_policy, "blocked");
assert.equal(report.field_cost, 0.35);
assert.equal(report.origin_x, 12);
assert.equal(report.origin_y, 14);
assert.deepEqual(report.exclusion_zones, edit.searchConfig().exclusion_zones);
assert.deepEqual(report.feasible_zones, edit.searchConfig().feasible_zones);
assert.equal(report.diagonal_access, true);
assert.equal(report.water_setback_m, 5);
assert.equal(edit.searchConfig().diagonal_access, true);

console.log("site report request assertions passed");
