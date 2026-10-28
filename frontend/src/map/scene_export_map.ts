import type { Map } from "maplibre-gl";
import { worldBasemap } from "./basemap";
import type { BuildingFootprint } from "./building_footprint";
import type { LocalPoint, SiteFrame } from "./site_frame";
import {
  emptyAgentPreview,
  syncConstructionFeasibilityOverlay,
  syncElevationOverlay,
  syncFavoritePoints,
  syncLanduseCorrections,
  syncLanduseOverlays,
  syncProtectedFarmlandOverlay,
  syncRegionVisibility,
  syncRoadNetwork,
  syncSiteOverlay,
} from "./site_overlay";
import type {
  AgentPreview,
  ConstructionFeasibilityLayer,
  ElevationLayer,
  FavoriteOverlayPoint,
  LanduseCorrection,
  LanduseLayer,
  LandusePreviewShape,
  RegionVisibility,
  RoadSegment,
} from "./site_overlay";
import type { ExclusionZone } from "./exclusion_sketch";
import {
  imageLooksBlank,
  sceneExportTitle,
  withSceneExport,
} from "./scene_export";
import type { ExportExtent } from "./scene_export";

export type WorkspacePaint = {
  frame: SiteFrame;
  tool: string;
  zones: readonly ExclusionZone[];
  hoveredZoneId: string | null;
  draft: readonly LocalPoint[];
  footprints: readonly BuildingFootprint[];
  haulPath: readonly LocalPoint[];
  origin: LocalPoint | null;
  originHovered: boolean;
  preview: AgentPreview;
  favoritePoints: readonly FavoriteOverlayPoint[];
  landuseEdits: readonly LanduseCorrection[];
  landuseDraft: readonly LocalPoint[];
  landuseDraftClassId: LanduseCorrection["classId"] | null;
  showLanduseOutlines: boolean;
  landusePreview: readonly LandusePreviewShape[];
  landuseLayers: readonly LanduseLayer[];
  elevationLayer: ElevationLayer | null;
  feasibilityLayer: ConstructionFeasibilityLayer | null;
  protectedFarmlandLayer: { url: string; visible: boolean } | null;
  roadSegments: readonly RoadSegment[];
  roadKinds: readonly number[];
  roadsVisible: boolean;
  regionVisibility: RegionVisibility;
};

export type SceneCaptureRequest = {
  extent: ExportExtent;
  satellite: boolean;
  title: string;
  legend: readonly { label: string; color: string }[];
  landuseVisible: Record<"field" | "building" | "road" | "water", boolean>;
  dem: boolean;
  feasibility: { url: string } | null;
  roads: boolean;
  roadSegments: readonly RoadSegment[];
  roadKinds: readonly number[];
  regions: RegionVisibility;
  haul: boolean;
  origin: boolean;
  favorites: boolean;
  protectedFarmland: boolean;
  footprints: readonly BuildingFootprint[];
  ranks: readonly { rank: number; x: number; y: number; color: string }[];
};

export function paintWorkspace(map: Map, paint: WorkspacePaint): void {
  const draftKind = paint.tool === "feasible-box" ? "feasible" : paint.tool === "exclusion-box" ? "exclusion" : null;
  if (map.getLayer("satellite")) map.setLayoutProperty("satellite", "visibility", "visible");
  syncSiteOverlay(map, {
    zones: paint.zones,
    hoveredZoneId: paint.hoveredZoneId,
    draft: paint.draft,
    draftKind,
    footprints: paint.footprints,
    haulPath: paint.haulPath,
    origin: paint.origin,
    originHovered: paint.originHovered,
    preview: paint.preview,
  }, paint.frame);
  syncFavoritePoints(map, paint.favoritePoints, paint.frame);
  syncLanduseCorrections(
    map,
    paint.landuseEdits,
    paint.landuseDraft,
    paint.landuseDraftClassId,
    paint.showLanduseOutlines,
    paint.frame,
    paint.landusePreview,
  );
  syncElevationOverlay(map, paint.elevationLayer, paint.frame);
  syncLanduseOverlays(map, paint.landuseLayers, paint.frame);
  syncProtectedFarmlandOverlay(map, paint.protectedFarmlandLayer, paint.frame);
  syncConstructionFeasibilityOverlay(map, paint.feasibilityLayer, paint.frame);
  syncRoadNetwork(map, paint.roadSegments, paint.roadsVisible, paint.frame, paint.roadKinds);
  syncRegionVisibility(map, paint.regionVisibility);
}

export async function captureMapScene(
  map: Map,
  workspace: () => WorkspacePaint,
  request: SceneCaptureRequest,
): Promise<Blob> {
  const errors: string[] = [];
  const onError = (event: { error?: { message?: string } }) => {
    errors.push(event.error?.message || "地图资源加载失败");
  };
  map.on("error", onError);
  const badges = map.getContainer().querySelectorAll<HTMLElement>(".recommend-badge");
  badges.forEach((badge) => {
    badge.dataset.exportVisibility = badge.style.visibility;
    badge.style.visibility = "hidden";
  });
  lockMap(map);
  try {
    return await withSceneExport({
      camera: () => {
        const center = map.getCenter();
        return { lng: center.lng, lat: center.lat, zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() };
      },
      jumpTo: (camera) => {
        map.jumpTo({ center: [camera.lng, camera.lat], zoom: camera.zoom, bearing: camera.bearing, pitch: camera.pitch });
      },
      showExport: () => paintExport(map, workspace().frame, workspace(), request),
      showWorkspace: () => paintWorkspace(map, workspace()),
      fitSite: () => fitSite(map, workspace().frame),
    }, request.extent, async () => {
      await waitForMapPaint(map, () => errors[0]);
      if (errors.length > 0) throw new Error(errors[0]);
      const samples = sampleCanvas(map.getCanvas());
      if (request.satellite && imageLooksBlank(samples)) {
        throw new Error("卫星底图没有画进图片，已取消导出。");
      }
      if (!request.satellite && samples.every((pixel) => pixel.a < 8)) {
        throw new Error("图片是空的，已取消导出。");
      }
      return composeScenePng(map, workspace().frame, request);
    });
  } finally {
    map.off("error", onError);
    badges.forEach((badge) => {
      badge.style.visibility = badge.dataset.exportVisibility ?? "";
    });
    unlockMap(map);
  }
}

function paintExport(map: Map, frame: SiteFrame, workspacePaint: WorkspacePaint, request: SceneCaptureRequest): void {
  if (map.getLayer("satellite")) {
    map.setLayoutProperty("satellite", "visibility", request.satellite ? "visible" : "none");
  }
  syncProtectedFarmlandOverlay(map, workspacePaint.protectedFarmlandLayer
    ? { ...workspacePaint.protectedFarmlandLayer, visible: request.protectedFarmland }
    : null, frame);
  syncLanduseOverlays(map, workspacePaint.landuseLayers.map((layer) => ({
    ...layer,
    visible: layer.id === "field" || layer.id === "building" || layer.id === "road" || layer.id === "water"
      ? request.landuseVisible[layer.id]
      : false,
  })), frame);
  syncElevationOverlay(map, workspacePaint.elevationLayer
    ? { ...workspacePaint.elevationLayer, visible: request.dem }
    : null, frame);
  syncConstructionFeasibilityOverlay(map, request.feasibility
    ? { url: request.feasibility.url, visible: true }
    : null, frame);
  syncRoadNetwork(map, request.roads ? request.roadSegments : workspacePaint.roadSegments, request.roads, frame, request.roads ? request.roadKinds : workspacePaint.roadKinds);
  syncRegionVisibility(map, request.regions);
  syncFavoritePoints(map, request.favorites ? workspacePaint.favoritePoints : [], frame);
  syncLanduseCorrections(map, workspacePaint.landuseEdits, [], null, false, frame);
  syncSiteOverlay(map, {
    zones: workspacePaint.zones,
    draft: [],
    footprints: request.footprints,
    haulPath: request.haul ? workspacePaint.haulPath : [],
    origin: request.origin ? workspacePaint.origin : null,
    preview: emptyAgentPreview,
  }, frame);
}

function fitSite(map: Map, frame: SiteFrame): void {
  const ring = frame.ring();
  const lngs = ring.map((point) => point[0]);
  const lats = ring.map((point) => point[1]);
  map.fitBounds(
    [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
    { padding: 48, duration: 0, animate: false },
  );
}

function mapPaintSettled(map: Map): boolean {
  const tilesLoaded = typeof map.areTilesLoaded !== "function" || map.areTilesLoaded();
  const loaded = typeof map.loaded !== "function" || map.loaded();
  const moving = typeof map.isMoving === "function" && map.isMoving();
  return tilesLoaded && loaded && !moving;
}

function waitForMapPaint(map: Map, failure: () => string | undefined): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      cleanup();
      reject(new Error(failure() || "地图没有在时限内完成渲染。"));
    }, 12000);
    const finish = () => {
      window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
        cleanup();
        resolve();
      }));
    };
    const onIdle = () => {
      if (!mapPaintSettled(map)) return;
      map.off("idle", onIdle);
      finish();
    };
    const cleanup = () => {
      window.clearTimeout(timer);
      map.off("idle", onIdle);
    };
    map.on("idle", onIdle);
    map.triggerRepaint();
  });
}

function sampleCanvas(canvas: HTMLCanvasElement): { r: number; g: number; b: number; a: number }[] {
  const copy = document.createElement("canvas");
  copy.width = canvas.width;
  copy.height = canvas.height;
  const context = copy.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("无法读取地图画面。");
  try {
    context.drawImage(canvas, 0, 0);
    const pixels = [];
    const stepX = Math.max(1, Math.floor(canvas.width / 8));
    const stepY = Math.max(1, Math.floor(canvas.height / 8));
    for (let y = Math.floor(stepY / 2); y < canvas.height; y += stepY) {
      for (let x = Math.floor(stepX / 2); x < canvas.width; x += stepX) {
        const pixel = context.getImageData(x, y, 1, 1).data;
        pixels.push({ r: pixel[0], g: pixel[1], b: pixel[2], a: pixel[3] });
      }
    }
    return pixels;
  } catch {
    throw new Error("浏览器无法读取地图画面。卫星瓦片若缺少跨域许可，就不能导出。");
  }
}

function composeScenePng(map: Map, frame: SiteFrame, request: SceneCaptureRequest): Promise<Blob> {
  const source = map.getCanvas();
  const ratio = source.clientWidth > 0 ? source.width / source.clientWidth : 1;
  const band = Math.round(84 * ratio);
  const output = document.createElement("canvas");
  output.width = source.width;
  output.height = source.height + band;
  const context = output.getContext("2d");
  if (!context) return Promise.reject(new Error("无法生成 PNG。"));
  context.fillStyle = "#071018";
  context.fillRect(0, 0, output.width, output.height);
  context.drawImage(source, 0, 0);
  for (const mark of request.ranks) {
    const geographic = frame.localToLngLat({ x: mark.x, y: mark.y });
    const lngLat: [number, number] = [geographic.lng, geographic.lat];
    const projected = map.project(lngLat);
    const x = projected.x * ratio;
    const y = projected.y * ratio;
    if (x < 0 || y < 0 || x > source.width || y > source.height) continue;
    const radius = 13 * ratio;
    context.beginPath();
    context.fillStyle = mark.color;
    context.arc(x, y, radius, 0, Math.PI * 2);
    context.fill();
    context.fillStyle = "#042028";
    context.font = `700 ${Math.round(12 * ratio)}px sans-serif`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(String(mark.rank), x, y);
  }
  context.fillStyle = "#071018";
  context.fillRect(0, source.height, output.width, band);
  context.fillStyle = "#e7fbff";
  context.font = `700 ${Math.round(16 * ratio)}px sans-serif`;
  context.textAlign = "left";
  context.textBaseline = "top";
  context.fillText(sceneExportTitle(request.title), 16 * ratio, source.height + 12 * ratio);
  context.font = `500 ${Math.round(12 * ratio)}px sans-serif`;
  context.fillStyle = "#9fd7e4";
  context.fillText("优化方案分布图", 16 * ratio, source.height + 34 * ratio);
  let cursor = 16 * ratio;
  const rowY = source.height + 58 * ratio;
  context.font = `600 ${Math.round(12 * ratio)}px sans-serif`;
  for (const row of request.legend) {
    context.fillStyle = row.color;
    context.fillRect(cursor, rowY, 10 * ratio, 10 * ratio);
    context.fillStyle = "#d7f6ff";
    context.fillText(row.label, cursor + 14 * ratio, rowY - 2 * ratio);
    cursor += context.measureText(row.label).width + 28 * ratio;
  }
  if (request.satellite) {
    context.fillStyle = "#9fd7e4";
    context.font = `500 ${Math.round(10 * ratio)}px sans-serif`;
    context.textAlign = "right";
    context.fillText(worldBasemap.attribution, output.width - 16 * ratio, source.height + 14 * ratio);
  }
  return new Promise((resolve, reject) => {
    output.toBlob((blob) => {
      if (!blob || blob.size < 32) reject(new Error("浏览器没有生成有效的 PNG。"));
      else resolve(blob);
    }, "image/png");
  });
}

function lockMap(map: Map): void {
  map.dragPan.disable();
  map.scrollZoom.disable();
  map.boxZoom.disable();
  map.doubleClickZoom.disable();
  map.keyboard.disable();
  map.touchZoomRotate.disable();
}

function unlockMap(map: Map): void {
  map.scrollZoom.enable();
  map.boxZoom.enable();
  map.keyboard.enable();
  map.touchZoomRotate.enable();
}
