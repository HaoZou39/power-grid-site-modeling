import type { SceneRecord } from "../api";
import { JOB_STATUS_LABEL } from "../run_status";
import { ROUTING_ALGORITHM_LABELS, ROUTING_FIELD_LABELS } from "./routing_edit";
import type { RoutingFields } from "./routing_edit";
import type { RoutingController } from "./use_routing_controller";

type Controls = Pick<RoutingController, "edit" | "pick" | "draft" | "busy" | "jobId" | "job" | "error" | "notice" | "history" |
  "update" | "beginPick" | "removeRegion" | "start" | "cancel" | "finishRegion" | "refreshHistory" | "loadHistory">;

export function RoutingControls({ state, scene, scenes, onSceneChange, onFocus }: {
  state: Controls; scene: SceneRecord | null; scenes: SceneRecord[];
  onSceneChange: (id: string) => void; onFocus: () => void;
}) {
  const { edit, pick, draft, busy, jobId, job, error, notice, history, update,
    beginPick, removeRegion, start, cancel, finishRegion, refreshHistory, loadHistory } = state;
  return <aside className="hud-panel routing-controls" aria-label="选线配置">
      <p className="hud-kicker">杆塔选线</p><p className="hud-note">固定接入点 · 四目标最小化 · 净空未校核</p>
      <label>场景<select value={scene?.id ?? ""} disabled={busy} onChange={(event) => onSceneChange(event.target.value)}>
        {scenes.map((item) => <option key={item.id} value={item.id}>{item.title}{!item.ready ? "（未准备）" : ""}</option>)}
      </select></label>
      <button type="button" onClick={onFocus}>定位当前场景</button>
      <fieldset disabled={busy || !scene?.ready || scene.read_only === true}>
        {(["start", "end"] as const).map((which) => <section key={which} className="routing-connection">
          <strong>{which === "start" ? "起点" : "终点"} · 固定接入点</strong>
          <label>经度<input aria-label={`${which === "start" ? "起点" : "终点"}经度`} value={edit[which].lng}
            onChange={(event) => update(edit.connection(which, { ...edit[which], lng: event.target.value }))} /></label>
          <label>纬度<input aria-label={`${which === "start" ? "起点" : "终点"}纬度`} value={edit[which].lat}
            onChange={(event) => update(edit.connection(which, { ...edit[which], lat: event.target.value }))} /></label>
          <button type="button" aria-pressed={pick === which} onClick={() => { beginPick(which); }}>地图点选{which === "start" ? "起点" : "终点"}</button>
        </section>)}
        {(Object.keys(ROUTING_FIELD_LABELS) as RoutingFields[]).map((name) => <label key={name}>{ROUTING_FIELD_LABELS[name]}
          <input aria-label={ROUTING_FIELD_LABELS[name]} value={edit.values[name]} onChange={(event) => update(edit.copy({ values: { ...edit.values, [name]: event.target.value } }))} />
        </label>)}
        <p className="hud-note">道路控制距离同时影响塔基避让与跨越长度。</p>
        <div className="hud-actions"><button type="button" onClick={() => { beginPick("no_tower"); }}>绘制禁落塔区域</button>
          <button type="button" onClick={() => { beginPick("no_cross"); }}>绘制禁跨越区域</button></div>
        {pick && <p role="status">{pick === "start" || pick === "end" ? "请在地图范围内点选接入点。" : `请点选多边形顶点，当前 ${draft.length} 个点。`}</p>}
        {draft.length > 0 && <button type="button" onClick={finishRegion}>完成区域</button>}
        {pick && <button type="button" onClick={() => { beginPick(null); }}>取消点选</button>}
        {edit.regions.map((region, index) => <div key={index} className="routing-region-row">
          <span>{region.kind === "no_cross" ? "禁跨越" : "禁落塔"}区域 {index + 1}</span>
          <button type="button" onClick={() => removeRegion(index)}>删除</button>
        </div>)}
        {edit.generationLimit !== null && <p className="hud-note" aria-label="选线计算预算">
          评价预算 {String(edit.algorithm.max_evaluations)} 次，每代最多 {String(edit.algorithm.popsize)} 个候选，演化最多 {edit.generationLimit} 代。初始化、内部试探及局部/全局搜索共用评价预算，实际代数可能更少。
        </p>}
        <details><summary>算法参数</summary>
          <button type="button" onClick={() => update(edit.resetAlgorithm())}>恢复当前算法默认参数</button>
          {edit.algorithm.search_strategy === "pilot_reference" && <p className="hud-note">CPU 迁移参考策略；启用机制以本次配置为准，尚未启用的机制不会参与搜索。</p>}
          {edit.algorithm.search_strategy === "pilot_reference" && <p className="hud-note" aria-label="已启用选线机制">{edit.mechanismSummary}</p>}
          {edit.algorithm.search_strategy === "pilot_reference" && "rrt_goal_bias" in (edit.algorithmDefaults.pilot as Record<string, unknown> ?? {}) && <label><input type="checkbox" checked={edit.rrtEnabled}
            onChange={(event) => update(edit.toggleRrt(event.target.checked))} />RRT 初始化（实验选项，默认关闭）</label>}
          {edit.algorithm.search_strategy === "pilot_reference" && "initialization_mode" in edit.pilotParameters && <>
            <label>初始化模式<select value={String(edit.pilotParameters.initialization_mode)}
              onChange={(event) => update(edit.pilotParameter("initialization_mode", event.target.value))}>
              {edit.algorithmSchema.properties?.pilot?.properties?.initialization_mode?.enum?.map((mode) =>
                <option key={String(mode)} value={String(mode)}>{{ legacy: "原始参考", pruned: "种子删塔", balanced: "删塔并补齐种群", bounded: "补齐并控制上界扩展", hybrid: "PILOT 混合初始化" }[String(mode)] ?? String(mode)}</option>)}
            </select></label>
            {edit.pilotParameters.initialization_mode === "hybrid" && <p className="hud-note">混合初始化使用多尺度 A*；RRT 是否参与由实验开关控制。</p>}
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
            disabled={edit.algorithm.search_strategy === "pilot_reference" && name === "evolution_backend"}
            onChange={(event) => update(edit.algorithmParameter(name, event.target.value))}>
            {edit.algorithmSchema.properties[name].enum?.filter((choice) => !(edit.algorithm.search_strategy === "pilot_reference" && name === "evaluation_backend" && choice === "tensor"))
              .map((choice) => <option key={String(choice)} value={String(choice)}>{name === "search_strategy"
                ? (choice === "pilot_reference" ? "PILOT 迁移参考策略（CPU）" : "当前策略") : String(choice)}</option>)}
          </select> : <input value={String(edit.algorithm[name] ?? "")} disabled={edit.algorithm.search_strategy === "pilot_reference" && name === "devices"}
            onChange={(event) => update(edit.algorithmParameter(name, event.target.value))} />}
        </label>)}</details>
        <button type="button" className="primary" onClick={() => void start()} disabled={!scene?.ready || scene?.read_only === true}>开始选线</button>
      </fieldset>
      {busy && jobId && <button type="button" disabled={job?.status === "cancelling"} onClick={cancel}>
        {job?.status === "cancelling" ? "等待取消完成…" : "取消选线"}</button>}
      {job && <p role="status">{JOB_STATUS_LABEL[job.status]} · {Math.round(job.progress * 100)}% · {job.message}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="hud-note">{notice}</p>}
      <button type="button" disabled={busy} onClick={() => void refreshHistory()}>读取选线历史</button>
      {history.map((item) => <button key={item.id} type="button" disabled={busy} onClick={() => {
        loadHistory(item);
      }}>{item.name}</button>)}
    </aside>;
}
