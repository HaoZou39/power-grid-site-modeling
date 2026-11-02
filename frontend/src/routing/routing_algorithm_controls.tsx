import { ROUTING_ALGORITHM_LABELS } from "./routing_edit";
import type { RoutingEdit } from "./routing_edit";

/** The advanced form edits the same task state as the main routing controls. */
export function RoutingAlgorithmControls({ edit, update }: {
  edit: RoutingEdit; update: (edit: RoutingEdit) => void;
}) {
  return <details><summary>算法参数</summary>
          <button type="button" onClick={() => update(edit.resetAlgorithm())}>恢复当前算法默认参数</button>
          {edit.algorithm.search_strategy === "pilot_reference" && <p className="hud-note">支持 CPU 参考执行或张量演化与评价；CUDA 设备需显式填写。初始化与规划器仍在 CPU，启用机制以本次配置为准。</p>}
          {edit.algorithm.search_strategy === "pilot_reference" && <p className="hud-note" aria-label="已启用选线机制">{edit.mechanismSummary}</p>}
          {edit.algorithm.search_strategy === "pilot_reference" && "rrt_goal_bias" in (edit.algorithmDefaults.pilot as Record<string, unknown> ?? {}) && <label><input type="checkbox" checked={edit.rrtEnabled}
            onChange={(event) => update(edit.toggleRrt(event.target.checked))} />RRT 初始化（默认启用，可关闭）</label>}
          {edit.algorithm.search_strategy === "pilot_reference" && "initialization_mode" in edit.pilotParameters && <>
            <label>初始化模式<select value={String(edit.pilotParameters.initialization_mode)}
              onChange={(event) => update(edit.pilotParameter("initialization_mode", event.target.value))}>
              {edit.algorithmSchema.properties?.pilot?.properties?.initialization_mode?.enum?.map((mode) =>
                <option key={String(mode)} value={String(mode)}>{{ legacy: "原始参考", pruned: "种子删塔", balanced: "删塔并补齐种群", bounded: "补齐并控制上界扩展", hybrid: "PILOT 混合初始化" }[String(mode)] ?? String(mode)}</option>)}
            </select></label>
            {edit.pilotParameters.initialization_mode === "hybrid" && <p className="hud-note">混合初始化使用多尺度 A* 和 RRT；可在此关闭 RRT。</p>}
            <label>初始化评价上限（种群倍数）<input type="number" min="1" step="1"
              value={String(edit.pilotParameters.initialization_budget_factor)}
              onChange={(event) => update(edit.pilotParameter("initialization_budget_factor", Number(event.target.value)))} /></label>
            {edit.rrtEnabled && <>
              <label>RRT 终点采样概率<input type="number" min="0" max="1" step="any" value={String(edit.pilotParameters.rrt_goal_bias)}
                onChange={(event) => update(edit.pilotParameter("rrt_goal_bias", Number(event.target.value)))} /></label>
              <label>RRT 最小扩展与档距比例<input type="number" min="0" max="1" step="any" value={String(edit.pilotParameters.rrt_min_step_ratio)}
                onChange={(event) => update(edit.pilotParameter("rrt_min_step_ratio", Number(event.target.value)))} /></label>
            </>}
          </>}
          {Object.entries(ROUTING_ALGORITHM_LABELS).filter(([name]) => name in edit.algorithm).map(([name, label]) => <label key={name}>{label}
          {edit.algorithmSchema.properties?.[name]?.enum ? <select value={String(edit.algorithm[name] ?? "")}
            onChange={(event) => update(edit.algorithmParameter(name, event.target.value))}>
            {edit.algorithmSchema.properties[name].enum?.map((choice) => <option key={String(choice)} value={String(choice)}>{name === "search_strategy"
                ? (choice === "pilot_reference" ? "PILOT 选线策略" : "标准选线策略") : String(choice)}</option>)}
          </select> : <input value={String(edit.algorithm[name] ?? "")}
            onChange={(event) => update(edit.algorithmParameter(name, event.target.value))} />}
        </label>)}</details>;
}
