import { useEffect, useRef, useState } from "react";
import { cancelJob, createJob, deleteExperiment, fetchArtifactText, fetchPoseObjectives, fetchSiteReport, getExperiments, getJob, getScenes, pickLandusePatch } from "../api";
import type { ExperimentRecord, JobRecord, SceneRecord, SiteReport } from "../api";
import { JOB_STATUS_LABEL, messageLabel } from "../run_status";
import { WorldMap } from "./world_map";
import { BuildingFootprint } from "./building_footprint";
import {
  BuildingSize,
  JobFollowUp,
  GuidedDecisionRun,
  buildingSizeFromResolvedConfig,
  compareChart,
  comparedFields,
  measuredChoice,
  refineSquare,
  refinedChoices,
  schemeCard,
  unmeasured,
} from "./decision_run";
import type { StatusRow } from "./decision_run";
import type { ParetoChoice } from "./decision_run";
import { SiteEdit, rectangleCorners } from "./site_edit";
import type { FieldPolicy, RegionKind } from "./site_edit";
import { ExclusionZone } from "./exclusion_sketch";
import { emptyAgentPreview } from "./site_overlay";
import { AgentPanel } from "../agent/agent_panel";
import type { AskPose } from "../agent/agent_panel";
import { recordPreferenceChoice } from "../agent/agent_api";
import { preferenceChoice, toSnapshot } from "../agent/workspace_snapshot";
import { applyOps, proposalPreview } from "../agent/edit_ops";
import type { EditOp } from "../agent/edit_ops";
import type { LocalPoint } from "./site_frame";
import { HistoryPanel } from "./history_panel";
import { MapToolbar } from "./map_toolbar";
import { LANDUSE_CLASSES, hiddenLanduseClasses, regionKind } from "./toolbar_commands";
import type { MapToolName } from "./toolbar_commands";
import { MapShortcuts } from "./map_shortcuts";
import type { MapCommands } from "./map_shortcuts";

const PREPARE_PLUGIN = "site.prepare_scene";
const DEFAULT_SCENE = "cangnan";

/** Decision map. Scene data is prepared once. Optimization only reads that scene. */
export function MapWorkspace({ health }: { health: string }) {
  const [tool, setTool] = useState<MapToolName>("pan");
  const boxAnchor = useRef<LocalPoint | null>(null);
  const [adjusting, setAdjusting] = useState(false);
  const [edit, setEdit] = useState(() => new SiteEdit<ParetoChoice>());
  const editRef = useRef(edit);
  editRef.current = edit;
  const [notice, setNoticeText] = useState("");
  const [noticeToken, setNoticeToken] = useState(0);
  const [noticeFading, setNoticeFading] = useState(false);
  function setNotice(message: string) {
    setNoticeFading(false);
    setNoticeText(message);
    setNoticeToken((token) => token + 1);
  }
  const [rectW, setRectW] = useState("77");
  const [rectH, setRectH] = useState("51.5");
  const [job, setJob] = useState<JobRecord | null>(null);
  const [focusToken, setFocusToken] = useState(0);
  const [scene, setScene] = useState<SceneRecord | null>(null);
  const [shownClasses, setShownClasses] = useState(hiddenLanduseClasses);
  const [fieldCost, setFieldCost] = useState("0.5");
  const [report, setReport] = useState<SiteReport | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);
  const [askPose, setAskPose] = useState<AskPose | null>(null);
  const [previewOps, setPreviewOps] = useState<readonly EditOp[] | null>(null);
  const [panelMinimized, setPanelMinimized] = useState(false);
  const [history, setHistory] = useState<ExperimentRecord[] | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [loadedCaseId, setLoadedCaseId] = useState<string | null>(null);
  const [schemeAnchor, setSchemeAnchor] = useState<{ x: number; y: number } | null>(null);
  const [closedCardId, setClosedCardId] = useState<string | null>(null);
  const [comparedIds, setComparedIds] = useState<string[]>([]);
  const run = useRef(new GuidedDecisionRun({ getExperiments, fetchArtifactText }));
  const followUp = useRef(new JobFollowUp());
  // A local re-search adds its picks next to this scheme instead of replacing the map.
  const refining = useRef<{ jobId: string; origin: ParetoChoice; hasOrigin: boolean; includeDemand: boolean } | null>(null);
  const dragStart = useRef<{ id: string; x: number; y: number } | null>(null);
  const commands = useRef<MapCommands>(idleCommands);

  const selected = edit.selected;
  const origin = edit.origin;
  const liveReport = report ? {
    offroadHaulM: report.offroad_haul_m,
    haulRiseM: report.haul_rise_m,
    accessSlopeDeg: report.access_slope_deg,
    accessWarning: report.access_warning,
    roadHaulM: report.road_haul_m,
  } : null;
  const compared = comparedIds.flatMap((id) => {
    const index = edit.poses.findIndex((pose) => pose.id === id);
    const pose = edit.poses[index];
    if (!pose) return [];
    return [{ id, name: `方案 ${index + 1}`, choice: pose, colorIndex: index }];
  });
  const running = job !== null && JobFollowUp.isActive(job.status);
  const preparing = running && job?.plugin_id === PREPARE_PLUGIN;
  const sceneReady = scene?.ready === true;

  useEffect(() => {
    if (!notice) {
      setNoticeFading(false);
      return;
    }
    setNoticeFading(false);
    const fade = window.setTimeout(() => setNoticeFading(true), 4500);
    const clear = window.setTimeout(() => setNoticeText(""), 5400);
    return () => {
      window.clearTimeout(fade);
      window.clearTimeout(clear);
    };
  }, [noticeToken]);

  async function refreshScene() {
    const scenes = await getScenes();
    setScene(scenes.find((item) => item.id === DEFAULT_SCENE) ?? scenes[0] ?? null);
  }

  function activeKind(): RegionKind {
    const kind = regionKind(tool);
    if (!kind) throw new Error("当前工具不能画范围。");
    return kind;
  }

  function selectTool(next: MapToolName) {
    if (next !== tool) {
      boxAnchor.current = null;
      setEdit((current) => current.draft.length > 0 ? current.cancelDraft() : current);
    }
    setTool(next);
  }

  function clickBox(point: LocalPoint) {
    const kind = activeKind();
    const kindLabel = kind === "feasible" ? "可行域" : "禁区";
    const anchor = boxAnchor.current;
    if (!anchor) {
      boxAnchor.current = point;
      setEdit((current) => current.replaceDraft([point]));
      setNotice(`已记下左上角。再点对角线的右下角，这块方框记为${kindLabel}。`);
      return;
    }
    try {
      setEdit(editRef.current.addRectangle(kind, anchor, point));
      boxAnchor.current = null;
      setNotice("");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法画方框");
    }
  }

  function previewBox(point: LocalPoint) {
    const anchor = boxAnchor.current;
    if (!anchor) return;
    const ring = rectangleCorners(anchor, point);
    setEdit((current) => current.replaceDraft([...ring, ring[0]]));
  }

  function addDraftPoint(point: LocalPoint) {
    setEdit((current) => current.addDraftPoint(point, activeKind()));
    setNotice("");
  }

  function previewStroke(points: LocalPoint[]) {
    setEdit((current) => current.replaceDraft(points));
  }

  function finishStroke(points: LocalPoint[]) {
    try {
      setEdit(editRef.current.finishStroke(points, activeKind()));
      setNotice("");
    } catch (reason) {
      setEdit(editRef.current.cancelDraft());
      setNotice(reason instanceof Error ? reason.message : "无法闭合禁行区");
    }
  }

  async function pickPatch(point: LocalPoint) {
    if (!scene) {
      setNotice("场景还没有准备好，不能点选用地。");
      return;
    }
    try {
      const patch = await pickLandusePatch(scene.id, point.x, point.y);
      const points = patch.points.map(([x, y]) => ({ x, y }));
      setEdit(editRef.current.addExclusion(points));
      setNotice(`已标出 ${patch.cell_count} 个同类格子。`);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法标出这块用地");
    }
  }

  function closeDraft() {
    try {
      setEdit(editRef.current.closeDraft(activeKind()));
      setTool("pan");
      setNotice("");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法闭合禁行区");
    }
  }

  async function prepareScene() {
    if (running) return;
    setNotice("");
    setEdit((current) => current.clearPoses());
    setComparedIds([]);
    setClosedCardId(null);
    setLoadedCaseId(null);
    try {
      setJob(await createJob({ plugin_id: PREPARE_PLUGIN, config: { scene_name: scene?.id ?? DEFAULT_SCENE } }));
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法构建场景数据");
    }
  }

  async function stopPrepare() {
    if (!job || job.plugin_id !== PREPARE_PLUGIN) return;
    try {
      setJob(await cancelJob(job.job_id));
      setNotice("构建已终止。正在进行的这一步结束后不再继续。");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法终止构建");
    }
  }

  async function toggleHistory() {
    if (historyOpen) {
      setHistoryOpen(false);
      setPendingDeleteId(null);
      return;
    }
    setHistoryOpen(true);
    setHistoryError("");
    setPendingDeleteId(null);
    try {
      setHistory(await getExperiments());
    } catch (reason) {
      setHistory(null);
      setHistoryError(reason instanceof Error ? reason.message : "无法读取历史结果");
    }
  }

  async function importHistory(experimentId: string) {
    if (running) {
      setNotice("优化进行中，结束后再导入历史结果。");
      return;
    }
    try {
      const experiments = history ?? await getExperiments();
      const experiment = experiments.find((item) => item.id === experimentId);
      const choices = await run.current.loadPareto(experimentId);
      const size = await importedBuildingSize(experiment);
      setEdit((current) => {
        const sized = size ? current.withBuilding(size.widthM, size.heightM) : current;
        return sized.withPoses(choices);
      });
      if (size) {
        setRectW(String(size.widthM));
        setRectH(String(size.heightM));
      }
      setComparedIds([]);
      setClosedCardId(null);
      setLoadedCaseId(experimentId);
      setFocusToken((token) => token + 1);
      setHistoryOpen(false);
      setNotice(`已导入 ${experimentId}，共 ${choices.length} 个可行帕累托方案。`);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法导入这次结果");
    }
  }

  async function confirmDeleteHistory(experimentId: string) {
    const activeName = running ? String(job?.config.experiment_name ?? "") : "";
    if (activeName && activeName === experimentId) {
      setPendingDeleteId(null);
      setNotice("这次优化还在写入该目录，结束后才能删除。");
      return;
    }
    try {
      await deleteExperiment(experimentId);
      setHistory((current) => current?.filter((item) => item.id !== experimentId) ?? null);
      setPendingDeleteId(null);
      if (loadedCaseId === experimentId) {
        setEdit((current) => current.clearPoses());
        setComparedIds([]);
        setClosedCardId(null);
        setLoadedCaseId(null);
      }
      setNotice(`已删除 ${experimentId}。`);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法删除这次结果");
    }
  }

  async function submitSearch(current: SiteEdit<ParetoChoice>) {
    if (running) {
      setNotice("优化还在进行，这次没有重新开始。");
      return;
    }
    if (!sceneReady) {
      setNotice("请先完成场景数据构建。优化不会在搜索时重新生成 DEM、道路和需求点。");
      return;
    }
    // The previous schemes stay on the map until the new ones load, so a failed run leaves them in place.
    const submitted = current.withScene(scene?.id ?? DEFAULT_SCENE);
    setNotice("");
    setEdit(submitted);
    setRectW(String(submitted.widthM));
    setRectH(String(submitted.heightM));
    setFieldCost(String(submitted.fieldCost));
    refining.current = null;
    setJob(await createJob(run.current.createRequest(submitted, new Date())));
  }

  async function submitRefine(current: SiteEdit<ParetoChoice>, poseId: string, halfWidthM: number) {
    if (running) {
      setNotice("优化还在进行，这次没有开始局部优化。");
      return;
    }
    const pose = current.poses.find((item) => item.id === poseId);
    if (!pose || !sceneReady) return;
    const submitted = current.withScene(scene?.id ?? DEFAULT_SCENE);
    const record = await createJob(run.current.createRefineRequest(submitted, pose, halfWidthM, new Date()));
    refining.current = {
      jobId: record.job_id,
      origin: pose,
      hasOrigin: submitted.origin !== null,
      includeDemand: submitted.includeDemand,
    };
    setNotice(`正在方案 ${current.poses.indexOf(pose) + 1} 周围局部优化，原方案保留。`);
    setJob(record);
  }

  /** Recompute moved schemes with the search's own objectives. A scheme moved again meanwhile keeps waiting. */
  async function remeasure(current: SiteEdit<ParetoChoice>, ids: readonly string[]) {
    const poses = current.poses.filter((pose) => ids.includes(pose.id));
    if (!scene || poses.length === 0) return;
    const { scene_name: _scene, ...config } = current.searchConfig();
    try {
      const { items } = await fetchPoseObjectives(scene.id, {
        ...config,
        poses: poses.map(({ x, y, theta }) => ({ x, y, theta })),
      });
      setEdit((latest) => latest.withPoses(latest.poses.map((pose) => {
        const index = poses.findIndex((item) => item.id === pose.id && item.x === pose.x && item.y === pose.y && item.theta === pose.theta);
        return index < 0 ? pose : measuredChoice(pose, items[index]);
      })));
    } catch (reason) {
      setNotice(`目标值没有重算：${reason instanceof Error ? reason.message : "请求失败"}`);
    }
  }

  function markMoved(current: SiteEdit<ParetoChoice>, ids: readonly string[]): SiteEdit<ParetoChoice> {
    if (ids.length === 0) return current;
    const next = current.withPoses(current.poses.map((pose) => ids.includes(pose.id) ? unmeasured(pose) : pose));
    setEdit(next);
    void remeasure(next, ids);
    return next;
  }

  async function startOptimization() {
    if (running) return;
    try {
      const current = editRef.current;
      const size = BuildingSize.parse(rectW, rectH);
      const cost = current.fieldPolicy === "costly" ? Number(fieldCost) : 0.5;
      if (current.fieldPolicy === "costly" && (!Number.isFinite(cost) || cost <= 0 || cost > 1)) {
        setNotice("农田代价系数必须在 0 到 1 之间。");
        return;
      }
      await submitSearch(
        current.withBuilding(size.widthM, size.heightM).withPolicies("allowed", current.fieldPolicy, cost),
      );
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法开始优化");
    }
  }

  async function confirmAgent(ops: readonly EditOp[]) {
    const before = editRef.current;
    const applied = applyOps(before, ops);
    setRectW(String(applied.edit.widthM));
    setRectH(String(applied.edit.heightM));
    setFieldCost(String(applied.edit.fieldCost));
    const moved = applied.edit.poses.filter((pose) => {
      const old = before.poses.find((item) => item.id === pose.id);
      return old && (old.x !== pose.x || old.y !== pose.y || old.theta !== pose.theta);
    });
    const rescored = JSON.stringify(before.searchConfig()) !== JSON.stringify(applied.edit.searchConfig()) && !applied.runSearch;
    setEdit(applied.edit);
    const edit = markMoved(applied.edit, (rescored ? applied.edit.poses : moved).map((pose) => pose.id));
    try {
      if (applied.runSearch) await submitSearch(edit);
      if (applied.refine) await submitRefine(edit, applied.refine.poseId, applied.refine.halfWidthM);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法开始优化");
    }
  }

  function mergeRefined(
    refine: NonNullable<typeof refining.current>,
    experimentId: string,
    local: ParetoChoice[],
  ) {
    const current = editRef.current;
    const original = current.poses.find((pose) => pose.id === refine.origin.id) ?? refine.origin;
    const fields = comparedFields(refine.hasOrigin, refine.includeDemand);
    const { choices, improved } = refinedChoices(original, local, fields);
    // Local ids restart at 0 in every run, so they are scoped by the run directory.
    const added = choices.map((choice) => ({ ...choice, id: `${experimentId}/${choice.id}`, derivedFrom: original.id }));
    const originIndex = current.poses.findIndex((pose) => pose.id === refine.origin.id);
    const next = current.withPoses([...current.poses, ...added]);
    setEdit(added.length > 0 ? next.selectPose(added[0].id) : next);
    setFocusToken((token) => token + 1);
    const first = current.poses.length + 1;
    const range = added.length > 1 ? `方案 ${first}–${first + added.length - 1}` : `方案 ${first}`;
    if (added.length === 0) setNotice(`局部优化完成：方案 ${originIndex + 1} 附近没有在任何一项目标上更好的点。`);
    else setNotice(improved
      ? `局部优化完成：加入${range}，其中有各项目标都不差于方案 ${originIndex + 1} 的点。`
      : `局部优化完成：附近没有各项都不差于方案 ${originIndex + 1} 的点。加入的${range}各在一项上更好，其余项变差最少。`);
  }

  async function recordChoice(poseId: string, label: string) {
    try {
      const { count } = await recordPreferenceChoice(
        preferenceChoice(toSnapshot(editRef.current, { experimentId: loadedCaseId }), poseId),
      );
      setNotice(`已记下：这次选了${label}，累计 ${count} 次。之后可以让 AI 按以往的选择推荐方案。`);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法记下这次选择");
    }
  }

  commands.current = {
    drawing: regionKind(tool) !== null,
    pan: () => selectTool("pan"),
    draw: () => selectTool("exclusion"),
    focus: () => setFocusToken((token) => token + 1),
    closeDraft,
    cancelDraft: () => {
      boxAnchor.current = null;
      setEdit((current) => current.cancelDraft());
      setTool("pan");
    },
    undoPoint: () => setEdit((current) => current.undoPoint()),
    previous: () => setEdit((current) => current.stepPose(-1)),
    next: () => setEdit((current) => current.stepPose(1)),
    optimize: () => void startOptimization(),
  };

  useEffect(() => {
    if (!job || !JobFollowUp.isActive(job.status)) return;
    let stopped = false;
    const poll = async () => {
      try {
        const record = await getJob(job.job_id);
        if (stopped) return;
        setJob(record);
        const failed = followUp.current.failureNotice(record);
        if (failed) setNotice(failed);
        if (record.plugin_id === PREPARE_PLUGIN) {
          if (followUp.current.opened(record.job_id, record.status)) {
            await refreshScene();
            setNotice("场景数据已更新。之后的优化会直接读取它，不会重新构建。");
          }
          return;
        }
        const experimentId = followUp.current.claimExperiment(record);
        if (!experimentId) return;
        const choices = await run.current.loadPareto(experimentId);
        const refine = refining.current?.jobId === record.job_id ? refining.current : null;
        if (refine) {
          refining.current = null;
          mergeRefined(refine, experimentId, choices);
          return;
        }
        setEdit((current) => current.withPoses(choices));
        setComparedIds([]);
        setClosedCardId(null);
        setLoadedCaseId(experimentId);
        setFocusToken((token) => token + 1);
        setNotice("");
      } catch (reason) {
        if (!stopped) setNotice(reason instanceof Error ? reason.message : "无法读取任务状态");
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [job?.job_id, job?.status]);

  useEffect(() => {
    refreshScene().catch((reason) => {
      setNotice(reason instanceof Error ? reason.message : "无法读取场景");
    });
  }, []);

  useEffect(() => {
    if (!scene || !selected || adjusting) {
      if (!selected) setReport(null);
      return;
    }
    let stopped = false;
    const body = edit.reportRequest();
    if (!body) return;
    fetchSiteReport(scene.id, body)
      .then((value) => {
        if (!stopped) setReport(value);
      })
      .catch(() => {
        if (!stopped) setNotice("这次报告没有更新");
      });
    return () => {
      stopped = true;
    };
  }, [scene?.id, selected, edit.marks, edit.widthM, edit.heightM, adjusting]);

  useEffect(() => {
    const shortcuts = new MapShortcuts(() => commands.current);
    const onKeyDown = (event: KeyboardEvent) => shortcuts.handle(event);
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className={panelMinimized ? "map-app panel-minimized" : "map-app"}>
      <WorldMap
        tool={tool}
        zones={edit.zones}
        draft={edit.draft}
        footprints={BuildingFootprint.layer(edit.poses, { widthM: edit.widthM, heightM: edit.heightM }, edit.selectedIndex)}
        landuseLayers={sceneReady && scene ? LANDUSE_CLASSES.map((item) => ({
          id: item.id,
          url: `/api/v1/scenes/${scene.id}/landuse-overlay/${item.id}`,
          visible: shownClasses[item.id],
        })) : []}
        haulPath={(report?.haul_path ?? []).map(([x, y]) => ({ x, y }))}
        origin={origin}
        preview={agentMapPreview(edit, previewOps)}
        focusToken={focusToken}
        onAddDraftPoint={addDraftPoint}
        onPreviewStroke={previewStroke}
        onFinishStroke={finishStroke}
        onPickPoint={(point) => void pickPatch(point)}
        onPickOrigin={(point) => {
          try {
            setEdit((current) => current.putOrigin(point));
            setNotice(`已标出进货原点 (${point.x.toFixed(0)}, ${point.y.toFixed(0)}) m。这次优化会比较沿路运输。`);
          } catch (reason) {
            setNotice(reason instanceof Error ? reason.message : "无法标出进货原点");
          }
        }}
        onCloseDraft={closeDraft}
        onDrawOutside={() => setNotice("范围只能画在选址范围框内。")}
        onSelectFootprint={(id) => setEdit((current) => current.selectPose(id))}
        onBoxClick={clickBox}
        onBoxMove={previewBox}
        onEraseZone={(id) => {
          if (!id) {
            setNotice("这里没有可擦掉的范围。");
            return;
          }
          setEdit((current) => current.removeRegion(id));
          setNotice("已擦掉这块范围。");
        }}
        onMoveFootprint={(dx, dy) => {
          const pose = editRef.current.selected;
          if (pose && !dragStart.current) dragStart.current = { id: pose.id, x: pose.x, y: pose.y };
          setAdjusting(true);
          setEdit((current) => current.moveSelected(dx, dy));
        }}
        onFinishMove={() => {
          setAdjusting(false);
          const start = dragStart.current;
          dragStart.current = null;
          const pose = start ? editRef.current.poses.find((item) => item.id === start.id) : undefined;
          if (start && pose && (pose.x !== start.x || pose.y !== start.y)) markMoved(editRef.current, [pose.id]);
        }}
        onSchemeAnchor={setSchemeAnchor}
      />
      <header className="hud-top">
        <div>
          <p>温州电力设计院</p>
          <strong>苍南选址规划</strong>
        </div>
        <div className="hud-brand">
          <span className={health.includes("失败") ? "hud-health bad" : "hud-health"}>{health}</span>
          <img className="lab-logo" src="/tgai-logo.png" alt="西湖大学可信及通用人工智能实验室" />
          <img src="/westlake-logo.png" alt="西湖大学" />
        </div>
      </header>
      <MapToolbar
        tool={tool}
        shownClasses={shownClasses}
        notify={setNotice}
        focusSite={() => setFocusToken((token) => token + 1)}
        setTool={selectTool}
        toggleClass={(id) => setShownClasses((current) => ({ ...current, [id]: !current[id] }))}
        hasSelection={selected !== null}
        sceneLabel={preparing ? "终止构建" : sceneReady ? "更新场景数据" : "构建场景数据"}
        sceneDisabled={!preparing && running}
        onPrepare={() => void (preparing ? stopPrepare() : prepareScene())}
        optimizeLabel={running && !preparing ? "正在优化…" : "开始优化"}
        optimizeDisabled={running || !sceneReady}
        onOptimize={() => void startOptimization()}
        historyOpen={historyOpen}
        onImportCase={() => void toggleHistory()}
        agentOpen={agentOpen}
        onToggleAgent={() => {
          setAgentOpen((open) => !open);
          setPreviewOps(null);
        }}
      />
      {agentOpen && (
        <AgentPanel
          edit={edit}
          experimentId={loadedCaseId}
          onApply={confirmAgent}
          onPreview={setPreviewOps}
          ask={askPose}
        />
      )}
      {historyOpen && (
        <HistoryPanel
          experiments={history ?? []}
          loading={history === null && !historyError}
          error={historyError}
          pendingDeleteId={pendingDeleteId}
          onClose={() => {
            setHistoryOpen(false);
            setPendingDeleteId(null);
          }}
          onImport={(experimentId) => void importHistory(experimentId)}
          onAskDelete={setPendingDeleteId}
          onConfirmDelete={(experimentId) => void confirmDeleteHistory(experimentId)}
          onCancelDelete={() => setPendingDeleteId(null)}
        />
      )}
      <aside className={panelMinimized ? "hud-panel minimized" : "hud-panel"}>
        <div className="hud-panel-head">
          <p className="hud-kicker">工作栏</p>
          <button
            type="button"
            className="agent-min"
            aria-label={panelMinimized ? "展开工作栏" : "最小化工作栏"}
            title={panelMinimized ? "展开工作栏" : "最小化工作栏"}
            onClick={() => setPanelMinimized((current) => !current)}
          >
            {panelMinimized ? "▢" : "–"}
          </button>
        </div>
        {!panelMinimized && (
        <>
        <p className="hud-kicker">1. 场景数据</p>
        <p className="hud-note">{scene ? `${scene.title} · ${scene.ready ? "已准备" : "尚未构建"}` : "正在读取场景"}</p>
        <p className="hud-note">选定范围后的 DEM、不可建设区域、道路和需求点在这里构建一次。之后可以再更新，但不会在每次优化时重做。构建和更新用上方「主页」里的按钮。</p>
        <p className="hud-kicker">2. 优化</p>
        <label>变电站长度（m）<input value={rectW} onChange={(event) => setRectW(event.target.value)} /></label>
        <label>变电站宽度（m）<input value={rectH} onChange={(event) => setRectH(event.target.value)} /></label>
        <p className="hud-note">110 kV 变电站默认占地尺寸：长 77 m × 宽 51.5 m，可修改。</p>
        <label className="hud-check">
          <input
            type="checkbox"
            checked={edit.includeDemand}
            onChange={(event) => setEdit((current) => current.withIncludeDemand(event.target.checked))}
          />
          比较需求点距离
        </label>
        <p className="hud-note">需求点目前是随机生成的，默认不参加比较。有真实负荷后再打开。</p>
        <label>农田
          <select value={edit.fieldPolicy} onChange={(event) => setEdit((current) => current.withPolicies("allowed", event.target.value as FieldPolicy, current.fieldCost))}>
            <option value="allowed">按坡度和进场判断</option>
            <option value="blocked">一律不可建设</option>
            <option value="costly">允许建设，计入成本</option>
          </select>
        </label>
        {edit.fieldPolicy === "costly" && (
          <label>农田代价系数<input value={fieldCost} onChange={(event) => setFieldCost(event.target.value)} /></label>
        )}
        <button type="button" className="primary" onClick={() => void startOptimization()} disabled={running || !sceneReady}>
          {running && !preparing ? "正在优化…" : "开始优化 P"}
        </button>
        {job && <p className="hud-note">{JOB_STATUS_LABEL[job.status]} · {messageLabel(job.message)}</p>}
        {origin ? (
          <p className="hud-note">进货原点 ({origin.x.toFixed(0)}, {origin.y.toFixed(0)}) m，地图上的黄点。这次会比较沿路运输。</p>
        ) : (
          <p className="hud-note">未设置进货原点，这次不比较沿路运输。需要时点「进货原点」再在图上点一下。</p>
        )}
        {selected && (
          <p className="hud-note">方案 {edit.selectedIndex + 1}/{edit.poses.length}。点矩形或按 [ ] 切换。要移动时先点「调整方案」。</p>
        )}
        <p className="hud-note">范围 {edit.zones.length} 处，禁区 {edit.zones.filter((zone) => zone.kind === "exclusion").length}，可行域 {edit.zones.filter((zone) => zone.kind === "feasible").length}。禁区和可行域下面都可以选画圈或方框。画圈松手闭合。方框先点一角，再点对角线另一角。橡皮擦点中可删。</p>
        {edit.zones.map((zone) => (
          <button key={zone.id} type="button" className="legend-toggle" onClick={() => setEdit((current) => current.removeRegion(zone.id))}>
            删除 {zone.kind === "feasible" ? "可行域" : "禁区"} {zone.id}
          </button>
        ))}
        <p className="hud-keys">V 拖拽 · B 禁区 · 点选同类单击闭合 · Esc 取消 · F 定位 · [ ] 切换方案 · P 开始优化</p>
        </>
        )}
      </aside>
      {notice && <p className={noticeFading ? "map-toast fading" : "map-toast"} role="status">{notice}</p>}
      {selected && closedCardId !== selected.id && schemeAnchor && (
        <SchemeCard
          title={`方案 ${edit.selectedIndex + 1}/${edit.poses.length}${derivedLabel(edit, selected)}`}
          card={schemeCard(selected, liveReport, origin !== null, edit.includeDemand)}
          anchor={schemeAnchor}
          onClose={() => setClosedCardId(selected.id)}
          onAsk={() => {
            setAskPose({ id: selected.id, label: `方案 ${edit.selectedIndex + 1}/${edit.poses.length}`, nonce: Date.now() });
            setAgentOpen(true);
          }}
          onChoose={() => void recordChoice(selected.id, `方案 ${edit.selectedIndex + 1}`)}
          compared={comparedIds.includes(selected.id)}
          onToggleCompare={() => {
            if (comparedIds.includes(selected.id)) {
              setComparedIds((current) => current.filter((id) => id !== selected.id));
              return;
            }
            if (comparedIds.length >= 5) {
              setNotice("最多同时对比 5 个方案。");
              return;
            }
            setComparedIds((current) => (
              current.includes(selected.id) || current.length >= 5 ? current : [...current, selected.id]
            ));
          }}
        />
      )}
      {compared.length > 0 && (
        <ComparePanel items={compared} scale={edit.poses} includeDemand={edit.includeDemand} onClear={() => setComparedIds([])} />
      )}
    </div>
  );
}

async function importedBuildingSize(experiment: ExperimentRecord | undefined): Promise<BuildingSize | null> {
  const url = experiment?.artifacts.find((item) => item.name === "resolved_config.json")?.url;
  if (!url) return null;
  try {
    return buildingSizeFromResolvedConfig(JSON.parse(await fetchArtifactText(url)));
  } catch {
    return null;
  }
}

function SchemeCard({
  title,
  card,
  anchor,
  compared,
  onToggleCompare,
  onClose,
  onAsk,
  onChoose,
}: {
  title: string;
  card: { decisions: StatusRow[]; objectives: StatusRow[] };
  anchor: { x: number; y: number };
  compared: boolean;
  onToggleCompare: () => void;
  onClose: () => void;
  onAsk: () => void;
  onChoose: () => void;
}) {
  const width = 300;
  const left = Math.min(Math.max(8, anchor.x + 8), window.innerWidth - width - 8);
  const top = Math.min(Math.max(8, anchor.y + 8), Math.max(8, window.innerHeight - 180));
  return (
    <aside className="scheme-card" style={{ left, top }}>
      <div className="scheme-card-head">
        <strong>{title}</strong>
        <button type="button" className="drawer-close" onClick={onClose}>关闭</button>
      </div>
      <p className="hud-kicker">决策变量</p>
      <dl className="hud-metrics">{card.decisions.map((row) => <Metric key={row.label} row={row} />)}</dl>
      <p className="hud-kicker">目标</p>
      <dl className="hud-metrics">{card.objectives.map((row) => <Metric key={row.label} row={row} />)}</dl>
      <div className="hud-actions">
        <button type="button" className="legend-toggle" onClick={onToggleCompare}>{compared ? "移出对比" : "加入对比"}</button>
        <button type="button" className="legend-toggle" onClick={onAsk}>问 AI</button>
        <button type="button" className="legend-toggle" onClick={onChoose}>记为我的选择</button>
      </div>
    </aside>
  );
}

function Metric({ row }: { row: StatusRow }) {
  return <div><dt>{row.label}</dt><dd>{row.value}</dd></div>;
}

const COMPARE_COLORS = ["#39f3ff", "#ff8b96", "#ffd166", "#3dd68c", "#d78bff"];

function ComparePanel({
  items,
  scale,
  includeDemand,
  onClear,
}: {
  items: { id: string; name: string; choice: ParetoChoice; colorIndex: number }[];
  scale: readonly ParetoChoice[];
  includeDemand: boolean;
  onClear: () => void;
}) {
  const chart = compareChart(items, scale, includeDemand);
  const width = 640;
  const height = 210;
  const padLeft = 36;
  const padRight = 16;
  const padTop = 12;
  const padBottom = 44;
  const span = Math.max(chart.labels.length - 1, 1);
  const inner = height - padTop - padBottom;
  const xAt = (index: number) => padLeft + (index * (width - padLeft - padRight)) / span;
  const yAt = (value: number) => height - padBottom - value * inner;
  return (
    <section className="compare-panel">
      <div className="scheme-card-head">
        <strong>方案对比</strong>
        <button type="button" className="drawer-close" onClick={onClear}>清空</button>
      </div>
      <p className="hud-note">每条线是一个方案。各项都是越小越好，线越低越优。纵轴按这次全部帕累托方案固定，再加入一条线不会改动已经画出的线。</p>
      {items.length < 2 ? <p className="hud-note">再加入一个方案，折线才会叠在一起。</p> : (
        <svg className="compare-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="方案目标折线对比">
          {chart.labels.map((label, index) => (
            <g key={label}>
              <line x1={xAt(index)} y1={padTop} x2={xAt(index)} y2={height - padBottom} stroke="rgb(120 230 255 / 25%)" />
              <text x={xAt(index)} y={height - 14} textAnchor="middle" fill="#d7f6ff" fontSize="22">{label}</text>
            </g>
          ))}
          {chart.series.map((series, seriesIndex) => {
            const points = series.values.flatMap((value, index) => value === null ? [] : [`${xAt(index)},${yAt(value)}`]);
            const color = COMPARE_COLORS[items[seriesIndex].colorIndex % COMPARE_COLORS.length];
            return <polyline key={series.id} points={points.join(" ")} fill="none" stroke={color} strokeWidth="2.5" />;
          })}
        </svg>
      )}
      <div className="compare-legend">
        {items.map((item) => (
          <span key={item.id}><i style={{ background: COMPARE_COLORS[item.colorIndex % COMPARE_COLORS.length] }} />{item.name}</span>
        ))}
      </div>
    </section>
  );
}

function derivedLabel(edit: SiteEdit<ParetoChoice>, pose: ParetoChoice): string {
  if (!pose.derivedFrom) return "";
  const index = edit.poses.findIndex((item) => item.id === pose.derivedFrom);
  return index < 0 ? " · 局部优化" : ` · 由方案 ${index + 1} 局部优化`;
}

function agentMapPreview(edit: SiteEdit<ParetoChoice>, ops: readonly EditOp[] | null) {
  if (!ops) return emptyAgentPreview;
  try {
    const applied = applyOps(edit, ops);
    const geometry = proposalPreview(edit, applied.edit);
    const refined = applied.refine ? applied.edit.poses.find((pose) => pose.id === applied.refine?.poseId) : undefined;
    const square = refined && applied.refine
      ? [new ExclusionZone("refine", refineSquare(refined, applied.refine.halfWidthM).map(([x, y]) => ({ x, y })), "feasible")]
      : [];
    return {
      zones: [...geometry.regions.map((region) => new ExclusionZone(region.id, region.ring, region.kind)), ...square],
      footprints: BuildingFootprint.layer(
        geometry.poses,
        { widthM: applied.edit.widthM, heightM: applied.edit.heightM },
        -1,
      ),
      origin: geometry.origin,
    };
  } catch {
    return emptyAgentPreview;
  }
}

const idleCommands: MapCommands = {
  drawing: false,
  pan: () => undefined,
  draw: () => undefined,
  focus: () => undefined,
  closeDraft: () => undefined,
  cancelDraft: () => undefined,
  undoPoint: () => undefined,
  previous: () => undefined,
  next: () => undefined,
  optimize: () => undefined,
};
