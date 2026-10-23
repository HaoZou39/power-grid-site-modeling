import assert from "node:assert/strict";
import { exportSolutionsCsv, exportSolutionsJson } from "../../.tmp-problem-snapshot/map/solution_export.js";
import { localToLngLat } from "../../.tmp-problem-snapshot/map/site_frame.js";

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
const infeasible = { ...choice, id: "run-3", feasible: "不可行" };

const csv = exportSolutionsCsv([choice, other, infeasible]);
const coordinates = localToLngLat({ x: choice.x, y: choice.y });
const longitude = coordinates.lng.toFixed(6);
const latitude = coordinates.lat.toFixed(6);
assert.equal(csv.startsWith("\uFEFF方案编号,经度（CGCS2000，度）,纬度（CGCS2000，度）,方位角（宽边，度）,地形平整度,"), true);
assert.equal(csv.includes('"run,""1""",' + longitude + "," + latitude + ",90,0.25,18,,"), true);
assert.equal(csv.includes("run-2," + localToLngLat({ x: 30, y: 23.25 }).lng.toFixed(6) + "," + latitude + ",90,0.25,18,,,3.5,0,0,可行\r\n"), true);
assert.equal(csv.endsWith("run-3," + longitude + "," + latitude + ",90,0.25,18,,,3.5,0,0,不可行\r\n"), true);
assert.equal(csv.includes("theta_rad"), false);
assert.equal(csv.includes("derived_from"), false);
assert.equal(csv.includes("experiment-a"), false);
assert.equal(csv.includes("longitude_deg"), false);
assert.equal(csv.split("\r\n").length, 5);

const json = JSON.parse(exportSolutionsJson("cangnan", 77, 51.5, [choice, other], "2026-10-14T00:00:00.000Z"));
assert.equal(json.scene_id, "cangnan");
assert.equal(json.exported_at, "2026-10-14T00:00:00.000Z");
assert.equal(json.solution_count, 2);
assert.deepEqual(json.building_size_m, { length: 77, width: 51.5 });
assert.equal(json.geographic_crs.startsWith("EPSG:4490 CGCS2000"), true);
assert.equal(json.solutions[0].longitude_deg, Number(longitude));
assert.equal(json.solutions[0].latitude_deg, Number(latitude));
assert.equal(json.solutions[0].solution_id, 'run,"1"');
assert.equal(json.solutions[0].azimuth_deg, 90);
assert.equal(json.solutions[0].demand_distance_m, null);
assert.equal(json.solutions[0].is_feasible, true);
assert.equal(json.solutions[0].derived_from, "experiment-a");
assert.equal("derived_from" in json.solutions[1], false);

console.log("solution_export assertions passed");
