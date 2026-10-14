import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { basemapStyle, initialView } from "./basemap";
import { insideSite, lngLatToLocal, localToLngLat, siteRing } from "./site_frame";
import type { LocalPoint } from "./site_frame";
import { RECOMMEND_COLORS, addSiteLayers, emptyAgentPreview, syncConstructionFeasibilityOverlay, syncElevationOverlay, syncLanduseCorrections, syncLanduseOverlays, syncRegionVisibility, syncRoadNetwork, syncSiteOverlay } from "./site_overlay";
import type { AgentPreview, ConstructionFeasibilityLayer, ElevationLayer, LanduseCorrection, LanduseLayer, RegionVisibility, RoadSegment } from "./site_overlay";
import type { BuildingFootprint } from "./building_footprint";
import type { ExclusionZone } from "./exclusion_sketch";
import type { SchemeTarget, ViewportPoint } from "./scheme_connector";
import { isBoxTool, isLoopTool, landuseEditClass } from "./toolbar_commands";
import type { MapToolName } from "./toolbar_commands";
import { pointInLanduseRing } from "./landuse_sketch";

const ERASER_CURSOR_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><path d="M5 21 17 5a3 3 0 0 1 4.2-.6l5.4 4.2a3 3 0 0 1 .5 4.2L17.5 25H8.2Z" fill="#f6fbff" stroke="#06202b" stroke-width="2"/><path d="m11 18 7 5" fill="none" stroke="#ff7d8c" stroke-width="4"/><circle cx="6" cy="25" r="2.2" fill="#ffe08a" stroke="#06202b"/></svg>`;
const ERASER_CURSOR = `url("data:image/svg+xml,${encodeURIComponent(ERASER_CURSOR_SVG)}") 6 25, pointer`;

export function WorldMap({
  tool,
  zones,
  draft,
  footprints,
  landuseLayers,
  landuseEdits,
  landuseDraft,
  landuseDraftClassId,
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
  onAddLanduseDraftPoint,
  onFinishLanduseDraft,
  onUndoLanduseDraft,
  onCancelLanduseDraft,
  onUpdateLanduseEdit,
  onDeleteLanduseEdit,
  onCloseDraft,
  onDrawOutside,
  onPickPoint,
  onPickOrigin,
  onSelectFootprint,
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
  landuseEdits: readonly LanduseCorrection[];
  landuseDraft: readonly LocalPoint[];
  landuseDraftClassId: LanduseCorrection["classId"] | null;
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
  onAddLanduseDraftPoint: (point: LocalPoint) => void;
  onFinishLanduseDraft: () => void;
  onUndoLanduseDraft: () => void;
  onCancelLanduseDraft: () => void;
  onUpdateLanduseEdit: (editId: string, points: readonly LocalPoint[]) => void;
  onDeleteLanduseEdit: (editId: string) => void;
  onCloseDraft: () => void;
  onDrawOutside: () => void;
  onPickPoint: (point: LocalPoint) => void;
  onPickOrigin: (point: LocalPoint) => void;
  onSelectFootprint: (id: string) => void;
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
  const [landuseContextMenu, setLanduseContextMenu] = useState<{
    x: number;
    y: number;
    draft: boolean;
    editId?: string;
    vertexIndex?: number;
  } | null>(null);
  const hoveredZone = useRef<string | null>(null);
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
  const landuseDraftRef = useRef(landuseDraft);
  landuseDraftRef.current = landuseDraft;
  const schemeProjectionKey = selectedFootprint
    ? `${selectedFootprint.id}:${selectedFootprint.center.x}:${selectedFootprint.center.y}:${selectedFootprint.theta}:${selectedFootprint.widthM}:${selectedFootprint.heightM}`
    : "none";
  const handlers = useRef({
    onAddDraftPoint,
    onPreviewStroke,
    onFinishStroke,
    onAddLanduseDraftPoint,
    onFinishLanduseDraft,
    onUndoLanduseDraft,
    onCancelLanduseDraft,
    onUpdateLanduseEdit,
    onDeleteLanduseEdit,
    onCloseDraft,
    onDrawOutside,
    onPickPoint,
    onPickOrigin,
    onSelectFootprint,
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
    onAddLanduseDraftPoint,
    onFinishLanduseDraft,
    onUndoLanduseDraft,
    onCancelLanduseDraft,
    onUpdateLanduseEdit,
    onDeleteLanduseEdit,
    onCloseDraft,
    onDrawOutside,
    onPickPoint,
    onPickOrigin,
    onSelectFootprint,
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
      erasePopup.current?.remove();
      erasePopup.current = null;
    }
  }, [tool, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const draftKind = tool === "feasible-box" ? "feasible" : tool === "exclusion-box" ? "exclusion" : null;
    syncSiteOverlay(map, { zones, hoveredZoneId, draft, draftKind, footprints, haulPath, origin, preview });
    syncLanduseCorrections(map, landuseEdits, landuseDraft, landuseDraftClassId);
    syncElevationOverlay(map, elevationLayer);
    syncLanduseOverlays(map, landuseLayers);
    syncConstructionFeasibilityOverlay(map, feasibilityLayer);
    syncRoadNetwork(map, roadSegments, roadsVisible);
    syncRegionVisibility(map, regionVisibility);
  }, [tool, zones, hoveredZoneId, draft, footprints, haulPath, origin, preview, landuseLayers, landuseEdits, landuseDraft, landuseDraftClassId, elevationLayer, feasibilityLayer, roadSegments, roadsVisible, regionVisibility, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const eraseZoneAt = (event: maplibregl.MapMouseEvent): string => {
      if (!map.getLayer("forbidden-fill")) return "";
      const feature = map.queryRenderedFeatures(event.point, { layers: ["forbidden-fill"] })[0];
      const id = feature?.properties?.id;
      return typeof id === "string" ? id : "";
    };
    const setEraseHover = (id: string, event?: maplibregl.MapMouseEvent) => {
      const next = id || null;
      if (hoveredZone.current !== next) {
        hoveredZone.current = next;
        setHoveredZoneId(next);
      }
      if (!next || !event) {
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
      popup.setLngLat(event.lngLat).setText("点击删除").addTo(map);
    };
    const onClick = (event: maplibregl.MapMouseEvent) => {
      const action = handlers.current;
      setLanduseContextMenu(null);
      if (gesture.current.skipClick) {
        gesture.current.skipClick = false;
        return;
      }
      if (tool === "adjust") return;
      if (landuseEditClass(tool)) {
        if (event.originalEvent.detail > 1) return;
        const local = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        if (!insideSite(local)) {
          action.onDrawOutside();
          return;
        }
        action.onAddLanduseDraftPoint(local);
        return;
      }
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
        action.onEraseZone(eraseZoneAt(event));
        setEraseHover("");
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
        setEraseHover(eraseZoneAt(event), event);
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
    const onContextMenu = (event: maplibregl.MapMouseEvent) => {
      if (landuseEditClass(tool) && landuseDraftRef.current.length > 0) {
        event.preventDefault();
        setLanduseContextMenu({ x: event.point.x, y: event.point.y, draft: true });
        return;
      }
      const local = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
      const edits = landuseEditsRef.current;
      const contained = [...edits].reverse().find((item) => pointInLanduseRing(local, item.points));
      let candidate = contained;
      let vertexIndex: number | undefined;
      if (candidate) {
        const nearby = nearestVertexIndex(map, event.point, candidate.points);
        if (nearby.distance <= 14) vertexIndex = nearby.index;
      } else {
        const nearest = edits.flatMap((item) => {
          const vertex = nearestVertexIndex(map, event.point, item.points);
          return vertex.distance <= 14 ? [{ item, ...vertex }] : [];
        }).sort((left, right) => left.distance - right.distance)[0];
        if (nearest) {
          candidate = nearest.item;
          vertexIndex = nearest.index;
        }
      }
      if (!candidate) return;
      event.preventDefault();
      setLanduseContextMenu({
        x: event.point.x,
        y: event.point.y,
        draft: false,
        editId: candidate.id,
        vertexIndex,
      });
    };
    const onMouseLeave = () => {
      if (tool === "erase") setEraseHover("");
    };
    const canvas = map.getCanvas();
    map.on("click", onClick);
    map.on("mousedown", onMouseDown);
    map.on("mousemove", onMouseMove);
    map.on("dblclick", onDoubleClick);
    map.on("contextmenu", onContextMenu);
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
      map.off("contextmenu", onContextMenu);
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

  const contextEdit = landuseContextMenu?.editId
    ? landuseEdits.find((item) => item.id === landuseContextMenu.editId)
    : undefined;
  return (
    <div className="map-viewport-shell">
      <div ref={containerRef} className="map-viewport" />
      {landuseContextMenu && (
        <div
          className="landuse-context-menu"
          role="menu"
          aria-label="土地类型图斑操作"
          style={{
            left: Math.min(landuseContextMenu.x, Math.max(0, (containerRef.current?.clientWidth ?? 220) - 220)),
            top: Math.min(landuseContextMenu.y, Math.max(0, (containerRef.current?.clientHeight ?? 120) - 120)),
          }}
          onContextMenu={(event) => event.preventDefault()}
        >
          {landuseContextMenu.draft ? (
            <>
              <button type="button" role="menuitem" disabled={landuseDraft.length < 3} onClick={() => {
                setLanduseContextMenu(null);
                handlers.current.onFinishLanduseDraft();
              }}>完成勾选</button>
              <button type="button" role="menuitem" onClick={() => {
                setLanduseContextMenu(null);
                handlers.current.onUndoLanduseDraft();
              }}>删除最近折点</button>
              <button type="button" role="menuitem" onClick={() => {
                setLanduseContextMenu(null);
                handlers.current.onCancelLanduseDraft();
              }}>取消当前图斑</button>
            </>
          ) : contextEdit ? (
            <>
              {landuseContextMenu.vertexIndex !== undefined && contextEdit.points.length > 3 && (
                <button type="button" role="menuitem" onClick={() => {
                  const points = contextEdit.points.filter((_, index) => index !== landuseContextMenu.vertexIndex);
                  setLanduseContextMenu(null);
                  handlers.current.onUpdateLanduseEdit(contextEdit.id, points);
                }}>删除最近折点</button>
              )}
              <button type="button" role="menuitem" onClick={() => {
                setLanduseContextMenu(null);
                handlers.current.onDeleteLanduseEdit(contextEdit.id);
              }}>删除整块图斑</button>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}

function nearestVertexIndex(
  map: maplibregl.Map,
  point: maplibregl.Point,
  ring: readonly LocalPoint[],
): { index: number; distance: number } {
  let index = -1;
  let distance = Number.POSITIVE_INFINITY;
  ring.forEach((vertex, vertexIndex) => {
    const lngLat = localToLngLat(vertex);
    const pixel = map.project([lngLat.lng, lngLat.lat]);
    const current = Math.hypot(pixel.x - point.x, pixel.y - point.y);
    if (current < distance) {
      index = vertexIndex;
      distance = current;
    }
  });
  return { index, distance };
}

function sameProjectedPoint(
  left: ViewportPoint | null,
  right: ViewportPoint | null,
): boolean {
  if (!left || !right) return left === right;
  return Math.abs(left.x - right.x) < 0.5 && Math.abs(left.y - right.y) < 0.5;
}
