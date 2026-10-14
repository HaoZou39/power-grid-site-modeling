import assert from "node:assert/strict";
import { exportSolutionsCsv, exportSolutionsJson } from "../../.tmp-problem-snapshot/map/solution_export.js";

const choice = {
  id: 'run,"1"',
  x: 12.5,
  y: 23.25,
  theta: 0,
  demSoft: "0.25",
  roadDistance: "18",
  demandDistance: "重算中",
  roadHaul: "未提供",
  offroadHaul: "3.5",
  haulRise: "0",
  obstacleHardCount: "0",
  feasible: "可行",
  original: { x: 12.5, y: 23.25, theta: 0 },
  baseline: {
    demSoft: "0.25",
    roadDistance: "18",
    demandDistance: "重算中",
    roadHaul: "未提供",
    offroadHaul: "3.5",
    haulRise: "0",
    obstacleHardCount: "0",
    feasible: "可行",
  },
  derivedFrom: "experiment-a",
};
const other = { ...choice, id: "run-2", x: 30, derivedFrom: undefined };

const csv = exportSolutionsCsv([choice, other]);
assert.equal(csv.startsWith("\uFEFFsolution_id,x_m,y_m,theta_rad,azimuth_deg,"), true);
assert.equal(csv.includes('"run,""1""",12.5,23.25,0,90,0.25,18,,'), true);
assert.equal(csv.includes(",true,experiment-a\r\n"), true);
assert.equal(csv.endsWith("run-2,30,23.25,0,90,0.25,18,,,3.5,0,0,true,\r\n"), true);
assert.equal(csv.split("\r\n").length, 4);

const json = JSON.parse(exportSolutionsJson("cangnan", 77, 51.5, [choice, other], "2026-10-14T00:00:00.000Z"));
assert.equal(json.scene_id, "cangnan");
assert.equal(json.exported_at, "2026-10-14T00:00:00.000Z");
assert.equal(json.solution_count, 2);
assert.deepEqual(json.building_size_m, { length: 77, width: 51.5 });
assert.equal(json.solutions[0].solution_id, 'run,"1"');
assert.equal(json.solutions[0].azimuth_deg, 90);
assert.equal(json.solutions[0].demand_distance_m, null);
assert.equal(json.solutions[0].is_feasible, true);
assert.equal(json.solutions[0].derived_from, "experiment-a");
assert.equal("derived_from" in json.solutions[1], false);

console.log("solution_export assertions passed");
