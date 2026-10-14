import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { basemapStyle, initialView } from "./basemap";
import { insideSite, lngLatToLocal, localToLngLat, siteRing } from "./site_frame";
import type { LocalPoint } from "./site_frame";
import { RECOMMEND_COLORS, addSiteLayers, emptyAgentPreview, syncConstructionFeasibilityOverlay, syncElevationOverlay, syncLanduseOverlays, syncRegionVisibility, syncRoadNetwork, syncSiteOverlay } from "./site_overlay";
import type { AgentPreview, ConstructionFeasibilityLayer, ElevationLayer, LanduseLayer, RegionVisibility, RoadSegment } from "./site_overlay";
import type { BuildingFootprint } from "./building_footprint";
import type { ExclusionZone } from "./exclusion_sketch";
import type { SchemeTarget, ViewportPoint } from "./scheme_connector";
import { isBoxTool, isLoopTool } from "./toolbar_commands";
import type { MapToolName } from "./toolbar_commands";

const ERASER_CURSOR_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><path d="M5 21 17 5a3 3 0 0 1 4.2-.6l5.4 4.2a3 3 0 0 1 .5 4.2L17.5 25H8.2Z" fill="#f6fbff" stroke="#06202b" stroke-width="2"/><path d="m11 18 7 5" fill="none" stroke="#ff7d8c" stroke-width="4"/><circle cx="6" cy="25" r="2.2" fill="#ffe08a" stroke="#06202b"/></svg>`;
const ERASER_CURSOR = `url("data:image/svg+xml,${encodeURIComponent(ERASER_CURSOR_SVG)}") 6 25, pointer`;

type EraseTarget =
  | { kind: "origin" }
  | { kind: "region"; id: string }
  | null;

export function WorldMap({
  tool,
  zones,
  draft,
  footprints,
  landuseLayers,
  elevationLayer,
  feasibilityLayer,
  roadSegments,
  roadsVisible,
  regionVisibility,
  haulPath,
  origin,
  preview = emptyAgentPreview,
  focusToken,
  onAddDraftPoint,
  onPreviewStroke,
  onFinishStroke,
  onCloseDraft,
  onDrawOutside,
  onPickPoint,
  onPickOrigin,
  onSelectFootprint,
  onEraseOrigin,
  onEraseZone,
  onBoxClick,
  onBoxMove,
  onMoveFootprint,
  onFinishMove,
  onSchemeAnchor,
  onSchemeTarget,
}: {
  tool: MapToolName;
  zones: readonly ExclusionZone[];
  draft: readonly LocalPoint[];
  footprints: readonly BuildingFootprint[];
  landuseLayers: readonly LanduseLayer[];
  elevationLayer: ElevationLayer | null;
  feasibilityLayer: ConstructionFeasibilityLayer | null;
  roadSegments: readonly RoadSegment[];
  roadsVisible: boolean;
  regionVisibility: RegionVisibility;
  haulPath: readonly LocalPoint[];
  origin: LocalPoint | null;
  preview?: AgentPreview;
  focusToken: number;
  onAddDraftPoint: (point: LocalPoint) => void;
  onPreviewStroke: (points: LocalPoint[]) => void;
  onFinishStroke: (points: LocalPoint[]) => void;
  onCloseDraft: () => void;
  onDrawOutside: () => void;
  onPickPoint: (point: LocalPoint) => void;
  onPickOrigin: (point: LocalPoint) => void;
  onSelectFootprint: (id: string) => void;
  onEraseOrigin: () => void;
  onEraseZone: (id: string) => void;
  onBoxClick: (point: LocalPoint) => void;
  onBoxMove: (point: LocalPoint) => void;
  onMoveFootprint: (dx: number, dy: number) => void;
  onFinishMove: () => void;
  onSchemeAnchor: (point: { x: number; y: number } | null) => void;
  onSchemeTarget: (point: SchemeTarget | null) => void;
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
  const schemeProjectionKey = selectedFootprint
    ? `${selectedFootprint.id}:${selectedFootprint.center.x}:${selectedFootprint.center.y}:${selectedFootprint.theta}:${selectedFootprint.widthM}:${selectedFootprint.heightM}`
    : "none";
  const handlers = useRef({
    onAddDraftPoint,
    onPreviewStroke,
    onFinishStroke,
    onCloseDraft,
    onDrawOutside,
    onPickPoint,
    onPickOrigin,
    onSelectFootprint,
    onEraseOrigin,
    onEraseZone,
    onBoxClick,
    onBoxMove,
    onMoveFootprint,
    onFinishMove,
  });
  handlers.current = {
    onAddDraftPoint,
    onPreviewStroke,
    onFinishStroke,
    onCloseDraft,
    onDrawOutside,
    onPickPoint,
    onPickOrigin,
    onSelectFootprint,
    onEraseOrigin,
    onEraseZone,
    onBoxClick,
    onBoxMove,
    onMoveFootprint,
    onFinishMove,
  };
  const gesture = useRef({
    stroke: [] as LocalPoint[],
    drawing: false,
    dragging: false,
    moved: false,
    skipClick: false,
    last: null as LocalPoint | null,
  });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const map = new maplibregl.Map({
      container,
      style: basemapStyle(),
      center: initialView.center,
      zoom: initialView.zoom,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    map.on("load", () => {
      addSiteLayers(map);
      mapRef.current = map;
      setReady(true);
    });
    return () => {
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const canvas = map.getCanvas();
    if (tool === "pan") {
      map.dragPan.enable();
      map.doubleClickZoom.enable();
      canvas.style.cursor = "";
    } else if (tool === "adjust") {
      map.dragPan.disable();
      map.doubleClickZoom.disable();
      canvas.style.cursor = "grab";
    } else if (tool === "erase") {
      map.dragPan.disable();
      map.doubleClickZoom.disable();
      canvas.style.cursor = ERASER_CURSOR;
    } else {
      map.dragPan.disable();
      map.doubleClickZoom.disable();
      canvas.style.cursor = "crosshair";
    }
    if (tool !== "erase") {
      hoveredZone.current = null;
      setHoveredZoneId(null);
      hoveredOrigin.current = false;
      setOriginHovered(false);
      erasePopup.current?.remove();
      erasePopup.current = null;
    }
  }, [tool, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const draftKind = tool === "feasible-box" ? "feasible" : tool === "exclusion-box" ? "exclusion" : null;
    syncSiteOverlay(map, { zones, hoveredZoneId, draft, draftKind, footprints, haulPath, origin, originHovered, preview });
    syncElevationOverlay(map, elevationLayer);
    syncLanduseOverlays(map, landuseLayers);
    syncConstructionFeasibilityOverlay(map, feasibilityLayer);
    syncRoadNetwork(map, roadSegments, roadsVisible);
    syncRegionVisibility(map, regionVisibility);
  }, [tool, zones, hoveredZoneId, draft, footprints, haulPath, origin, originHovered, preview, landuseLayers, elevationLayer, feasibilityLayer, roadSegments, roadsVisible, regionVisibility, ready]);

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
      if (!map.getLayer("forbidden-fill")) return null;
      const feature = map.queryRenderedFeatures(event.point, { layers: ["forbidden-fill"] })[0];
      const id = feature?.properties?.id;
      return typeof id === "string" && id ? { kind: "region", id } : null;
    };
    const setEraseHover = (target: EraseTarget, event?: maplibregl.MapMouseEvent) => {
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
      popup.setLngLat(event.lngLat).setText(target.kind === "origin" ? "点击删除进货原点" : "点击删除").addTo(map);
    };
    const onClick = (event: maplibregl.MapMouseEvent) => {
      const action = handlers.current;
      if (gesture.current.skipClick) {
        gesture.current.skipClick = false;
        return;
      }
      if (tool === "adjust") return;
      if (tool === "pick" || tool === "origin") {
        const local = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        if (!insideSite(local)) {
          action.onDrawOutside();
          return;
        }
        if (tool === "pick") action.onPickPoint(local);
        else action.onPickOrigin(local);
        return;
      }
      if (isBoxTool(tool)) {
        const local = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        if (!insideSite(local)) {
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
        setEraseHover(null);
        return;
      }
      if (!map.getLayer("footprint-fill")) return;
      const feature = map.queryRenderedFeatures(event.point, { layers: ["footprint-fill"] })[0];
      const id = feature?.properties?.id;
      if (typeof id === "string" && id) action.onSelectFootprint(id);
    };
    const onMouseDown = (event: maplibregl.MapMouseEvent) => {
      const action = handlers.current;
      if (tool === "adjust") {
        if (!map.getLayer("footprint-fill")) return;
        const feature = map.queryRenderedFeatures(event.point, { layers: ["footprint-fill"] })[0];
        const selected = feature?.properties?.selected;
        if (selected !== true && selected !== "true") return;
        gesture.current.dragging = true;
        gesture.current.moved = false;
        gesture.current.last = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        return;
      }
      if (!isLoopTool(tool)) return;
      const local = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
      if (!insideSite(local)) {
        action.onDrawOutside();
        return;
      }
      gesture.current.drawing = true;
      gesture.current.stroke = [local];
      action.onPreviewStroke(gesture.current.stroke);
    };
    const onMouseMove = (event: maplibregl.MapMouseEvent) => {
      const action = handlers.current;
      const current = gesture.current;
      if (tool === "erase") {
        setEraseHover(eraseTargetAt(event), event);
        return;
      }
      if (isBoxTool(tool)) {
        const local = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        if (!insideSite(local)) return;
        action.onBoxMove(local);
        return;
      }
      if (current.dragging && current.last) {
        const local = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        action.onMoveFootprint(local.x - current.last.x, local.y - current.last.y);
        current.last = local;
        current.moved = true;
        return;
      }
      if (!current.drawing) return;
      const local = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
      if (!insideSite(local)) return;
      const previous = current.stroke[current.stroke.length - 1];
      if (Math.hypot(local.x - previous.x, local.y - previous.y) < 2) return;
      current.stroke = [...current.stroke, local];
      action.onPreviewStroke(current.stroke);
    };
    const onMouseUp = () => {
      const action = handlers.current;
      const current = gesture.current;
      if (current.dragging) {
        current.dragging = false;
        current.last = null;
        if (current.moved) {
          current.skipClick = true;
          action.onFinishMove();
        }
        current.moved = false;
        return;
      }
      if (!current.drawing) return;
      current.drawing = false;
      const finished = current.stroke;
      current.stroke = [];
      if (finished.length >= 3) action.onFinishStroke(finished);
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
      if (gesture.current.drawing) handlers.current.onPreviewStroke([]);
      gesture.current.drawing = false;
      gesture.current.dragging = false;
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
  }, [tool, ready]);

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
        const lngLat = localToLngLat(corner);
        const pixel = map.project([lngLat.lng, lngLat.lat]);
        x = Math.max(x, pixel.x);
        y = Math.max(y, pixel.y);
      }
      publishAnchor({ x, y });
      const centerLngLat = localToLngLat(selected.center);
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
  }, [ready]);

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
      const at = localToLngLat(item.center);
      return new maplibregl.Marker({ element: badge }).setLngLat([at.lng, at.lat]).addTo(map);
    });
    return () => markers.forEach((marker) => marker.remove());
  }, [badgeKey, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || focusToken === 0) return;
    const ring = siteRing();
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
      },
    );
  }, [focusToken, ready]);

  return <div ref={containerRef} className="map-viewport" />;
}

function sameProjectedPoint(
  left: ViewportPoint | null,
  right: ViewportPoint | null,
): boolean {
  if (!left || !right) return left === right;
  return Math.abs(left.x - right.x) < 0.5 && Math.abs(left.y - right.y) < 0.5;
}
