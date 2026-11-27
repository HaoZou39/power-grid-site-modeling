import type { Feature, FeatureCollection, Geometry } from "geojson";
import maplibregl, { type Map, type GeoJSONSource, type LineLayerSpecification, type FilterSpecification } from "maplibre-gl";
import type { LocalPoint, SiteFrame } from "../map/site_frame.js";
import type { ExistingPowerLine, RoutingRegion } from "./routing_edit.js";
import { EXISTING_LINE_COLOR } from "./routing_edit.js";
import type { RoutingSolution } from "./routing_result.js";
import type { RoutingTool } from "./routing_interaction.js";
import { routingRegionKind } from "./routing_interaction.js";
import { routingCompareColor } from "./routing_compare.js";

const FORBIDDEN_REGION_COLOR = { no_tower: "#a96432", no_cross: "#ff5a6a" } as const;
export const ROUTING_CORRIDOR_COLOR = "#7dfff1";
const POINT_FILTER: FilterSpecification = ["all", ["==", ["geometry-type"], "Point"], ["!=", ["get", "kind"], "corridor-tower-density"]];
const BOUNDARY_FILTER: FilterSpecification = ["all", ["!=", ["get", "kind"], "route"], ["!=", ["get", "kind"], "corridor-density"]];

export type RoutingInspection = {
  kind: "route" | "tower" | "endpoint";
  pointIndex?: number;
  spanIndex?: number;
  endpoint?: "start" | "end";
  anchor?: { x: number; y: number };
};

export type RoutingCorridorView = {
  bands: { id: string; routes: { id: string; points: RoutingSolution["points"] }[] }[];
  paddingM: number;
  focusedGroupId: string | null;
  showTowerDensity: boolean;
  cameraCommand?: { kind: "focus"; points: readonly LocalPoint[] } | { kind: "back" } | { kind: "overview" };
};

export type RoutingMapState = {
  active: boolean;
  picking: boolean;
  mode: RoutingTool | null;
  start: LocalPoint | null;
  end: LocalPoint | null;
  regions: (RoutingRegion & { index: number })[];
  existingLines?: readonly ExistingPowerLine[];
  cursor?: LocalPoint | null;
  draft: LocalPoint[];
  routes: RoutingSolution[];
  selectedId: string | null;
  compared?: readonly string[];
  routeNumbers?: Readonly<Record<string, number>>;
  towerRouteIds?: readonly string[];
  corridorView?: RoutingCorridorView | null;
  resultStale?: boolean;
  towerRadius: number;
  onPick: (point: LocalPoint) => void;
  onCursor?: (point: LocalPoint) => void;
  onPreviewStroke: (points: LocalPoint[]) => void;
  onFinishStroke: (points: LocalPoint[]) => void;
  onBoxClick: (point: LocalPoint) => void;
  onBoxMove: (point: LocalPoint) => void;
  onMoveEndpoint: (which: "start" | "end", point: LocalPoint) => void;
  onEraseRegion: (index: number) => void;
  onSelect: (id: string, inspection?: RoutingInspection) => void;
  onDeselect?: () => void;
};

export function routingFeatures(frame: SiteFrame, state: RoutingMapState | null): FeatureCollection {
  const features: Feature[] = [];
  if (!state?.active) return { type: "FeatureCollection", features };
  const xy = (point: LocalPoint) => { const value = frame.localToLngLat(point); return [value.lng, value.lat]; };
  const add = (geometry: Geometry, properties: Record<string, unknown>) => features.push({ type: "Feature", geometry, properties });
  for (const [point, color, label, endpoint] of [[state.start, "#39d8b0", "起点", "start"], [state.end, "#ff8391", "终点", "end"]] as const) {
    if (point) add({ type: "Point", coordinates: xy(point) }, { kind: "endpoint", color, label, endpoint });
  }
  for (const band of state.corridorView?.bands ?? []) {
    for (const route of band.routes) if (route.points.length > 1) {
      add({ type: "LineString", coordinates: route.points.map(xy) }, {
        kind: "corridor-density", corridor_id: band.id, color: ROUTING_CORRIDOR_COLOR, opacity: .24,
      });
      if (state.corridorView?.showTowerDensity) for (const point of route.points) if (point.role === "tower") {
        add({ type: "Point", coordinates: xy(point) }, { kind: "corridor-tower-density" });
      }
    }
  }
  for (const region of state.regions) {
    if (region.points.length < 3) continue;
    add({ type: "Polygon", coordinates: [[...region.points, region.points[0]].map(xy)] },
      { kind: "zone", region_index: region.index, color: FORBIDDEN_REGION_COLOR[region.kind] });
  }
  for (const line of state.existingLines ?? []) {
    if (line.points.length < 2) continue;
    add({ type: "LineString", coordinates: line.points.map(xy) }, { kind: "existing-line", line_id: line.id, color: EXISTING_LINE_COLOR, width: 3 });
  }
  const drawingLine = state.mode === "existing_line";
  const preview = drawingLine && state.cursor && state.draft.length ? [...state.draft, state.cursor] : state.draft;
  if (preview.length > 1) add({ type: "LineString", coordinates: preview.map(xy) },
    { kind: drawingLine ? "existing-line" : "zone", color: drawingLine ? EXISTING_LINE_COLOR : FORBIDDEN_REGION_COLOR[routingRegionKind(state.mode) ?? "no_cross"] });
  if (drawingLine) for (const point of state.draft) add({ type: "Point", coordinates: xy(point) }, { kind: "existing-vertex", color: EXISTING_LINE_COLOR });
  const priority = (id: string) => id === state.selectedId ? 2 : state.compared?.includes(id) ? 1 : 0;
  const towerIds = new Set(state.towerRouteIds);
  for (const route of [...state.routes].sort((a, b) => priority(a.id) - priority(b.id))) {
    const comparedIndex = state.compared?.indexOf(route.id) ?? -1;
    const routeColor = route.id === state.selectedId ? "#49e4cf"
      : comparedIndex >= 0 ? routingCompareColor(comparedIndex) : "#ba9cfa";
    add({ type: "LineString", coordinates: route.points.map(xy) }, { kind: "route", route_id: route.id,
      color: routeColor,
      width: route.id === state.selectedId ? 4 : comparedIndex >= 0 ? 3 : 2,
      opacity: route.id === state.selectedId || comparedIndex >= 0 ? 1 : state.corridorView ? .8 : .65 });
    const showTowers = route.id === state.selectedId || towerIds.has(route.id);
    if (!showTowers) continue;
    for (const [pointIndex, point] of route.points.entries()) {
      if (point.role !== "tower") continue;
      add({ type: "Point", coordinates: xy(point) }, { kind: "tower", color: route.id === state.selectedId ? "#ffe1a2" : "#ff8f7a", route_id: route.id, point_index: pointIndex });
      if (state.towerRadius > 0) {
        const ring = Array.from({ length: 49 }, (_, index) => xy({
          x: point.x + state.towerRadius * Math.cos(index * 2 * Math.PI / 48),
          y: point.y + state.towerRadius * Math.sin(index * 2 * Math.PI / 48),
        }));
        add({ type: "Polygon", coordinates: [ring] }, { kind: "footprint", color: "#ffe1a2" });
      }
    }
  }
  const selected = state.routes.find((route) => route.id === state.selectedId);
  for (const point of selected?.existing_line_crossings ?? []) {
    add({ type: "Point", coordinates: xy(point) }, { kind: "existing-crossing", color: "#ff5a6a" });
  }
  return { type: "FeatureCollection", features };
}

export function syncRoutingLayer(map: Map, frame: SiteFrame, state: RoutingMapState | null): void {
  // MapLibre's world is 512 px at zoom 0, independently of the raster tile size.
  const metersToWorld = maplibregl.MercatorCoordinate.fromLngLat(frame.ring()[0]).meterInMercatorCoordinateUnits();
  const widthAtZoom0 = (state?.corridorView?.paddingM ?? 0) * 2 * metersToWorld * 512;
  const densityWidth: NonNullable<LineLayerSpecification["paint"]>["line-width"] =
    ["interpolate", ["exponential", 2], ["zoom"], 8, widthAtZoom0 * 2 ** 8, 22, widthAtZoom0 * 2 ** 22];
  if (!map.getSource("routing")) {
    map.addSource("routing", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({ id: "routing-fill", source: "routing", type: "fill", filter: ["==", ["geometry-type"], "Polygon"],
      paint: { "fill-color": ["get", "color"], "fill-opacity": ["coalesce", ["get", "fill_opacity"], .18] } });
    map.addLayer({ id: "routing-boundaries", source: "routing", type: "line", filter: BOUNDARY_FILTER,
      paint: { "line-color": ["get", "color"], "line-width": ["case", ["==", ["get", "kind"], "existing-line"], 3, 1.5],
        "line-opacity": ["coalesce", ["get", "boundary_opacity"], 1] } });
    map.addLayer({ id: "routing-zone-highlight", source: "routing", type: "line", filter: ["==", ["get", "region_index"], -1],
      paint: { "line-color": "#ffe08a", "line-width": 4 } });
    map.addLayer({ id: "routing-lines", source: "routing", type: "line", filter: ["==", ["get", "kind"], "route"],
      paint: { "line-color": ["get", "color"], "line-width": ["get", "width"], "line-opacity": ["get", "opacity"] } });
    map.addLayer({ id: "routing-points", source: "routing", type: "circle", filter: POINT_FILTER,
      paint: { "circle-color": ["get", "color"], "circle-opacity": 1,
        "circle-radius": ["case", ["==", ["get", "kind"], "endpoint"], 7, 4],
        "circle-stroke-color": "#102e37", "circle-stroke-width": 1.5,
        "circle-stroke-opacity": 1 } });
  }
  const before = map.getLayer("routing-boundaries") ? "routing-boundaries" : undefined;
  if (!map.getLayer("routing-tower-density")) map.addLayer({ id: "routing-tower-density", source: "routing", type: "heatmap",
    filter: ["==", ["get", "kind"], "corridor-tower-density"],
    paint: { "heatmap-radius": 22, "heatmap-intensity": 1, "heatmap-opacity": .85,
      "heatmap-color": ["interpolate", ["linear"], ["heatmap-density"], 0, "rgba(255,185,53,0)",
        .3, "rgba(255,185,53,.15)", .6, "rgba(255,140,30,.52)", 1, "rgba(191,53,13,.88)"] } }, before);
  if (!map.getLayer("routing-corridor-density")) map.addLayer({ id: "routing-corridor-density", source: "routing", type: "line",
    filter: ["==", ["get", "kind"], "corridor-density"],
    paint: { "line-color": ["get", "color"], "line-opacity": ["get", "opacity"], "line-width": densityWidth } }, before);
  // Existing sources survive hot reload; refresh both filters when adding density features.
  for (const [id, filter] of [["routing-points", POINT_FILTER], ["routing-boundaries", BOUNDARY_FILTER]] as const) {
    if (JSON.stringify(map.getFilter(id)) !== JSON.stringify(filter)) map.setFilter(id, filter);
  }
  if (JSON.stringify(map.getPaintProperty("routing-corridor-density", "line-width")) !== JSON.stringify(densityWidth)) {
    map.setPaintProperty("routing-corridor-density", "line-width", densityWidth);
  }
  (map.getSource("routing") as GeoJSONSource).setData(routingFeatures(frame, state));
}
