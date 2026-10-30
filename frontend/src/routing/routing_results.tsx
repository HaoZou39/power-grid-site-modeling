import type { RoutingController } from "./use_routing_controller";

type Results = Pick<RoutingController, "front" | "resultSummary" | "selected" | "selectedId" | "compared" | "toggleCompared" | "selectRoute">;

export function RoutingResults({ state }: { state: Results }) {
  const { front, resultSummary, selected, selectedId, compared, toggleCompared, selectRoute } = state;
  return <section className="routing-results" aria-label="选线结果">
      <h2>选线方案 · {front.length} 个可行 Pareto 方案</h2><p>净空未校核；指标为保存时的结果。勾选方案可叠加对比。</p>
      {typeof resultSummary?.generation_count === "number" && <p aria-label="选线实际预算">
        实际完成 {resultSummary.generation_count} 代，搜索评价 {String(resultSummary.evaluation_count)} 次（其中初始化 {String(resultSummary.initialization_evaluations)} 次）。
      </p>}
      <table><thead><tr><th>对比</th><th>方案</th><th>新增塔</th><th>三维长度 m</th><th>水平曲折 °</th><th>跨越 m</th></tr></thead>
        <tbody>{front.map((route, index) => <tr key={route.id} aria-selected={route.id === selectedId}>
          <td><input type="checkbox" aria-label={`对比线路 ${index + 1}`} checked={compared.includes(route.id)} onChange={() => toggleCompared(route.id)} /></td>
          <td><button type="button" onClick={() => selectRoute(route.id)}>线路 {index + 1}</button></td>
          <td>{route.objectives.tower_count}</td><td>{route.objectives.length_3d_m.toFixed(1)}</td>
          <td>{(route.objectives.bend_sum_rad * 180 / Math.PI).toFixed(1)}</td><td>{route.objectives.crossing_3d_m.toFixed(1)}</td>
        </tr>)}</tbody></table>
      {!front.length && <p>本次预算内未找到可行线路。可调整约束或计算预算后重试。</p>}
      {selected && <details open><summary>当前线路：逐档与塔基指标</summary>
        <table><thead><tr><th>档</th><th>水平 m</th><th>三维 m</th><th>跨越 m</th></tr></thead><tbody>
          {selected.spans.map((span, index) => <tr key={index}><td>{index + 1}</td><td>{span.horizontal_m.toFixed(1)}</td><td>{span.length_3d_m.toFixed(1)}</td><td>{span.crossing_3d_m.toFixed(1)}</td></tr>)}
        </tbody></table>
        <p>塔位水平转角（°）：{selected.turns_deg.map((value) => value.toFixed(1)).join("、") || "无中间塔"}</p>
        <p>塔基最大坡度（°，仅报告）：{selected.tower_slopes_deg.map((value) => value?.toFixed(1) ?? "缺失").join("、") || "无中间塔"}</p>
      </details>}
    </section>;
}
