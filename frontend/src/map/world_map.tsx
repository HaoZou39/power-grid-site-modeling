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
  onMoveFootprint: (dx: number, dy: number) => void;
  onFinishMove: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);

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
    let stroke: LocalPoint[] = [];
    let drawing = false;
    let dragging = false;
    let moved = false;
    let skipClick = false;
    let last: LocalPoint | null = null;
    const onClick = (event: maplibregl.MapMouseEvent) => {
      if (skipClick) {
        skipClick = false;
        return;
      }
      if (tool === "adjust") return;
      if (tool === "pick" || tool === "origin") {
        const local = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        if (!insideSite(local)) {
          onDrawOutside();
          return;
        }
        if (tool === "pick") onPickPoint(local);
        else onPickOrigin(local);
        return;
      }
      if (tool === "draw") return;
      if (!map.getLayer("footprint-fill")) return;
      const feature = map.queryRenderedFeatures(event.point, { layers: ["footprint-fill"] })[0];
      const id = feature?.properties?.id;
      if (typeof id === "string" && id) onSelectFootprint(id);
    };
    const onMouseDown = (event: maplibregl.MapMouseEvent) => {
      if (tool === "adjust") {
        if (!map.getLayer("footprint-fill")) return;
        const feature = map.queryRenderedFeatures(event.point, { layers: ["footprint-fill"] })[0];
        const selected = feature?.properties?.selected;
        if (selected !== true && selected !== "true") return;
        dragging = true;
        moved = false;
        last = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        return;
      }
      if (tool !== "draw") return;
      const local = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
      if (!insideSite(local)) {
        onDrawOutside();
        return;
      }
      drawing = true;
      stroke = [local];
      onPreviewStroke(stroke);
    };
    const onMouseMove = (event: maplibregl.MapMouseEvent) => {
      if (dragging && last) {
        const local = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
        onMoveFootprint(local.x - last.x, local.y - last.y);
        last = local;
        moved = true;
        return;
      }
      if (!drawing) return;
      const local = lngLatToLocal({ lng: event.lngLat.lng, lat: event.lngLat.lat });
      if (!insideSite(local)) return;
      const previous = stroke[stroke.length - 1];
      if (Math.hypot(local.x - previous.x, local.y - previous.y) < 2) return;
      stroke = [...stroke, local];
      onPreviewStroke(stroke);
    };
    const onMouseUp = () => {
      if (dragging) {
        dragging = false;
        last = null;
        if (moved) {
          skipClick = true;
          onFinishMove();
        }
        moved = false;
        return;
      }
      if (!drawing) return;
      drawing = false;
      const finished = stroke;
      stroke = [];
      if (finished.length >= 3) onFinishStroke(finished);
      else if (finished.length === 1) onAddDraftPoint(finished[0]);
      else onPreviewStroke([]);
    };
    const onDoubleClick = (event: maplibregl.MapMouseEvent) => {
      if (tool !== "draw") return;
      event.preventDefault();
      onCloseDraft();
    };
    map.on("click", onClick);
    map.on("mousedown", onMouseDown);
    map.on("mousemove", onMouseMove);
    map.on("dblclick", onDoubleClick);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      map.off("click", onClick);
      map.off("mousedown", onMouseDown);
      map.off("mousemove", onMouseMove);
      map.off("dblclick", onDoubleClick);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [tool, ready, onAddDraftPoint, onPreviewStroke, onFinishStroke, onCloseDraft, onDrawOutside, onPickPoint, onPickOrigin, onSelectFootprint, onMoveFootprint, onFinishMove]);

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
