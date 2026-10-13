import assert from "node:assert/strict";
import { clampFootprintCenter, footprintCorners, footprintInsideSite, insideSite, lngLatToLocal, localToLngLat, siteFrame } from "../../.tmp-problem-snapshot/map/site_frame.js";
import { placeDescription } from "../../.tmp-problem-snapshot/map/decision_run.js";

for (const point of [
  { x: 0, y: 0 },
  { x: 100.5, y: 240.25 },
  { x: 900, y: 900 },
  { x: siteFrame.widthM, y: siteFrame.heightM },
]) {
  const roundTrip = lngLatToLocal(localToLngLat(point));
  assert.ok(Math.abs(roundTrip.x - point.x) < 1, `x ${point.x} -> ${roundTrip.x}`);
  assert.ok(Math.abs(roundTrip.y - point.y) < 1, `y ${point.y} -> ${roundTrip.y}`);
}

assert.equal(insideSite({ x: 10, y: 10 }), true);
assert.equal(insideSite({ x: -1, y: 10 }), false);
assert.equal(insideSite({ x: siteFrame.widthM + 1, y: 10 }), false);

const northwest = localToLngLat({ x: 0, y: 0 });
assert.ok(northwest.lng > 120 && northwest.lng < 121);
assert.ok(northwest.lat > 27 && northwest.lat < 28);

const described = placeDescription({ x: 100.5, y: 240.25 });
const describedBack = lngLatToLocal({ lng: Number(described.lng), lat: Number(described.lat) });
assert.ok(Math.abs(describedBack.x - 100.5) < 1);
assert.ok(Math.abs(describedBack.y - 240.25) < 1);

const corners = footprintCorners(1105.628662109375, 1000.3971557617188, 1.0063979625701904, 80, 50);
const expected = [
  [1105.3551230538774, 953.2280432368353],
  [1148.1477298077466, 1020.8208890654339],
  [1105.9022011648726, 1047.5662682866023],
  [1063.1095944110034, 979.9734224580036],
];
corners.forEach((corner, index) => {
  assert.ok(Math.abs(corner.x - expected[index][0]) < 1e-6, `corner x ${corner.x}`);
  assert.ok(Math.abs(corner.y - expected[index][1]) < 1e-6, `corner y ${corner.y}`);
});

const clampedAxisAligned = clampFootprintCenter(-10, 1820, 0, 80, 50);
assert.deepEqual(clampedAxisAligned, { x: 40, y: 1775 });
assert.equal(footprintInsideSite(clampedAxisAligned.x, clampedAxisAligned.y, 0, 80, 50), true);

const quarterTurn = Math.PI / 2;
const clampedQuarterTurn = clampFootprintCenter(-10, -10, quarterTurn, 80, 50);
assert.ok(Math.abs(clampedQuarterTurn.x - 25) < 1e-9);
assert.ok(Math.abs(clampedQuarterTurn.y - 40) < 1e-9);
assert.equal(footprintInsideSite(clampedQuarterTurn.x, clampedQuarterTurn.y, quarterTurn, 80, 50), true);

const diagonal = Math.PI / 4;
const clampedDiagonal = clampFootprintCenter(0, 0, diagonal, 80, 50);
assert.equal(footprintInsideSite(clampedDiagonal.x, clampedDiagonal.y, diagonal, 80, 50), true);
assert.ok(footprintCorners(clampedDiagonal.x, clampedDiagonal.y, diagonal, 80, 50).every((point) => (
  point.x >= -1e-9 && point.y >= -1e-9
  && point.x <= siteFrame.widthM + 1e-9 && point.y <= siteFrame.heightM + 1e-9
)));
assert.equal(footprintInsideSite(10, 10, diagonal, 80, 50), false);

console.log("site_frame assertions passed");
