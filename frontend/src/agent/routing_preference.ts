import type { RoutingObjectives } from "../routing/routing_result.js";

export type RoutingPreference = Record<keyof RoutingObjectives, number>;
export const ROUTING_PREFERENCE_KEY = "power-grid.routing-preference.v1";
export const ROUTING_PREFERENCE_OBJECTIVES: readonly { key: keyof RoutingObjectives; label: string }[] = [
  { key: "tower_count", label: "新增塔数" },
  { key: "length_3d_m", label: "三维长度" },
  { key: "bend_sum_rad", label: "水平曲折" },
  { key: "crossing_3d_m", label: "跨越长度" },
];

export function defaultRoutingPreference(): RoutingPreference {
  return { tower_count: 1, length_3d_m: 1, bend_sum_rad: 1, crossing_3d_m: 1 };
}

export function readRoutingPreference(storage: Pick<Storage, "getItem">): RoutingPreference | null {
  const saved = storage.getItem(ROUTING_PREFERENCE_KEY);
  if (saved === null) return null;
  const value: unknown = JSON.parse(saved);
  if (!value || typeof value !== "object" || ROUTING_PREFERENCE_OBJECTIVES.some(({ key }) => {
    const score = (value as Record<string, unknown>)[key];
    return typeof score !== "number" || !Number.isInteger(score) || score < 0 || score > 5;
  })) throw new Error("保存的选线偏好格式无效，请重新设置并保存。");
  return Object.fromEntries(ROUTING_PREFERENCE_OBJECTIVES.map(({ key }) => [key, (value as RoutingPreference)[key]])) as RoutingPreference;
}

export function writeRoutingPreference(storage: Pick<Storage, "setItem">, preference: RoutingPreference) {
  storage.setItem(ROUTING_PREFERENCE_KEY, JSON.stringify(preference));
}
