import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { basemapStyle, initialView } from "./basemap";
import { insideSite, lngLatToLocal, localToLngLat, siteRing } from "./site_frame";
import type { LocalPoint } from "./site_frame";
import { RECOMMEND_COLORS, addSiteLayers, emptyAgentPreview, syncLanduseOverlays, syncSiteOverlay } from "./site_overlay";
import type { AgentPreview, LanduseLayer } from "./site_overlay";
import type { BuildingFootprint } from "./building_footprint";
import type { ExclusionZone } from "./exclusion_sketch";
import { isBoxTool, isLoopTool } from "./toolbar_commands";
import type { MapToolName } from "./toolbar_commands";
export function WorldMap({
  tool,
  zones,
  draft,
  footprints,
  landuseLayers,
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
  onEraseZone,
  onBoxClick,
  onBoxMove,
  onMoveFootprint,
  onFinishMove,
  onSchemeAnchor,
}: {
  tool: MapToolName;
  zones: readonly ExclusionZone[];
  draft: readonly LocalPoint[];
  footprints: readonly BuildingFootprint[];
  landuseLayers: readonly LanduseLayer[];
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
  onEraseZone: (id: string) => void;
  onBoxClick: (point: LocalPoint) => void;
  onBoxMove: (point: LocalPoint) => void;
  onMoveFootprint: (dx: number, dy: number) => void;
  onFinishMove: () => void;
  onSchemeAnchor: (point: { x: number; y: number } | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const schemeAnchor = useRef(onSchemeAnchor);
  schemeAnchor.current = onSchemeAnchor;
  const handlers = useRef({
    onAddDraftPoint,
    onPreviewStroke,
    onFinishStroke,
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
      canvas.style.cursor = "pointer";
    } else {
      map.dragPan.disable();
      map.doubleClickZoom.disable();
      canvas.style.cursor = "crosshair";
    }
  }, [tool, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    syncSiteOverlay(map, { zones, draft, footprints, haulPath, origin, preview });
    syncLanduseOverlays(map, landuseLayers);
  }, [zones, draft, footprints, haulPath, origin, preview, landuseLayers, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
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
        const layers = ["forbidden-fill", "forbidden-line"].filter((id) => map.getLayer(id));
        const feature = layers.length === 0 ? undefined : map.queryRenderedFeatures(event.point, { layers })[0];
        const id = feature?.properties?.id;
        action.onEraseZone(typeof id === "string" ? id : "");
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
    map.on("click", onClick);
    map.on("mousedown", onMouseDown);
    map.on("mousemove", onMouseMove);
    map.on("dblclick", onDoubleClick);
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
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [tool, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const update = () => {
      const selected = footprints.find((item) => item.selected);
      if (!selected) {
        schemeAnchor.current(null);
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
      schemeAnchor.current({ x, y });
    };
    update();
    map.on("move", update);
    map.on("resize", update);
    return () => {
      map.off("move", update);
      map.off("resize", update);
    };
  }, [footprints, ready]);

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
      { padding: 80, duration: 900 },
    );
  }, [focusToken, ready]);

  return <div ref={containerRef} className="map-viewport" />;
}
