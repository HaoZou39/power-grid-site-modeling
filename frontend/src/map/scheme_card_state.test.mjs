import assert from "node:assert/strict";
import {
  isSchemeCardVisible,
  schemeCardShouldOpen,
} from "../../.tmp-problem-snapshot/map/scheme_card_state.js";

assert.equal(schemeCardShouldOpen("automatic", true), false);
assert.equal(schemeCardShouldOpen("automatic", false), false);
assert.equal(schemeCardShouldOpen("user", true), true);
assert.equal(schemeCardShouldOpen("user", false), false);

assert.equal(isSchemeCardVisible("pose-1", true), true);
assert.equal(isSchemeCardVisible("pose-1", false), false);
assert.equal(isSchemeCardVisible(null, true), false);

console.log("scheme_card_state tests passed");
