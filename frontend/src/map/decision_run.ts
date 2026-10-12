import { failurePresentation, submittedExperimentId } from "../run_status.js";
import { adaptSolutions, selectResultArtifacts } from "../solution_record.js";
import type { ResultArtifact, SolutionRecord } from "../solution_record.js";
import { clampSitePoint, type SiteEdit } from "./site_edit.js";
import { localToLngLat } from "./site_frame.js";
import type { LocalPoint } from "./site_frame.js";

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
  feasible: string;
};

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

/** One NSGA-II decision run. Six objectives are compared directly, without weights. */
export class Nsga2DecisionRun {
  static readonly pluginId = "site.nsga2";

  constructor(private readonly catalog: ExperimentCatalog) {}

  createRequest(edit: SiteEdit, now = new Date()): DecisionJobRequest {
    return {
      plugin_id: Nsga2DecisionRun.pluginId,
      config: {
        experiment_name: `site-${stamp(now)}`,
        ...edit.searchConfig(),
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

  moveSelected(dx: number, dy: number): ParetoSelection {
    const choice = this.selected;
    if (!choice) return this;
    const choices = this.choices.slice();
    choices[this.index] = moveChoice(choice, dx, dy);
    return new ParetoSelection(choices, this.index);
  }
}

export type ChoiceReport = {
  offroadHaulM: number | null;
  haulRiseM: number | null;
  accessSlopeDeg: number;
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
): { decisions: StatusRow[]; objectives: StatusRow[] } {
  const place = placeDescription(choice);
  const status = choiceStatus(choice, report);
  const objectives = status.filter((row) => !["位置（m）", "朝向", "可行性"].includes(row.label));
  objectives.push({ label: "道路距离（m）", value: choice.roadDistance });
  if (hasOrigin) {
    const road = report?.roadHaulM != null ? formatObjective(String(report.roadHaulM)) : choice.roadHaul;
    objectives.splice(objectives.length - 1, 0, { label: "沿路长度（m）", value: road });
  }
  return {
    decisions: [
      { label: "经度", value: place.lng },
      { label: "纬度", value: place.lat },
      { label: "方位角（宽边）", value: `${widthAzimuthDeg(choice.theta).toFixed(1)}°` },
      { label: "可行性", value: choice.feasible },
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
): CompareChart {
  const columns = COMPARE_AXES.flatMap((axis) => {
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

/** One status card for the selected footprint. A report replaces the CSV haul numbers. */
export function choiceStatus(choice: ParetoChoice, report: ChoiceReport | null): StatusRow[] {
  const offroad = report?.offroadHaulM != null ? formatObjective(String(report.offroadHaulM)) : choice.offroadHaul;
  const rise = report?.haulRiseM != null ? formatObjective(String(report.haulRiseM)) : choice.haulRise;
  const rows: StatusRow[] = [
    { label: "位置（m）", value: `${choice.x.toFixed(0)}, ${choice.y.toFixed(0)}` },
    { label: "朝向", value: choice.theta.toFixed(2) },
    { label: "可行性", value: choice.feasible },
    { label: "地形平整度", value: choice.demSoft },
    { label: "需求点距离（m）", value: choice.demandDistance },
    { label: "进场（m）", value: offroad },
    { label: "进场高差（m）", value: rise },
  ];
  if (report) {
    const slope = formatObjective(String(report.accessSlopeDeg));
    rows.push({ label: "进场坡度（°）", value: report.accessWarning ? `${slope} · 偏陡` : slope });
  }
  return rows;
}

/** Move one scheme. Orientation stays. The center stays inside the site frame. */
export function moveChoice(choice: ParetoChoice, dx: number, dy: number): ParetoChoice {
  const moved = clampSitePoint(choice.x + dx, choice.y + dy);
  return { ...choice, x: moved.x, y: moved.y };
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
    return [{
      id: item.id,
      x,
      y,
      theta,
      demSoft: formatObjective(item.demSoft),
      roadDistance: formatObjective(item.roadDistance),
      demandDistance: formatObjective(item.demandDistance),
      roadHaul: formatObjective(item.roadHaul),
      offroadHaul: formatObjective(item.offroadHaul),
      haulRise: formatObjective(item.haulRise),
      feasible: "可行",
    }];
  });
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
