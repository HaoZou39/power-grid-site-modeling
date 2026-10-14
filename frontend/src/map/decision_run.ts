import { failurePresentation, submittedExperimentId } from "../run_status.js";
import { NOT_PROVIDED, adaptSolutions, selectResultArtifacts } from "../solution_record.js";
import type { ResultArtifact, SolutionRecord } from "../solution_record.js";
import { clampSitePoint, type SiteEdit } from "./site_edit.js";
import { clampFootprintCenter, footprintInsideSite, localToLngLat } from "./site_frame.js";
import type { LocalPoint } from "./site_frame.js";

export type SitePose = { x: number; y: number; theta: number };

export type ChoiceBaseline = {
  demSoft: string;
  roadDistance: string;
  demandDistance: string;
  roadHaul: string;
  offroadHaul: string;
  haulRise: string;
  obstacleHardCount: string;
  feasible: string;
};

export type { FieldPolicy, MountainPolicy } from "./site_edit.js";

export type ParetoChoice = {
  id: string;
  x: number;
  y: number;
  theta: number;
  demSoft: string;
  roadDistance: string;
  demandDistance: string;
  roadHaul: string;
  offroadHaul: string;
  haulRise: string;
  obstacleHardCount: string;
  feasible: string;
  original: SitePose;
  baseline: ChoiceBaseline;
  /** Set on schemes found by a local re-search around another scheme. */
  derivedFrom?: string;
};

/** One `solutions.csv` row from `POST /scenes/{id}/pose-objectives`. */
export type PoseObjectives = {
  dem_soft: number;
  road_distance: number;
  demand_distance: number;
  road_haul_m: number | "";
  offroad_haul_m: number;
  haul_rise_m: number;
  obstacle_hard_count: number;
  is_feasible: boolean;
};

export const UNMEASURED = "重算中";

export type DecisionJobRequest = {
  plugin_id: string;
  config: {
    experiment_name: string;
    rect_w_m: number;
    rect_h_m: number;
    scene_name: string;
    field_policy: "blocked" | "allowed" | "costly";
    mountain_policy: "blocked" | "allowed";
    field_cost: number;
    exclusion_zones: { points: [number, number][] }[];
    feasible_zones: { points: [number, number][] }[];
    include_demand: boolean;
    origin_x?: number;
    origin_y?: number;
  };
};

export type ScenePreparationRequest = {
  plugin_id: string;
  config: { scene_name: string };
};

export type ExperimentCatalog = {
  getExperiments(): Promise<{ id: string; artifacts: ResultArtifact[] }[]>;
  fetchArtifactText(url: string): Promise<string>;
};

type FollowedJob = {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  message: string;
  result: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
};

/** Rectangle size submitted with one run. The drawn footprint keeps this size after the inputs change. */
export class BuildingSize {
  constructor(readonly widthM: number, readonly heightM: number) {}

  static parse(widthText: string, heightText: string): BuildingSize {
    const widthM = Number(widthText);
    const heightM = Number(heightText);
    if (!Number.isFinite(widthM) || widthM <= 0 || !Number.isFinite(heightM) || heightM <= 0) {
      throw new Error("变电站长度和宽度必须是大于 0 的米数。");
    }
    return new BuildingSize(widthM, heightM);
  }
}

/** One guided-search decision run. The compared objectives are minimized directly, without weights. */
export class GuidedDecisionRun {
  static readonly pluginId = "site.guided_search";

  constructor(private readonly catalog: ExperimentCatalog) {}

  createRequest(edit: SiteEdit, now = new Date()): DecisionJobRequest {
    return {
      plugin_id: GuidedDecisionRun.pluginId,
      config: {
        experiment_name: `site-${stamp(now)}`,
        ...edit.searchConfig(),
      },
    };
  }

  /** The same search limited to one square around `center`. Drawn feasible zones are replaced, exclusions stay. */
  createRefineRequest(edit: SiteEdit, center: LocalPoint, halfWidthM: number, now = new Date()): DecisionJobRequest {
    return {
      plugin_id: GuidedDecisionRun.pluginId,
      config: {
        ...edit.searchConfig(),
        experiment_name: `refine-${stamp(now)}`,
        feasible_zones: [{ points: refineSquare(center, halfWidthM) }],
      },
    };
  }

  async loadPareto(experimentId: string): Promise<ParetoChoice[]> {
    const experiments = await this.catalog.getExperiments();
    const experiment = experiments.find((item) => item.id === experimentId);
    if (!experiment) {
      throw new Error(`实验 ${experimentId} 已完成，但目录里还没有可读取的产物。`);
    }
    const artifacts = selectResultArtifacts(experiment.artifacts);
    if (!artifacts.solutionsUrl) throw new Error("这次实验没有方案表。");
    const paretoCsv = artifacts.paretoSolutionsUrl
      ? await this.catalog.fetchArtifactText(artifacts.paretoSolutionsUrl)
      : null;
    const solutions = adaptSolutions(await this.catalog.fetchArtifactText(artifacts.solutionsUrl), paretoCsv);
    const choices = feasibleParetoChoices(solutions);
    if (choices.length === 0) throw new Error("这次搜索没有画出可行的帕累托方案。");
    return choices;
  }
}

/** Remembers which finished job already loaded its Pareto table. */
export class JobFollowUp {
  private claimed = "";

  static isActive(status: FollowedJob["status"]): boolean {
    return status === "queued" || status === "running";
  }

  failureNotice(record: FollowedJob): string | null {
    if (record.status !== "failed") return null;
    return failurePresentation({ message: record.message, error: record.error }).summary;
  }

  opened(jobId: string, status: FollowedJob["status"]): boolean {
    if (status !== "succeeded" || this.claimed === jobId) return false;
    this.claimed = jobId;
    return true;
  }

  claimExperiment(record: FollowedJob): string | null {
    if (!this.opened(record.job_id, record.status)) return null;
    const experimentId = submittedExperimentId(record.result);
    if (!experimentId) throw new Error("任务已完成，但没有返回实验目录。");
    return experimentId;
  }
}

/** The Pareto row currently shown on the map. */
export class ParetoSelection {
  constructor(readonly choices: readonly ParetoChoice[], readonly index: number) {}

  get selected(): ParetoChoice | null {
    return this.choices[this.index] ?? null;
  }

  step(delta: number): ParetoSelection {
    if (this.choices.length === 0) return this;
    const span = this.choices.length;
    const index = ((this.index + delta) % span + span) % span;
    return new ParetoSelection(this.choices, index);
  }

  select(id: string): ParetoSelection {
    const index = this.choices.findIndex((item) => item.id === id);
    if (index < 0) return this;
    return new ParetoSelection(this.choices, index);
  }

  moveSelected(dx: number, dy: number, size: BuildingSize): ParetoSelection {
    const choice = this.selected;
    if (!choice) return this;
    const choices = this.choices.slice();
    choices[this.index] = moveChoice(choice, dx, dy, size);
    return new ParetoSelection(choices, this.index);
  }

  rotateSelected(theta: number, size: BuildingSize): ParetoSelection {
    const choice = this.selected;
    if (!choice) return this;
    const choices = this.choices.slice();
    choices[this.index] = rotateChoice(choice, theta, size);
    return new ParetoSelection(choices, this.index);
  }

  restoreSelected(): ParetoSelection {
    const choice = this.selected;
    if (!choice) return this;
    const choices = this.choices.slice();
    choices[this.index] = restoreChoice(choice);
    return new ParetoSelection(choices, this.index);
  }
}

export type ChoiceReport = {
  offroadHaulM: number | null;
  haulRiseM: number | null;
  accessSlopeDeg: number | null;
  accessWarning: boolean;
  roadHaulM?: number | null;
};

export type StatusRow = { label: string; value: string };

/** Local meters plus longitude and latitude. Any later click uses this one conversion. */
export function placeDescription(point: LocalPoint): { local: string; lng: string; lat: string } {
  const lngLat = localToLngLat(point);
  return {
    local: `${point.x.toFixed(0)}, ${point.y.toFixed(0)}`,
    lng: lngLat.lng.toFixed(6),
    lat: lngLat.lat.toFixed(6),
  };
}

/** Compass bearing of the rectangle's width axis. North is 0°, clockwise, in degrees. */
export function widthAzimuthDeg(theta: number): number {
  const degrees = (theta * 180) / Math.PI;
  return ((degrees + 90) % 360 + 360) % 360;
}

export function schemeCard(
  choice: ParetoChoice,
  report: ChoiceReport | null,
  hasOrigin: boolean,
  includeDemand = false,
): { decisions: StatusRow[]; objectives: StatusRow[] } {
  const place = placeDescription(choice);
  const status = choiceStatus(choice, report);
  const decisionLabels = ["位置（m）", "旋转角度（°）", "可行性"];
  const objectives = status.filter((row) => !decisionLabels.includes(row.label));
  if (!includeDemand) {
    const demand = objectives.findIndex((row) => row.label === "需求点距离（m）");
    if (demand >= 0) objectives.splice(demand, 1);
  }
  if (hasOrigin) {
    const road = report?.roadHaulM != null ? formatObjective(String(report.roadHaulM)) : choice.roadHaul;
    const roadIndex = objectives.findIndex((row) => row.label === "道路距离（m）");
    objectives.splice(roadIndex < 0 ? objectives.length : roadIndex, 0, {
      label: "沿路长度（m）",
      value: changedMetric(choice.baseline.roadHaul, road, isChoiceEdited(choice)),
    });
  }
  const angle = status.find((row) => row.label === "旋转角度（°）")?.value ?? formatObjective(String(radiansToDegrees(choice.theta)));
  const feasibility = status.find((row) => row.label === "可行性")?.value ?? choice.feasible;
  return {
    decisions: [
      { label: "经度", value: place.lng },
      { label: "纬度", value: place.lat },
      { label: "旋转角度", value: angle },
      { label: "方位角（宽边）", value: `${widthAzimuthDeg(choice.theta).toFixed(1)}°` },
      { label: "可行性", value: feasibility },
    ],
    objectives,
  };
}

const COMPARE_AXES: { key: keyof ParetoChoice; label: string }[] = [
  { key: "demSoft", label: "地形" },
  { key: "demandDistance", label: "需求" },
  { key: "offroadHaul", label: "进场" },
  { key: "haulRise", label: "高差" },
  { key: "roadHaul", label: "沿路" },
  { key: "roadDistance", label: "道路" },
];

export type CompareChart = {
  labels: string[];
  series: { id: string; name: string; values: (number | null)[] }[];
};

/**
 * Each axis is stretched across `scale`, normally every Pareto scheme from this run.
 * 0 is the best value on that axis. Adding a line does not move the lines already drawn.
 */
export function compareChart(
  items: readonly { id: string; name: string; choice: ParetoChoice }[],
  scale: readonly ParetoChoice[] = items.map((item) => item.choice),
  includeDemand = false,
): CompareChart {
  const axes = includeDemand ? COMPARE_AXES : COMPARE_AXES.filter((axis) => axis.key !== "demandDistance");
  const columns = axes.flatMap((axis) => {
    const plotted = items.map((item) => finiteObjective(item.choice[axis.key]));
    if (!plotted.some((value) => value !== null)) return [];
    const reference = scale.map((choice) => finiteObjective(choice[axis.key])).filter((value): value is number => value !== null);
    const basis = reference.length > 0 ? reference : plotted.filter((value): value is number => value !== null);
    return [{ label: axis.label, plotted, low: Math.min(...basis), high: Math.max(...basis) }];
  });
  return {
    labels: columns.map((column) => column.label),
    series: items.map((item, itemIndex) => ({
      id: item.id,
      name: item.name,
      values: columns.map((column) => normalizeLow(column.plotted[itemIndex], column.low, column.high)),
    })),
  };
}

function finiteObjective(value: ParetoChoice[keyof ParetoChoice]): number | null {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function normalizeLow(value: number | null, low: number, high: number): number | null {
  if (value === null) return null;
  if (high === low) return 0;
  return (value - low) / (high - low);
}

/** One status card for the selected footprint. Adjusted values never masquerade as original CSV metrics. */
export function choiceStatus(choice: ParetoChoice, report: ChoiceReport | null): StatusRow[] {
  const edited = isChoiceEdited(choice);
  const originalPosition = `${choice.original.x.toFixed(0)}, ${choice.original.y.toFixed(0)}`;
  const currentPosition = `${choice.x.toFixed(0)}, ${choice.y.toFixed(0)}`;
  const originalAngle = formatObjective(String(radiansToDegrees(choice.original.theta)));
  const currentAngle = formatObjective(String(radiansToDegrees(choice.theta)));
  const offroad = report?.offroadHaulM != null ? formatObjective(String(report.offroadHaulM)) : choice.offroadHaul;
  const rise = report?.haulRiseM != null ? formatObjective(String(report.haulRiseM)) : choice.haulRise;
  const rows: StatusRow[] = [
    { label: "位置（m）", value: changedMetric(originalPosition, currentPosition, edited) },
    { label: "旋转角度（°）", value: changedMetric(originalAngle, currentAngle, edited) },
    { label: "可行性", value: changedMetric(choice.baseline.feasible, choice.feasible, edited) },
    { label: "地形平整度", value: changedMetric(choice.baseline.demSoft, choice.demSoft, edited) },
    { label: "需求点距离（m）", value: changedMetric(choice.baseline.demandDistance, choice.demandDistance, edited) },
    { label: "进场（m）", value: changedMetric(choice.baseline.offroadHaul, offroad, edited) },
    { label: "进场高差（m）", value: changedMetric(choice.baseline.haulRise, rise, edited) },
    { label: "禁建覆盖格数", value: changedMetric(choice.baseline.obstacleHardCount, choice.obstacleHardCount, edited) },
    { label: "道路距离（m）", value: changedMetric(choice.baseline.roadDistance, choice.roadDistance, edited) },
  ];
  if (report?.accessSlopeDeg != null) {
    const slope = formatObjective(String(report.accessSlopeDeg));
    rows.push({ label: "进场坡度（°）", value: report.accessWarning ? `${slope} · 偏陡` : slope });
  }
  return rows;
}

function changedMetric(original: string, current: string, edited: boolean): string {
  return edited ? `${original} → ${current}` : current;
}

export function isChoiceEdited(choice: ParetoChoice): boolean {
  return Math.abs(choice.x - choice.original.x) > 1e-9
    || Math.abs(choice.y - choice.original.y) > 1e-9
    || Math.abs(choice.theta - choice.original.theta) > 1e-9;
}

/** Move one scheme. Orientation and size stay unchanged; all four corners remain inside. */
export function moveChoice(choice: ParetoChoice, dx: number, dy: number, size: BuildingSize): ParetoChoice {
  const center = clampFootprintCenter(
    choice.x + dx,
    choice.y + dy,
    choice.theta,
    size.widthM,
    size.heightM,
  );
  return {
    ...choice,
    ...center,
  };
}

/** Rotate one scheme only when its actual rotated footprint remains inside. */
export function rotateChoice(choice: ParetoChoice, theta: number, size: BuildingSize): ParetoChoice {
  if (!Number.isFinite(theta)) throw new Error("旋转角度必须是有限数字。");
  if (!footprintInsideSite(choice.x, choice.y, theta, size.widthM, size.heightM)) {
    throw new Error("这个角度会让建筑超出规划区域，请先向区域内部移动。");
  }
  return { ...choice, theta };
}

export function restoreChoice(choice: ParetoChoice): ParetoChoice {
  return { ...choice, ...choice.original, ...choice.baseline };
}

/** Normalize user-facing degrees before converting to the internal radians pose. */
export function angleDegreesToRadians(degrees: number): number {
  if (!Number.isFinite(degrees)) throw new Error("旋转角度必须是有限数字。");
  const normalized = ((degrees + 180) % 360 + 360) % 360 - 180;
  return normalized * Math.PI / 180;
}

export function radiansToDegrees(radians: number): number {
  if (!Number.isFinite(radians)) throw new Error("候选方案角度必须是有限数字。");
  return radians * 180 / Math.PI;
}

/** One decimal for a decision maker. Full precision stays in the CSV. */
export function formatObjective(value: string, digits = 1): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return number.toFixed(digits).replace(/\.0$/, "");
}

export function feasibleParetoChoices(solutions: readonly SolutionRecord[]): ParetoChoice[] {
  return solutions.flatMap((item) => {
    const x = Number(item.x);
    const y = Number(item.y);
    const theta = Number(item.theta);
    if (item.isPareto !== true || item.isFeasible !== true) return [];
    if (![x, y, theta].every((value) => Number.isFinite(value))) return [];
    const baseline: ChoiceBaseline = {
      demSoft: formatObjective(item.demSoft),
      roadDistance: formatObjective(item.roadDistance),
      demandDistance: formatObjective(item.demandDistance),
      roadHaul: formatObjective(item.roadHaul),
      offroadHaul: formatObjective(item.offroadHaul),
      haulRise: formatObjective(item.haulRise),
      obstacleHardCount: formatObjective(item.obstacleHardCount),
      feasible: "可行",
    };
    return [{
      id: item.id,
      x,
      y,
      theta,
      ...baseline,
      original: { x, y, theta },
      baseline,
    }];
  });
}

/** Objectives the guided search compares, in the order of markdown/GUIDED_SEARCH.md. road_distance is not compared. */
export function comparedFields(hasOrigin: boolean, includeDemand: boolean): (keyof ParetoChoice)[] {
  return [
    "demSoft",
    ...(includeDemand ? ["demandDistance" as const] : []),
    "offroadHaul",
    "haulRise",
    ...(hasOrigin ? ["roadHaul" as const] : []),
  ];
}

/** Square ring around `center`, clipped to the site frame. Local meters, y grows south. */
export function refineSquare(center: LocalPoint, halfWidthM: number): [number, number][] {
  const left = clampSitePoint(center.x - halfWidthM, center.y - halfWidthM);
  const right = clampSitePoint(center.x + halfWidthM, center.y + halfWidthM);
  return [[left.x, left.y], [right.x, left.y], [right.x, right.y], [left.x, right.y]];
}

/** Display fields go blank until the recomputed row arrives, so nobody reads the old place's numbers. */
export function unmeasured(choice: ParetoChoice): ParetoChoice {
  return {
    ...choice,
    demSoft: UNMEASURED,
    roadDistance: UNMEASURED,
    demandDistance: UNMEASURED,
    roadHaul: UNMEASURED,
    offroadHaul: UNMEASURED,
    haulRise: UNMEASURED,
    obstacleHardCount: UNMEASURED,
    feasible: UNMEASURED,
  };
}

export function measuredChoice(choice: ParetoChoice, row: PoseObjectives): ParetoChoice {
  const cell = (value: number | "") => value === "" ? NOT_PROVIDED : formatObjective(String(value));
  return {
    ...choice,
    demSoft: cell(row.dem_soft),
    roadDistance: cell(row.road_distance),
    demandDistance: cell(row.demand_distance),
    roadHaul: cell(row.road_haul_m),
    offroadHaul: cell(row.offroad_haul_m),
    haulRise: cell(row.haul_rise_m),
    obstacleHardCount: cell(row.obstacle_hard_count),
    feasible: row.is_feasible ? "可行" : "不可行",
  };
}

/**
 * Pick what a local re-search adds to the map, at most one per compared objective. For objective k, take the
 * scheme that beats `original` on k and gets worse on the others by the least, measured as the largest rise
 * divided by that objective's span over `local` and `original`; ties go to the smaller k. `improved` means at
 * least one pick is no worse than `original` anywhere. An unmeasured original falls back to the best on each k.
 */
export function refinedChoices(
  original: ParetoChoice,
  local: readonly ParetoChoice[],
  fields: readonly (keyof ParetoChoice)[],
): { choices: ParetoChoice[]; improved: boolean } {
  const rows = local.map((choice) => fields.map((field) => Number(choice[field])));
  const own = fields.map((field) => Number(original[field]));
  const measured = own.every((value) => Number.isFinite(value));
  const span = fields.map((_, j) => {
    const column = [...rows.map((row) => row[j]), ...(measured ? [own[j]] : [])];
    return Math.max(...column) - Math.min(...column) || 1;
  });
  const loss = (row: number[], k: number) => measured
    ? Math.max(0, ...row.map((value, j) => j === k ? 0 : (value - own[j]) / span[j]))
    : 0;
  const picks: number[] = [];
  fields.forEach((_, k) => {
    let best = -1;
    rows.forEach((row, i) => {
      if (measured && !(row[k] < own[k])) return;
      if (best < 0 || loss(row, k) < loss(rows[best], k) || (loss(row, k) === loss(rows[best], k) && row[k] < rows[best][k])) best = i;
    });
    if (best >= 0 && !picks.includes(best)) picks.push(best);
  });
  return {
    choices: picks.map((i) => local[i]),
    improved: measured && picks.some((i) => rows[i].every((value, j) => value <= own[j])),
  };
}

/** Rectangle size stored with a completed run. Missing or invalid sizes stay unset. */
export function buildingSizeFromResolvedConfig(value: unknown): BuildingSize | null {
  if (!value || typeof value !== "object") return null;
  const modeling = (value as { modeling?: unknown }).modeling;
  if (!modeling || typeof modeling !== "object") return null;
  const widthM = Number((modeling as { rect_w_m?: unknown }).rect_w_m);
  const heightM = Number((modeling as { rect_h_m?: unknown }).rect_h_m);
  if (!Number.isFinite(widthM) || widthM <= 0 || !Number.isFinite(heightM) || heightM <= 0) return null;
  return new BuildingSize(widthM, heightM);
}

function stamp(now: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}
