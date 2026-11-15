import { useMemo } from "react";
import { finiteEntries, formatFinite, nextRoutingSort, sortRoutingSolutions, visibleSpanColumns } from "./routing_result";
import type { RoutingObjectives } from "./routing_result";
import { groupNeedsReview, LEGACY_PORTFOLIO_MESSAGE, ROUTING_MODES, routingModeContent } from "./routing_portfolio";
import type { RoutingDisplayMode, RoutingPortfolio } from "./routing_portfolio";
import type { RoutingController } from "./use_routing_controller";

type Results = Pick<RoutingController, "front" | "resultSummary" | "resultStale" | "selected" | "selectedId" | "compared" | "toggleCompared" | "selectRoute"
  | "portfolio" | "displayMode" | "setDisplayMode" | "expandedGroupId" | "setExpandedGroupId" | "paretoPage" | "setParetoPage" | "routeQuery" | "setRouteQuery" | "routeSort" | "setRouteSort">;
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
    expandedGroupId: state.expandedGroupId, query: state.routeQuery, page: state.paretoPage, sort,
    pinnedIds: [...compared, ...(selectedId ? [selectedId] : [])],
  }) : null, [portfolio, state.displayMode, state.expandedGroupId, state.routeQuery, state.paretoPage, sort, compared, selectedId]);
  const rows = content ? content.rows.map((route, index) => ({ route, index })) : sortRoutingSolutions(front, sort);
  const recommendation = portfolio && selected ? content?.recommendationByRoute.get(selected.id) : undefined;
  const group = portfolio && selected ? content?.groupByRoute.get(selected.id) : undefined;
  const spanColumns = selected ? visibleSpanColumns(selected.spans) : [];
  const turns = selected ? finiteEntries(selected.turns_deg) : [];
  const slopes = selected ? finiteEntries(selected.tower_slopes_deg) : [];
  return <section className="routing-results" aria-label="选线结果">
      <h2>选线方案 · {portfolio ? modeCount(portfolio, state.displayMode) : `${front.length} 条线路`}</h2>
      <div className="routing-mode-switch" role="group" aria-label="线路显示档">
        {ROUTING_MODES.map((mode) => <button key={mode.id} type="button" aria-pressed={state.displayMode === mode.id}
          onClick={() => state.setDisplayMode(mode.id)}>{mode.label}{portfolio ? `：${countLabel(portfolio, mode.id)}` : ""}</button>)}
      </div>
      {portfolio ? <p>切换显示不重新优化。筛选组只表示五项数值接近，不是工程等效。净空未校核。</p>
        : <p role="status">{state.portfolio?.status === "failed" && state.portfolio.message ? state.portfolio.message : LEGACY_PORTFOLIO_MESSAGE}</p>}
      {portfolio && selectedId && outsideMode(portfolio, state.displayMode, state.expandedGroupId, selectedId) && <p role="status">所选线路不在当前显示档的代表集合里，仍保持选中，对比列表没有移除。</p>}
      <div className="routing-sort-help"><span>点击目标列标题排序，再次点击切换升降序。</span>
        {sort && <button type="button" onClick={() => state.setRouteSort(null)}>恢复原顺序</button>}
        {portfolio && state.displayMode === "all" && <input aria-label="搜索线路编号" placeholder="搜索线路编号" value={state.routeQuery}
          onChange={(event) => state.setRouteQuery(event.target.value)} />}
      </div>
      {resultStale && <p role="status">当前接入点或配置已修改，显示的是修改前的线路结果；请重新选线。</p>}
      {typeof resultSummary?.generation_count === "number" && <p aria-label="选线实际预算">
        实际完成 {resultSummary.generation_count} 代，搜索评价 {String(resultSummary.evaluation_count)} 次（其中初始化 {String(resultSummary.initialization_evaluations)} 次）。
      </p>}
      <table><thead><tr><th scope="col">对比</th><th scope="col">方案</th>{OBJECTIVE_COLUMNS.map(({ key, label }) => <th key={key} scope="col"
        aria-sort={sort?.objective === key ? sort.direction : "none"}>
        <button type="button" className="routing-sort-button" onClick={() => state.setRouteSort(nextRoutingSort(sort, key))}
          aria-label={`${label}，${sort?.objective === key ? (sort.direction === "ascending" ? "当前升序，点击降序" : "当前降序，点击升序") : "点击升序排序"}`}>
          {label} <span aria-hidden="true">{sort?.objective === key ? (sort.direction === "ascending" ? "▲" : "▼") : "↕"}</span>
        </button></th>)}</tr></thead>
        <tbody>{rows.map(({ route, index }) => {
          const group = content?.groupByRoute.get(route.id);
          const recommendation = content?.recommendationByRoute.get(route.id);
          const extra = !portfolio ? null : state.displayMode === "recommended" && recommendation ? recommendation.recommendation_tags.join("、")
            : state.displayMode === "groups" && group && route.id === group.representative_route_id
              ? `${group.member_count} 条${groupNeedsReview(group) ? "，工程差异待复核" : ""}`
              : state.displayMode === "groups" && group ? "组成员" : null;
          const label = portfolio ? route.id : `线路 ${index + 1}`;
          return <tr key={route.id} aria-selected={route.id === selectedId}>
            <td><input type="checkbox" disabled={!route.is_feasible} aria-label={`对比线路 ${label}`} checked={compared.includes(route.id)} onChange={() => toggleCompared(route.id)} /></td>
            <td><button type="button" onClick={() => {
              selectRoute(route.id);
              if (portfolio && state.displayMode === "groups" && group && route.id === group.representative_route_id) {
                state.setExpandedGroupId(state.expandedGroupId === group.group_id ? null : group.group_id);
              }
            }}>{label}{route.is_feasible ? "" : " · 不可行"}{extra ? ` · ${extra}` : ""}</button></td>
            <td>{objectiveText(route.objectives.tower_count, 0)}</td><td>{objectiveText(route.objectives.length_3d_m)}</td>
            <td>{objectiveText(typeof route.objectives.bend_sum_rad === "number" ? route.objectives.bend_sum_rad * 180 / Math.PI : null)}</td><td>{objectiveText(route.objectives.crossing_3d_m)}</td>
          </tr>;
        })}
        </tbody></table>
      {content && state.displayMode !== "recommended" && content.pageCount > 1 && <div className="routing-sort-help">
        <button type="button" disabled={content.page === 0} onClick={() => state.setParetoPage(content.page - 1)}>上一页</button>
        <span>第 {content.page + 1} / {content.pageCount} 页，共 {content.matchedCount} {state.displayMode === "groups" ? "组" : "条"}</span>
        <button type="button" disabled={content.page + 1 >= content.pageCount} onClick={() => state.setParetoPage(content.page + 1)}>下一页</button>
      </div>}
      {!rows.length && <p>{portfolio ? "这一档没有线路。" : "本次预算内未找到可行线路。可调整约束或计算预算后重试。"}</p>}
      {selected && recommendation && <p>推荐标签：{recommendation.recommendation_tags.join("、") || "无"}。{recommendation.recommendation_reasons}</p>}
      {selected && group && <p>所属相似线路组 {group.group_id}，成员 {group.member_count} 条。复核状态 {group.engineering_review_status}。
        {groupNeedsReview(group) ? "工程差异待复核。" : ""}
        {group.group_risk_flags.includes("CROSSING_OBJECTS_DATA_MISSING") ? "跨越对象 DATA_MISSING。" : ""}
        <button type="button" onClick={() => { state.setDisplayMode("groups"); state.setExpandedGroupId(group.group_id); }}>查看组内线路</button>
      </p>}
      {selected && (spanColumns.length > 0 || turns.length > 0 || slopes.length > 0) && <details open><summary>当前线路：逐档与塔基指标</summary>
        {spanColumns.length > 0 && <table><thead><tr><th>档</th>{spanColumns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>
          {selected.spans.map((span, index) => <tr key={index}><td>{index + 1}</td>{spanColumns.map((column) => <td key={column.key}>{formatFinite(span[column.key])}</td>)}</tr>)}
        </tbody></table>}
        {turns.length > 0 && <p>塔位水平转角（°）：{turns.map((item) => `${item.index}：${item.text}`).join("、")}</p>}
        {slopes.length > 0 && <p>塔基最大坡度（°，仅报告）：{slopes.map((item) => `${item.index}：${item.text}`).join("、")}</p>}
      </details>}
    </section>;
}

function outsideMode(portfolio: RoutingPortfolio, mode: RoutingDisplayMode, expandedGroupId: string | null, selectedId: string): boolean {
  if (mode === "recommended") return !portfolio.recommendations.some((item) => item.route_id === selectedId);
  if (mode === "all") return !portfolio.routes.some((route) => route.id === selectedId);
  const group = portfolio.groups.find((item) => item.member_route_ids.includes(selectedId));
  if (!group) return true;
  return group.representative_route_id !== selectedId && expandedGroupId !== group.group_id;
}

function countLabel(portfolio: RoutingPortfolio, mode: RoutingDisplayMode): string {
  if (mode === "recommended") return `${portfolio.counts.recommended ?? 0} 条`;
  if (mode === "groups") return `${portfolio.counts.groups ?? 0} 组`;
  return `${portfolio.counts.all ?? 0} 条`;
}

function modeCount(portfolio: RoutingPortfolio, mode: RoutingDisplayMode): string {
  return `${ROUTING_MODES.find((item) => item.id === mode)?.label} ${countLabel(portfolio, mode)}`;
}
