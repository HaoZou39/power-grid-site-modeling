/** Map drawing. This file places frames, zones, footprints and land-use images. It does not compute objectives. */

import type { GeoJSONSource, ImageSource, Map } from "maplibre-gl";
import { localToLngLat, siteRing } from "./site_frame";
import type { LocalPoint } from "./site_frame";
import { BuildingFootprint } from "./building_footprint";
import type { ExclusionZone } from "./exclusion_sketch";

const emptyCollection = { type: "FeatureCollection" as const, features: [] };

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
      "line-color": ["match", ["get", "kind"], "feasible", "#b8ffd4", "#ff8b96"],
      "line-width": 2,
    },
  });

  map.addSource("draft-zone", { type: "geojson", data: emptyCollection });
  map.addLayer({
    id: "draft-line",
    type: "line",
    source: "draft-zone",
    paint: { "line-color": "#7dfff1", "line-width": 2, "line-dasharray": [2, 1.5] },
  });

  map.addSource("origin-mark", { type: "geojson", data: emptyCollection });
  map.addLayer({
    id: "origin-halo",
    type: "circle",
    source: "origin-mark",
    paint: { "circle-radius": 16, "circle-color": "#ffd166", "circle-opacity": 0.35 },
  });
  map.addLayer({
    id: "origin-dot",
    type: "circle",
    source: "origin-mark",
    paint: {
      "circle-radius": 7,
      "circle-color": "#ffd166",
      "circle-stroke-width": 3,
      "circle-stroke-color": "#042028",
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
  map.addLayer({
    id: "footprint-fill",
    type: "fill",
    source: "footprints",
    paint: {
      "fill-color": ["case", ["==", ["get", "selected"], true], "#39f3ff", "#d7fff8"],
      "fill-opacity": ["case", ["==", ["get", "selected"], true], 0.55, 0.22],
    },
  });
  map.addLayer({
    id: "footprint-line",
    type: "line",
    source: "footprints",
    paint: {
      "line-color": ["case", ["==", ["get", "selected"], true], "#e7fbff", "#7dfff1"],
      "line-width": ["case", ["==", ["get", "selected"], true], 3, 1.5],
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

export const emptyAgentPreview: AgentPreview = { zones: [], footprints: [], origin: null };

export type LanduseLayer = { id: string; url: string; visible: boolean };

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
      }, "forbidden-fill");
      continue;
    }
    if (map.getLayer(sourceId)) {
      map.setLayoutProperty(sourceId, "visibility", layer.visible ? "visible" : "none");
    }
  }
}

export function syncSiteOverlay(map: Map, input: {
  zones: readonly ExclusionZone[];
  draft: readonly LocalPoint[];
  footprints: readonly BuildingFootprint[];
  haulPath: readonly LocalPoint[];
  origin: LocalPoint | null;
  preview?: AgentPreview;
}): void {
  const preview = input.preview ?? emptyAgentPreview;
  setSource(map, "forbidden-zones", zoneCollection(input.zones));
  setSource(map, "draft-zone", draftCollection(input.draft));
  setSource(map, "footprints", footprintCollection(input.footprints));
  setSource(map, "haul-route", haulCollection(input.haulPath));
  setSource(map, "origin-mark", originCollection(input.origin));
  setSource(map, "agent-preview", previewCollection(preview));
  setSource(map, "agent-preview-origin", originCollection(preview.origin));
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

function zoneCollection(zones: readonly ExclusionZone[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: zones.filter((zone) => zone.points.length >= 3).map((zone) => ({
      type: "Feature",
      properties: { id: zone.id, kind: zone.kind },
      geometry: { type: "Polygon", coordinates: [closeRing(zone.points)] },
    })),
  };
}

function originCollection(origin: LocalPoint | null): GeoJSON.FeatureCollection {
  if (!origin) return emptyCollection;
  return {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      properties: { label: "进货原点" },
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

function draftCollection(points: readonly LocalPoint[]): GeoJSON.FeatureCollection {
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

function previewCollection(preview: AgentPreview): GeoJSON.FeatureCollection {
  const regions = zoneCollection(preview.zones).features;
  const poses = preview.footprints.flatMap((item) => {
    const feature = item.toFeature(toCoordinate);
    if (!feature) return [];
    return [{ ...feature, properties: { ...feature.properties, kind: "pose" } }];
  });
  return { type: "FeatureCollection", features: [...regions, ...poses] };
}

function footprintCollection(footprints: readonly BuildingFootprint[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: footprints.flatMap((item) => {
      const feature = item.toFeature(toCoordinate);
      return feature ? [feature] : [];
    }),
  };
}

function closeRing(points: LocalPoint[]): number[][] {
  const ring = points.map(toCoordinate);
  ring.push(ring[0]);
  return ring;
}

function toCoordinate(point: LocalPoint): number[] {
  const lngLat = localToLngLat(point);
  return [lngLat.lng, lngLat.lat];
}
