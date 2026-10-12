/** Default importance per objective, served by /api/v1/agent/preferences. The files live on the backend. */

/** Same keys and labels as agent/analysis.py RANKED_OBJECTIVES; every one is minimized. */
export const PREFERENCE_OBJECTIVES: readonly { key: string; label: string }[] = [
  { key: "dem_soft", label: "地形平整度" },
  { key: "demand_distance", label: "需求点距离（m）" },
  { key: "road_haul_m", label: "沿路长度（m）" },
  { key: "offroad_haul_m", label: "进场（m）" },
  { key: "haul_rise_m", label: "进场高差（m）" },
];

/** 0 ignores the objective, 5 matters most; a key left out counts as 1. */
export const IMPORTANCE_MAX = 5;

export type PreferenceState = {
  defaults: { weights: Record<string, number> } | null;
  choice_count: number;
};

export async function readPreferences(): Promise<PreferenceState> {
  return parseResponse(await fetch("/api/v1/agent/preferences"));
}

export async function writeDefaults(weights: Record<string, number>): Promise<PreferenceState> {
  return parseResponse(await fetch("/api/v1/agent/preferences/defaults", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ weights }),
  }));
}

/** Importance shown on the page: saved values, 1 for anything not saved yet. */
export function importanceOf(state: PreferenceState | null): Record<string, number> {
  const saved = state?.defaults?.weights ?? {};
  return Object.fromEntries(PREFERENCE_OBJECTIVES.map(({ key }) => [key, saved[key] ?? 1]));
}

async function parseResponse(response: Response): Promise<PreferenceState> {
  const body = await response.json().catch(() => ({}));
  if (response.status === 404) throw new Error("后端没有偏好接口，可能还是旧版本。请重启 API 后再打开「偏好」页。");
  if (!response.ok) throw new Error(body?.detail?.message ?? `偏好读写失败 (${response.status})`);
  return body as PreferenceState;
}
