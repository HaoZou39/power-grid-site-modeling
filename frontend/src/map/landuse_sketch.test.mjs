import assert from "node:assert/strict";
import { landuseEditClassId, pointInLanduseRing } from "../../.tmp-problem-snapshot/map/landuse_sketch.js";

const first = { x: 1, y: 2 };
const second = { x: 5, y: 2 };
const third = { x: 5, y: 7 };
const fourth = { x: 1, y: 7 };
const points = [first, second, third, fourth];

assert.equal(landuseEditClassId("field"), 1);
assert.equal(landuseEditClassId("building"), 2);
assert.equal(landuseEditClassId("road"), 3);
assert.equal(landuseEditClassId("water"), 5);
assert.equal(pointInLanduseRing({ x: 3, y: 3 }, points), true);
assert.equal(pointInLanduseRing({ x: 9, y: 3 }, points), false);
