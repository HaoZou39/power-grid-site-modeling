import { useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { basemapStyle, initialView } from "./basemap";
import type { LocalPoint, SiteFrame } from "./site_frame";
import { containShift, paddedView, screenBounds, siteLngLatBounds, viewportPadding } from "./site_viewport";
import type { ViewportPadding } from "./site_viewport";
import { RECOMMEND_COLORS, addSiteLayers, emptyAgentPreview, syncConstructionFeasibilityOverlay } from "./site_overlay";
import type { AgentPreview, ConstructionFeasibilityLayer, ElevationLayer, FavoriteOverlayPoint, LanduseCorrection, LanduseDraftKind, LanduseLayer, LandusePreviewShape, RegionVisibility, RoadSegment } from "./site_overlay";
import type { BuildingFootprint } from "./building_footprint";
import type { ExclusionZone } from "./exclusion_sketch";
import type { SchemeTarget, ViewportPoint } from "./scheme_connector";
import { isBoxTool, isLanduseSketchTool, isLoopTool } from "./toolbar_commands";
import type { MapToolName } from "./toolbar_commands";
import { pointInLanduseRing } from "./landuse_sketch";
import { captureMapScene, paintWorkspace } from "./scene_export_map";
import type { SceneCaptureRequest, WorkspacePaint } from "./scene_export_map";
import { syncRoutingLayer } from "../routing/routing_layer";
import type { RoutingMapState } from "../routing/routing_layer";

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
  landuseDraftKind,
  showLanduseOutlines,
  landusePreview,
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
  onSelectFavorite,
  captureRef,
  routing = null,
  rectSelecting = false,
  onRectSelect,
  onRectSelectCancel,
}: {
  frame: SiteFrame;
  tool: MapToolName;
  zones: readonly ExclusionZone[];
  draft: readonly LocalPoint[];
  footprints: readonly BuildingFootprint[];
  landuseLayers: readonly LanduseLayer[];
  landuseEdits: readonly LanduseCorrection[];
  landuseDraft: readonly LocalPoint[];
  landuseDraftKind: LanduseDraftKind;
  showLanduseOutlines: boolean;
  landusePreview: readonly LandusePreviewShape[];
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
  onSelectFavorite: (favoriteId: string) => void;
  captureRef?: MutableRefObject<WorldMapCapture | null>;
  routing?: RoutingMapState | null;
  /** When true, a drag on the map reports two WGS84 corners to build a scene from. */
  rectSelecting?: boolean;
  onRectSelect?: (a: { lng: number; lat: number }, b: { lng: number; lat: number }) => void;
  onRectSelectCancel?: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const routingRef = useRef(routing);
  routingRef.current = routing;
  useEffect(() => {
    if (mapRef.current && ready) {
      syncRoutingLayer(mapRef.current, frame, routing);
      if (routing?.active) mapRef.current.getCanvas().style.cursor = routing.picking ? "crosshair" : "";
    }
  }, [ready, frame, routing]);
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
    onSelectFavorite,
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
    onSelectFavorite,
  };
  const gesture = useRef({
    stroke: [] as LocalPoint[],
    drawing: false,
    dragging: false,
    moved: false,
    skipClick: false,
    last: null as LocalPoint | null,
  });
  const framing = useRef(false);
  const clamping = useRef(false);

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
    landuseDraftKind,
    showLanduseOutlines,
    landusePreview,
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
    const currentRouting = routingRef.current;
    if (currentRouting?.active) map.getCanvas().style.cursor = currentRouting.picking ? "crosshair" : "";
  }, [tool, zones, hoveredZoneId, draft, footprints, haulPath, origin, originHovered, preview, favoritePoints, landuseEdits, landuseDraft, landuseDraftKind, showLanduseOutlines, landusePreview, landuseLayers, elevationLayer, protectedFarmlandLayer, roadSegments, roadKinds, roadsVisible, regionVisibility, ready, frame]);

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
      const currentRouting = routingRef.current;
      if (currentRouting?.active) {
        const point = frame.lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        if (currentRouting.picking) currentRouting.onPick(point);
        else if (map.getLayer("routing-lines")) {
          const id = map.queryRenderedFeatures(event.point, { layers: ["routing-lines"] })[0]?.properties?.route_id;
          if (typeof id === "string") currentRouting.onSelect(id);
        }
        return;
      }
      if (tool === "adjust") return;
      if (tool === "pose-add") {
        const local = frame.lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        if (!frame.inside(local)) {
          action.onDrawOutside();
          return;
        }
        action.onCreatePose(local);
        return;
      }
      if (isLanduseSketchTool(tool)) {
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
          return;
        }
      }
      if (!map.getLayer("footprint-fill")) return;
      const feature = map.queryRenderedFeatures(event.point, { layers: ["footprint-fill"] })[0];
      const id = feature?.properties?.id;
      if (typeof id === "string" && id) action.onSelectFootprint(id);
    };
    const onMouseDown = (event: maplibregl.MapMouseEvent) => {
      if (routingRef.current?.active) return;
      if (event.originalEvent.button !== 0) return;
      gesture.current.skipClick = false;
      const action = handlers.current;
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
      if (!isLoopTool(tool) && !isLanduseSketchTool(tool)) return;
      const local = frame.lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
      if (!frame.inside(local)) {
        action.onDrawOutside();
        return;
      }
      gesture.current.drawing = true;
      gesture.current.stroke = [local];
      if (isLanduseSketchTool(tool)) action.onPreviewLanduseDraft(gesture.current.stroke);
      else action.onPreviewStroke(gesture.current.stroke);
    };
    const onMouseMove = (event: maplibregl.MapMouseEvent) => {
      const action = handlers.current;
      const current = gesture.current;
      if (tool === "erase") {
        setEraseHover(eraseTargetAt(event), event);
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
      if (isLanduseSketchTool(tool)) action.onPreviewLanduseDraft(current.stroke);
      else action.onPreviewStroke(current.stroke);
    };
    const finishAdjustment = () => {
      const current = gesture.current;
      if (current.dragging) handlers.current.onFinishMove();
      current.dragging = false;
      current.last = null;
      current.moved = false;
    };
    const onMouseUp = (event: MouseEvent) => {
      if (event.button !== 0) return;
      const action = handlers.current;
      const current = gesture.current;
      if (current.dragging) {
        if (current.moved) current.skipClick = true;
        finishAdjustment();
        return;
      }
      if (!current.drawing) return;
      current.drawing = false;
      const finished = current.stroke;
      current.stroke = [];
      if (isLanduseSketchTool(tool)) {
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
        if (isLanduseSketchTool(tool)) handlers.current.onPreviewLanduseDraft([]);
        else handlers.current.onPreviewStroke([]);
      }
      finishAdjustment();
      gesture.current.drawing = false;
      gesture.current.dragging = false;
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

  // The site frame is the geographic ring. Panning moves it on screen, so the same measured
  // padding both fits the camera and stops a later pan from sliding the ring under the chrome.
  useEffect(() => {
    const map = mapRef.current;
    const container = containerRef.current;
    if (!map || !container || !ready || focusToken === 0) return;

    let disposed = false;
    let lastKey = "";
    let fitFrame = 0;

    const clamp = () => {
      if (disposed || framing.current || clamping.current) return;
      clamping.current = true;
      try {
        for (let step = 0; step < 4; step += 1) {
          const shift = siteFrameShift(map, frame, container);
          if (!Number.isFinite(shift.x) || !Number.isFinite(shift.y)) break;
          if (Math.abs(shift.x) < 0.5 && Math.abs(shift.y) < 0.5) break;
          shiftCamera(map, shift);
        }
      } finally {
        clamping.current = false;
      }
    };

    const fit = (animate: boolean) => {
      if (disposed || container.clientWidth < 2 || container.clientHeight < 2) return;
      const padding = measureMapPadding(container);
      const key = viewportKey(container, padding);
      if (!animate && key === lastKey) return;
      lastKey = key;
      framing.current = true;
      map.fitBounds(siteLngLatBounds(frame.ring()), {
        padding,
        duration: animate ? 900 : 0,
        linear: !animate,
        bearing: 0,
        pitch: 0,
      });
      if (!animate) {
        framing.current = false;
        clamp();
      }
    };

    const onMove = () => {
      if (framing.current) return;
      clamp();
    };
    const onMoveEnd = () => {
      if (!framing.current) return;
      framing.current = false;
      clamp();
    };

    map.on("move", onMove);
    map.on("moveend", onMoveEnd);
    fit(true);

    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => {
      if (fitFrame) return;
      fitFrame = window.requestAnimationFrame(() => {
        fitFrame = 0;
        fit(false);
      });
    });
    observer?.observe(container);
    container.closest(".map-app")?.querySelectorAll(".hud-top, .map-toolbar, .hud-panel, .map-quick").forEach((node) => {
      observer?.observe(node);
    });

    return () => {
      disposed = true;
      framing.current = false;
      if (fitFrame) window.cancelAnimationFrame(fitFrame);
      map.off("move", onMove);
      map.off("moveend", onMoveEnd);
      observer?.disconnect();
    };
  }, [focusToken, ready, frame]);

  // Scene-build drag rectangle: two WGS84 corners, isolated from the scene tools.
  const rectStart = useRef<{ x: number; y: number } | null>(null);
  const [rectBox, setRectBox] = useState<{ left: number; top: number; width: number; height: number } | null>(null);
  const rectSelectRef = useRef(onRectSelect);
  rectSelectRef.current = onRectSelect;
  const rectCancelRef = useRef(onRectSelectCancel);
  rectCancelRef.current = onRectSelectCancel;
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !rectSelecting) return;
    const canvas = map.getCanvas();
    const container = map.getCanvasContainer();
    const previousCursor = canvas.style.cursor;
    map.dragPan.disable();
    canvas.style.cursor = "crosshair";

    const pointOf = (event: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };
    const onDown = (event: MouseEvent) => {
      if (event.button !== 0) return;
      rectStart.current = pointOf(event);
      setRectBox(null);
      event.preventDefault();
    };
    const onMove = (event: MouseEvent) => {
      const start = rectStart.current;
      if (!start) return;
      const current = pointOf(event);
      setRectBox({
        left: Math.min(start.x, current.x),
        top: Math.min(start.y, current.y),
        width: Math.abs(current.x - start.x),
        height: Math.abs(current.y - start.y),
      });
    };
    const onUp = (event: MouseEvent) => {
      const start = rectStart.current;
      if (!start || event.button !== 0) return;
      rectStart.current = null;
      setRectBox(null);
      const current = pointOf(event);
      if (Math.abs(current.x - start.x) < 4 || Math.abs(current.y - start.y) < 4) return;
      const a = map.unproject([start.x, start.y]);
      const b = map.unproject([current.x, current.y]);
      rectSelectRef.current?.({ lng: a.lng, lat: a.lat }, { lng: b.lng, lat: b.lat });
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      rectStart.current = null;
      setRectBox(null);
      rectCancelRef.current?.();
    };
    container.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("keydown", onKey);
    return () => {
      map.dragPan.enable();
      canvas.style.cursor = previousCursor;
      container.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("keydown", onKey);
      rectStart.current = null;
      setRectBox(null);
    };
  }, [ready, rectSelecting]);

  return (
    <div className="map-viewport-shell">
      <div ref={containerRef} className="map-viewport" />
      {rectSelecting && !rectBox && <div className="map-rect-hint">按住左键拖出场景范围，Esc 取消</div>}
      {rectBox && <div className="map-rect-select" style={rectBox} />}
    </div>
  );
}

const OVERLAY_SELECTORS = [
  ".hud-top",
  ".map-toolbar",
  ".hud-panel",
  ".map-quick",
  ".maplibregl-ctrl-bottom-left",
  ".maplibregl-ctrl-bottom-right",
];

function measureMapPadding(container: HTMLElement): ViewportPadding {
  const rect = container.getBoundingClientRect();
  const mapBox = { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom };
  const root = container.closest(".map-app") ?? container;
  const obstructions = OVERLAY_SELECTORS.flatMap((selector) => [...root.querySelectorAll<HTMLElement>(selector)].map((element) => {
    const style = getComputedStyle(element);
    const box = element.getBoundingClientRect();
    const overlays = (style.position === "absolute" || style.position === "fixed" || style.position === "sticky")
      && style.display !== "none"
      && style.visibility !== "hidden"
      && box.width > 0
      && box.height > 0;
    return {
      box: { left: box.left, top: box.top, right: box.right, bottom: box.bottom },
      overlays,
    };
  }));
  return viewportPadding(mapBox, obstructions);
}

function shiftCamera(map: maplibregl.Map, shift: { x: number; y: number }): void {
  const center = map.project(map.getCenter());
  const next = map.unproject([center.x - shift.x, center.y - shift.y]);
  const dragging = map.dragPan.isActive() || map.scrollZoom.isZooming() || map.touchZoomRotate.isActive();
  // panBy cancels the gesture and applies the opposite screen shift. Move the transform
  // directly while dragging, and cancel coasting inertia once the pointer is up.
  if (!dragging && map.isMoving()) map.stop();
  map.transform.setCenter(next);
  map.triggerRepaint();
}

function siteFrameShift(map: maplibregl.Map, frame: SiteFrame, container: HTMLElement): { x: number; y: number } {
  const padding = measureMapPadding(container);
  const projected = frame.ring().map(([lng, lat]) => {
    const point = map.project([lng, lat]);
    return { x: point.x, y: point.y };
  });
  return containShift(screenBounds(projected), paddedView(container.clientWidth, container.clientHeight, padding));
}

function viewportKey(container: HTMLElement, padding: ViewportPadding): string {
  return [
    container.clientWidth,
    container.clientHeight,
    Math.round(padding.top),
    Math.round(padding.right),
    Math.round(padding.bottom),
    Math.round(padding.left),
  ].join(":");
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
  canvas.style.cursor = tool === "adjust"
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
