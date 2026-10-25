import assert from "node:assert/strict";
import { evaluateFavorite, favoriteEvaluationRequests } from "../../.tmp-problem-snapshot/map/favorite_evaluation.js";
import { favoritePoseSnapshot } from "../../.tmp-problem-snapshot/map/favorite_points.js";
import { SiteFrame } from "../../.tmp-problem-snapshot/map/site_frame.js";
import { SiteEdit } from "../../.tmp-problem-snapshot/map/site_edit.js";

const frame = new SiteFrame(13379105, 3187189, 1, -1, 600, 600);
const favorite = { ...favoritePoseSnapshot({ x: 400, y: 400 }, 0.73, 65, 42, frame), id: "f", scene_id: "cangnan", created_at: "", updated_at: "" };
const config = new SiteEdit("cangnan", 77, 51.5).withRoadSetback(8).withWaterSetback(12)
  .withPolicies("blocked", "costly", 0.3).withIncludeDemand(true)
  .addRegion("feasible", [{ x: 1, y: 1 }, { x: 10, y: 1 }, { x: 10, y: 10 }]).searchConfig();
config.origin_x = 50;
config.origin_y = 70;
const requests = favoriteEvaluationRequests(favorite, frame, config);
for (const key of ["mountain_policy", "field_policy", "field_cost", "exclusion_zones", "feasible_zones", "origin_x", "origin_y", "road_setback_m", "water_setback_m", "diagonal_access"]) {
  assert.deepEqual(requests.objectives[key], config[key], key);
  assert.deepEqual(requests.report[key], config[key], key);
}
assert.equal(requests.objectives.rect_w_m, 65);
assert.equal(requests.report.rect_h_m, 42);
assert.equal(requests.objectives.include_demand, true);
assert.equal("include_demand" in requests.report, false);
assert.equal("scene_name" in requests.objectives, false);
assert.ok(Math.abs(requests.objectives.poses[0].x - 400) < 1e-6);
assert.ok(Math.abs(requests.objectives.poses[0].theta - 0.73) < 1e-12);

const metrics = { dem_soft: 3, obstacle_hard_count: 12, is_feasible: false };
const published = [];
await evaluateFavorite("cangnan", requests, new AbortController().signal, (result) => published.push(result), {
  async objectives(scene, body) {
    assert.equal(scene, "cangnan");
    assert.deepEqual(body, requests.objectives);
    return { items: [metrics] };
  },
  async report(scene, body) {
    assert.equal(published.length, 1, "objectives must appear before the report begins");
    assert.deepEqual(body, requests.report);
    throw new Error("no access path");
  },
});
assert.deepEqual(published[0], { objectives: metrics });
assert.deepEqual(published[1], { objectives: metrics, reportError: "no access path" });

const obsolete = new AbortController();
const stale = [];
await evaluateFavorite("cangnan", requests, obsolete.signal, (result) => stale.push(result), {
  async objectives() { obsolete.abort(); return { items: [metrics] }; },
  async report() { assert.fail("an obsolete evaluation must not request a report"); },
});
assert.deepEqual(stale, []);
await evaluateFavorite("cangnan", requests, new AbortController().signal, (result) => stale.push(result), {
  async objectives() { return { items: [] }; },
  async report() { assert.fail("empty objectives must not request a report"); },
});
assert.match(stale[0].error, /未返回一个站址/);

const cancelledReport = new AbortController();
const phases = [];
await evaluateFavorite("cangnan", requests, cancelledReport.signal, (result) => phases.push(result), {
  async objectives() { return { items: [metrics] }; },
  async report() { cancelledReport.abort(); return { haul_path: [] }; },
});
assert.deepEqual(phases, [{ objectives: metrics }]);
console.log("favorite evaluation: shared constraints, own dimensions, phased output and obsolete responses passed");
