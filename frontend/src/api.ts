/** Typed HTTP seam shared by every frontend feature. */
import type { components } from "./generated/api";
import { resolveSchemaRefs } from "./config_check";
import { adaptProblemSnapshot, selectProblemArtifacts } from "./problem_snapshot";
import type { ProblemSnapshot } from "./problem_snapshot";

export type { ProblemSnapshot };

export type JsonSchema = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  required?: string[];
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  minItems?: number;
  maxItems?: number;
  /** Presentation hints. A new plugin can set these in its schema without a form change. */
  "x-unit"?: string;
  "x-group"?: "identity" | "site" | "preference" | "algorithm";
  "x-readonly"?: boolean;
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  allOf?: JsonSchema[];
};

type GeneratedPluginSpec = components["schemas"]["PluginSpecResponse"];
export type PluginSpec = Omit<GeneratedPluginSpec, "config_schema"> & {
  config_schema: JsonSchema;
};

type GeneratedJobRecord = components["schemas"]["JobResponse"];
export type JobRecord = Omit<GeneratedJobRecord, "status" | "result" | "error"> & {
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  result: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...init,
    headers,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail?.message ?? `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const getHealth = () => request<components["schemas"]["HealthResponse"]>("/api/v1/health");
export const getPlugins = async () => {
  const catalog = await request<{ items: PluginSpec[] }>("/api/v1/plugins");
  return {
    items: catalog.items.map((item) => ({
      ...item,
      config_schema: resolveSchemaRefs(item.config_schema),
    })),
  };
};
export const createJob = (payload: JobCreateRequest) =>
  request<JobRecord>("/api/v1/jobs", { method: "POST", body: JSON.stringify(payload) });
export const getJob = (jobId: string) => request<JobRecord>(`/api/v1/jobs/${jobId}`);
export const cancelJob = (jobId: string) =>
  request<JobRecord>(`/api/v1/jobs/${jobId}/cancel`, { method: "POST" });

export type JobCreateRequest = components["schemas"]["JobCreateRequest"];

export type ArtifactRecord = Omit<components["schemas"]["ArtifactResponse"], "kind"> & {
  kind: "image" | "html" | "json" | "table";
};

export type ExperimentRecord = Omit<components["schemas"]["ExperimentResponse"], "artifacts"> & {
  artifacts: ArtifactRecord[];
};

export const getExperiments = () => request<ExperimentRecord[]>("/api/v1/experiments");

export type SceneRecord = {
  id: string;
  title: string;
  ready: boolean;
  missing: string[];
};

export const getScenes = () => request<SceneRecord[]>("/api/v1/scenes");

export type LandusePatch = {
  class_id: number;
  cell_count: number;
  points: [number, number][];
};

export const pickLandusePatch = (sceneId: string, x: number, y: number) =>
  request<LandusePatch>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/landuse-patch`, {
    method: "POST",
    body: JSON.stringify({ x, y }),
  });

export type SiteReport = {
  footprint_slope_deg: number;
  slope_limit_deg: number;
  access_rise_m: number;
  access_slope_deg: number;
  access_warning: boolean;
  road_haul_m: number | null;
  offroad_haul_m: number | null;
  haul_rise_m: number | null;
  haul_path: [number, number][] | null;
  /** Added by the precise single-candidate evaluator in the backend phase. */
  dem_soft?: number | null;
  obstacle_soft?: number | null;
  road_distance?: number | null;
  demand_distance?: number | null;
  dem_hard_var?: number | null;
  dem_hard_range?: number | null;
  obstacle_hard_count?: number | null;
  obstacle_hard_ratio?: number | null;
  constraint_violation?: number | null;
  is_feasible?: boolean | null;
};

export type SiteReportRequest = {
  x: number;
  y: number;
  /** Internal pose angle in radians. */
  theta: number;
  rect_w_m: number;
  rect_h_m: number;
  field_policy: "blocked" | "allowed" | "costly";
  mountain_policy: "blocked" | "allowed";
  field_cost: number;
  exclusion_zones: { points: [number, number][] }[];
  origin_x?: number;
  origin_y?: number;
};

export const fetchSiteReport = (
  sceneId: string,
  body: SiteReportRequest,
) => request<SiteReport>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/site-report`, {
  method: "POST",
  body: JSON.stringify(body),
});

/** Read an artifact body as text. The URL must come from the experiment manifest. */
export async function fetchArtifactText(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail?.message ?? `请求失败 (${response.status})`);
  }
  return response.text();
}

/** Load one experiment's problem overview from manifest URLs only. */
export async function loadProblemSnapshot(experiment: ExperimentRecord): Promise<ProblemSnapshot> {
  const selected = selectProblemArtifacts(experiment.artifacts);
  const [dataMetadata, resolvedConfig] = await Promise.all([
    selected.metadataUrl ? request<unknown>(selected.metadataUrl) : Promise.resolve(null),
    selected.configUrl ? request<unknown>(selected.configUrl) : Promise.resolve(null),
  ]);
  return adaptProblemSnapshot({
    experimentName: experiment.name,
    dataMetadata,
    resolvedConfig,
    mapImageUrl: selected.mapImageUrl,
  });
}
