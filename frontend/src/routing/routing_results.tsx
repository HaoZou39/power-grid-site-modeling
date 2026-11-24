import { useFilterCaseSource, type FilterCaseSource } from "../results/use_filter_case_source.js";
import { captureFilterSnapshot } from "../results/filter_snapshot.js";
import type { RankingStage } from "../results/ranking_pipeline.js";
import { useEffect, useMemo, useRef, useState } from "react";
import { useDraggablePanel } from "../map/use_draggable_panel";
import { finiteEntries, formatFinite, routeTortuosity, visibleSpanColumns } from "./routing_result";
import type { RoutingObjectives, RoutingSolution, RoutingSortKey } from "./routing_result";
import { FILTERED_EMPTY_MESSAGE, HISTORICAL_FILTER_MESSAGE, LEGACY_PORTFOLIO_MESSAGE, ROUTING_MODES, ROUTING_PAGE_SIZE, routingModeContent } from "./routing_portfolio";
import type { RoutingDisplayMode, RoutingPortfolio } from "./routing_portfolio";
import type { RoutingController } from "./use_routing_controller";
import { RankingColumnHeader, RankingMapOptions, RankingRecorder, nextRankingDisplaySort, type RankingDisplaySort, type RankingField, type RankingMapMode } from "../results/ranking_controls.js";
import { RankingRangeHeader } from "../results/ranking_range_control.js";
import { useRankingPipeline } from "../results/use_ranking_pipeline.js";
import { useScopedState } from "../results/use_scoped_state.js";
import { hasRankingFilter, rankingMapIds, sortRankingRows } from "../results/ranking_pipeline.js";
import defaults from "../../../config/default_config.json";
import { corridorMapRouteIds, groupRoutingCorridors, readCorridorSnapshot } from "./corridor_groups.js";

type Results = Pick<RoutingController, "filterSnapshot" | "resultTask" | "bundle" | "front" | "catalog" | "routeNumbers" | "loadedExperimentId" | "resultSummary" | "resultStale" | "selected" | "selectedId" | "compared" | "toggleCompared" | "selectRoute"
  | "portfolio" | "displayMode" | "setDisplayMode" | "paretoPage" | "setParetoPage" | "routeQuery" | "setRouteQuery">;
const OBJECTIVE_COLUMNS: readonly { key: keyof RoutingObjectives; label: string }[] = [
  { key: "tower_count", label: "新增塔" },
  { key: "length_3d_m", label: "三维长度 m" },
  { key: "bend_sum_rad", label: "水平曲折 °" },
  { key: "crossing_3d_m", label: "跨越 m" },
];
const RANKING_FIELDS: readonly RankingField<RoutingSortKey>[] = [
  { key: "tortuosity_k", label: "曲折系数 K" },
  { key: "tower_count", label: "新增塔" },
  { key: "length_3d_m", label: "三维长度 m" },
  { key: "bend_sum_rad", label: "水平曲折 °" },
  { key: "crossing_3d_m", label: "跨越 m" },
];
const objectiveText = (value: unknown, digits = 1) => formatFinite(value, digits) || "不可用";

export function RoutingResults({ active = true, state, onDisplayedRoutesChange, onFilterSourceChange }: {
  active?: boolean;
  onFilterSourceChange?: (source: FilterCaseSource | null) => void;
  state: Results;
  onDisplayedRoutesChange: (ids: string[]) => void;
}) {
  const { front, resultSummary, resultStale, selected, selectedId, compared, toggleCompared, selectRoute } = state;
  const portfolio = state.portfolio?.status === "complete" ? state.portfolio : null;
  const content = useMemo(() => portfolio ? routingModeContent(portfolio, state.displayMode, {
    query: state.routeQuery, page: 0, sort: null, pinnedIds: [],
  }) : null, [portfolio, state.displayMode, state.routeQuery]);
  const sourceRoutes = content?.allRoutes ?? (state.filterSnapshot ? state.catalog : front);
  const groupable = state.displayMode === "filtered" && (portfolio?.filteredRouteIds != null || !!state.filterSnapshot);
  const corridorResult = useMemo(() => {
    if (!groupable) return { snapshot: null, error: null };
    try {
      return { snapshot: readCorridorSnapshot(state.filterSnapshot?.context?.corridor_grouping, sourceRoutes)
        ?? groupRoutingCorridors(sourceRoutes, defaults.routing_result), error: null };
    } catch (error) {
      return { snapshot: null, error: error instanceof Error ? error.message : String(error) };
    }
  }, [groupable, sourceRoutes, state.filterSnapshot]);
  const groups = corridorResult.snapshot?.groups ?? [];
  const resultKey = useMemo(() => ({}), [state.bundle, state.portfolio, state.filterSnapshot, state.loadedExperimentId]);
  const initialMetric = state.filterSnapshot?.display_sort?.key ?? state.filterSnapshot?.stages.at(-1)?.key;
  const [{ mapMode, displaySort, activeMetric, rangeExpanded, openGroupId }, updateView] = useScopedState<{
    mapMode: RankingMapMode; displaySort: RankingDisplaySort<RoutingSortKey>; activeMetric: RoutingSortKey; rangeExpanded: boolean; openGroupId: string | null;
  }>(resultKey, state.displayMode, { mapMode: groups.length ? "grouped" : "retained", displaySort: state.filterSnapshot?.display_sort as RankingDisplaySort<RoutingSortKey> ?? null,
    activeMetric: RANKING_FIELDS.some(({ key }) => key === initialMetric) ? initialMetric as RoutingSortKey : "tortuosity_k", rangeExpanded: false,
    openGroupId: groups[0]?.id ?? null });
  const setMapMode = (mapMode: RankingMapMode) => updateView((current) => ({ ...current, mapMode }));
  const setDisplaySort = (displaySort: RankingDisplaySort<RoutingSortKey>) => updateView((current) => ({ ...current, displaySort }));
  const setActiveMetric = (activeMetric: RoutingSortKey) => updateView((current) => ({ ...current, activeMetric }));
  const setRangeExpanded = (rangeExpanded: boolean) => updateView((current) => ({ ...current, rangeExpanded }));
  const sourceKey = `${state.loadedExperimentId ?? "current"}:${state.displayMode}:${state.routeQuery}:${sourceRoutes.map(routeId).join(",")}`;
  const ranking = useRankingPipeline(sourceRoutes,
    resultKey,
    RANKING_FIELDS.map(({ key }) => key), routeRankingValue, state.filterSnapshot?.stages as RankingStage<RoutingSortKey>[] | undefined, state.displayMode);
  const displayRows = useMemo(() => sortRankingRows(ranking.result.rows, displaySort?.key ?? null,
    displaySort?.direction ?? "ascending", routeRankingValue), [ranking.result.rows, displaySort]);
  const captureFilter = state.bundle && state.resultTask ? () => captureFilterSnapshot({
    problem_type: "routing", scene_name: state.bundle!.scene_name, source_experiment_id: state.loadedExperimentId,
    scene_version: state.filterSnapshot?.scene_version ?? state.bundle!.data_version ?? {},
    scope: state.filterSnapshot?.scope ?? { display_mode: state.displayMode, query: state.routeQuery },
    context: { frame: state.bundle!.frame, task: state.resultTask, metric_units: { bend_sum_rad: "degree", bend_sum_rad_raw: "radian" },
      ...(corridorResult.snapshot ? { corridor_grouping: corridorResult.snapshot } : {}) },
  }, sourceRoutes.map((route) => ({ id: route.id, original_number: state.routeNumbers[route.id], data: { ...route, number: state.routeNumbers[route.id] },
    geometry: { points: route.points }, metrics: { ...route.objectives, bend_sum_rad_raw: route.objectives.bend_sum_rad,
      ...Object.fromEntries(RANKING_FIELDS.map(({ key }) => [key, routeRankingValue(route, key)])) } })),
  displayRows, routeId, ranking.stages, ranking.result.retainedByStage, displaySort) : undefined;
  useFilterCaseSource(sourceKey, captureFilter ? { total: sourceRoutes.length, retained: ranking.result.active.length,
    hasFilter: hasRankingFilter(sourceRoutes, ranking.stages, routeRankingValue), capture: captureFilter } : null, onFilterSourceChange);
  function changeColumnSort(field: RoutingSortKey) {
    const next = nextRankingDisplaySort(displaySort, field);
    setDisplaySort(next);
    setActiveMetric(field);
    const direction = next?.direction ?? "original";
    ranking.open(field, direction);
    ranking.setStageDirection(field, direction);
  }
  function moveRankingStage(index: number, offset: -1 | 1) {
    const from = ranking.stages[index], to = ranking.stages[index + offset];
    if (!from || !to) return;
    ranking.reorder(from.key, to.key);
    setDisplaySort(null);
  }
  useEffect(() => { state.setParetoPage(0); }, [sourceKey]);
  function editRankingStage(index: number) {
    const stage = ranking.stages[index];
    if (stage) { setActiveMetric(stage.key); ranking.edit(index); setRangeExpanded(true); }
  }
  function removeRankingStage(index: number) {
    const stage = ranking.stages[index];
    ranking.remove(index);
    if (stage && displaySort?.key === stage.key) setDisplaySort(null);
  }
  function undoRankingStage() {
    const stage = ranking.stages.at(-1);
    ranking.undo();
    if (stage && displaySort?.key === stage.key) setDisplaySort(null);
  }
  function clearRanking() { ranking.clear(); setDisplaySort(null); }
  const selectedGroup = groups.find((group) => group.id === openGroupId) ?? groups[0];
  const groupIds = selectedGroup ? new Set(selectedGroup.member_route_ids) : null;
  const tableRows = groupIds ? displayRows.filter((row) => groupIds.has(row.item.id)) : displayRows;
  const pageCount = Math.max(1, Math.ceil(tableRows.length / ROUTING_PAGE_SIZE));
  const page = Math.min(state.paretoPage, pageCount - 1);
  const rows = tableRows.slice(page * ROUTING_PAGE_SIZE, (page + 1) * ROUTING_PAGE_SIZE);
  const activeIds = rankingMapIds(displayRows, routeId, "retained");
  const visibleRouteIds = mapMode === "grouped" && groups.length
    ? corridorMapRouteIds(groups, activeIds, selectedId, compared) : rankingMapIds(displayRows, routeId, mapMode);
  const visibleRouteKey = visibleRouteIds.join("\u001f");
  const spanColumns = selected ? visibleSpanColumns(selected.spans) : [];
  const turns = selected ? finiteEntries(selected.turns_deg) : [];
  const slopes = selected ? finiteEntries(selected.tower_slopes_deg) : [];
  const [minimized, setMinimized] = useState(false);
  const expandedHeight = useRef(480);
  const panelRef = useRef<HTMLElement>(null);
  const panel = useDraggablePanel(panelRef, {
    defaultSize: { width: 610, height: 480 },
    minSize: { width: 320, height: 160 },
    topInset: 180,
    margin: 12,
    initialPosition: (bounds, size) => ({
      x: Math.max(12, bounds.width - size.width - 20),
      y: 180,
    }),
  });
  useEffect(() => { onDisplayedRoutesChange(visibleRouteIds); }, [visibleRouteKey, onDisplayedRoutesChange]);
  useEffect(() => () => onDisplayedRoutesChange([]), [onDisplayedRoutesChange]);
  const title = portfolio ? modeCount(portfolio, state.displayMode) : `${front.length} 条线路`;
  function toggleMinimized() {
    const frame = panel.getFrame();
    if (frame) {
      if (minimized) panel.setFrame({ ...frame, height: expandedHeight.current });
      else {
        expandedHeight.current = frame.height;
        panel.setFrame({ ...frame, height: 64 });
      }
    }
    setMinimized((value) => !value);
  }
  return <section ref={panelRef} className={["routing-results", panel.dragging ? "panel-dragging" : "", panel.resizing ? "panel-resizing" : "", minimized ? "minimized" : ""].filter(Boolean).join(" ")}
    style={{ ...panel.style, maxHeight: "none", ...(minimized ? { height: "auto" } : {}), display: active ? undefined : "none" }} aria-label="选线结果">
      <div className="routing-results-head panel-drag-handle" title="拖动选线结果" {...panel.dragHandleProps}>
        <h2>选线方案 · {title}</h2>
      <RankingMapOptions mode={mapMode} onChange={setMapMode} grouped={groups.length > 0} />
        <button type="button" className="agent-min" aria-label={minimized ? "展开选线结果" : "最小化选线结果"} title={minimized ? "展开" : "最小化"}
          onClick={toggleMinimized}>{minimized ? "▢" : "–"}</button>
      </div>
      {!minimized && (portfolio || !state.filterSnapshot) && <div className="routing-mode-switch" role="group" aria-label="线路显示档">
        {ROUTING_MODES.map((mode) => {
          const count = portfolio ? countLabel(portfolio, mode.id) : "";
          return <button key={mode.id} type="button" aria-pressed={state.displayMode === mode.id}
            onClick={() => state.setDisplayMode(mode.id)}>{mode.label}{count ? `：${count}` : ""}</button>;
        })}
      </div>}
      {!minimized && <div className="routing-results-body">
      {state.filterSnapshot ? <p>筛选案例：已恢复候选快照与轮次，可继续调整后另存。</p> : portfolio ? <p>切换显示不重新优化。</p>
        : <p role="status">{state.portfolio?.status === "failed" && state.portfolio.message ? state.portfolio.message : LEGACY_PORTFOLIO_MESSAGE}</p>}
      {portfolio && state.displayMode === "filtered" && portfolio.filteredRouteIds == null && <p role="status">{HISTORICAL_FILTER_MESSAGE}</p>}
      {portfolio && selectedId && outsideMode(portfolio, state.displayMode, selectedId) && <p role="status">所选线路不在当前显示档里，仍保持选中，对比列表没有移除。</p>}
      <div className="routing-sort-help"><span>地图随筛选实时更新，不受列表分页影响。</span>
        {portfolio && state.displayMode === "all" && <input aria-label="搜索线路编号" placeholder="线路序号或原始编号" value={state.routeQuery}
          onChange={(event) => state.setRouteQuery(event.target.value)} />}
      </div>
      <RankingRecorder fields={RANKING_FIELDS} workflow={ranking} onEdit={editRankingStage} onRemove={removeRankingStage}
        onUndo={undoRankingStage} onClear={clearRanking} onMove={moveRankingStage} />
      {corridorResult.error && <p role="status">走廊分组不可用：{corridorResult.error}，已显示原线路列表。</p>}
      {groups.length > 0 && <section className="corridor-groups" aria-label="线路走廊分组">
        <div className="corridor-groups-head"><strong>走廊概览 · {groups.length} 组</strong><span>展开组查看线路；筛选和排序仍作用于全部线路</span></div>
        {groups.map((group, index) => {
          const retained = group.member_route_ids.filter((id) => activeIds.includes(id)).length;
          return <button key={group.id} type="button" className="corridor-group-button"
            title={`组内最大走向差 ${group.max_pair_distance_m.toFixed(1)} m`}
            aria-expanded={selectedGroup?.id === group.id} onClick={() => { updateView((current) => ({ ...current, openGroupId: group.id })); state.setParetoPage(0); }}>
            <span>走廊 {index + 1} · 代表线路 {state.routeNumbers[group.representative_route_id]}</span>
            <span>保留 {retained} / {group.member_route_ids.length} 条</span>
            {group.max_pair_distance_m > corridorResult.snapshot!.config.corridor_max_diameter_m && <span title="组数上限导致此组包含较宽的线路走向">跨度较大</span>}
          </button>;
        })}
      </section>}
      {resultStale && <p role="status">当前接入点或配置已修改，显示的是修改前的线路结果；请重新选线。</p>}
      {typeof resultSummary?.generation_count === "number" && <p aria-label="选线实际预算">
        实际完成 {resultSummary.generation_count} 代，搜索评价 {String(resultSummary.evaluation_count)} 次（其中初始化 {String(resultSummary.initialization_evaluations)} 次）。
      </p>}
      <table className="ranking-results-table">
      <colgroup><col style={{ width: 32 }} /><col style={{ width: 90 }} />{RANKING_FIELDS.map(({ key }) => <col key={key} />)}</colgroup>
      <thead>
      <tr><th scope="col">对比</th><th scope="col">编号</th>
        {[RANKING_FIELDS[0], ...OBJECTIVE_COLUMNS].map(({ key, label }) => <th key={key} scope="col"><div className="ranking-header-stack">
          <RankingColumnHeader label={label} field={key} sort={displaySort} workflow={ranking}
            onSort={changeColumnSort} />
          {activeMetric === key && <RankingRangeHeader field={key} fields={RANKING_FIELDS}
            valueOf={routeRankingValue} workflow={ranking} sort={displaySort}
            expanded={active && rangeExpanded} onExpandedChange={setRangeExpanded} />}
        </div></th>)}
      </tr></thead>
        <tbody>{rows.map(({ item: route, state: rowState, filteredAt }) => {
          const number = state.routeNumbers[route.id];
          return <tr key={route.id} className={rowState === "filtered" ? "ranking-filtered" : rowState === "unavailable" ? "ranking-unavailable" : undefined} aria-selected={route.id === selectedId}>
            <td><input type="checkbox" disabled={!route.is_feasible} aria-label={`对比线路 ${number}`} checked={compared.includes(route.id)} onChange={() => toggleCompared(route.id)} /></td>
            <td><button type="button" aria-label={`线路 ${number}`} onClick={() => selectRoute(route.id)}>{number}{route.is_feasible ? "" : " · 不可行"}</button>
              {rowState === "filtered" && <span>已筛除·第{filteredAt}轮</span>}
              {rowState === "unavailable" && <span>指标不可用</span>}
            </td>
            <td>{tortuosityText(route)}</td>
            <td>{objectiveText(route.objectives.tower_count, 0)}</td><td>{objectiveText(route.objectives.length_3d_m)}</td>
            <td>{objectiveText(typeof route.objectives.bend_sum_rad === "number" ? route.objectives.bend_sum_rad * 180 / Math.PI : null)}</td><td>{objectiveText(route.objectives.crossing_3d_m)}</td>
          </tr>;
        })}
        </tbody></table>
      {pageCount > 1 && <div className="routing-sort-help">
        <button type="button" disabled={page === 0} onClick={() => state.setParetoPage(page - 1)}>上一页</button>
        <span>第 {page + 1} / {pageCount} 页，共 {tableRows.length} 条</span>
        <button type="button" disabled={page + 1 >= pageCount} onClick={() => state.setParetoPage(page + 1)}>下一页</button>
      </div>}
      {!rows.length && portfolio && state.displayMode === "filtered" && portfolio.counts.filtered === 0 && <p>{FILTERED_EMPTY_MESSAGE}</p>}
      {!rows.length && !portfolio && <p>本次预算内未找到可行线路。可调整约束或计算预算后重试。</p>}
      {selected && (spanColumns.length > 0 || turns.length > 0 || slopes.length > 0) && <details open><summary>当前线路：逐档与塔基指标</summary>
        {spanColumns.length > 0 && <table><thead><tr><th>档</th>{spanColumns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>
          {selected.spans.map((span, index) => <tr key={index}><td>{index + 1}</td>{spanColumns.map((column) => <td key={column.key}>{formatFinite(span[column.key])}</td>)}</tr>)}
        </tbody></table>}
        {turns.length > 0 && <p>塔位水平转角（°）：{turns.map((item) => `${item.index}：${item.text}`).join("、")}</p>}
        {slopes.length > 0 && <p>塔基最大坡度（°，仅报告）：{slopes.map((item) => `${item.index}：${item.text}`).join("、")}</p>}
      </details>}
      </div>}
      {!minimized && <button type="button" className="panel-resize" aria-label="调整选线结果面板大小" title="调整大小" {...panel.resizeHandleProps} />}
    </section>;
}

function tortuosityText(route: RoutingSolution): string {
  const value = routeTortuosity(route);
  return value.status === "invalid" || value.k == null ? "数据异常" : value.k.toFixed(3);
}

function routeId(route: RoutingSolution): string { return route.id; }

function routeRankingValue(route: RoutingSolution, key: RoutingSortKey): number | null {
  if (key === "tortuosity_k") {
    const tortuosity = routeTortuosity(route);
    return tortuosity.status === "ok" ? tortuosity.k : null;
  }
  const value = route.objectives[key];
  if (!Number.isFinite(value)) return null;
  return key === "bend_sum_rad" ? value * 180 / Math.PI : value;
}

function outsideMode(portfolio: RoutingPortfolio, mode: RoutingDisplayMode, selectedId: string): boolean {
  if (mode === "all") return !portfolio.routes.some((route) => route.id === selectedId);
  if (portfolio.filteredRouteIds == null) return false;
  return !portfolio.filteredRouteIds.includes(selectedId);
}

function countLabel(portfolio: RoutingPortfolio, mode: RoutingDisplayMode): string {
  if (mode === "filtered") return portfolio.counts.filtered == null ? "" : `${portfolio.counts.filtered} 条`;
  return `${portfolio.counts.all ?? 0} 条`;
}

function modeCount(portfolio: RoutingPortfolio, mode: RoutingDisplayMode): string {
  return `${ROUTING_MODES.find((item) => item.id === mode)?.label} ${countLabel(portfolio, mode)}`;
}
