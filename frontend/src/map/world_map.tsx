import { useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { basemapStyle, initialView } from "./basemap";
import type { LocalPoint, SiteFrame } from "./site_frame";
import { RECOMMEND_COLORS, addSiteLayers, emptyAgentPreview, syncConstructionFeasibilityOverlay } from "./site_overlay";
import type { AgentPreview, ConstructionFeasibilityLayer, ElevationLayer, FavoriteOverlayPoint, LanduseCorrection, LanduseLayer, RegionVisibility, RoadSegment } from "./site_overlay";
import type { BuildingFootprint } from "./building_footprint";
import type { ExclusionZone } from "./exclusion_sketch";
import type { SchemeTarget, ViewportPoint } from "./scheme_connector";
import { isBoxTool, isLoopTool, landuseEditClass } from "./toolbar_commands";
import type { MapToolName } from "./toolbar_commands";
import { pointInLanduseRing } from "./landuse_sketch";
import { captureMapScene, paintWorkspace } from "./scene_export_map";
import type { SceneCaptureRequest, WorkspacePaint } from "./scene_export_map";

const ERASER_CURSOR_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><path d="M5 21 17 5a3 3 0 0 1 4.2-.6l5.4 4.2a3 3 0 0 1 .5 4.2L17.5 25H8.2Z" fill="#f6fbff" stroke="#06202b" stroke-width="2"/><path d="m11 18 7 5" fill="none" stroke="#ff7d8c" stroke-width="4"/><circle cx="6" cy="25" r="2.2" fill="#ffe08a" stroke="#06202b"/></svg>`;
const ERASER_CURSOR = `url("data:image/svg+xml,${encodeURIComponent(ERASER_CURSOR_SVG)}") 6 25, pointer`;

type EraseTarget =
  | { kind: "origin" }
  | { kind: "region"; id: string }
  | { kind: "favorite"; id: string }
  | { kind: "pose"; id: string }
  | { kind: "landuse"; id: string }
  | null;

export type WorldMapCapture = {
  captureScene: (request: SceneCaptureRequest) => Promise<Blob>;
};

export function WorldMap({
  frame,
  tool,
  zones,
  draft,
  footprints,
  landuseLayers,
  landuseEdits,
  landuseDraft,
  landuseDraftClassId,
  showLanduseOutlines,
  elevationLayer,
  feasibilityLayer,
  protectedFarmlandLayer,
  roadSegments,
  roadKinds,
  roadsVisible,
  regionVisibility,
  haulPath,
  origin,
  favoritePoints,
  preview = emptyAgentPreview,
  focusToken,
  onAddDraftPoint,
  onPreviewStroke,
  onFinishStroke,
  onPreviewLanduseDraft,
  onFinishLanduseDraft,
  onDeleteLanduseEdit,
  onCloseDraft,
  onDrawOutside,
  onPickPoint,
  onPickOrigin,
  onSelectFootprint,
  onEraseOrigin,
  onEraseZone,
  onEraseFavorite,
  onErasePose,
  onBoxClick,
  onBoxMove,
  onMoveFootprint,
  onFinishMove,
  onSchemeAnchor,
  onSchemeTarget,
  onCreatePose,
  onCreateFavorite,
  onSelectFavorite,
  onPreviewFavoriteMove,
  onFinishFavoriteEdit,
  captureRef,
}: {
  frame: SiteFrame;
  tool: MapToolName;
  zones: readonly ExclusionZone[];
  draft: readonly LocalPoint[];
  footprints: readonly BuildingFootprint[];
  landuseLayers: readonly LanduseLayer[];
  landuseEdits: readonly LanduseCorrection[];
  landuseDraft: readonly LocalPoint[];
  landuseDraftClassId: LanduseCorrection["classId"] | null;
  showLanduseOutlines: boolean;
  elevationLayer: ElevationLayer | null;
  feasibilityLayer: ConstructionFeasibilityLayer | null;
  protectedFarmlandLayer: { url: string; visible: boolean } | null;
  roadSegments: readonly RoadSegment[];
  roadKinds: readonly number[];
  roadsVisible: boolean;
  regionVisibility: RegionVisibility;
  haulPath: readonly LocalPoint[];
  origin: LocalPoint | null;
  favoritePoints: readonly FavoriteOverlayPoint[];
  preview?: AgentPreview;
  focusToken: number;
  onAddDraftPoint: (point: LocalPoint) => void;
  onPreviewStroke: (points: LocalPoint[]) => void;
  onFinishStroke: (points: LocalPoint[]) => void;
  onPreviewLanduseDraft: (points: LocalPoint[]) => void;
  onFinishLanduseDraft: (points: LocalPoint[]) => void;
  onDeleteLanduseEdit: (editId: string) => void;
  onCloseDraft: () => void;
  onDrawOutside: () => void;
  onPickPoint: (point: LocalPoint) => void;
  onPickOrigin: (point: LocalPoint) => void;
  onSelectFootprint: (id: string) => void;
  onEraseOrigin: () => void;
  onEraseZone: (id: string) => void;
  onEraseFavorite: (id: string) => void;
  onErasePose: (id: string) => void;
  onBoxClick: (point: LocalPoint) => void;
  onBoxMove: (point: LocalPoint) => void;
  onMoveFootprint: (dx: number, dy: number) => void;
  onFinishMove: () => void;
  onSchemeAnchor: (point: { x: number; y: number } | null) => void;
  onSchemeTarget: (point: SchemeTarget | null) => void;
  onCreatePose: (point: LocalPoint) => void;
  onCreateFavorite: (point: LocalPoint) => void;
  onSelectFavorite: (favoriteId: string) => void;
  onPreviewFavoriteMove: (favoriteId: string, dx: number, dy: number) => void;
  onFinishFavoriteEdit: () => void;
  captureRef?: MutableRefObject<WorldMapCapture | null>;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [hoveredZoneId, setHoveredZoneId] = useState<string | null>(null);
  const hoveredZone = useRef<string | null>(null);
  const [originHovered, setOriginHovered] = useState(false);
  const hoveredOrigin = useRef(false);
  const erasePopup = useRef<maplibregl.Popup | null>(null);
  const schemeAnchor = useRef(onSchemeAnchor);
  schemeAnchor.current = onSchemeAnchor;
  const schemeTarget = useRef(onSchemeTarget);
  schemeTarget.current = onSchemeTarget;
  const lastSchemeAnchor = useRef<ViewportPoint | null>(null);
  const lastSchemeTarget = useRef<SchemeTarget | null>(null);
  const projectionUpdate = useRef<(() => void) | null>(null);
  const selectedFootprint = footprints.find((item) => item.selected) ?? null;
  const selectedFootprintRef = useRef(selectedFootprint);
  selectedFootprintRef.current = selectedFootprint;
  const landuseEditsRef = useRef(landuseEdits);
  landuseEditsRef.current = landuseEdits;
  const schemeProjectionKey = selectedFootprint
    ? `${selectedFootprint.id}:${selectedFootprint.center.x}:${selectedFootprint.center.y}:${selectedFootprint.theta}:${selectedFootprint.widthM}:${selectedFootprint.heightM}`
    : "none";
  const handlers = useRef({
    onAddDraftPoint,
    onPreviewStroke,
    onFinishStroke,
    onPreviewLanduseDraft,
    onFinishLanduseDraft,
    onDeleteLanduseEdit,
    onCloseDraft,
    onDrawOutside,
    onPickPoint,
    onPickOrigin,
    onSelectFootprint,
    onEraseOrigin,
    onEraseZone,
    onEraseFavorite,
    onErasePose,
    onBoxClick,
    onBoxMove,
    onMoveFootprint,
    onFinishMove,
    onCreatePose,
    onCreateFavorite,
    onSelectFavorite,
    onPreviewFavoriteMove,
    onFinishFavoriteEdit,
  });
  handlers.current = {
    onAddDraftPoint,
    onPreviewStroke,
    onFinishStroke,
    onPreviewLanduseDraft,
    onFinishLanduseDraft,
    onDeleteLanduseEdit,
    onCloseDraft,
    onDrawOutside,
    onPickPoint,
    onPickOrigin,
    onSelectFootprint,
    onEraseOrigin,
    onEraseZone,
    onEraseFavorite,
    onErasePose,
    onBoxClick,
    onBoxMove,
    onMoveFootprint,
    onFinishMove,
    onCreatePose,
    onCreateFavorite,
    onSelectFavorite,
    onPreviewFavoriteMove,
    onFinishFavoriteEdit,
  };
  const gesture = useRef({
    stroke: [] as LocalPoint[],
    drawing: false,
    dragging: false,
    moved: false,
    skipClick: false,
    last: null as LocalPoint | null,
    favoriteEditing: null as { id: string; mode: "move" } | null,
  });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const map = new maplibregl.Map({
      container,
      style: basemapStyle(),
      center: initialView.center,
      zoom: initialView.zoom,
      bearing: 0,
      pitch: 0,
      dragRotate: false,
      touchPitch: false,
      attributionControl: { compact: true },
      canvasContextAttributes: { preserveDrawingBuffer: true },
    });
    map.touchZoomRotate.disableRotation();
    map.keyboard.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    map.on("load", () => {
      addSiteLayers(map, frame);
      mapRef.current = map;
      setReady(true);
    });
    return () => {
      map.remove();
      mapRef.current = null;
      setReady(false);
      if (captureRef) captureRef.current = null;
    };
  }, [frame]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    syncMapInteraction(map, tool);
    if (tool !== "erase") {
      if (map.getLayer("footprint-erase")) map.setFilter("footprint-erase", ["==", ["get", "id"], ""]);
      hoveredZone.current = null;
      setHoveredZoneId(null);
      hoveredOrigin.current = false;
      setOriginHovered(false);
      erasePopup.current?.remove();
      erasePopup.current = null;
    }
  }, [tool, ready]);

  const captureLock = useRef(false);
  const paintRef = useRef<WorkspacePaint | null>(null);
  paintRef.current = {
    frame,
    tool,
    zones,
    hoveredZoneId,
    draft,
    footprints,
    haulPath,
    origin,
    originHovered,
    preview,
    favoritePoints,
    landuseEdits,
    landuseDraft,
    landuseDraftClassId,
    showLanduseOutlines,
    landuseLayers,
    elevationLayer,
    feasibilityLayer,
    protectedFarmlandLayer,
    roadSegments,
    roadKinds,
    roadsVisible,
    regionVisibility,
  };
  if (captureRef) {
    captureRef.current = {
      captureScene: (request) => {
        const map = mapRef.current;
        const paint = paintRef.current;
        if (!map || !ready || !paint) return Promise.reject(new Error("地图还没有准备好，不能导出。"));
        if (captureLock.current) return Promise.reject(new Error("正在生成图片，请稍候。"));
        captureLock.current = true;
        return captureMapScene(map, () => paintRef.current ?? paint, request).finally(() => {
          captureLock.current = false;
          const current = mapRef.current;
          if (current && paintRef.current) syncMapInteraction(current, paintRef.current.tool);
        });
      },
    };
  }

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || captureLock.current || !paintRef.current) return;
    paintWorkspace(map, paintRef.current);
  }, [tool, zones, hoveredZoneId, draft, footprints, haulPath, origin, originHovered, preview, favoritePoints, landuseEdits, landuseDraft, landuseDraftClassId, showLanduseOutlines, landuseLayers, elevationLayer, protectedFarmlandLayer, roadSegments, roadKinds, roadsVisible, regionVisibility, ready, frame]);

  const feasibilityUrl = feasibilityLayer?.url ?? null;
  const feasibilityShown = feasibilityLayer?.visible ?? false;
  useEffect(() => {
    const map = mapRef.current;
    const paint = paintRef.current;
    if (!map || !ready || captureLock.current || !paint) return;
    syncConstructionFeasibilityOverlay(map, paint.feasibilityLayer, paint.frame);
  }, [feasibilityUrl, feasibilityShown, ready, frame]);

  useEffect(() => {
    if (origin || !hoveredOrigin.current) return;
    hoveredOrigin.current = false;
    setOriginHovered(false);
    erasePopup.current?.remove();
  }, [origin]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const eraseTargetAt = (event: maplibregl.MapMouseEvent): EraseTarget => {
      if (map.getLayer("origin-dot") && map.queryRenderedFeatures(event.point, { layers: ["origin-dot"] }).length > 0) {
        return { kind: "origin" };
      }
      if (map.getLayer("favorite-fill")) {
        const favorite = map.queryRenderedFeatures(event.point, { layers: ["favorite-fill", "favorite-center", "favorite-line"] })[0];
        const id = favorite?.properties?.id;
        if (typeof id === "string" && id) return { kind: "favorite", id };
      }
      if (map.getLayer("footprint-fill")) {
        const pose = map.queryRenderedFeatures(event.point, { layers: ["footprint-fill", "footprint-line"] })[0];
        const id = pose?.properties?.id;
        if (typeof id === "string" && id) return { kind: "pose", id };
      }
      const local = frame.lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
      const patch = [...landuseEditsRef.current].reverse().find((item) => pointInLanduseRing(local, item.points));
      if (patch) return { kind: "landuse", id: patch.id };
      if (!map.getLayer("forbidden-fill")) return null;
      const feature = map.queryRenderedFeatures(event.point, { layers: ["forbidden-fill"] })[0];
      const id = feature?.properties?.id;
      return typeof id === "string" && id ? { kind: "region", id } : null;
    };
    const setEraseHover = (target: EraseTarget, event?: maplibregl.MapMouseEvent) => {
      if (map.getLayer("footprint-erase")) map.setFilter("footprint-erase", ["==", ["get", "id"], target?.kind === "pose" ? target.id : ""]);
      const zoneId = target?.kind === "region" ? target.id : null;
      const originHit = target?.kind === "origin";
      if (hoveredZone.current !== zoneId) {
        hoveredZone.current = zoneId;
        setHoveredZoneId(zoneId);
      }
      if (hoveredOrigin.current !== originHit) {
        hoveredOrigin.current = originHit;
        setOriginHovered(originHit);
      }
      if (!target || !event) {
        erasePopup.current?.remove();
        return;
      }
      const popup = erasePopup.current ?? new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
        offset: 14,
        className: "erase-tip",
      });
      erasePopup.current = popup;
      popup.setLngLat(event.lngLat).setText(target.kind === "origin" ? "点击删除进货原点" : target.kind === "favorite" ? "点击删除收藏点" : target.kind === "pose" ? "点击删除优化方案" : target.kind === "landuse" ? "点击删除土地类型图斑" : "点击删除").addTo(map);
    };
    const onClick = (event: maplibregl.MapMouseEvent) => {
      const action = handlers.current;
      if (gesture.current.skipClick) {
        gesture.current.skipClick = false;
        return;
      }
      if (tool === "adjust") return;
      if (tool === "favorite-add" || tool === "pose-add") {
        const local = frame.lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        if (!frame.inside(local)) {
          action.onDrawOutside();
          return;
        }
        if (tool === "pose-add") action.onCreatePose(local);
        else action.onCreateFavorite(local);
        return;
      }
      if (landuseEditClass(tool)) {
        return;
      }
      if (tool === "pick" || tool === "origin") {
        const local = frame.lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        if (!frame.inside(local)) {
          action.onDrawOutside();
          return;
        }
        if (tool === "pick") action.onPickPoint(local);
        else action.onPickOrigin(local);
        return;
      }
      if (isBoxTool(tool)) {
        const local = frame.lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        if (!frame.inside(local)) {
          action.onDrawOutside();
          return;
        }
        action.onBoxClick(local);
        return;
      }
      if (isLoopTool(tool)) return;
      if (tool === "erase") {
        const target = eraseTargetAt(event);
        if (target?.kind === "origin") action.onEraseOrigin();
        else if (target?.kind === "region") action.onEraseZone(target.id);
        else if (target?.kind === "favorite") action.onEraseFavorite(target.id);
        else if (target?.kind === "pose") action.onErasePose(target.id);
        else if (target?.kind === "landuse") action.onDeleteLanduseEdit(target.id);
        setEraseHover(null);
        return;
      }
      if (map.getLayer("favorite-fill")) {
        const favorite = map.queryRenderedFeatures(event.point, {
          layers: ["favorite-fill", "favorite-center"],
        })[0];
        const favoriteId = favorite?.properties?.id;
        if (typeof favoriteId === "string" && favoriteId) {
          action.onSelectFavorite(favoriteId);
          if (tool !== "favorite-adjust") return;
        }
      }
      if (tool === "favorite-adjust") return;
      if (!map.getLayer("footprint-fill")) return;
      const feature = map.queryRenderedFeatures(event.point, { layers: ["footprint-fill"] })[0];
      const id = feature?.properties?.id;
      if (typeof id === "string" && id) action.onSelectFootprint(id);
    };
    const onMouseDown = (event: maplibregl.MapMouseEvent) => {
      if (event.originalEvent.button !== 0) return;
      gesture.current.skipClick = false;
      const action = handlers.current;
      if (tool === "favorite-adjust") {
        const feature = map.queryRenderedFeatures(event.point, {
          layers: ["favorite-fill", "favorite-center"],
        })[0];
        const favoriteId = feature?.properties?.id;
        if (typeof favoriteId === "string" && favoriteId) {
          action.onSelectFavorite(favoriteId);
          gesture.current.favoriteEditing = { id: favoriteId, mode: "move" };
          gesture.current.last = frame.lngLatToLocal({
            lng: event.lngLat.lng,
            lat: event.lngLat.lat,
          });
          gesture.current.moved = false;
        }
        return;
      }
      if (tool === "adjust") {
        if (!map.getLayer("footprint-fill")) return;
        const feature = map.queryRenderedFeatures(event.point, { layers: ["footprint-fill"] })[0];
        const selected = feature?.properties?.selected;
        if (selected !== true && selected !== "true") return;
        gesture.current.dragging = true;
        gesture.current.moved = false;
        gesture.current.last = frame.lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        return;
      }
      if (!isLoopTool(tool) && !landuseEditClass(tool)) return;
      const local = frame.lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
      if (!frame.inside(local)) {
        action.onDrawOutside();
        return;
      }
      gesture.current.drawing = true;
      gesture.current.stroke = [local];
      if (landuseEditClass(tool)) action.onPreviewLanduseDraft(gesture.current.stroke);
      else action.onPreviewStroke(gesture.current.stroke);
    };
    const onMouseMove = (event: maplibregl.MapMouseEvent) => {
      const action = handlers.current;
      const current = gesture.current;
      if (tool === "erase") {
        setEraseHover(eraseTargetAt(event), event);
        return;
      }
      if (current.favoriteEditing) {
        const local = frame.lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        if (current.favoriteEditing.mode === "move" && current.last) {
          action.onPreviewFavoriteMove(
            current.favoriteEditing.id,
            local.x - current.last.x,
            local.y - current.last.y,
          );
          current.last = local;
        }
        current.moved = true;
        return;
      }
      if (isBoxTool(tool)) {
        const local = frame.lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        if (!frame.inside(local)) return;
        action.onBoxMove(local);
        return;
      }
      if (current.dragging && current.last) {
        const local = frame.lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        action.onMoveFootprint(local.x - current.last.x, local.y - current.last.y);
        current.last = local;
        current.moved = true;
        return;
      }
      if (!current.drawing) return;
      const local = frame.lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
      if (!frame.inside(local)) return;
      const previous = current.stroke[current.stroke.length - 1];
      if (Math.hypot(local.x - previous.x, local.y - previous.y) < 2) return;
      current.stroke = [...current.stroke, local];
      if (landuseEditClass(tool)) action.onPreviewLanduseDraft(current.stroke);
      else action.onPreviewStroke(current.stroke);
    };
    const finishAdjustment = () => {
      const current = gesture.current;
      if (current.favoriteEditing) handlers.current.onFinishFavoriteEdit();
      if (current.dragging) handlers.current.onFinishMove();
      current.favoriteEditing = null;
      current.dragging = false;
      current.last = null;
      current.moved = false;
    };
    const onMouseUp = (event: MouseEvent) => {
      if (event.button !== 0) return;
      const action = handlers.current;
      const current = gesture.current;
      if (current.favoriteEditing || current.dragging) {
        if (current.moved) current.skipClick = true;
        finishAdjustment();
        return;
      }
      if (!current.drawing) return;
      current.drawing = false;
      const finished = current.stroke;
      current.stroke = [];
      if (landuseEditClass(tool)) {
        if (finished.length >= 3) action.onFinishLanduseDraft(finished);
        else action.onPreviewLanduseDraft([]);
      } else if (finished.length >= 3) action.onFinishStroke(finished);
      else if (finished.length === 1) action.onAddDraftPoint(finished[0]);
      else action.onPreviewStroke([]);
    };
    const onDoubleClick = (event: maplibregl.MapMouseEvent) => {
      if (!isLoopTool(tool)) return;
      event.preventDefault();
      handlers.current.onCloseDraft();
    };
    const onMouseLeave = () => {
      if (tool === "erase") setEraseHover(null);
    };
    const canvas = map.getCanvas();
    map.on("click", onClick);
    map.on("mousedown", onMouseDown);
    map.on("mousemove", onMouseMove);
    map.on("dblclick", onDoubleClick);
    canvas.addEventListener("mouseleave", onMouseLeave);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      if (gesture.current.drawing) {
        if (landuseEditClass(tool)) handlers.current.onPreviewLanduseDraft([]);
        else handlers.current.onPreviewStroke([]);
      }
      finishAdjustment();
      gesture.current.drawing = false;
      gesture.current.dragging = false;
      gesture.current.favoriteEditing = null;
      gesture.current.skipClick = false;
      gesture.current.stroke = [];
      gesture.current.last = null;
      map.off("click", onClick);
      map.off("mousedown", onMouseDown);
      map.off("mousemove", onMouseMove);
      map.off("dblclick", onDoubleClick);
      canvas.removeEventListener("mouseleave", onMouseLeave);
      window.removeEventListener("mouseup", onMouseUp);
      erasePopup.current?.remove();
      erasePopup.current = null;
    };
  }, [tool, ready, frame]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    let animationFrame = 0;
    const publishAnchor = (next: ViewportPoint | null) => {
      if (sameProjectedPoint(lastSchemeAnchor.current, next)) return;
      lastSchemeAnchor.current = next;
      schemeAnchor.current(next);
    };
    const publishTarget = (next: SchemeTarget | null) => {
      const previous = lastSchemeTarget.current;
      if (previous?.schemeId === next?.schemeId && sameProjectedPoint(previous, next)) return;
      lastSchemeTarget.current = next;
      schemeTarget.current(next);
    };
    const update = () => {
      animationFrame = 0;
      const selected = selectedFootprintRef.current;
      if (!selected) {
        publishAnchor(null);
        publishTarget(null);
        return;
      }
      let x = Number.NEGATIVE_INFINITY;
      let y = Number.NEGATIVE_INFINITY;
      for (const corner of selected.corners()) {
        const lngLat = frame.localToLngLat(corner);
        const pixel = map.project([lngLat.lng, lngLat.lat]);
        x = Math.max(x, pixel.x);
        y = Math.max(y, pixel.y);
      }
      publishAnchor({ x, y });
      const centerLngLat = frame.localToLngLat(selected.center);
      const centerPixel = map.project([centerLngLat.lng, centerLngLat.lat]);
      const containerBounds = map.getContainer().getBoundingClientRect();
      const visible = centerPixel.x >= 0
        && centerPixel.y >= 0
        && centerPixel.x <= containerBounds.width
        && centerPixel.y <= containerBounds.height;
      publishTarget(visible ? {
        schemeId: selected.id,
        x: containerBounds.left + centerPixel.x,
        y: containerBounds.top + centerPixel.y,
      } : null);
    };
    const schedule = () => {
      if (animationFrame) return;
      animationFrame = window.requestAnimationFrame(update);
    };
    projectionUpdate.current = schedule;
    schedule();
    map.on("move", schedule);
    map.on("resize", schedule);
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    resizeObserver?.observe(map.getContainer());
    return () => {
      projectionUpdate.current = null;
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
      map.off("move", schedule);
      map.off("resize", schedule);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
      resizeObserver?.disconnect();
      publishAnchor(null);
      publishTarget(null);
    };
  }, [ready, frame]);

  useEffect(() => {
    projectionUpdate.current?.();
  }, [ready, schemeProjectionKey]);

  // `footprints` is rebuilt on every render; rebuild badges only when ranks or centers change.
  const badgeKey = footprints.filter((item) => item.rank > 0).map((item) => `${item.id}:${item.rank}:${item.center.x}:${item.center.y}`).join("|");
  // Rank badges are DOM markers: the basemap style has no glyphs, so map text layers cannot draw numbers.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const markers = footprints.filter((item) => item.rank > 0).map((item) => {
      const badge = document.createElement("button");
      badge.type = "button";
      badge.className = "recommend-badge";
      badge.textContent = String(item.rank);
      badge.style.background = RECOMMEND_COLORS[item.rank - 1];
      badge.addEventListener("click", (event) => {
        event.stopPropagation();
        handlers.current.onSelectFootprint(item.id);
      });
      const at = frame.localToLngLat(item.center);
      return new maplibregl.Marker({ element: badge }).setLngLat([at.lng, at.lat]).addTo(map);
    });
    return () => markers.forEach((marker) => marker.remove());
  }, [badgeKey, ready, frame]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || focusToken === 0) return;
    const ring = frame.ring();
    const lngs = ring.map((point) => point[0]);
    const lats = ring.map((point) => point[1]);
    map.fitBounds(
      [
        [Math.min(...lngs), Math.min(...lats)],
        [Math.max(...lngs), Math.max(...lats)],
      ],
      {
        padding: {
          top: 160,
          bottom: 60,
          left: 80,
          right: 80,
        },
        duration: 900,
        bearing: 0,
        pitch: 0,
      },
    );
  }, [focusToken, ready, frame]);

  return (
    <div className="map-viewport-shell">
      <div ref={containerRef} className="map-viewport" />
    </div>
  );
}

function syncMapInteraction(map: maplibregl.Map, tool: string): void {
  const canvas = map.getCanvas();
  if (tool === "pan") {
    map.dragPan.enable();
    map.doubleClickZoom.enable();
    canvas.style.cursor = "";
    return;
  }
  map.dragPan.disable();
  map.doubleClickZoom.disable();
  canvas.style.cursor = tool === "adjust" || tool === "favorite-adjust"
    ? "grab"
    : tool === "erase"
      ? ERASER_CURSOR
      : "crosshair";
}

function sameProjectedPoint(
  left: ViewportPoint | null,
  right: ViewportPoint | null,
): boolean {
  if (!left || !right) return left === right;
  return Math.abs(left.x - right.x) < 0.5 && Math.abs(left.y - right.y) < 0.5;
}
