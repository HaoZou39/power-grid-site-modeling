import { RoutingWorkspace } from "../routing/routing_workspace";
import type { RoutingMapState } from "../routing/routing_layer";
import { SetbackInput } from "./setback_input";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ApiRequestError, cancelJob, createJob, deleteExperiment, deleteProtectedFarmland, deleteScene, fetchArtifactText, fetchConstructionFeasibilityOverlay, fetchPoseObjectives, fetchSiteReport, getAdminBoundaries, getExperiments, getJob, getLanduseEdits, getPlugins, getRoadSegments, getSceneLayerInfo, getScenes, pickLandusePatch, replaceLanduseEdits } from "../api";
import type { AdminBoundaryCollection, ExperimentRecord, JobRecord, RoadSegment, SceneLayerInfo, SceneRecord, SiteReport } from "../api";
import { mapJobStatusLine } from "../run_status";
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
  manualChoice,
  placeDescription,
  refineSquare,
  refinedChoices,
  restoreChoice,
  rotateChoice,
  presentChoice,
  schemeCard,
  STALE,
  unmeasured,
  widthAzimuthDeg,
} from "./decision_run";
import type { StatusRow } from "./decision_run";
import type { ParetoChoice } from "./decision_run";
import { acceptImportedPoses, autoPendingPoses, batches, evaluationKey, isAwaitingReview, poseFreshness, stalePoses } from "./pose_evaluation";
import { SiteEdit, rectangleCorners } from "./site_edit";
import type { FieldPolicy, ImportedSiteForm, RegionKind, SiteRegion } from "./site_edit";
import { siteReportFailureNotice } from "./site_report_feedback";
import { ExclusionZone } from "./exclusion_sketch";
import { RECOMMEND_COLORS, adminBoundaryLabels, emptyAgentPreview } from "./site_overlay";
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
import { activateSiteFrame, clampFootprintCenter, siteFrame } from "./site_frame";
import type { SiteFrame } from "./site_frame";
import { HistoryPanel } from "./history_panel";
import { SoftwareUpdateDialog, useSoftwareUpdate } from "./software_update_dialog";
import { MapToolbar } from "./map_toolbar";
import { exportSolutionsCsv, exportSolutionsJson } from "./solution_export";
import { SceneDataImportDialog } from "./scene_data_import_dialog";
import { saveExperiment } from "../api";
import { experimentSaveBody } from "./save_experiment";
import { SaveExperimentDialog } from "./save_experiment_dialog";
import type { ImportMapPreview } from "./scene_data_import_dialog";
import { LayerPanel } from "./layer_panel";
import { FavoritePanel } from "./favorite_panel";
import { mergeDisplayedChoices, PARETO_LAYER_COLORS, visibleAtLevel } from "./solution_diversity";
import type { ParetoLayer } from "./solution_diversity";
import { bearingToTheta, favoritePoseSnapshot, favoriteMatches } from "./favorite_points";
import type { FavoritePointInput } from "./favorite_points";
import { useFavoritePoints } from "./use_favorite_points";
import { readMapTheme, toggleMapTheme, writeMapTheme } from "./theme";
import type { MapTheme } from "./theme";
import { LANDUSE_CLASSES, hiddenLanduseClasses, isLanduseSketchTool, landuseEditClass, regionKind } from "./toolbar_commands";
import type { MapToolName } from "./toolbar_commands";
import { landuseEditClassId } from "./landuse_sketch";
import {
  LANDUSE_DRAFT_NOTICE,
  LANDUSE_PREVIEW_NOTE,
  LANDUSE_REFRESH_WARNING,
  WATER_CORRECTION_PREVIEW_NOTE,
  WATER_TO_OTHER,
  acceptPublishedLanduse,
  addLanduseDraft,
  beginLanduseSave,
  completeLanduseSave,
  conflictLanduseSave,
  discardLanduseDraft,
  emptyLanduseDraft,
  failLanduseSave,
  isWaterCorrection,
  landuseComputeBlocked,
  landusePreviewMarks,
  landuseSaveEnabled,
  landuseSceneSwitch,
  newLanduseEditId,
  noteLanduseScene,
  parseLanduseEdit,
  redoLanduseDraft,
  reloadPublishedLanduse,
  removeLanduseDraft,
  undoLanduseDraft,
} from "./landuse_draft";
import {
  PARETO_LAYER_NOTE,
  afterLandusePublish,
  computeFailedAfterSave,
  computeStoppedNotice,
  createActionGate,
  siteReportAllowed,
  type LandusePublishOutcome,
} from "./landuse_compute";
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
import { rectToSceneConfig } from "./scene_rect_select.js";
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
type EvaluationState = "idle" | "loading" | "success" | "error" | "stale";
type ErasedItem =
  | { kind: "region"; region: SiteRegion }
  | { kind: "origin"; point: LocalPoint };

/** Decision map. Scene data is prepared once. Optimization only reads that scene. */
export function MapWorkspace({ health }: { health: string }) {
  const [problemType, setProblemType] = useState<"site" | "routing">("site");
  const [routingLayer, setRoutingLayer] = useState<RoutingMapState | null>(null);
  const [routingBusy, setRoutingBusy] = useState(false);
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
  const [submittingShownJob, setSubmittingShownJob] = useState(false);
  const jobStartingRef = useRef(false);
  const [focusToken, setFocusToken] = useState(0);
  const [scenes, setScenes] = useState<SceneRecord[]>([]);
  const [buildLat, setBuildLat] = useState("");
  const [buildLon, setBuildLon] = useState("");
  const [buildSide, setBuildSide] = useState(String(DEFAULT_SIDE_LENGTH_M));
  const [buildName, setBuildName] = useState("");
  const [buildFormError, setBuildFormError] = useState("");
  const [sceneBuildOpen, setSceneBuildOpen] = useState(false);
  const [rectSelecting, setRectSelecting] = useState(false);
  const [sceneExportOpen, setSceneExportOpen] = useState(false);
  const [farmlandImportOpen, setFarmlandImportOpen] = useState(false);
  const [farmlandVisible, setFarmlandVisible] = useState(false);
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
  const [landuseState, setLanduseState] = useState(emptyLanduseDraft);
  const landuseStateRef = useRef(landuseState);
  landuseStateRef.current = landuseState;
  const [landuseAwaitingReview, setLanduseAwaitingReview] = useState(false);
  const [pendingSceneSwitch, setPendingSceneSwitch] = useState<{ next: SceneRecord; options?: { reload?: boolean; notice?: string } } | null>(null);
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
  const layerInfoRef = useRef(layerInfo);
  layerInfoRef.current = layerInfo;
  const [layerError, setLayerError] = useState("");
  const [demVisible, setDemVisible] = useState(false);
  const [demOpacity, setDemOpacity] = useState(0.6);
  const [roadsVisible, setRoadsVisible] = useState(false);
  const [roadSegments, setRoadSegments] = useState<RoadSegment[]>([]);
  const [roadKinds, setRoadKinds] = useState<number[]>([]);
  const [adminBoundariesVisible, setAdminBoundariesVisible] = useState(true);
  const [adminBoundaries, setAdminBoundaries] = useState<AdminBoundaryCollection | null>(null);
  const [adminBoundaryError, setAdminBoundaryError] = useState("");
  const [importPreview, setImportPreview] = useState<ImportMapPreview | null>(null);
  const [roadError, setRoadError] = useState("");
  const [regionVisibility, setRegionVisibility] = useState<RegionVisibility>({ exclusion: true, feasible: true });
  const [feasibilityVisible, setFeasibilityVisible] = useState(false);
  const [feasibilityPreparing, setFeasibilityPreparing] = useState(false);
  const [feasibilityUrl, setFeasibilityUrl] = useState<string | null>(null);
  const [fieldCost, setFieldCost] = useState("0.5");
  const [report, setReport] = useState<SiteReport | null>(null);
  const [azimuthDeg, setAzimuthDeg] = useState("");
  const azimuthEditing = useRef(false);
  const azimuthPoseId = useRef<string | undefined>(undefined);
  const evaluationInFlight = useRef(new Set<string>());
  const evaluationFailed = useRef(new Map<string, string>());
  const reevaluatingRef = useRef(false);
  const [reevaluating, setReevaluating] = useState(false);
  const actionGate = useRef(createActionGate());
  const sceneRevisionOverride = useRef<{ sceneId: string; revision: string } | null>(null);
  const [paretoLayerNote, setParetoLayerNote] = useState("");
  const [evaluationRevision, setEvaluationRevision] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [saveExperimentOpen, setSaveExperimentOpen] = useState(false);
  const [savingExperiment, setSavingExperiment] = useState(false);
  const savingExperimentRef = useRef(false);
  const [saveExperimentError, setSaveExperimentError] = useState("");
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
  const refining = useRef<{ jobId: string; origin: ParetoChoice; hasOrigin: boolean; includeDemand: boolean; edit: SiteEdit<ParetoChoice> } | null>(null);
  const dragStart = useRef<{ id: string; x: number; y: number } | null>(null);
  const erasedItem = useRef<ErasedItem | null>(null);
  const landuseUndoPreferred = useRef(false);
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
  const retainedCount = mergeDisplayedChoices(diversityPool.current, edit.poses).length;
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
    [edit.sceneName, edit.mountainPolicy, edit.fieldPolicy, edit.fieldCost, edit.regions, edit.roadSetbackM, edit.waterSetbackM, edit.highwaySetbackM],
  );
  const feasibilityKey = useMemo(
    () => JSON.stringify(feasibilityBody),
    [feasibilityBody],
  );

  const publishedRevision = layerInfo && layerInfo.scene_id === scene?.id ? layerInfo.data_version?.scene_revision : undefined;
  if (
    sceneRevisionOverride.current
    && (sceneRevisionOverride.current.sceneId !== scene?.id || publishedRevision === sceneRevisionOverride.current.revision)
  ) {
    sceneRevisionOverride.current = null;
  }
  const dataVersion = {
    road_product_id: layerInfo?.roads.road_product_id ?? "",
    farmland_content_sha256: layerInfo?.protected_farmland?.content_sha256 ?? "",
    ...layerInfo?.data_version,
    ...(sceneRevisionOverride.current ? { scene_revision: sceneRevisionOverride.current.revision } : {}),
  };
  const evaluationSnapshot = useRef({ sceneId: scene?.id, dataVersion });
  evaluationSnapshot.current = { sceneId: scene?.id, dataVersion };
  const keyOf = (pose: ParetoChoice, current = edit) => evaluationKey(
    scene?.id ?? current.sceneName, { ...current.searchConfig(), ...dataVersion }, pose,
  );
  const freshnessOf = (pose: ParetoChoice, current = edit) => poseFreshness(
    pose.evaluatedFor, scene?.id ?? current.sceneName, { ...current.searchConfig(), ...dataVersion }, pose,
  );
  const staleRetained = stalePoses(
    mergeDisplayedChoices(diversityPool.current, edit.poses),
    (pose) => freshnessOf(pose),
  );
  const selectedKey = selected ? keyOf(selected) : "";
  const evaluationError = evaluationFailed.current.get(selectedKey) ?? "";
  const selectedFreshness = selected ? freshnessOf(selected) : "current";
  const evaluationState: EvaluationState = !selected || scene?.read_only ? "idle"
    : isAwaitingReview(selectedFreshness)
      ? evaluationError ? "error" : evaluationInFlight.current.has(selectedKey) ? "loading" : "stale"
      : adjusting || selected.evaluatedFor !== selectedKey ? evaluationError ? "error" : "loading"
      : selected.reevaluated ? "success" : "idle";

  useLayoutEffect(() => {
    if (!defaultSize || !scene?.ready || scene.read_only || !layerInfo || layerInfo.scene_id !== scene.id) return;
    if (reevaluatingRef.current || landuseComputeBlocked(landuseStateRef.current)) return;
    const candidates = edit.poses.filter((pose) => !(adjusting && pose.id === edit.selectedPoseId));
    const inputs = { ...edit.searchConfig(), ...dataVersion };
    const pending = autoPendingPoses(
      candidates,
      (pose) => keyOf(pose),
      evaluationInFlight.current,
      evaluationFailed.current,
      (pose) => poseFreshness(pose.evaluatedFor, scene.id, inputs, pose),
    );
    if (!pending.length) return;
    const pendingIds = new Set(pending.map((pose) => pose.id));
    const { scene_name: _scene, ...config } = edit.searchConfig();
    const requestedScene = scene.id;
    const requests = batches(pending).map((poses) => ({ poses, keys: poses.map((pose) => keyOf(pose)) }));
    requests.forEach(({ keys }) => keys.forEach((key) => evaluationInFlight.current.add(key)));
    setEdit((current) => current.withPoses(current.poses.map((pose) => (
      pendingIds.has(pose.id) && pose.demSoft !== "重算中" ? unmeasured(pose) : pose
    ))));
    void (async () => {
      for (const { poses, keys } of requests) {
        try {
          const { items } = await fetchPoseObjectives(requestedScene, {
            ...config, poses: poses.map(({ x, y, theta }) => ({ x, y, theta })),
          });
          if (items.length !== poses.length) throw new Error("评价返回的方案数量不一致。");
          setEdit((current) => {
            const latest = evaluationSnapshot.current;
            if (latest.sceneId !== requestedScene) return current;
            const latestInputs = { ...current.searchConfig(), ...latest.dataVersion };
            return current.withPoses(current.poses.map((pose) => {
              const index = poses.findIndex((requested) => requested.id === pose.id);
              return index >= 0 && evaluationKey(requestedScene, latestInputs, pose) === keys[index]
                ? measuredChoice(pose, items[index], keys[index]) : pose;
            }));
          });
        } catch (reason) {
          const message = reason instanceof Error ? reason.message : "请求失败";
          keys.forEach((key) => evaluationFailed.current.set(key, message));
        } finally {
          keys.forEach((key) => evaluationInFlight.current.delete(key));
          setEvaluationRevision((value) => value + 1);
        }
      }
    })();
  }, [edit, scene?.id, scene?.ready, sceneVersion, layerInfo, adjusting, evaluationRevision, defaultSize, landuseState.dirty, landuseState.saving, landuseState.conflict]);

  function retrySelectedEvaluation() {
    evaluationFailed.current.clear();
    setEvaluationRevision((value) => value + 1);
  }

  async function scoreWaiting(sceneId: string): Promise<"ok" | "failed" | "empty"> {
    setLanduseAwaitingReview(false);
    const current = editRef.current;
    const inputs = { ...current.searchConfig(), ...evaluationSnapshot.current.dataVersion };
    const waiting = mergeDisplayedChoices(diversityPool.current, current.poses).filter((pose) => {
      if (!isAwaitingReview(poseFreshness(pose.evaluatedFor, sceneId, inputs, pose))) return false;
      return !evaluationInFlight.current.has(evaluationKey(sceneId, inputs, pose));
    });
    if (waiting.length === 0) return "empty";
    const { scene_name: _scene, ...config } = current.searchConfig();
    let failed = false;
    for (const poses of batches(waiting)) {
        if (optimizationActive() || evaluationSnapshot.current.sceneId !== sceneId) break;
        const latest = editRef.current;
        const latestInputs = { ...latest.searchConfig(), ...evaluationSnapshot.current.dataVersion };
        const retained = mergeDisplayedChoices(diversityPool.current, latest.poses);
        const group = poses.filter((pose) => {
          const live = retained.find((item) => item.id === pose.id);
          return live !== undefined && evaluationKey(sceneId, latestInputs, live) === evaluationKey(sceneId, inputs, pose);
        });
        if (group.length === 0) continue;
        const keys = group.map((pose) => evaluationKey(sceneId, inputs, pose));
        keys.forEach((key) => {
          evaluationInFlight.current.add(key);
          evaluationFailed.current.delete(key);
        });
        setEvaluationRevision((value) => value + 1);
        try {
          const { items } = await fetchPoseObjectives(sceneId, {
            ...config, poses: group.map(({ x, y, theta }) => ({ x, y, theta })),
          });
          if (items.length !== group.length) throw new Error("评价返回的方案数量不一致。");
          const after = editRef.current;
          const afterInputs = { ...after.searchConfig(), ...evaluationSnapshot.current.dataVersion };
          const afterRetained = mergeDisplayedChoices(diversityPool.current, after.poses);
          const measured = new Map<string, ParetoChoice>();
          group.forEach((pose, index) => {
            const live = afterRetained.find((item) => item.id === pose.id);
            if (!live || evaluationSnapshot.current.sceneId !== sceneId) return;
            if (evaluationKey(sceneId, afterInputs, live) !== keys[index]) return;
            measured.set(pose.id, measuredChoice(live, items[index], keys[index]));
          });
          if (measured.size > 0) {
            diversityPool.current = diversityPool.current.map((pose) => {
              const next = measured.get(pose.id);
              return next && pose.x === next.x && pose.y === next.y && pose.theta === next.theta ? next : pose;
            });
            setEdit((editState) => editState.withPoses(editState.poses.map((pose) => {
              const next = measured.get(pose.id);
              if (!next || pose.x !== next.x || pose.y !== next.y || pose.theta !== next.theta) return pose;
              const poseInputs = { ...editState.searchConfig(), ...evaluationSnapshot.current.dataVersion };
              return evaluationKey(sceneId, poseInputs, pose) === next.evaluatedFor ? next : pose;
            })));
          }
        } catch (reason) {
          failed = true;
          const message = reason instanceof Error ? reason.message : "重新评价失败";
          keys.forEach((key) => evaluationFailed.current.set(key, message));
        } finally {
          keys.forEach((key) => evaluationInFlight.current.delete(key));
          setEvaluationRevision((value) => value + 1);
        }
      }
    return failed ? "failed" : "ok";
  }

  async function reevaluateStaleSolutions() {
    if (reevaluatingRef.current || optimizationActive() || actionGate.current.held() || scene?.read_only || !scene?.ready) return;
    const sceneId = scene.id;
    await actionGate.current.run("review", async () => {
      reevaluatingRef.current = true;
      setReevaluating(true);
      let published = false;
      try {
        const step = await afterLandusePublish({
          publish: async () => {
            const outcome = await publishLanduseDraft();
            published = outcome.status === "published";
            return outcome;
          },
          sceneRevision: () => evaluationSnapshot.current.sceneId === sceneId
            ? evaluationSnapshot.current.dataVersion.scene_revision
            : undefined,
          run: () => scoreWaiting(sceneId),
        });
        if (!step.ran) {
          const stopped = computeStoppedNotice("重新评价", step.outcome);
          if (stopped) setNotice(stopped);
          return;
        }
        if (step.value === "failed" && published) setNotice(computeFailedAfterSave("重新评价"));
      } catch (reason) {
        setNotice(published
          ? computeFailedAfterSave("重新评价")
          : (reason instanceof Error ? reason.message : "无法重新评价旧方案"));
      } finally {
        reevaluatingRef.current = false;
        setReevaluating(false);
      }
    });
  }

  function createManualPose(point: LocalPoint) {
    if (!sceneReady || optimizationActive()) return;
    try {
      let current = editRef.current;
      if (!current.poses.length) {
        const size = BuildingSize.parse(rectW, rectH);
        current = current.withBuilding(size.widthM, size.heightM);
      }
      const theta = bearingToTheta(0, current.widthM, current.heightM, siteFrame, point);
      const center = clampFootprintCenter(point.x, point.y, theta, current.widthM, current.heightM);
      const number = Math.max(0, ...mergeDisplayedChoices(diversityPool.current, current.poses)
        .map((pose) => /^manual-(\d+)$/.exec(pose.id)).map((match) => match ? Number(match[1]) : 0)) + 1;
      const next = current.addPose(manualChoice(`manual-${number}`, center, theta));
      editRef.current = next;
      setEdit(next);
      diversityPool.current = mergeDisplayedChoices(diversityPool.current, next.poses);
      setSchemeCardOpen(true);
      selectTool("pan");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法添加方案");
    }
  }

  function deleteDisplayedSolution(id: string) {
    if (optimizationActive() || adjusting) {
      setNotice("优化或调整进行中，结束后才能删除方案。");
      return;
    }
    const current = editRef.current;
    const index = current.poses.findIndex((pose) => pose.id === id);
    if (index < 0) return;
    const next = current.removePose(id);
    const retained = mergeDisplayedChoices(diversityPool.current, current.poses).filter((pose) => pose.id !== id);
    if (!retained.length) clearDisplayedSolutions(false);
    else {
      diversityPool.current = retained;
      editRef.current = next;
      setEdit(next);
      setComparedIds((items) => items.filter((item) => item !== id));
      setRecommendedIds((items) => items.filter((item) => item !== id));
      setPreviewOps(null);
      setAskPose(null);
      if (current.selectedPoseId === id) {
        solutionGeneration.current.advance();
        setSchemeCardOpen(false);
        setSchemeAnchor(null);
        setSchemeTarget(null);
        setSchemeCardBounds(null);
        setReport(null);
        setAzimuthDeg("");
        dragStart.current = null;
      }
    }
    setNotice(current.poses[index].manual
      ? `已删除手动方案 ${index + 1}。历史优化结果已保留。`
      : `已删除方案 ${index + 1}。历史优化结果不受影响，重新导入该案例可恢复。`);
  }

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
    const pose = edit.poses[index];
    if (!pose || isAwaitingReview(freshnessOf(pose))) return [];
    return [{ id, rank: rank + 1, name: `方案 ${index + 1}` }];
  });
  const running = jobStarting || (job !== null && JobFollowUp.isActive(job.status));
  const preparing = running && (job?.plugin_id === PREPARE_PLUGIN || job?.plugin_id === BUILD_SCENE_PLUGIN);
  const shownJobLine = mapJobStatusLine(job && job.plugin_id !== BUILD_SCENE_PLUGIN ? job : null, submittingShownJob);
  const originLockMessage = running
    ? "优化进行中，暂不能修改进货原点。"
    : retainedCount > 0
      ? "当前方案已绑定进货原点，请先清空当前方案后再修改。"
      : null;
  const sceneReady = scene?.ready === true;
  const currentLanduseEditClass = landuseEditClass(tool);
  const landuseSketchActive = isLanduseSketchTool(tool);
  const landuseDraftKind = currentLanduseEditClass
    ? { classId: landuseEditClassId(currentLanduseEditClass) }
    : tool === "landuse-clear-water"
      ? { operation: WATER_TO_OTHER }
      : null;
  const landuseBlocked = landuseComputeBlocked(landuseState);
  const landuseBusy = landuseState.saving || landuseState.conflict;
  const landuseMarks = landuseState.dirty || landuseState.conflict
    ? landusePreviewMarks(landuseState.publishedItems, landuseState.draftItems)
    : [];
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
    admin_boundaries: {
      visible: adminBoundariesVisible,
      available: sceneReady && (adminBoundaries?.features.length ?? 0) > 0,
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
    if (mergeDisplayedChoices(diversityPool.current, editRef.current.poses).length > 0) return "当前方案已绑定进货原点，请先清空当前方案后再修改。";
    return null;
  }

  function requireOriginEditable(): void {
    const message = originEditingBlockedMessage();
    if (message) throw new Error(message);
  }

  async function createTrackedJob(request: Parameters<typeof createJob>[0]): Promise<JobRecord> {
    const shown = request.plugin_id !== BUILD_SCENE_PLUGIN;
    jobStartingRef.current = true;
    setJobStarting(true);
    if (shown) setSubmittingShownJob(true);
    try {
      const record = await createJob(request);
      jobRef.current = record;
      setJob(record);
      return record;
    } finally {
      jobStartingRef.current = false;
      setJobStarting(false);
      if (shown) setSubmittingShownJob(false);
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
    const preferred = !scene ? available.find((item) => item.default && item.ready)
      ?? available.find((item) => item.default) : null;
    const nextScene = preferred ?? available.find((item) => item.id === selectedId)
      ?? available.find((item) => item.id === DEFAULT_SCENE)
      ?? available[0]
      ?? null;
    setScenes(available);
    if (nextScene && editRef.current.sceneName !== nextScene.id) {
      const current = editRef.current;
      const next = current.withScene(nextScene.id);
      if (current === initialEdit.current) initialEdit.current = next;
      editRef.current = next;
      setEdit(next);
    }
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
    if (landuseStateRef.current.saving) {
      setNotice("正在保存土地类型，请稍候再切换场景。");
      return;
    }
    const gate = landuseSceneSwitch(landuseStateRef.current, next.id, options?.reload === true);
    if (!gate.allowed) {
      setPendingSceneSwitch({ next, options });
      setNotice("有未保存的土地类型修改。请先保存或放弃，再切换场景。");
      return;
    }
    setPendingSceneSwitch(null);
    landuseStateRef.current = gate.state;
    setLanduseState(gate.state);
    setLanduseAwaitingReview(false);
    sceneRevisionOverride.current = null;
    setParetoLayerNote("");
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
      current.highwaySetbackM,
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
    setLanduseDraftPoints([]);
    setLayerInfo(null);
    setLayerError("");
    setRoadSegments([]);
    setRoadKinds([]);
    setRoadError("");
    setAdminBoundaries(null);
    setAdminBoundaryError("");
    setShownClasses(hiddenLanduseClasses());
    setFarmlandDeleting(false);
    setFarmlandPreviewUrl(null);
    setFarmlandVisible(false);
    setDemVisible(false);
    setRoadsVisible(false);
    setFeasibilityVisible(false);
    setFeasibilityPreparing(false);
    showFeasibilityUrl(null, null);
    setReport(null);
    setAzimuthDeg("");
    evaluationFailed.current.clear();
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
    if (scene?.read_only && next !== "pan") {
      setNotice("历史场景已封存，请切换到 UTM 场景编辑。");
      return;
    }
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
    if (next === "landuse-clear-water") {
      setShownClasses((current) => ({ ...current, water: true }));
      setNotice("圈选遥感误识别为水体的区域。仅圈内当前水体改为其他，农田、道路和建筑不变。");
    }
    setTool(next);
  }

  function setLanduseDraftPoints(points: LocalPoint[]) {
    landuseDraftRef.current = points;
    setLanduseDraft(points);
  }

  function previewLanduseDraft(points: LocalPoint[]) {
    if (!isLanduseSketchTool(tool)) return;
    setLanduseDraftPoints(points);
    setNotice("");
  }

  function finishLanduseDraft(stroke: readonly LocalPoint[]) {
    const category = landuseEditClass(tool);
    const clearWater = tool === "landuse-clear-water";
    const points = simplifyStroke(stroke, 4);
    setLanduseDraftPoints([]);
    if ((!category && !clearWater) || !scene || points.length < 3) {
      setNotice("土地类型图斑至少需要三个折点。");
      return;
    }
    const current = landuseStateRef.current;
    if (scene.read_only) {
      setNotice("历史场景已封存，不能修改土地类型。");
      return;
    }
    let id: string;
    try {
      id = newLanduseEditId(current.draftItems);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法生成图斑编号。");
      return;
    }
    const next = addLanduseDraft(current, clearWater
      ? { id, operation: WATER_TO_OTHER, points: localRing(points) }
      : { id, class_id: landuseEditClassId(category!), points: localRing(points) });
    if (next === current) {
      setNotice(current.saving ? "正在保存土地类型，请稍候再编辑。" : current.conflict ? current.error ?? "场景版本冲突，请先处理未保存修改。" : "这个图斑没有加入草稿。");
      return;
    }
    landuseStateRef.current = next;
    setLanduseState(next);
    landuseUndoPreferred.current = true;
    setNotice(clearWater
      ? `${LANDUSE_DRAFT_NOTICE}${WATER_CORRECTION_PREVIEW_NOTE}`
      : `${LANDUSE_DRAFT_NOTICE}${LANDUSE_PREVIEW_NOTE}`);
  }

  function removeLandusePatch(editId: string) {
    const next = removeLanduseDraft(landuseStateRef.current, editId);
    if (next === landuseStateRef.current) {
      setNotice("无法从草稿中删除这个图斑。");
      return;
    }
    landuseStateRef.current = next;
    setLanduseState(next);
    landuseUndoPreferred.current = true;
    setNotice("已从草稿中删除图斑。保存后才会改场景土地类型。");
  }

  function rememberPublishedRevision(sceneId: string, revision: string) {
    sceneRevisionOverride.current = { sceneId, revision };
    const info = layerInfoRef.current;
    const nextInfo = info && info.scene_id === sceneId ? {
      ...info,
      data_version: {
        frame_id: info.data_version?.frame_id ?? null,
        scene_revision: revision,
      },
    } : info;
    layerInfoRef.current = nextInfo;
    evaluationSnapshot.current = {
      sceneId,
      dataVersion: {
        road_product_id: nextInfo?.roads.road_product_id ?? "",
        farmland_content_sha256: nextInfo?.protected_farmland?.content_sha256 ?? "",
        ...nextInfo?.data_version,
        scene_revision: revision,
      },
    };
    setLayerInfo(nextInfo);
    setSceneVersion((version) => version + 1);
    setReport(null);
    setLanduseAwaitingReview(true);
    if (mergeDisplayedChoices(diversityPool.current, editRef.current.poses).length > 0) {
      setParetoLayerNote(PARETO_LAYER_NOTE);
    }
  }

  async function publishLanduseDraft(): Promise<LandusePublishOutcome> {
    const started = beginLanduseSave(landuseStateRef.current);
    if (!started.request) {
      const current = landuseStateRef.current;
      if (current.conflict) return { status: "conflict" };
      if (current.saving) return { status: "cancelled" };
      if (current.dirty) return { status: "failed", message: "当前还没有场景版本，不能保存土地类型。" };
      return { status: "unchanged", sceneRevision: current.baseRevision ?? "" };
    }
    const sceneId = started.request.sceneId;
    landuseStateRef.current = started.state;
    setLanduseState(started.state);
    try {
      const result = await replaceLanduseEdits(sceneId, started.request.expected_scene_revision, started.request.items);
      if (landuseStateRef.current.sceneId !== sceneId) return { status: "cancelled" };
      const saved = completeLanduseSave(landuseStateRef.current, {
        ...result,
        items: result.items.flatMap((item) => {
          const parsed = parseLanduseEdit(item);
          return parsed ? [parsed] : [];
        }),
      });
      landuseStateRef.current = saved;
      setLanduseState(saved);
      if (!result.changed) return { status: "unchanged", sceneRevision: result.scene_revision };
      rememberPublishedRevision(sceneId, result.scene_revision);
      return { status: "published", sceneRevision: result.scene_revision };
    } catch (reason) {
      if (landuseStateRef.current.sceneId !== sceneId) return { status: "cancelled" };
      if (reason instanceof ApiRequestError && reason.status === 409 && reason.code === "landuse_revision_conflict") {
        const conflicted = conflictLanduseSave(landuseStateRef.current);
        landuseStateRef.current = conflicted;
        setLanduseState(conflicted);
        return { status: "conflict" };
      }
      const message = reason instanceof Error ? reason.message : "无法保存土地类型修改";
      const failed = failLanduseSave(landuseStateRef.current, message);
      landuseStateRef.current = failed;
      setLanduseState(failed);
      return { status: "failed", message };
    }
  }

  async function saveLanduseDraft() {
    if (actionGate.current.held() || reevaluatingRef.current || optimizationActive()) {
      setNotice("正在处理上一次操作。");
      return;
    }
    const result = await actionGate.current.run("save", () => publishLanduseDraft());
    if (result.skipped) return;
    const outcome = result.value;
    if (outcome.status === "published") setNotice("土地类型已保存。旧方案需要重新评价后才会使用新的土地类型。");
    else if (outcome.status === "unchanged") setNotice("土地类型没有变化，场景版本保持不变。");
    else if (outcome.status === "conflict") setNotice(landuseStateRef.current.error ?? "场景版本冲突，未写入。");
    else if (outcome.status === "failed") setNotice(outcome.message);
  }

  function discardLanduseChanges() {
    if (!window.confirm("放弃未保存的土地类型修改？这些草稿不会写入场景。")) return;
    const next = discardLanduseDraft(landuseStateRef.current);
    landuseStateRef.current = next;
    setLanduseState(next);
    setLanduseDraftPoints([]);
    setNotice("已放弃未保存的土地类型修改。");
  }

  function discardLanduseAndSwitch() {
    const pending = pendingSceneSwitch;
    if (!pending) return;
    const next = discardLanduseDraft(landuseStateRef.current);
    landuseStateRef.current = next;
    setLanduseState(next);
    setPendingSceneSwitch(null);
    switchScene(pending.next, pending.options);
  }

  async function reloadPublishedLanduseEdits() {
    const current = landuseStateRef.current;
    if (!current.sceneId) return;
    if (!window.confirm("重新加载会放弃当前草稿，改用服务器上已发布的图斑。")) return;
    const sceneId = current.sceneId;
    try {
      const payload = await getLanduseEdits(sceneId);
      if (landuseStateRef.current.sceneId !== sceneId) return;
      const items = payload.items.flatMap((item) => {
        const parsed = parseLanduseEdit(item);
        return parsed ? [parsed] : [];
      });
      const next = reloadPublishedLanduse(landuseStateRef.current, items, payload.scene_revision);
      landuseStateRef.current = next;
      setLanduseState(next);
      setLanduseDraftPoints([]);
      setNotice("已重新加载服务器上的土地类型图斑，未保存修改已放弃。");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法重新加载土地类型图斑");
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

  function erasePose(id: string) {
    if (evaluationState === "loading") {
      setNotice("重算进行中，结束后才能删除方案。");
      return;
    }
    deleteDisplayedSolution(id);
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
    landuseUndoPreferred.current = false;
    setEdit((current) => current.removeRegion(id));
    setNotice("已擦掉这块范围。按 Ctrl+Z 可以恢复。");
  }

  function replaceOriginAndRemeasure(next: SiteEdit<ParetoChoice>) {
    setReport(null);
    setEdit(next);
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
    landuseUndoPreferred.current = false;
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

  function undoLanduseDraftChange(): boolean {
    const next = undoLanduseDraft(landuseStateRef.current);
    if (next === landuseStateRef.current) return false;
    landuseStateRef.current = next;
    setLanduseState(next);
    landuseUndoPreferred.current = next.undo.length > 0 || next.redo.length > 0;
    setNotice("已撤销土地类型草稿修改。");
    return true;
  }

  function undoErase() {
    if (landuseUndoPreferred.current && undoLanduseDraftChange()) return;
    if (isLanduseSketchTool(tool) && undoLanduseDraftChange()) return;
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
    const retained = mergeDisplayedChoices(diversityPool.current, current.poses).length;
    if (retained === 0 && !allowEmpty) return false;
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
    evaluationFailed.current.clear();
    setParetoLayerNote("");
    setPreviewOps(null);
    setAskPose(null);
    setAdjusting(false);
    dragStart.current = null;
    refining.current = null;
    if (tool === "adjust") setTool("pan");
    if (announce) setNotice("已清空当前方案，历史优化结果已保留。");
    return retained > 0;
  }

  function changeDiversity(level: ParetoLayer) {
    if (running || adjusting) return;
    const current = editRef.current;
    diversityPool.current = mergeDisplayedChoices(diversityPool.current, current.poses);
    const visible = diversityPool.current.filter((choice) => visibleAtLevel(choice, level));
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
    const blocked = landuseComputeBlocked(landuseStateRef.current);
    if (blocked) {
      setNotice(`${blocked}然后再重新准备场景数据。`);
      return;
    }
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
      const metadataUrl = experiment?.artifacts.find((item) => item.name === "data_metadata.json")?.url;
      if (metadataUrl) {
        const metadata = JSON.parse(await fetchArtifactText(metadataUrl)) as {data_version?: {frame_id?: string}; frame_id?: string};
        const sourceFrame = metadata.data_version?.frame_id ?? metadata.frame_id;
        if (sourceFrame && dataVersion.frame_id && sourceFrame !== dataVersion.frame_id) {
          throw new Error("历史结果使用了不同坐标网格，请在对应历史场景查看。");
        }
      }
      const loaded = await run.current.loadPareto(experimentId, true);
      const size = await importedBuildingSize(experiment);
      if (!solutionGeneration.current.isCurrent(generation)) return;
      const form = await importedSiteForm(experiment);
      if (!solutionGeneration.current.isCurrent(generation)) return;
      const current = editRef.current;
      const sized = size ? current.withBuilding(size.widthM, size.heightM) : current;
      const restored = form ? sized.withImportedSiteForm(form) : sized;
      const pool = acceptImportedPoses(
        loaded,
        scene?.id ?? restored.sceneName,
        { ...restored.searchConfig(), ...evaluationSnapshot.current.dataVersion },
      );
      const choices = pool.filter((choice) => visibleAtLevel(choice, 1));
      diversityPool.current = pool;
      const imported = restored.withPoses(choices);
      editRef.current = imported;
      setEdit(imported);
      setDiversityLevel(1);
      setParetoLayerNote("");
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
      const label = experiment?.name ?? experimentId;
      const description = experiment?.algorithm === "workspace_snapshot"
        ? `已导入 ${label}，保留 ${pool.length} 个方案，当前显示 ${choices.length} 个。`
        : `已导入 ${label}，共 ${choices.length} 个可行帕累托方案。`;
      const keptDraft = landuseStateRef.current.dirty || landuseStateRef.current.conflict;
      setNotice(keptDraft
        ? `${form ? description : `${description}这次结果没有保存当时的约束，侧栏仍是当前设置。`}未保存的土地类型修改仍保留，没有提交。`
        : (form ? description : `${description}这次结果没有保存当时的约束，侧栏仍是当前设置。`));
    } catch (reason) {
      if (!solutionGeneration.current.isCurrent(generation)) return;
      setNotice(reason instanceof Error ? reason.message : "无法导入这次结果");
    }
  }

  async function saveCurrentExperiment(name: string) {
    if (savingExperimentRef.current) return;
    try {
      if (optimizationActive() || adjusting) throw new Error("请在优化和方案调整结束后保存。");
      if (!scene?.ready) throw new Error("请先准备当前场景数据。");
      const body = experimentSaveBody(name, editRef.current, diversityPool.current, loadedCaseId);
      savingExperimentRef.current = true;
      setSavingExperiment(true);
      setSaveExperimentError("");
      const saved = await saveExperiment(body);
      setSaveExperimentOpen(false);
      setHistory(null);
      setNotice(`已保存「${saved.name}」，共 ${saved.solution_count} 个方案，可从「导入案例」重新打开。`);
    } catch (reason) {
      setSaveExperimentError(reason instanceof Error ? reason.message : "无法保存实验");
    } finally {
      savingExperimentRef.current = false;
      setSavingExperiment(false);
    }
  }

  function downloadSolutions(format: "csv" | "json") {
    if (edit.poses.length === 0) {
      setNotice("暂无可导出的方案，请先导入案例或完成一次优化。");
      return;
    }
    const exported = edit.poses.map((pose) => presentChoice(pose, freshnessOf(pose)));
    const content = format === "csv"
      ? exportSolutionsCsv(exported)
      : exportSolutionsJson(edit.sceneName, edit.widthM, edit.heightM, exported);
    const staleExport = exported.some((pose) => pose.demSoft === STALE);
    const blob = new Blob([content], { type: format === "csv" ? "text/csv;charset=utf-8" : "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${edit.sceneName}-solutions.${format}`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    setNotice(staleExport
      ? `已导出 ${edit.poses.length} 个方案（${format.toUpperCase()}）。待重评方案的目标值已留空。`
      : `已导出 ${edit.poses.length} 个方案（${format.toUpperCase()}）。`);
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
    const pool = mergeDisplayedChoices(diversityPool.current, editRef.current.poses);
    const poses = selectExportPoses(pool, value.pareto);
    const rankIds = value.showRecommendRanks
      ? recommendedIds.filter((id) => {
        const pose = poses.find((item) => item.id === id);
        return pose !== undefined && !isAwaitingReview(freshnessOf(pose, editRef.current));
      })
      : [];
    const footprints = BuildingFootprint.layer(
      poses,
      { widthM: edit.widthM, heightM: edit.heightM },
      -1,
      rankIds,
    );
    const ranks = exportRankMarks(poses, rankIds, value.showRecommendRanks).map((mark) => ({
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
      let kinds = roadKinds;
      if (value.layers.osm && segments.length === 0 && layerInfo?.roads.available === true) {
        const loaded = await getRoadSegments(currentScene.id);
        if (sceneExportToken.current !== token) return;
        segments = loaded.segments;
        kinds = loaded.kinds;
      }
      let boundaries = adminBoundaries;
      if (value.layers["admin-boundaries"] && boundaries === null) {
        boundaries = await getAdminBoundaries(currentScene.id);
        if (sceneExportToken.current !== token) return;
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
        "admin-boundaries": (boundaries?.features.length ?? 0) > 0,
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
        roadKinds: kinds,
        adminBoundaries: value.layers["admin-boundaries"],
        adminBoundaryCollection: boundaries,
        adminLabels: adminBoundaryLabels(boundaries),
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
    if (reevaluatingRef.current || actionGate.current.held()) {
      setNotice("正在处理上一次操作。");
      return false;
    }
    if (scene?.read_only) { setNotice("历史场景已封存，请切换到 UTM 场景优化。"); return false; }
    if (!sceneReady) {
      setNotice("请先完成场景数据构建。优化不会在搜索时重新生成 DEM、道路和需求点。");
      return false;
    }
    const result = await actionGate.current.run("optimize", async () => {
      let published = false;
      try {
        const step = await afterLandusePublish({
          publish: async () => {
            const outcome = await publishLanduseDraft();
            published = outcome.status === "published";
            return outcome;
          },
          sceneRevision: () => evaluationSnapshot.current.dataVersion.scene_revision,
          run: async () => {
            setLanduseAwaitingReview(false);
            setParetoLayerNote("");
            const submitted = current.withScene(scene?.id ?? DEFAULT_SCENE);
            setNotice("");
            setEdit(submitted);
            setRectW(String(submitted.widthM));
            setRectH(String(submitted.heightM));
            setFieldCost(String(submitted.fieldCost));
            refining.current = null;
            solutionGeneration.current.advance();
            await createTrackedJob(run.current.createRequest(submitted, new Date()));
          },
        });
        if (!step.ran) {
          const stopped = computeStoppedNotice("优化", step.outcome);
          if (stopped) setNotice(stopped);
          return false;
        }
        return true;
      } catch (reason) {
        setNotice(published
          ? computeFailedAfterSave("优化")
          : (reason instanceof Error ? reason.message : "无法开始优化"));
        return false;
      }
    });
    return result.skipped ? false : result.value;
  }

  async function submitRefine(current: SiteEdit<ParetoChoice>, poseId: string, halfWidthM: number) {
    if (optimizationActive() || reevaluatingRef.current || actionGate.current.held()) {
      setNotice("优化还在进行，这次没有开始局部优化。");
      return;
    }
    const pose = current.poses.find((item) => item.id === poseId);
    if (!pose || !sceneReady || scene?.read_only) return;
    await actionGate.current.run("optimize", async () => {
      let published = false;
      try {
        const step = await afterLandusePublish({
          publish: async () => {
            const outcome = await publishLanduseDraft();
            published = outcome.status === "published";
            return outcome;
          },
          sceneRevision: () => evaluationSnapshot.current.dataVersion.scene_revision,
          run: async () => {
            setLanduseAwaitingReview(false);
            const submitted = current.withScene(scene?.id ?? DEFAULT_SCENE);
            solutionGeneration.current.advance();
            const record = await createTrackedJob(run.current.createRefineRequest(submitted, pose, halfWidthM, new Date()));
            refining.current = {
              jobId: record.job_id,
              origin: pose,
              hasOrigin: submitted.origin !== null,
              includeDemand: submitted.includeDemand,
              edit: submitted,
            };
            setNotice(`正在方案 ${current.poses.indexOf(pose) + 1} 周围局部优化，原方案保留。`);
          },
        });
        if (!step.ran) {
          const stopped = computeStoppedNotice("优化", step.outcome);
          if (stopped) setNotice(stopped);
        }
      } catch (reason) {
        setNotice(published
          ? computeFailedAfterSave("优化")
          : (reason instanceof Error ? reason.message : "无法开始局部优化"));
      }
    });
  }

  async function startOptimization() {
    try {
      const current = editRef.current;
      const size = BuildingSize.parse(rectW, rectH);
      const cost = current.fieldPolicy === "costly" ? Number(fieldCost) : 0.5;
      if (current.fieldPolicy === "costly" && (!Number.isFinite(cost) || cost <= 0 || cost > 1)) {
        setNotice("农田代价系数必须在 0 到 1 之间。");
        return;
      }
      if (optimizationActive() || reevaluatingRef.current) return;
      const submitted = await submitSearch(
        current.withBuilding(size.widthM, size.heightM).withPolicies("allowed", current.fieldPolicy, cost),
      );
      if (submitted) selectTool("pan");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法开始优化");
    }
  }

  function changeAzimuth(value: string) {
    if (scene?.read_only) return;
    azimuthEditing.current = true;
    setAzimuthDeg(value);
    const current = editRef.current;
    const choice = current.selected;
    if (!choice || value.trim() === "") return;
    try {
      angleDegreesToRadians(Number(value));
      const theta = siteFrame.thetaFromBearing(Number(value), choice);
      const next = current.updateSelected((item) => rotateChoice(
        item,
        theta,
        new BuildingSize(current.widthM, current.heightM),
      ));
      setEdit(next);
      setNotice("");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法应用这个方位角");
    }
  }

  function resetAzimuth() {
    azimuthEditing.current = false;
    const choice = editRef.current.selected;
    setAzimuthDeg(choice ? formatAzimuthDegrees(choice.theta, choice) : "");
  }

  function restoreOriginal() {
    const current = editRef.current;
    const choice = current.selected;
    if (!choice || !isChoiceEdited(choice)) return;
    setEdit(current.updateSelected(restoreChoice));
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
      setAdminBoundariesVisible(applied.layers.admin_boundaries.visible);
      setRegionVisibility({ ...applied.layers.regions });
    }
    if (panelChanged) setLayersOpen(applied.layers.panel_open);
    else if (displayChanged) setLayersOpen(true);
    const edit = applied.edit;
    if (applied.edit !== before) {
      setRectW(String(applied.edit.widthM));
      setRectH(String(applied.edit.heightM));
      setFieldCost(String(applied.edit.fieldCost));
      setEdit(applied.edit);
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
      const recorded = editRef.current.withPoses(editRef.current.poses.map((pose) => presentChoice(pose, freshnessOf(pose, editRef.current))));
      const { count } = await recordPreferenceChoice(
        preferenceChoice(toSnapshot(recorded, { experimentId: loadedCaseId }), poseId),
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
    drawing: regionKind(tool) !== null || isLanduseSketchTool(tool),
    pan: () => selectTool("pan"),
    draw: () => selectTool("exclusion"),
    focus: () => setFocusToken((token) => token + 1),
    closeDraft,
    cancelDraft: () => {
      boxAnchor.current = null;
      setAdjusting(false);
      setEdit((current) => current.cancelDraft());
      setLanduseDraftPoints([]);
      setTool("pan");
    },
    undoPoint: () => {
      if (isLanduseSketchTool(tool)) {
        setLanduseDraftPoints([]);
        return;
      }
      setEdit((current) => current.undoPoint());
    },
    undoErase,
    redo: () => {
      if (!landuseUndoPreferred.current && !isLanduseSketchTool(tool)) return;
      const next = redoLanduseDraft(landuseStateRef.current);
      if (next === landuseStateRef.current) return;
      landuseStateRef.current = next;
      setLanduseState(next);
      landuseUndoPreferred.current = next.undo.length > 0 || next.redo.length > 0;
      setNotice("已恢复土地类型草稿修改。");
    },
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
        const resultData = record.result?.data as {data_version?: {frame_id?: string; scene_revision?: string}} | undefined;
        const sourceVersion = resultData?.data_version;
        const currentVersion = evaluationSnapshot.current.dataVersion;
        if (sourceVersion?.frame_id && currentVersion.frame_id && sourceVersion.frame_id !== currentVersion.frame_id) {
          setNotice("结果使用了不同坐标网格，不能导入当前场景。请在对应历史场景查看。");
          return;
        }
        const sameVersion = sourceVersion?.scene_revision && sourceVersion.scene_revision === currentVersion.scene_revision;
        const pool = (await run.current.loadPareto(experimentId, !refine)).map((choice) => ({
          ...choice, evaluatedFor: sameVersion ? evaluationKey(editRef.current.sceneName, { ...record.config, ...currentVersion }, choice) : undefined,
        }));
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
        setParetoLayerNote("");
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
        initialEdit.current = defaults;
        editRef.current = defaults;
        setEdit(defaults);
        setRectW(String(defaults.widthM));
        setRectH(String(defaults.heightM));
      })
      .catch((reason) => {
        setNotice(reason instanceof Error ? reason.message : "无法读取默认参数");
      });
  }, []);

  useEffect(() => {
    if (!azimuthEditing.current || azimuthPoseId.current !== selected?.id) {
      azimuthEditing.current = false;
      setAzimuthDeg(selected ? formatAzimuthDegrees(selected.theta, selected) : "");
    }
    azimuthPoseId.current = selected?.id;
  }, [selected?.id, selected?.theta, selected?.x, selected?.y]);

  useEffect(() => {
    setLayerInfo(null);
    setLayerError("");
    setRoadSegments([]);
    setRoadKinds([]);
    setRoadError("");
    setAdminBoundaries(null);
    setAdminBoundaryError("");
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
    if (!sceneReady || !scene || !layerInfo || layerInfo.scene_id !== scene.id) return;
    if (!Object.values(layerInfo.landuse).some(Boolean)) return;
    const sceneId = scene.id;
    const bound = landuseStateRef.current;
    if (bound.sceneId !== sceneId) {
      const next = noteLanduseScene(bound, sceneId);
      if (next === bound) return;
      landuseStateRef.current = next;
      setLanduseState(next);
      return;
    }
    const token = bound.loadToken;
    let stopped = false;
    getLanduseEdits(sceneId)
      .then((payload) => {
        if (stopped) return;
        setLanduseState((current) => {
          const accepted = acceptPublishedLanduse(current, {
            sceneId,
            items: payload.items.flatMap((item) => {
              const parsed = parseLanduseEdit(item);
              return parsed ? [parsed] : [];
            }),
            sceneRevision: payload.scene_revision,
            token,
          });
          landuseStateRef.current = accepted;
          return accepted;
        });
      })
      .catch((reason) => {
        if (!stopped) setNotice(reason instanceof Error ? reason.message : "无法读取场景土地类型修正");
      });
    return () => {
      stopped = true;
    };
  }, [scene?.id, sceneReady, layerInfo, landuseState.sceneId, landuseState.loadToken]);

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
        if (!stopped) { setRoadSegments(value.segments); setRoadKinds(value.kinds); }
      })
      .catch((reason) => {
        if (!stopped) setRoadError(reason instanceof Error ? reason.message : "无法读取道路网络");
      });
    return () => {
      stopped = true;
    };
  }, [roadsVisible, scene?.id, sceneReady, layerInfo?.roads.available, roadSegments.length]);

  useEffect(() => {
    if (!adminBoundariesVisible || !sceneReady || !scene || adminBoundaries !== null) return;
    let stopped = false;
    setAdminBoundaryError("");
    getAdminBoundaries(scene.id)
      .then((value) => {
        if (!stopped) setAdminBoundaries(value);
      })
      .catch((reason) => {
        if (!stopped) setAdminBoundaryError(reason instanceof Error ? reason.message : "无法读取行政边界");
      });
    return () => {
      stopped = true;
    };
  }, [adminBoundariesVisible, scene?.id, sceneReady, adminBoundaries]);

  const reportRequestKey = JSON.stringify([scene?.id, selected?.id, edit.reportRequest(), sceneVersion, farmlandVersion, selectedFreshness]);
  useEffect(() => {
    if (!siteReportAllowed(landuseComputeBlocked(landuseStateRef.current) !== null, selectedFreshness)) {
      if (!selected || isAwaitingReview(selectedFreshness)) setReport(null);
      return;
    }
    if (!scene || !selected || adjusting || scene.read_only) return;
    const controller = new AbortController();
    const generation = solutionGeneration.current.capture();
    const selectedIndex = edit.selectedIndex;
    const body = edit.reportRequest();
    if (!body) return;
    setReport(null);
    fetchSiteReport(scene.id, body, controller.signal)
      .then((value) => {
        if (landuseComputeBlocked(landuseStateRef.current)) return;
        if (!controller.signal.aborted && solutionGeneration.current.isCurrent(generation)) setReport(value);
      })
      .catch((reason) => {
        if (!controller.signal.aborted && solutionGeneration.current.isCurrent(generation)) {
          setNotice(siteReportFailureNotice(selectedIndex, reason));
        }
      });
    return () => controller.abort();
  }, [reportRequestKey, adjusting, selectedFreshness]);

  useEffect(() => {
    const onLeave = (event: BeforeUnloadEvent) => {
      const current = landuseStateRef.current;
      if (!current.dirty && !current.conflict) return;
      event.preventDefault();
      event.returnValue = LANDUSE_REFRESH_WARNING;
    };
    window.addEventListener("beforeunload", onLeave);
    return () => window.removeEventListener("beforeunload", onLeave);
  }, []);

  useEffect(() => {
    if (problemType !== "site") return;
    const shortcuts = new MapShortcuts(() => commands.current);
    const onKeyDown = (event: KeyboardEvent) => shortcuts.handle(event);
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [problemType]);

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

  useLayoutEffect(() => {
    const root = workspaceRef.current;
    if (!root) return;
    const measure = () => {
      const title = root.querySelector<HTMLElement>(".hud-top");
      const toolbar = root.querySelector<HTMLElement>(".map-toolbar");
      if (!title || !toolbar) return;
      const rootTop = root.getBoundingClientRect().top;
      const titleHeight = title.getBoundingClientRect().bottom - rootTop;
      root.style.setProperty("--hud-title-height", `${titleHeight}px`);
      const chromeBottom = toolbar.getBoundingClientRect().bottom - rootTop;
      root.style.setProperty("--map-chrome-bottom", `${chromeBottom}px`);
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    const title = root.querySelector(".hud-top");
    const toolbar = root.querySelector(".map-toolbar");
    if (title) observer?.observe(title);
    if (toolbar) observer?.observe(toolbar);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  return (
    <div ref={workspaceRef} className={panelMinimized ? "map-app panel-minimized" : "map-app"} data-theme={theme}>
      {sceneFrame ? <WorldMap
        key={scene?.id ?? "loading"}
        frame={sceneFrame}
        routing={problemType === "routing" ? routingLayer : null}
        tool={problemType === "routing" ? "pan" : tool}
        zones={problemType === "site" ? edit.zones : []}
        draft={problemType === "site" ? edit.draft : []}
        footprints={problemType === "site" ? BuildingFootprint.layer(edit.poses, { widthM: edit.widthM, heightM: edit.heightM }, edit.selectedIndex, recommended.map((item) => item.id)) : []}
        landuseEdits={landuseState.draftItems.map((item) => (
          isWaterCorrection(item)
            ? { id: item.id, operation: WATER_TO_OTHER, points: item.points.map(([x, y]) => ({ x, y })) }
            : { id: item.id, classId: item.class_id, points: item.points.map(([x, y]) => ({ x, y })) }
        ))}
        landuseDraft={landuseDraft}
        landuseDraftKind={landuseDraftKind}
        showLanduseOutlines={tool === "erase" || landuseSketchActive || (!landuseState.dirty && (currentLanduseEditClass !== null || previewOps !== null))}
        landusePreview={landuseMarks.map((item) => (
          isWaterCorrection(item)
            ? { id: item.id, operation: WATER_TO_OTHER, status: item.status, points: item.points.map(([x, y]) => ({ x, y })) }
            : { id: item.id, classId: item.class_id, status: item.status, points: item.points.map(([x, y]) => ({ x, y })) }
        ))}
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
        feasibilityLayer={problemType === "site" && feasibilityUrl ? {
          url: feasibilityUrl,
          visible: feasibilityVisible,
        } : null}
        protectedFarmlandLayer={sceneReady && scene && (farmlandPreviewUrl || layerInfo?.protected_farmland?.available) ? {
          url: farmlandPreviewUrl ?? `/api/v1/scenes/${scene.id}/protected-farmland-overlay?v=${farmlandVersion}`,
          visible: farmlandPreviewUrl !== null || farmlandVisible,
        } : null}
        roadSegments={importPreview?.roads?.segments ?? roadSegments}
        roadKinds={importPreview?.roads?.kinds ?? roadKinds}
        roadsVisible={importPreview?.roads !== null && importPreview?.roads !== undefined || roadsVisible}
        adminBoundaries={adminBoundaries}
        adminBoundariesVisible={adminBoundariesVisible}
        regionVisibility={regionVisibility}
        haulPath={problemType === "site" && !landuseBlocked ? (report?.haul_path ?? []).map(([x, y]) => ({ x, y })) : []}
        origin={problemType === "site" ? origin : null}
        favoritePoints={problemType === "site" ? favoriteOverlayPoints : []}
        preview={problemType === "site" ? agentMapPreview(edit, previewOps, agentLayers) : undefined}
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
        onCreatePose={createManualPose}
        onSelectFavorite={(id) => {
          favorites.select(id);
          setFavoritesOpen(true);
          setSchemeCardOpen(false);
          bringToFront("favorites");
        }}
        captureRef={mapCapture}
        rectSelecting={rectSelecting}
        onRectSelect={(a, b) => {
          setRectSelecting(false);
          const config = rectToSceneConfig(a, b);
          setSceneBuildOpen(true);
          if (!config) {
            setBuildFormError("框选范围太小或超出可建区域，请拖出至少 2 m 的范围。");
            return;
          }
          setBuildFormError("");
          setBuildLat(String(Number(config.lat.toFixed(6))));
          setBuildLon(String(Number(config.lon.toFixed(6))));
          setBuildSide(String(config.sideLengthM));
        }}
        onRectSelectCancel={() => {
          setRectSelecting(false);
          setSceneBuildOpen(true);
        }}
        onBoxClick={clickBox}
        onBoxMove={previewBox}
        onEraseOrigin={clearLogisticsOrigin}
        onEraseZone={eraseRegion}
        onErasePose={erasePose}
        onEraseFavorite={(id) => void favorites.remove(id)}
        onMoveFootprint={(dx, dy) => {
          const pose = editRef.current.selected;
          if (pose && !dragStart.current) dragStart.current = { id: pose.id, x: pose.x, y: pose.y };
          setAdjusting(true);
          setEdit((current) => current.moveSelected(dx, dy));
        }}
        onFinishMove={() => {
          setAdjusting(false);
          dragStart.current = null;
        }}
        onSchemeAnchor={setSchemeAnchor}
        onSchemeTarget={setSchemeTarget}
      /> : (
        <div className="map-viewport-shell map-unavailable" role="status">
          当前场景缺少可用的 reference GeoTIFF 或 landuse 网格；请补齐四份原始文件后构建场景数据。
        </div>
      )}
      <header className="hud-top">
        <div>
          <p>温州电力设计院</p>
          <strong>{scene ? `${scene.title}${problemType === "routing" ? "选线规划" : "选址规划"}` : "选址规划"}</strong>
        </div>
        <div className="workspace-mode" aria-label="问题模式">
          <button type="button" aria-pressed={problemType === "site"} disabled={running || routingBusy}
            onClick={() => { selectTool("pan"); setProblemType("site"); }}>选址</button>
          <button type="button" aria-pressed={problemType === "routing"} disabled={running || routingBusy}
            onClick={() => { selectTool("pan"); setProblemType("routing"); }}>选线</button>
        </div>
        <div className="hud-brand">
          <span className={health.includes("失败") ? "hud-health bad" : "hud-health"}>{health}</span>
          <img className="lab-logo" src="/tgai-logo.png" alt="西湖大学可信及通用人工智能实验室" />
          <img src={theme === "light" ? "/westlake-logo-ink.png" : "/westlake-logo.png"} alt="西湖大学" />
        </div>
      </header>
      <RoutingWorkspace active={problemType === "routing"} scene={scene} scenes={scenes} frame={sceneFrame}
        onSceneChange={(id) => { const next = scenes.find((item) => item.id === id); if (next) switchScene(next); }}
        onFocus={() => setFocusToken((token) => token + 1)} onLayer={setRoutingLayer} onBusy={setRoutingBusy} />
      <div style={{ display: problemType === "site" ? "contents" : "none" }}>
      <SchemeConnector
        target={schemeTarget?.schemeId === selected?.id ? schemeTarget : null}
        cardBounds={schemeCardBounds && schemeCardBounds.schemeId === selected?.id ? schemeCardBounds.bounds : null}
        workspaceBounds={workspaceBounds}
        visible={showSchemeCard}
      />
      <MapToolbar
        poseAddDisabled={!sceneReady || running || scene?.read_only === true}
        poseAddDisabledReason={!sceneReady ? "请先准备场景数据" : running ? "优化进行中" : undefined}
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
        onDeleteScene={(sceneId) => void (async () => {
          const target = scenes.find((item) => item.id === sceneId);
          try {
            const result = await deleteScene(sceneId);
            setScenes(await getScenes());
            setNotice(`已删除场景「${target?.title ?? sceneId}」及其 ${result.favorites_removed} 个收藏点；历史实验保留。`);
          } catch (reason) {
            setNotice(reason instanceof Error ? `删除场景失败：${reason.message}` : "删除场景失败");
          }
        })()}
        sceneSwitchDisabled={running || exportingScene}
        sceneLabel={preparing ? "终止构建" : "准备当前场景数据"}
        sceneDisabled={scene?.read_only === true || (!preparing && running)}
        onPrepare={() => void (preparing ? stopPrepare() : prepareScene())}
        onNewScene={() => setSceneBuildOpen(true)}
        onImportData={() => setFarmlandImportOpen(true)}
        importDataDisabled={!sceneReady || scene?.read_only === true}
        optimizeLabel={running && !preparing ? "正在优化…" : "开始优化"}
        optimizeDisabled={running || !sceneReady || scene?.read_only === true || landuseBusy}
        onOptimize={() => void startOptimization()}
        clearSolutionsDisabled={running || retainedCount === 0}
        onClearSolutions={clearDisplayedSolutionsFromUi}
        historyOpen={historyOpen}
        onImportCase={() => void toggleHistory()}
        onSaveExperiment={() => {
          setHistoryOpen(false);
          setSaveExperimentError("");
          setSaveExperimentOpen(true);
        }}
        saveExperimentDisabled={!sceneReady || scene?.read_only === true || running || adjusting || savingExperiment || retainedCount === 0}
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
      />
      {saveExperimentOpen && <SaveExperimentDialog
        count={retainedCount}
        busy={savingExperiment}
        error={saveExperimentError}
        onClose={() => { if (!savingExperiment) setSaveExperimentOpen(false); }}
        onSave={(name) => void saveCurrentExperiment(name)}
      />}
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
        onRectPick={() => {
          setSceneBuildOpen(false);
          setRectSelecting(true);
        }}
        onSubmit={() => void submitBuild()}
        onRetry={() => void retryBuild()}
        onStop={() => void stopPrepare()}
      />
      <SceneDataImportDialog
        open={farmlandImportOpen}
        sceneId={scene?.id ?? null}
        sceneTitle={scene?.title ?? ""}
        onClose={() => setFarmlandImportOpen(false)}
        roadProvider={layerInfo?.roads.provider ?? ""}
        hasUnsavedLanduse={landuseState.dirty || landuseState.saving || landuseState.conflict}
        fieldPolicy={edit.fieldPolicy}
        onPreview={(preview) => { setImportPreview(preview); setFarmlandPreviewUrl(preview?.farmlandUrl ?? null); }}
        onCommitted={(message, cadChanged, revision) => {
          if (cadChanged) {
            setFeasibilityVisible(true);
            if (scene && revision) rememberPublishedRevision(scene.id, revision);
          } else {
            setFarmlandVisible(true);
            setFarmlandVersion((version) => version + 1);
            setRoadSegments([]);
            setRoadKinds([]);
          }
          if (!cadChanged || !revision) setSceneVersion((version) => version + 1);
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
          "admin-boundaries": {
            available: sceneReady && !adminBoundaryError && (adminBoundaries === null || adminBoundaries.features.length > 0),
            visible: adminBoundariesVisible,
            reason: !sceneReady ? "场景尚未准备完成" : adminBoundaryError || "当前范围没有行政边界数据",
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
        adminBoundariesVisible={adminBoundariesVisible}
        adminBoundaryError={adminBoundaryError}
        onToggleAdminBoundaries={() => setAdminBoundariesVisible((visible) => !visible)}
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
        pauseEvaluation={landuseBlocked !== null || landuseAwaitingReview}
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
        onDelete={favorites.remove}
      />
      {agentOpen && (
        <AgentPanel
          problemType={problemType}
          edit={edit.withPoses(edit.poses.map((pose) => presentChoice(pose, freshnessOf(pose))))}
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
          experiments={(history ?? []).filter((item) => item.summary.problem_type !== "routing")}
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
        <div className="hud-panel-body">
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
          <SetbackInput key={`${scene?.id}-road`} value={edit.roadSetbackM}
            onCommit={(value) => setEdit((current) => current.withRoadSetback(value))} />
        </label>
        <label>水体最小退距（m）
          <SetbackInput key={`${scene?.id}-water`} value={edit.waterSetbackM}
            onCommit={(value) => setEdit((current) => current.withWaterSetback(value))} />
        </label>
        {evaluationFailed.current.size > 0 && <button type="button" onClick={retrySelectedEvaluation}>
          重试全部失败评价
        </button>}
        <section className="solution-diversity" aria-label="方案多样性">
          <label htmlFor="solution-diversity">方案多样性 <strong>{diversityLevel} 档</strong></label>
          <input id="solution-diversity" type="range" min="1" max="3" step="1"
            value={diversityLevel} aria-valuetext={`显示前 ${diversityLevel} 层帕累托方案`}
            disabled={running || adjusting || diversityPool.current.length === 0}
            onChange={(event) => changeDiversity(Number(event.target.value) as ParetoLayer)} />
          <div className="diversity-ticks" aria-hidden="true"><span>少 · 1</span><span>2</span><span>3 · 多</span></div>
          <div className="diversity-legend">{PARETO_LAYER_COLORS.map((color, index) => (
            <span key={color} className={index < diversityLevel ? "" : "muted"}>
              <i style={{ backgroundColor: color }} />第 {index + 1} 层 · {diversityPool.current.filter((choice) => !choice.manual && (choice.paretoLayer ?? 1) === index + 1).length}
            </span>
          ))}</div>
          {paretoLayerNote && <p className="hud-note">{paretoLayerNote}</p>}
        </section>
        <div className="hud-actions hud-optimize-actions">
          <button type="button" className="primary" onClick={() => void startOptimization()} disabled={running || !sceneReady || scene?.read_only === true || landuseBusy}>
            {running && !preparing ? "正在优化…" : "开始优化"}
          </button>
          {(staleRetained.length > 0 || (landuseState.dirty && retainedCount > 0) || landuseState.conflict) && (
            <button type="button" onClick={() => void reevaluateStaleSolutions()} disabled={running || reevaluating || !sceneReady || scene?.read_only === true || landuseBusy}>
              {reevaluating ? "正在重新评价…" : "重新评价旧方案"}
            </button>
          )}
          <button type="button" onClick={clearDisplayedSolutionsFromUi} disabled={running || retainedCount === 0}>清空方案</button>
        </div>
        {shownJobLine && <p className="hud-note">{shownJobLine}</p>}
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
        </div>
        )}
        {landuseState.dirty && (
          <div className="landuse-draft-footer" role="status">
            <p className="landuse-draft-title">土地类型有未保存修改</p>
            <p className="landuse-draft-note">
              {landuseState.saving
                ? "正在保存土地类型修改…"
                : landuseState.conflict
                  ? (landuseState.error ?? "场景版本冲突，未写入。")
                  : "当前方案仍基于已发布场景。保存后才会更新。"}
            </p>
            <div className="hud-actions landuse-draft-actions">
              <button type="button" className="primary" onClick={() => void saveLanduseDraft()} disabled={!landuseSaveEnabled(landuseState) || scene?.read_only === true}>
                保存土地类型修改
              </button>
              <button type="button" onClick={discardLanduseChanges} disabled={landuseState.saving}>
                放弃未保存修改
              </button>
            </div>
            {(landuseState.conflict || pendingSceneSwitch) && (
              <div className="hud-actions landuse-draft-actions">
                {landuseState.conflict && (
                  <button type="button" onClick={() => void reloadPublishedLanduseEdits()}>重新加载已发布图斑</button>
                )}
                {pendingSceneSwitch && (
                  <button type="button" onClick={discardLanduseAndSwitch}>放弃并切换场景</button>
                )}
              </div>
            )}
          </div>
        )}
      </aside>
      {notice && <p className={noticeFading ? "map-toast fading" : "map-toast"} role="status">{notice}</p>}
      {showSchemeCard && selected && (
        <SchemeCard
          key={selected.id}
          schemeId={selected.id}
          title={`方案 ${edit.selectedIndex + 1}/${edit.poses.length} · ${selected.manual ? "手动添加" : `第 ${selected.paretoLayer ?? 1} 层${isAwaitingReview(selectedFreshness) ? " · 旧优化结果" : ""}`}${derivedLabel(edit, selected)}${recommended.some((item) => item.id === selected.id) ? ` · 推荐第 ${recommended.find((item) => item.id === selected.id)?.rank} 名` : ""}`}
          card={schemeCard(presentChoice(selected, selectedFreshness), liveReport, origin !== null, edit.includeDemand)}
          azimuthDeg={azimuthDeg}
          evaluationState={evaluationState}
          evaluationError={evaluationError}
          adjusting={adjusting}
          canRestore={isChoiceEdited(selected)}
          onAzimuthChange={changeAzimuth}
          onAzimuthBlur={resetAzimuth}
          onRestore={restoreOriginal}
          onRetry={() => {
            if (isAwaitingReview(freshnessOf(selected))) void reevaluateStaleSolutions();
            else retrySelectedEvaluation();
          }}
          staleMessage={selectedFreshness === "history-stale"
            ? "这是导入的历史结果，目标值尚未按当前约束评价。"
            : selectedFreshness === "revision-stale"
              ? "土地类型已更新，本方案目标值尚未按新场景评价。"
              : "当前禁区或可行域已变化，本方案目标值尚未按新约束评价。"}
          canReevaluate={!running && !reevaluating && sceneReady && scene?.read_only !== true && !landuseBusy}
          onReevaluate={() => void reevaluateStaleSolutions()}
          onDelete={() => deleteDisplayedSolution(selected.id)}
          deleteDisabled={running || adjusting || scene?.read_only === true}
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
          items={compared.map((item) => ({ ...item, choice: presentChoice(item.choice, freshnessOf(item.choice)) }))}
          scale={edit.poses.map((pose) => presentChoice(pose, freshnessOf(pose)))}
          includeDemand={edit.includeDemand}
          hasOrigin={origin !== null}
          panelMinimized={panelMinimized}
          zIndex={floatingPanelZIndex(panelOrder, "compare")}
          onBringToFront={() => bringToFront("compare")}
          onClear={() => setComparedIds([])}
        />
      )}
      </div>
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
  onRetry,
  staleMessage,
  canReevaluate,
  onReevaluate,
  onDelete,
  deleteDisabled,
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
  onRetry: () => void;
  staleMessage: string;
  canReevaluate: boolean;
  onReevaluate: () => void;
  onDelete: () => void;
  deleteDisabled: boolean;
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
  const [confirmDelete, setConfirmDelete] = useState(false);
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
              disabled={deleteDisabled}
              value={azimuthDeg}
              onChange={(event) => onAzimuthChange(event.target.value)}
              onBlur={onAzimuthBlur}
            />
          </dd></div>
          : <Metric key={row.label} row={row} />)}</dl>
        <div className="hud-actions hud-edit-actions">
          <button type="button" onClick={onRestore} disabled={!canRestore || deleteDisabled}>恢复原始方案</button>
          {confirmDelete ? <>
            <button type="button" onClick={onDelete} disabled={deleteDisabled}>确认删除</button>
            <button type="button" onClick={() => setConfirmDelete(false)}>取消</button>
          </> : <button type="button" onClick={() => setConfirmDelete(true)} disabled={deleteDisabled}>删除方案</button>}
        </div>
        {evaluationState === "loading" && (
          <p className="hud-evaluation loading">{adjusting ? "调整中，松手后重新评价…" : "正在重新评价目标与约束…"}</p>
        )}
        {evaluationState === "success" && <p className="hud-evaluation success">目标与约束已重新评价</p>}
        {evaluationState === "error" && <p className="hud-evaluation error">重新评价失败：{evaluationError} <button type="button" onClick={onRetry}>重试</button></p>}
        {evaluationState === "stale" && (
          <p className="hud-evaluation">{staleMessage}
            <button type="button" onClick={onReevaluate} disabled={!canReevaluate}>重新评价旧方案</button>
          </p>
        )}
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
        {items.some((item) => item.choice.demSoft === STALE) && <p className="hud-note">待重评的方案不参与当前约束下的对比。标成旧优化结果的层级也不是新约束下的帕累托前沿。</p>}
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

function formatAzimuthDegrees(theta: number, point: LocalPoint): string {
  return widthAzimuthDeg(theta, point).toFixed(1);
}
