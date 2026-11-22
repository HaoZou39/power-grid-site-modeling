import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { BuildingFootprint } from "../src/map/building_footprint.js";
import { siteFrameFromInfo } from "../src/map/site_frame.js";
import { addSiteLayers, syncSiteOverlay } from "../src/map/site_overlay.js";
import { siteCompareColor } from "../src/map/site_compare.js";

const frame = siteFrameFromInfo({ crs: "EPSG:3857", transform: [1, 0, 0, 0, -1, 600], width: 900, height: 600 });
const choices = [5, 91, 15].map((number, index) => ({ id: `site-${number}`, x: 150 + index * 300, y: 300, theta: 0 }));
const ids = choices.map((item) => item.id);
const map = new maplibregl.Map({ container: "map", center: frame.localToLngLat({ x: 450, y: 300 }), zoom: 16,
  style: { version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": "#142834" } }] },
  canvasContextAttributes: { preserveDrawingBuffer: true }, attributionControl: false });
document.getElementById("legend")!.innerHTML = choices.map((item, index) => `<span style="display:inline-block;padding:15px;color:${siteCompareColor(index)}">方案 ${[5, 91, 15][index]}</span>`).join("");
document.body.style.cssText = "background:#142834;color:white;font:20px sans-serif";

function check(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
async function painted() {
  await new Promise<void>((resolve) => { map.once("idle", () => resolve()); map.triggerRepaint(); });
}
function sync(compared: string[], retained: Set<string> | null = null) {
  syncSiteOverlay(map, { zones: [], draft: [], origin: null, haulPath: [],
    footprints: BuildingFootprint.layer(choices, { widthM: 100, heightM: 90 }, 2, [], retained, compared) }, frame);
}
function pixel(index: number) {
  const point = map.project(frame.localToLngLat(choices[index]));
  const canvas = map.getCanvas();
  const gl = canvas.getContext("webgl2")!;
  const values = new Uint8Array(4);
  const scale = canvas.width / canvas.clientWidth;
  gl.readPixels(Math.round(point.x * scale), canvas.height - 1 - Math.round(point.y * scale), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, values);
  return [...values];
}
function checkColors(stage: string) {
  const [cyan, pink, yellow] = choices.map((_, index) => pixel(index));
  check(cyan[1] > cyan[0] + 40 && cyan[2] > cyan[0] + 40, `${stage}: first scheme is not cyan: ${cyan}`);
  check(pink[0] > pink[1] + 30 && pink[0] > pink[2] + 30, `${stage}: second scheme is not pink: ${pink}`);
  check(yellow[0] > yellow[2] + 40 && yellow[1] > yellow[2] + 30, `${stage}: selected third scheme is not yellow: ${yellow}`);
}
async function run() {
  await new Promise<void>((resolve) => map.once("load", () => resolve()));
  addSiteLayers(map, frame);
  sync(ids); await painted(); checkColors("Fresh map");
  // An existing map can retain the old paints across a frontend module refresh.
  map.setPaintProperty("footprint-fill", "fill-color", "#d7fff8");
  map.setPaintProperty("footprint-line", "line-color", "#7dfff1");
  map.setLayoutProperty("footprint-fill", "fill-sort-key", null);
  map.setLayoutProperty("footprint-line", "line-sort-key", null);
  sync(ids); await painted(); checkColors("Existing map with old paints");
  const originalPaintSetter = map.setPaintProperty.bind(map);
  const originalLayoutSetter = map.setLayoutProperty.bind(map);
  let styleChanges = 0;
  map.setPaintProperty = (...args) => { styleChanges++; return originalPaintSetter(...args); };
  map.setLayoutProperty = (...args) => { styleChanges++; return originalLayoutSetter(...args); };
  sync(ids); await painted();
  check(styleChanges === 0, "Unchanged paints were unnecessarily reinstalled");
  sync([]); await painted();
  const ordinary = pixel(1);
  check(ordinary[1] > ordinary[0], "Removing comparison did not restore ordinary colors");
  sync(ids, new Set([ids[0]])); await painted();
  const shown = new Set(map.queryRenderedFeatures({ layers: ["footprint-fill"] }).map((item) => item.properties.id));
  check(shown.size === 1 && shown.has(ids[0]), "Comparison reinserted a filtered scheme");
  sync(ids); await painted(); checkColors("Restored comparisons");
  choices[0].x = choices[2].x;
  sync([ids[0]]); await painted();
  const overlapping = pixel(0);
  check(overlapping[1] > overlapping[0] + 40 && overlapping[2] > overlapping[0] + 40,
    `An ordinary selected footprint covered a compared scheme: ${overlapping}`);
  document.body.dataset.result = "PASS";
}
run().catch((error) => { document.body.dataset.result = `FAIL: ${error.message}`; document.body.append(String(error)); });
