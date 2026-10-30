import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cancelJob, createJob, fetchArtifactText, getExperiments, getPlugins } from "../api";
import type { ExperimentRecord, SceneRecord } from "../api";
import { shouldPoll } from "../run_status";
import { useJobPolling } from "../use_job_polling";
import { SolutionGeneration } from "../map/solution_generation";
import type { LocalPoint, SiteFrame } from "../map/site_frame";
import { RoutingEdit } from "./routing_edit";
import type { RegionKind } from "./routing_edit";
import { parseRoutingResult } from "./routing_result";
import type { RoutingBundle } from "./routing_result";
import type { RoutingMapState } from "./routing_layer";

type PickingMode = "start" | "end" | RegionKind | null;

export interface RoutingWorkspaceProps {
  active: boolean; scene: SceneRecord | null; scenes: SceneRecord[]; frame: SiteFrame | null;
  onSceneChange: (id: string) => void; onFocus: () => void;
  onLayer: (state: RoutingMapState | null) => void; onBusy: (busy: boolean) => void;
}

export function useRoutingController({ active, scene, frame, onLayer, onBusy }: RoutingWorkspaceProps) {
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

  function beginPick(next: PickingMode) { setDraft([]); setPick(next); }
  function removeRegion(index: number) { update(edit.copy({ regions: edit.regions.filter((_, i) => i !== index) })); }
  function toggleCompared(id: string) { setCompared((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]); }
  function loadHistory(record: ExperimentRecord) {
    generation.current.advance(); void loadExperiment(record).catch((reason) => setError(reason.message));
  }
  function cancel() { if (jobId) void cancelJob(jobId).catch((reason) => setError(reason.message)); }

  return { edit, pick, draft, busy, jobId, job, error: error || pollError, notice, history,
    bundle, resultSummary, front, selected, selectedId, compared, update, beginPick, removeRegion,
    toggleCompared, selectRoute: setSelectedId, start, cancel, finishRegion, refreshHistory, loadHistory };
}

export type RoutingController = ReturnType<typeof useRoutingController>;
