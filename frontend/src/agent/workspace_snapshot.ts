import type { FieldPolicy, MountainPolicy, SitePose } from "../map/site_edit.js";
import type { LocalPoint } from "../map/site_frame.js";
import { siteFrame } from "../map/site_frame.js";

export type SnapshotPoint = { x: number; y: number };
export type SnapshotRegion = {
  id: string;
  kind: "exclusion" | "feasible";
  ring: SnapshotPoint[];
};
export type SnapshotPose = {
  id: string;
  x: number;
  y: number;
  theta: number;
  objectives?: Record<string, number>;
  feasible?: boolean;
  derived_from?: string;
};

/** Serializable view of one map edit. An unfinished stroke stays on `draft` and is omitted. */
export type WorkspaceSnapshot = {
  scene_name: string;
  site: { width_m: number; height_m: number };
  building: { width_m: number; height_m: number };
  policies: { mountain_policy: MountainPolicy; field_policy: FieldPolicy; field_cost: number };
  origin: SnapshotPoint | null;
  regions: SnapshotRegion[];
  poses: SnapshotPose[];
  selected_pose_id: string | null;
  experiment_id: string | null;
};

/** One click on 「记为我的选择」: the chosen scheme out of every measured scheme on the map. */
export type PreferenceChoice = {
  scene_name: string;
  experiment_id: string | null;
  chosen_id: string;
  candidates: { id: string; objectives: Record<string, number> }[];
};

type MeasuredPose = SitePose & {
  demSoft?: string;
  roadDistance?: string;
  demandDistance?: string;
  roadHaul?: string;
  offroadHaul?: string;
  haulRise?: string;
  feasible?: string;
  derivedFrom?: string;
};

type SnapshotSource = {
  sceneName: string;
  widthM: number;
  heightM: number;
  mountainPolicy: MountainPolicy;
  fieldPolicy: FieldPolicy;
  fieldCost: number;
  origin: LocalPoint | null;
  regions: readonly { id: string; kind: string; ring: readonly LocalPoint[] }[];
  poses: readonly MeasuredPose[];
  selectedPoseId: string | null;
  includeDemand?: boolean;
};

const OBJECTIVE_FIELDS: readonly [string, keyof MeasuredPose][] = [
  ["dem_soft", "demSoft"],
  ["road_distance", "roadDistance"],
  ["demand_distance", "demandDistance"],
  ["road_haul_m", "roadHaul"],
  ["offroad_haul_m", "offroadHaul"],
  ["haul_rise_m", "haulRise"],
];

export function toSnapshot(
  edit: SnapshotSource,
  context: { experimentId?: string | null } = {},
): WorkspaceSnapshot {
  return {
    scene_name: edit.sceneName,
    site: { width_m: siteFrame.widthM, height_m: siteFrame.heightM },
    building: { width_m: edit.widthM, height_m: edit.heightM },
    policies: {
      mountain_policy: edit.mountainPolicy,
      field_policy: edit.fieldPolicy,
      field_cost: edit.fieldCost,
    },
    origin: edit.origin ? { x: edit.origin.x, y: edit.origin.y } : null,
    regions: edit.regions.map((region) => ({
      id: region.id,
      kind: regionKind(region.kind),
      ring: region.ring.map((point) => ({ x: point.x, y: point.y })),
    })),
    poses: edit.poses.map((pose) => {
      const objectives = objectivesOf(pose, edit.includeDemand === true);
      return {
        id: pose.id,
        x: pose.x,
        y: pose.y,
        theta: pose.theta,
        ...(objectives ? { objectives } : {}),
        ...(pose.feasible === "可行" || pose.feasible === "不可行" ? { feasible: pose.feasible === "可行" } : {}),
        ...(pose.derivedFrom ? { derived_from: pose.derivedFrom } : {}),
      };
    }),
    selected_pose_id: edit.selectedPoseId,
    experiment_id: context.experimentId ?? null,
  };
}

export function preferenceChoice(snapshot: WorkspaceSnapshot, chosenId: string): PreferenceChoice {
  const candidates = snapshot.poses.flatMap((pose) => (pose.objectives ? [{ id: pose.id, objectives: pose.objectives }] : []));
  if (candidates.length < 2) throw new Error("至少要有两个带目标值的方案，才能记下选择。");
  if (!candidates.some((candidate) => candidate.id === chosenId)) throw new Error("这个方案还没有目标值，不能记为选择。");
  return { scene_name: snapshot.scene_name, experiment_id: snapshot.experiment_id, chosen_id: chosenId, candidates };
}

/** Stable text used to notice that the map changed after a proposal was made. */
export function snapshotStamp(snapshot: WorkspaceSnapshot): string {
  return JSON.stringify(snapshot);
}

function regionKind(kind: string): "exclusion" | "feasible" {
  if (kind === "exclusion" || kind === "feasible") return kind;
  throw new Error(`不认识的范围：${kind}`);
}

function objectivesOf(pose: MeasuredPose, includeDemand: boolean): Record<string, number> | undefined {
  const objectives: Record<string, number> = {};
  for (const [key, field] of OBJECTIVE_FIELDS) {
    if (key === "demand_distance" && !includeDemand) continue;
    const raw = pose[field];
    if (typeof raw !== "string" || raw === "") continue;
    const value = Number(raw);
    if (Number.isFinite(value)) objectives[key] = value;
  }
  return Object.keys(objectives).length > 0 ? objectives : undefined;
}
