import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { PARETO_LAYER_COLORS } from "../../.tmp-problem-snapshot/map/solution_diversity.js";
import { toolbarCommands } from "../../.tmp-problem-snapshot/map/toolbar_commands.js";
import {
  describeExportLayers,
  exportLegendRows,
  exportRankMarks,
  imageLooksBlank,
  paretoLayerCounts,
  pngFilename,
  selectExportPoses,
  withSceneExport,
} from "../../.tmp-problem-snapshot/map/scene_export.js";

const pool = [
  { id: "a", paretoLayer: 1, x: 1, y: 2 },
  { id: "b", paretoLayer: 2, x: 3, y: 4 },
  { id: "c", x: 5, y: 6 },
  { id: "d", paretoLayer: 9, x: 7, y: 8 },
];
const original = pool.map((pose) => ({ ...pose }));
assert.deepEqual(paretoLayerCounts(pool), { 1: 2, 2: 1, 3: 0 });
assert.deepEqual(selectExportPoses(pool, { 1: false, 2: true, 3: false }).map((pose) => pose.id), ["b"]);
assert.deepEqual(selectExportPoses(pool, { 1: true, 2: false, 3: true }).map((pose) => pose.id), ["a", "c"]);
assert.deepEqual(selectExportPoses(pool, { 1: false, 2: false, 3: false }), []);
assert.deepEqual(pool, original);

const layerTwo = selectExportPoses(pool, { 1: false, 2: true, 3: false });
assert.deepEqual(exportRankMarks(layerTwo, ["a", "b", "c"], true), [
  { id: "b", rank: 2, x: 3, y: 4 },
]);
assert.deepEqual(exportRankMarks(layerTwo, ["a", "b"], false), []);

const rows = exportLegendRows({
  layers: [
    { id: "satellite", selected: true, hasData: true },
    { id: "dem", selected: true, hasData: false },
    { id: "field", selected: false, hasData: true },
  ],
  pareto: [
    { layer: 1, selected: true, count: 2 },
    { layer: 2, selected: true, count: 0 },
    { layer: 3, selected: false, count: 4 },
  ],
});
assert.deepEqual(rows.map((row) => row.label), ["卫星影像底图", "第 1 层"]);
assert.equal(rows[1].color, PARETO_LAYER_COLORS[0]);

const choices = describeExportLayers({
  satellite: { available: true, visible: false },
  dem: { available: false, visible: true, reason: "当前场景没有 DEM 高程" },
  field: { available: true, visible: true },
});
assert.equal(choices.find((item) => item.id === "satellite").checked, true);
assert.equal(choices.find((item) => item.id === "dem").disabled, true);
assert.equal(choices.find((item) => item.id === "dem").checked, false);
assert.equal(choices.find((item) => item.id === "dem").reason, "当前场景没有 DEM 高程");
assert.equal(choices.find((item) => item.id === "field").checked, true);
assert.equal(choices.find((item) => item.id === "water").disabled, true);
assert.equal(choices.find((item) => item.id === "water").checked, false);

assert.equal(pngFilename("楠溪江选址规划-优化方案分布图", "楠溪江"), "楠溪江选址规划-优化方案分布图.png");
assert.equal(pngFilename("楠溪江选址规划-优化方案分布图.png", "楠溪江"), "楠溪江选址规划-优化方案分布图.png");
assert.equal(pngFilename("东片/方案:A*", "楠溪江"), "东片 方案 A.png");
assert.equal(pngFilename("   ", "楠溪江"), "楠溪江选址规划-优化方案分布图.png");
assert.equal(pngFilename("   ", "楠溪江", "routing"), "楠溪江选线规划-优化方案分布图.png");
assert.equal(pngFilename("方案.png.png", "楠溪江"), "方案.png");
assert.equal(pngFilename("a".repeat(90), "楠溪江").length, 84);

assert.equal(imageLooksBlank([{ r: 0, g: 0, b: 0, a: 0 }]), true);
assert.equal(imageLooksBlank([{ r: 40, g: 80, b: 30, a: 255 }]), false);

const calls = [];
const painter = {
  camera: () => ({ lng: 1, lat: 2, zoom: 3, bearing: 4, pitch: 5 }),
  jumpTo: (camera) => {
    assert.deepEqual(camera, { lng: 1, lat: 2, zoom: 3, bearing: 4, pitch: 5 });
    calls.push(["jump", camera.zoom]);
  },
  showExport: () => calls.push(["export"]),
  showWorkspace: () => calls.push(["workspace"]),
  fitSite: () => calls.push(["fit"]),
};
assert.equal(await withSceneExport(painter, "site", async () => "png"), "png");
assert.deepEqual(calls, [["export"], ["fit"], ["jump", 3], ["workspace"]]);
calls.length = 0;
await withSceneExport(painter, "view", async () => "png");
assert.deepEqual(calls, [["export"], ["jump", 3], ["workspace"]]);
calls.length = 0;
await assert.rejects(() => withSceneExport(painter, "site", async () => {
  throw new Error("瓦片没有加载");
}), /瓦片没有加载/);
assert.deepEqual(calls, [["export"], ["fit"], ["jump", 3], ["workspace"]]);

const commands = toolbarCommands({
  tool: "pan",
  notify: () => undefined,
  focusSite: () => undefined,
  setTool: () => undefined,
});
const png = commands.find((command) => command.id === "export-scene-png");
assert.equal(png.label, "导出优化场景 PNG…");
assert.equal(png.group, "文件");
assert.equal(commands.filter((command) => command.group === "文件").map((command) => command.id).at(-1), "export-scene-png");
assert.equal(toolbarCommands({
  tool: "pan",
  notify: () => undefined,
  focusSite: () => undefined,
  setTool: () => undefined,
  sceneExportDisabled: true,
}).find((command) => command.id === "export-scene-png").disabled, true);
let opened = false;
toolbarCommands({
  tool: "pan",
  notify: () => undefined,
  focusSite: () => undefined,
  setTool: () => undefined,
  sceneExportDisabled: false,
  onExportScenePng: () => { opened = true; },
}).find((command) => command.id === "export-scene-png").run();
assert.equal(opened, true);

const workspace = readFileSync(new URL("./map_workspace.tsx", import.meta.url), "utf8");
const dialog = readFileSync(new URL("./scene_export_dialog.tsx", import.meta.url), "utf8");
const worldMap = readFileSync(new URL("./world_map.tsx", import.meta.url), "utf8");
const capture = readFileSync(new URL("./scene_export_map.ts", import.meta.url), "utf8");
const exportStart = workspace.indexOf("async function exportScenePng");
const exportEnd = workspace.indexOf("async function confirmDeleteHistory", exportStart);
const exportBody = workspace.slice(exportStart, exportEnd);
assert.equal(exportBody.includes("selectExportPoses"), true);
assert.equal(exportBody.includes("diversityPool.current"), true);
assert.equal(exportBody.includes("setDiversityLevel"), false);
assert.equal(exportBody.includes("setDemVisible"), false);
assert.equal(exportBody.includes("setRoadsVisible"), false);
assert.equal(exportBody.includes("setFeasibilityVisible"), false);
assert.equal(exportBody.includes("setEdit("), false);
assert.equal(workspace.includes("sceneExportDisabled={!sceneReady || exportingScene}"), true);
assert.equal(workspace.includes("captureRef={mapCapture}"), true);
assert.equal(dialog.includes('role="dialog"'), true);
assert.equal(dialog.includes("第 {layer} 层"), true);
assert.equal(dialog.includes("显示推荐方案排名编号"), true);
assert.equal(dialog.includes("完整选址范围"), true);
assert.equal(dialog.includes("当前地图视角"), true);
assert.equal(dialog.includes("正在生成图片…"), true);
assert.equal(dialog.includes('event.key !== "Escape"'), true);
assert.equal(dialog.includes("cancelJob"), false);
assert.equal(worldMap.includes("preserveDrawingBuffer: true"), true);
assert.equal(worldMap.includes("captureLock"), true);
assert.equal(capture.includes(".toBlob("), true);
assert.equal(capture.includes("finally"), true);
assert.equal(capture.includes('map.on("idle"'), true);
assert.equal(capture.includes(", 1000)"), false);
