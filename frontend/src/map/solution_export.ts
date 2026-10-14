import { NOT_PROVIDED } from "../solution_record.js";
import type { ParetoChoice } from "./decision_run.js";
import { widthAzimuthDeg } from "./decision_run.js";

type ExportedSolution = {
  solution_id: string;
  x_m: number;
  y_m: number;
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

const COLUMNS: (keyof ExportedSolution)[] = [
  "solution_id",
  "x_m",
  "y_m",
  "theta_rad",
  "azimuth_deg",
  "dem_soft",
  "road_distance_m",
  "demand_distance_m",
  "road_haul_m",
  "offroad_haul_m",
  "haul_rise_m",
  "obstacle_hard_count",
  "is_feasible",
  "derived_from",
];

export function exportSolutionsCsv(choices: readonly ParetoChoice[]): string {
  const rows = [
    COLUMNS.join(","),
    ...choices.map((choice) => {
      const solution = exportSolution(choice);
      return COLUMNS.map((column) => csvCell(solution[column])).join(",");
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
    building_size_m: { length: rectWidthM, width: rectHeightM },
    angle_units: { theta: "radians", azimuth_deg: "degrees clockwise from north" },
    solution_count: choices.length,
    solutions: choices.map(exportSolution),
  }, null, 2);
}

function exportSolution(choice: ParetoChoice): ExportedSolution {
  return {
    solution_id: choice.id,
    x_m: choice.x,
    y_m: choice.y,
    theta_rad: choice.theta,
    azimuth_deg: widthAzimuthDeg(choice.theta),
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
  if (!value.trim() || value === NOT_PROVIDED || value === "重算中") return null;
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
