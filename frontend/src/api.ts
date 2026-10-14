/** Typed HTTP seam shared by every frontend feature. */
import type { components } from "./generated/api";
import { resolveSchemaRefs } from "./config_check";
import { adaptProblemSnapshot, selectProblemArtifacts } from "./problem_snapshot";
import type { ProblemSnapshot } from "./problem_snapshot";
import type { SearchConfig } from "./map/site_edit";
import type { PoseObjectives } from "./map/decision_run";

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

async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail?.message ?? `请求失败 (${response.status})`);
  }
  return response.blob();
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
  /** UTC time of run_summary.json. Present after the catalog adds it; older generated types omit it. */
  modified_at?: string;
};

export const getExperiments = () => request<ExperimentRecord[]>("/api/v1/experiments");

/** Remove one completed experiment directory. The id must come from the catalog. */
export const deleteExperiment = (experimentId: string) =>
  request<{ id: string; deleted: boolean }>(
    `/api/v1/experiments/${encodeURIComponent(experimentId)}`,
    { method: "DELETE" },
  );

export type SceneRecord = {
  id: string;
  title: string;
  ready: boolean;
  missing: string[];
};

export const getScenes = () => request<SceneRecord[]>("/api/v1/scenes");

export type SceneLayerInfo = {
  dem: {
    available: boolean;
    min_elevation_m?: number;
    max_elevation_m?: number;
    unit?: "m";
    source_resolution_m?: number | null;
    grid_resolution_m?: number;
    resampling?: string;
    error?: string;
  };
  landuse: Record<"field" | "building" | "road" | "water", boolean>;
  roads: { available: boolean; segment_count: number; error?: string };
};

export type RoadSegment = [number, number, number, number];

export const getSceneLayerInfo = (sceneId: string) =>
  request<SceneLayerInfo>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/map-layers`);

export const getRoadSegments = (sceneId: string) =>
  request<{ segments: RoadSegment[]; count: number }>(
    `/api/v1/scenes/${encodeURIComponent(sceneId)}/road-segments`,
  );

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

export type LanduseEditClassId = 1 | 2 | 5;
export type LanduseEdit = {
  id: string;
  class_id: LanduseEditClassId;
  points: [number, number][];
};

export const getLanduseEdits = (sceneId: string) =>
  request<{ items: LanduseEdit[] }>(
    `/api/v1/scenes/${encodeURIComponent(sceneId)}/landuse-edits`,
  );

export const createLanduseEdit = (
  sceneId: string,
  classId: LanduseEditClassId,
  points: [number, number][],
) => request<{ items: LanduseEdit[] }>(
  `/api/v1/scenes/${encodeURIComponent(sceneId)}/landuse-edits`,
  { method: "POST", body: JSON.stringify({ class_id: classId, points }) },
);

export const updateLanduseEdit = (
  sceneId: string,
  editId: string,
  points: [number, number][],
) => request<{ items: LanduseEdit[] }>(
  `/api/v1/scenes/${encodeURIComponent(sceneId)}/landuse-edits/${encodeURIComponent(editId)}`,
  { method: "PUT", body: JSON.stringify({ points }) },
);

export const deleteLanduseEdit = (sceneId: string, editId: string) =>
  request<{ items: LanduseEdit[] }>(
    `/api/v1/scenes/${encodeURIComponent(sceneId)}/landuse-edits/${encodeURIComponent(editId)}`,
    { method: "DELETE" },
  );

export type SiteReport = {
  footprint_slope_deg: number;
  slope_limit_deg: number;
  access_rise_m: number | null;
  access_slope_deg: number | null;
  access_warning: boolean;
  access_error?: string;
  road_haul_m: number | null;
  offroad_haul_m: number | null;
  haul_rise_m: number | null;
  haul_path: [number, number][] | null;
};

export type SiteReportRequest = {
  x: number;
  y: number;
  /** Internal pose angle in radians. */
  theta: number;
  rect_w_m: number;
  rect_h_m: number;
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

/** Same columns as the search's solution table, for poses placed outside the search. */
export const fetchPoseObjectives = (
  sceneId: string,
  body: Omit<SearchConfig, "scene_name"> & { poses: { x: number; y: number; theta: number }[] },
) => request<{ items: PoseObjectives[] }>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/pose-objectives`, {
  method: "POST",
  body: JSON.stringify(body),
});

export type ConstructionFeasibilityRequest = Pick<
  SearchConfig,
  "mountain_policy" | "field_policy" | "field_cost" | "exclusion_zones" | "feasible_zones"
>;

export const fetchConstructionFeasibilityOverlay = (
  sceneId: string,
  body: ConstructionFeasibilityRequest,
  signal?: AbortSignal,
) => requestBlob(
  `/api/v1/scenes/${encodeURIComponent(sceneId)}/construction-feasibility-overlay`,
  { method: "POST", body: JSON.stringify(body), signal },
);

export type SoftwareUpdateStatus = {
  configured: boolean;
  updating: boolean;
  id: string;
  result: "succeeded" | "rolled_back" | "failed" | null;
  message: string;
  commit: string;
};

export const getSoftwareUpdate = () => request<SoftwareUpdateStatus>("/api/v1/software-update");

export const postSoftwareUpdate = (password: string) =>
  request<{ id: string; message: string }>("/api/v1/software-update", {
    method: "POST",
    body: JSON.stringify({ password }),
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
