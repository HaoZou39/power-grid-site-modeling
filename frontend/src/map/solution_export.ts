import { NOT_PROVIDED } from "../solution_record.js";
import type { ParetoChoice } from "./decision_run.js";
import { STALE, widthAzimuthDeg } from "./decision_run.js";
import { localToLngLat } from "./site_frame.js";

// WGS84 from the EPSG:3857 grid is used as CGCS2000 directly: the datums differ by
// centimeters to decimeters, far below the 10 m DEM and OSM road accuracy.
const GEOGRAPHIC_CRS = "EPSG:4490 CGCS2000 (WGS84 values used without datum shift)";

type ExportedSolution = {
  solution_id: string;
  x_m: number;
  y_m: number;
  longitude_deg: number;
  latitude_deg: number;
  theta_rad: number;
  azimuth_deg: number;
  dem_soft: number | null;
  road_distance_m: number | null;
  demand_distance_m: number | null;
  road_haul_m: number | null;
  offroad_haul_m: number | null;
  haul_rise_m: number | null;
  obstacle_hard_count: number | null;
  is_feasible: boolean | null;
  derived_from?: string;
};

type CsvSolution = Omit<ExportedSolution, "x_m" | "y_m" | "theta_rad" | "derived_from" | "is_feasible"> & {
  is_feasible: "可行" | "不可行" | "未知";
};

const COLUMNS: { key: keyof CsvSolution; label: string }[] = [
  { key: "solution_id", label: "方案编号" },
  { key: "longitude_deg", label: "经度（CGCS2000，度）" },
  { key: "latitude_deg", label: "纬度（CGCS2000，度）" },
  { key: "azimuth_deg", label: "方位角（宽边，度）" },
  { key: "dem_soft", label: "地形平整度" },
  { key: "road_distance_m", label: "道路距离（米）" },
  { key: "demand_distance_m", label: "需求点距离（米）" },
  { key: "road_haul_m", label: "沿路长度（米）" },
  { key: "offroad_haul_m", label: "进站长度（米）" },
  { key: "haul_rise_m", label: "进站累计高差（米）" },
  { key: "obstacle_hard_count", label: "禁建覆盖格数" },
  { key: "is_feasible", label: "可行性" },
];

export function exportSolutionsCsv(choices: readonly ParetoChoice[]): string {
  const rows = [
    COLUMNS.map((column) => csvCell(column.label)).join(","),
    ...choices.map((choice) => {
      const solution = exportCsvSolution(choice);
      return COLUMNS.map((column) => csvCell(solution[column.key])).join(",");
    }),
  ];
  return `\uFEFF${rows.join("\r\n")}\r\n`;
}

export function exportSolutionsJson(
  sceneId: string,
  rectWidthM: number,
  rectHeightM: number,
  choices: readonly ParetoChoice[],
  exportedAt = new Date().toISOString(),
): string {
  return JSON.stringify({
    format: "power-grid-site-modeling/solutions-v1",
    exported_at: exportedAt,
    scene_id: sceneId,
    coordinate_system: "scene-local meters; x east, y south",
    geographic_crs: GEOGRAPHIC_CRS,
    building_size_m: { length: rectWidthM, width: rectHeightM },
    angle_units: { theta: "radians", azimuth_deg: "degrees clockwise from north" },
    solution_count: choices.length,
    solutions: choices.map(exportSolution),
  }, null, 2);
}

function exportCsvSolution(choice: ParetoChoice): CsvSolution {
  const solution = exportSolution(choice);
  return {
    solution_id: solution.solution_id,
    longitude_deg: solution.longitude_deg,
    latitude_deg: solution.latitude_deg,
    azimuth_deg: solution.azimuth_deg,
    dem_soft: solution.dem_soft,
    road_distance_m: solution.road_distance_m,
    demand_distance_m: solution.demand_distance_m,
    road_haul_m: solution.road_haul_m,
    offroad_haul_m: solution.offroad_haul_m,
    haul_rise_m: solution.haul_rise_m,
    obstacle_hard_count: solution.obstacle_hard_count,
    is_feasible: solution.is_feasible === true ? "可行" : solution.is_feasible === false ? "不可行" : "未知",
  };
}

function exportSolution(choice: ParetoChoice): ExportedSolution {
  const { lng, lat } = localToLngLat({ x: choice.x, y: choice.y });
  return {
    solution_id: choice.id,
    x_m: choice.x,
    y_m: choice.y,
    longitude_deg: Number(lng.toFixed(6)),
    latitude_deg: Number(lat.toFixed(6)),
    theta_rad: choice.theta,
    azimuth_deg: widthAzimuthDeg(choice.theta, choice),
    dem_soft: numericCell(choice.demSoft),
    road_distance_m: numericCell(choice.roadDistance),
    demand_distance_m: numericCell(choice.demandDistance),
    road_haul_m: numericCell(choice.roadHaul),
    offroad_haul_m: numericCell(choice.offroadHaul),
    haul_rise_m: numericCell(choice.haulRise),
    obstacle_hard_count: numericCell(choice.obstacleHardCount),
    is_feasible: feasibilityCell(choice.feasible),
    ...(choice.derivedFrom ? { derived_from: choice.derivedFrom } : {}),
  };
}

function numericCell(value: string): number | null {
  if (!value.trim() || value === NOT_PROVIDED || value === "重算中" || value === STALE) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function feasibilityCell(value: string): boolean | null {
  if (value === "可行") return true;
  if (value === "不可行") return false;
  return null;
}

function csvCell(value: ExportedSolution[keyof ExportedSolution] | undefined): string {
  const text = value == null ? "" : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}
