import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { activateSiteFrame, clampFootprintCenter, footprintCorners, footprintInsideSite, insideSite, lngLatToLocal, localToLngLat, siteFrame, siteFrameFromInfo, uprightRectangle, uprightRectangleRing } from "../../.tmp-problem-snapshot/map/site_frame.js";
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

const yongjiaFrame = siteFrameFromInfo({
  crs: "EPSG:3857",
  transform: [1.0005819327609302, 0, 13441942.292989261, 0, -1.0002501748253902, 3274576.026515471],
  width: 1800,
  height: 1800,
});
const yongjiaCenter = yongjiaFrame.localToLngLat({ x: 900, y: 900 });
assert.ok(Math.abs(yongjiaCenter.lng - 120.759112) < 0.001);
assert.ok(Math.abs(yongjiaCenter.lat - 28.195751) < 0.001);
const yongjiaRoundTrip = yongjiaFrame.lngLatToLocal(yongjiaCenter);
assert.ok(Math.abs(yongjiaRoundTrip.x - 900) < 1e-6);
assert.ok(Math.abs(yongjiaRoundTrip.y - 900) < 1e-6);
assert.throws(() => siteFrameFromInfo({ crs: "EPSG:4326", transform: [1, 0, 0, 0, -1, 0], width: 10, height: 10 }), /EPSG:3857/);

const controls = JSON.parse(readFileSync(new URL("./metric_frame_controls.json", import.meta.url)));
for (const sample of controls) {
  const frame = siteFrameFromInfo(sample.frame);
  for (const { point, lngLat } of sample.controls) {
    const actual = frame.localToLngLat(point);
    assert.ok(Math.abs(actual.lng - lngLat.lng) < 1e-8);
    assert.ok(Math.abs(actual.lat - lngLat.lat) < 1e-8);
    const back = frame.lngLatToLocal(lngLat);
    assert.ok(Math.hypot(back.x - point.x, back.y - point.y) < .01);
    const northTheta = frame.thetaFromBearing(0, point);
    const north = frame.localToLngLat({x: point.x + 10 * Math.cos(northTheta), y: point.y + 10 * Math.sin(northTheta)});
    assert.ok(north.lat > lngLat.lat);
    assert.ok(Math.abs(north.lng - lngLat.lng) < 1e-8);
    assert.ok(Math.abs(frame.widthBearing(frame.thetaFromBearing(37.5, point), point) - 37.5) < 1e-8);
  }
}

const mercatorBox = uprightRectangle(siteFrame, { x: 30, y: 40 }, { x: 10, y: 20 });
assert.deepEqual(mercatorBox, [
  { x: 10, y: 20 }, { x: 30, y: 20 }, { x: 30, y: 40 }, { x: 10, y: 40 },
]);

// Cangnan UTM grid; the study domain comes from data_tools/study_domain.py.
activateSiteFrame({
  crs: "EPSG:32651",
  transform: [1.0, 0.0, 221947.3654621762, 0.0, -1.0, 3046035.718347911],
  width: 1800,
  height: 1800,
  study_domain: {
    window: [40, 40, 1755, 1765],
    ring: [[40.107654739695136, 0.06334050977602601], [1798.9792025620118, 39.87385689467192],
      [1759.2874242660473, 1799.5565799176693], [0.1625196267850697, 1759.7615143251605]],
    side_m: 1759.3220282124885,
  },
});
const [topLeft, topRight, bottomRight, bottomLeft] = siteFrame.ring();
assert.ok(Math.abs(topLeft[1] - topRight[1]) < 1e-6 && Math.abs(bottomLeft[1] - bottomRight[1]) < 1e-6, "study edges run east-west");
assert.ok(Math.abs(topLeft[0] - bottomLeft[0]) < 1e-6 && Math.abs(topRight[0] - bottomRight[0]) < 1e-6, "study edges run north-south");
assert.equal(insideSite({ x: 5, y: 5 }), true);
assert.equal(footprintInsideSite(45, 45, 0, 80, 50), false);
const clampedStudy = clampFootprintCenter(0, 0, 0, 80, 50);
assert.equal(footprintInsideSite(clampedStudy.x, clampedStudy.y, 0, 80, 50), true);
const clampedStudyTurn = clampFootprintCenter(1800, 1800, 0.7, 80, 50);
assert.equal(footprintInsideSite(clampedStudyTurn.x, clampedStudyTurn.y, 0.7, 80, 50), true);
const studyRing = [
  [40.107654739695136, 0.06334050977602601], [1798.9792025620118, 39.87385689467192],
  [1759.2874242660473, 1799.5565799176693], [0.1625196267850697, 1759.7615143251605],
];
const upright = uprightRectangle(siteFrame, { x: 400, y: 500 }, { x: 900, y: 1100 });
const parallel = (a, b) => Math.abs(a.x * b.y - a.y * b.x) < 1e-6 * Math.hypot(a.x, a.y) * Math.hypot(b.x, b.y);
const studyTop = { x: studyRing[1][0] - studyRing[0][0], y: studyRing[1][1] - studyRing[0][1] };
const edgeU = { x: upright[1].x - upright[0].x, y: upright[1].y - upright[0].y };
const edgeV = { x: upright[3].x - upright[0].x, y: upright[3].y - upright[0].y };
assert.ok(parallel(edgeU, studyTop), "box edge follows the study domain");
// studyBox takes v exactly perpendicular to the top edge; the ring's side chord is not a perfect right angle.
assert.ok(parallel(edgeV, { x: -studyTop.y, y: studyTop.x }));
const side = { x: studyRing[3][0] - studyRing[0][0], y: studyRing[3][1] - studyRing[0][1] };
const sine = Math.abs(edgeV.x * side.y - edgeV.y * side.x) / (Math.hypot(edgeV.x, edgeV.y) * Math.hypot(side.x, side.y));
assert.ok(sine < 1e-3);
const near = (point, x, y) => Math.hypot(point.x - x, point.y - y) < 1e-6;
const firstIndex = upright.findIndex((point) => near(point, 400, 500));
const secondIndex = upright.findIndex((point) => near(point, 900, 1100));
assert.equal(Math.abs(firstIndex - secondIndex), 2);
const axisAligned = [
  { x: 400, y: 500 }, { x: 900, y: 500 }, { x: 900, y: 1100 }, { x: 400, y: 1100 },
];
assert.ok(upright.some((corner, index) => Math.hypot(corner.x - axisAligned[index].x, corner.y - axisAligned[index].y) > 1));
const assistantBox = [
  { x: 400, y: 500 }, { x: 900, y: 500 }, { x: 900, y: 1100 }, { x: 400, y: 1100 },
];
const snapped = uprightRectangleRing(siteFrame, assistantBox);
assert.ok(snapped);
assert.ok(parallel(
  { x: snapped[1].x - snapped[0].x, y: snapped[1].y - snapped[0].y },
  studyTop,
));
assert.equal(uprightRectangleRing(siteFrame, assistantBox.slice(0, 3)), null);
assert.equal(uprightRectangleRing(siteFrame, [
  { x: 400, y: 500 }, { x: 900, y: 520 }, { x: 880, y: 1100 }, { x: 420, y: 1080 },
]), null);
console.log("site_frame assertions passed");
