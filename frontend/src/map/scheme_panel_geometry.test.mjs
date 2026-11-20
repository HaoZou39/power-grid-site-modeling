import assert from "node:assert/strict";
import { findClearSchemePosition, leastCoveredSchemePosition, placeSchemeCard, placeSchemePanel } from "../../.tmp-scheme-panels/map/scheme_panel_geometry.js";

const size = { width: 360, height: 540 };
for (const anchor of [
  { left: 500, top: 300, x: 600, y: 400 },
  { left: 1100, top: 650, x: 1200, y: 750 },
  { left: 30, top: 170, x: 150, y: 280 },
]) {
  const position = placeSchemeCard(anchor, { width: 1366, height: 900 }, size);
  assert.ok(position.x >= 8 && position.x + size.width <= 1358);
  assert.ok(position.y >= 148 && position.y + size.height <= 892);
  assert.ok(position.x >= anchor.x + 12 || position.x + size.width <= anchor.left - 12
    || position.y >= anchor.y + 12 || position.y + size.height <= anchor.top - 12,
  "edge clamping must not push the card back over the selected footprint");
}

const obstacles = [
  { left: 850, right: 1030, top: 230, bottom: 680 },
  { left: 1050, right: 1200, top: 300, bottom: 700 },
  { left: 500, right: 700, top: 400, bottom: 600 },
];
const clear = findClearSchemePosition(obstacles, { width: 1366, height: 900 }, size, { x: 900, y: 200 });
assert.ok(clear, "find blank space beyond the selected scheme's four sides");
for (const box of obstacles) {
  assert.ok(clear.x + size.width <= box.left - 12 || clear.x >= box.right + 12
    || clear.y + size.height <= box.top - 12 || clear.y >= box.bottom + 12,
  "the whole card and clearance must avoid every displayed scheme");
}
assert.deepEqual(findClearSchemePosition([], { width: 1366, height: 900 }, size, clear), clear);
assert.equal(findClearSchemePosition([{ left: 0, right: 1366, top: 0, bottom: 900 }],
  { width: 1366, height: 900 }, size, { x: 10, y: 150 }), null,
"report no space instead of silently choosing partial overlap");

const denseSchemes = Array.from({ length: 702 }, (_, index) => ({
  left: 250 + (index % 27) * 22, right: 274 + (index % 27) * 22,
  top: 148 + Math.floor(index / 27) * 25, bottom: 176 + Math.floor(index / 27) * 25,
}));
const sidePanels = [{ left: 0, right: 250, top: 148, bottom: 800 },
  { left: 850, right: 1200, top: 148, bottom: 800 }];
const leastCovered = leastCoveredSchemePosition(denseSchemes, sidePanels,
  { width: 1200, height: 800 }, size, { x: 750, y: 180 });
assert.ok(leastCovered.x >= 250 && leastCovered.x + size.width <= 850,
  "when schemes fill the center, keep the detail out of both information panels");
assert.ok(leastCovered.y >= 148 && leastCovered.y + size.height <= 792);

const resultsBelow = { left: 750, right: 1200, top: 500, bottom: 800 };
const schemesAcrossMap = Array.from({ length: 702 }, (_, index) => ({
  left: 300 + (index % 18) * 25, right: 326 + (index % 18) * 25,
  top: 180 + Math.floor(index / 18) * 16, bottom: 202 + Math.floor(index / 18) * 16,
}));
const fitted = placeSchemePanel(schemesAcrossMap, [
  { left: 0, right: 300, top: 148, bottom: 800 }, resultsBelow,
], { width: 1200, height: 800 }, size, { width: 300, height: 280 },
  { left: 610, top: 350, x: 650, y: 390 });
assert.ok(fitted.width >= 300 && fitted.height >= 280 && fitted.height < 540,
  "shrink a scrolling detail card when its default size cannot fit a clear page region");
for (const box of [...schemesAcrossMap, resultsBelow, { left: 0, right: 300, top: 148, bottom: 800 }]) {
  assert.ok(fitted.x + fitted.width <= box.left - 12 || fitted.x >= box.right + 12
    || fitted.y + fitted.height <= box.top - 12 || fitted.y >= box.bottom + 12,
  "a smaller card must avoid all visible schemes and information panels");
}

const studyArea = { left: 500, right: 900, top: 148, bottom: 900 };
const rightResults = { left: 920, right: 1366, top: 300, bottom: 900 };
const outsideStudy = findClearSchemePosition([studyArea, rightResults],
  { width: 1366, height: 900 }, size, { x: 940, y: 200 });
assert.ok(outsideStudy && outsideStudy.x + size.width <= studyArea.left - 12,
  "use page space outside the study area while avoiding the right information panel");
const symmetric = placeSchemeCard({ left: 650, x: 750, top: 400, y: 500 },
  { width: 1400, height: 1000 }, { width: 200, height: 300 });
assert.ok(symmetric.x + 200 <= 638, "equal spaces must not retain a right-side preference");

let seed = 8713;
const random = (max) => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed % max; };
for (let sample = 0; sample < 80; sample++) {
  const boxes = Array.from({ length: 6 }, () => {
    const left = random(120) - 10, top = random(90) + 135;
    return { left, right: left + random(25), top, bottom: top + random(25) };
  });
  const preferred = { x: random(110), y: random(70) + 140 };
  const isClear = ({ x, y }) => boxes.every((box) => x + 20 <= box.left - 12 || x >= box.right + 12
    || y + 20 <= box.top - 12 || y >= box.bottom + 12);
  let minimum = Infinity;
  for (let x = 8; x <= 92; x++) for (let y = 148; y <= 202; y++) {
    if (isClear({ x, y })) minimum = Math.min(minimum, (x - preferred.x) ** 2 + (y - preferred.y) ** 2);
  }
  const found = findClearSchemePosition(boxes, { width: 120, height: 230 }, { width: 20, height: 20 }, preferred);
  assert.equal(found === null, minimum === Infinity, "sweep and exhaustive search must agree on whether space exists");
  if (found) {
    assert.ok(isClear(found));
    assert.equal((found.x - preferred.x) ** 2 + (found.y - preferred.y) ** 2, minimum,
      "overlapping and degenerate obstacles must still yield the nearest clear position");
  }
}
console.log("scheme panel geometry: obstacles, bounds, no-space, unbiased placement and exhaustive cross-check passed");
