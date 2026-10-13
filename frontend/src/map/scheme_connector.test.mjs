import assert from "node:assert/strict";
import { schemeConnectorGeometry } from "../../.tmp-problem-snapshot/map/scheme_connector.js";

const workspace = { left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600, scrollLeft: 0, scrollTop: 0 };
const card = { left: 200, top: 150, right: 500, bottom: 450, width: 300, height: 300 };

const right = schemeConnectorGeometry({ x: 700, y: 300 }, card, workspace);
assert.deepEqual(right?.start, { x: 500, y: 300 });

const left = schemeConnectorGeometry({ x: 50, y: 300 }, card, workspace);
assert.deepEqual(left?.start, { x: 200, y: 300 });

const above = schemeConnectorGeometry({ x: 350, y: 50 }, card, workspace);
assert.deepEqual(above?.start, { x: 350, y: 150 });

const below = schemeConnectorGeometry({ x: 350, y: 550 }, card, workspace);
assert.deepEqual(below?.start, { x: 350, y: 450 });

const upperRight = schemeConnectorGeometry({ x: 700, y: 0 }, card, workspace);
assert.deepEqual(upperRight?.start, { x: 500, y: 206 });

assert.equal(schemeConnectorGeometry({ x: 350, y: 300 }, card, workspace), null);
assert.equal(schemeConnectorGeometry({ x: 850, y: 300 }, card, workspace), null);

const offsetWorkspace = { left: 40, top: 30, right: 840, bottom: 630, width: 800, height: 600, scrollLeft: 0, scrollTop: 0 };
const offsetCard = { left: 240, top: 180, right: 540, bottom: 480, width: 300, height: 300 };
const offset = schemeConnectorGeometry({ x: 740, y: 330 }, offsetCard, offsetWorkspace);
assert.deepEqual(offset?.start, { x: 500, y: 300 });
assert.deepEqual(offset?.target, { x: 700, y: 300 });
assert.match(offset?.path ?? "", /^M 500\.00 300\.00 Q /);

const scrolled = schemeConnectorGeometry(
  { x: 740, y: 330 },
  offsetCard,
  { ...offsetWorkspace, height: 1000, scrollTop: 120 },
);
assert.deepEqual(scrolled?.start, { x: 500, y: 420 });
assert.deepEqual(scrolled?.target, { x: 700, y: 420 });

console.log("scheme_connector tests passed");
