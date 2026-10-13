import assert from "node:assert/strict";
import {
  bringPanelToFront,
  floatingPanelZIndex,
} from "../../.tmp-problem-snapshot/map/floating_panel_order.js";

const opened = bringPanelToFront([], "agent");
assert.deepEqual(opened, ["agent"]);

const withGis = bringPanelToFront(opened, "gis");
assert.deepEqual(withGis, ["agent", "gis"]);
assert.ok(floatingPanelZIndex(withGis, "gis") > floatingPanelZIndex(withGis, "agent"));

const agentInFront = bringPanelToFront(withGis, "agent");
assert.deepEqual(agentInFront, ["gis", "agent"]);
assert.equal(new Set(agentInFront).size, agentInFront.length);
assert.ok(floatingPanelZIndex(agentInFront, "agent") > floatingPanelZIndex(agentInFront, "gis"));

assert.equal(bringPanelToFront(agentInFront, "agent"), agentInFront);
assert.deepEqual(bringPanelToFront(agentInFront, "compare"), ["gis", "agent", "compare"]);

console.log("floating_panel_order tests passed");
