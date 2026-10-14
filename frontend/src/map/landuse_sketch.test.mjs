import assert from "node:assert/strict";
import { addLanduseVertex, landuseEditClassId, pointInLanduseRing, removeLastLanduseVertex, removeLanduseRingVertex } from "../../.tmp-problem-snapshot/map/landuse_sketch.js";

const first = { x: 1, y: 2 };
const second = { x: 5, y: 2 };
const third = { x: 5, y: 7 };
const fourth = { x: 1, y: 7 };
const points = [first, second, third, fourth];

assert.deepEqual(addLanduseVertex(points, { x: 2, y: 8 }), [...points, { x: 2, y: 8 }]);
assert.deepEqual(removeLastLanduseVertex(points), [first, second, third]);
assert.deepEqual(removeLanduseRingVertex(points, 1), [first, third, fourth]);
assert.throws(() => removeLanduseRingVertex(points, 4), /不存在/);
assert.throws(() => removeLanduseRingVertex([first, second, third], 1), /三个折点/);
assert.equal(landuseEditClassId("field"), 1);
assert.equal(landuseEditClassId("building"), 2);
assert.equal(landuseEditClassId("water"), 5);
assert.equal(pointInLanduseRing({ x: 3, y: 3 }, points), true);
assert.equal(pointInLanduseRing({ x: 9, y: 3 }, points), false);
