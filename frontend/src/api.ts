/** Typed HTTP seam shared by every frontend feature. */
import type { components } from "./generated/api";
import { resolveSchemaRefs } from "./config_check";
import { adaptProblemSnapshot, selectProblemArtifacts } from "./problem_snapshot";
import type { ProblemSnapshot } from "./problem_snapshot";
import type { SearchConfig, SiteReportBody } from "./map/site_edit";
import type { SitePlanningConfig } from "./map/site_plan";
import type { RoutingPlanningConfig } from "./routing/routing_plan";
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

let csrfToken = "";

export function setCsrfToken(token: string): void {
  csrfToken = token;
}

export function clearCsrfToken(): void {
  csrfToken = "";
}

export { resetAccountStorage } from "./account_storage";

function withSession(init?: RequestInit): RequestInit {
  const headers = new Headers(init?.headers);
  const method = (init?.method ?? "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD" && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  if (init?.body != null && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return { ...init, headers, credentials: "include" };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, withSession(init));
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/api/v1/auth/login")) {
      window.dispatchEvent(new Event("session-expired"));
    }
    const body = await response.json().catch(() => ({}));
    const parts = errorParts(body, response.status);
    throw new ApiRequestError(parts.message, response.status, parts.code, parts.sceneRevision);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  const response = await fetch(path, withSession(init));
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/api/v1/auth/login")) {
      window.dispatchEvent(new Event("session-expired"));
    }
    const body = await response.json().catch(() => ({}));
    const parts = errorParts(body, response.status);
    throw new ApiRequestError(parts.message, response.status, parts.code, parts.sceneRevision);
  }
  return response.blob();
}

export type Account = {
  id: string;
  username: string;
  role: "admin" | "user";
  disabled_at: string | null;
  created_at: string;
};

export const getHealth = () => request<components["schemas"]["HealthResponse"]>("/api/v1/health");
export const currentAccount = () => request<{ user: Account; csrf_token: string }>("/api/v1/auth/me");
export const loginAccount = (username: string, password: string) =>
  request<{ user: Account; csrf_token: string }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
export const logoutAccount = () => request<{ ok: boolean }>("/api/v1/auth/logout", { method: "POST" });
export const listAccounts = () => request<{ users: Account[] }>("/api/v1/admin/users");
export const createAccount = (body: { username: string; password: string; role: "admin" | "user" }) =>
  request<Account>("/api/v1/admin/users", { method: "POST", body: JSON.stringify(body) });
export const patchAccount = (userId: string, body: { disabled?: boolean; password?: string }) =>
  request<Account>(`/api/v1/admin/users/${userId}`, { method: "PATCH", body: JSON.stringify(body) });
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

export const getExperiments = (casesOnly = false) => request<ExperimentRecord[]>(`/api/v1/experiments${casesOnly ? "?cases_only=true" : ""}`);

export const saveRoutingExperiment = (body: { name: string; source_experiment_id: string; task: Record<string, unknown> }) =>
  request<{ id: string; name: string; solution_count: number }>("/api/v1/routing-experiments", {
    method: "POST", body: JSON.stringify(body),
  });

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

/** Personal planning metadata. The map does not list or switch these yet. */
export type PlanningWorkspace = {
  workspace_id: string;
  owner_id: string;
  base_scene_id: string;
  base_frame_id: string;
  base_revision: string;
  workspace_revision: string;
  display_name: string;
  created_at: string;
  updated_at: string;
  base_status: "current" | "changed" | "missing";
};

export const listPlanningWorkspaces = (baseSceneId?: string) =>
  request<PlanningWorkspace[]>(
    `/api/v1/workspaces${baseSceneId ? `?base_scene_id=${encodeURIComponent(baseSceneId)}` : ""}`,
  );

export const createPlanningWorkspace = (body: { base_scene_id: string; display_name: string }) =>
  request<PlanningWorkspace>("/api/v1/workspaces", { method: "POST", body: JSON.stringify(body) });

export const getPlanningWorkspace = (workspaceId: string) =>
  request<PlanningWorkspace>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}`);

export const renamePlanningWorkspace = (workspaceId: string, displayName: string) =>
  request<PlanningWorkspace>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}`, {
    method: "PATCH",
    body: JSON.stringify({ display_name: displayName }),
  });

export const deletePlanningWorkspace = (workspaceId: string) =>
  request<{ workspace_id: string; deleted: boolean }>(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}`,
    { method: "DELETE" },
  );

/** Saved planning inputs. The map does not load or switch these yet, and search still uses the public scene. */
export type WorkspacePlan = {
  workspace_id: string;
  workspace_revision: string;
  base_status: PlanningWorkspace["base_status"];
  schema_version: 1;
  site: SitePlanningConfig | null;
  routing: RoutingPlanningConfig | null;
};

export type WorkspacePlanSaved = { workspace_revision: string; changed: boolean };

export const getWorkspacePlan = (workspaceId: string) =>
  request<WorkspacePlan>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/plan`);

export const saveWorkspaceSitePlan = (
  workspaceId: string,
  body: { expected_workspace_revision: string; site: SitePlanningConfig | null },
) => request<WorkspacePlanSaved>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/plan/site`, {
  method: "PUT",
  body: JSON.stringify(body),
});

export const saveWorkspaceRoutingPlan = (
  workspaceId: string,
  body: { expected_workspace_revision: string; routing: RoutingPlanningConfig | null },
) => request<WorkspacePlanSaved>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/plan/routing`, {
  method: "PUT",
  body: JSON.stringify(body),
});

/** Physically remove a scene directory and its favorites; experiment outputs are kept. */
export const deleteScene = (sceneId: string) =>
  request<{ id: string; deleted: boolean; favorites_removed: number }>(
    `/api/v1/scenes/${encodeURIComponent(sceneId)}`,
    { method: "DELETE" },
  );

/** Update the display title. The scene id and stored products stay in place. */
export const renameScene = (sceneId: string, title: string) =>
  request<{ id: string; title: string }>(
    `/api/v1/scenes/${encodeURIComponent(sceneId)}`,
    { method: "PATCH", body: JSON.stringify({ title }) },
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

export type CadFileRecord = components["schemas"]["CadFileResponse"] & { reused?: boolean };

export class CadNameConflict extends Error {
  readonly matches: CadFileRecord[];

  constructor(message: string, matches: CadFileRecord[]) {
    super(message);
    this.name = "CadNameConflict";
    this.matches = matches;
  }
}

export const getCadFiles = (sceneId: string, signal?: AbortSignal) =>
  request<CadFileRecord[]>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-files`, { signal });

export async function addCadFile(sceneId: string, body: FormData): Promise<CadFileRecord> {
  const response = await fetch(`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-files`, { method: "POST", body });
  const payload = await response.json().catch(() => ({}));
  const detail = payload.detail;
  if (response.status === 409 && detail?.code === "cad_name_conflict") {
    throw new CadNameConflict(detail.message || "同名 CAD 内容不同，请确认要替换的附件", detail.matches ?? []);
  }
  if (!response.ok) throw new Error(errorDetail(payload, response.status));
  return payload as CadFileRecord;
}

export async function replaceCadFile(sceneId: string, cadId: string, body: FormData): Promise<CadFileRecord> {
  const response = await fetch(`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-files/${encodeURIComponent(cadId)}/replace`, { method: "POST", body });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorDetail(payload, response.status));
  return payload as CadFileRecord;
}

export const deleteCadFile = (sceneId: string, cadId: string) =>
  request<void>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-files/${encodeURIComponent(cadId)}`, { method: "DELETE" });

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
export type CadFeasibleZones = { points: [number, number][] }[];
export type CadFeasiblePreview = {
  token: string; covered_area_m2: number; layer_name: string; feasible_zones: CadFeasibleZones; warnings: string[];
};
export const previewCadFeasible = (sceneId: string, cadId: string, sourceCrs: string) =>
  request<CadFeasiblePreview>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-files/${cadId}/feasible-preview`, {
    method: "POST", body: JSON.stringify({ source_crs: sourceCrs.trim() }),
  });
export const confirmCadFeasible = (sceneId: string, token: string) =>
  request<{ feasible_zones: CadFeasibleZones }>(`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-files/feasible-confirm`, {
    method: "POST", body: JSON.stringify({ token }),
  });
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
  operation?: "water_to_other" | "class_to_other";
  target_class_id?: LanduseEditClassId;
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
  "mountain_policy" | "field_policy" | "field_cost" | "exclusion_zones" | "feasible_zones" | "road_setback_m" | "water_setback_m" | "max_elevation_m"
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
