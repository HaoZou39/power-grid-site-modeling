import assert from "node:assert/strict";
import { SiteFrame, siteFrameFromInfo } from "../../.tmp-problem-snapshot/map/site_frame.js";
import { coordinatePosition, originCoordinatePosition } from "../../.tmp-problem-snapshot/map/pose_coordinates.js";

const frame = new SiteFrame(0, 0, 1, -1, 1000, 1000);
const target = frame.localToLngLat({ x: 500, y: 450 });
const point = coordinatePosition(String(target.lng), String(target.lat), frame, Math.PI / 4, 100, 50);
assert.ok(Math.abs(point.x - 500) < 1e-6);
assert.ok(Math.abs(point.y - 450) < 1e-6);
for (const [lng, lat] of [["", "0"], ["NaN", "0"], ["181", "0"], ["0", "91"]]) {
  assert.throws(() => coordinatePosition(lng, lat, frame, 0, 100, 50), /有效的经纬度/);
}
const nearEdge = frame.localToLngLat({ x: 20, y: 500 });
assert.throws(() => coordinatePosition(String(nearEdge.lng), String(nearEdge.lat), frame, 0, 100, 50), /超出选址范围/);
const outside = frame.localToLngLat({ x: 1100, y: 500 });
assert.throws(() => coordinatePosition(String(outside.lng), String(outside.lat), frame, 0, 100, 50), /超出选址范围/);
assert.throws(() => originCoordinatePosition(String(outside.lng), String(outside.lat), frame), /超出当前场景范围/);
const cangnan = siteFrameFromInfo({
  crs: "EPSG:32651", transform: [1, 0, 221947.3654621762, 0, -1, 3046035.718347911], width: 1800, height: 1800,
  study_domain: { window: [40, 40, 1755, 1765], ring: [
    [40.107654739695136, 0.06334050977602601], [1798.9792025620118, 39.87385689467192],
    [1759.2874242660473, 1799.5565799176693], [0.1625196267850697, 1759.7615143251605],
  ], side_m: 1759.3220282124885 },
});
for (const candidate of [{ x: 10, y: 10 }, { x: 1790, y: 1000 }, { x: 900, y: 1801 }]) {
  const ll = cangnan.localToLngLat(candidate);
  assert.throws(() => coordinatePosition(String(ll.lng), String(ll.lat), cangnan, 0.4, 100, 50), /超出选址范围/);
}
const cangnanCenter = cangnan.localToLngLat({ x: 900, y: 900 });
assert.ok(Math.abs(coordinatePosition(String(cangnanCenter.lng), String(cangnanCenter.lat), cangnan, 0.4, 100, 50).x - 900) < 1e-6);
const cangnanGridCorner = cangnan.localToLngLat({ x: 5, y: 5 });
assert.ok(Math.abs(originCoordinatePosition(String(cangnanGridCorner.lng), String(cangnanGridCorner.lat), cangnan).x - 5) < 1e-6);
assert.throws(() => originCoordinatePosition("", String(cangnanGridCorner.lat), cangnan), /有效的经纬度/);
// A no-op confirmation must preserve exact local coordinates, including grid edges.
for (const current of [{ x: 0, y: 0 }, { x: 1800, y: 1800 }, { x: 900.123456789, y: 900.987654321 }]) {
  const ll = cangnan.localToLngLat(current);
  assert.deepEqual(originCoordinatePosition(String(ll.lng), String(ll.lat), cangnan, current), current);
}
const current = { x: 900.123456789, y: 900.987654321 };
const unchanged = cangnan.localToLngLat(current);
assert.deepEqual(coordinatePosition(String(unchanged.lng), String(unchanged.lat), cangnan, 0.4, 100, 50, current), current);
console.log("pose coordinates tests passed");
