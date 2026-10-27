import type { CheckSchema as JsonSchema } from "../config_check.js";
import type { LngLat, LocalPoint, SiteFrame } from "../map/site_frame.js";

export type RegionKind = "no_tower" | "no_cross";
export type RoutingRegion = { kind: RegionKind; points: LocalPoint[] };
export type ConnectionInput = { lng: string; lat: string };
export type RoutingFields = "max_span_m" | "tower_radius_m" | "max_turn_deg" | "road_setback_m" | "highway_setback_m";
export const ROUTING_FIELD_LABELS: Record<RoutingFields, string> = { max_span_m: "最大档距（m）", tower_radius_m: "塔基控制半径（m）",
  max_turn_deg: "最大允许转角（°）", road_setback_m: "普通道路控制距离（m）", highway_setback_m: "高速及匝道控制距离（m）" };
export const ROUTING_ALGORITHM_LABELS: Record<string, string> = { seed: "随机种子", popsize: "种群数量", max_evaluations: "评价次数预算",
  evolution_backend: "演化后端", evaluation_backend: "评价后端", devices: "计算设备（逗号分隔）",
  evaluation_batch_size: "评价批次大小", gpu_memory_budget_mib: "每卡显存预算（MiB）", context_cache_mib: "上下文缓存上限（MiB）",
  reference_count: "参考曲线数量", mutation_scale: "移动尺度比例", expansion_interval: "塔数扩展周期（代）",
  expansion_step: "每次扩展塔数", repair_attempts: "塔位修复尝试次数", navigation_step_m: "初始化导航步长（m）" };

function number(value: string, name: string): number {
  if (!value.trim() || !Number.isFinite(Number(value))) throw new Error(`${name}必须填写有限数值。`);
  return Number(value);
}

export class RoutingEdit {
  start: ConnectionInput = { lng: "", lat: "" };
  end: ConnectionInput = { lng: "", lat: "" };
  values: Record<RoutingFields, string> = { max_span_m: "", tower_radius_m: "", max_turn_deg: "", road_setback_m: "", highway_setback_m: "" };
  regions: RoutingRegion[] = [];
  algorithm: Record<string, unknown> = {};
  algorithmDefaults: Record<string, unknown> = {};
  algorithmSchema: JsonSchema = {};

  copy(patch: Partial<RoutingEdit>): RoutingEdit { return Object.assign(new RoutingEdit(), this, patch); }

  get generationLimit(): number | null {
    const budget = Number(this.algorithm.max_evaluations), population = Number(this.algorithm.popsize);
    return Number.isSafeInteger(budget) && budget > 0 && Number.isSafeInteger(population) && population >= 4
      ? Math.ceil(budget / population) : null;
  }

  resetAlgorithm(): RoutingEdit { return this.copy({ algorithm: { ...this.algorithmDefaults } }); }

  defaults(schema: JsonSchema): RoutingEdit {
    const properties = schema.properties ?? {};
    const values = { ...this.values };
    for (const name of ["road_setback_m", "highway_setback_m"] as const) {
      if (!values[name] && typeof properties[name]?.default === "number") values[name] = String(properties[name].default);
    }
    const algorithmDefaults = properties.algorithm?.default as Record<string, unknown>;
    return this.copy({ values, algorithmDefaults, algorithmSchema: properties.algorithm ?? {},
      algorithm: { ...algorithmDefaults, ...this.algorithm } });
  }

  connection(which: "start" | "end", input: ConnectionInput): RoutingEdit { return this.copy({ [which]: input }); }

  localPoint(which: "start" | "end", frame: SiteFrame): LocalPoint | null {
    const value = this[which];
    if (!value.lng.trim() || !value.lat.trim()) return null;
    const lng = Number(value.lng), lat = Number(value.lat);
    if (!Number.isFinite(lng) || !Number.isFinite(lat) || Math.abs(lng) > 180 || Math.abs(lat) > 90) return null;
    const point = frame.lngLatToLocal({ lng, lat });
    return Number.isFinite(point.x) && Number.isFinite(point.y) && frame.inside(point) ? point : null;
  }

  picked(which: "start" | "end", point: LocalPoint, frame: SiteFrame): RoutingEdit {
    if (!frame.inside(point)) throw new Error("接入点必须位于当前场景内。");
    const { lng, lat } = frame.localToLngLat(point);
    return this.connection(which, { lng: lng.toFixed(9), lat: lat.toFixed(9) });
  }

  task(sceneName: string, experimentName: string, frame: SiteFrame): Record<string, unknown> {
    if (!this.localPoint("start", frame) || !this.localPoint("end", frame)) throw new Error("请为起终点填写场景内有效的经纬度，或在地图点选。");
    const start: LngLat = { lng: Number(this.start.lng), lat: Number(this.start.lat) };
    const end: LngLat = { lng: Number(this.end.lng), lat: Number(this.end.lat) };
    if (start.lng === end.lng && start.lat === end.lat) throw new Error("起终点不能重合。");
    const values = Object.fromEntries(Object.entries(this.values).map(([name, value]) => [name, number(value, ROUTING_FIELD_LABELS[name as RoutingFields])]));
    if (values.max_span_m <= 0 || values.tower_radius_m <= 0) throw new Error("最大档距和塔基控制半径必须大于零。");
    if (values.max_turn_deg < 0 || values.max_turn_deg > 180) throw new Error("最大允许转角须在 0–180° 内。");
    if (values.road_setback_m < 0 || values.highway_setback_m < 0) throw new Error("道路控制距离不能小于零。");
    if (!Object.keys(this.algorithm).length) throw new Error("算法默认配置尚未读取完成。");
    const rings = (kind: RegionKind) => this.regions.filter((item) => item.kind === kind).map((item) => item.points.map(({ x, y }) => [x, y]));
    const algorithm = Object.fromEntries(Object.entries(this.algorithm).map(([name, value]) => {
      const original = this.algorithmDefaults[name];
      if (typeof value !== "string" || typeof original === "string") return [name, value];
      if (Array.isArray(original)) return [name, value.split(",").map((item) => item.trim())];
      return [name, number(value, ROUTING_ALGORITHM_LABELS[name] ?? name)];
    }));
    return { scene_name: sceneName, experiment_name: experimentName, start, end, ...values,
      algorithm, no_tower_zones: rings("no_tower"), no_cross_zones: rings("no_cross") };
  }

  static fromTask(task: Record<string, unknown>): RoutingEdit {
    const edit = new RoutingEdit();
    for (const which of ["start", "end"] as const) {
      const point = task[which] as LngLat;
      edit[which] = { lng: String(point.lng), lat: String(point.lat) };
    }
    for (const name of Object.keys(edit.values) as RoutingFields[]) edit.values[name] = String(task[name]);
    edit.algorithm = { ...task.algorithm as Record<string, unknown> };
    edit.algorithmDefaults = { ...edit.algorithm };
    for (const kind of ["no_tower", "no_cross"] as const) {
      const rings = task[`${kind}_zones`] as number[][][] | undefined;
      for (const ring of rings ?? []) edit.regions.push({ kind, points: ring.map(([x, y]) => ({ x, y })) });
    }
    return edit;
  }
}
