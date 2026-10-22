import assert from "node:assert/strict";
import { adaptSolutions } from "../../.tmp-problem-snapshot/solution_record.js";
import { solutionLayers, mergeDisplayedChoices, PARETO_LAYER_COLORS } from "../../.tmp-problem-snapshot/map/solution_diversity.js";
import { GuidedDecisionRun } from "../../.tmp-problem-snapshot/map/decision_run.js";
import { BuildingFootprint } from "../../.tmp-problem-snapshot/map/building_footprint.js";

const csv = [
  "run_id,x,y,theta,dem_soft,offroad_haul_m,haul_rise_m,demand_distance,road_haul_m,is_feasible",
  "first,100,100,0,0,0,0,0,0,True",
  "second,200,200,0,1,1,1,100,100,True",
  "equal,250,250,0,1,1,1,100,100,True",
  "third,300,300,0,1.00001,1,1,1,1,True",
  "fourth,400,400,0,3,3,3,200,200,True",
  "blocked,500,500,0,-1,-1,-1,-1,-1,False",
].join("\n");
const pareto = "run_id\nfirst";
const records = adaptSolutions(csv, pareto);
const layers = solutionLayers(records, { include_demand: false });
assert.deepEqual([...layers], [["first", 1], ["second", 2], ["equal", 2], ["third", 3]]);
assert.equal(solutionLayers(records, { include_demand: true }).get("third"), 2);
assert.equal(solutionLayers(records, { origin_x: 0, origin_y: 0 }).get("third"), 2);
assert.equal(solutionLayers([], {}).size, 0);
assert.equal(solutionLayers(records.slice(0, 1), {}).size, 1);
assert.throws(() => solutionLayers([{ ...records[1], demSoft: "" }], {}));
assert.throws(() => solutionLayers([{ ...records[1], demSoft: "Infinity" }], {}));

function catalog(withForm) {
  return {
    async getExperiments() { return [{ id: "run", artifacts: [
      { name: "solutions.csv", kind: "table", url: "solutions" },
      { name: "pareto_solutions.csv", kind: "table", url: "pareto" },
      ...(withForm ? [{ name: "site_form_snapshot.json", kind: "json", url: "form" }] : []),
    ] }]; },
    async fetchArtifactText(url) { return { solutions: csv, pareto, form: "{\"include_demand\":false}" }[url]; },
  };
}
const choices = await new GuidedDecisionRun(catalog(true)).loadPareto("run", true);
assert.deepEqual(choices.map((item) => item.paretoLayer), [1, 2, 2, 3]);
assert.equal((await new GuidedDecisionRun(catalog(true)).loadPareto("run")).length, 1);
assert.equal((await new GuidedDecisionRun(catalog(false)).loadPareto("run", true)).length, 1);
assert.deepEqual([1, 2, 3].map((level) => choices.filter((item) => item.paretoLayer <= level).length), [1, 3, 4]);

let pool = mergeDisplayedChoices(choices, [{ ...choices[1], theta: 0.75 }]);
pool = mergeDisplayedChoices(pool, pool.filter((item) => item.paretoLayer === 1));
assert.equal(pool.find((item) => item.id === "second").theta, 0.75);
const features = BuildingFootprint.layer(choices, { widthM: 77, heightM: 51.5 }, 0).map((item) => item.toFeature((point) => [point.x, point.y]));
assert.deepEqual(features.map((item) => item.properties.pareto_layer), [1, 2, 2, 3]);
assert.equal(new Set(PARETO_LAYER_COLORS).size, 3);
console.log("solution diversity tests passed");
