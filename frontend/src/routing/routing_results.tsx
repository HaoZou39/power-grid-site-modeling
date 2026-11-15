import { useMemo } from "react";
import { nextRoutingSort, sortRoutingSolutions } from "./routing_result";
import type { RoutingObjectives } from "./routing_result";
import { groupNeedsReview, routingModeContent } from "./routing_portfolio";
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
const shown = (value: number | null | undefined, digits = 1) => typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "无数据";
const MODES: readonly { id: RoutingDisplayMode; label: string }[] = [
  { id: "recommended", label: "推荐方案" },
  { id: "groups", label: "相似线路" },
  { id: "all", label: "全部 Pareto" },
];

export function RoutingResults({ state }: { state: Results }) {
  const { front, resultSummary, resultStale, selected, selectedId, compared, toggleCompared, selectRoute } = state;
  const sort = state.routeSort;
  const preview = state.portfolio?.status === "complete" ? state.portfolio : null;
  const content = useMemo(() => preview ? routingModeContent(preview, state.displayMode, {
    expandedGroupId: state.expandedGroupId, query: state.routeQuery, page: state.paretoPage, sort,
    pinnedIds: [...compared, ...(selectedId ? [selectedId] : [])],
  }) : null, [preview, state.displayMode, state.expandedGroupId, state.routeQuery, state.paretoPage, sort, compared, selectedId]);
  const rows = content ? content.rows.map((route, index) => ({ route, index })) : sortRoutingSolutions(front, sort);
  const recommendation = preview && selected ? content?.recommendationByRoute.get(selected.id) : undefined;
  const group = preview && selected ? content?.groupByRoute.get(selected.id) : undefined;
  return <section className="routing-results" aria-label="选线结果">
      <h2>选线方案 · {preview ? modeCount(preview, state.displayMode) : `${front.length} 条线路`}</h2>
      {preview ? <div className="routing-mode-switch" role="group" aria-label="线路显示档">
        {MODES.map((mode) => <button key={mode.id} type="button" aria-pressed={state.displayMode === mode.id}
          onClick={() => state.setDisplayMode(mode.id)}>{mode.label}：{countLabel(preview, mode.id)}</button>)}
      </div> : <p>全部线路已显示在地图上；可行线路可勾选对比。净空未校核。</p>}
      {preview && <p>切换显示不重新优化。相似组只表示五项数值接近，不是工程等效。净空未校核。</p>}
      {preview && selectedId && outsideMode(preview, state.displayMode, state.expandedGroupId, selectedId) && <p role="status">所选线路不在当前显示档的代表集合里，仍保持选中，对比列表没有移除。</p>}
      {state.portfolio && state.portfolio.status !== "complete" && <p role="status">{state.portfolio.message}</p>}
      <div className="routing-sort-help"><span>点击目标列标题排序，再次点击切换升降序。</span>
        {sort && <button type="button" onClick={() => state.setRouteSort(null)}>恢复原顺序</button>}
        {preview && state.displayMode === "all" && <input aria-label="搜索线路编号" placeholder="搜索 route_id" value={state.routeQuery}
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
          const extra = !preview ? null : state.displayMode === "recommended" && recommendation ? recommendation.recommendation_tags.join("、")
            : state.displayMode === "groups" && group && route.id === group.representative_route_id
              ? `${group.member_count} 条${groupNeedsReview(group) ? "，工程差异待复核" : ""}`
              : state.displayMode === "groups" && group ? "组成员" : null;
          const label = preview ? route.id : `线路 ${index + 1}`;
          return <tr key={route.id} aria-selected={route.id === selectedId}>
            <td><input type="checkbox" disabled={!route.is_feasible} aria-label={`对比线路 ${label}`} checked={compared.includes(route.id)} onChange={() => toggleCompared(route.id)} /></td>
            <td><button type="button" onClick={() => {
              selectRoute(route.id);
              if (preview && state.displayMode === "groups" && group && route.id === group.representative_route_id) {
                state.setExpandedGroupId(state.expandedGroupId === group.group_id ? null : group.group_id);
              }
            }}>{label}{route.is_feasible ? "" : " · 不可行"}{extra ? ` · ${extra}` : ""}</button></td>
            <td>{shown(route.objectives.tower_count, 0)}</td><td>{shown(route.objectives.length_3d_m)}</td>
            <td>{typeof route.objectives.bend_sum_rad === "number" ? shown(route.objectives.bend_sum_rad * 180 / Math.PI) : "无数据"}</td><td>{shown(route.objectives.crossing_3d_m)}</td>
          </tr>;
        })}
        </tbody></table>
      {content && state.displayMode === "all" && content.pageCount > 1 && <div className="routing-sort-help">
        <button type="button" disabled={content.page === 0} onClick={() => state.setParetoPage(content.page - 1)}>上一页</button>
        <span>第 {content.page + 1} / {content.pageCount} 页，共 {content.matchedCount} 条</span>
        <button type="button" disabled={content.page + 1 >= content.pageCount} onClick={() => state.setParetoPage(content.page + 1)}>下一页</button>
      </div>}
      {!rows.length && <p>{preview ? "这一档没有线路。" : "本次预算内未找到可行线路。可调整约束或计算预算后重试。"}</p>}
      {selected && recommendation && <p>推荐标签：{recommendation.recommendation_tags.join("、") || "无"}。{recommendation.recommendation_reasons}</p>}
      {selected && group && <p>所属相似组 {group.group_id}，成员 {group.member_count} 条。复核状态 {group.engineering_review_status}。
        {groupNeedsReview(group) ? "工程差异待复核。" : ""}
        {group.group_risk_flags.includes("CROSSING_OBJECTS_DATA_MISSING") ? "跨越对象 DATA_MISSING。" : ""}
        <button type="button" onClick={() => { state.setDisplayMode("groups"); state.setExpandedGroupId(group.group_id); }}>查看相似线路</button>
      </p>}
      {selected && <details open><summary>当前线路：逐档与塔基指标</summary>
        <table><thead><tr><th>档</th><th>水平 m</th><th>三维 m</th><th>跨越 m</th></tr></thead><tbody>
          {selected.spans.map((span, index) => <tr key={index}><td>{index + 1}</td><td>{shown(span.horizontal_m)}</td><td>{shown(span.length_3d_m)}</td><td>{shown(span.crossing_3d_m)}</td></tr>)}
        </tbody></table>
        <p>塔位水平转角（°）：{selected.turns_deg.map((value) => value.toFixed(1)).join("、") || "无中间塔"}</p>
        <p>塔基最大坡度（°，仅报告）：{selected.tower_slopes_deg.map((value) => value?.toFixed(1) ?? "缺失").join("、") || "无中间塔"}</p>
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
  return `${MODES.find((item) => item.id === mode)?.label} ${countLabel(portfolio, mode)}`;
}
