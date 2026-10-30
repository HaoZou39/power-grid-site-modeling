import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  SITE_VIEW_CLEARANCE_PX,
  containShift,
  paddedView,
  screenBounds,
  siteLngLatBounds,
  viewportPadding,
} from "../../.tmp-problem-snapshot/map/site_viewport.js";

const map = { left: 0, top: 0, right: 1920, bottom: 1080 };
const gap = SITE_VIEW_CLEARANCE_PX;

const fitted = viewportPadding(map, [
  { box: { left: 0, top: 0, right: 1920, bottom: 236 }, overlays: true },
  { box: { left: 18, top: 248, right: 358, bottom: 1062 }, overlays: true },
  { box: { left: 1788, top: 260, right: 1902, bottom: 420 }, overlays: true },
  { box: { left: 0, top: 0, right: 1920, bottom: 366 }, overlays: false },
]);

assert.equal(fitted.top, 236 + gap);
assert.equal(fitted.left, 358 + gap);
assert.equal(fitted.right, 1920 - 1788 + gap);
assert.equal(fitted.bottom, gap);

const zoomControl = viewportPadding(map, [
  { box: { left: 1870, top: 960, right: 1910, bottom: 1060 }, overlays: true },
]);
assert.equal(zoomControl.right, 1920 - 1870 + gap);
assert.equal(zoomControl.bottom, gap);

const tight = viewportPadding(
  { left: 0, top: 0, right: 320, bottom: 200 },
  [
    { box: { left: 0, top: 0, right: 320, bottom: 180 }, overlays: true },
    { box: { left: 0, top: 160, right: 320, bottom: 200 }, overlays: true },
  ],
);
assert.ok(tight.top + tight.bottom <= 200 - 64);
assert.ok(tight.top >= tight.bottom);

const inside = containShift(
  { left: 80, top: 40, right: 180, bottom: 140 },
  { left: 20, top: 30, right: 300, bottom: 200 },
);
assert.deepEqual(inside, { x: 0, y: 0 });

const pastRight = containShift(
  { left: 50, top: 40, right: 150, bottom: 80 },
  { left: 0, top: 0, right: 100, bottom: 100 },
);
assert.deepEqual(pastRight, { x: -50, y: 0 });

const above = containShift(
  { left: 10, top: -80, right: 40, bottom: -20 },
  { left: 0, top: 0, right: 100, bottom: 100 },
);
assert.deepEqual(above, { x: 0, y: 80 });

const zoomedIn = containShift(
  { left: 0, top: 20, right: 400, bottom: 300 },
  { left: 0, top: 0, right: 100, bottom: 100 },
);
assert.deepEqual(zoomedIn, { x: 0, y: -20 });

const corners = screenBounds([
  { x: 12, y: 40 },
  { x: 80, y: 10 },
  { x: 4, y: 90 },
]);
assert.deepEqual(corners, { left: 4, top: 10, right: 80, bottom: 90 });

const view = paddedView(1000, 800, { top: 200, right: 40, bottom: 30, left: 360 });
assert.deepEqual(view, { left: 360, top: 200, right: 960, bottom: 770 });

assert.deepEqual(siteLngLatBounds([[120.4, 27.5], [120.5, 27.4], [120.4, 27.5]]), [
  [120.4, 27.4],
  [120.5, 27.5],
]);

const worldMap = readFileSync(new URL("./world_map.tsx", import.meta.url), "utf8");
assert.match(worldMap, /measureMapPadding/);
assert.doesNotMatch(worldMap, /top:\s*160/);
