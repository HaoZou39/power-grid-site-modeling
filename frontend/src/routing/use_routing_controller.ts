import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cancelJob, createJob, fetchArtifactText, getExperiments, getPlugins } from "../api";
import type { ExperimentRecord, SceneRecord } from "../api";
import { shouldPoll } from "../run_status";
import { useJobPolling } from "../use_job_polling";
import { SolutionGeneration } from "../map/solution_generation";
import type { LocalPoint, SiteFrame } from "../map/site_frame";
import { RoutingEdit } from "./routing_edit";
import type { RoutingRegion } from "./routing_edit";
import { rectangleCorners } from "../map/site_edit";
import { routingBox, routingLoop, routingRectangle, routingRegionKind, routingStroke } from "./routing_interaction";
import type { RoutingTool } from "./routing_interaction";
import { readRoutingExperiment } from "./routing_experiment";
import type { RoutingBundle } from "./routing_result";
import type { RoutingInspection, RoutingMapState } from "./routing_layer";

type PickingMode = RoutingTool | null;

export interface RoutingWorkspaceProps {
  active: boolean; scene: SceneRecord | null; scenes: SceneRecord[]; frame: SiteFrame | null;
  onSceneChange: (id: string) => void; onFocus: () => void;
  onLayer: (state: RoutingMapState | null) => void; onBusy: (busy: boolean) => void;
  onBeginPick: () => void;
  onRegionErased: () => void;
  landuseBlocked: boolean;
  externalBusy: boolean;
}

export function useRoutingController({ active, scene, frame, onLayer, onBusy, onBeginPick, onRegionErased, landuseBlocked, externalBusy }: RoutingWorkspaceProps) {
  const [edit, setEdit] = useState(new RoutingEdit());
  const [pick, setPick] = useState<PickingMode>(null);
  const [draft, setDraft] = useState<LocalPoint[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [history, setHistory] = useState<ExperimentRecord[]>([]);
  const [bundle, setBundle] = useState<RoutingBundle | null>(null);
  const [resultTask, setResultTask] = useState<Record<string, unknown> | null>(null);
  const [resultSummary, setResultSummary] = useState<Record<string, unknown> | null>(null);
  const [resultStale, setResultStale] = useState(false);
  const [loadedExperimentId, setLoadedExperimentId] = useState<string | null>(null);
  const [regionVisibility, setRegionVisibility] = useState({ no_tower: true, no_cross: true });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [inspection, setInspection] = useState<RoutingInspection | null>(null);
  const [compared, setCompared] = useState<string[]>([]);
  const defaults = useRef<Parameters<RoutingEdit["defaults"]>[0] | null>(null);
  const generation = useRef(new SolutionGeneration());
  const historyGeneration = useRef(new SolutionGeneration());
  const importedJob = useRef<string | null>(null);
  const boxAnchor = useRef<LocalPoint | null>(null);
  const erasedRegion = useRef<{ index: number; region: RoutingRegion } | null>(null);
  const { job, error: pollError, missing } = useJobPolling(jobId);
  const routingBusy = starting || (!!jobId && (!job || shouldPoll(job.status)));
  const busy = externalBusy || routingBusy;
  useEffect(() => { onBusy(routingBusy); }, [routingBusy, onBusy]);
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
    generation.current.advance(); historyGeneration.current.advance(); importedJob.current = null;
    setBundle(null); setResultTask(null); setResultSummary(null); setResultStale(false); setLoadedExperimentId(null); setRegionVisibility({ no_tower: true, no_cross: true }); setSelectedId(null); setInspection(null); setCompared([]); setDraft([]); setPick(null); setError("");
    boxAnchor.current = null;
    erasedRegion.current = null;
    setHistory([]); setNotice(""); setStarting(false);
    const next = new RoutingEdit(); setEdit(defaults.current ? next.defaults(defaults.current) : next);
    setJobId(scene ? sessionStorage.getItem(`routing-job:${scene.id}`) : null);
  }, [scene?.id]);
  useEffect(() => () => {
    generation.current.advance();
    historyGeneration.current.advance();
  }, []);

  const update = useCallback((next: RoutingEdit) => {
    generation.current.advance(); setEdit(next); setError("");
    if (bundle) setResultStale(true);
  }, [bundle]);
  const onPick = useCallback((point: LocalPoint) => {
    if (!frame || busy || (pick !== "start" && pick !== "end")) return;
    if (!frame.inside(point)) { setError("请在当前场景范围内点选。"); return; }
    update(edit.picked(pick, point, frame)); setPick(null);
  }, [frame, busy, pick, edit, update]);

  const onMoveEndpoint = useCallback((which: "start" | "end", point: LocalPoint) => {
    if (!frame || busy || pick !== "adjust-endpoints" || !frame.inside(point)) return;
    update(edit.picked(which, point, frame));
  }, [frame, busy, pick, edit, update]);

  const onPreviewStroke = useCallback((points: LocalPoint[]) => { setDraft(points); }, []);
  const onFinishStroke = useCallback((points: LocalPoint[]) => {
    const kind = routingRegionKind(pick);
    if (!kind || !routingLoop(pick) || busy) return;
    try {
      const ring = routingStroke(points);
      update(edit.copy({ regions: [...edit.regions, { kind, points: ring }] }));
      setNotice("区域已创建。");
    } catch (reason) { setNotice(""); setError(reason instanceof Error ? reason.message : String(reason)); }
    setDraft([]);
  }, [pick, busy, edit, update]);
  const onBoxClick = useCallback((point: LocalPoint) => {
    const kind = routingRegionKind(pick);
    if (!kind || !routingBox(pick) || !frame || busy) return;
    if (!frame.inside(point)) { setError("请在当前场景范围内绘制。"); return; }
    if (!boxAnchor.current) { boxAnchor.current = point; setDraft([point]); setNotice("已确定第一个角点，请单击对角点完成方框。"); return; }
    try {
      const ring = routingRectangle(boxAnchor.current, point);
      update(edit.copy({ regions: [...edit.regions, { kind, points: ring }] }));
      boxAnchor.current = null; setDraft([]); setNotice("区域已创建。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }, [pick, frame, busy, edit, update]);
  const onBoxMove = useCallback((point: LocalPoint) => {
    if (!frame || !frame.inside(point) || !boxAnchor.current || !routingBox(pick)) return;
    const ring = rectangleCorners(boxAnchor.current, point);
    setDraft([...ring, ring[0]]);
  }, [frame, pick]);
  const removeRegion = useCallback((index: number) => {
    const region = edit.regions[index];
    if (busy || !region) return;
    erasedRegion.current = { index, region };
    onRegionErased();
    update(edit.copy({ regions: edit.regions.filter((_, i) => i !== index) }));
    setNotice("已擦除区域，按 Ctrl+Z 可以恢复。");
  }, [busy, edit, update, onRegionErased]);

  function undoRegionErase(): boolean {
    const erased = erasedRegion.current;
    if (busy || !erased) return false;
    const regions = [...edit.regions];
    regions.splice(Math.min(erased.index, regions.length), 0, erased.region);
    erasedRegion.current = null;
    update(edit.copy({ regions }));
    setNotice("已恢复刚刚擦除的区域。");
    return true;
  }

  const front = useMemo(() => bundle?.routes.filter((route) => route.is_pareto && route.is_feasible) ?? [], [bundle]);
  const selected = front.find((route) => route.id === selectedId) ?? null;
  const selectRoute = useCallback((id: string, target: RoutingInspection = { kind: "route" }) => {
    setSelectedId(id);
    setInspection(target);
  }, []);
  const layer = useMemo<RoutingMapState | null>(() => frame ? ({ active, picking: pick !== null, mode: pick,
    start: edit.localPoint("start", frame), end: edit.localPoint("end", frame), regions: edit.regions.map((region, index) => ({ ...region, index })).filter((region) => regionVisibility[region.kind]), draft,
    routes: front.filter((route) => route.id === selectedId || compared.includes(route.id)), selectedId,
    routeNumbers: Object.fromEntries(front.map((route, index) => [route.id, index + 1])), resultStale,
    towerRadius: Number(resultTask?.tower_radius_m ?? edit.values.tower_radius_m) || 0,
    onPick, onPreviewStroke, onFinishStroke, onBoxClick, onBoxMove, onMoveEndpoint, onEraseRegion: removeRegion, onSelect: selectRoute }) : null,
  [frame, active, pick, edit, regionVisibility, draft, front, selectedId, compared, resultTask, resultStale, onPick, onPreviewStroke, onFinishStroke, onBoxClick, onBoxMove, onMoveEndpoint, removeRegion, selectRoute]);
  useEffect(() => { onLayer(layer); }, [layer, onLayer]);

  const loadExperiment = useCallback(async (record: ExperimentRecord) => {
    if (!scene) throw new Error("当前场景没有有效网格。");
    const token = generation.current.capture();
    const { bundle: parsed, task, edit: loaded } = await readRoutingExperiment(record, scene, fetchArtifactText);
    if (!generation.current.isCurrent(token)) return;
    const restored = defaults.current ? loaded.defaults(defaults.current) : loaded;
    erasedRegion.current = null;
    setBundle(parsed); setResultTask(task); setResultSummary(record.summary); setResultStale(false); setInspection(null); setCompared([]);
    setLoadedExperimentId(record.id);
    setSelectedId(parsed.routes.find((item) => item.is_pareto && item.is_feasible)?.id ?? null);
    setEdit(restored);
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
    } else if (job.status === "failed") {
      setNotice("");
      setError(String(job.error?.message ?? "选线任务失败"));
    }
  }, [job, jobId, scene?.id, loadExperiment]);

  async function start() {
    if (!scene?.ready || scene.read_only || !frame || busy) return;
    if (landuseBlocked) { setError("请先保存或放弃土地类型修改，再开始选线。"); return; }
    const token = generation.current.advance();
    onBeginPick();
    setError(""); setNotice(""); setJobId(null); sessionStorage.removeItem(`routing-job:${scene.id}`);
    setStarting(true); setPick(null); setDraft([]); boxAnchor.current = null;
    try {
      const task = edit.task(scene.id, `routing-${Date.now()}`, frame);
      const created = await createJob({ plugin_id: "routing.nsga2", config: task });
      if (!generation.current.isCurrent(token)) return;
      importedJob.current = null; setJobId(created.job_id);
      sessionStorage.setItem(`routing-job:${scene.id}`, created.job_id);
      setNotice("选线已提交；运行期间接入点与约束固定。");
    } catch (reason) { if (generation.current.isCurrent(token)) setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { if (generation.current.isCurrent(token)) setStarting(false); }
  }

  async function refreshHistory() {
    const token = generation.current.capture();
    const historyToken = historyGeneration.current.advance();
    try {
      const records = await getExperiments();
      if (!generation.current.isCurrent(token) || !historyGeneration.current.isCurrent(historyToken)) return;
      setHistory(records.filter((item) => item.summary.problem_type === "routing" && item.summary.scene_name === scene?.id));
    } catch (reason) {
      if (generation.current.isCurrent(token) && historyGeneration.current.isCurrent(historyToken)) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    }
  }

  function beginPick(next: PickingMode) {
    if (next) onBeginPick();
    const kind = routingRegionKind(next);
    if (kind) setRegionVisibility((current) => ({ ...current, [kind]: true }));
    boxAnchor.current = null;
    setDraft([]); setPick(next);
  }
  function clearRoutes() {
    if (busy) return;
    generation.current.advance();
    setBundle(null); setResultTask(null); setResultSummary(null); setResultStale(false); setLoadedExperimentId(null); setSelectedId(null); setInspection(null); setCompared([]);
    setNotice("已清空当前线路，历史选线结果已保留。");
  }
  function toggleCompared(id: string) { setCompared((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]); }
  function loadHistory(record: ExperimentRecord) {
    const token = generation.current.advance();
    void loadExperiment(record).catch((reason) => {
      if (generation.current.isCurrent(token)) setError(reason instanceof Error ? reason.message : String(reason));
    });
  }
  function cancel() {
    const token = generation.current.capture();
    if (jobId) void cancelJob(jobId).catch((reason) => {
      if (generation.current.isCurrent(token)) setError(reason instanceof Error ? reason.message : String(reason));
    });
  }

  return { edit, pick, draft, busy, jobId, job, error: error || pollError, notice, history,
    bundle, resultTask, resultSummary, resultStale, loadedExperimentId, regionVisibility, setRegionVisibility, front, selected, selectedId, compared, update, beginPick, removeRegion, undoRegionErase,
    toggleCompared, selectRoute, inspection, closeInspection: () => setInspection(null), layer, start, cancel, refreshHistory, loadHistory, clearRoutes };
}

export type RoutingController = ReturnType<typeof useRoutingController>;
