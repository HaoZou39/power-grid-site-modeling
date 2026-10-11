import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  EXPERIMENT_SOURCE_LABEL,
  HARD_FEASIBILITY_RULE,
  NOT_PROVIDED,
  OBJECTIVE_ORDER,
  adaptProblemSnapshot,
  emptyExperimentOverview,
  selectProblemArtifacts,
} from "../.tmp-problem-snapshot/problem_snapshot.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const metadata = JSON.parse(readFileSync(join(root, "outputs/cmaes_region_0.1/data_metadata.json"), "utf8"));
const config = JSON.parse(readFileSync(join(root, "outputs/cmaes_region_0.1/resolved_config.json"), "utf8"));
const mapUrl = "/api/v1/experiments/cmaes_region_0.1/artifacts/site.png";

const complete = adaptProblemSnapshot({
  experimentName: "cmaes_region_0.1",
  dataMetadata: metadata,
  resolvedConfig: config,
  mapImageUrl: mapUrl,
});
assert.equal(complete.sourceLabel, EXPERIMENT_SOURCE_LABEL);
assert.equal(complete.experimentName, "cmaes_region_0.1");
assert.equal(complete.gridWidth, "1800");
assert.equal(complete.gridHeight, "1800");
assert.equal(complete.resolutionM, "1 m");
assert.equal(complete.coordinateConvention, "原点 左上角，x 向右，y 向下，单位 米");
assert.equal(complete.layers.dem, true);
assert.equal(complete.layers.obstacle, true);
assert.equal(complete.layers.roads, true);
assert.equal(complete.layers.demandPoints, true);
assert.equal(complete.dataSource, metadata.dem.source_path);
assert.equal(complete.seed, "42");
assert.equal(complete.rectWidthM, "80 m");
assert.equal(complete.rectHeightM, "50 m");
assert.deepEqual(complete.objectiveOrder, OBJECTIVE_ORDER);
assert.equal(complete.hardFeasibility, HARD_FEASIBILITY_RULE);
assert.equal(complete.mapImageUrl, mapUrl);
assert.deepEqual(complete.missing, []);

const missingLayers = adaptProblemSnapshot({
  experimentName: "partial",
  dataMetadata: {
    dem: {
      shape: [10, 20],
      target_resolution_m: 1,
      source_path: "data/dem.tif",
      local_coord_convention: { origin: "upper_left", x_positive: "right", y_positive: "down", unit: "meter" },
    },
  },
  resolvedConfig: { modeling: {} },
  mapImageUrl: null,
});
assert.equal(missingLayers.layers.dem, true);
assert.equal(missingLayers.layers.obstacle, false);
assert.equal(missingLayers.layers.roads, false);
assert.equal(missingLayers.layers.demandPoints, false);
assert.equal(missingLayers.gridWidth, "20");
assert.equal(missingLayers.gridHeight, "10");
assert.equal(missingLayers.seed, NOT_PROVIDED);
assert.equal(missingLayers.rectWidthM, NOT_PROVIDED);
assert.equal(missingLayers.rectHeightM, NOT_PROVIDED);
assert.equal(missingLayers.mapImageUrl, null);
assert.deepEqual(missingLayers.missing, ["不可建设区域", "道路", "需求点", "建筑矩形宽度", "建筑矩形高度", "地图 PNG"]);

const empty = emptyExperimentOverview();
assert.deepEqual(empty.missing, ["实验目录", "data_metadata.json", "resolved_config.json", "地图 PNG"]);
assert.match(empty.nextAction, /data_metadata\.json/);

const selected = selectProblemArtifacts([
  { name: "notes.json", kind: "json", url: "/api/v1/experiments/demo/artifacts/notes.json" },
  { name: "data_metadata.json", kind: "json", url: "/api/v1/experiments/demo/artifacts/data_metadata.json" },
  { name: "resolved_config.json", kind: "json", url: "/api/v1/experiments/demo/artifacts/resolved_config.json" },
  { name: "site.png", kind: "image", url: "/api/v1/experiments/demo/artifacts/site.png" },
]);
assert.equal(selected.metadataUrl, "/api/v1/experiments/demo/artifacts/data_metadata.json");
assert.equal(selected.configUrl, "/api/v1/experiments/demo/artifacts/resolved_config.json");
assert.equal(selected.mapImageUrl, "/api/v1/experiments/demo/artifacts/site.png");
assert.deepEqual(selectProblemArtifacts([{ name: "map.png", kind: "json", url: "/guessed/map.png" }]), {
  metadataUrl: null,
  configUrl: null,
  mapImageUrl: null,
});

console.log("problem_snapshot assertions passed");
