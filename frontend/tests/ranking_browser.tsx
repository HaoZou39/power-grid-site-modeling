import { createRoot } from "react-dom/client";
import { useState, type ComponentProps } from "react";
import { RoutingResults } from "../src/routing/routing_results.js";
import { SiteResults } from "../src/map/site_results.js";
import { manualChoice } from "../src/map/decision_run.js";
import { BuildingFootprint } from "../src/map/building_footprint.js";
import { routingFeatures } from "../src/routing/routing_layer.js";
import type { RoutingMapState } from "../src/routing/routing_layer.js";
import type { RoutingSolution } from "../src/routing/routing_result.js";
import type { SiteFrame } from "../src/map/site_frame.js";
import "../src/styles.css";
import "../src/routing/routing.css";

import { filteredCsv, type FilterSnapshot } from "../src/results/filter_snapshot.js";
const routes: RoutingSolution[] = Array.from({ length: 60 }, (_, index) => ({
  id: `route-${index + 1}`, is_feasible: true, is_pareto: true, violations: {},
  objectives: { length_3d_m: index + 1, tower_count: index + 1, bend_sum_rad: index / 10, crossing_3d_m: index + 1 },
  points: [{ x: 0, y: 0, z: 0, role: "start" }, { x: index + 1, y: 1, z: 0, role: "tower" }, { x: 14, y: 0, z: 0, role: "end" }],
  spans: [], turns_deg: [], tower_slopes_deg: [], tortuosity_k: 1 + index / 10, tortuosity_status: "ok",
}));
const noop = () => {};
const site = new URLSearchParams(location.search).has("site");
const metric = site ? "地形平整度" : "三维长度 m";
const secondMetric = site ? "进站长度 m" : "新增塔";
const poses = routes.map((route, index) => ({ ...manualChoice(route.id, { x: index, y: index }, 0),
  rawMetrics: { demSoft: index + 1, offroadHaul: index + 1, haulRise: index + 1 }, demSoft: String(index + 1), offroadHaul: String(index + 1), haulRise: String(index + 1) }));
const state: ComponentProps<typeof RoutingResults>["state"] = {
  filterSnapshot: null, resultTask: { scene_name: "fixture" }, bundle: { schema_version: 1, problem_type: "routing", scene_name: "fixture", frame: {} as never, routes },
  front: routes, catalog: routes, loadedExperimentId: null, resultSummary: null, resultStale: false,
  selected: null, selectedId: null, compared: [], toggleCompared: noop, selectRoute: noop,
  portfolio: null, displayMode: "filtered", setDisplayMode: noop, paretoPage: 0, setParetoPage: noop,
  routeQuery: "", setRouteQuery: noop,
};
let displayed = { ids: [] as string[] };
const publish = (ids: string[]) => { displayed = { ids }; };
const root = document.getElementById("root")!;
root.className = "map-app";
root.dataset.theme = "dark";
let saved: FilterSnapshot | null = null;
window.fetch = async (_url, init) => {
  saved = JSON.parse(String(init?.body)).snapshot;
  return new Response(JSON.stringify({ id: "saved-fixture", name: "测试筛选", solution_count: saved!.retained_ids.length }), { status: 201 });
};
let restore = (_snapshot: FilterSnapshot) => {};
function Fixture() {
  const [page, setPage] = useState(0);
  const [snapshot, setSnapshot] = useState<FilterSnapshot | null>(null);
  restore = setSnapshot;
  return site ? <SiteResults key={snapshot ? "restored" : "original"} poses={poses} sourceKey="fixture" selectedId="route-60" hasOrigin={false} includeDemand={false}
    freshness={() => "current"} comparedIds={["route-59"]} onToggleCompare={noop} onSelect={noop} onRetainedChange={publish}
    restoredSnapshot={snapshot} caseContext={{ problem_type: "site", scene_name: "fixture", source_experiment_id: "source", scene_version: {}, scope: {}, context: { widthM: 10, heightM: 20 } }} />
    : <RoutingResults key={snapshot ? "restored" : "original"} state={{ ...state, filterSnapshot: snapshot, paretoPage: page, setParetoPage: setPage }} onDisplayedRoutesChange={publish} />;
}
createRoot(root).render(<Fixture />);
const style = document.createElement("style");
const panelWidth = new URLSearchParams(location.search).has("narrow") ? 610 : 1100;
style.textContent = `.routing-results,.site-results { width:${panelWidth}px!important; height:850px!important; left:30px!important; top:100px!important; }`;
document.head.append(style);

function check(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));
function button(text: string, parent: ParentNode = document): HTMLButtonElement {
  const found = [...parent.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent?.trim() === text);
  check(found, `Missing button: ${text}`); return found;
}
function header(label: string) {
  const found = [...document.querySelectorAll<HTMLButtonElement>(".ranking-sort-button")].find((item) => item.textContent?.startsWith(label));
  check(found, `Missing header: ${label}`); return found;
}
function slider(edge: string) {
  const found = document.querySelector<HTMLInputElement>(`input[aria-label="${metric} 区间${edge}"]`);
  check(found, `Missing slider: ${edge}`); return found;
}
async function change(input: HTMLInputElement, value: number) {
  input.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, String(value));
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
  await settle();
}

async function run() {
  await settle();
  check(displayed.ids.length === 60, "All retained candidates must be displayed, across pages");
  check(!document.querySelector(".ranking-opacity-control"), "Opacity control remains");
  if (!site) { button("下一页").click(); await settle(); check(displayed.ids.length === 60, "Paging changed map membership"); button("上一页").click(); await settle(); }
  button("保存筛选结果（60）").click(); await settle();
  header(metric).click(); await settle();
  await change(slider("上界"), 3.1);
  button("确认保存").click(); await settle();
  check(saved !== null && saved.retained_ids.length === 60, "Save must use the click snapshot, not later slider edits");
  check(saved!.candidates.length === 60 && saved!.retained_ids.at(-1) === "route-60", "Snapshot lost off-page candidates");
  check(filteredCsv(saved!).split("\r\n").length === 61, "CSV lost retained rows");
  button("清空").click(); await settle();
  if (document.querySelector(".ranking-range-detail")) button("关闭", document.querySelector(".ranking-range-detail")!).click();
  await settle();
  header(metric).click(); await settle();
  const metricCells = [...document.querySelectorAll(".ranking-results-table thead tr:last-child th")].slice(2);
  check(metricCells.every((cell) => cell.getBoundingClientRect().width >= 70), "Metric columns collapsed under the opacity header");
  const recordStyle = getComputedStyle(button("修改", document.querySelector(".ranking-stage")!));
  check((recordStyle.backgroundColor.match(/\d+/g) ?? []).slice(0, 3).every((value) => Number(value) < 100), "Record button still has a white background in dark mode");
  check(!document.querySelector(".ranking-range-detail"), "Detail should wait for slider interaction");
  const before = slider("上界").getBoundingClientRect();
  await change(slider("上界"), 3.1);
  check(displayed.ids.join() === "route-1,route-2,route-3", "Filtered rows filled the retained top ten");

  const after = slider("上界").getBoundingClientRect();
  check(Math.abs(before.top - after.top) < 1 && Math.abs(before.left - after.left) < 1, `Opening detail moved the slider: ${before.left},${before.top} to ${after.left},${after.top}`);
  check(document.querySelectorAll(".ranking-bin").length === 16, "Full histogram is missing");
  check(getComputedStyle(document.querySelector(".ranking-range-detail")!).visibility === "visible", "Expanded histogram is mounted but invisible");
  check(document.querySelector(".ranking-range-detail")?.textContent?.includes("本轮保留 3 个"), "Expanded count is stale");
  header(metric).click(); await settle();
  header(metric).click(); await settle();
  check(document.querySelector(".ranking-stage")?.textContent?.includes("载入顺序"), "Load-order label is missing");
  check(displayed.ids.join() === "route-1,route-2,route-3", "Load order cleared the filter or kept descending order");
  await change(slider("上界"), 2.1);
  check(document.querySelectorAll("tbody tr.ranking-filtered").length > 0, "Excluded rows must stay gray in the table");
  check(displayed.ids.join() === "route-1,route-2", "Map did not refresh when only retained membership changed");
  await change(slider("上界"), 2.5);
  await change(slider("下界"), 2.4);
  check(displayed.ids.length === 0, "Zero retained routes must not fall back to ten");
  const frame = { localToLngLat: ({ x, y }: { x: number; y: number }) => ({ lng: x, lat: y }) } as SiteFrame;
  const mapState = { active: true, start: null, end: null, regions: [], draft: [], routes: routes.filter((route) => displayed.ids.includes(route.id)),
    selectedId: "route-60", compared: ["route-59"], towerRadius: 1, towerRouteIds: displayed.ids } as unknown as RoutingMapState;
  check(routingFeatures(frame, mapState).features.length === 0, "Excluded routes or towers were reinserted by selection");
  if (site) {
    const footprints = BuildingFootprint.layer(poses, { widthM: 10, heightM: 20 }, 59, ["route-59"], new Set(displayed.ids));
    check(footprints.length === 0, "Excluded site footprints were reinserted by selection or recommendations");
  }
  button("清空").click(); await settle();
  header(metric).click(); await settle();
  header(secondMetric).click(); await settle();
  let records = document.querySelectorAll(".ranking-stage");
  check(records.length === 2, "Sort actions were not recorded");
  button("下移", records[0]).click(); await settle();
  records = document.querySelectorAll(".ranking-stage");
  check(records[0].textContent?.includes(secondMetric) && records[1].textContent?.includes(metric), "Record move did not reorder stages");
  check(!document.querySelector("thead [draggable=true]"), "Column dragging is still enabled");
  button("修改", records[1]).click(); await settle();
  check(document.querySelector(".ranking-range-detail")?.textContent?.includes(metric), "Modify did not open matching range detail");
  button("关闭", document.querySelector(".ranking-range-detail")!).click(); await settle();
  check(!document.querySelector(".ranking-range-detail"), "Close failed");
  button("撤销上一轮").click(); await settle();
  check(document.querySelectorAll(".ranking-stage").length === 1, "Undo round failed");
  button("移除", document.querySelector(".ranking-stage")!).click(); await settle();
  check(document.querySelectorAll(".ranking-stage").length === 0, "Remove failed");
  check(button("撤销上一轮").disabled && button("清空").disabled, "Empty recorder controls should remain visible and disabled");
  header(metric).click(); await settle();
  await change(slider("上界"), 3.1);
  header(secondMetric).click(); await settle();
  records = document.querySelectorAll(".ranking-stage");
  button("修改", records[0]).click(); await settle();
  button("移除", records[1]).click(); await settle();
  check(slider("上界").max === "60", "Removing another round shrank this round's input range to its retained values");
  button("修改", document.querySelector(".ranking-stage")!).click(); await settle();
  button("保存筛选结果（3）").click(); await settle();
  button("确认保存").click(); await settle();
  const snapshot = saved!;
  check(snapshot.retained_ids.length === 3 && snapshot.candidates.length === 60 && snapshot.stages.length === 1, "Snapshot must preserve excluded candidates and rounds");
  restore(snapshot); await settle(); await settle();
  check(displayed.ids.join() === snapshot.retained_ids.join(), "Reopening did not restore retained order");
  check(document.querySelectorAll(".ranking-stage").length === 1, "Reopening lost records");
  const only = document.querySelector<HTMLInputElement>('.filter-case-actions input[type=checkbox]')!;
  only.click(); await settle();
  check(document.querySelectorAll("tbody tr").length === 3, "Only retained view contains excluded candidates");
  button("清空").click(); await settle();
  check(displayed.ids.length === 60, "Clearing restored filters lost the candidate snapshot");
  document.body.dataset.result = "PASS";
}
run().catch((error) => { document.body.dataset.result = `FAIL: ${error.message}`; });
