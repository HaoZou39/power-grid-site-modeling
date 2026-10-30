import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { Map, GeoJSONSource } from "maplibre-gl";
import type { LocalPoint, SiteFrame } from "../map/site_frame.js";
import type { RoutingRegion } from "./routing_edit.js";
import type { RoutingSolution } from "./routing_result.js";

export type RoutingMapState = {
  active: boolean;
  picking: boolean;
  start: LocalPoint | null;
  end: LocalPoint | null;
  regions: RoutingRegion[];
  draft: LocalPoint[];
  routes: RoutingSolution[];
  selectedId: string | null;
  towerRadius: number;
  onPick: (point: LocalPoint) => void;
  onSelect: (id: string) => void;
};

export function routingFeatures(frame: SiteFrame, state: RoutingMapState | null): FeatureCollection {
  const features: Feature[] = [];
  if (!state?.active) return { type: "FeatureCollection", features };
  const xy = (point: LocalPoint) => { const value = frame.localToLngLat(point); return [value.lng, value.lat]; };
  const add = (geometry: Geometry, properties: Record<string, unknown>) => features.push({ type: "Feature", geometry, properties });
  for (const [point, color, label] of [[state.start, "#39d8b0", "起点"], [state.end, "#ff8391", "终点"]] as const) {
    if (point) add({ type: "Point", coordinates: xy(point) }, { kind: "endpoint", color, label });
  }
  for (const region of state.regions) {
    if (region.points.length < 3) continue;
    add({ type: "Polygon", coordinates: [[...region.points, region.points[0]].map(xy)] },
      { kind: "zone", color: region.kind === "no_cross" ? "#ff8391" : "#f3bc62" });
  }
  if (state.draft.length > 1) add({ type: "LineString", coordinates: state.draft.map(xy) }, { kind: "zone", color: "#f3bc62" });
  for (const route of state.routes) {
    add({ type: "LineString", coordinates: route.points.map(xy) }, { kind: "route", route_id: route.id,
      color: route.id === state.selectedId ? "#49e4cf" : "#ba9cfa", width: route.id === state.selectedId ? 4 : 2 });
    if (route.id !== state.selectedId) continue;
    for (const point of route.points.filter((item) => item.role === "tower")) {
      add({ type: "Point", coordinates: xy(point) }, { kind: "tower", color: "#ffe1a2" });
      if (state.towerRadius > 0) {
        const ring = Array.from({ length: 49 }, (_, index) => xy({
          x: point.x + state.towerRadius * Math.cos(index * 2 * Math.PI / 48),
          y: point.y + state.towerRadius * Math.sin(index * 2 * Math.PI / 48),
        }));
        add({ type: "Polygon", coordinates: [ring] }, { kind: "footprint", color: "#ffe1a2" });
      }
    }
  }
  return { type: "FeatureCollection", features };
}

export function syncRoutingLayer(map: Map, frame: SiteFrame, state: RoutingMapState | null): void {
  if (!map.getSource("routing")) {
    map.addSource("routing", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({ id: "routing-fill", source: "routing", type: "fill", filter: ["==", ["geometry-type"], "Polygon"],
      paint: { "fill-color": ["get", "color"], "fill-opacity": .18 } });
    map.addLayer({ id: "routing-boundaries", source: "routing", type: "line", filter: ["!=", ["get", "kind"], "route"],
      paint: { "line-color": ["get", "color"], "line-width": 1.5 } });
    map.addLayer({ id: "routing-lines", source: "routing", type: "line", filter: ["==", ["get", "kind"], "route"],
      paint: { "line-color": ["get", "color"], "line-width": ["get", "width"] } });
    map.addLayer({ id: "routing-points", source: "routing", type: "circle", filter: ["==", ["geometry-type"], "Point"],
      paint: { "circle-color": ["get", "color"], "circle-radius": ["case", ["==", ["get", "kind"], "endpoint"], 7, 4],
        "circle-stroke-color": "#102e37", "circle-stroke-width": 1.5 } });
  }
  (map.getSource("routing") as GeoJSONSource).setData(routingFeatures(frame, state));
}
