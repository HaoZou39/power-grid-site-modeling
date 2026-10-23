/** Coordinate scene-build form. The backend remains the authority for site identity. */

export const BUILD_SCENE_PLUGIN = "site.build_scene";
export const DEFAULT_SIDE_LENGTH_M = 1800;
export const MAX_SIDE_LENGTH_M = 10000;

const STAGE_LABEL: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  generating_data: "正在生成数据",
  validating_data: "正在校验数据",
  rebuilding_scene: "正在重建场景",
  ready: "场景已就绪",
  completed: "已完成",
  failed: "失败",
  cancelled: "已终止",
};

export type BuildSceneConfig = {
  lat: number;
  lon: number;
  side_length_m: number;
  site_name?: string;
};

export function radiusKmFromSideLength(sideLengthM: number): number {
  return sideLengthM / 2000;
}

export function projectedExtentSummary(sideLengthM: number): string | null {
  if (!Number.isInteger(sideLengthM) || sideLengthM < 2 || sideLengthM > MAX_SIDE_LENGTH_M || sideLengthM % 2 !== 0) return null;
  const halfSideM = sideLengthM / 2;
  const radiusKm = radiusKmFromSideLength(sideLengthM);
  return `正方形边长 ${sideLengthM} m，一格 1 m，网格 ${sideLengthM} × ${sideLengthM}。Web Mercator 半边长 ${halfSideM} m（radius_km=${radiusKm}）。真实地理范围以生成后的 GeoTIFF bounds 为准。`;
}

export function sceneBuildExtentLines(sideLengthM: number): { grid: string; resolution: string; mercator: string } | null {
  if (projectedExtentSummary(sideLengthM) === null) return null;
  return {
    grid: `网格：${sideLengthM} × ${sideLengthM}`,
    resolution: "分辨率：1 m",
    mercator: `Web Mercator 半边长 ${sideLengthM / 2} m。真实地理范围以生成后的 GeoTIFF bounds 为准。`,
  };
}

const SITE_NAME = /^[0-9A-Za-z\u4e00-\u9fff][0-9A-Za-z\u4e00-\u9fff_-]{0,40}$/;

export function parseBuildSceneConfig(input: {
  lat: string;
  lon: string;
  sideLengthM: string;
  siteName: string;
}): { ok: true; config: BuildSceneConfig } | { ok: false; error: string } {
  const lat = Number(input.lat.trim());
  const lon = Number(input.lon.trim());
  const sideLengthM = Number(input.sideLengthM.trim());
  if (!input.lat.trim() || !Number.isFinite(lat) || lat < -90 || lat > 90) return { ok: false, error: "纬度必须是 -90 到 90 之间的有限数字。" };
  if (!input.lon.trim() || !Number.isFinite(lon) || lon < -180 || lon > 180) return { ok: false, error: "经度必须是 -180 到 180 之间的有限数字。" };
  if (!Number.isInteger(sideLengthM) || sideLengthM < 2 || sideLengthM > MAX_SIDE_LENGTH_M || sideLengthM % 2 !== 0) {
    return { ok: false, error: `边长必须是 2 到 ${MAX_SIDE_LENGTH_M} 之间的偶数米。一格是 1 m，网格等于边长乘边长。` };
  }
  const siteName = input.siteName.trim();
  if (siteName && !SITE_NAME.test(siteName)) {
    return { ok: false, error: "场景名称只能使用中文、字母、数字、下划线或连字符。" };
  }
  return {
    ok: true,
    config: {
      lat,
      lon,
      side_length_m: sideLengthM,
      ...(siteName ? { site_name: siteName } : {}),
    },
  };
}

export function selectBuiltScene<T extends { id: string }>(scenes: readonly T[], builtId: string): T | null {
  const match = scenes.find((scene) => scene.id === builtId);
  return match ?? null;
}

export function builtSceneId(result: Record<string, unknown> | null): string | null {
  const data = result?.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const sceneId = (data as Record<string, unknown>).scene_id;
  return typeof sceneId === "string" && sceneId.trim() ? sceneId : null;
}

export function buildStageLabel(stage: string): string {
  return STAGE_LABEL[stage] ?? (stage.trim() || "未提供");
}

export function elapsedSeconds(createdAt: string, updatedAt: string): number | null {
  const started = Date.parse(createdAt);
  const updated = Date.parse(updatedAt);
  if (!Number.isFinite(started) || !Number.isFinite(updated) || updated < started) return null;
  return Math.round((updated - started) / 1000);
}
