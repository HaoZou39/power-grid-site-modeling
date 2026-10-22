import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  BUILD_SCENE_PLUGIN,
  builtSceneId,
  elapsedSeconds,
  parseBuildSceneConfig,
  projectedExtentSummary,
  radiusKmFromSideLength,
  selectBuiltScene,
} from "../../.tmp-problem-snapshot/map/scene_build.js";

assert.equal(radiusKmFromSideLength(1800), 0.9);
assert.equal(
  projectedExtentSummary(1800),
  "正方形边长 1800 m，一格 1 m，网格 1800 × 1800。Web Mercator 半边长 900 m（radius_km=0.9）。真实地理范围以生成后的 GeoTIFF bounds 为准。",
);
assert.equal(projectedExtentSummary(1801), null);

const parsed = parseBuildSceneConfig({
  lat: "27.501662",
  lon: "120.194639",
  sideLengthM: "1800",
  siteName: "苍南东片",
});
assert.equal(parsed.ok, true);
if (parsed.ok) {
  assert.equal(parsed.config.side_length_m, 1800);
  assert.equal(parsed.config.site_name, "苍南东片");
}
assert.equal(parseBuildSceneConfig({
  lat: "91",
  lon: "0",
  sideLengthM: "1800",
  siteName: "",
}).ok, false);
assert.equal(parseBuildSceneConfig({
  lat: "",
  lon: "120.194639",
  sideLengthM: "1800",
  siteName: "",
}).ok, false);
assert.equal(parseBuildSceneConfig({
  lat: "27.5",
  lon: "120.1",
  sideLengthM: "1801",
  siteName: "",
}).ok, false);

const scenes = [
  { id: "cangnan", title: "苍南" },
  { id: "lat27.501662_lon120.194639_r0.900km_z18_g1800x1800_rb500m", title: "东片" },
];
const builtId = scenes[1].id;
assert.equal(selectBuiltScene(scenes, builtId)?.id, builtId);
assert.equal(selectBuiltScene(scenes, builtId)?.id === "cangnan", false);
assert.equal(selectBuiltScene(scenes, "missing"), null);
assert.equal(builtSceneId({ data: { scene_id: builtId } }), builtId);
assert.equal(elapsedSeconds("2026-10-22T00:00:00Z", "2026-10-22T00:00:12Z"), 12);

const workspace = readFileSync(new URL("./map_workspace.tsx", import.meta.url), "utf8");
assert.equal(BUILD_SCENE_PLUGIN, "site.build_scene");
assert.equal(workspace.includes("BUILD_SCENE_PLUGIN"), true);
assert.equal(workspace.includes("selectBuiltScene"), true);
assert.equal(workspace.includes("构建场景"), true);
assert.equal(workspace.includes("sceneSwitchDisabled={running}"), true);
