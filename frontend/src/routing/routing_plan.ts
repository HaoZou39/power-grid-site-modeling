import type { RoutingEdit, RoutingFields } from "./routing_edit.js";
import { validateRoutingPolygon } from "./routing_polygon.js";

/** Form text plus algorithm keys the user changed. Plugin defaults are not copied in. */
export type RoutingPlanningConfig = {
  start: { lng: string; lat: string };
  end: { lng: string; lat: string };
  max_span_m: string;
  tower_radius_m: string;
  max_turn_deg: string;
  road_setback_m: string;
  highway_setback_m: string;
  no_tower_zones: [number, number][][];
  no_cross_zones: [number, number][][];
  algorithm_overrides: Record<string, unknown>;
};

const FIELDS: RoutingFields[] = ["max_span_m", "tower_radius_m", "max_turn_deg", "road_setback_m", "highway_setback_m"];

function stable(value: unknown): string {
  return JSON.stringify(sorted(value));
}

function sorted(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sorted);
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return Object.fromEntries(Object.keys(record).sort().map((key) => [key, sorted(record[key])]));
  }
  return value;
}

function finiteOrBlank(value: string, name: string): string {
  if (value.trim() && !Number.isFinite(Number(value))) throw new Error(`${name}必须是有限数值或留空。`);
  return value;
}

function changedKeys(current: Record<string, unknown> | undefined, defaults: Record<string, unknown> | undefined): Record<string, unknown> {
  const saved: Record<string, unknown> = {};
  const base = defaults ?? {};
  for (const key of Object.keys(current ?? {}).sort()) {
    const value = current?.[key];
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      const nested = changedKeys(value as Record<string, unknown>, base[key] as Record<string, unknown> | undefined);
      if (Object.keys(nested).length) saved[key] = nested;
      continue;
    }
    if (stable(value) !== stable(base[key])) saved[key] = value;
  }
  return saved;
}

function applyOverrides(defaults: Record<string, unknown>, overrides: Record<string, unknown>): Record<string, unknown> {
  const next: Record<string, unknown> = { ...defaults };
  for (const [key, value] of Object.entries(overrides)) {
    const current = defaults[key];
    next[key] = value !== null && typeof value === "object" && !Array.isArray(value)
      ? applyOverrides((current ?? {}) as Record<string, unknown>, value as Record<string, unknown>)
      : value;
  }
  return next;
}

/** Save a routing form even when it is not yet complete enough to submit. */
export function serializeRoutingPlanningConfig(edit: RoutingEdit): RoutingPlanningConfig {
  edit.regions.forEach((region) => validateRoutingPolygon(region.points));
  const rings = (kind: "no_tower" | "no_cross") => edit.regions
    .filter((region) => region.kind === kind)
    .map((region) => region.points.map((point) => [point.x, point.y] as [number, number]));
  return {
    start: { lng: finiteOrBlank(edit.start.lng, "起点经度"), lat: finiteOrBlank(edit.start.lat, "起点纬度") },
    end: { lng: finiteOrBlank(edit.end.lng, "终点经度"), lat: finiteOrBlank(edit.end.lat, "终点纬度") },
    max_span_m: finiteOrBlank(edit.values.max_span_m, "最大档距"),
    tower_radius_m: finiteOrBlank(edit.values.tower_radius_m, "塔基控制半径"),
    max_turn_deg: finiteOrBlank(edit.values.max_turn_deg, "最大允许转角"),
    road_setback_m: finiteOrBlank(edit.values.road_setback_m, "道路控制距离"),
    highway_setback_m: finiteOrBlank(edit.values.highway_setback_m, "高速及匝道控制距离"),
    no_tower_zones: rings("no_tower"),
    no_cross_zones: rings("no_cross"),
    algorithm_overrides: changedKeys(edit.algorithm, edit.algorithmDefaults),
  };
}

/** Restore saved inputs onto the current plugin defaults. Unchanged defaults stay defaults. */
export function restoreRoutingPlanningConfig(edit: RoutingEdit, config: RoutingPlanningConfig): RoutingEdit {
  const values = { ...edit.values };
  for (const name of FIELDS) values[name] = config[name];
  const regions = [
    ...config.no_tower_zones.map((points) => ({ kind: "no_tower" as const, points: points.map(([x, y]) => ({ x, y })) })),
    ...config.no_cross_zones.map((points) => ({ kind: "no_cross" as const, points: points.map(([x, y]) => ({ x, y })) })),
  ];
  return edit.copy({
    start: { ...config.start },
    end: { ...config.end },
    values,
    regions,
    algorithm: applyOverrides({ ...edit.algorithmDefaults }, config.algorithm_overrides),
  });
}
