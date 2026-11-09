import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { RoutingEdit } from "../../.tmp-routing/routing/routing_edit.js";
import { restoreRoutingPlanningConfig, serializeRoutingPlanningConfig } from "../../.tmp-routing/routing/routing_plan.js";

const defaults = JSON.parse(readFileSync(new URL("../../../config/default_config.json", import.meta.url), "utf8"));
const schema = { properties: { road_setback_m: { default: defaults.modeling.road_setback_m },
  highway_setback_m: { default: defaults.modeling.highway_setback_m }, algorithm: { default: defaults.routing } } };

const blank = serializeRoutingPlanningConfig(new RoutingEdit());
assert.equal(blank.start.lng, "");
assert.equal(blank.max_span_m, "");
assert.equal(blank.tower_radius_m, "");
assert.deepEqual(blank.no_tower_zones, []);
assert.deepEqual(blank.algorithm_overrides, {});
assert.equal(JSON.stringify(blank).includes("algorithmSchema"), false);
assert.equal(JSON.stringify(blank).includes("job_id"), false);

const prepared = new RoutingEdit().defaults(schema);
const edited = prepared
  .pilotParameter("rrt_goal_bias", 0.41)
  .toggleRrt(false)
  .connection("start", { lng: "120.123456789", lat: "" })
  .copy({ values: { ...prepared.values, max_span_m: "30.5", tower_radius_m: "", max_turn_deg: "", road_setback_m: prepared.values.road_setback_m, highway_setback_m: prepared.values.highway_setback_m },
    regions: [{ kind: "no_tower", points: [{ x: 10.25, y: 10 }, { x: 16, y: 10 }, { x: 16, y: 18.5 }] }] });
const saved = serializeRoutingPlanningConfig(edited);
assert.equal(saved.start.lng, "120.123456789");
assert.equal(saved.start.lat, "");
assert.equal(saved.max_span_m, "30.5");
assert.equal(saved.tower_radius_m, "");
assert.equal(saved.algorithm_overrides.pilot.rrt_goal_bias, 0.41);
assert.equal(saved.algorithm_overrides.pilot.enabled_mechanisms.includes("rrt"), false);
assert.equal(saved.algorithm_overrides.popsize, undefined);
assert.equal(saved.algorithm_overrides.pilot.core, undefined);
assert.equal(Object.keys(saved.algorithm_overrides).join(), "pilot");
assert.deepEqual(saved.no_tower_zones, [[[10.25, 10], [16, 10], [16, 18.5]]]);
assert.equal(JSON.stringify(saved).includes("algorithmDefaults"), false);

const restored = restoreRoutingPlanningConfig(new RoutingEdit().defaults(schema), saved);
assert.equal(restored.pilotParameters.rrt_goal_bias, 0.41);
assert.equal(restored.rrtEnabled, false);
assert.equal(restored.pilotParameters.rrt_iterations_per_span, defaults.routing.pilot.rrt_iterations_per_span);
assert.deepEqual(restored.algorithmDefaults, prepared.algorithmDefaults);
assert.equal(restored.values.max_span_m, "30.5");
assert.equal(restored.values.tower_radius_m, "");
assert.deepEqual(serializeRoutingPlanningConfig(restored), saved);
assert.throws(() => serializeRoutingPlanningConfig(edited.copy({
  regions: [{ kind: "no_tower", points: [{ x: 0, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }, { x: 1, y: 0 }] }],
})));
