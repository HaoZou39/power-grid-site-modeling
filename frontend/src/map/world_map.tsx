import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { basemapStyle, initialView } from "./basemap";
import { insideSite, lngLatToLocal, siteRing } from "./site_frame";
import type { LocalPoint } from "./site_frame";
import { addSiteLayers, syncLanduseOverlays, syncSiteOverlay } from "./site_overlay";
import type { LanduseLayer } from "./site_overlay";
import type { BuildingFootprint } from "./building_footprint";
import type { ExclusionZone } from "./exclusion_sketch";
import type { MapToolName } from "./toolbar_commands";

/** World satellite map. Drag and wheel zoom belong to MapLibre, not to an image element. */
export function WorldMap({
  tool,
  zones,
  draft,
  footprints,
  landuseLayers,
  haulPath,
  origin,
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
  onMoveFootprint,
  onFinishMove,
}: {
  tool: MapToolName;
  zones: readonly ExclusionZone[];
  draft: readonly LocalPoint[];
  footprints: readonly BuildingFootprint[];
  landuseLayers: readonly LanduseLayer[];
  haulPath: readonly LocalPoint[];
  origin: LocalPoint | null;
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
  onMoveFootprint: (dx: number, dy: number) => void;
  onFinishMove: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
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
    syncSiteOverlay(map, { zones, draft, footprints, haulPath, origin });
    syncLanduseOverlays(map, landuseLayers);
  }, [zones, draft, footprints, haulPath, origin, landuseLayers, ready]);

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
      if (tool === "draw") return;
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
      if (tool !== "draw") return;
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
      if (tool !== "draw") return;
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
