import { useMemo, useRef, useState } from "react";
import { useDraggablePanel } from "../map/use_draggable_panel";
import { finiteEntries, formatFinite, nextRoutingSort, routeTortuosity, sortRoutingSolutions, visibleSpanColumns } from "./routing_result";
import type { RoutingObjectives, RoutingSolution, RoutingSort } from "./routing_result";
import { FILTERED_EMPTY_MESSAGE, HISTORICAL_FILTER_MESSAGE, LEGACY_PORTFOLIO_MESSAGE, ROUTING_MODES, routingModeContent } from "./routing_portfolio";
import type { RoutingDisplayMode, RoutingPortfolio } from "./routing_portfolio";
import type { RoutingController } from "./use_routing_controller";

type Results = Pick<RoutingController, "front" | "resultSummary" | "resultStale" | "selected" | "selectedId" | "compared" | "toggleCompared" | "selectRoute"
  | "portfolio" | "displayMode" | "setDisplayMode" | "paretoPage" | "setParetoPage" | "routeQuery" | "setRouteQuery" | "routeSort" | "setRouteSort">;
const OBJECTIVE_COLUMNS: readonly { key: keyof RoutingObjectives; label: string }[] = [
  { key: "tower_count", label: "新增塔" },
  { key: "length_3d_m", label: "三维长度 m" },
  { key: "bend_sum_rad", label: "水平曲折 °" },
  { key: "crossing_3d_m", label: "跨越 m" },
];
const objectiveText = (value: unknown, digits = 1) => formatFinite(value, digits) || "不可用";

export function RoutingResults({ state }: { state: Results }) {
  const { front, resultSummary, resultStale, selected, selectedId, compared, toggleCompared, selectRoute } = state;
  const sort = state.routeSort;
  const portfolio = state.portfolio?.status === "complete" ? state.portfolio : null;
  const content = useMemo(() => portfolio ? routingModeContent(portfolio, state.displayMode, {
    query: state.routeQuery, page: state.paretoPage, sort,
    pinnedIds: [...compared, ...(selectedId ? [selectedId] : [])],
  }) : null, [portfolio, state.displayMode, state.routeQuery, state.paretoPage, sort, compared, selectedId]);
  const rows = content ? content.rows.map((route, index) => ({ route, index })) : sortRoutingSolutions(front, sort);
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
    style={{ ...panel.style, maxHeight: "none", ...(minimized ? { height: "auto" } : {}) }} aria-label="选线结果">
      <div className="routing-results-head panel-drag-handle" title="拖动选线结果" {...panel.dragHandleProps}>
        <h2>选线方案 · {title}</h2>
        <button type="button" className="agent-min" aria-label={minimized ? "展开选线结果" : "最小化选线结果"} title={minimized ? "展开" : "最小化"}
          onClick={toggleMinimized}>{minimized ? "▢" : "–"}</button>
      </div>
      {!minimized && <div className="routing-results-body">
      <div className="routing-mode-switch" role="group" aria-label="线路显示档">
        {ROUTING_MODES.map((mode) => {
          const count = portfolio ? countLabel(portfolio, mode.id) : "";
          return <button key={mode.id} type="button" aria-pressed={state.displayMode === mode.id}
            onClick={() => state.setDisplayMode(mode.id)}>{mode.label}{count ? `：${count}` : ""}</button>;
        })}
      </div>
      {portfolio ? <p>切换显示不重新优化。</p>
        : <p role="status">{state.portfolio?.status === "failed" && state.portfolio.message ? state.portfolio.message : LEGACY_PORTFOLIO_MESSAGE}</p>}
      {portfolio && state.displayMode === "filtered" && portfolio.filteredRouteIds == null && <p role="status">{HISTORICAL_FILTER_MESSAGE}</p>}
      {portfolio && selectedId && outsideMode(portfolio, state.displayMode, selectedId) && <p role="status">所选线路不在当前显示档里，仍保持选中，对比列表没有移除。</p>}
      <div className="routing-sort-help"><span>点击列标题排序，再次点击切换升降序。</span>
        {sort && <button type="button" onClick={() => state.setRouteSort(null)}>恢复原顺序</button>}
        {portfolio && state.displayMode === "all" && <input aria-label="搜索线路编号" placeholder="搜索线路编号" value={state.routeQuery}
          onChange={(event) => state.setRouteQuery(event.target.value)} />}
      </div>
      {resultStale && <p role="status">当前接入点或配置已修改，显示的是修改前的线路结果；请重新选线。</p>}
      {typeof resultSummary?.generation_count === "number" && <p aria-label="选线实际预算">
        实际完成 {resultSummary.generation_count} 代，搜索评价 {String(resultSummary.evaluation_count)} 次（其中初始化 {String(resultSummary.initialization_evaluations)} 次）。
      </p>}
      <table><thead><tr><th scope="col">对比</th><th scope="col">方案</th>
        <SortHeader label="曲折系数" sortKey="tortuosity_k" sort={sort} onSort={state.setRouteSort} />
        {OBJECTIVE_COLUMNS.map(({ key, label }) => <SortHeader key={key} label={label} sortKey={key} sort={sort} onSort={state.setRouteSort} />)}
      </tr></thead>
        <tbody>{rows.map(({ route, index }) => {
          const label = portfolio ? route.id : `线路 ${index + 1}`;
          return <tr key={route.id} aria-selected={route.id === selectedId}>
            <td><input type="checkbox" disabled={!route.is_feasible} aria-label={`对比线路 ${label}`} checked={compared.includes(route.id)} onChange={() => toggleCompared(route.id)} /></td>
            <td><button type="button" onClick={() => selectRoute(route.id)}>{label}{route.is_feasible ? "" : " · 不可行"}</button></td>
            <td>{tortuosityText(route)}</td>
            <td>{objectiveText(route.objectives.tower_count, 0)}</td><td>{objectiveText(route.objectives.length_3d_m)}</td>
            <td>{objectiveText(typeof route.objectives.bend_sum_rad === "number" ? route.objectives.bend_sum_rad * 180 / Math.PI : null)}</td><td>{objectiveText(route.objectives.crossing_3d_m)}</td>
          </tr>;
        })}
        </tbody></table>
      {content && content.pageCount > 1 && <div className="routing-sort-help">
        <button type="button" disabled={content.page === 0} onClick={() => state.setParetoPage(content.page - 1)}>上一页</button>
        <span>第 {content.page + 1} / {content.pageCount} 页，共 {content.matchedCount} 条</span>
        <button type="button" disabled={content.page + 1 >= content.pageCount} onClick={() => state.setParetoPage(content.page + 1)}>下一页</button>
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

function SortHeader({ label, sortKey, sort, onSort }: {
  label: string;
  sortKey: RoutingSort["objective"];
  sort: RoutingSort | null;
  onSort: (sort: RoutingSort | null) => void;
}) {
  const active = sort?.objective === sortKey;
  return <th scope="col" aria-sort={active ? sort.direction : "none"}>
    <button type="button" className="routing-sort-button" onClick={() => onSort(nextRoutingSort(sort, sortKey))}
      aria-label={`${label}，${active ? (sort.direction === "ascending" ? "当前升序，点击降序" : "当前降序，点击升序") : "点击升序排序"}`}>
      {label} <span aria-hidden="true">{active ? (sort.direction === "ascending" ? "▲" : "▼") : "↕"}</span>
    </button>
  </th>;
}

function tortuosityText(route: RoutingSolution): string {
  const value = routeTortuosity(route);
  return value.status === "invalid" || value.k == null ? "数据异常" : value.k.toFixed(3);
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
