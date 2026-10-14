/** Map drawing. This file places frames, zones, footprints and land-use images. It does not compute objectives. */

import type { ExpressionSpecification, GeoJSONSource, ImageSource, Map } from "maplibre-gl";
import { localToLngLat, siteRing } from "./site_frame";
import type { LocalPoint } from "./site_frame";
import { BuildingFootprint } from "./building_footprint";
import type { ExclusionZone } from "./exclusion_sketch";

const emptyCollection = { type: "FeatureCollection" as const, features: [] };

/** Rank 1 first. Length matches the `recommend_poses` top_k limit of 10. */
export const RECOMMEND_COLORS = [
  "#ff3df2", "#ff9f1a", "#ffe14d", "#4dff88", "#4da6ff",
  "#c77dff", "#ff66c4", "#a0522d", "#00e5c7", "#9aa5b1",
];

export function addSiteLayers(map: Map): void {
  map.addSource("site-frame", { type: "geojson", data: siteFrameCollection() });
  map.addLayer({
    id: "site-frame-fill",
    type: "fill",
    source: "site-frame",
    paint: { "fill-color": "#39f3ff", "fill-opacity": 0.08 },
  });
  map.addLayer({
    id: "site-frame-line",
    type: "line",
    source: "site-frame",
    paint: { "line-color": "#7dfff1", "line-width": 2 },
  });

  map.addSource("forbidden-zones", { type: "geojson", data: emptyCollection });
  map.addLayer({
    id: "forbidden-fill",
    type: "fill",
    source: "forbidden-zones",
    paint: {
      "fill-color": ["match", ["get", "kind"], "feasible", "#3dd68c", "#ff5a6a"],
      "fill-opacity": 0.35,
    },
  });
  map.addLayer({
    id: "forbidden-line",
    type: "line",
    source: "forbidden-zones",
    paint: {
      "line-color": [
        "case",
        ["boolean", ["get", "hovered"], false],
        "#ffe08a",
        ["match", ["get", "kind"], "feasible", "#b8ffd4", "#ff8b96"],
      ],
      "line-width": ["case", ["boolean", ["get", "hovered"], false], 4, 2],
    },
  });

  map.addSource("draft-zone", { type: "geojson", data: emptyCollection });
  map.addLayer({
    id: "draft-fill",
    type: "fill",
    source: "draft-zone",
    paint: {
      "fill-color": ["match", ["get", "kind"], "feasible", "#3dd68c", "exclusion", "#ff5a6a", "#7dfff1"],
      "fill-opacity": 0.22,
    },
  });
  map.addLayer({
    id: "draft-line",
    type: "line",
    source: "draft-zone",
    paint: {
      "line-color": ["match", ["get", "kind"], "feasible", "#b8ffd4", "exclusion", "#ff8b96", "#7dfff1"],
      "line-width": 2,
      "line-dasharray": [2, 1.5],
    },
  });
  map.addSource("draft-anchor", { type: "geojson", data: emptyCollection });
  map.addLayer({
    id: "draft-anchor",
    type: "circle",
    source: "draft-anchor",
    paint: {
      "circle-radius": 6,
      "circle-color": ["match", ["get", "kind"], "feasible", "#3dd68c", "#ff5a6a"],
      "circle-stroke-width": 2,
      "circle-stroke-color": "#ffffff",
    },
  });

  map.addSource("landuse-corrections", { type: "geojson", data: emptyCollection });
  map.addLayer({
    id: "landuse-correction-line",
    type: "line",
    source: "landuse-corrections",
    paint: { "line-color": landuseColor(), "line-width": 2 },
  });
  map.addSource("landuse-draft", { type: "geojson", data: emptyCollection });
  map.addLayer({
    id: "landuse-draft-fill",
    type: "fill",
    source: "landuse-draft",
    paint: { "fill-color": landuseColor(), "fill-opacity": 0.2 },
  });
  map.addLayer({
    id: "landuse-draft-line",
    type: "line",
    source: "landuse-draft",
    paint: { "line-color": landuseColor(), "line-width": 2, "line-dasharray": [2, 1.5] },
  });

  map.addSource("origin-mark", { type: "geojson", data: emptyCollection });
  map.addLayer({
    id: "origin-halo",
    type: "circle",
    source: "origin-mark",
    paint: {
      "circle-radius": ["case", ["boolean", ["get", "hovered"], false], 21, 16],
      "circle-color": "#ffd166",
      "circle-opacity": ["case", ["boolean", ["get", "hovered"], false], 0.62, 0.35],
    },
  });
  map.addLayer({
    id: "origin-dot",
    type: "circle",
    source: "origin-mark",
    paint: {
      "circle-radius": ["case", ["boolean", ["get", "hovered"], false], 9, 7],
      "circle-color": "#ffd166",
      "circle-stroke-width": ["case", ["boolean", ["get", "hovered"], false], 4, 3],
      "circle-stroke-color": ["case", ["boolean", ["get", "hovered"], false], "#ffffff", "#042028"],
    },
  });

  map.addSource("haul-route", { type: "geojson", data: emptyCollection });
  map.addLayer({
    id: "haul-route",
    type: "line",
    source: "haul-route",
    paint: { "line-color": "#ffd166", "line-width": 4 },
  });

  map.addSource("footprints", { type: "geojson", data: emptyCollection });
  const ranked = ["match", ["get", "rank"], ...RECOMMEND_COLORS.flatMap((color, index) => [index + 1, color])];
  map.addLayer({
    id: "footprint-fill",
    type: "fill",
    source: "footprints",
    paint: {
      "fill-color": [...ranked, ["case", ["==", ["get", "selected"], true], "#39f3ff", "#d7fff8"]] as never,
      "fill-opacity": ["case", [">", ["get", "rank"], 0], 0.85, ["==", ["get", "selected"], true], 0.55, ["get", "dimmed"], 0.06, 0.22],
    },
  });
  map.addLayer({
    id: "footprint-line",
    type: "line",
    source: "footprints",
    paint: {
      "line-color": ["case", ["==", ["get", "selected"], true], "#ffffff", [...ranked, "#7dfff1"]] as never,
      "line-width": ["case", ["==", ["get", "selected"], true], 4, [">", ["get", "rank"], 0], 3, 1.5],
      "line-opacity": ["case", ["get", "dimmed"], 0.3, 1],
    },
  });

  map.addSource("agent-preview", { type: "geojson", data: emptyCollection });
  map.addLayer({
    id: "agent-preview-fill",
    type: "fill",
    source: "agent-preview",
    paint: {
      "fill-color": ["match", ["get", "kind"], "feasible", "#3dd68c", "pose", "#ffe08a", "#ff5a6a"],
      "fill-opacity": 0.18,
    },
  });
  map.addLayer({
    id: "agent-preview-line",
    type: "line",
    source: "agent-preview",
    paint: {
      "line-color": ["match", ["get", "kind"], "feasible", "#b8ffd4", "pose", "#ffe08a", "#ff8b96"],
      "line-width": 2,
      "line-dasharray": [1.2, 1.2],
    },
  });
  map.addSource("agent-preview-origin", { type: "geojson", data: emptyCollection });
  map.addLayer({
    id: "agent-preview-origin",
    type: "circle",
    source: "agent-preview-origin",
    paint: { "circle-radius": 7, "circle-color": "#ffe08a", "circle-stroke-width": 2, "circle-stroke-color": "#042028" },
  });
}

export type AgentPreview = {
  zones: readonly ExclusionZone[];
  footprints: readonly BuildingFootprint[];
  origin: LocalPoint | null;
};

export type LanduseCorrection = {
  id: string;
  classId: 1 | 2 | 5;
  points: readonly LocalPoint[];
};

export const emptyAgentPreview: AgentPreview = { zones: [], footprints: [], origin: null };

export type LanduseLayer = { id: string; url: string; visible: boolean };
export type ElevationLayer = { url: string; visible: boolean; opacity: number };
export type ConstructionFeasibilityLayer = { url: string; visible: boolean };
export type RoadSegment = [number, number, number, number];
export type RegionVisibility = { exclusion: boolean; feasible: boolean };

const feasibilitySourceUrls = new WeakMap<ImageSource, string>();
const landuseSourceUrls = new WeakMap<ImageSource, string>();

export function syncConstructionFeasibilityOverlay(
  map: Map,
  layer: ConstructionFeasibilityLayer | null,
): void {
  const sourceId = "construction-feasibility";
  let source = map.getSource(sourceId) as ImageSource | undefined;
  if (!layer) {
    if (map.getLayer(sourceId)) map.setLayoutProperty(sourceId, "visibility", "none");
    return;
  }
  const coordinates = siteRing().slice(0, 4) as [
    [number, number], [number, number], [number, number], [number, number],
  ];
  if (!source) {
    map.addSource(sourceId, { type: "image", url: layer.url, coordinates });
    map.addLayer({
      id: sourceId,
      type: "raster",
      source: sourceId,
      paint: { "raster-opacity": 1, "raster-fade-duration": 0 },
    }, map.getLayer("forbidden-fill") ? "forbidden-fill" : "site-frame-fill");
    source = map.getSource(sourceId) as ImageSource;
    feasibilitySourceUrls.set(source, layer.url);
  } else if (feasibilitySourceUrls.get(source) !== layer.url) {
    source.updateImage({ url: layer.url, coordinates });
    feasibilitySourceUrls.set(source, layer.url);
  }
  map.setLayoutProperty(sourceId, "visibility", layer.visible ? "visible" : "none");
}

export function syncElevationOverlay(map: Map, layer: ElevationLayer | null): void {
  const sourceId = "dem-elevation";
  const existing = map.getSource(sourceId) as ImageSource | undefined;
  if (!layer) {
    if (map.getLayer(sourceId)) map.setLayoutProperty(sourceId, "visibility", "none");
    return;
  }
  if (!existing) {
    const coordinates = siteRing().slice(0, 4) as [
      [number, number], [number, number], [number, number], [number, number],
    ];
    map.addSource(sourceId, { type: "image", url: layer.url, coordinates });
    map.addLayer({
      id: sourceId,
      type: "raster",
      source: sourceId,
      paint: { "raster-opacity": layer.opacity, "raster-fade-duration": 0 },
    }, "site-frame-fill");
  }
  map.setLayoutProperty(sourceId, "visibility", layer.visible ? "visible" : "none");
  map.setPaintProperty(sourceId, "raster-opacity", layer.opacity);
}

export function syncLanduseOverlays(map: Map, layers: readonly LanduseLayer[]): void {
  const coordinates = siteRing().slice(0, 4) as [
    [number, number],
    [number, number],
    [number, number],
    [number, number],
  ];
  for (const layer of layers) {
    const sourceId = `landuse-${layer.id}`;
    const existing = map.getSource(sourceId) as ImageSource | undefined;
    if (!existing) {
      if (!layer.visible) continue;
      map.addSource(sourceId, { type: "image", url: layer.url, coordinates });
      map.addLayer({
        id: sourceId,
        type: "raster",
        source: sourceId,
        paint: { "raster-opacity": 0.95, "raster-fade-duration": 0 },
      }, "site-frame-fill");
      landuseSourceUrls.set(map.getSource(sourceId) as ImageSource, layer.url);
      continue;
    }
    if (landuseSourceUrls.get(existing) !== layer.url) {
      existing.updateImage({ url: layer.url, coordinates });
      landuseSourceUrls.set(existing, layer.url);
    }
    if (map.getLayer(sourceId)) {
      map.setLayoutProperty(sourceId, "visibility", layer.visible ? "visible" : "none");
    }
  }
}

export function syncRoadNetwork(map: Map, segments: readonly RoadSegment[], visible: boolean): void {
  const sourceId = "osm-road-network";
  let source = map.getSource(sourceId) as GeoJSONSource | undefined;
  if (!source && segments.length > 0) {
    map.addSource(sourceId, { type: "geojson", data: roadCollection(segments) });
    map.addLayer({
      id: sourceId,
      type: "line",
      source: sourceId,
      paint: {
        "line-color": "#76e6ff",
        "line-width": ["interpolate", ["linear"], ["zoom"], 12, 0.8, 17, 2.2],
        "line-opacity": 0.82,
      },
    }, "site-frame-line");
    source = map.getSource(sourceId) as GeoJSONSource;
  }
  source?.setData(roadCollection(segments));
  if (map.getLayer(sourceId)) {
    map.setLayoutProperty(sourceId, "visibility", visible ? "visible" : "none");
  }
}

export function syncRegionVisibility(map: Map, visibility: RegionVisibility): void {
  const filter = visibility.exclusion && visibility.feasible
    ? null
    : visibility.exclusion
      ? ["==", ["get", "kind"], "exclusion"]
      : visibility.feasible
        ? ["==", ["get", "kind"], "feasible"]
        : ["==", ["get", "kind"], "__hidden__"];
  for (const id of ["forbidden-fill", "forbidden-line"]) {
    if (map.getLayer(id)) map.setFilter(id, filter as never);
  }
}

export function syncSiteOverlay(map: Map, input: {
  zones: readonly ExclusionZone[];
  hoveredZoneId?: string | null;
  draft: readonly LocalPoint[];
  draftKind?: "exclusion" | "feasible" | null;
  footprints: readonly BuildingFootprint[];
  haulPath: readonly LocalPoint[];
  origin: LocalPoint | null;
  originHovered?: boolean;
  preview?: AgentPreview;
}): void {
  const preview = input.preview ?? emptyAgentPreview;
  setSource(map, "forbidden-zones", zoneCollection(input.zones, input.hoveredZoneId));
  setSource(map, "draft-zone", draftCollection(input.draft, input.draftKind));
  setSource(map, "draft-anchor", draftAnchorCollection(input.draft, input.draftKind));
  setSource(map, "footprints", footprintCollection(input.footprints));
  setSource(map, "haul-route", haulCollection(input.haulPath));
  setSource(map, "origin-mark", originCollection(input.origin, input.originHovered));
  setSource(map, "agent-preview", previewCollection(preview));
  setSource(map, "agent-preview-origin", originCollection(preview.origin));
}

export function syncLanduseCorrections(
  map: Map,
  edits: readonly LanduseCorrection[],
  draft: readonly LocalPoint[],
  draftClassId: LanduseCorrection["classId"] | null,
): void {
  setSource(map, "landuse-corrections", landuseCorrectionCollection(edits));
  setSource(map, "landuse-draft", landuseDraftCollection(draft, draftClassId));
}

function setSource(map: Map, id: string, data: GeoJSON.FeatureCollection): void {
  const source = map.getSource(id) as GeoJSONSource | undefined;
  source?.setData(data);
}

function siteFrameCollection(): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      properties: {},
      geometry: { type: "Polygon", coordinates: [siteRing()] },
    }],
  };
}

function zoneCollection(zones: readonly ExclusionZone[], hoveredZoneId?: string | null): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: zones.filter((zone) => zone.points.length >= 3).map((zone) => ({
      type: "Feature",
      properties: { id: zone.id, kind: zone.kind, hovered: zone.id === hoveredZoneId },
      geometry: { type: "Polygon", coordinates: [closeRing(zone.points)] },
    })),
  };
}

function originCollection(origin: LocalPoint | null, hovered = false): GeoJSON.FeatureCollection {
  if (!origin) return emptyCollection;
  return {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      properties: { label: "进货原点", hovered },
      geometry: { type: "Point", coordinates: toCoordinate(origin) },
    }],
  };
}

function haulCollection(points: readonly LocalPoint[]): GeoJSON.FeatureCollection {
  if (points.length < 2) return emptyCollection;
  return {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      properties: {},
      geometry: { type: "LineString", coordinates: points.map(toCoordinate) },
    }],
  };
}

function draftCollection(
  points: readonly LocalPoint[],
  kind?: "exclusion" | "feasible" | null,
): GeoJSON.FeatureCollection {
  if (points.length < 2) return emptyCollection;
  if (kind && points.length >= 4) {
    return {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        properties: { kind },
        geometry: { type: "Polygon", coordinates: [points.map(toCoordinate)] },
      }],
    };
  }
  return {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      properties: { kind },
      geometry: { type: "LineString", coordinates: points.map(toCoordinate) },
    }],
  };
}

function roadCollection(segments: readonly RoadSegment[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: segments.map((segment, index) => ({
      type: "Feature",
      properties: { segment_id: index },
      geometry: {
        type: "LineString",
        coordinates: [
          toCoordinate({ x: segment[0], y: segment[1] }),
          toCoordinate({ x: segment[2], y: segment[3] }),
        ],
      },
    })),
  };
}

function draftAnchorCollection(
  points: readonly LocalPoint[],
  kind?: "exclusion" | "feasible" | null,
): GeoJSON.FeatureCollection {
  if (!kind || points.length === 0) return emptyCollection;
  return {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      properties: { kind },
      geometry: { type: "Point", coordinates: toCoordinate(points[0]) },
    }],
  };
}

function previewCollection(preview: AgentPreview): GeoJSON.FeatureCollection {
  const regions = zoneCollection(preview.zones).features;
  const poses = preview.footprints.flatMap((item) => {
    const feature = item.toFeature(toCoordinate);
    if (!feature) return [];
    return [{ ...feature, properties: { ...feature.properties, kind: "pose" } }];
  });
  return { type: "FeatureCollection", features: [...regions, ...poses] };
}

/** While a recommendation is shown, unranked and unselected footprints fade so the ranked ones stand out. */
function footprintCollection(footprints: readonly BuildingFootprint[]): GeoJSON.FeatureCollection {
  const ranking = footprints.some((item) => item.rank > 0);
  return {
    type: "FeatureCollection",
    features: footprints.flatMap((item) => {
      const feature = item.toFeature(toCoordinate);
      if (!feature) return [];
      return [{ ...feature, properties: { ...feature.properties, dimmed: ranking && item.rank === 0 && !item.selected } }];
    }),
  };
}

function closeRing(points: LocalPoint[]): number[][] {
  const ring = points.map(toCoordinate);
  ring.push(ring[0]);
  return ring;
}

function landuseCorrectionCollection(edits: readonly LanduseCorrection[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: edits.filter((edit) => edit.points.length >= 3).map((edit) => ({
      type: "Feature",
      properties: { id: edit.id, class_id: edit.classId },
      geometry: { type: "Polygon", coordinates: [closeRing([...edit.points])] },
    })),
  };
}

function landuseDraftCollection(
  points: readonly LocalPoint[],
  classId: LanduseCorrection["classId"] | null,
): GeoJSON.FeatureCollection {
  if (!classId || points.length === 0) return emptyCollection;
  const geometry: GeoJSON.Geometry = points.length === 1
    ? { type: "Point", coordinates: toCoordinate(points[0]) }
    : points.length >= 3
      ? { type: "Polygon", coordinates: [closeRing([...points])] }
      : { type: "LineString", coordinates: points.map(toCoordinate) };
  return {
    type: "FeatureCollection",
    features: [{ type: "Feature", properties: { class_id: classId }, geometry }],
  };
}

function landuseColor(): ExpressionSpecification {
  return ["match", ["get", "class_id"], 1, "#e6be28", 2, "#d6308c", 5, "#2470d6", "#ffffff"];
}

function toCoordinate(point: LocalPoint): number[] {
  const lngLat = localToLngLat(point);
  return [lngLat.lng, lngLat.lat];
}
