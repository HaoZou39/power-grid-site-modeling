import type { FieldPolicy, MountainPolicy, RegionKind, SiteEdit, SitePose } from "../map/site_edit.js";
import { insideSite } from "../map/site_frame.js";
import type { LocalPoint } from "../map/site_frame.js";

/** Keep this list equal to `edit_op_kinds()` in `agent/workspace.py`. */
export const EDIT_OP_KINDS = [
  "set_building",
  "set_policies",
  "set_origin",
  "clear_origin",
  "add_region",
  "remove_region",
  "update_pose",
  "select_pose",
  "run_search",
] as const;

export type EditOp =
  | { kind: "set_building"; width_m: number; height_m: number }
  | {
    kind: "set_policies";
    mountain_policy?: MountainPolicy | null;
    field_policy?: FieldPolicy | null;
    field_cost?: number | null;
  }
  | { kind: "set_origin"; x: number; y: number }
  | { kind: "clear_origin" }
  | { kind: "add_region"; region_kind: RegionKind; ring: LocalPoint[] }
  | { kind: "remove_region"; region_id: string }
  | { kind: "update_pose"; pose_id: string; x?: number | null; y?: number | null; theta?: number | null }
  | { kind: "select_pose"; pose_id: string }
  | { kind: "run_search"; plugin_id: "site.nsga2" };

export type AppliedOps<Pose extends SitePose> = { edit: SiteEdit<Pose>; runSearch: boolean };

export type ProposalPreview = {
  regions: { id: string; kind: "exclusion" | "feasible"; ring: LocalPoint[] }[];
  poses: { id: string; x: number; y: number; theta: number }[];
  origin: LocalPoint | null;
};

const MOUNTAIN: readonly MountainPolicy[] = ["blocked", "allowed"];
const FIELD: readonly FieldPolicy[] = ["blocked", "allowed", "costly"];

/** Apply a confirmed proposal. `run_search` is reported and does not submit a job. */
export function applyOps<Pose extends SitePose>(edit: SiteEdit<Pose>, ops: readonly EditOp[]): AppliedOps<Pose> {
  let next = edit;
  let runSearch = false;
  for (const op of ops) {
    if (op.kind === "run_search") {
      if (op.plugin_id !== "site.nsga2") throw new Error("目前只能提出 site.nsga2 搜索。");
      runSearch = true;
      continue;
    }
    next = applyOne(next, op);
  }
  return { edit: next, runSearch };
}

/** Lines for the confirm card. `run_search` does not change the edit, so it is read from `ops`. */
export function describeOps<Pose extends SitePose>(
  before: SiteEdit<Pose>,
  after: SiteEdit<Pose>,
  ops: readonly EditOp[] = [],
): string[] {
  const lines: string[] = [];
  if (before.widthM !== after.widthM || before.heightM !== after.heightM) {
    lines.push(`建筑 ${num(before.widthM)}×${num(before.heightM)} → ${num(after.widthM)}×${num(after.heightM)}`);
  }
  if (before.mountainPolicy !== after.mountainPolicy) {
    lines.push(`山体 ${policyLabel(before.mountainPolicy)} → ${policyLabel(after.mountainPolicy)}`);
  }
  if (before.fieldPolicy !== after.fieldPolicy) {
    lines.push(`农田 ${policyLabel(before.fieldPolicy)} → ${policyLabel(after.fieldPolicy)}`);
  }
  if (before.fieldCost !== after.fieldCost) {
    lines.push(`农田代价 ${num(before.fieldCost)} → ${num(after.fieldCost)}`);
  }
  lines.push(...originLines(before.origin, after.origin));
  // A removed id can be reused by the next added ring, so identity is id, kind and ring.
  const key = (region: { id: string; kind: string; ring: readonly LocalPoint[] }) =>
    JSON.stringify([region.id, region.kind, region.ring]);
  const kept = (region: SiteEdit<Pose>["regions"][number], others: SiteEdit<Pose>["regions"]) =>
    others.some((item) => key(item) === key(region));
  for (const region of before.regions) {
    if (!kept(region, after.regions)) lines.push(`删除范围 ${region.id}`);
  }
  for (const region of after.regions) {
    if (kept(region, before.regions)) continue;
    const label = region.kind === "feasible" ? "可行域" : "禁区";
    lines.push(`新增${label} ${region.ring.length} 点`);
  }
  after.poses.forEach((pose, index) => {
    const previous = before.poses.find((item) => item.id === pose.id);
    if (!previous) return;
    if (previous.x !== pose.x) lines.push(`方案 #${index + 1} x ${num(previous.x)}→${num(pose.x)}`);
    if (previous.y !== pose.y) lines.push(`方案 #${index + 1} y ${num(previous.y)}→${num(pose.y)}`);
    if (previous.theta !== pose.theta) lines.push(`方案 #${index + 1} 朝向 ${num(previous.theta)}→${num(pose.theta)}`);
  });
  if (before.selectedPoseId !== after.selectedPoseId && after.selectedPoseId) {
    const index = after.poses.findIndex((pose) => pose.id === after.selectedPoseId);
    if (index >= 0) lines.push(`当前方案 #${index + 1}`);
  }
  if (ops.some((op) => op.kind === "run_search")) lines.push("开始一次 NSGA-II 搜索");
  return lines;
}

/** Geometry that would appear only after confirm. Removals stay in the text diff. */
export function proposalPreview<Pose extends SitePose>(before: SiteEdit<Pose>, after: SiteEdit<Pose>): ProposalPreview {
  const previous = new Map(before.regions.map((region) => [region.id, JSON.stringify(region.ring)]));
  return {
    regions: after.regions.flatMap((region) => {
      if (region.kind !== "exclusion" && region.kind !== "feasible") return [];
      if (previous.get(region.id) === JSON.stringify(region.ring)) return [];
      return [{ id: region.id, kind: region.kind, ring: region.ring.map((point) => ({ ...point })) }];
    }),
    poses: after.poses.filter((pose) => {
      const earlier = before.poses.find((item) => item.id === pose.id);
      return !earlier || earlier.x !== pose.x || earlier.y !== pose.y || earlier.theta !== pose.theta;
    }).map((pose) => ({ id: pose.id, x: pose.x, y: pose.y, theta: pose.theta })),
    origin: samePoint(before.origin, after.origin) ? null : after.origin,
  };
}

function applyOne<Pose extends SitePose>(edit: SiteEdit<Pose>, op: Exclude<EditOp, { kind: "run_search" }>): SiteEdit<Pose> {
  switch (op.kind) {
    case "set_building":
      if (!(op.width_m > 0) || !(op.height_m > 0)) throw new Error("建筑宽和高必须大于 0。");
      return edit.withBuilding(op.width_m, op.height_m);
    case "set_policies":
      return edit.withPolicies(
        policy(MOUNTAIN, op.mountain_policy, edit.mountainPolicy, "山体策略"),
        policy(FIELD, op.field_policy, edit.fieldPolicy, "农田策略"),
        fieldCost(op.field_cost, edit.fieldCost),
      );
    case "set_origin":
      return edit.putOrigin({ x: op.x, y: op.y });
    case "clear_origin":
      return edit.clearOrigin();
    case "add_region":
      return edit.addRegion(op.region_kind, op.ring);
    case "remove_region":
      if (!edit.regions.some((region) => region.id === op.region_id)) throw new Error(`没有这个范围：${op.region_id}`);
      return edit.removeRegion(op.region_id);
    case "update_pose":
      return updatePose(edit, op);
    case "select_pose":
      if (!edit.poses.some((pose) => pose.id === op.pose_id)) throw new Error(`没有这个方案：${op.pose_id}`);
      return edit.selectPose(op.pose_id);
    default: {
      const unknown: never = op;
      throw new Error(`不认识的操作：${(unknown as { kind?: string }).kind ?? ""}`);
    }
  }
}

function updatePose<Pose extends SitePose>(
  edit: SiteEdit<Pose>,
  op: Extract<EditOp, { kind: "update_pose" }>,
): SiteEdit<Pose> {
  const current = edit.poses.find((pose) => pose.id === op.pose_id);
  if (!current) throw new Error(`没有这个方案：${op.pose_id}`);
  if (op.x == null && op.y == null && op.theta == null) throw new Error("修改方案至少要改一项。");
  const x = op.x ?? current.x;
  const y = op.y ?? current.y;
  const theta = op.theta ?? current.theta;
  if (!insideSite({ x, y })) throw new Error("这个点不在选址范围框内。");
  if (!Number.isFinite(theta)) throw new Error("朝向必须是有限数值。");
  return edit.withPoses(edit.poses.map((pose) => pose.id === op.pose_id ? { ...pose, x, y, theta } : pose));
}

function policy<T extends string>(allowed: readonly T[], value: T | null | undefined, current: T, label: string): T {
  if (value == null) return current;
  if (!allowed.includes(value)) throw new Error(`不认识的${label}：${value}`);
  return value;
}

function fieldCost(value: number | null | undefined, current: number): number {
  if (value == null) return current;
  if (!Number.isFinite(value) || value <= 0 || value > 1) throw new Error("农田代价系数必须在 0 到 1 之间。");
  return value;
}

function originLines(before: LocalPoint | null, after: LocalPoint | null): string[] {
  if (samePoint(before, after)) return [];
  if (!after) return ["清除进货原点"];
  if (!before) return [`进货原点 (${num(after.x)}, ${num(after.y)})`];
  return [`进货原点 (${num(before.x)}, ${num(before.y)}) → (${num(after.x)}, ${num(after.y)})`];
}

function samePoint(left: LocalPoint | null, right: LocalPoint | null): boolean {
  if (!left || !right) return left === right;
  return left.x === right.x && left.y === right.y;
}

function policyLabel(value: string): string {
  if (value === "blocked") return "不可建设";
  if (value === "costly") return "计入成本";
  return "按坡度判断";
}

function num(value: number): string {
  return String(value);
}
