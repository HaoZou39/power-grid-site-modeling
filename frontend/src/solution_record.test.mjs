import assert from "node:assert/strict";
import {
  adaptSolutions,
  comparisonPoints,
  experimentListStats,
  resultSummary,
  selectResultArtifacts,
  sortSolutions,
  toggleCompared,
} from "../.tmp-problem-snapshot/solution_record.js";

const header = "run_id,x,y,theta,dem_soft,road_distance,demand_distance,is_feasible";
const firstRow = "0,1105.628662109375,1000.3971557617188,1.0063979625701904,2,3,4,True";
const solutionsCsv = `${header}\n${firstRow}\n1,200,300,0,5,6,7,True\n2,400,500,0,8,9,10,False\n`;
const paretoCsv = `${header}\n${firstRow}\n`;
const summary = { n_solutions: 3, n_feasible: 2, n_pareto: 1 };

const records = adaptSolutions(solutionsCsv, paretoCsv);
assert.equal(records.length, 3);
assert.equal(records[0].id, "0");
assert.equal(records[0].isFeasible, true);
assert.equal(records[0].isPareto, true);
assert.equal(records[0].x.startsWith("1105.628662109375"), true);
assert.equal(records.filter((item) => item.isPareto).length, 1);
assert.equal(comparisonPoints(records).length, 3);
assert.equal(records.some((item) => item.isPareto === false), true);

const withoutParetoFile = adaptSolutions("run_id,x,is_feasible\n7,1.5,True\n", null);
assert.equal(withoutParetoFile[0].y, "未提供");
assert.equal(withoutParetoFile[0].demSoft, "未提供");
assert.equal(withoutParetoFile[0].isFeasible, true);
assert.equal(withoutParetoFile[0].isPareto, null);
assert.equal(withoutParetoFile[0].obstacleHardCount, "未提供");
assert.equal(comparisonPoints(withoutParetoFile).length, 0);

const counts = resultSummary(summary, records);
assert.equal(counts.total, "3");
assert.equal(counts.feasible, "2");
assert.equal(counts.pareto, "1");
assert.equal(counts.hasFeasible, "是");
assert.equal(experimentListStats(summary).finishedAt, "未提供");

const maps = selectResultArtifacts([
  { name: "notes.json", kind: "json", url: "/notes" },
  { name: "other.png", kind: "image", url: "/other" },
  { name: "pareto_points_map.png", kind: "image", url: "/points" },
  { name: "pareto_footprints_map.png", kind: "image", url: "/foot" },
  { name: "pareto_3d_interactive.html", kind: "html", url: "/html" },
  { name: "solutions.csv", kind: "table", url: "/solutions" },
]);
assert.deepEqual(maps.maps.map((item) => item.url), ["/foot", "/points", "/other"]);
assert.equal(maps.paretoHtml.url, "/html");
assert.equal(maps.solutionsUrl, "/solutions");
assert.equal(maps.paretoSolutionsUrl, null);

const sorted = sortSolutions([
  { ...withoutParetoFile[0], key: "a", isFeasible: false, sort: { ...withoutParetoFile[0].sort, feasible: 0 } },
  { ...withoutParetoFile[0], key: "b", id: "8", isFeasible: true, sort: { ...withoutParetoFile[0].sort, feasible: 1 } },
], "feasible", "desc");
assert.deepEqual(sorted.map((item) => item.key), ["b", "a"]);

assert.deepEqual(toggleCompared([], "a").keys, ["a"]);
assert.deepEqual(toggleCompared(["a", "b", "c"], "d"), { keys: ["a", "b", "c"], rejected: true });
assert.deepEqual(toggleCompared(["a", "b"], "a").keys, ["b"]);

console.log("solution_record assertions passed");
