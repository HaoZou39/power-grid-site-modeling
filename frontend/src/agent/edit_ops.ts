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
  "refine_pose",
] as const;

/** Keep equal to `RefinePose.half_width_m` in `agent/workspace.py`. Local meters. */
export const REFINE_HALF_WIDTH_M = { min: 30, max: 400, default: 150 } as const;

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
  | { kind: "run_search"; plugin_id: "site.guided_search" }
  | { kind: "refine_pose"; pose_id: string; half_width_m?: number | null };

type SearchOp = Extract<EditOp, { kind: "run_search" | "refine_pose" }>;

/** `refine` is the scheme to search around and the half width of its square, in meters. */
export type AppliedOps<Pose extends SitePose> = {
  edit: SiteEdit<Pose>;
  runSearch: boolean;
  refine: { poseId: string; halfWidthM: number } | null;
};

export type ProposalPreview = {
  regions: { id: string; kind: "exclusion" | "feasible"; ring: LocalPoint[] }[];
  poses: { id: string; x: number; y: number; theta: number }[];
  origin: LocalPoint | null;
};

const MOUNTAIN: readonly MountainPolicy[] = ["blocked", "allowed"];
const FIELD: readonly FieldPolicy[] = ["blocked", "allowed", "costly"];

/** Apply a confirmed proposal. `run_search` and `refine_pose` are reported and do not submit a job. */
export function applyOps<Pose extends SitePose>(edit: SiteEdit<Pose>, ops: readonly EditOp[]): AppliedOps<Pose> {
  let next = edit;
  let runSearch = false;
  let refine: AppliedOps<Pose>["refine"] = null;
  for (const op of ops) {
    if (op.kind === "run_search") {
      if (op.plugin_id !== "site.guided_search") throw new Error("目前只能提出 site.guided_search 搜索。");
      runSearch = true;
      continue;
    }
    if (op.kind === "refine_pose") {
      if (refine) throw new Error("一次只能局部优化一个方案。");
      refine = { poseId: op.pose_id, halfWidthM: refineHalfWidth(op.half_width_m) };
      continue;
    }
    next = applyOne(next, op);
  }
  if (runSearch && refine) throw new Error("重新搜索和局部优化不能放在同一个提案里。");
  if (refine && !next.poses.some((pose) => pose.id === refine?.poseId)) throw new Error(`没有这个方案：${refine.poseId}`);
  return { edit: next, runSearch, refine };
}

/** Lines for the confirm card. Searches do not change the edit, so they are read from `ops`. */
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
  if (ops.some((op) => op.kind === "run_search")) lines.push("开始一次引导式多目标搜索");
  for (const op of ops) {
    if (op.kind !== "refine_pose") continue;
    const index = after.poses.findIndex((pose) => pose.id === op.pose_id);
    const side = 2 * refineHalfWidth(op.half_width_m);
    lines.push(`在方案 #${index + 1} 周围 ${num(side)}×${num(side)} m 内局部优化，新方案加到地图上，原方案保留`);
  }
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

function refineHalfWidth(value: number | null | undefined): number {
  if (value == null) return REFINE_HALF_WIDTH_M.default;
  if (!Number.isFinite(value) || value < REFINE_HALF_WIDTH_M.min || value > REFINE_HALF_WIDTH_M.max) {
    throw new Error(`局部优化的半宽要在 ${REFINE_HALF_WIDTH_M.min} 到 ${REFINE_HALF_WIDTH_M.max} 米之间。`);
  }
  return value;
}

function applyOne<Pose extends SitePose>(edit: SiteEdit<Pose>, op: Exclude<EditOp, SearchOp>): SiteEdit<Pose> {
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
