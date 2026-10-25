import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { cancelJob, createJob, createLanduseEdit, deleteExperiment, deleteLanduseEdit, deleteProtectedFarmland, fetchArtifactText, fetchConstructionFeasibilityOverlay, fetchPoseObjectives, fetchSiteReport, getExperiments, getJob, getLanduseEdits, getPlugins, getRoadSegments, getSceneLayerInfo, getScenes, pickLandusePatch } from "../api";
import type { ExperimentRecord, JobRecord, LanduseEdit, RoadSegment, SceneLayerInfo, SceneRecord, SiteReport } from "../api";
import { JOB_STATUS_LABEL, messageLabel } from "../run_status";
import { WorldMap } from "./world_map";
import type { WorldMapCapture } from "./world_map";
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
import type { FieldPolicy, ImportedSiteForm, RegionKind, SiteRegion } from "./site_edit";
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
import { activateSiteFrame, siteFrame } from "./site_frame";
import type { SiteFrame } from "./site_frame";
import { HistoryPanel } from "./history_panel";
import { SoftwareUpdateDialog, useSoftwareUpdate } from "./software_update_dialog";
import { MapToolbar } from "./map_toolbar";
import { exportSolutionsCsv, exportSolutionsJson } from "./solution_export";
import { FarmlandImportDialog } from "./farmland_import_dialog";
import { LayerPanel } from "./layer_panel";
import { FavoritePanel } from "./favorite_panel";
import { mergeDisplayedChoices, PARETO_LAYER_COLORS } from "./solution_diversity";
import type { ParetoLayer } from "./solution_diversity";
import { favoritePoseSnapshot, favoriteMatches } from "./favorite_points";
import type { FavoritePointInput } from "./favorite_points";
import { useFavoritePoints } from "./use_favorite_points";
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
import { FeasibilityImageCache, FEASIBILITY_PRELOAD_MAX_CELLS, LatestOverlayRequest, feasibilityCacheKey, feasibilityRequest, scheduleIdle } from "./feasibility_overlay";
import { SolutionGeneration } from "./solution_generation";
import {
  BUILD_SCENE_PLUGIN,
  DEFAULT_SIDE_LENGTH_M,
  builtSceneId,
  parseBuildSceneConfig,
  protectedFarmlandNotice,
  selectBuiltScene,
} from "./scene_build";
import { SceneBuildDialog } from "./scene_build_dialog";
import { SceneExportDialog } from "./scene_export_dialog";
import type { SceneExportDialogValue } from "./scene_export_dialog";
import {
  EXPORT_LAYERS,
  describeExportLayers,
  exportLegendRows,
  exportRankMarks,
  paretoLayerCounts,
  pngFilename,
  selectExportPoses,
} from "./scene_export";
import type { ExportLayerId } from "./scene_export";

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
  const initialEdit = useRef(edit);
  const editRef = useRef(edit);
  editRef.current = edit;
  const [diversityLevel, setDiversityLevel] = useState<ParetoLayer>(1);
  const diversityPool = useRef<readonly ParetoChoice[]>([]);
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
  // 尺寸在插件默认值读到之前留空，优化会因尺寸无效而拒绝提交。
  const [rectW, setRectW] = useState("");
  const [rectH, setRectH] = useState("");
  const [defaultSize, setDefaultSize] = useState<{ widthM: number; heightM: number } | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const jobRef = useRef(job);
  jobRef.current = job;
  const [jobStarting, setJobStarting] = useState(false);
  const jobStartingRef = useRef(false);
  const [focusToken, setFocusToken] = useState(0);
  const [scenes, setScenes] = useState<SceneRecord[]>([]);
  const [buildLat, setBuildLat] = useState("");
  const [buildLon, setBuildLon] = useState("");
  const [buildSide, setBuildSide] = useState(String(DEFAULT_SIDE_LENGTH_M));
  const [buildName, setBuildName] = useState("");
  const [buildFormError, setBuildFormError] = useState("");
  const [sceneBuildOpen, setSceneBuildOpen] = useState(false);
  const [sceneExportOpen, setSceneExportOpen] = useState(false);
  const [farmlandImportOpen, setFarmlandImportOpen] = useState(false);
  const [farmlandVisible, setFarmlandVisible] = useState(true);
  const [farmlandVersion, setFarmlandVersion] = useState(0);
  const [farmlandPreviewUrl, setFarmlandPreviewUrl] = useState<string | null>(null);
  const [farmlandDeleting, setFarmlandDeleting] = useState(false);
  const [exportingScene, setExportingScene] = useState(false);
  const [sceneExportError, setSceneExportError] = useState("");
  const buildRequest = useRef<Parameters<typeof createJob>[0]["config"] | null>(null);
  const [scene, setScene] = useState<SceneRecord | null>(null);
  const [sceneFrame, setSceneFrame] = useState<SiteFrame | null>(siteFrame);
  const [sceneVersion, setSceneVersion] = useState(0);
  const [shownClasses, setShownClasses] = useState(hiddenLanduseClasses);
  const [landuseEdits, setLanduseEdits] = useState<LanduseEdit[]>([]);
  const [landuseDraft, setLanduseDraft] = useState<LocalPoint[]>([]);
  const landuseDraftRef = useRef(landuseDraft);
  landuseDraftRef.current = landuseDraft;
  const [layersOpen, setLayersOpen] = useState(false);
  const [favoritesOpen, setFavoritesOpen] = useState(false);
  const favorites = useFavoritePoints(scene?.id ?? null, sceneFrame, setNotice);
  const {
    items: favoritePoints, selectedId: selectedFavoriteId,
    loading: favoritePointsLoading, saving: favoriteSaving, error: favoritePointsError,
    outOfRangeIds: favoriteOutOfRangeIds, overlays: favoriteOverlayPoints,
  } = favorites;
  const [layerInfo, setLayerInfo] = useState<SceneLayerInfo | null>(null);
  const [layerError, setLayerError] = useState("");
  const [demVisible, setDemVisible] = useState(false);
  const [demOpacity, setDemOpacity] = useState(0.6);
  const [roadsVisible, setRoadsVisible] = useState(false);
  const [roadSegments, setRoadSegments] = useState<RoadSegment[]>([]);
  const [roadError, setRoadError] = useState("");
  const [regionVisibility, setRegionVisibility] = useState<RegionVisibility>({ exclusion: true, feasible: true });
  const [feasibilityVisible, setFeasibilityVisible] = useState(false);
  const [feasibilityPreparing, setFeasibilityPreparing] = useState(false);
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
  const feasibilityImages = useRef(new FeasibilityImageCache(2, (url) => URL.revokeObjectURL(url)));
  const feasibilityShownKey = useRef<string | null>(null);
  const feasibilityActiveKey = useRef<string | null>(null);
  const feasibilityVisibleRef = useRef(false);
  const feasibilityPreloaded = useRef(new Set<string>());
  const feasibilityFlight = useRef<{
    key: string;
    controller: AbortController;
    token: number;
    opened: boolean;
    done: Promise<string | null>;
  } | null>(null);
  feasibilityVisibleRef.current = feasibilityVisible;
  const solutionGeneration = useRef(new SolutionGeneration());
  const mapCapture = useRef<WorldMapCapture | null>(null);
  const sceneExportToken = useRef(0);
  const exportingSceneRef = useRef(false);

  const selected = edit.selected;
  const selectedFavoriteSnapshot = selected && sceneFrame
    ? favoritePoseSnapshot(selected, selected.theta, edit.widthM, edit.heightM, sceneFrame) : null;
  const selectedAlreadyFavorite = selectedFavoriteSnapshot !== null && favoritePoints.some((item) => favoriteMatches(item, edit.sceneName, selectedFavoriteSnapshot));
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
  const showFeasibilityUrl = useCallback((key: string | null, next: string | null) => {
    feasibilityShownKey.current = key;
    feasibilityUrlRef.current = next;
    feasibilityImages.current.pin(next);
    setFeasibilityUrl(next);
  }, []);
  const feasibilityBody = useMemo(
    () => feasibilityRequest(edit.searchConfig()),
    [edit.sceneName, edit.mountainPolicy, edit.fieldPolicy, edit.fieldCost, edit.regions, edit.roadSetbackM, edit.waterSetbackM],
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
    if (favoritesOpen) bringToFront("favorites");
  }, [favoritesOpen, bringToFront]);

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
  const preparing = running && (job?.plugin_id === PREPARE_PLUGIN || job?.plugin_id === BUILD_SCENE_PLUGIN);
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

  function openSavedFavorite(saved: boolean) {
    if (!saved) return;
    setFavoritesOpen(true);
    setSchemeCardOpen(false);
    selectTool("pan");
  }

  async function saveFavorite(input: FavoritePointInput): Promise<void> {
    openSavedFavorite(await favorites.save(input));
  }

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

  async function refreshScene(selectedId = scene?.id ?? DEFAULT_SCENE) {
    const available = await getScenes();
    const nextScene = available.find((item) => item.id === selectedId)
      ?? available.find((item) => item.id === DEFAULT_SCENE)
      ?? available[0]
      ?? null;
    setScenes(available);
    setSceneFrame(nextScene?.frame ? activateSiteFrame(nextScene.frame) : null);
    setScene(nextScene);
    setSceneVersion((version) => version + 1);
  }

  function switchScene(next: SceneRecord, options?: { reload?: boolean; notice?: string }) {
    if (exportingSceneRef.current) {
      setNotice("正在生成图片，请稍候再切换场景。");
      return;
    }
    if (optimizationActive() || (!options?.reload && next.id === scene?.id)) return;
    const frame = next.frame ? activateSiteFrame(next.frame) : null;
    solutionGeneration.current.advance();
    const current = editRef.current;
    const reset = new SiteEdit<ParetoChoice>(
      next.id,
      current.widthM,
      current.heightM,
      current.mountainPolicy,
      current.fieldPolicy,
      current.fieldCost,
      [],
      [],
      [],
      null,
      [],
      current.includeDemand,
      current.diagonalAccess,
      current.roadSetbackM,
      current.waterSetbackM,
    );
    editRef.current = reset;
    diversityPool.current = [];
    setDiversityLevel(1);
    setEdit(reset);
    setSceneFrame(frame);
    setScene(next);
    setSceneVersion((version) => version + 1);
    setTool("pan");
    boxAnchor.current = null;
    erasedItem.current = null;
    setLanduseEdits([]);
    setLanduseDraftPoints([]);
    setLayerInfo(null);
    setLayerError("");
    setRoadSegments([]);
    setRoadError("");
    setShownClasses(hiddenLanduseClasses());
    setFarmlandDeleting(false);
    setFarmlandPreviewUrl(null);
    setFarmlandVisible(true);
    setDemVisible(false);
    setRoadsVisible(false);
    setFeasibilityVisible(false);
    setFeasibilityPreparing(false);
    showFeasibilityUrl(null, null);
    setReport(null);
    setAzimuthDeg("");
    setEvaluationState("idle");
    setEvaluationError("");
    setLoadedCaseId(null);
    setComparedIds([]);
    setRecommendedIds([]);
    setSchemeCardOpen(false);
    setSchemeAnchor(null);
    setSchemeTarget(null);
    setSchemeCardBounds(null);
    setPreviewOps(null);
    setAskPose(null);
    setAdjusting(false);
    setHistoryOpen(false);
    setPendingDeleteId(null);
    setFocusToken((token) => token + 1);
    setNotice(options?.notice ?? `已切换到${next.title}。${next.ready ? "场景可直接优化。" : "请先构建场景数据。"}`);
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
    diversityPool.current = [];
    setDiversityLevel(1);
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

  function changeDiversity(level: ParetoLayer) {
    if (running || adjusting || evaluationState === "loading") return;
    const current = editRef.current;
    diversityPool.current = mergeDisplayedChoices(diversityPool.current, current.poses);
    const visible = diversityPool.current.filter((choice) => (choice.paretoLayer ?? 1) <= level);
    const ids = new Set(visible.map((choice) => choice.id));
    const next = current.withPoses(visible);
    editRef.current = next;
    setEdit(next);
    setDiversityLevel(level);
    setComparedIds((items) => items.filter((id) => ids.has(id)));
    setRecommendedIds((items) => items.filter((id) => ids.has(id)));
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

  async function submitBuild() {
    if (optimizationActive()) return;
    const parsed = parseBuildSceneConfig({
      lat: buildLat,
      lon: buildLon,
      sideLengthM: buildSide,
      siteName: buildName,
    });
    if (!parsed.ok) {
      setBuildFormError(parsed.error);
      setNotice(parsed.error);
      return;
    }
    setBuildFormError("");
    setNotice("");
    const config: Record<string, unknown> = { ...parsed.config };
    buildRequest.current = config;
    try {
      await createTrackedJob({ plugin_id: BUILD_SCENE_PLUGIN, config });
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法构建场景");
    }
  }

  async function retryBuild() {
    const config = buildRequest.current;
    if (!config || optimizationActive()) {
      setNotice(config ? "已有任务在运行。" : "没有可以重试的构建参数。");
      return;
    }
    setNotice("");
    try {
      await createTrackedJob({ plugin_id: BUILD_SCENE_PLUGIN, config });
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法重试构建");
    }
  }

  async function prepareScene() {
    if (optimizationActive()) return;
    setNotice("");
    clearDisplayedSolutions(false, true);
    try {
      await createTrackedJob({
        plugin_id: PREPARE_PLUGIN,
        config: { scene_name: scene?.id ?? DEFAULT_SCENE, rebuild: true },
      });
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法构建场景数据");
    }
  }

  async function stopPrepare() {
    if (!job || (job.plugin_id !== PREPARE_PLUGIN && job.plugin_id !== BUILD_SCENE_PLUGIN)) return;
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
      const historyScene = await importedSceneName(experiment);
      if (!historyScene) throw new Error("这次历史结果没有记录 scene_name，不能安全导入当前地图。");
      if (historyScene !== scene?.id) {
        const owner = scenes.find((item) => item.id === historyScene)?.title ?? historyScene;
        throw new Error(`这次历史结果属于${owner}，不能导入${scene?.title ?? "当前场景"}。`);
      }
      const pool = await run.current.loadPareto(experimentId, true);
      const choices = pool.filter((choice) => choice.paretoLayer === 1);
      const size = await importedBuildingSize(experiment);
      if (!solutionGeneration.current.isCurrent(generation)) return;
      const form = await importedSiteForm(experiment);
      if (!solutionGeneration.current.isCurrent(generation)) return;
      setEdit((current) => {
        const sized = size ? current.withBuilding(size.widthM, size.heightM) : current;
        const restored = form ? sized.withImportedSiteForm(form) : sized;
        return restored.withPoses(choices);
      });
      diversityPool.current = pool;
      setDiversityLevel(1);
      if (size) {
        setRectW(String(size.widthM));
        setRectH(String(size.heightM));
      }
      if (form && typeof form.field_cost === "number") setFieldCost(String(form.field_cost));
      setComparedIds([]);
      setRecommendedIds([]);
      setSchemeCardOpen(schemeCardShouldOpen("automatic", choices.length > 0));
      setLoadedCaseId(experimentId);
      setFocusToken((token) => token + 1);
      setHistoryOpen(false);
      setNotice(form
        ? `已导入 ${experimentId}，共 ${choices.length} 个可行帕累托方案。`
        : `已导入 ${experimentId}，共 ${choices.length} 个可行帕累托方案。这次结果没有保存当时的约束，侧栏仍是当前设置。`);
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

  async function exportScenePng(value: SceneExportDialogValue) {
    if (exportingSceneRef.current) return;
    const currentScene = scene;
    if (!mapCapture.current || !currentScene || !sceneFrame || !sceneReady) {
      setSceneExportError("当前没有可导出的场景。");
      setNotice("当前没有可导出的场景。");
      return;
    }
    const token = sceneExportToken.current + 1;
    sceneExportToken.current = token;
    exportingSceneRef.current = true;
    setExportingScene(true);
    setSceneExportError("");
    setNotice("正在生成图片…");
    const pool = diversityPool.current;
    const poses = selectExportPoses(pool, value.pareto);
    const footprints = BuildingFootprint.layer(
      poses,
      { widthM: edit.widthM, heightM: edit.heightM },
      -1,
      value.showRecommendRanks ? recommendedIds : [],
    );
    const ranks = exportRankMarks(poses, recommendedIds, value.showRecommendRanks).map((mark) => ({
      rank: mark.rank,
      x: mark.x,
      y: mark.y,
      color: RECOMMEND_COLORS[mark.rank - 1] ?? RECOMMEND_COLORS[RECOMMEND_COLORS.length - 1],
    }));
    const haulPath = report?.haul_path ?? [];
    try {
      let feasibility: { url: string } | null = null;
      if (value.layers.feasibility) {
        const overlayKey = feasibilityCacheKey(currentScene.id, sceneVersion, farmlandVersion, feasibilityKey);
        const existing = feasibilityImages.current.get(overlayKey)
          ?? (feasibilityShownKey.current === overlayKey ? feasibilityUrlRef.current : null);
        const pending = feasibilityFlight.current?.key === overlayKey ? feasibilityFlight.current.done : null;
        if (existing) feasibility = { url: existing };
        else if (pending) {
          const url = await pending;
          if (sceneExportToken.current !== token) return;
          if (url) feasibility = { url };
        } else {
          const blob = await fetchConstructionFeasibilityOverlay(currentScene.id, feasibilityBody);
          if (sceneExportToken.current !== token) return;
          const url = URL.createObjectURL(blob);
          feasibilityImages.current.put(overlayKey, url);
          feasibilityImages.current.pin(url);
          if (feasibilityShownKey.current === overlayKey) showFeasibilityUrl(overlayKey, url);
          feasibility = { url };
        }
      }
      let segments = roadSegments;
      if (value.layers.osm && segments.length === 0 && layerInfo?.roads.available === true) {
        const loaded = await getRoadSegments(currentScene.id);
        if (sceneExportToken.current !== token) return;
        segments = loaded.segments;
      }
      if (scene?.id !== currentScene.id || !mapCapture.current) throw new Error("场景已切换，已取消导出。");
      const hasData: Record<ExportLayerId, boolean> = {
        satellite: true,
        dem: layerInfo?.dem.available === true,
        field: layerInfo?.landuse.field === true,
        "protected-farmland": farmlandPreviewUrl !== null || layerInfo?.protected_farmland?.available === true,
        building: layerInfo?.landuse.building === true,
        road: layerInfo?.landuse.road === true,
        water: layerInfo?.landuse.water === true,
        osm: segments.length > 0,
        feasibility: feasibility !== null,
        exclusion: edit.zones.some((zone) => zone.kind === "exclusion"),
        feasible: edit.zones.some((zone) => zone.kind === "feasible"),
        haul: haulPath.length > 0,
        origin: edit.origin !== null,
        favorites: favoriteOverlayPoints.length > 0,
      };
      const blob = await mapCapture.current.captureScene({
        extent: value.extent,
        satellite: value.layers.satellite,
        title: currentScene.title,
        legend: exportLegendRows({
          layers: EXPORT_LAYERS.map((item) => ({
            id: item.id,
            selected: value.layers[item.id],
            hasData: hasData[item.id],
          })),
          pareto: ([1, 2, 3] as const).map((layer) => ({
            layer,
            selected: value.pareto[layer],
            count: poses.filter((pose) => (pose.paretoLayer ?? 1) === layer).length,
          })),
        }),
        landuseVisible: {
          field: value.layers.field,
          building: value.layers.building,
          road: value.layers.road,
          water: value.layers.water,
        },
        dem: value.layers.dem,
        feasibility,
        roads: value.layers.osm,
        roadSegments: segments,
        regions: { exclusion: value.layers.exclusion, feasible: value.layers.feasible },
        haul: value.layers.haul,
        origin: value.layers.origin,
        favorites: value.layers.favorites,
        protectedFarmland: value.layers["protected-farmland"],
        footprints,
        ranks,
      });
      if (sceneExportToken.current !== token) return;
      const filename = pngFilename(value.filename, currentScene.title);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      setNotice(`已导出 ${filename}。`);
      setSceneExportOpen(false);
    } catch (reason) {
      if (sceneExportToken.current !== token) return;
      const message = reason instanceof Error ? reason.message : "无法导出图片";
      setSceneExportError(message);
      setNotice(message);
    } finally {
      feasibilityImages.current.pin(feasibilityUrlRef.current);
      if (sceneExportToken.current === token) {
        exportingSceneRef.current = false;
        setExportingScene(false);
      }
    }
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
    diversityPool.current = mergeDisplayedChoices(diversityPool.current, [...current.poses, ...added]);
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
        if (record.plugin_id === PREPARE_PLUGIN || record.plugin_id === BUILD_SCENE_PLUGIN) {
          if (followUp.current.opened(record.job_id, record.status)) {
            const available = await getScenes();
            setScenes(available);
            if (record.plugin_id === BUILD_SCENE_PLUGIN) {
              const next = selectBuiltScene(available, builtSceneId(record.result) ?? "");
              if (!next) {
                setNotice("场景已构建，但场景列表里没有它。");
                return;
              }
              const farmlandNotice = protectedFarmlandNotice(record.result);
              switchScene(next, {
                reload: true,
                notice: farmlandNotice
                  ? `场景已构建。${farmlandNotice}`
                  : "场景已构建。之后的优化会直接读取它，不会重新构建。",
              });
              return;
            }
            await refreshScene(String(record.config.scene_name ?? scene?.id ?? DEFAULT_SCENE));
            const farmlandNotice = protectedFarmlandNotice(record.result);
            setNotice(farmlandNotice
              ? `场景数据已更新。${farmlandNotice}`
              : "场景数据已更新。之后的优化会直接读取它，不会重新构建。");
          }
          return;
        }
        const experimentId = followUp.current.claimExperiment(record);
        if (!experimentId) return;
        if (String(record.config.scene_name ?? DEFAULT_SCENE) !== editRef.current.sceneName) return;
        resultGeneration = solutionGeneration.current.capture();
        const refine = refining.current?.jobId === record.job_id ? refining.current : null;
        const pool = await run.current.loadPareto(experimentId, !refine);
        const choices = pool.filter((choice) => (choice.paretoLayer ?? 1) === 1);
        if (!solutionGeneration.current.isCurrent(resultGeneration)) return;
        if (refine) {
          refining.current = null;
          mergeRefined(refine, experimentId, choices);
          return;
        }
        setEdit((current) => current.withPoses(choices));
        diversityPool.current = pool;
        setDiversityLevel(1);
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
    refreshScene(DEFAULT_SCENE).catch((reason) => {
      setNotice(reason instanceof Error ? reason.message : "无法读取场景");
    });
  }, []);

  useEffect(() => {
    getPlugins()
      .then(({ items }) => {
        const plugin = items.find((item) => item.id === GuidedDecisionRun.pluginId);
        if (!plugin) throw new Error("没有找到引导搜索插件。");
        const defaults = initialEdit.current.withFormDefaults(plugin.config_schema.properties ?? {});
        setDefaultSize({ widthM: defaults.widthM, heightM: defaults.heightM });
        if (editRef.current !== initialEdit.current) return;
        setEdit(defaults);
        setRectW(String(defaults.widthM));
        setRectH(String(defaults.heightM));
      })
      .catch((reason) => {
        setNotice(reason instanceof Error ? reason.message : "无法读取默认参数");
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
    setFarmlandDeleting(false);
    setFarmlandPreviewUrl(null);
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
    const sceneId = scene?.id;
    if (!sceneReady || !sceneId) {
      feasibilityFlight.current?.controller.abort();
      feasibilityFlight.current = null;
      feasibilityRequests.current.begin();
      showFeasibilityUrl(null, null);
      setFeasibilityPreparing(false);
      return;
    }
    const key = feasibilityCacheKey(sceneId, sceneVersion, farmlandVersion, feasibilityKey);
    feasibilityActiveKey.current = key;
    if (feasibilityFlight.current && feasibilityFlight.current.key !== key) {
      feasibilityFlight.current.controller.abort();
      feasibilityFlight.current = null;
      feasibilityRequests.current.begin();
    }
    const cached = feasibilityImages.current.get(key);
    if (cached) {
      if (feasibilityVisible) {
        if (feasibilityPreloaded.current.delete(key)) {
          console.info("construction_feasibility client=preload-hit");
        }
        showFeasibilityUrl(key, cached);
        setFeasibilityPreparing(false);
      }
      return;
    }
    if (feasibilityShownKey.current !== key) showFeasibilityUrl(key, null);
    const cells = (sceneFrame?.widthM ?? 0) * (sceneFrame?.heightM ?? 0);
    if (!feasibilityVisible) {
      setFeasibilityPreparing(false);
      if (defaultSize === null || cells > FEASIBILITY_PRELOAD_MAX_CELLS) return;
      if (feasibilityFlight.current?.key === key) return;
      return scheduleIdle(() => {
        if (feasibilityActiveKey.current !== key) return;
        if (feasibilityImages.current.get(key) || feasibilityFlight.current?.key === key) return;
        beginFeasibilityLoad(sceneId, false);
      });
    }
    const flight = feasibilityFlight.current;
    if (flight?.key === key) {
      if (!flight.opened) {
        flight.opened = true;
        console.info("construction_feasibility client=join");
      }
      setFeasibilityPreparing(true);
      return;
    }
    console.info("construction_feasibility client=compute");
    setFeasibilityPreparing(true);
    beginFeasibilityLoad(sceneId, true);

    function beginFeasibilityLoad(targetSceneId: string, opened: boolean) {
      const controller = new AbortController();
      const token = feasibilityRequests.current.begin();
      let resolveDone: (url: string | null) => void = () => undefined;
      const done = new Promise<string | null>((resolve) => {
        resolveDone = resolve;
      });
      feasibilityFlight.current = { key, controller, token, opened, done };
      fetchConstructionFeasibilityOverlay(targetSceneId, feasibilityBody, controller.signal)
        .then((blob) => {
          if (!feasibilityRequests.current.isCurrent(token)) {
            resolveDone(null);
            return;
          }
          const url = URL.createObjectURL(blob);
          feasibilityImages.current.put(key, url);
          const current = feasibilityFlight.current;
          const showIt = current?.token === token && current.opened;
          if (current?.token === token) {
            if (!current.opened) feasibilityPreloaded.current.add(key);
            feasibilityFlight.current = null;
          }
          if (showIt && feasibilityActiveKey.current === key) {
            showFeasibilityUrl(key, url);
            setFeasibilityPreparing(false);
          }
          resolveDone(url);
        })
        .catch(() => {
          const stale = controller.signal.aborted || !feasibilityRequests.current.isCurrent(token);
          const current = feasibilityFlight.current;
          const showIt = !stale && current?.token === token && current.opened;
          if (current?.token === token) feasibilityFlight.current = null;
          if (showIt && feasibilityActiveKey.current === key) {
            showFeasibilityUrl(key, null);
            setFeasibilityPreparing(false);
          }
          resolveDone(null);
        });
    }
  }, [
    feasibilityVisible,
    sceneReady,
    scene?.id,
    sceneVersion,
    farmlandVersion,
    feasibilityKey,
    feasibilityBody,
    sceneFrame,
    defaultSize,
    showFeasibilityUrl,
  ]);

  useEffect(() => () => {
    feasibilityFlight.current?.controller.abort();
    feasibilityRequests.current.begin();
    feasibilityImages.current.releaseAll();
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
        if (!stopped) setRoadError(reason instanceof Error ? reason.message : "无法读取道路网络");
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
    edit.diagonalAccess,
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
      {sceneFrame ? <WorldMap
        key={scene?.id ?? "loading"}
        frame={sceneFrame}
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
        showLanduseOutlines={currentLanduseEditClass !== null || tool === "erase" || previewOps !== null}
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
        feasibilityLayer={feasibilityUrl ? {
          url: feasibilityUrl,
          visible: feasibilityVisible,
        } : null}
        protectedFarmlandLayer={sceneReady && scene && (farmlandPreviewUrl || layerInfo?.protected_farmland?.available) ? {
          url: farmlandPreviewUrl ?? `/api/v1/scenes/${scene.id}/protected-farmland-overlay?v=${farmlandVersion}`,
          visible: farmlandPreviewUrl !== null || farmlandVisible,
        } : null}
        roadSegments={roadSegments}
        roadsVisible={roadsVisible}
        regionVisibility={regionVisibility}
        haulPath={(report?.haul_path ?? []).map(([x, y]) => ({ x, y }))}
        origin={origin}
        favoritePoints={favoriteOverlayPoints}
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
        onCreateFavorite={(point) => {
          const { widthM, heightM } = editRef.current;
          void favorites.addAt(point, widthM, heightM).then(openSavedFavorite);
        }}
        onSelectFavorite={(id) => {
          favorites.select(id);
          setFavoritesOpen(true);
          setSchemeCardOpen(false);
          bringToFront("favorites");
        }}
        onPreviewFavoriteMove={favorites.previewMove}
        onFinishFavoriteEdit={() => void favorites.finishMove()}
        captureRef={mapCapture}
        onBoxClick={clickBox}
        onBoxMove={previewBox}
        onEraseOrigin={clearLogisticsOrigin}
        onEraseZone={eraseRegion}
        onEraseFavorite={(id) => void favorites.remove(id)}
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
      /> : (
        <div className="map-viewport-shell map-unavailable" role="status">
          当前场景缺少可用的 reference GeoTIFF 或 landuse 网格；请补齐四份原始文件后构建场景数据。
        </div>
      )}
      <SchemeConnector
        target={schemeTarget?.schemeId === selected?.id ? schemeTarget : null}
        cardBounds={schemeCardBounds && schemeCardBounds.schemeId === selected?.id ? schemeCardBounds.bounds : null}
        workspaceBounds={workspaceBounds}
        visible={showSchemeCard}
      />
      <header className="hud-top">
        <div>
          <p>温州电力设计院</p>
          <strong>{scene ? `${scene.title}选址规划` : "选址规划"}</strong>
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
        scenes={scenes}
        sceneId={scene?.id ?? null}
        onSceneChange={(sceneId) => {
          const next = scenes.find((item) => item.id === sceneId);
          if (next) switchScene(next);
        }}
        sceneSwitchDisabled={running || exportingScene}
        sceneLabel={preparing ? "终止构建" : "准备当前场景数据"}
        sceneDisabled={!preparing && running}
        onPrepare={() => void (preparing ? stopPrepare() : prepareScene())}
        onNewScene={() => setSceneBuildOpen(true)}
        onImportData={() => setFarmlandImportOpen(true)}
        importDataDisabled={!sceneReady}
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
        onExportScenePng={() => {
          setSceneExportError("");
          setSceneExportOpen(true);
        }}
        sceneExportDisabled={!sceneReady || exportingScene}
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
        favoriteAdjustDisabled={selectedFavoriteId === null || favoritePointsLoading || favoriteSaving}
      />
      <SceneBuildDialog
        open={sceneBuildOpen}
        lat={buildLat}
        lon={buildLon}
        side={buildSide}
        name={buildName}
        onLat={(value) => { setBuildFormError(""); setBuildLat(value); }}
        onLon={(value) => { setBuildFormError(""); setBuildLon(value); }}
        onSide={(value) => { setBuildFormError(""); setBuildSide(value); }}
        onName={(value) => { setBuildFormError(""); setBuildName(value); }}
        submitDisabled={running}
        formError={buildFormError}
        job={job?.plugin_id === BUILD_SCENE_PLUGIN ? job : null}
        onClose={() => setSceneBuildOpen(false)}
        onSubmit={() => void submitBuild()}
        onRetry={() => void retryBuild()}
        onStop={() => void stopPrepare()}
      />
      <FarmlandImportDialog
        open={farmlandImportOpen}
        sceneId={scene?.id ?? null}
        sceneTitle={scene?.title ?? ""}
        onClose={() => setFarmlandImportOpen(false)}
        onPreview={(preview) => setFarmlandPreviewUrl(preview?.url ?? null)}
        onCommitted={(message) => {
          setFarmlandVisible(true);
          setFarmlandVersion((version) => version + 1);
          setNotice(message);
          if (scene) {
            getSceneLayerInfo(scene.id).then(setLayerInfo).catch((reason) => {
              setLayerError(reason instanceof Error ? reason.message : "无法读取图层资源");
            });
          }
        }}
      />
      <SceneExportDialog
        open={sceneExportOpen}
        sceneTitle={scene?.title ?? ""}
        layers={describeExportLayers({
          satellite: { available: sceneReady, visible: true, reason: "场景尚未准备完成" },
          dem: {
            available: layerInfo?.dem.available === true,
            visible: demVisible,
            reason: layerInfo?.dem.error || (layerInfo ? "当前场景没有 DEM 高程" : "正在读取图层资源"),
          },
          field: {
            available: layerInfo?.landuse.field === true,
            visible: shownClasses.field,
            reason: layerInfo ? "当前场景没有农田" : "正在读取图层资源",
          },
          "protected-farmland": {
            available: layerInfo?.protected_farmland?.available === true,
            visible: farmlandVisible,
            reason: layerInfo ? "尚未导入永久基本农田" : "正在读取图层资源",
          },
          building: {
            available: layerInfo?.landuse.building === true,
            visible: shownClasses.building,
            reason: layerInfo ? "当前场景没有已有建筑" : "正在读取图层资源",
          },
          road: {
            available: layerInfo?.landuse.road === true,
            visible: shownClasses.road,
            reason: layerInfo ? "当前场景没有遥感道路" : "正在读取图层资源",
          },
          water: {
            available: layerInfo?.landuse.water === true,
            visible: shownClasses.water,
            reason: layerInfo ? "当前场景没有水体" : "正在读取图层资源",
          },
          osm: {
            available: layerInfo?.roads.available === true,
            visible: roadsVisible,
            reason: layerInfo?.roads.error || (layerInfo ? "当前场景没有道路网络" : "正在读取图层资源"),
          },
          feasibility: { available: sceneReady, visible: feasibilityVisible, reason: "场景尚未准备完成" },
          exclusion: {
            available: edit.zones.some((zone) => zone.kind === "exclusion"),
            visible: regionVisibility.exclusion,
            reason: "当前没有手绘禁区",
          },
          feasible: {
            available: edit.zones.some((zone) => zone.kind === "feasible"),
            visible: regionVisibility.feasible,
            reason: "当前没有手绘可行域",
          },
          haul: { available: (report?.haul_path?.length ?? 0) > 0, visible: true, reason: "当前没有进站路径" },
          origin: { available: origin !== null, visible: true, reason: "当前没有进货原点" },
          favorites: { available: favoriteOverlayPoints.length > 0, visible: true, reason: "当前没有收藏站址" },
        })}
        paretoCounts={paretoLayerCounts(diversityPool.current)}
        busy={exportingScene}
        error={sceneExportError}
        onClose={() => { if (!exportingScene) setSceneExportOpen(false); }}
        onExport={(value) => void exportScenePng(value)}
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
        feasibilityPreparing={feasibilityPreparing}
        farmlandVisible={farmlandVisible}
        farmlandDeleting={farmlandDeleting}
        onClose={() => setLayersOpen(false)}
        onToggleClass={(id) => setShownClasses((current) => ({ ...current, [id]: !current[id] }))}
        onToggleDem={() => setDemVisible((visible) => !visible)}
        onDemOpacity={setDemOpacity}
        onToggleRoads={() => setRoadsVisible((visible) => !visible)}
        onToggleRegion={(kind) => setRegionVisibility((current) => ({ ...current, [kind]: !current[kind] }))}
        onToggleFeasibility={() => setFeasibilityVisible((visible) => !visible)}
        onToggleFarmland={() => setFarmlandVisible((visible) => !visible)}
        onReplaceFarmland={() => {
          setFarmlandDeleting(false);
          setFarmlandImportOpen(true);
        }}
        onDeleteFarmland={() => {
          if (!scene || layerInfo?.protected_farmland?.available !== true) return;
          if (!farmlandDeleting) {
            setFarmlandDeleting(true);
            return;
          }
          void deleteProtectedFarmland(scene.id).then(() => {
            setFarmlandDeleting(false);
            setFarmlandVersion((version) => version + 1);
            setNotice("已删除永久基本农田。");
            return getSceneLayerInfo(scene.id).then(setLayerInfo);
          }).catch((reason) => {
            setFarmlandDeleting(false);
            setNotice(reason instanceof Error ? reason.message : "无法删除永久基本农田");
          });
        }}
      />
      <FavoritePanel
        open={favoritesOpen}
        zIndex={floatingPanelZIndex(panelOrder, "favorites")}
        sceneTitle={scene?.title ?? "未选择场景"}
        frame={sceneFrame}
        config={edit.searchConfig()}
        sceneVersion={sceneVersion}
        ready={sceneReady}
        busy={favoriteSaving}
        favorites={favoritePoints.filter((favorite) => favorite.scene_id === scene?.id)}
        selectedId={selectedFavoriteId}
        outOfRangeIds={favoriteOutOfRangeIds}
        loading={favoritePointsLoading}
        error={favoritePointsError}
        onBringToFront={() => bringToFront("favorites")}
        onClose={() => setFavoritesOpen(false)}
        onSelect={favorites.select}
        onAdjust={(favoriteId) => {
          favorites.select(favoriteId);
          selectTool("favorite-adjust");
        }}
        onUpdate={favorites.rotate}
        onDelete={favorites.remove}
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
          <p className="hud-kicker">选址优化</p>
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
        <p className="hud-note">{scene ? `${scene.title} · ${scene.ready ? "已准备" : "尚未构建"}` : "正在读取场景"}</p>
        <label>变电站长度（m）<input value={rectW} onChange={(event) => setRectW(event.target.value)} /></label>
        <label>变电站宽度（m）<input value={rectH} onChange={(event) => setRectH(event.target.value)} /></label>
        <p className="hud-note">
          {defaultSize
            ? `110 kV 变电站默认占地尺寸：长 ${defaultSize.widthM} m × 宽 ${defaultSize.heightM} m，可修改。`
            : "正在读取默认占地尺寸"}
        </p>
        <label className="hud-check">
          <input
            type="checkbox"
            checked={edit.includeDemand}
            onChange={(event) => setEdit((current) => current.withIncludeDemand(event.target.checked))}
          />
          比较需求点距离（预留接口）
        </label>
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
        <label>道路最小退距（m）
          <input
            type="number"
            min={0}
            step="any"
            value={edit.roadSetbackM}
            onChange={(event) => {
              if (event.target.value.trim() === "") return;
              const value = Number(event.target.value);
              if (!Number.isFinite(value) || value < 0) return;
              setEdit((current) => current.withRoadSetback(value));
            }}
          />
        </label>
        <label>水体最小退距（m）
          <input
            type="number"
            min={0}
            step="any"
            value={edit.waterSetbackM}
            onChange={(event) => {
              if (event.target.value.trim() === "") return;
              const value = Number(event.target.value);
              if (!Number.isFinite(value) || value < 0) return;
              const next = editRef.current.withWaterSetback(value);
              if (next.waterSetbackM === editRef.current.waterSetbackM) return;
              const ids = next.poses.map((pose) => pose.id);
              if (ids.length > 0) markMoved(next, ids);
              else setEdit(next);
            }}
          />
        </label>
        <section className="solution-diversity" aria-label="方案多样性">
          <label htmlFor="solution-diversity">方案多样性 <strong>{diversityLevel} 档</strong></label>
          <input id="solution-diversity" type="range" min="1" max="3" step="1"
            value={diversityLevel} aria-valuetext={`显示前 ${diversityLevel} 层帕累托方案`}
            disabled={running || adjusting || evaluationState === "loading" || diversityPool.current.length === 0}
            onChange={(event) => changeDiversity(Number(event.target.value) as ParetoLayer)} />
          <div className="diversity-ticks" aria-hidden="true"><span>少 · 1</span><span>2</span><span>3 · 多</span></div>
          <div className="diversity-legend">{PARETO_LAYER_COLORS.map((color, index) => (
            <span key={color} className={index < diversityLevel ? "" : "muted"}>
              <i style={{ backgroundColor: color }} />第 {index + 1} 层 · {diversityPool.current.filter((choice) => (choice.paretoLayer ?? 1) === index + 1).length}
            </span>
          ))}</div>
        </section>
        <div className="hud-actions hud-optimize-actions">
          <button type="button" className="primary" onClick={() => void startOptimization()} disabled={running || !sceneReady}>
            {running && !preparing ? "正在优化…" : "开始优化"}
          </button>
          <button type="button" onClick={clearDisplayedSolutionsFromUi} disabled={running || edit.poses.length === 0}>清空方案</button>
        </div>
        {job && job.plugin_id !== BUILD_SCENE_PLUGIN && <p className="hud-note">{JOB_STATUS_LABEL[job.status]} · {messageLabel(job.message)}</p>}
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
          title={`方案 ${edit.selectedIndex + 1}/${edit.poses.length} · 第 ${selected.paretoLayer ?? 1} 层${derivedLabel(edit, selected)}${recommendedIds.includes(selected.id) ? ` · 推荐第 ${recommendedIds.indexOf(selected.id) + 1} 名` : ""}`}
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
          favoriteSaving={favoriteSaving}
          isFavorite={selectedAlreadyFavorite}
          onFavorite={() => { if (selectedFavoriteSnapshot) void saveFavorite(selectedFavoriteSnapshot); }}
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

async function importedSiteForm(experiment: ExperimentRecord | undefined): Promise<ImportedSiteForm | null> {
  const url = experiment?.artifacts.find((item) => item.name === "site_form_snapshot.json")?.url;
  if (!url) return null;
  return JSON.parse(await fetchArtifactText(url)) as ImportedSiteForm;
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

async function importedSceneName(experiment: ExperimentRecord | undefined): Promise<string | null> {
  for (const name of ["site_form_snapshot.json", "resolved_config.json"]) {
    const url = experiment?.artifacts.find((item) => item.name === name)?.url;
    if (!url) continue;
    try {
      const value = JSON.parse(await fetchArtifactText(url)) as { scene_name?: unknown };
      if (typeof value.scene_name === "string" && value.scene_name) return value.scene_name;
    } catch {
      return null;
    }
  }
  return null;
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
  onFavorite,
  favoriteSaving,
  isFavorite,
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
  onFavorite: () => void;
  favoriteSaving: boolean;
  isFavorite: boolean;
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
          <button type="button" className="legend-toggle" onClick={onFavorite} disabled={favoriteSaving || isFavorite}>
            {favoriteSaving ? "收藏中…" : isFavorite ? "已收藏" : "收藏站址"}
          </button>
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
