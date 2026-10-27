import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cancelJob, createJob, fetchArtifactText, getExperiments, getPlugins } from "../api";
import type { ExperimentRecord, SceneRecord } from "../api";
import { JOB_STATUS_LABEL, shouldPoll } from "../run_status";
import { useJobPolling } from "../use_job_polling";
import { SolutionGeneration } from "../map/solution_generation";
import type { LocalPoint, SiteFrame } from "../map/site_frame";
import { ROUTING_ALGORITHM_LABELS, ROUTING_FIELD_LABELS, RoutingEdit } from "./routing_edit";
import type { RegionKind, RoutingFields } from "./routing_edit";
import { parseRoutingResult } from "./routing_result";
import type { RoutingBundle } from "./routing_result";
import type { RoutingMapState } from "./routing_layer";
import "./routing.css";

type Pick = "start" | "end" | RegionKind | null;

export function RoutingWorkspace({ active, scene, scenes, frame, onSceneChange, onFocus, onLayer, onBusy }: {
  active: boolean; scene: SceneRecord | null; scenes: SceneRecord[]; frame: SiteFrame | null;
  onSceneChange: (id: string) => void; onFocus: () => void;
  onLayer: (state: RoutingMapState | null) => void; onBusy: (busy: boolean) => void;
}) {
  const [edit, setEdit] = useState(new RoutingEdit());
  const [pick, setPick] = useState<Pick>(null);
  const [draft, setDraft] = useState<LocalPoint[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [history, setHistory] = useState<ExperimentRecord[]>([]);
  const [bundle, setBundle] = useState<RoutingBundle | null>(null);
  const [resultTask, setResultTask] = useState<Record<string, unknown> | null>(null);
  const [resultSummary, setResultSummary] = useState<Record<string, unknown> | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [compared, setCompared] = useState<string[]>([]);
  const defaults = useRef<Parameters<RoutingEdit["defaults"]>[0] | null>(null);
  const generation = useRef(new SolutionGeneration());
  const importedJob = useRef<string | null>(null);
  const { job, error: pollError, missing } = useJobPolling(jobId);
  const busy = starting || (!!jobId && (!job || shouldPoll(job.status)));
  useEffect(() => { onBusy(busy); }, [busy, onBusy]);
  useEffect(() => {
    if (!missing || !scene) return;
    const key = `routing-job:${scene.id}`;
    if (sessionStorage.getItem(key) !== jobId) return;
    sessionStorage.removeItem(key); setJobId(null);
    setError("任务记录已失效（服务可能已重启），请读取选线历史或重新运行。");
  }, [missing, jobId, scene?.id]);

  useEffect(() => {
    let stopped = false;
    void getPlugins().then((catalog) => {
      const schema = catalog.items.find((item) => item.id === "routing.nsga2")?.config_schema;
      if (!schema) throw new Error("后端尚未提供选线插件，请更新后端。");
      if (!stopped) { defaults.current = schema; setEdit((current) => current.defaults(schema)); }
    }).catch((reason) => { if (!stopped) setError(String(reason.message ?? reason)); });
    return () => { stopped = true; };
  }, []);

  useEffect(() => {
    generation.current.advance(); importedJob.current = null;
    setBundle(null); setResultTask(null); setResultSummary(null); setSelectedId(null); setCompared([]); setDraft([]); setPick(null); setError("");
    setHistory([]); setNotice("");
    const next = new RoutingEdit(); setEdit(defaults.current ? next.defaults(defaults.current) : next);
    setJobId(scene ? sessionStorage.getItem(`routing-job:${scene.id}`) : null);
  }, [scene?.id]);

  const update = useCallback((next: RoutingEdit) => {
    generation.current.advance(); setEdit(next); setError("");
  }, []);
  const onPick = useCallback((point: LocalPoint) => {
    if (!frame || busy || !pick) return;
    if (!frame.inside(point)) { setError("请在当前场景范围内点选。"); return; }
    if (pick === "start" || pick === "end") { update(edit.picked(pick, point, frame)); setPick(null); }
    else setDraft((current) => [...current, point]);
  }, [frame, busy, pick, edit, update]);

  const front = useMemo(() => bundle?.routes.filter((route) => route.is_pareto && route.is_feasible) ?? [], [bundle]);
  const selected = front.find((route) => route.id === selectedId) ?? null;
  const layer = useMemo<RoutingMapState | null>(() => frame ? ({ active, picking: pick !== null,
    start: edit.localPoint("start", frame), end: edit.localPoint("end", frame), regions: edit.regions, draft,
    routes: front.filter((route) => route.id === selectedId || compared.includes(route.id)), selectedId,
    towerRadius: Number(resultTask?.tower_radius_m ?? edit.values.tower_radius_m) || 0,
    onPick, onSelect: setSelectedId }) : null,
  [frame, active, pick, edit, draft, front, selectedId, compared, resultTask, onPick]);
  useEffect(() => { onLayer(layer); }, [layer, onLayer]);

  const loadExperiment = useCallback(async (record: ExperimentRecord) => {
    if (!scene?.frame) throw new Error("当前场景没有有效网格。");
    const token = generation.current.capture();
    const find = (name: string) => record.artifacts.find((item) => item.name === name)?.url;
    const routeUrl = find("routes.json"), configUrl = find("resolved_config.json");
    if (!routeUrl || !configUrl) throw new Error("选线产物不完整。");
    const [routeText, configText] = await Promise.all([fetchArtifactText(routeUrl), fetchArtifactText(configUrl)]);
    if (!generation.current.isCurrent(token)) return;
    const parsed = parseRoutingResult(routeText, scene.id, scene.frame);
    const task = JSON.parse(configText) as Record<string, unknown>;
    setBundle(parsed); setResultTask(task); setResultSummary(record.summary); setCompared([]);
    setSelectedId(parsed.routes.find((item) => item.is_pareto && item.is_feasible)?.id ?? null);
    const loaded = RoutingEdit.fromTask(task);
    setEdit(defaults.current ? loaded.defaults(defaults.current) : loaded);
    setNotice(`已读取 ${record.name}；所有指标来自本次保存结果，净空未校核。`);
  }, [scene?.id, scene?.frame]);

  useEffect(() => {
    if (!job || job.job_id !== jobId || job.config.scene_name !== scene?.id || importedJob.current === job.job_id) return;
    if (job.status === "succeeded") {
      importedJob.current = job.job_id;
      const token = generation.current.capture();
      void getExperiments().then(async (records) => {
        if (!generation.current.isCurrent(token)) return;
        const data = job.result?.data as { experiment_id?: string } | undefined;
        const record = records.find((item) => item.id === data?.experiment_id);
        if (!record) throw new Error("任务完成，但尚未找到实验产物；可从选线历史重新读取。");
        await loadExperiment(record);
      }).catch((reason) => { if (generation.current.isCurrent(token)) setError(reason.message); });
    } else if (job.status === "failed") setError(String(job.error?.message ?? "选线任务失败"));
  }, [job, jobId, scene?.id, loadExperiment]);

  async function start() {
    if (!scene?.ready || scene.read_only || !frame || busy) return;
    const token = generation.current.advance();
    setError(""); setStarting(true); setPick(null); setDraft([]);
    try {
      const task = edit.task(scene.id, `routing-${Date.now()}`, frame);
      const created = await createJob({ plugin_id: "routing.nsga2", config: task });
      if (!generation.current.isCurrent(token)) return;
      importedJob.current = null; setJobId(created.job_id);
      sessionStorage.setItem(`routing-job:${scene.id}`, created.job_id);
      setNotice("选线已提交；运行期间接入点与约束固定。");
    } catch (reason) { if (generation.current.isCurrent(token)) setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setStarting(false); }
  }

  function finishRegion() {
    if (pick !== "no_tower" && pick !== "no_cross") return;
    if (draft.length < 3) { setError("区域至少需要三个点。"); return; }
    update(edit.copy({ regions: [...edit.regions, { kind: pick, points: draft }] })); setDraft([]); setPick(null);
  }

  async function refreshHistory() {
    const token = generation.current.capture();
    try {
      const records = await getExperiments();
      if (!generation.current.isCurrent(token)) return;
      setHistory(records.filter((item) => item.summary.problem_type === "routing" && item.summary.scene_name === scene?.id));
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }

  return <div style={{ display: active ? "contents" : "none" }}>
    <aside className="hud-panel routing-controls" aria-label="选线配置">
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
          <button type="button" aria-pressed={pick === which} onClick={() => { setDraft([]); setPick(which); }}>地图点选{which === "start" ? "起点" : "终点"}</button>
        </section>)}
        {(Object.keys(ROUTING_FIELD_LABELS) as RoutingFields[]).map((name) => <label key={name}>{ROUTING_FIELD_LABELS[name]}
          <input aria-label={ROUTING_FIELD_LABELS[name]} value={edit.values[name]} onChange={(event) => update(edit.copy({ values: { ...edit.values, [name]: event.target.value } }))} />
        </label>)}
        <p className="hud-note">道路控制距离同时影响塔基避让与跨越长度。</p>
        <div className="hud-actions"><button type="button" onClick={() => { setPick("no_tower"); setDraft([]); }}>绘制禁落塔区域</button>
          <button type="button" onClick={() => { setPick("no_cross"); setDraft([]); }}>绘制禁跨越区域</button></div>
        {pick && <p role="status">{pick === "start" || pick === "end" ? "请在地图范围内点选接入点。" : `请点选多边形顶点，当前 ${draft.length} 个点。`}</p>}
        {draft.length > 0 && <button type="button" onClick={finishRegion}>完成区域</button>}
        {pick && <button type="button" onClick={() => { setPick(null); setDraft([]); }}>取消点选</button>}
        {edit.regions.map((region, index) => <div key={index} className="routing-region-row">
          <span>{region.kind === "no_cross" ? "禁跨越" : "禁落塔"}区域 {index + 1}</span>
          <button type="button" onClick={() => update(edit.copy({ regions: edit.regions.filter((_, i) => i !== index) }))}>删除</button>
        </div>)}
        {edit.generationLimit !== null && <p className="hud-note" aria-label="选线计算预算">
          评价预算 {String(edit.algorithm.max_evaluations)} 次，每代最多 {String(edit.algorithm.popsize)} 个候选，演化最多 {edit.generationLimit} 代。初始化、内部试探及局部/全局搜索共用评价预算，实际代数可能更少。
        </p>}
        <details><summary>算法参数</summary>
          <button type="button" onClick={() => update(edit.resetAlgorithm())}>恢复当前算法默认参数</button>
          {edit.algorithm.search_strategy === "pilot_reference" && <p className="hud-note">CPU 迁移参考策略；启用机制以本次配置为准，尚未启用的机制不会参与搜索。</p>}
          {edit.algorithm.search_strategy === "pilot_reference" && "rrt_goal_bias" in (edit.algorithmDefaults.pilot as Record<string, unknown> ?? {}) && <label><input type="checkbox" checked={edit.rrtEnabled}
            onChange={(event) => update(edit.toggleRrt(event.target.checked))} />RRT 初始化（实验选项，默认关闭）</label>}
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
      {busy && jobId && <button type="button" disabled={job?.status === "cancelling"} onClick={() => void cancelJob(jobId).catch((reason) => setError(reason.message))}>
        {job?.status === "cancelling" ? "等待取消完成…" : "取消选线"}</button>}
      {job && <p role="status">{JOB_STATUS_LABEL[job.status]} · {Math.round(job.progress * 100)}% · {job.message}</p>}
      {(error || pollError) && <p className="error" role="alert">{error || pollError}</p>}
      {notice && <p className="hud-note">{notice}</p>}
      <button type="button" disabled={busy} onClick={() => void refreshHistory()}>读取选线历史</button>
      {history.map((item) => <button key={item.id} type="button" disabled={busy} onClick={() => {
        generation.current.advance(); void loadExperiment(item).catch((reason) => setError(reason.message));
      }}>{item.name}</button>)}
    </aside>
    {bundle && <section className="routing-results" aria-label="选线结果">
      <h2>选线方案 · {front.length} 个可行 Pareto 方案</h2><p>净空未校核；指标为保存时的结果。勾选方案可叠加对比。</p>
      {typeof resultSummary?.generation_count === "number" && <p aria-label="选线实际预算">
        实际完成 {resultSummary.generation_count} 代，搜索评价 {String(resultSummary.evaluation_count)} 次（其中初始化 {String(resultSummary.initialization_evaluations)} 次）。
      </p>}
      <table><thead><tr><th>对比</th><th>方案</th><th>新增塔</th><th>三维长度 m</th><th>水平曲折 °</th><th>跨越 m</th></tr></thead>
        <tbody>{front.map((route, index) => <tr key={route.id} aria-selected={route.id === selectedId}>
          <td><input type="checkbox" aria-label={`对比线路 ${index + 1}`} checked={compared.includes(route.id)} onChange={() => setCompared((current) => current.includes(route.id) ? current.filter((id) => id !== route.id) : [...current, route.id])} /></td>
          <td><button type="button" onClick={() => setSelectedId(route.id)}>线路 {index + 1}</button></td>
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
    </section>}
  </div>;
}
