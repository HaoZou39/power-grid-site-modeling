import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  BUILD_SCENE_PLUGIN,
  builtSceneId,
  elapsedSeconds,
  parseBuildSceneConfig,
  projectedExtentSummary,
  radiusKmFromSideLength,
  sceneBuildExtentLines,
  selectBuiltScene,
} from "../../.tmp-problem-snapshot/map/scene_build.js";

assert.equal(radiusKmFromSideLength(1800), 0.9);
assert.equal(
  projectedExtentSummary(1800),
  "正方形边长 1800 m，一格 1 m，网格 1800 × 1800。Web Mercator 半边长 900 m（radius_km=0.9）。真实地理范围以生成后的 GeoTIFF bounds 为准。",
);
assert.equal(projectedExtentSummary(1801), null);
assert.deepEqual(sceneBuildExtentLines(1800), {
  grid: "网格：1800 × 1800",
  resolution: "分辨率：1 m",
  mercator: "Web Mercator 半边长 900 m。真实地理范围以生成后的 GeoTIFF bounds 为准。",
});
assert.equal(sceneBuildExtentLines(1801), null);

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
const dialog = readFileSync(new URL("./scene_build_dialog.tsx", import.meta.url), "utf8");
assert.equal(BUILD_SCENE_PLUGIN, "site.build_scene");
assert.equal(workspace.includes("BUILD_SCENE_PLUGIN"), true);
assert.equal(workspace.includes("selectBuiltScene"), true);
assert.equal(workspace.includes("switchScene(next"), true);
assert.equal(workspace.includes("sceneSwitchDisabled={running || exportingScene}"), true);
assert.equal(workspace.includes('onNewScene={() => setSceneBuildOpen(true)}'), true);
assert.equal(workspace.includes("onClose={() => setSceneBuildOpen(false)}"), true);
assert.equal(workspace.includes("onSubmit={() => void submitBuild()}"), true);
assert.equal(workspace.includes("onRetry={() => void retryBuild()}"), true);
assert.equal(workspace.includes('job={job?.plugin_id === BUILD_SCENE_PLUGIN ? job : null}'), true);
assert.equal(workspace.includes("1. 场景数据"), false);
assert.equal(workspace.includes('className="scene-build"'), false);
assert.equal(workspace.includes("选址优化"), true);
assert.equal(workspace.includes("道路最小退距（m）"), true);
assert.equal(workspace.includes("方案多样性"), true);
assert.equal(dialog.includes('role="dialog"'), true);
assert.equal(dialog.includes('aria-labelledby="scene-build-title"'), true);
assert.equal(dialog.includes("新建场景"), true);
assert.equal(dialog.includes("通过地理坐标生成站址基础数据"), true);
assert.equal(dialog.includes('event.key !== "Escape"'), true);
assert.equal(dialog.includes("onCloseRef.current()"), true);
assert.equal(dialog.includes("onClick={onClose}"), true);
assert.equal(dialog.includes("cancelJob"), false);
assert.equal(dialog.includes("stopPrepare"), false);
assert.equal(dialog.includes("构建场景"), true);
assert.equal(dialog.includes("终止构建"), true);
assert.equal(dialog.includes("重试"), true);
