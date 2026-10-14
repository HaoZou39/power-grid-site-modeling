import assert from "node:assert/strict";
import {
  clampPanelFrame,
  clampPanelPosition,
  clampPanelResize,
  clampPanelSize,
} from "../../.tmp-problem-snapshot/map/use_draggable_panel.js";

const bounds = { width: 1000, height: 700 };

for (const workspace of [
  { width: 1920, height: 1080 },
  { width: 1752, height: 860 },
  { width: 1366, height: 768 },
]) {
  const layerPanelSize = { width: 310, height: 560 };
  const initialPosition = {
    x: workspace.width - 310 - layerPanelSize.width / 2,
    y: workspace.height - layerPanelSize.height - 72,
  };
  assert.deepEqual(
    clampPanelPosition(initialPosition, layerPanelSize, workspace, 148),
    {
      x: initialPosition.x,
      y: Math.max(initialPosition.y, 148),
    },
  );
}

assert.deepEqual(
  clampPanelPosition({ x: 120, y: 180 }, { width: 300, height: 200 }, bounds, 148),
  { x: 120, y: 180 },
);
assert.deepEqual(
  clampPanelPosition({ x: -40, y: 10 }, { width: 300, height: 200 }, bounds, 148),
  { x: 8, y: 148 },
);
assert.deepEqual(
  clampPanelPosition({ x: 900, y: 650 }, { width: 300, height: 200 }, bounds, 148),
  { x: 692, y: 492 },
);
assert.deepEqual(
  clampPanelSize({ width: 240, height: 180 }, bounds, { width: 300, height: 280 }, 148),
  { width: 300, height: 280 },
);
assert.deepEqual(
  clampPanelSize({ width: 1200, height: 900 }, bounds, { width: 420, height: 260 }, 148),
  { width: 984, height: 544 },
);
assert.deepEqual(
  clampPanelFrame(
    { x: 900, y: 650, width: 1200, height: 900 },
    bounds,
    { width: 420, height: 260 },
    148,
  ),
  { x: 8, y: 148, width: 984, height: 544 },
);
assert.deepEqual(
  clampPanelResize(
    { x: 600, y: 300, width: 680, height: 400 },
    bounds,
    { width: 420, height: 260 },
  ),
  { x: 600, y: 300, width: 392, height: 392 },
);
assert.deepEqual(
  clampPanelFrame(
    { x: 680, y: 480, width: 360, height: 540 },
    { width: 760, height: 520 },
    { width: 300, height: 280 },
    148,
  ),
  { x: 392, y: 148, width: 360, height: 364 },
);

console.log("use_draggable_panel tests passed");
