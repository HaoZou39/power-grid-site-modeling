/**
 * Read solution rows from experiment CSV artifacts.
 * Feasibility and Pareto membership are taken from those files.
 * This module does not compute objectives, constraints, or the Pareto front.
 */

export const NOT_PROVIDED = "未提供";

const MAP_ORDER = [
  "pareto_footprints_map.png",
  "all_candidates_points_map.png",
  "all_candidates_footprints_map.png",
  "pareto_points_map.png",
] as const;

const MAP_LABEL: Record<string, string> = {
  "pareto_footprints_map.png": "Pareto 足迹图",
  "all_candidates_points_map.png": "候选点图",
  "all_candidates_footprints_map.png": "全部可行足迹图",
  "pareto_points_map.png": "Pareto 点图",
};

export type SolutionRecord = {
  key: string;
  id: string;
  /** Local x in meters, original CSV text. */
  x: string;
  /** Local y in meters, original CSV text. */
  y: string;
  /** Heading in radians, original CSV text. */
  theta: string;
  demSoft: string;
  /** Road distance in meters, original CSV text. */
  roadDistance: string;
  /** Demand distance in meters, original CSV text. */
  demandDistance: string;
  roadHaul: string;
  offroadHaul: string;
  haulRise: string;
  obstacleHardCount: string;
  isFeasible: boolean | null;
  /** Null when pareto_solutions.csv was not available and the column was absent. */
  isPareto: boolean | null;
  sort: {
    feasible: number | null;
    pareto: number | null;
    demSoft: number | null;
    roadDistance: number | null;
    demandDistance: number | null;
  };
};

export type ResultArtifact = { name: string; kind: string; url: string };

export type ResultArtifactSelection = {
  solutionsUrl: string | null;
  paretoSolutionsUrl: string | null;
  maps: { name: string; label: string; url: string }[];
  paretoHtml: { name: string; url: string } | null;
  downloads: ResultArtifact[];
};

export type SortKey = "feasible" | "pareto" | "demSoft" | "roadDistance" | "demandDistance";

export type ComparisonPoint = {
  key: string;
  id: string;
  /** Road distance in meters, taken from the CSV cell. */
  roadDistance: number;
  /** Demand distance in meters, taken from the CSV cell. */
  demandDistance: number;
  isFeasible: boolean | null;
  isPareto: boolean | null;
};

/** Points for a display scatter. The axis extent is the loaded rows, not modeling normalization. */
export function comparisonPoints(records: readonly SolutionRecord[]): ComparisonPoint[] {
  const points: ComparisonPoint[] = [];
  for (const record of records) {
    if (record.sort.roadDistance === null || record.sort.demandDistance === null) continue;
    points.push({
      key: record.key,
      id: record.id,
      roadDistance: record.sort.roadDistance,
      demandDistance: record.sort.demandDistance,
      isFeasible: record.isFeasible,
      isPareto: record.isPareto,
    });
  }
  return points;
}

export function experimentListStats(summary: Record<string, unknown>): {
  finishedAt: string;
  total: string;
  feasible: string;
  pareto: string;
} {
  return {
    finishedAt: textValue(summary.completed_at ?? summary.finished_at),
    total: numberValue(summary.n_solutions),
    feasible: numberValue(summary.n_feasible),
    pareto: numberValue(summary.n_pareto),
  };
}

export function resultSummary(summary: Record<string, unknown>, solutions: SolutionRecord[] | null): {
  total: string;
  feasible: string;
  pareto: string;
  hasFeasible: string;
} {
  const total = numberValue(summary.n_solutions) !== NOT_PROVIDED
    ? numberValue(summary.n_solutions)
    : solutions ? String(solutions.length) : NOT_PROVIDED;
  const feasible = numberValue(summary.n_feasible) !== NOT_PROVIDED
    ? numberValue(summary.n_feasible)
    : countFlag(solutions, (item) => item.isFeasible);
  const pareto = numberValue(summary.n_pareto) !== NOT_PROVIDED
    ? numberValue(summary.n_pareto)
    : countFlag(solutions, (item) => item.isPareto);
  return { total, feasible, pareto, hasFeasible: hasFeasibleText(summary, solutions) };
}

export function selectResultArtifacts(artifacts: readonly ResultArtifact[]): ResultArtifactSelection {
  const images = artifacts.filter((item) => item.kind === "image" && item.url.trim());
  const known = MAP_ORDER
    .map((name) => images.find((item) => item.name === name))
    .filter((item): item is ResultArtifact => item !== undefined)
    .map((item) => ({ name: item.name, label: MAP_LABEL[item.name] ?? item.name, url: item.url }));
  const extra = images
    .filter((item) => !MAP_ORDER.includes(item.name as (typeof MAP_ORDER)[number]))
    .map((item) => ({ name: item.name, label: item.name, url: item.url }));
  const html = artifacts.find((item) => item.kind === "html" && item.name === "pareto_3d_interactive.html" && item.url.trim())
    ?? artifacts.find((item) => item.kind === "html" && item.name.toLowerCase().includes("pareto") && item.url.trim());
  return {
    solutionsUrl: artifactUrl(artifacts, "solutions.csv", "table"),
    paretoSolutionsUrl: artifactUrl(artifacts, "pareto_solutions.csv", "table"),
    maps: [...known, ...extra],
    paretoHtml: html ? { name: html.name, url: html.url } : null,
    downloads: artifacts.filter((item) => (item.kind === "json" || item.kind === "table") && item.url.trim()),
  };
}

/** Pareto ids come from pareto_solutions.csv. A missing file leaves isPareto null. */
export function adaptSolutions(solutionsCsv: string, paretoCsv: string | null): SolutionRecord[] {
  const table = parseCsv(solutionsCsv);
  if (table.length === 0) return [];
  const header = table[0].map((cell) => cell.trim());
  const paretoIds = paretoCsv === null ? null : paretoIdSet(paretoCsv);
  return table.slice(1).map((cells, index) => adaptRow(header, cells, index, paretoIds));
}

/** Keep at most three solutions for side-by-side comparison. A selected key is removed. */
export function toggleCompared(selected: readonly string[], key: string, limit = 3): { keys: string[]; rejected: boolean } {
  if (selected.includes(key)) return { keys: selected.filter((item) => item !== key), rejected: false };
  if (selected.length >= limit) return { keys: [...selected], rejected: true };
  return { keys: [...selected, key], rejected: false };
}

export function sortSolutions(records: readonly SolutionRecord[], key: SortKey, direction: "asc" | "desc"): SolutionRecord[] {
  const sign = direction === "asc" ? 1 : -1;
  return [...records].sort((left, right) => {
    const a = left.sort[key];
    const b = right.sort[key];
    if (a === null && b === null) return left.key.localeCompare(right.key);
    if (a === null) return 1;
    if (b === null) return -1;
    if (a === b) return left.key.localeCompare(right.key);
    return a < b ? -sign : sign;
  });
}

export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  const source = text.replace(/^\uFEFF/, "");
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (quoted) {
      if (char === '"') {
        if (source[index + 1] === '"') {
          cell += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += char;
      }
      continue;
    }
    if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (char !== "\r") {
      cell += char;
    }
  }
  if (cell.length > 0 || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((item) => item.some((value) => value.trim() !== ""));
}

function adaptRow(header: string[], cells: string[], index: number, paretoIds: Set<string> | null): SolutionRecord {
  const value = (name: string) => {
    const column = header.indexOf(name);
    if (column < 0) return null;
    return cells[column] ?? "";
  };
  const idCell = value("run_id") ?? value("solution_id");
  const id = idCell !== null && idCell.trim() ? idCell.trim() : NOT_PROVIDED;
  const feasibleCell = value("is_feasible");
  const paretoCell = value("is_pareto");
  const isFeasible = feasibleCell === null ? null : parseFlag(feasibleCell);
  const isPareto = paretoCell !== null
    ? parseFlag(paretoCell)
    : paretoIds === null || id === NOT_PROVIDED
      ? null
      : paretoIds.has(id);
  return {
    key: `${index}:${id}`,
    id,
    x: displayCell(value("x")),
    y: displayCell(value("y")),
    theta: displayCell(value("theta")),
    demSoft: displayCell(value("dem_soft")),
    roadDistance: displayCell(value("road_distance")),
    demandDistance: displayCell(value("demand_distance")),
    roadHaul: displayCell(value("road_haul_m")),
    offroadHaul: displayCell(value("offroad_haul_m")),
    haulRise: displayCell(value("haul_rise_m")),
    obstacleHardCount: displayCell(value("obstacle_hard_count")),
    isFeasible,
    isPareto,
    sort: {
      feasible: flagSort(isFeasible),
      pareto: flagSort(isPareto),
      demSoft: finiteNumber(value("dem_soft")),
      roadDistance: finiteNumber(value("road_distance")),
      demandDistance: finiteNumber(value("demand_distance")),
    },
  };
}

function paretoIdSet(csv: string): Set<string> {
  const table = parseCsv(csv);
  if (table.length === 0) return new Set();
  const header = table[0].map((cell) => cell.trim());
  const column = header.indexOf("run_id") >= 0 ? header.indexOf("run_id") : header.indexOf("solution_id");
  if (column < 0) return new Set();
  return new Set(table.slice(1).map((cells) => (cells[column] ?? "").trim()).filter((id) => id.length > 0));
}

function artifactUrl(artifacts: readonly ResultArtifact[], name: string, kind: string): string | null {
  const match = artifacts.find((item) => item.name === name && item.kind === kind && item.url.trim());
  return match ? match.url : null;
}

function displayCell(value: string | null): string {
  if (value === null || value.trim() === "") return NOT_PROVIDED;
  return value.trim();
}

function parseFlag(value: string): boolean | null {
  const text = value.trim().toLowerCase();
  if (text === "true" || text === "1") return true;
  if (text === "false" || text === "0") return false;
  return null;
}

function flagSort(value: boolean | null): number | null {
  if (value === null) return null;
  return value ? 1 : 0;
}

function finiteNumber(value: string | null): number | null {
  if (value === null || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function textValue(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : NOT_PROVIDED;
}

function numberValue(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : NOT_PROVIDED;
}

function countFlag(solutions: SolutionRecord[] | null, read: (item: SolutionRecord) => boolean | null): string {
  if (!solutions || solutions.length === 0) return NOT_PROVIDED;
  if (solutions.some((item) => read(item) === null)) return NOT_PROVIDED;
  return String(solutions.filter((item) => read(item) === true).length);
}

function hasFeasibleText(summary: Record<string, unknown>, solutions: SolutionRecord[] | null): string {
  if (typeof summary.no_feasible_solution === "boolean") return summary.no_feasible_solution ? "否" : "是";
  if (typeof summary.n_feasible === "number" && Number.isFinite(summary.n_feasible)) return summary.n_feasible > 0 ? "是" : "否";
  if (!solutions || solutions.some((item) => item.isFeasible === null)) return NOT_PROVIDED;
  return solutions.some((item) => item.isFeasible) ? "是" : "否";
}
