/**
 * Read-only view model for the siting problem.
 * Fields are display strings. Missing inputs stay "未提供"; this module does not
 * compute objectives, feasibility, or coordinates.
 */

export const NOT_PROVIDED = "未提供";

/** Shown until GET /api/v1/problem/context exists. Fixture data must not use this label. */
export const EXPERIMENT_SOURCE_LABEL = "来自实验产物";

/** Modeling objective order. Displayed as the problem definition, not derived from a run. */
export const OBJECTIVE_ORDER = ["dem_soft", "road_distance", "demand_distance"] as const;

/** Hard rule from the modeling spec. The view does not count obstacle cells. */
export const HARD_FEASIBILITY_RULE = "不可建设区域 hard count 必须为 0";

export const EMPTY_EXPERIMENT_MISSING = [
  "实验目录",
  "data_metadata.json",
  "resolved_config.json",
  "地图 PNG",
] as const;

export const EMPTY_EXPERIMENT_NEXT_ACTION =
  "先完成一次实验，并在输出目录中保留 data_metadata.json、resolved_config.json 和地图 PNG。";

export type ProblemSnapshot = {
  sourceLabel: typeof EXPERIMENT_SOURCE_LABEL;
  experimentName: string;
  /** Raster width in cells, from dem.shape[1]. */
  gridWidth: string;
  /** Raster height in cells, from dem.shape[0]. */
  gridHeight: string;
  /** Cell size in meters, from dem.target_resolution_m. */
  resolutionM: string;
  coordinateConvention: string;
  layers: {
    dem: boolean;
    obstacle: boolean;
    roads: boolean;
    demandPoints: boolean;
  };
  dataSource: string;
  /** Demand-point seed. Algorithm seeds are not a substitute. */
  seed: string;
  /** Building rectangle width in meters, from modeling.rect_w_m. */
  rectWidthM: string;
  /** Building rectangle height in meters, from modeling.rect_h_m. */
  rectHeightM: string;
  objectiveOrder: typeof OBJECTIVE_ORDER;
  hardFeasibility: typeof HARD_FEASIBILITY_RULE;
  /** Manifest artifact URL. Null when the catalog did not list an image. */
  mapImageUrl: string | null;
  missing: string[];
};

export type ProblemSnapshotInput = {
  experimentName: string;
  dataMetadata: unknown;
  resolvedConfig: unknown;
  mapImageUrl: string | null;
};

export type ManifestArtifact = {
  name: string;
  kind: string;
  url: string;
};

type JsonRecord = Record<string, unknown>;

const ORIGIN_LABEL: Record<string, string> = { upper_left: "左上角" };
const AXIS_LABEL: Record<string, string> = { right: "向右", down: "向下", left: "向左", up: "向上" };
const UNIT_LABEL: Record<string, string> = { meter: "米" };

export function emptyExperimentOverview(): { missing: string[]; nextAction: string } {
  return {
    missing: [...EMPTY_EXPERIMENT_MISSING],
    nextAction: EMPTY_EXPERIMENT_NEXT_ACTION,
  };
}

/** Pick overview files from the catalog manifest. URLs are never synthesized from names. */
export function selectProblemArtifacts(artifacts: readonly ManifestArtifact[]): {
  metadataUrl: string | null;
  configUrl: string | null;
  mapImageUrl: string | null;
} {
  return {
    metadataUrl: artifactUrl(artifacts, (item) => item.kind === "json" && item.name === "data_metadata.json"),
    configUrl: artifactUrl(artifacts, (item) => item.kind === "json" && item.name === "resolved_config.json"),
    mapImageUrl: artifactUrl(artifacts, (item) => item.kind === "image"),
  };
}

export function adaptProblemSnapshot(input: ProblemSnapshotInput): ProblemSnapshot {
  const missing: string[] = [];
  const experimentName = input.experimentName.trim();
  if (!experimentName) missing.push("实验名称");

  const metadata = asRecord(input.dataMetadata);
  if (!metadata) missing.push("data_metadata.json");
  const dem = metadata ? asRecord(metadata.dem) : null;
  const landuse = metadata ? asRecord(metadata.landuse) : null;
  const road = metadata ? asRecord(metadata.road) : null;
  const demand = metadata ? asRecord(metadata.demand) : null;
  if (metadata && !dem) missing.push("DEM");
  if (metadata && !landuse) missing.push("不可建设区域");
  if (metadata && !road) missing.push("道路");
  if (metadata && !demand) missing.push("需求点");

  const shape = numberPair(dem?.shape);
  if (metadata && dem && !shape) missing.push("栅格范围");
  const resolution = finiteNumber(dem?.target_resolution_m);
  if (metadata && dem && resolution === null) missing.push("分辨率");
  const coordinateConvention = coordinateText(dem?.local_coord_convention);
  if (metadata && dem && coordinateConvention === NOT_PROVIDED) missing.push("坐标约定");
  const dataSource = text(dem?.source_path);
  if (metadata && dem && dataSource === NOT_PROVIDED) missing.push("数据来源");
  const seed = finiteNumber(demand?.demand_seed);
  if (metadata && demand && seed === null) missing.push("需求点 seed");

  const config = asRecord(input.resolvedConfig);
  if (!config) missing.push("resolved_config.json");
  const modeling = config ? asRecord(config.modeling) : null;
  const rectWidth = finiteNumber(modeling?.rect_w_m);
  const rectHeight = finiteNumber(modeling?.rect_h_m);
  if (config && rectWidth === null) missing.push("建筑矩形宽度");
  if (config && rectHeight === null) missing.push("建筑矩形高度");

  const mapImageUrl = input.mapImageUrl && input.mapImageUrl.trim() ? input.mapImageUrl : null;
  if (!mapImageUrl) missing.push("地图 PNG");

  return {
    sourceLabel: EXPERIMENT_SOURCE_LABEL,
    experimentName: experimentName || NOT_PROVIDED,
    gridWidth: shape ? String(shape[1]) : NOT_PROVIDED,
    gridHeight: shape ? String(shape[0]) : NOT_PROVIDED,
    resolutionM: resolution === null ? NOT_PROVIDED : `${String(resolution)} m`,
    coordinateConvention,
    layers: {
      dem: dem !== null,
      obstacle: landuse !== null,
      roads: road !== null,
      demandPoints: demand !== null,
    },
    dataSource,
    seed: seed === null ? NOT_PROVIDED : String(seed),
    rectWidthM: rectWidth === null ? NOT_PROVIDED : `${String(rectWidth)} m`,
    rectHeightM: rectHeight === null ? NOT_PROVIDED : `${String(rectHeight)} m`,
    objectiveOrder: OBJECTIVE_ORDER,
    hardFeasibility: HARD_FEASIBILITY_RULE,
    mapImageUrl,
    missing,
  };
}

function artifactUrl(
  artifacts: readonly ManifestArtifact[],
  predicate: (item: ManifestArtifact) => boolean,
): string | null {
  const match = artifacts.find((item) => predicate(item) && item.url.trim());
  return match ? match.url : null;
}

function asRecord(value: unknown): JsonRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as JsonRecord;
}

function text(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : NOT_PROVIDED;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function numberPair(value: unknown): [number, number] | null {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const height = finiteNumber(value[0]);
  const width = finiteNumber(value[1]);
  if (height === null || width === null) return null;
  return [height, width];
}

function coordinateText(value: unknown): string {
  const convention = asRecord(value);
  if (!convention) return NOT_PROVIDED;
  const origin = typeof convention.origin === "string" ? convention.origin : "";
  const xPositive = typeof convention.x_positive === "string" ? convention.x_positive : "";
  const yPositive = typeof convention.y_positive === "string" ? convention.y_positive : "";
  const unit = typeof convention.unit === "string" ? convention.unit : "";
  if (!origin || !xPositive || !yPositive || !unit) return NOT_PROVIDED;
  return `原点 ${knownOrRaw(ORIGIN_LABEL, origin)}，x ${knownOrRaw(AXIS_LABEL, xPositive)}，y ${knownOrRaw(AXIS_LABEL, yPositive)}，单位 ${knownOrRaw(UNIT_LABEL, unit)}`;
}

function knownOrRaw(labels: Record<string, string>, value: string): string {
  return labels[value] ?? value;
}
