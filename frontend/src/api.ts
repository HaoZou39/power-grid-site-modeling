/** Typed HTTP seam shared by every frontend feature. */
import type { components } from "./generated/api";
import { resolveSchemaRefs } from "./config_check";
import { adaptProblemSnapshot, selectProblemArtifacts } from "./problem_snapshot";
import type { ProblemSnapshot } from "./problem_snapshot";
import type { SearchConfig, SiteReportBody } from "./map/site_edit";
import type { PoseObjectives } from "./map/decision_run";
import type { SceneFrameInfo } from "./map/site_frame";
import type { FavoritePointRecord } from "./map/favorite_points";
import type { SiteReport } from "./map/site_report_types";
export type { SiteReport } from "./map/site_report_types";

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
  status: "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled";
  result: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
};

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly sceneRevision: string | null;

  constructor(message: string, status: number, code: string | null, sceneRevision: string | null) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
    this.sceneRevision = sceneRevision;
  }
}

function errorParts(body: { detail?: { message?: string; code?: string; scene_revision?: string } | { msg?: string }[] }, status: number): {
  message: string;
  code: string | null;
  sceneRevision: string | null;
} {
  const detail = body.detail;
  if (Array.isArray(detail)) {
    const text = detail.map((item) => item.msg).filter(Boolean).join("；");
    return { message: text || `请求失败 (${status})`, code: null, sceneRevision: null };
  }
  if (detail?.message || detail?.code) {
    return {
      message: detail.message || `请求失败 (${status})`,
      code: detail.code ?? null,
      sceneRevision: detail.scene_revision ?? null,
    };
  }
  return { message: `请求失败 (${status})`, code: null, sceneRevision: null };
}

function errorDetail(body: Parameters<typeof errorParts>[0], status: number): string {
  return errorParts(body, status).message;
}

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
    const parts = errorParts(body, response.status);
    throw new ApiRequestError(parts.message, response.status, parts.code, parts.sceneRevision);
  }
  if (response.status === 204) return undefined as T;
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
    const parts = errorParts(body, response.status);
    throw new ApiRequestError(parts.message, response.status, parts.code, parts.sceneRevision);
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

export const saveExperiment = (body: components["schemas"]["SaveExperimentRequest"]) =>
  request<{ id: string; name: string; solution_count: number }>("/api/v1/experiments", {
    method: "POST", body: JSON.stringify(body),
  });

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
  frame: SceneFrameInfo | null;
  source_site_id: string | null;
  read_only?: boolean;
  default?: boolean;
};

export const getScenes = () => request<SceneRecord[]>("/api/v1/scenes");

/** Physically remove a scene directory and its favorites; experiment outputs are kept. */
export const deleteScene = (sceneId: string) =>
  request<{ id: string; deleted: boolean; favorites_removed: number }>(
    `/api/v1/scenes/${encodeURIComponent(sceneId)}`,
    { method: "DELETE" },
  );

export type FavoritePointCreate = Omit<
  FavoritePointRecord,
  "id" | "scene_id" | "created_at" | "updated_at"
>;
export type FavoritePointUpdate = Pick<
  FavoritePointRecord,
  "longitude" | "latitude" | "bearing_deg"
>;

export const getFavoritePoints = (sceneId: string) =>
  request<FavoritePointRecord[]>(
    `/api/v1/scenes/${encodeURIComponent(sceneId)}/favorites`,
    { cache: "no-store" },
  );

export const createFavoritePoint = (sceneId: string, payload: FavoritePointCreate) =>
  request<FavoritePointRecord>(
    `/api/v1/scenes/${encodeURIComponent(sceneId)}/favorites`,
    { method: "POST", body: JSON.stringify(payload) },
  );

export const updateFavoritePoint = (
  sceneId: string,
  favoriteId: string,
  payload: FavoritePointUpdate,
) => request<FavoritePointRecord>(
  `/api/v1/scenes/${encodeURIComponent(sceneId)}/favorites/${encodeURIComponent(favoriteId)}`,
  { method: "PUT", body: JSON.stringify(payload) },
);

export const deleteFavoritePoint = (sceneId: string, favoriteId: string) =>
  request<void>(
    `/api/v1/scenes/${encodeURIComponent(sceneId)}/favorites/${encodeURIComponent(favoriteId)}`,
    { method: "DELETE" },
  );

export type ProtectedFarmlandInfo = {
  content_sha256?: string;
  available: boolean;
  source_name?: string;
  source_crs?: string;
  feature_count?: number;
  intersecting_feature_count?: number;
  area_m2?: number;
  access_road_width_m?: number;
  osm_overlap_cells?: number;
  imported_at?: string;
  error?: string;
};

export type SceneLayerInfo = {
  scene_id: string;
  data_version?: {frame_id: string | null; scene_revision: string};
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
  roads: { available: boolean; segment_count: number; provider?: string; road_product_id?: string; error?: string };
  protected_farmland?: ProtectedFarmlandInfo;
};

export type FarmlandPreview = {
  token: string;
  scene_id: string;
  source_name: string;
  source_crs: string;
  scene_crs: string;
  feature_count: number;
  empty_feature_count: number;
  intersecting_feature_count: number;
  area_m2: number;
  osm_overlap_cells: number;
  access_road_width_m: number;
  saved: boolean;
};

export type RoadSegment = [number, number, number, number];

export const getSceneLayerInfo = (sceneId: string) =>
  request<SceneLayerInfo>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/map-layers`);

export type SceneDataPreview = {
  token: string;
  scene_id: string;
  saved: boolean;
  access_overlap_cells?: number;
  farmland: Omit<FarmlandPreview, "token" | "scene_id" | "saved"> | null;
  roads: {
    provider: string; n_segments: number;
    segment_kind_counts: Record<string, number>;
    import: { included_classes: Record<string, number>; excluded_classes: string[]; excluded_feature_counts: Record<string, number> };
  } | null;
};

export type CadFileRecord = components["schemas"]["CadFileResponse"];

export const getCadFiles = (sceneId: string, signal?: AbortSignal) =>
  request<CadFileRecord[]>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-files`, { signal });

export async function addCadFile(sceneId: string, body: FormData): Promise<CadFileRecord> {
  const response = await fetch(`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-files`, { method: "POST", body });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorDetail(payload, response.status));
  return payload as CadFileRecord;
}

export type CadKind = "field" | "building" | "road" | "water" | "ignore";
export type CadInspection = {
  layers: { name: string; polygon_count: number; invalid_count: number; unsupported_count: number;
    open_line_count: number; suggested_kind: Exclude<CadKind, "ignore"> | null }[];
  drawing_units: number;
  warnings: string[];
};
export type CadLandusePreview = {
  token: string; cell_counts: Record<string, number>; covered_area_m2: number; warnings: string[];
};
export const inspectCadFile = (sceneId: string, cadId: string) =>
  request<CadInspection>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-files/${cadId}/inspect`, { method: "POST" });
export const previewCadLanduse = (sceneId: string, cadId: string, sourceCrs: string, layerKinds: Record<string, CadKind>) =>
  request<CadLandusePreview>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-files/${cadId}/preview`, {
    method: "POST", body: JSON.stringify({ source_crs: sourceCrs.trim(), layer_kinds: layerKinds }),
  });
export const confirmCadLanduse = (sceneId: string, token: string) =>
  request<{ scene_revision: string }>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-files/confirm`, { method: "POST", body: JSON.stringify({ token }) });
export const clearCadLanduse = (sceneId: string) =>
  request<{ changed: boolean; scene_revision?: string }>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-landuse`, { method: "DELETE" });

export async function previewSceneData(sceneId: string, body: FormData): Promise<SceneDataPreview> {
  const response = await fetch(`/api/v1/scenes/${encodeURIComponent(sceneId)}/data-import/preview`, { method: "POST", body });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorDetail(payload, response.status));
  return payload as SceneDataPreview;
}

export const confirmSceneData = (sceneId: string, token: string) =>
  request<SceneDataPreview>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/data-import/confirm`, {
    method: "POST", body: JSON.stringify({ token }),
  });

export const restoreOsmRoads = (sceneId: string) =>
  request(`/api/v1/scenes/${encodeURIComponent(sceneId)}/data-import/restore-osm`, { method: "POST" });

export const getRoadPreview = (sceneId: string, token: string) =>
  request<{ segments: RoadSegment[]; kinds: number[] }>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/data-import/preview/${token}/roads`);

export const deleteProtectedFarmland = (sceneId: string) =>
  request<void>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/protected-farmland`, { method: "DELETE" });

export const getRoadSegments = (sceneId: string) =>
  request<{ segments: RoadSegment[]; kinds: number[]; count: number }>(
    `/api/v1/scenes/${encodeURIComponent(sceneId)}/road-segments`,
  );

export type AdminBoundaryCollection = GeoJSON.FeatureCollection & { source?: string };

export const getAdminBoundaries = (sceneId: string) =>
  request<AdminBoundaryCollection>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/admin-boundaries`);

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

export type LanduseEditClassId = 1 | 2 | 3 | 5;
export type LanduseEdit = {
  id: string;
  class_id?: LanduseEditClassId;
  operation?: "water_to_other";
  points: [number, number][];
};

export const getLanduseEdits = (sceneId: string) =>
  request<{ items: LanduseEdit[]; scene_revision: string }>(
    `/api/v1/scenes/${encodeURIComponent(sceneId)}/landuse-edits`,
    { cache: "no-store" },
  );

export const replaceLanduseEdits = (
  sceneId: string,
  expectedSceneRevision: string,
  items: LanduseEdit[],
) => request<{ items: LanduseEdit[]; scene_revision: string; changed: boolean }>(
  `/api/v1/scenes/${encodeURIComponent(sceneId)}/landuse-edits/batch`,
  {
    method: "POST",
    body: JSON.stringify({ expected_scene_revision: expectedSceneRevision, items }),
  },
);

export const clearLanduseEdits = (sceneId: string) =>
  request<{ items: LanduseEdit[] }>(
    `/api/v1/scenes/${encodeURIComponent(sceneId)}/landuse-edits`,
    { method: "DELETE" },
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

export type SiteReportRequest = SiteReportBody;

export const fetchSiteReport = (
  sceneId: string,
  body: SiteReportRequest,
  signal?: AbortSignal,
) => request<SiteReport>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/site-report`, {
  method: "POST",
  body: JSON.stringify(body),
  signal,
});

/** Same columns as the search's solution table, for poses placed outside the search. */
export const fetchPoseObjectives = (
  sceneId: string,
  body: Omit<SearchConfig, "scene_name"> & { poses: { x: number; y: number; theta: number }[] },
  signal?: AbortSignal,
) => request<{ items: PoseObjectives[] }>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/pose-objectives`, {
  method: "POST",
  body: JSON.stringify(body),
  signal,
});

export type ConstructionFeasibilityRequest = Pick<
  SearchConfig,
  "mountain_policy" | "field_policy" | "field_cost" | "exclusion_zones" | "feasible_zones" | "road_setback_m" | "water_setback_m"
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
    throw new Error(errorDetail(body, response.status));
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
