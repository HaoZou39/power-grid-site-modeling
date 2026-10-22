import { ExclusionZone, simplifyStroke } from "./exclusion_sketch.js";
import type { LocalPoint } from "./site_frame.js";
import { clampFootprintCenter, insideSite, siteFrame } from "./site_frame.js";

export type FieldPolicy = "blocked" | "allowed" | "costly";
export type MountainPolicy = "blocked" | "allowed";

/** A labeled point. `origin` is the only mark the search reads today. */
export type SiteMark = { id: string; kind: string; x: number; y: number };

/** A closed ring. `exclusion` blocks the interior. `feasible` limits the search to the union of these rings. */
export type RegionKind = "exclusion" | "feasible";
export type SiteRegion = { id: string; kind: string; ring: LocalPoint[] };

export type SitePose = { id: string; x: number; y: number; theta: number };

/** Fields copied back from a finished search. Missing keys leave the current edit alone. */
export type ImportedSiteForm = {
  mountain_policy?: unknown;
  field_policy?: unknown;
  field_cost?: unknown;
  exclusion_zones?: unknown;
  feasible_zones?: unknown;
  include_demand?: unknown;
  diagonal_access?: unknown;
  road_setback_m?: unknown;
  origin_x?: unknown;
  origin_y?: unknown;
};

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
  diagonal_access: boolean;
  road_setback_m: number;
  origin_x?: number;
  origin_y?: number;
};

/** One-pose construction/access report. Objectives are recomputed through pose-objectives. */
export type SiteReportBody = Pick<
  SearchConfig,
  | "rect_w_m"
  | "rect_h_m"
  | "field_policy"
  | "mountain_policy"
  | "field_cost"
  | "exclusion_zones"
  | "feasible_zones"
  | "origin_x"
  | "origin_y"
  | "diagonal_access"
> & {
  x: number;
  y: number;
  theta: number;
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
    readonly diagonalAccess = false,
    readonly roadSetbackM = 5,
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

  withDiagonalAccess(diagonalAccess: boolean): SiteEdit<Pose> {
    return this.next({ diagonalAccess });
  }

  withRoadSetback(roadSetbackM: number): SiteEdit<Pose> {
    return this.next({ roadSetbackM });
  }

  /** Copy the fields a finished search saved. Absent fields stay as they are. */
  withImportedSiteForm(form: ImportedSiteForm): SiteEdit<Pose> {
    let next: SiteEdit<Pose> = this;
    if (isMountainPolicy(form.mountain_policy) && isFieldPolicy(form.field_policy) && typeof form.field_cost === "number") {
      next = next.withPolicies(form.mountain_policy, form.field_policy, form.field_cost);
    }
    if (typeof form.include_demand === "boolean") next = next.withIncludeDemand(form.include_demand);
    if (typeof form.diagonal_access === "boolean") next = next.withDiagonalAccess(form.diagonal_access);
    if ("road_setback_m" in form) {
      const setback = Number(form.road_setback_m);
      if (!Number.isFinite(setback) || setback < 0) throw new Error("道路最小退距必须是不小于 0 的数。");
      next = next.withRoadSetback(setback);
    }
    if ("exclusion_zones" in form || "feasible_zones" in form) {
      const exclusions = "exclusion_zones" in form
        ? importedRegions(form.exclusion_zones, "exclusion")
        : this.regions.filter((region) => region.kind === "exclusion");
      const feasible = "feasible_zones" in form
        ? importedRegions(form.feasible_zones, "feasible")
        : this.regions.filter((region) => region.kind === "feasible");
      next = next.next({ regions: [...exclusions, ...feasible] });
    }
    if ("origin_x" in form || "origin_y" in form) {
      next = typeof form.origin_x === "number" && typeof form.origin_y === "number"
        ? next.putOrigin({ x: form.origin_x, y: form.origin_y })
        : next.clearOrigin();
    }
    return next;
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

  /** Restore one erased user region without replacing edits made after the deletion. */
  restoreRegion(region: SiteRegion): SiteEdit<Pose> {
    if (region.kind !== "exclusion" && region.kind !== "feasible") throw new Error(`不认识的范围：${region.kind}`);
    if (region.ring.length < 3) throw new Error(shortRingMessage(region.kind));
    region.ring.forEach(requireInside);
    const id = this.regions.some((item) => item.id === region.id) ? nextZoneId(this.regions) : region.id;
    return this.next({ regions: [...this.regions, { ...region, id, ring: [...region.ring] }] });
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

  /** Move the selected scheme without letting any rotated corner leave the frame. */
  moveSelected(dx: number, dy: number): SiteEdit<Pose> {
    const index = this.selectedIndex;
    if (index < 0) return this;
    const pose = this.poses[index];
    const moved = clampFootprintCenter(
      pose.x + dx,
      pose.y + dy,
      pose.theta,
      this.widthM,
      this.heightM,
    );
    const poses = this.poses.slice();
    poses[index] = { ...pose, x: moved.x, y: moved.y };
    return this.next({ poses });
  }

  updateSelected(update: (pose: Pose) => Pose): SiteEdit<Pose> {
    const index = this.selectedIndex;
    if (index < 0) return this;
    const poses = this.poses.slice();
    poses[index] = update(poses[index]);
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
      diagonal_access: this.diagonalAccess,
      road_setback_m: this.roadSetbackM,
      ...(origin ? { origin_x: origin.x, origin_y: origin.y } : {}),
    };
  }

  /** Build a one-pose construction/access report request. */
  reportRequest(): SiteReportBody | null {
    const pose = this.selected;
    if (!pose) return null;
    const config = this.searchConfig();
    return {
      x: pose.x,
      y: pose.y,
      theta: pose.theta,
      rect_w_m: config.rect_w_m,
      rect_h_m: config.rect_h_m,
      field_policy: config.field_policy,
      mountain_policy: config.mountain_policy,
      field_cost: config.field_cost,
      exclusion_zones: config.exclusion_zones,
      feasible_zones: config.feasible_zones,
      diagonal_access: config.diagonal_access,
      ...(config.origin_x !== undefined
        ? { origin_x: config.origin_x, origin_y: config.origin_y }
        : {}),
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
    diagonalAccess?: boolean;
    roadSetbackM?: number;
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
      patch.diagonalAccess ?? this.diagonalAccess,
      patch.roadSetbackM ?? this.roadSetbackM,
    );
  }
}

function isMountainPolicy(value: unknown): value is MountainPolicy {
  return value === "blocked" || value === "allowed";
}

function isFieldPolicy(value: unknown): value is FieldPolicy {
  return value === "blocked" || value === "allowed" || value === "costly";
}

function importedRegions(value: unknown, kind: RegionKind): SiteRegion[] {
  if (!Array.isArray(value)) throw new Error(kind === "feasible" ? "可行域格式不对。" : "禁区格式不对。");
  return value.map((zone, index) => {
    const points = zone && typeof zone === "object" && "points" in zone ? zone.points : null;
    if (!Array.isArray(points) || points.length < 3) throw new Error(shortRingMessage(kind));
    const ring = points.map((point) => {
      if (!Array.isArray(point) || point.length < 2) throw new Error(shortRingMessage(kind));
      const local = { x: Number(point[0]), y: Number(point[1]) };
      requireInside(local);
      return local;
    });
    return { id: `imported-${kind}-${index + 1}`, kind, ring };
  });
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
