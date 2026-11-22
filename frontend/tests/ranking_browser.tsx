import { createRoot } from "react-dom/client";
import { useState, type ComponentProps } from "react";
import { RoutingResults } from "../src/routing/routing_results.js";
import { SiteResults } from "../src/map/site_results.js";
import { manualChoice } from "../src/map/decision_run.js";
import { BuildingFootprint } from "../src/map/building_footprint.js";
import { routingFeatures } from "../src/routing/routing_layer.js";
import type { RoutingMapState } from "../src/routing/routing_layer.js";
import type { RoutingSolution } from "../src/routing/routing_result.js";
import { routingRouteNumbers } from "../src/routing/routing_result.js";
import type { RoutingPortfolio, RoutingDisplayMode } from "../src/routing/routing_portfolio.js";
import type { SiteFrame } from "../src/map/site_frame.js";
import "../src/styles.css";
import "../src/routing/routing.css";

import { type FilterSnapshot } from "../src/results/filter_snapshot.js";
import { exportFilterResult, retainedFilterData } from "../src/results/filter_export.js";
import { SceneExportDialog } from "../src/map/scene_export_dialog.js";
import { defaultExportFilename } from "../src/map/scene_export.js";
import type { FilterCaseSource } from "../src/results/use_filter_case_source.js";
import { SaveExperimentDialog } from "../src/map/save_experiment_dialog.js";
import { HistoryPanel } from "../src/map/history_panel.js";
import type { ExperimentRecord } from "../src/api.js";
import { MapToolbar } from "../src/map/map_toolbar.js";
import { filteredExperimentName, siteExperimentName, routingExperimentName } from "../src/experiment_name.js";
import { saveFilterCase } from "../src/api.js";
const caseFrame = { crs: "EPSG:32651", transform: [1, 0, 221000, 0, -1, 3046000] as [number, number, number, number, number, number], width: 100, height: 100 };
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
  filterSnapshot: null, resultTask: { scene_name: "fixture" }, bundle: { schema_version: 1, problem_type: "routing", scene_name: "fixture", frame: caseFrame, routes },
  front: routes, catalog: routes, routeNumbers: routingRouteNumbers(routes), loadedExperimentId: null, resultSummary: null, resultStale: false,
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
let enableModes = () => {};
let replaceResult = () => {};
let setPanelActive = (_active: boolean) => {};
function Fixture() {
  const [active, setActive] = useState(true);
  setPanelActive = setActive;
  const [page, setPage] = useState(0);
  const [snapshot, setSnapshot] = useState<FilterSnapshot | null>(null);
  const [portfolio, setPortfolio] = useState<RoutingPortfolio | null>(null);
  const [displayMode, setDisplayMode] = useState<RoutingDisplayMode>("filtered");
  const [bundle, setBundle] = useState(state.bundle);
  enableModes = () => { setSnapshot(null); setPortfolio({ status: "complete", message: null, routes, groups: [],
    filteredRouteIds: routes.slice(0, 30).map((route) => route.id), maxTortuosity: null, counts: { all: 60, filtered: 30 } }); };
  replaceResult = () => setBundle((current) => ({ ...current!, routes: [...routes] }));
  restore = setSnapshot;
  const [source, setSource] = useState<FilterCaseSource | null>(null);
  const [pending, setPending] = useState<FilterSnapshot | null>(null);
  const [png, setPng] = useState<FilterSnapshot | null>(null);
  const baseName = site ? siteExperimentName("测试", 10, 20) : routingExperimentName("测试", { lng: 120, lat: 27 }, { lng: 121, lat: 28 });
  const toolbar = { tool: "pan", scenes: [], sceneId: null, sceneLabel: "测试", notify: noop, focusSite: noop, setTool: noop,
    landuseOperation: "paint", landuseTargetClass: "field", landuseEditDisabled: {} } as ComponentProps<typeof MapToolbar>;
  return <><MapToolbar {...toolbar} filteredResults={{ total: source?.total ?? 0, retained: source?.retained ?? 0,
    disabled: !source?.hasFilter || !source.retained, onSave: () => setPending(source!.capture()),
    onExport: (format) => { if (format === "png") setPng(source!.capture()); } }} />
    <SceneExportDialog open={png !== null} filteredCount={png?.retained_ids.length} mode={site ? "site" : "routing"}
      sceneTitle="测试" layers={[]} paretoCounts={{ 1: 0, 2: 0, 3: 0 }} busy={false} error="" onClose={() => setPng(null)} onExport={noop} />
    {pending && <SaveExperimentDialog count={pending.retained_ids.length} busy={false} error="" filtered routing={!site}
      defaultName={filteredExperimentName(baseName)} onClose={() => setPending(null)}
      onSave={async (name) => { await saveFilterCase({ name, snapshot: pending }); setPending(null); }} />}
    {site ? <SiteResults active={active} key={snapshot ? "restored" : "original"} poses={poses} sourceKey="fixture" selectedId="route-60" hasOrigin={false} includeDemand={false}
    freshness={() => "current"} comparedIds={["route-59"]} onToggleCompare={noop} onSelect={noop} onRetainedChange={publish} onFilterSourceChange={setSource}
    restoredSnapshot={snapshot} caseContext={{ problem_type: "site", scene_name: "fixture", source_experiment_id: "source", scene_version: {}, scope: {}, context: { frame: caseFrame, widthM: 10, heightM: 20 } }} />
    : <RoutingResults active={active} key={snapshot ? "restored" : "original"} state={{ ...state, bundle, portfolio, displayMode, setDisplayMode, filterSnapshot: snapshot, paretoPage: page, setParetoPage: setPage }} onDisplayedRoutesChange={publish} onFilterSourceChange={setSource} />}</>;
}
createRoot(root).render(<Fixture />);
const style = document.createElement("style");
const panelWidth = new URLSearchParams(location.search).has("narrow") ? 610 : 1100;
style.textContent = `.routing-results,.site-results { width:${panelWidth}px!important; height:850px!important; left:30px!important; top:200px!important; }`;
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
function mapCheckbox(label: string) {
  const option = [...document.querySelectorAll<HTMLLabelElement>(".ranking-map-options label")].find((item) => item.textContent === label);
  check(option, "Missing map option: " + label); return option.querySelector<HTMLInputElement>("input")!;
}

function rowNumbers() {
  return [...document.querySelectorAll<HTMLButtonElement>("tbody tr td:nth-child(2) button")].map((item) => Number(item.textContent));
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
  if (!site) {
    check(rowNumbers().join() === Array.from({ length: 50 }, (_, index) => index + 1).join(), "Selected or compared routes were pinned above their page");
    header(metric).click(); await settle(); header(metric).click(); await settle();
    check(rowNumbers().join() === Array.from({ length: 50 }, (_, index) => 60 - index).join(), "Highlight changed descending row order");
    header(metric).click(); await settle(); button("清空").click(); await settle();
    button("下一页").click(); await settle();
    check(displayed.ids.length === 60, "Paging changed map membership");
    check(rowNumbers().join() === Array.from({ length: 10 }, (_, index) => 51 + index).join(), "Highlighted routes did not remain in their normal page positions");
    button("上一页").click(); await settle();
  }
  button("文件").click(); await settle();
  const fileGroup = document.querySelector(".filter-file-group")!;
  check(fileGroup.firstElementChild?.className === "filter-file-count" && fileGroup.children[1] === button("另存筛选版…"), "Count should immediately precede filtered save inside its group");
  check(button("另存筛选版…").disabled && button("导出筛选版 CSV").disabled, "Unfiltered result actions must be disabled");
  check(button("导出筛选版 PNG").disabled, "Unfiltered PNG should be disabled");
  check(!document.querySelector(".filter-case-actions"), "Save panel still occupies the result area");
  header(metric).click(); await settle();
  check(button("另存筛选版…").disabled, "Sorting alone enabled filtered save");
  mapCheckbox("只看前十").click(); await settle();
  check(displayed.ids.length === 10, "Top-ten map mode does not limit retained items");
  await change(slider("上界"), 55.1);
  const beforeSwitch = slider("上界").value;
  setPanelActive(false); await settle();
  check(!document.querySelector(".ranking-range-detail"), "Inactive workspace left a histogram portal on screen");
  check(getComputedStyle(document.querySelector(".site-results,.routing-results")!).display === "none", "Inactive result panel remained visible");
  setPanelActive(true); await settle();
  check(slider("上界").value === beforeSwitch && displayed.ids.length === 10 && document.querySelectorAll(".ranking-stage").length === 1,
    "Switching problem type lost filtering or map settings");
  button("导出筛选版 PNG").click(); await settle();
  const pngDialog = document.querySelector(".scene-export-dialog")!;
  check(pngDialog.textContent?.includes("全部 55 个最终保留方案"), "PNG wrongly limited by top-ten map display");
  check(pngDialog.querySelector<HTMLInputElement>('input:not([type])')?.value === defaultExportFilename("测试", site ? "site" : "routing") + "筛选版", "PNG naming differs from full export");
  check(!pngDialog.textContent?.includes("第 1 层"), "Filtered PNG must not filter Pareto layers again");
  button("取消", pngDialog).click(); await settle();
  check(!button("另存筛选版…").disabled, "Range filtering did not enable save");
  button("另存筛选版…").click(); await settle();
  const name = document.querySelector<HTMLInputElement>('.scene-build-dialog input')!.value;
  const baseName = site ? siteExperimentName("测试", 10, 20) : routingExperimentName("测试", { lng: 120, lat: 27 }, { lng: 121, lat: 28 });
  check(name === baseName + "筛选版", "Default name differs from full save naming");
  await change(slider("上界"), 3.1);
  button("保存实验").click(); await settle();
  check(saved !== null && saved.retained_ids.length === 55, "Save must include all pages, ignoring top ten and later edits");
  check(exportFilterResult(saved!, "csv").trim().split("\r\n").length === 56, "CSV lost retained rows");
  const doc = JSON.parse(exportFilterResult(saved!, "json"));
  check((site ? doc.solutions : doc.routes).length === 55 && doc.filter_snapshot.candidates.length === 60, "JSON must keep domain format and complete filter trace");
  if (site) check(doc.coordinate_context.scene_id === "fixture" && doc.coordinate_context.frame.crs === caseFrame.crs,
    "Filtered export must use the snapshot's solution coordinate context");
  check(retainedFilterData(saved!).map((item) => item.id).join() === saved!.retained_ids.join(), "PNG geometry selection must use all retained IDs in order");
  mapCheckbox("全部方案").click(); await settle();
  check(displayed.ids.length === 60 && !mapCheckbox("只看前十").checked, "All mode failed or map options are not exclusive");
  mapCheckbox("全部方案").click(); await settle();
  check(displayed.ids.length === 3, "Unchecked options must return to retained items");
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
  button("另存筛选版…").click(); await settle();
  button("保存实验").click(); await settle();
  const snapshot = saved!;
  check(snapshot.retained_ids.length === 3 && snapshot.candidates.length === 60 && snapshot.stages.length === 1, "Snapshot must preserve excluded candidates and rounds");
  restore(snapshot); await settle(); await settle();
  check(displayed.ids.join() === snapshot.retained_ids.join(), "Reopening did not restore retained order");
  check(document.querySelectorAll(".ranking-stage").length === 1, "Reopening lost records");
  mapCheckbox("只看前十").click(); await settle();
  check(displayed.ids.length === 3, "Top ten must not fill with excluded candidates");
  mapCheckbox("全部方案").click(); await settle();
  check(displayed.ids.length === 60 && document.querySelectorAll("tbody tr.ranking-filtered").length > 0, "All map mode must preserve gray table rows");
  mapCheckbox("全部方案").click(); await settle();
  button("清空").click(); await settle();
  check(displayed.ids.length === 60, "Clearing restored filters lost the candidate snapshot");
  check(button("另存筛选版…").disabled, "Clearing filters did not disable save");
  if (!site) {
    enableModes(); await settle();
    check(rowNumbers().join() === Array.from({ length: 30 }, (_, index) => index + 1).join(), "Switching modes inserted selected or compared routes from another mode");
    check(!button("1").hasAttribute("title") && button("1").getAttribute("aria-label") === "线路 1", "Result labels must use numeric identifiers without raw ID tooltips");
    const modes = document.querySelector(".routing-mode-switch")!;
    const scrollBody = document.querySelector(".routing-results-body")!;
    check(!scrollBody.contains(modes), "Mode buttons must remain outside scrolling results");
    header(metric).click(); await settle();
    await change(slider("上界"), 5.1);
    const filteredUpper = slider("上界").value;
    mapCheckbox("只看前十").click(); await settle();
    button("帕累托解：60 条").click(); await settle();
    check(rowNumbers().join() === Array.from({ length: 50 }, (_, index) => index + 1).join(), "Pareto mode pinned highlighted routes instead of sorting normally");
    check(document.querySelectorAll(".ranking-stage").length === 0 && displayed.ids.length === 60, "New display scope inherited another scope's filters");
    header(metric).click(); await settle(); header(metric).click(); await settle();
    await change(slider("上界"), 8.1);
    const paretoUpper = slider("上界").value;
    button("筛选方案：30 条").click(); await settle();
    check(displayed.ids.length === 5 && slider("上界").value === filteredUpper && mapCheckbox("只看前十").checked, "Filtered scope lost its range or map settings");
    check(document.querySelector(".ranking-stage")?.textContent?.includes("升序"), "Filtered scope lost ascending order");
    button("另存筛选版…").click(); await settle(); button("保存实验").click(); await settle();
    check(saved!.candidates.length === 30 && saved!.retained_ids.length === 5, "Save captured the wrong display scope");
    button("清空").click(); await settle();
    button("帕累托解：60 条").click(); await settle();
    check(displayed.ids.length === 8 && displayed.ids[0] === "route-8" && slider("上界").value === paretoUpper, "Clearing filtered scope damaged Pareto scope");
    check(!button("8").hasAttribute("title") && button("8").getAttribute("aria-label") === "线路 8", "Sorting or switching views changed the label or restored raw ID tooltips");
    button("另存筛选版…").click(); await settle(); button("保存实验").click(); await settle();
    check(saved!.candidates.length === 60 && saved!.retained_ids.length === 8 && saved!.scope.display_mode === "all", "Pareto save used filtered scope state");
    button("筛选方案：30 条").click(); await settle();
    header(metric).click(); await settle(); await change(slider("上界"), 3.1);
    button("帕累托解：60 条").click(); await settle();
    replaceResult(); await settle();
    check(document.querySelectorAll(".ranking-stage").length === 0 && button("另存筛选版…").disabled, "New result retained old filters");
    button("筛选方案：30 条").click(); await settle();
    check(document.querySelectorAll(".ranking-stage").length === 0, "New result retained inactive-scope filters");
  }
  const historyHost = document.createElement("div");
  root.append(historyHost);
  const historyRoot = createRoot(historyHost);
  let imported = "";
  const cases = [
    { id: "alpha", name: "Alpha 筛选版", modified_at: "2026-11-22T10:30:00", algorithm: "workspace_snapshot", summary: { n_feasible: 3 } },
    { id: "beta", name: "Beta", modified_at: "2026-11-21T10:30:00", algorithm: "workspace_snapshot", summary: { n_feasible: 13 } },
    { id: "zero", name: "Zero", modified_at: "2026-10-22T10:30:00", algorithm: "workspace_snapshot", summary: { n_feasible: 0 } },
  ] as ExperimentRecord[];
  historyRoot.render(<HistoryPanel experiments={cases} loading={false} error="" pendingDeleteId={null} onClose={noop}
    onImport={(id) => { imported = id; }} onAskDelete={noop} onConfirmDelete={noop} onCancelDelete={noop} />);
  await settle();
  const search = () => historyHost.querySelector<HTMLInputElement>('input[aria-label="搜索案例"]')!;
  const names = () => [...historyHost.querySelectorAll(".history-row strong")].map((item) => item.textContent);
  async function searchFor(value: string) {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(search(), value);
    search().dispatchEvent(new Event("input", { bubbles: true })); await settle();
  }
  async function searchBy(value: string) {
    const field = historyHost.querySelector("select")!;
    field.value = value; field.dispatchEvent(new Event("change", { bubbles: true })); await settle();
    check(search().value === "", "Changing search field should clear the previous query");
  }
  await searchFor("alpha"); check(names().join() === "Alpha 筛选版", "Case name search failed");
  button("导入", historyHost).click(); check(imported === "alpha", "Searching changed the import target");
  await searchBy("date"); await searchFor("2026-11"); check(names().length === 2, "Month search failed");
  await searchFor("2026-11-22"); check(names().join() === "Alpha 筛选版", "Date search failed");
  await searchBy("feasible"); await searchFor("3"); check(names().join() === "Alpha 筛选版", "Feasible count should match exactly, not also 13");
  await searchFor("0"); check(names().join() === "Zero", "Zero feasible count search failed");
  await searchFor("9"); check(names().length === 0 && historyHost.textContent?.includes("没有匹配的案例"), "No-match hint missing");
  button("清空搜索", historyHost).click(); await settle(); check(names().length === 3, "Clearing search lost cases");
  historyRoot.unmount(); historyHost.remove();
  document.body.dataset.result = "PASS";
}
run().catch((error) => { document.body.dataset.result = `FAIL: ${error.message}`; });
