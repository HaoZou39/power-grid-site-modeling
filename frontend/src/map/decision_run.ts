import { failurePresentation, submittedExperimentId } from "../run_status.js";
import { adaptSolutions, selectResultArtifacts } from "../solution_record.js";
import type { ResultArtifact, SolutionRecord } from "../solution_record.js";
import { siteFrame } from "./site_frame.js";

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
    origin_x?: number;
    origin_y?: number;
  };
};

export type FieldPolicy = "blocked" | "allowed" | "costly";
export type MountainPolicy = "blocked" | "allowed";

export type DecisionConstraints = {
  fieldPolicy: FieldPolicy;
  mountainPolicy: MountainPolicy;
  fieldCost: number;
  exclusionZones: { points: [number, number][] }[];
};

const OPEN_CONSTRAINTS: DecisionConstraints = {
  fieldPolicy: "allowed",
  mountainPolicy: "allowed",
  fieldCost: 0.5,
  exclusionZones: [],
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

  createRequest(
    size: BuildingSize,
    sceneName: string,
    now = new Date(),
    constraints: DecisionConstraints = OPEN_CONSTRAINTS,
    origin?: { x: number; y: number },
  ): DecisionJobRequest {
    return {
      plugin_id: Nsga2DecisionRun.pluginId,
      config: {
        experiment_name: `site-${stamp(now)}`,
        scene_name: sceneName,
        rect_w_m: size.widthM,
        rect_h_m: size.heightM,
        field_policy: constraints.fieldPolicy,
        mountain_policy: constraints.mountainPolicy,
        field_cost: constraints.fieldCost,
        exclusion_zones: constraints.exclusionZones,
        ...(origin ? { origin_x: origin.x, origin_y: origin.y } : {}),
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
};

export type StatusRow = { label: string; value: string };

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
  return {
    ...choice,
    x: clamp(choice.x + dx, 0, siteFrame.widthM),
    y: clamp(choice.y + dy, 0, siteFrame.heightM),
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
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

function stamp(now: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}
