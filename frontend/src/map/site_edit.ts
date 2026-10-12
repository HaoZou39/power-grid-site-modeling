import { ExclusionZone, simplifyStroke } from "./exclusion_sketch.js";
import type { LocalPoint } from "./site_frame.js";
import { insideSite, siteFrame } from "./site_frame.js";

export type FieldPolicy = "blocked" | "allowed" | "costly";
export type MountainPolicy = "blocked" | "allowed";

/** A labeled point. `origin` is the only mark the search reads today. */
export type SiteMark = { id: string; kind: string; x: number; y: number };

/** A closed ring. `exclusion` blocks the interior. `feasible` limits the search to the union of these rings. */
export type RegionKind = "exclusion" | "feasible";
export type SiteRegion = { id: string; kind: string; ring: LocalPoint[] };

export type SitePose = { id: string; x: number; y: number; theta: number };

/** Fields the existing guided-search job already accepts. Kinds do not leave this file. */
export type SearchConfig = {
  scene_name: string;
  rect_w_m: number;
  rect_h_m: number;
  field_policy: FieldPolicy;
  mountain_policy: MountainPolicy;
  field_cost: number;
  exclusion_zones: { points: [number, number][] }[];
  feasible_zones: { points: [number, number][] }[];
  include_demand: boolean;
  origin_x?: number;
  origin_y?: number;
};

/** Fields the existing site report already accepts. Exclusion rings are not included. */
export type SiteReportBody = {
  x: number;
  y: number;
  theta: number;
  rect_w_m: number;
  rect_h_m: number;
  origin_x?: number;
  origin_y?: number;
};

const CLOSE_DISTANCE_M = 8;
const STROKE_TOLERANCE_M = 4;

/**
 * One map edit. Gestures change this object. Search and the site report are the only sends.
 * An unfinished stroke stays on `draft` and is not sent.
 */
export class SiteEdit<Pose extends SitePose = SitePose> {
  constructor(
    readonly sceneName = "cangnan",
    readonly widthM = 77,
    readonly heightM = 51.5,
    readonly mountainPolicy: MountainPolicy = "allowed",
    readonly fieldPolicy: FieldPolicy = "allowed",
    readonly fieldCost = 0.5,
    readonly marks: readonly SiteMark[] = [],
    readonly regions: readonly SiteRegion[] = [],
    readonly poses: readonly Pose[] = [],
    readonly selectedPoseId: string | null = null,
    readonly draft: readonly LocalPoint[] = [],
    readonly includeDemand = false,
  ) {}

  get selected(): Pose | null {
    return this.poses.find((pose) => pose.id === this.selectedPoseId) ?? null;
  }

  get selectedIndex(): number {
    return this.poses.findIndex((pose) => pose.id === this.selectedPoseId);
  }

  get origin(): LocalPoint | null {
    const mark = this.marks.find((item) => item.kind === "origin");
    return mark ? { x: mark.x, y: mark.y } : null;
  }

  /** Closed rings the map draws. Red exclusions and green feasible areas share this list. */
  get zones(): ExclusionZone[] {
    return this.regions.flatMap((region) => {
      if (region.kind !== "exclusion" && region.kind !== "feasible") return [];
      return [new ExclusionZone(region.id, region.ring, region.kind)];
    });
  }

  withScene(sceneName: string): SiteEdit<Pose> {
    return this.next({ sceneName });
  }

  withBuilding(widthM: number, heightM: number): SiteEdit<Pose> {
    return this.next({ widthM, heightM });
  }

  withPolicies(mountainPolicy: MountainPolicy, fieldPolicy: FieldPolicy, fieldCost: number): SiteEdit<Pose> {
    return this.next({ mountainPolicy, fieldPolicy, fieldCost });
  }

  withIncludeDemand(includeDemand: boolean): SiteEdit<Pose> {
    return this.next({ includeDemand });
  }

  /** Replace the single logistics origin. A point outside the frame is refused. */
  putOrigin(point: LocalPoint): SiteEdit<Pose> {
    requireInside(point);
    const marks = this.marks.filter((mark) => mark.kind !== "origin");
    return this.next({ marks: [...marks, { id: "origin", kind: "origin", x: point.x, y: point.y }] });
  }

  /** Drop the logistics origin. Search then skips the along-road haul objective. */
  clearOrigin(): SiteEdit<Pose> {
    return this.next({ marks: this.marks.filter((mark) => mark.kind !== "origin") });
  }

  /** Append one no-build ring. Picked land-use patches use this. */
  addExclusion(ring: readonly LocalPoint[]): SiteEdit<Pose> {
    return this.addRegion("exclusion", ring);
  }

  /** Append one ring the search must stay inside. */
  addFeasible(ring: readonly LocalPoint[]): SiteEdit<Pose> {
    return this.addRegion("feasible", ring);
  }

  /** Two clicks are the diagonal. Local x increases east and y increases south. */
  addRectangle(kind: RegionKind, first: LocalPoint, second: LocalPoint): SiteEdit<Pose> {
    const width = Math.abs(first.x - second.x);
    const height = Math.abs(first.y - second.y);
    if (width < 1 || height < 1) throw new Error("方框的宽和高至少要有 1 米。");
    return this.addRegion(kind, rectangleCorners(first, second)).next({ draft: [] });
  }

  addRegion(kind: RegionKind, ring: readonly LocalPoint[]): SiteEdit<Pose> {
    if (ring.length < 3) throw new Error(shortRingMessage(kind));
    ring.forEach(requireInside);
    const region: SiteRegion = { id: nextZoneId(this.regions), kind, ring: [...ring] };
    return this.next({ regions: [...this.regions, region] });
  }

  removeRegion(id: string): SiteEdit<Pose> {
    return this.next({ regions: this.regions.filter((region) => region.id !== id) });
  }

  addDraftPoint(point: LocalPoint, kind: RegionKind = "exclusion"): SiteEdit<Pose> {
    if (this.draft.length >= 3 && distance(point, this.draft[0]) <= CLOSE_DISTANCE_M) return this.closeDraft(kind);
    return this.next({ draft: [...this.draft, point] });
  }

  replaceDraft(points: readonly LocalPoint[]): SiteEdit<Pose> {
    return this.next({ draft: points });
  }

  undoPoint(): SiteEdit<Pose> {
    return this.next({ draft: this.draft.slice(0, -1) });
  }

  cancelDraft(): SiteEdit<Pose> {
    return this.next({ draft: [] });
  }

  closeDraft(kind: RegionKind = "exclusion"): SiteEdit<Pose> {
    if (this.draft.length < 3) throw new Error(shortRingMessage(kind));
    return this.addRegion(kind, this.draft).next({ draft: [] });
  }

  /** Simplify a freehand loop and store it. The stroke itself is not sent. */
  finishStroke(points: readonly LocalPoint[], kind: RegionKind = "exclusion"): SiteEdit<Pose> {
    const ring = simplifyStroke(points, STROKE_TOLERANCE_M);
    if (ring.length < 3) throw new Error(openStrokeMessage(kind));
    return this.addRegion(kind, ring).next({ draft: [] });
  }

  withPoses(poses: readonly Pose[]): SiteEdit<Pose> {
    const selectedPoseId = poses.some((pose) => pose.id === this.selectedPoseId)
      ? this.selectedPoseId
      : poses[0]?.id ?? null;
    return this.next({ poses, selectedPoseId });
  }

  clearPoses(): SiteEdit<Pose> {
    return this.next({ poses: [], selectedPoseId: null });
  }

  selectPose(id: string): SiteEdit<Pose> {
    if (!this.poses.some((pose) => pose.id === id)) return this;
    return this.next({ selectedPoseId: id });
  }

  stepPose(delta: number): SiteEdit<Pose> {
    if (this.poses.length === 0) return this;
    const index = this.selectedIndex < 0 ? 0 : this.selectedIndex;
    const span = this.poses.length;
    const next = ((index + delta) % span + span) % span;
    return this.next({ selectedPoseId: this.poses[next].id });
  }

  /** Move the selected scheme. Heading stays. The center stays inside the frame. */
  moveSelected(dx: number, dy: number): SiteEdit<Pose> {
    const index = this.selectedIndex;
    if (index < 0) return this;
    const pose = this.poses[index];
    const moved = clampSitePoint(pose.x + dx, pose.y + dy);
    const poses = this.poses.slice();
    poses[index] = { ...pose, x: moved.x, y: moved.y };
    return this.next({ poses });
  }

  /** The existing optimization payload. Unknown kinds raise instead of being dropped. */
  searchConfig(): SearchConfig {
    const { exclusions, feasible, origin } = this.accepted();
    return {
      scene_name: this.sceneName,
      rect_w_m: this.widthM,
      rect_h_m: this.heightM,
      field_policy: this.fieldPolicy,
      mountain_policy: this.mountainPolicy,
      field_cost: this.fieldCost,
      exclusion_zones: exclusions,
      feasible_zones: feasible,
      include_demand: this.includeDemand,
      ...(origin ? { origin_x: origin.x, origin_y: origin.y } : {}),
    };
  }

  /** The existing one-pose report. Exclusion rings stay out of this request. */
  reportRequest(): SiteReportBody | null {
    const pose = this.selected;
    if (!pose) return null;
    const { origin } = this.accepted();
    return {
      x: pose.x,
      y: pose.y,
      theta: pose.theta,
      rect_w_m: this.widthM,
      rect_h_m: this.heightM,
      ...(origin ? { origin_x: origin.x, origin_y: origin.y } : {}),
    };
  }

  private accepted(): {
    exclusions: { points: [number, number][] }[];
    feasible: { points: [number, number][] }[];
    origin: LocalPoint | null;
  } {
    const origins = this.marks.filter((mark) => {
      if (mark.kind !== "origin") throw new Error(`不认识的标记：${mark.kind}`);
      return true;
    });
    if (origins.length > 1) throw new Error("进货原点只能有一个。");
    const exclusions: { points: [number, number][] }[] = [];
    const feasible: { points: [number, number][] }[] = [];
    for (const region of this.regions) {
      if (region.ring.length < 3) throw new Error(shortRingMessage(region.kind === "feasible" ? "feasible" : "exclusion"));
      const ring = { points: region.ring.map((point) => [point.x, point.y] as [number, number]) };
      if (region.kind === "exclusion") exclusions.push(ring);
      else if (region.kind === "feasible") feasible.push(ring);
      else throw new Error(`不认识的范围：${region.kind}`);
    }
    const mark = origins[0];
    return { exclusions, feasible, origin: mark ? { x: mark.x, y: mark.y } : null };
  }

  private next(patch: {
    sceneName?: string;
    widthM?: number;
    heightM?: number;
    mountainPolicy?: MountainPolicy;
    fieldPolicy?: FieldPolicy;
    fieldCost?: number;
    marks?: readonly SiteMark[];
    regions?: readonly SiteRegion[];
    poses?: readonly Pose[];
    selectedPoseId?: string | null;
    draft?: readonly LocalPoint[];
    includeDemand?: boolean;
  }): SiteEdit<Pose> {
    return new SiteEdit(
      patch.sceneName ?? this.sceneName,
      patch.widthM ?? this.widthM,
      patch.heightM ?? this.heightM,
      patch.mountainPolicy ?? this.mountainPolicy,
      patch.fieldPolicy ?? this.fieldPolicy,
      patch.fieldCost ?? this.fieldCost,
      patch.marks ?? this.marks,
      patch.regions ?? this.regions,
      patch.poses ?? this.poses,
      patch.selectedPoseId === undefined ? this.selectedPoseId : patch.selectedPoseId,
      patch.draft ?? this.draft,
      patch.includeDemand ?? this.includeDemand,
    );
  }
}

/** Keep a moved center inside the 1 m site frame. */
export function clampSitePoint(x: number, y: number): LocalPoint {
  return {
    x: Math.min(siteFrame.widthM, Math.max(0, x)),
    y: Math.min(siteFrame.heightM, Math.max(0, y)),
  };
}

/** Axis-aligned ring from either diagonal order. The first corner is the north-west. */
export function rectangleCorners(first: LocalPoint, second: LocalPoint): LocalPoint[] {
  const left = Math.min(first.x, second.x);
  const right = Math.max(first.x, second.x);
  const top = Math.min(first.y, second.y);
  const bottom = Math.max(first.y, second.y);
  return [
    { x: left, y: top },
    { x: right, y: top },
    { x: right, y: bottom },
    { x: left, y: bottom },
  ];
}

function shortRingMessage(kind: RegionKind): string {
  return kind === "feasible" ? "可行域至少需要三个顶点。" : "禁行区至少需要三个顶点。";
}

function openStrokeMessage(kind: RegionKind): string {
  return kind === "feasible" ? "请沿可行域画一圈，松手后会自动闭合。" : "请沿禁区画一圈，松手后会自动闭合。";
}

function nextZoneId(regions: readonly SiteRegion[]): string {
  const used = new Set(regions.map((region) => region.id));
  let index = regions.length + 1;
  while (used.has(`zone-${index}`)) index += 1;
  return `zone-${index}`;
}

function requireInside(point: LocalPoint): void {
  if (!insideSite(point)) throw new Error("这个点不在选址范围框内。");
}

function distance(left: LocalPoint, right: LocalPoint): number {
  return Math.hypot(left.x - right.x, left.y - right.y);
}
