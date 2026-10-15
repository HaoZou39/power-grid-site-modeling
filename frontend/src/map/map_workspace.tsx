import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { cancelJob, createJob, createLanduseEdit, deleteExperiment, deleteLanduseEdit, fetchArtifactText, fetchConstructionFeasibilityOverlay, fetchPoseObjectives, fetchSiteReport, getExperiments, getJob, getLanduseEdits, getRoadSegments, getSceneLayerInfo, getScenes, pickLandusePatch } from "../api";
import type { ExperimentRecord, JobRecord, LanduseEdit, RoadSegment, SceneLayerInfo, SceneRecord, SiteReport } from "../api";
import { JOB_STATUS_LABEL, messageLabel } from "../run_status";
import { WorldMap } from "./world_map";
import { BuildingFootprint } from "./building_footprint";
import {
  angleDegreesToRadians,
  BuildingSize,
  JobFollowUp,
  GuidedDecisionRun,
  buildingSizeFromResolvedConfig,
  compareChart,
  comparedFields,
  isChoiceEdited,
  measuredChoice,
  placeDescription,
  refineSquare,
  refinedChoices,
  restoreChoice,
  rotateChoice,
  schemeCard,
  unmeasured,
  widthAzimuthDeg,
} from "./decision_run";
import type { StatusRow } from "./decision_run";
import type { ParetoChoice } from "./decision_run";
import { SiteEdit, rectangleCorners } from "./site_edit";
import type { FieldPolicy, RegionKind, SiteRegion } from "./site_edit";
import { siteReportFailureNotice } from "./site_report_feedback";
import { ExclusionZone } from "./exclusion_sketch";
import { RECOMMEND_COLORS, emptyAgentPreview } from "./site_overlay";
import type { RegionVisibility } from "./site_overlay";
import { AgentPanel } from "../agent/agent_panel";
import type { AskPose } from "../agent/agent_panel";
import { recordPreferenceChoice } from "../agent/agent_api";
import { AgentSettingsDialog } from "../agent/agent_settings_dialog";
import { preferenceChoice, toSnapshot } from "../agent/workspace_snapshot";
import type { WorkspaceLayerState } from "../agent/workspace_snapshot";
import { applyOps, proposalPreview } from "../agent/edit_ops";
import type { EditOp } from "../agent/edit_ops";
import type { LocalPoint } from "./site_frame";
import { HistoryPanel } from "./history_panel";
import { SoftwareUpdateDialog, useSoftwareUpdate } from "./software_update_dialog";
import { MapToolbar } from "./map_toolbar";
import { exportSolutionsCsv, exportSolutionsJson } from "./solution_export";
import { LayerPanel } from "./layer_panel";
import { readMapTheme, toggleMapTheme, writeMapTheme } from "./theme";
import type { MapTheme } from "./theme";
import { LANDUSE_CLASSES, hiddenLanduseClasses, landuseEditClass, regionKind } from "./toolbar_commands";
import type { MapToolName } from "./toolbar_commands";
import { landuseEditClassId } from "./landuse_sketch";
import { simplifyStroke } from "./exclusion_sketch";
import { MapShortcuts } from "./map_shortcuts";
import type { MapCommands } from "./map_shortcuts";
import { useDraggablePanel } from "./use_draggable_panel.js";
import { SchemeConnector } from "./scheme_connector";
import type { SchemeCardBounds, SchemeTarget, ViewportRect, WorkspaceBounds } from "./scheme_connector";
import { bringPanelToFront, floatingPanelZIndex } from "./floating_panel_order";
import type { FloatingPanelId } from "./floating_panel_order";
import { isSchemeCardVisible, schemeCardShouldOpen } from "./scheme_card_state";
import { LatestOverlayRequest, feasibilityRequest, replaceOverlayObjectUrl } from "./feasibility_overlay";
import { SolutionGeneration } from "./solution_generation";

const PREPARE_PLUGIN = "site.prepare_scene";
const DEFAULT_SCENE = "cangnan";
type EvaluationState = "idle" | "loading" | "success" | "error";
type ErasedItem =
  | { kind: "region"; region: SiteRegion }
  | { kind: "origin"; point: LocalPoint };

/** Decision map. Scene data is prepared once. Optimization only reads that scene. */
export function MapWorkspace({ health }: { health: string }) {
  const workspaceRef = useRef<HTMLDivElement>(null);
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
  const softwareUpdate = useSoftwareUpdate(setNotice);
  const [agentSettingsOpen, setAgentSettingsOpen] = useState(false);
  const [memoryDisabledToken, setMemoryDisabledToken] = useState(0);
  const [rectW, setRectW] = useState("77");
  const [rectH, setRectH] = useState("51.5");
  const [job, setJob] = useState<JobRecord | null>(null);
  const jobRef = useRef(job);
  jobRef.current = job;
  const [jobStarting, setJobStarting] = useState(false);
  const jobStartingRef = useRef(false);
  const [focusToken, setFocusToken] = useState(0);
  const [scene, setScene] = useState<SceneRecord | null>(null);
  const [sceneVersion, setSceneVersion] = useState(0);
  const [shownClasses, setShownClasses] = useState(hiddenLanduseClasses);
  const [landuseEdits, setLanduseEdits] = useState<LanduseEdit[]>([]);
  const [landuseDraft, setLanduseDraft] = useState<LocalPoint[]>([]);
  const landuseDraftRef = useRef(landuseDraft);
  landuseDraftRef.current = landuseDraft;
  const [layersOpen, setLayersOpen] = useState(false);
  const [layerInfo, setLayerInfo] = useState<SceneLayerInfo | null>(null);
  const [layerError, setLayerError] = useState("");
  const [demVisible, setDemVisible] = useState(false);
  const [demOpacity, setDemOpacity] = useState(0.6);
  const [roadsVisible, setRoadsVisible] = useState(false);
  const [roadSegments, setRoadSegments] = useState<RoadSegment[]>([]);
  const [roadError, setRoadError] = useState("");
  const [regionVisibility, setRegionVisibility] = useState<RegionVisibility>({ exclusion: true, feasible: true });
  const [feasibilityVisible, setFeasibilityVisible] = useState(false);
  const [feasibilityUrl, setFeasibilityUrl] = useState<string | null>(null);
  const [fieldCost, setFieldCost] = useState("0.5");
  const [report, setReport] = useState<SiteReport | null>(null);
  const [azimuthDeg, setAzimuthDeg] = useState("");
  const [evaluationState, setEvaluationState] = useState<EvaluationState>("idle");
  const [evaluationError, setEvaluationError] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);
  const [askPose, setAskPose] = useState<AskPose | null>(null);
  const [previewOps, setPreviewOps] = useState<readonly EditOp[] | null>(null);
  const [panelMinimized, setPanelMinimized] = useState(false);
  const [theme, setTheme] = useState<MapTheme>(() => readMapTheme(window.localStorage));
  const [history, setHistory] = useState<ExperimentRecord[] | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [loadedCaseId, setLoadedCaseId] = useState<string | null>(null);
  const [schemeAnchor, setSchemeAnchor] = useState<{ x: number; y: number } | null>(null);
  const [schemeTarget, setSchemeTarget] = useState<SchemeTarget | null>(null);
  const [schemeCardBounds, setSchemeCardBounds] = useState<SchemeCardBounds | null>(null);
  const [workspaceBounds, setWorkspaceBounds] = useState<WorkspaceBounds | null>(null);
  const [schemeCardOpen, setSchemeCardOpen] = useState(false);
  const [comparedIds, setComparedIds] = useState<string[]>([]);
  const [recommendedIds, setRecommendedIds] = useState<readonly string[]>([]);
  const [panelOrder, setPanelOrder] = useState<readonly FloatingPanelId[]>([]);
  const run = useRef(new GuidedDecisionRun({ getExperiments, fetchArtifactText }));
  const followUp = useRef(new JobFollowUp());
  // A local re-search adds its picks next to this scheme instead of replacing the map.
  const refining = useRef<{ jobId: string; origin: ParetoChoice; hasOrigin: boolean; includeDemand: boolean } | null>(null);
  const dragStart = useRef<{ id: string; x: number; y: number } | null>(null);
  const erasedItem = useRef<ErasedItem | null>(null);
  const commands = useRef<MapCommands>(idleCommands);
  const feasibilityRequests = useRef(new LatestOverlayRequest());
  const feasibilityUrlRef = useRef<string | null>(null);
  const solutionGeneration = useRef(new SolutionGeneration());

  const selected = edit.selected;
  const origin = edit.origin;
  const originPlace = origin ? placeDescription(origin) : null;
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
    return [{ id, name: `方案 ${index + 1}`, choice: pose }];
  });
  const showSchemeCard = isSchemeCardVisible(selected?.id ?? null, schemeCardOpen);
  const schemePanelKey = showSchemeCard ? selected?.id ?? null : null;
  const compareOpen = compared.length > 0;
  const bringToFront = useCallback((id: FloatingPanelId) => {
    setPanelOrder((current) => bringPanelToFront(current, id));
  }, []);
  const replaceFeasibilityUrl = useCallback((next: string | null) => {
    feasibilityUrlRef.current = replaceOverlayObjectUrl(
      feasibilityUrlRef.current,
      next,
      (url) => URL.revokeObjectURL(url),
    );
    setFeasibilityUrl(feasibilityUrlRef.current);
  }, []);
  const feasibilityBody = useMemo(
    () => feasibilityRequest(edit.searchConfig()),
    [edit.sceneName, edit.mountainPolicy, edit.fieldPolicy, edit.fieldCost, edit.regions],
  );
  const feasibilityKey = useMemo(
    () => JSON.stringify(feasibilityBody),
    [feasibilityBody],
  );

  useLayoutEffect(() => {
    if (agentOpen) bringToFront("agent");
  }, [agentOpen, bringToFront]);

  useLayoutEffect(() => {
    if (layersOpen) bringToFront("gis");
  }, [layersOpen, bringToFront]);

  useLayoutEffect(() => {
    if (schemePanelKey) bringToFront("scheme");
  }, [schemePanelKey, bringToFront]);

  useLayoutEffect(() => {
    if (compareOpen) bringToFront("compare");
  }, [compareOpen, bringToFront]);

  const recommended = recommendedIds.flatMap((id, rank) => {
    const index = edit.poses.findIndex((pose) => pose.id === id);
    return index < 0 ? [] : [{ id, rank: rank + 1, name: `方案 ${index + 1}` }];
  });
  const running = jobStarting || (job !== null && JobFollowUp.isActive(job.status));
  const preparing = running && job?.plugin_id === PREPARE_PLUGIN;
  const originLockMessage = running
    ? "优化进行中，暂不能修改进货原点。"
    : edit.poses.length > 0
      ? "当前方案已绑定进货原点，请先清空当前方案后再修改。"
      : null;
  const sceneReady = scene?.ready === true;
  const currentLanduseEditClass = landuseEditClass(tool);
  const agentLayers: WorkspaceLayerState = {
    panel_open: layersOpen,
    scene_ready: sceneReady,
    dem: {
      visible: demVisible,
      opacity: demOpacity,
      available: sceneReady && layerInfo?.dem.available === true,
    },
    landuse: {
      field: { visible: shownClasses.field, available: sceneReady && layerInfo?.landuse.field === true },
      building: { visible: shownClasses.building, available: sceneReady && layerInfo?.landuse.building === true },
      road: { visible: shownClasses.road, available: sceneReady && layerInfo?.landuse.road === true },
      water: { visible: shownClasses.water, available: sceneReady && layerInfo?.landuse.water === true },
    },
    osm_roads: {
      visible: roadsVisible,
      available: sceneReady && layerInfo?.roads.available === true,
    },
    regions: { ...regionVisibility },
  };
  const agentLayersRef = useRef(agentLayers);
  agentLayersRef.current = agentLayers;

  function optimizationActive(): boolean {
    return jobStartingRef.current || (jobRef.current !== null && JobFollowUp.isActive(jobRef.current.status));
  }

  function originEditingBlockedMessage(): string | null {
    if (optimizationActive()) return "优化进行中，暂不能修改进货原点。";
    if (editRef.current.poses.length > 0) return "当前方案已绑定进货原点，请先清空当前方案后再修改。";
    return null;
  }

  function requireOriginEditable(): void {
    const message = originEditingBlockedMessage();
    if (message) throw new Error(message);
  }

  async function createTrackedJob(request: Parameters<typeof createJob>[0]): Promise<JobRecord> {
    jobStartingRef.current = true;
    setJobStarting(true);
    try {
      const record = await createJob(request);
      jobRef.current = record;
      setJob(record);
      return record;
    } finally {
      jobStartingRef.current = false;
      setJobStarting(false);
    }
  }

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
    const nextScene = scenes.find((item) => item.id === DEFAULT_SCENE) ?? scenes[0] ?? null;
    setScene(nextScene);
    setSceneVersion((version) => version + 1);
  }

  function activeKind(): RegionKind {
    const kind = regionKind(tool);
    if (!kind) throw new Error("当前工具不能画范围。");
    return kind;
  }

  function selectTool(next: MapToolName) {
    if (next === "origin") {
      const message = originEditingBlockedMessage();
      if (message) {
        setNotice(message);
        return;
      }
    }
    if (next !== tool) {
      boxAnchor.current = null;
      setEdit((current) => current.draft.length > 0 ? current.cancelDraft() : current);
      setLanduseDraftPoints([]);
    }
    const kind = regionKind(next);
    if (kind) {
      setRegionVisibility((current) => current[kind] ? current : { ...current, [kind]: true });
    }
    const landuseClass = landuseEditClass(next);
    if (landuseClass) {
      setShownClasses((current) => ({ ...current, [landuseClass]: true }));
    }
    setTool(next);
  }

  function setLanduseDraftPoints(points: LocalPoint[]) {
    landuseDraftRef.current = points;
    setLanduseDraft(points);
  }

  function previewLanduseDraft(points: LocalPoint[]) {
    if (!landuseEditClass(tool)) return;
    setLanduseDraftPoints(points);
    setNotice("");
  }

  async function finishLanduseDraft(stroke: readonly LocalPoint[]) {
    const category = landuseEditClass(tool);
    const points = simplifyStroke(stroke, 4);
    if (!category || !scene || points.length < 3) {
      setLanduseDraftPoints([]);
      setNotice("土地类型图斑至少需要三个折点。");
      return;
    }
    setLanduseDraftPoints([]);
    try {
      const result = await createLanduseEdit(scene.id, landuseEditClassId(category), localRing(points));
      setLanduseEdits(result.items);
      setLanduseDraftPoints([]);
      setSceneVersion((version) => version + 1);
      setNotice("图斑已保存到当前场景，之后的优化会使用修正后的土地类型。");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法保存土地类型图斑");
    }
  }

  async function removeLandusePatch(editId: string) {
    if (!scene) return;
    try {
      const result = await deleteLanduseEdit(scene.id, editId);
      setLanduseEdits(result.items);
      setSceneVersion((version) => version + 1);
      setNotice("已删除图斑，场景土地类型已恢复。");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法删除土地类型图斑");
    }
  }

  function clickBox(point: LocalPoint) {
    const kind = activeKind();
    const kindLabel = kind === "feasible" ? "可行域" : "禁区";
    const anchor = boxAnchor.current;
    if (!anchor) {
      boxAnchor.current = point;
      setEdit((current) => current.replaceDraft([point]));
      setNotice("已确定第一个角点，请单击对角点完成方框。");
      return;
    }
    try {
      setEdit(editRef.current.addRectangle(kind, anchor, point));
      boxAnchor.current = null;
      setNotice(`${kindLabel}已创建。`);
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

  function eraseRegion(id: string) {
    if (!id) {
      setNotice("这里没有可擦掉的范围。");
      return;
    }
    const region = editRef.current.regions.find((item) => item.id === id);
    if (!region || (region.kind !== "exclusion" && region.kind !== "feasible")) {
      setNotice("这里没有可擦掉的范围。");
      return;
    }
    erasedItem.current = { kind: "region", region: { ...region, ring: [...region.ring] } };
    setEdit((current) => current.removeRegion(id));
    setNotice("已擦掉这块范围。按 Ctrl+Z 可以恢复。");
  }

  function replaceOriginAndRemeasure(next: SiteEdit<ParetoChoice>) {
    setReport(null);
    const ids = next.poses.map((pose) => pose.id);
    if (ids.length > 0) markMoved(next, ids);
    else setEdit(next);
  }

  function clearLogisticsOrigin() {
    const message = originEditingBlockedMessage();
    if (message) {
      setNotice(message);
      return;
    }
    const current = editRef.current;
    const point = current.origin;
    if (!point) return;
    erasedItem.current = { kind: "origin", point: { ...point } };
    replaceOriginAndRemeasure(current.clearOrigin());
    if (tool === "origin") selectTool("pan");
    setNotice("已清除进货原点，按 Ctrl+Z 可恢复。");
  }

  function putLogisticsOrigin(point: LocalPoint) {
    requireOriginEditable();
    const next = editRef.current.putOrigin(point);
    if (erasedItem.current?.kind === "origin") erasedItem.current = null;
    replaceOriginAndRemeasure(next);
  }

  function undoErase() {
    const erased = erasedItem.current;
    if (!erased) {
      setNotice("没有刚刚删除的内容可以恢复。");
      return;
    }
    if (erased.kind === "region") {
      setEdit((current) => current.restoreRegion(erased.region));
      erasedItem.current = null;
      setNotice("已恢复刚刚擦除的范围。");
      return;
    }
    const message = originEditingBlockedMessage();
    if (message) {
      setNotice(message);
      return;
    }
    if (editRef.current.origin) {
      erasedItem.current = null;
      setNotice("当前已有进货原点，未用旧位置覆盖。");
      return;
    }
    erasedItem.current = null;
    replaceOriginAndRemeasure(editRef.current.putOrigin(erased.point));
    setNotice("已恢复进货原点。");
  }

  function clearDisplayedSolutions(announce = true, allowEmpty = false): boolean {
    if (optimizationActive()) throw new Error("优化进行中，结束后才能清空方案。");
    const current = editRef.current;
    if (current.poses.length === 0 && !allowEmpty) return false;
    solutionGeneration.current.advance();
    const cleared = current.clearPoses();
    editRef.current = cleared;
    setEdit(cleared);
    setLoadedCaseId(null);
    setComparedIds([]);
    setRecommendedIds([]);
    setSchemeCardOpen(false);
    setSchemeAnchor(null);
    setSchemeTarget(null);
    setSchemeCardBounds(null);
    setReport(null);
    setAzimuthDeg("");
    setEvaluationState("idle");
    setEvaluationError("");
    setPreviewOps(null);
    setAskPose(null);
    setAdjusting(false);
    dragStart.current = null;
    refining.current = null;
    if (tool === "adjust") setTool("pan");
    if (announce) setNotice("已清空当前方案，历史优化结果已保留。");
    return current.poses.length > 0;
  }

  function clearDisplayedSolutionsFromUi() {
    try {
      clearDisplayedSolutions();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法清空方案");
    }
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
    if (optimizationActive()) return;
    setNotice("");
    clearDisplayedSolutions(false, true);
    try {
      await createTrackedJob({ plugin_id: PREPARE_PLUGIN, config: { scene_name: scene?.id ?? DEFAULT_SCENE } });
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法构建场景数据");
    }
  }

  async function stopPrepare() {
    if (!job || job.plugin_id !== PREPARE_PLUGIN) return;
    try {
      const record = await cancelJob(job.job_id);
      jobRef.current = record;
      setJob(record);
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
    if (optimizationActive()) {
      setNotice("优化进行中，结束后再导入历史结果。");
      return;
    }
    const generation = solutionGeneration.current.advance();
    try {
      const experiments = history ?? await getExperiments();
      const experiment = experiments.find((item) => item.id === experimentId);
      const choices = await run.current.loadPareto(experimentId);
      const size = await importedBuildingSize(experiment);
      if (!solutionGeneration.current.isCurrent(generation)) return;
      setEdit((current) => {
        const sized = size ? current.withBuilding(size.widthM, size.heightM) : current;
        return sized.withPoses(choices);
      });
      if (size) {
        setRectW(String(size.widthM));
        setRectH(String(size.heightM));
      }
      setComparedIds([]);
      setRecommendedIds([]);
      setSchemeCardOpen(schemeCardShouldOpen("automatic", choices.length > 0));
      setLoadedCaseId(experimentId);
      setFocusToken((token) => token + 1);
      setHistoryOpen(false);
      setNotice(`已导入 ${experimentId}，共 ${choices.length} 个可行帕累托方案。`);
    } catch (reason) {
      if (!solutionGeneration.current.isCurrent(generation)) return;
      setNotice(reason instanceof Error ? reason.message : "无法导入这次结果");
    }
  }

  function downloadSolutions(format: "csv" | "json") {
    if (edit.poses.length === 0) {
      setNotice("暂无可导出的方案，请先导入案例或完成一次优化。");
      return;
    }
    const content = format === "csv"
      ? exportSolutionsCsv(edit.poses)
      : exportSolutionsJson(edit.sceneName, edit.widthM, edit.heightM, edit.poses);
    const blob = new Blob([content], { type: format === "csv" ? "text/csv;charset=utf-8" : "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${edit.sceneName}-solutions.${format}`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    setNotice(`已导出 ${edit.poses.length} 个方案（${format.toUpperCase()}）。`);
  }

  async function confirmDeleteHistory(experimentId: string) {
    const activeName = running ? String(job?.config.experiment_name ?? "") : "";
    if (activeName && activeName === experimentId) {
      setPendingDeleteId(null);
      setNotice("这次优化还在写入该目录，结束后才能删除。");
      return;
    }
    if (loadedCaseId === experimentId && optimizationActive()) {
      setPendingDeleteId(null);
      setNotice("优化进行中，结束后才能删除当前加载的案例。");
      return;
    }
    try {
      await deleteExperiment(experimentId);
      setHistory((current) => current?.filter((item) => item.id !== experimentId) ?? null);
      setPendingDeleteId(null);
      if (loadedCaseId === experimentId) {
        clearDisplayedSolutions(false, true);
      }
      setNotice(`已删除 ${experimentId}。`);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法删除这次结果");
    }
  }

  async function submitSearch(current: SiteEdit<ParetoChoice>): Promise<boolean> {
    if (optimizationActive()) {
      setNotice("优化还在进行，这次没有重新开始。");
      return false;
    }
    if (!sceneReady) {
      setNotice("请先完成场景数据构建。优化不会在搜索时重新生成 DEM、道路和需求点。");
      return false;
    }
    // The previous schemes stay on the map until the new ones load, so a failed run leaves them in place.
    const submitted = current.withScene(scene?.id ?? DEFAULT_SCENE);
    setNotice("");
    setEdit(submitted);
    setRectW(String(submitted.widthM));
    setRectH(String(submitted.heightM));
    setFieldCost(String(submitted.fieldCost));
    refining.current = null;
    solutionGeneration.current.advance();
    await createTrackedJob(run.current.createRequest(submitted, new Date()));
    return true;
  }

  async function submitRefine(current: SiteEdit<ParetoChoice>, poseId: string, halfWidthM: number) {
    if (optimizationActive()) {
      setNotice("优化还在进行，这次没有开始局部优化。");
      return;
    }
    const pose = current.poses.find((item) => item.id === poseId);
    if (!pose || !sceneReady) return;
    const submitted = current.withScene(scene?.id ?? DEFAULT_SCENE);
    solutionGeneration.current.advance();
    const record = await createTrackedJob(run.current.createRefineRequest(submitted, pose, halfWidthM, new Date()));
    refining.current = {
      jobId: record.job_id,
      origin: pose,
      hasOrigin: submitted.origin !== null,
      includeDemand: submitted.includeDemand,
    };
    setNotice(`正在方案 ${current.poses.indexOf(pose) + 1} 周围局部优化，原方案保留。`);
  }

  /** Recompute moved schemes with the search's own objectives. A scheme moved again meanwhile keeps waiting. */
  async function remeasure(current: SiteEdit<ParetoChoice>, ids: readonly string[]) {
    const poses = current.poses.filter((pose) => ids.includes(pose.id));
    if (!scene || poses.length === 0) return;
    const { scene_name: _scene, ...config } = current.searchConfig();
    const configKey = JSON.stringify(config);
    const generation = solutionGeneration.current.capture();
    try {
      const { items } = await fetchPoseObjectives(scene.id, {
        ...config,
        poses: poses.map(({ x, y, theta }) => ({ x, y, theta })),
      });
      if (!solutionGeneration.current.isCurrent(generation)) return;
      const { scene_name: _latestScene, ...latestConfig } = editRef.current.searchConfig();
      if (JSON.stringify(latestConfig) !== configKey) return;
      setEdit((latest) => {
        const { scene_name: _currentScene, ...currentConfig } = latest.searchConfig();
        if (JSON.stringify(currentConfig) !== configKey) return latest;
        return latest.withPoses(latest.poses.map((pose) => {
          const index = poses.findIndex((item) => item.id === pose.id && item.x === pose.x && item.y === pose.y && item.theta === pose.theta);
          return index < 0 ? pose : measuredChoice(pose, items[index]);
        }));
      });
      setEvaluationState("success");
      setEvaluationError("");
    } catch (reason) {
      if (!solutionGeneration.current.isCurrent(generation)) return;
      const message = reason instanceof Error ? reason.message : "请求失败";
      setEvaluationState("error");
      setEvaluationError(message);
      setNotice(`目标值没有重算：${message}`);
    }
  }

  function markMoved(current: SiteEdit<ParetoChoice>, ids: readonly string[]): SiteEdit<ParetoChoice> {
    if (ids.length === 0) return current;
    setEvaluationState("loading");
    setEvaluationError("");
    const next = current.withPoses(current.poses.map((pose) => ids.includes(pose.id) ? unmeasured(pose) : pose));
    setEdit(next);
    void remeasure(next, ids);
    return next;
  }

  async function startOptimization() {
    if (optimizationActive()) return;
    try {
      const current = editRef.current;
      const size = BuildingSize.parse(rectW, rectH);
      const cost = current.fieldPolicy === "costly" ? Number(fieldCost) : 0.5;
      if (current.fieldPolicy === "costly" && (!Number.isFinite(cost) || cost <= 0 || cost > 1)) {
        setNotice("农田代价系数必须在 0 到 1 之间。");
        return;
      }
      const submitted = await submitSearch(
        current.withBuilding(size.widthM, size.heightM).withPolicies("allowed", current.fieldPolicy, cost),
      );
      if (submitted) selectTool("pan");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法开始优化");
    }
  }

  function changeAzimuth(value: string) {
    setAzimuthDeg(value);
    const current = editRef.current;
    const choice = current.selected;
    if (!choice || value.trim() === "") return;
    try {
      const theta = angleDegreesToRadians(Number(value) - 90);
      const next = current.updateSelected((item) => rotateChoice(
        item,
        theta,
        new BuildingSize(current.widthM, current.heightM),
      ));
      if (Math.abs(theta - choice.theta) > 1e-9) markMoved(next, [choice.id]);
      else setEdit(next);
      setNotice("");
    } catch (reason) {
      setAzimuthDeg(formatAzimuthDegrees(choice.theta));
      setNotice(reason instanceof Error ? reason.message : "无法应用这个方位角");
    }
  }

  function resetAzimuth() {
    const choice = editRef.current.selected;
    setAzimuthDeg(choice ? formatAzimuthDegrees(choice.theta) : "");
  }

  function restoreOriginal() {
    const current = editRef.current;
    const choice = current.selected;
    if (!choice || !isChoiceEdited(choice)) return;
    markMoved(current.updateSelected(restoreChoice), [choice.id]);
    setNotice("");
  }

  async function confirmAgent(ops: readonly EditOp[]) {
    validateAgentOps(ops);
    const before = editRef.current;
    const applied = applyOps(before, ops, agentLayersRef.current);
    if (applied.clearPoses) {
      clearDisplayedSolutions();
      return;
    }
    const originChanged = !samePoint(before.origin, applied.edit.origin);
    if (originChanged) {
      setReport(null);
      if (applied.edit.origin && erasedItem.current?.kind === "origin") erasedItem.current = null;
    }
    const displayChanged = applied.layerChanges.some((op) => op.kind !== "set_layer_panel_open");
    const panelChanged = applied.layerChanges.some((op) => op.kind === "set_layer_panel_open");
    if (displayChanged) {
      setDemVisible(applied.layers.dem.visible);
      setDemOpacity(applied.layers.dem.opacity);
      setShownClasses({
        field: applied.layers.landuse.field.visible,
        building: applied.layers.landuse.building.visible,
        road: applied.layers.landuse.road.visible,
        water: applied.layers.landuse.water.visible,
      });
      setRoadsVisible(applied.layers.osm_roads.visible);
      setRegionVisibility({ ...applied.layers.regions });
    }
    if (panelChanged) setLayersOpen(applied.layers.panel_open);
    else if (displayChanged) setLayersOpen(true);
    const moved = applied.edit.poses.filter((pose) => {
      const old = before.poses.find((item) => item.id === pose.id);
      return old && (old.x !== pose.x || old.y !== pose.y || old.theta !== pose.theta);
    });
    const rescored = JSON.stringify(before.searchConfig()) !== JSON.stringify(applied.edit.searchConfig()) && !applied.runSearch;
    let edit = applied.edit;
    if (applied.edit !== before) {
      setRectW(String(applied.edit.widthM));
      setRectH(String(applied.edit.heightM));
      setFieldCost(String(applied.edit.fieldCost));
      setEdit(applied.edit);
      edit = markMoved(applied.edit, (rescored ? applied.edit.poses : moved).map((pose) => pose.id));
    }
    try {
      if (applied.runSearch) await submitSearch(edit);
      if (applied.refine) await submitRefine(edit, applied.refine.poseId, applied.refine.halfWidthM);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法开始优化");
    }
  }

  function validateAgentOps(ops: readonly EditOp[]): void {
    if (ops.some((op) => op.kind === "set_origin" || op.kind === "clear_origin")) requireOriginEditable();
    applyOps(editRef.current, ops, agentLayersRef.current);
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
    setSchemeCardOpen(schemeCardShouldOpen("automatic", added.length > 0));
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

  function selectPoseAndOpen(id: string) {
    const hasSelection = editRef.current.poses.some((pose) => pose.id === id);
    setEdit((current) => current.selectPose(id));
    setSchemeCardOpen(schemeCardShouldOpen("user", hasSelection));
  }

  function stepPoseAndOpen(delta: number) {
    const hasSelection = editRef.current.poses.length > 0;
    setEdit((current) => current.stepPose(delta));
    setSchemeCardOpen(schemeCardShouldOpen("user", hasSelection));
  }

  commands.current = {
    drawing: regionKind(tool) !== null || landuseEditClass(tool) !== null,
    pan: () => selectTool("pan"),
    draw: () => selectTool("exclusion"),
    focus: () => setFocusToken((token) => token + 1),
    closeDraft,
    cancelDraft: () => {
      boxAnchor.current = null;
      setEdit((current) => current.cancelDraft());
      setLanduseDraftPoints([]);
      setTool("pan");
    },
    undoPoint: () => {
      if (landuseEditClass(tool)) {
        setLanduseDraftPoints([]);
        return;
      }
      setEdit((current) => current.undoPoint());
    },
    undoErase,
    previous: () => stepPoseAndOpen(-1),
    next: () => stepPoseAndOpen(1),
    optimize: () => void startOptimization(),
  };

  useEffect(() => {
    if (!job || !JobFollowUp.isActive(job.status)) return;
    let stopped = false;
    const poll = async () => {
      let resultGeneration: number | null = null;
      try {
        const record = await getJob(job.job_id);
        if (stopped) return;
        jobRef.current = record;
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
        resultGeneration = solutionGeneration.current.capture();
        const choices = await run.current.loadPareto(experimentId);
        if (!solutionGeneration.current.isCurrent(resultGeneration)) return;
        const refine = refining.current?.jobId === record.job_id ? refining.current : null;
        if (refine) {
          refining.current = null;
          mergeRefined(refine, experimentId, choices);
          return;
        }
        setEdit((current) => current.withPoses(choices));
        setComparedIds([]);
        setRecommendedIds([]);
        setSchemeCardOpen(schemeCardShouldOpen("automatic", choices.length > 0));
        setLoadedCaseId(experimentId);
        setFocusToken((token) => token + 1);
        setNotice("");
      } catch (reason) {
        if (!stopped && (resultGeneration === null || solutionGeneration.current.isCurrent(resultGeneration))) {
          setNotice(reason instanceof Error ? reason.message : "无法读取任务状态");
        }
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
    const loadInitialScene = async () => {
      const scenes = await getScenes();
      const initialScene = scenes.find((item) => item.id === DEFAULT_SCENE) ?? scenes[0] ?? null;
      setScene(initialScene);
      setSceneVersion((version) => version + 1);
    };
    loadInitialScene().catch((reason) => {
      setNotice(reason instanceof Error ? reason.message : "无法读取场景");
    });
  }, []);

  useEffect(() => {
    setAzimuthDeg(selected ? formatAzimuthDegrees(selected.theta) : "");
  }, [selected?.id, selected?.theta]);

  useEffect(() => {
    setEvaluationState("idle");
    setEvaluationError("");
  }, [selected?.id]);

  useEffect(() => {
    setLayerInfo(null);
    setLayerError("");
    setRoadSegments([]);
    setRoadError("");
    if (!sceneReady || !scene) return;
    let stopped = false;
    getSceneLayerInfo(scene.id)
      .then((value) => {
        if (!stopped) setLayerInfo(value);
      })
      .catch((reason) => {
        if (!stopped) setLayerError(reason instanceof Error ? reason.message : "无法读取图层资源");
      });
    return () => {
      stopped = true;
    };
  }, [scene]);

  useEffect(() => {
    setLanduseEdits([]);
    setLanduseDraftPoints([]);
    if (!sceneReady || !scene || !layerInfo
      || !Object.values(layerInfo.landuse).some(Boolean)) return;
    let stopped = false;
    getLanduseEdits(scene.id)
      .then(({ items }) => {
        if (!stopped) setLanduseEdits(items);
      })
      .catch((reason) => {
        if (!stopped) setNotice(reason instanceof Error ? reason.message : "无法读取场景土地类型修正");
      });
    return () => {
      stopped = true;
    };
  }, [scene?.id, sceneReady, sceneVersion, layerInfo]);

  useEffect(() => {
    const token = feasibilityRequests.current.begin();
    const controller = new AbortController();
    if (!feasibilityVisible || !sceneReady || !scene) {
      replaceFeasibilityUrl(null);
      return () => controller.abort();
    }
    replaceFeasibilityUrl(null);
    fetchConstructionFeasibilityOverlay(scene.id, feasibilityBody, controller.signal)
      .then((blob) => {
        if (!feasibilityRequests.current.isCurrent(token)) return;
        replaceFeasibilityUrl(URL.createObjectURL(blob));
      })
      .catch(() => {
        if (controller.signal.aborted || !feasibilityRequests.current.isCurrent(token)) return;
        replaceFeasibilityUrl(null);
      });
    return () => controller.abort();
  }, [
    feasibilityVisible,
    sceneReady,
    scene?.id,
    sceneVersion,
    feasibilityKey,
    replaceFeasibilityUrl,
  ]);

  useEffect(() => () => {
    feasibilityRequests.current.begin();
    if (feasibilityUrlRef.current) URL.revokeObjectURL(feasibilityUrlRef.current);
    feasibilityUrlRef.current = null;
  }, []);

  useEffect(() => {
    if (!roadsVisible || !sceneReady || !scene || layerInfo?.roads.available !== true || roadSegments.length > 0) return;
    let stopped = false;
    setRoadError("");
    getRoadSegments(scene.id)
      .then((value) => {
        if (!stopped) setRoadSegments(value.segments);
      })
      .catch((reason) => {
        if (!stopped) setRoadError(reason instanceof Error ? reason.message : "无法读取 OSM 道路网络");
      });
    return () => {
      stopped = true;
    };
  }, [roadsVisible, scene?.id, sceneReady, layerInfo?.roads.available, roadSegments.length]);

  useEffect(() => {
    if (!scene || !selected || adjusting) {
      if (!selected) setReport(null);
      return;
    }
    let stopped = false;
    const generation = solutionGeneration.current.capture();
    const selectedIndex = edit.selectedIndex;
    const body = edit.reportRequest();
    if (!body) return;
    setReport(null);
    fetchSiteReport(scene.id, body)
      .then((value) => {
        if (!stopped && solutionGeneration.current.isCurrent(generation)) setReport(value);
      })
      .catch((reason) => {
        if (!stopped && solutionGeneration.current.isCurrent(generation)) {
          setNotice(siteReportFailureNotice(selectedIndex, reason));
        }
      });
    return () => {
      stopped = true;
    };
  }, [
    scene?.id,
    selected,
    edit.marks,
    edit.widthM,
    edit.heightM,
    edit.mountainPolicy,
    edit.fieldPolicy,
    edit.fieldCost,
    edit.regions,
    adjusting,
  ]);

  useEffect(() => {
    const shortcuts = new MapShortcuts(() => commands.current);
    const onKeyDown = (event: KeyboardEvent) => shortcuts.handle(event);
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useLayoutEffect(() => {
    const node = workspaceRef.current;
    if (!node) return;
    let animationFrame = 0;
    const update = () => {
      animationFrame = 0;
      const next = workspaceRect(node);
      setWorkspaceBounds((current) => sameViewportRect(current, next) ? current : next);
    };
    const schedule = () => {
      if (animationFrame) return;
      animationFrame = window.requestAnimationFrame(update);
    };
    update();
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    observer?.observe(node);
    return () => {
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
      observer?.disconnect();
    };
  }, []);

  useLayoutEffect(() => {
    const node = workspaceRef.current;
    if (!node) return;
    const next = workspaceRect(node);
    setWorkspaceBounds((current) => sameViewportRect(current, next) ? current : next);
  });

  return (
    <div ref={workspaceRef} className={panelMinimized ? "map-app panel-minimized" : "map-app"} data-theme={theme}>
      <WorldMap
        tool={tool}
        zones={edit.zones}
        draft={edit.draft}
        footprints={BuildingFootprint.layer(edit.poses, { widthM: edit.widthM, heightM: edit.heightM }, edit.selectedIndex, recommendedIds)}
        landuseEdits={landuseEdits.map((item) => ({
          id: item.id,
          classId: item.class_id,
          points: item.points.map(([x, y]) => ({ x, y })),
        }))}
        landuseDraft={landuseDraft}
        landuseDraftClassId={currentLanduseEditClass ? landuseEditClassId(currentLanduseEditClass) : null}
        showLanduseOutlines={currentLanduseEditClass !== null || previewOps !== null}
        landuseLayers={sceneReady && scene ? LANDUSE_CLASSES.map((item) => ({
          id: item.id,
          url: `/api/v1/scenes/${scene.id}/landuse-overlay/${item.id}?v=${sceneVersion}`,
          visible: shownClasses[item.id],
        })) : []}
        elevationLayer={sceneReady && scene && layerInfo?.dem.available ? {
          url: `/api/v1/scenes/${scene.id}/dem-overlay`,
          visible: demVisible,
          opacity: demOpacity,
        } : null}
        feasibilityLayer={feasibilityVisible && feasibilityUrl ? {
          url: feasibilityUrl,
          visible: true,
        } : null}
        roadSegments={roadSegments}
        roadsVisible={roadsVisible}
        regionVisibility={regionVisibility}
        haulPath={(report?.haul_path ?? []).map(([x, y]) => ({ x, y }))}
        origin={origin}
        preview={agentMapPreview(edit, previewOps, agentLayers)}
        focusToken={focusToken}
        onAddDraftPoint={addDraftPoint}
        onPreviewStroke={previewStroke}
        onFinishStroke={finishStroke}
        onPreviewLanduseDraft={previewLanduseDraft}
        onFinishLanduseDraft={(points) => void finishLanduseDraft(points)}
        onDeleteLanduseEdit={(editId) => void removeLandusePatch(editId)}
        onPickPoint={(point) => void pickPatch(point)}
        onPickOrigin={(point) => {
          try {
            putLogisticsOrigin(point);
            const place = placeDescription(point);
            setNotice(`已设置进货原点：经度 ${place.lng}°，纬度 ${place.lat}°。`);
          } catch (reason) {
            setNotice(reason instanceof Error ? reason.message : "无法标出进货原点");
          }
        }}
        onCloseDraft={closeDraft}
        onDrawOutside={() => setNotice("范围只能画在选址范围框内。")}
        onSelectFootprint={selectPoseAndOpen}
        onBoxClick={clickBox}
        onBoxMove={previewBox}
        onEraseOrigin={clearLogisticsOrigin}
        onEraseZone={eraseRegion}
        onMoveFootprint={(dx, dy) => {
          const pose = editRef.current.selected;
          if (pose && !dragStart.current) dragStart.current = { id: pose.id, x: pose.x, y: pose.y };
          setAdjusting(true);
          setEvaluationState("loading");
          setEvaluationError("");
          setEdit((current) => current.moveSelected(dx, dy));
        }}
        onFinishMove={() => {
          setAdjusting(false);
          const start = dragStart.current;
          dragStart.current = null;
          const pose = start ? editRef.current.poses.find((item) => item.id === start.id) : undefined;
          if (start && pose && (pose.x !== start.x || pose.y !== start.y)) markMoved(editRef.current, [pose.id]);
          else setEvaluationState("idle");
        }}
        onSchemeAnchor={setSchemeAnchor}
        onSchemeTarget={setSchemeTarget}
      />
      <SchemeConnector
        target={schemeTarget?.schemeId === selected?.id ? schemeTarget : null}
        cardBounds={schemeCardBounds && schemeCardBounds.schemeId === selected?.id ? schemeCardBounds.bounds : null}
        workspaceBounds={workspaceBounds}
        visible={showSchemeCard}
      />
      <header className="hud-top">
        <div>
          <p>温州电力设计院</p>
          <strong>苍南选址规划</strong>
        </div>
        <div className="hud-brand">
          <span className={health.includes("失败") ? "hud-health bad" : "hud-health"}>{health}</span>
          <img className="lab-logo" src="/tgai-logo.png" alt="西湖大学可信及通用人工智能实验室" />
          <img src={theme === "light" ? "/westlake-logo-ink.png" : "/westlake-logo.png"} alt="西湖大学" />
        </div>
      </header>
      <MapToolbar
        tool={tool}
        notify={setNotice}
        focusSite={() => setFocusToken((token) => token + 1)}
        setTool={selectTool}
        hasSelection={selected !== null}
        sceneLabel={preparing ? "终止构建" : sceneReady ? "更新场景数据" : "构建场景数据"}
        sceneDisabled={!preparing && running}
        onPrepare={() => void (preparing ? stopPrepare() : prepareScene())}
        optimizeLabel={running && !preparing ? "正在优化…" : "开始优化"}
        optimizeDisabled={running || !sceneReady}
        onOptimize={() => void startOptimization()}
        clearSolutionsDisabled={running || edit.poses.length === 0}
        onClearSolutions={clearDisplayedSolutionsFromUi}
        historyOpen={historyOpen}
        onImportCase={() => void toggleHistory()}
        onExportCsv={() => downloadSolutions("csv")}
        onExportJson={() => downloadSolutions("json")}
        exportDisabled={edit.poses.length === 0}
        landuseEditDisabled={{
          field: !sceneReady || layerInfo?.landuse.field !== true,
          building: !sceneReady || layerInfo?.landuse.building !== true,
          road: !sceneReady || layerInfo?.landuse.road !== true,
          water: !sceneReady || layerInfo?.landuse.water !== true,
        }}
        originDisabled={originLockMessage !== null}
        originDisabledReason={originLockMessage ?? undefined}
        onSoftwareUpdate={softwareUpdate.openDialog}
        onAgentSettings={() => setAgentSettingsOpen(true)}
        themeLight={theme === "light"}
        onToggleTheme={() => {
          const next = toggleMapTheme(theme);
          writeMapTheme(window.localStorage, next);
          setTheme(next);
        }}
        updateDisabled={softwareUpdate.busy}
        agentOpen={agentOpen}
        onToggleAgent={() => {
          setAgentOpen((open) => !open);
          setPreviewOps(null);
        }}
        layersOpen={layersOpen}
        onToggleLayers={() => setLayersOpen((open) => !open)}
      />
      <SoftwareUpdateDialog update={softwareUpdate} />
      <AgentSettingsDialog
        open={agentSettingsOpen}
        onClose={() => setAgentSettingsOpen(false)}
        onMemoryDisabled={() => setMemoryDisabledToken((token) => token + 1)}
      />
      <LayerPanel
        open={layersOpen}
        zIndex={floatingPanelZIndex(panelOrder, "gis")}
        onBringToFront={() => bringToFront("gis")}
        sceneReady={sceneReady}
        info={layerInfo}
        error={layerError}
        shownClasses={shownClasses}
        demVisible={demVisible}
        demOpacity={demOpacity}
        roadsVisible={roadsVisible}
        roadError={roadError}
        regionVisibility={regionVisibility}
        feasibilityVisible={feasibilityVisible}
        onClose={() => setLayersOpen(false)}
        onToggleClass={(id) => setShownClasses((current) => ({ ...current, [id]: !current[id] }))}
        onToggleDem={() => setDemVisible((visible) => !visible)}
        onDemOpacity={setDemOpacity}
        onToggleRoads={() => setRoadsVisible((visible) => !visible)}
        onToggleRegion={(kind) => setRegionVisibility((current) => ({ ...current, [kind]: !current[kind] }))}
        onToggleFeasibility={() => setFeasibilityVisible((visible) => !visible)}
      />
      {agentOpen && (
        <AgentPanel
          edit={edit}
          zIndex={floatingPanelZIndex(panelOrder, "agent")}
          onBringToFront={() => bringToFront("agent")}
          experimentId={loadedCaseId}
          layers={agentLayers}
          onValidate={validateAgentOps}
          onApply={confirmAgent}
          onPreview={setPreviewOps}
          onRecommend={setRecommendedIds}
          ask={askPose}
          memoryDisabledToken={memoryDisabledToken}
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
        <p className="hud-note">预留接口</p>
        <label>农田
          <select value={edit.fieldPolicy} onChange={(event) => setEdit((current) => current.withPolicies("allowed", event.target.value as FieldPolicy, current.fieldCost))}>
            <option value="allowed">按坡度和进站条件判断</option>
            <option value="blocked">一律不可建设</option>
            <option value="costly">允许建设，计入成本</option>
          </select>
        </label>
        {edit.fieldPolicy === "costly" && (
          <label>农田代价系数<input value={fieldCost} onChange={(event) => setFieldCost(event.target.value)} /></label>
        )}
        <div className="hud-actions hud-optimize-actions">
          <button type="button" className="primary" onClick={() => void startOptimization()} disabled={running || !sceneReady}>
            {running && !preparing ? "正在优化…" : "开始优化"}
          </button>
          <button type="button" onClick={clearDisplayedSolutionsFromUi} disabled={running || edit.poses.length === 0}>清空方案</button>
        </div>
        {job && <p className="hud-note">{JOB_STATUS_LABEL[job.status]} · {messageLabel(job.message)}</p>}
        {originPlace ? (
          <section className="origin-status" aria-label="进货原点">
            <div className="origin-status-head">
              <strong>进货原点</strong>
              <button
                type="button"
                className="legend-toggle"
                onClick={clearLogisticsOrigin}
                disabled={originLockMessage !== null}
                title={originLockMessage ?? undefined}
              >清除</button>
            </div>
            <dl>
              <div><dt>经度</dt><dd>{originPlace.lng}°</dd></div>
              <div><dt>纬度</dt><dd>{originPlace.lat}°</dd></div>
            </dl>
            <p className="hud-note">优化时比较沿路运输距离。</p>
          </section>
        ) : (
          <section className="origin-status empty" aria-label="进货原点未设置">
            <strong>进货原点：未设置</strong>
            <p className="hud-note">本次优化不比较沿路运输距离。通过「编辑 → 进货原点」在地图上设置。</p>
          </section>
        )}
        {selected && (
          <p className="hud-note">方案 {edit.selectedIndex + 1}/{edit.poses.length}。点矩形或按 [ ] 切换。要移动时先点「调整方案」。</p>
        )}
        <p className="hud-note">范围 {edit.zones.length} 处，禁区 {edit.zones.filter((zone) => zone.kind === "exclusion").length}，可行域 {edit.zones.filter((zone) => zone.kind === "feasible").length}。禁区和可行域下面都可以选画圈或方框。画圈松手闭合。方框先点一角，再点对角线另一角。橡皮擦悬停高亮，点击删除，Ctrl+Z 恢复。</p>
        {edit.zones.map((zone) => (
          <button key={zone.id} type="button" className="legend-toggle" onClick={() => setEdit((current) => current.removeRegion(zone.id))}>
            删除 {zone.kind === "feasible" ? "可行域" : "禁区"} {zone.id}
          </button>
        ))}
        <p className="hud-keys">V 拖拽 · B 禁区 · Esc 取消 · Ctrl+Z 恢复擦除 · F 定位 · [ ] 切换方案 · P 开始优化</p>
        </>
        )}
      </aside>
      {notice && <p className={noticeFading ? "map-toast fading" : "map-toast"} role="status">{notice}</p>}
      {showSchemeCard && selected && (
        <SchemeCard
          key={selected.id}
          schemeId={selected.id}
          title={`方案 ${edit.selectedIndex + 1}/${edit.poses.length}${derivedLabel(edit, selected)}${recommendedIds.includes(selected.id) ? ` · 推荐第 ${recommendedIds.indexOf(selected.id) + 1} 名` : ""}`}
          card={schemeCard(selected, liveReport, origin !== null, edit.includeDemand)}
          azimuthDeg={azimuthDeg}
          evaluationState={evaluationState}
          evaluationError={evaluationError}
          adjusting={adjusting}
          canRestore={isChoiceEdited(selected)}
          onAzimuthChange={changeAzimuth}
          onAzimuthBlur={resetAzimuth}
          onRestore={restoreOriginal}
          anchor={schemeAnchor}
          onBoundsChange={setSchemeCardBounds}
          zIndex={floatingPanelZIndex(panelOrder, "scheme")}
          onBringToFront={() => bringToFront("scheme")}
          onClose={() => setSchemeCardOpen(false)}
          onAsk={() => {
            setAskPose({ id: selected.id, label: `方案 ${edit.selectedIndex + 1}/${edit.poses.length}`, nonce: Date.now() });
            bringToFront("agent");
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
      {recommended.length > 0 && (
        <div className="recommend-legend">
          <strong>助手推荐</strong>
          {recommended.map((item) => (
            <button key={item.id} type="button" onClick={() => {
              selectPoseAndOpen(item.id);
            }}>
              <i style={{ background: RECOMMEND_COLORS[item.rank - 1] }} />第 {item.rank} 名 · {item.name}
            </button>
          ))}
          <button type="button" className="recommend-clear" onClick={() => setRecommendedIds([])}>清除颜色</button>
        </div>
      )}
      {compared.length > 0 && (
        <ComparePanel
          items={compared}
          scale={edit.poses}
          includeDemand={edit.includeDemand}
          hasOrigin={origin !== null}
          panelMinimized={panelMinimized}
          zIndex={floatingPanelZIndex(panelOrder, "compare")}
          onBringToFront={() => bringToFront("compare")}
          onClear={() => setComparedIds([])}
        />
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
  schemeId,
  title,
  card,
  azimuthDeg,
  evaluationState,
  evaluationError,
  adjusting,
  canRestore,
  onAzimuthChange,
  onAzimuthBlur,
  onRestore,
  anchor,
  onBoundsChange,
  zIndex,
  onBringToFront,
  compared,
  onToggleCompare,
  onClose,
  onAsk,
  onChoose,
}: {
  schemeId: string;
  title: string;
  card: { decisions: StatusRow[]; objectives: StatusRow[] };
  azimuthDeg: string;
  evaluationState: EvaluationState;
  evaluationError: string;
  adjusting: boolean;
  canRestore: boolean;
  onAzimuthChange: (value: string) => void;
  onAzimuthBlur: () => void;
  onRestore: () => void;
  anchor: { x: number; y: number } | null;
  onBoundsChange: (bounds: SchemeCardBounds | null) => void;
  zIndex: number;
  onBringToFront: () => void;
  compared: boolean;
  onToggleCompare: () => void;
  onClose: () => void;
  onAsk: () => void;
  onChoose: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const lastBounds = useRef<ViewportRect | null>(null);
  const anchorKey = anchor ? anchor.x.toFixed(1) + ":" + anchor.y.toFixed(1) : "pending";
  const panel = useDraggablePanel(panelRef, {
    defaultSize: { width: 360, height: 540 },
    minSize: { width: 300, height: 280 },
    topInset: 148,
    resetKey: schemeId,
    positionKey: anchorKey,
    initialPosition: (bounds, size) => ({
      x: anchor ? anchor.x + 8 : (bounds.width - size.width) / 2,
      y: anchor ? anchor.y + 8 : 168,
    }),
  });
  const reportBounds = useCallback(() => {
    const node = panelRef.current;
    if (!node) return;
    const next = viewportRect(node.getBoundingClientRect());
    if (sameViewportRect(lastBounds.current, next)) return;
    lastBounds.current = next;
    onBoundsChange({ schemeId, bounds: next });
  }, [onBoundsChange, schemeId]);

  useLayoutEffect(() => {
    reportBounds();
  });

  useLayoutEffect(() => {
    const node = panelRef.current;
    if (!node) return;
    reportBounds();
    window.addEventListener("resize", reportBounds);
    window.addEventListener("scroll", reportBounds, true);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(reportBounds);
    observer?.observe(node);
    return () => {
      window.removeEventListener("resize", reportBounds);
      window.removeEventListener("scroll", reportBounds, true);
      observer?.disconnect();
      lastBounds.current = null;
      onBoundsChange(null);
    };
  }, [onBoundsChange, reportBounds]);

  return (
    <aside
      ref={panelRef}
      className={["scheme-card", panel.dragging ? "panel-dragging" : "", panel.resizing ? "panel-resizing" : ""].filter(Boolean).join(" ")}
      style={{ ...panel.style, zIndex }}
      onPointerDownCapture={onBringToFront}
      onFocusCapture={onBringToFront}
      onWheel={(event) => event.stopPropagation()}
    >
      <div className="scheme-card-head panel-drag-handle" {...panel.dragHandleProps}>
        <strong>{title}</strong>
        <button type="button" className="drawer-close" onClick={onClose}>关闭</button>
      </div>
      <div className="scheme-card-content">
        <p className="hud-kicker">决策变量</p>
        <dl className="hud-metrics">{card.decisions.map((row) => row.label === "方位角（宽边）"
          ? <div key={row.label} className="scheme-azimuth"><dt>{row.label}</dt><dd>
            <input
              type="number"
              min="0"
              max="360"
              step="1"
              aria-label="方位角（宽边）"
              value={azimuthDeg}
              onChange={(event) => onAzimuthChange(event.target.value)}
              onBlur={onAzimuthBlur}
            />
          </dd></div>
          : <Metric key={row.label} row={row} />)}</dl>
        <div className="hud-actions hud-edit-actions">
          <button type="button" onClick={onRestore} disabled={!canRestore}>恢复原始方案</button>
        </div>
        {evaluationState === "loading" && (
          <p className="hud-evaluation loading">{adjusting ? "调整中，松手后重新评价…" : "正在重新评价目标与约束…"}</p>
        )}
        {evaluationState === "success" && <p className="hud-evaluation success">目标与约束已重新评价</p>}
        {evaluationState === "error" && <p className="hud-evaluation error">重新评价失败：{evaluationError}</p>}
        <p className="hud-kicker">目标</p>
        <dl className="hud-metrics">{card.objectives.map((row) => <Metric key={row.label} row={row} />)}</dl>
        <div className="hud-actions">
          <button type="button" className="legend-toggle" onClick={onToggleCompare}>{compared ? "移出对比" : "加入对比"}</button>
          <button type="button" className="legend-toggle" onClick={onAsk}>问 AI</button>
          <button type="button" className="legend-toggle" onClick={onChoose}>记为我的选择</button>
        </div>
      </div>
      <button
        type="button"
        className="panel-resize"
        aria-label="调整方案详情面板大小"
        title="调整大小"
        {...panel.resizeHandleProps}
      />
    </aside>
  );
}

function viewportRect(rect: DOMRect): ViewportRect {
  return {
    left: rect.left,
    top: rect.top,
    right: rect.right,
    bottom: rect.bottom,
    width: rect.width,
    height: rect.height,
  };
}

function workspaceRect(node: HTMLDivElement): WorkspaceBounds {
  const rect = node.getBoundingClientRect();
  return {
    ...viewportRect(rect),
    width: Math.max(rect.width, node.scrollWidth),
    height: Math.max(rect.height, node.scrollHeight),
    scrollLeft: node.scrollLeft,
    scrollTop: node.scrollTop,
  };
}

function sameViewportRect(left: ViewportRect | null, right: ViewportRect): boolean {
  if (!left) return false;
  return Math.abs(left.left - right.left) < 0.5
    && Math.abs(left.top - right.top) < 0.5
    && Math.abs(left.right - right.right) < 0.5
    && Math.abs(left.bottom - right.bottom) < 0.5
    && Math.abs(left.width - right.width) < 0.5
    && Math.abs(left.height - right.height) < 0.5
    && Math.abs(((left as Partial<WorkspaceBounds>).scrollLeft ?? 0) - ((right as Partial<WorkspaceBounds>).scrollLeft ?? 0)) < 0.5
    && Math.abs(((left as Partial<WorkspaceBounds>).scrollTop ?? 0) - ((right as Partial<WorkspaceBounds>).scrollTop ?? 0)) < 0.5;
}

function samePoint(left: LocalPoint | null, right: LocalPoint | null): boolean {
  return left?.x === right?.x && left?.y === right?.y;
}

function Metric({ row }: { row: StatusRow }) {
  return <div><dt>{row.label}</dt><dd>{row.value}</dd></div>;
}

const COMPARE_COLORS = ["#39f3ff", "#ff8b96", "#ffd166", "#3dd68c", "#d78bff"];

function ComparePanel({
  items,
  scale,
  includeDemand,
  hasOrigin,
  panelMinimized,
  zIndex,
  onBringToFront,
  onClear,
}: {
  items: { id: string; name: string; choice: ParetoChoice }[];
  scale: readonly ParetoChoice[];
  includeDemand: boolean;
  hasOrigin: boolean;
  panelMinimized: boolean;
  zIndex: number;
  onBringToFront: () => void;
  onClear: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const panel = useDraggablePanel(panelRef, {
    defaultSize: { width: 680, height: 400 },
    minSize: { width: 420, height: 260 },
    topInset: 148,
    positionKey: panelMinimized ? "work-panel-minimized" : "work-panel-open",
    initialPosition: (bounds, size) => ({
      x: panelMinimized ? 18 : 380,
      y: bounds.height - size.height - 18,
    }),
  });
  const chart = compareChart(items, scale, includeDemand, hasOrigin);
  const width = 680;
  const height = 240;
  const padLeft = 44;
  const padRight = 44;
  const padTop = 12;
  const padBottom = 44;
  const span = Math.max(chart.labels.length - 1, 1);
  const inner = height - padTop - padBottom;
  const xAt = (index: number) => padLeft + (index * (width - padLeft - padRight)) / span;
  const yAt = (value: number) => height - padBottom - value * inner;

  return (
    <section
      ref={panelRef}
      className={["compare-panel", panel.dragging ? "panel-dragging" : "", panel.resizing ? "panel-resizing" : ""].filter(Boolean).join(" ")}
      style={{ ...panel.style, zIndex }}
      onPointerDownCapture={onBringToFront}
      onFocusCapture={onBringToFront}
      onWheel={(event) => event.stopPropagation()}
    >
      <div className="scheme-card-head panel-drag-handle" {...panel.dragHandleProps}>
        <strong>方案对比</strong>
        <button type="button" className="drawer-close" onClick={onClear}>清空</button>
      </div>
      <div className="compare-panel-body">
        <p className="hud-note">每条线是一个方案。各项都是越小越好，线越低越优。纵轴按这次全部帕累托方案固定，再加入一条线不会改动已经画出的线。</p>
        {items.length < 2 ? <p className="hud-note">再加入一个方案，折线才会叠在一起。</p> : (
          <svg
            className="compare-chart"
            viewBox={"0 0 " + width + " " + height}
            preserveAspectRatio="xMidYMid meet"
            role="img"
            aria-label="方案目标折线对比"
          >
            {chart.labels.map((label, index) => (
              <g key={label}>
                <line x1={xAt(index)} y1={padTop} x2={xAt(index)} y2={height - padBottom} stroke="currentColor" opacity="0.28" />
                <text x={xAt(index)} y={height - 14} textAnchor="middle" fill="currentColor" fontSize="22">{label}</text>
              </g>
            ))}
            {chart.series.map((series, seriesIndex) => {
              const points = series.values.flatMap((value, index) => (
                value === null ? [] : [xAt(index) + "," + yAt(value)]
              ));
              const color = COMPARE_COLORS[seriesIndex % COMPARE_COLORS.length];
              return <polyline key={series.id} points={points.join(" ")} fill="none" stroke={color} strokeWidth="2.5" />;
            })}
          </svg>
        )}
        <div className="compare-legend">
          {items.map((item, index) => (
            <span key={item.id}><i style={{ background: COMPARE_COLORS[index % COMPARE_COLORS.length] }} />{item.name}</span>
          ))}
        </div>
      </div>
      <button
        type="button"
        className="panel-resize"
        aria-label="调整方案对比面板大小"
        title="调整大小"
        {...panel.resizeHandleProps}
      />
    </section>
  );
}
function derivedLabel(edit: SiteEdit<ParetoChoice>, pose: ParetoChoice): string {
  if (!pose.derivedFrom) return "";
  const index = edit.poses.findIndex((item) => item.id === pose.derivedFrom);
  return index < 0 ? " · 局部优化" : ` · 由方案 ${index + 1} 局部优化`;
}

function localRing(points: readonly LocalPoint[]): [number, number][] {
  return points.map(({ x, y }) => [x, y]);
}

function agentMapPreview(
  edit: SiteEdit<ParetoChoice>,
  ops: readonly EditOp[] | null,
  layers: WorkspaceLayerState,
) {
  if (!ops) return emptyAgentPreview;
  try {
    const applied = applyOps(edit, ops, layers);
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
  undoErase: () => undefined,
  previous: () => undefined,
  next: () => undefined,
  optimize: () => undefined,
};

function formatAzimuthDegrees(theta: number): string {
  return widthAzimuthDeg(theta).toFixed(1);
}
