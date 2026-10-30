import { PARETO_LAYER_COLORS } from "./solution_diversity.js";
import type { ParetoLayer } from "./solution_diversity.js";

export const EXPORT_LAYERS = [
  { id: "satellite", label: "卫星影像底图" },
  { id: "dem", label: "DEM 高程" },
  { id: "field", label: "农田" },
  { id: "protected-farmland", label: "永久基本农田" },
  { id: "building", label: "已有建筑" },
  { id: "road", label: "遥感道路" },
  { id: "water", label: "水体" },
  { id: "osm", label: "道路网络" },
  { id: "admin-boundaries", label: "行政边界" },
  { id: "feasibility", label: "建设可行性" },
  { id: "exclusion", label: "手绘禁区" },
  { id: "feasible", label: "手绘可行域" },
  { id: "haul", label: "进站路径" },
  { id: "origin", label: "进货原点" },
  { id: "favorites", label: "收藏站址" },
] as const;

export type ExportLayerId = (typeof EXPORT_LAYERS)[number]["id"];
export type ExportExtent = "site" | "view";
export type ExportLayerFlags = Record<ExportLayerId, boolean>;

export type ExportLayerChoice = {
  id: ExportLayerId;
  label: string;
  checked: boolean;
  disabled: boolean;
  reason: string;
};

/** Same paints as the map layers. Pareto colors stay in PARETO_LAYER_COLORS. */
const LAYER_SWATCH: Record<ExportLayerId, string> = {
  satellite: "#8d9aa3",
  dem: "#c4a574",
  field: "#e6be28",
  "protected-farmland": "#a8328f",
  building: "#d6308c",
  road: "#dc3030",
  water: "#2470d6",
  osm: "#76e6ff",
  "admin-boundaries": "#efecf8",
  feasibility: "#ff5a6a",
  exclusion: "#ff5a6a",
  feasible: "#3dd68c",
  haul: "#ffd166",
  origin: "#ffd166",
  favorites: "#ffe08a",
};

const ILLEGAL_FILENAME = /[\\/:*?"<>|\u0000-\u001f]/g;

export type SceneCamera = {
  lng: number;
  lat: number;
  zoom: number;
  bearing: number;
  pitch: number;
};

export type ExportPainter = {
  camera: () => SceneCamera;
  jumpTo: (camera: SceneCamera) => void;
  showExport: () => void;
  showWorkspace: () => void;
  fitSite: () => void;
};

export function sceneExportTitle(sceneTitle: string, mode: "site" | "routing" = "site"): string {
  const suffix = mode === "routing" ? "选线规划" : "选址规划";
  const title = sceneTitle.trim() || (mode === "routing" ? "选线场景" : "选址场景");
  return title.endsWith(suffix) ? title : `${title}${suffix}`;
}

export function defaultExportFilename(sceneTitle: string, mode: "site" | "routing" = "site"): string {
  return `${sceneExportTitle(sceneTitle, mode)}-优化方案分布图`;
}

export function pngFilename(raw: string, sceneTitle: string, mode: "site" | "routing" = "site"): string {
  const fallback = defaultExportFilename(sceneTitle, mode);
  let stem = raw.replace(ILLEGAL_FILENAME, " ").replace(/\s+/g, " ").trim().replace(/[. ]+$/g, "");
  while (stem.toLowerCase().endsWith(".png")) stem = stem.slice(0, -4).replace(/[. ]+$/g, "");
  if (!stem) stem = fallback;
  if (stem.length > 80) stem = stem.slice(0, 80).replace(/[. ]+$/g, "");
  if (!stem) stem = fallback;
  return `${stem}.png`;
}

export function describeExportLayers(
  availability: Partial<Record<ExportLayerId, { available: boolean; visible: boolean; reason?: string }>>,
): ExportLayerChoice[] {
  return EXPORT_LAYERS.map((item) => {
    const state = availability[item.id];
    const available = state?.available === true;
    const checked = item.id === "satellite" ? available : available && state?.visible === true;
    return {
      id: item.id,
      label: item.label,
      checked,
      disabled: !available,
      reason: available ? "" : (state?.reason || "当前场景不可用"),
    };
  });
}

export function paretoLayerCounts<T extends { paretoLayer?: number; manual?: boolean }>(
  pool: readonly T[],
): Record<ParetoLayer, number> {
  const counts: Record<ParetoLayer, number> = { 1: 0, 2: 0, 3: 0 };
  for (const pose of pool) {
    if (pose.manual) continue;
    const layer = pose.paretoLayer ?? 1;
    if (layer === 1 || layer === 2 || layer === 3) counts[layer] += 1;
  }
  return counts;
}

export function selectExportPoses<T extends { id: string; paretoLayer?: number; manual?: boolean }>(
  pool: readonly T[],
  layers: Readonly<Record<ParetoLayer, boolean>>,
): T[] {
  return pool.filter((pose) => {
    if (pose.manual) return true;
    const layer = pose.paretoLayer ?? 1;
    if (layer !== 1 && layer !== 2 && layer !== 3) return false;
    return layers[layer];
  });
}

export function exportRankMarks<T extends { id: string; x: number; y: number }>(
  poses: readonly T[],
  recommendedIds: readonly string[],
  show: boolean,
): { id: string; rank: number; x: number; y: number }[] {
  if (!show) return [];
  const byId = new Map(poses.map((pose) => [pose.id, pose]));
  return recommendedIds.flatMap((id, index) => {
    const pose = byId.get(id);
    return pose ? [{ id, rank: index + 1, x: pose.x, y: pose.y }] : [];
  });
}

export function exportLegendRows(input: {
  layers: readonly { id: ExportLayerId; selected: boolean; hasData: boolean }[];
  pareto: readonly { layer: ParetoLayer; selected: boolean; count: number }[];
}): { label: string; color: string }[] {
  const labels = new Map(EXPORT_LAYERS.map((item) => [item.id, item.label]));
  const gis = input.layers.flatMap((layer) => (
    layer.selected && layer.hasData
      ? [{ label: labels.get(layer.id) ?? layer.id, color: LAYER_SWATCH[layer.id] }]
      : []
  ));
  const fronts = input.pareto.flatMap((layer) => (
    layer.selected && layer.count > 0
      ? [{ label: `第 ${layer.layer} 层`, color: PARETO_LAYER_COLORS[layer.layer - 1] }]
      : []
  ));
  return [...gis, ...fronts];
}

export function imageLooksBlank(pixels: readonly { r: number; g: number; b: number; a: number }[]): boolean {
  if (pixels.length === 0) return true;
  const empty = pixels.filter((pixel) => pixel.a < 8 || (pixel.r < 8 && pixel.g < 8 && pixel.b < 8)).length;
  return empty / pixels.length > 0.98;
}

export async function withSceneExport<T>(
  painter: ExportPainter,
  extent: ExportExtent,
  body: () => Promise<T>,
): Promise<T> {
  const camera = painter.camera();
  try {
    painter.showExport();
    if (extent === "site") painter.fitSite();
    return await body();
  } finally {
    painter.jumpTo(camera);
    painter.showWorkspace();
  }
}
