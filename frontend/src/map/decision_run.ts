import { failurePresentation, submittedExperimentId } from "../run_status.js";
import { adaptSolutions, selectResultArtifacts } from "../solution_record.js";
import type { ResultArtifact, SolutionRecord } from "../solution_record.js";
import { clampFootprintCenter, footprintInsideSite } from "./site_frame.js";
import type { SiteEdit } from "./site_edit.js";

export type SitePose = { x: number; y: number; theta: number };

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
  original: SitePose;
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
      throw new Error("建筑宽度和高度必须是大于 0 的米数。");
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
  demSoft: number | null;
  roadDistance: number | null;
  demandDistance: number | null;
  obstacleHardCount: number | null;
  isFeasible: boolean | null;
  offroadHaulM: number | null;
  haulRiseM: number | null;
  accessSlopeDeg: number;
  accessWarning: boolean;
};

export type StatusRow = { label: string; value: string };

/** One status card for the selected footprint. Adjusted values never masquerade as original CSV metrics. */
export function choiceStatus(choice: ParetoChoice, report: ChoiceReport | null): StatusRow[] {
  const edited = isChoiceEdited(choice);
  const feasibility = report?.isFeasible == null
    ? (edited ? `${choice.feasible} → 等待精确评价` : choice.feasible)
    : (edited ? `${choice.feasible} → ${report.isFeasible ? "可行" : "不可行"}` : report.isFeasible ? "可行" : "不可行");
  const rows: StatusRow[] = [
    { label: "位置（m）", value: `${choice.x.toFixed(0)}, ${choice.y.toFixed(0)}` },
    { label: "朝向（°）", value: formatObjective(String(radiansToDegrees(choice.theta))) },
    { label: "可行性", value: feasibility },
    { label: "地形平整度", value: changedMetric(choice.demSoft, report?.demSoft ?? null, edited) },
    { label: "道路距离（m）", value: changedMetric(choice.roadDistance, report?.roadDistance ?? null, edited) },
    { label: "需求点距离（m）", value: changedMetric(choice.demandDistance, report?.demandDistance ?? null, edited) },
    { label: "进场（m）", value: changedMetric(choice.offroadHaul, report?.offroadHaulM ?? null, edited) },
    { label: "进场高差（m）", value: changedMetric(choice.haulRise, report?.haulRiseM ?? null, edited) },
  ];
  if (report?.obstacleHardCount != null) {
    rows.push({ label: "禁建覆盖格数", value: formatObjective(String(report.obstacleHardCount)) });
  }
  if (report) {
    const slope = formatObjective(String(report.accessSlopeDeg));
    rows.push({ label: "进场坡度（°）", value: report.accessWarning ? `${slope} · 偏陡` : slope });
  }
  return rows;
}

function changedMetric(original: string, current: number | null, edited: boolean): string {
  if (current == null) return edited ? `${original} → 等待精确评价` : original;
  const formatted = formatObjective(String(current));
  return edited ? `${original} → ${formatted}` : formatted;
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
  return { ...choice, ...choice.original };
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
      original: { x, y, theta },
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
