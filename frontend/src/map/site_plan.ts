import { BuildingSize } from "./decision_run.js";
import { SiteEdit, type FieldPolicy, type MountainPolicy, type SitePose } from "./site_edit.js";

/** Closed zones and the next search. Drawn solutions and the unfinished stroke stay out. */
export type SitePlanningConfig = {
  rect_w_m: number;
  rect_h_m: number;
  field_policy: FieldPolicy;
  mountain_policy: MountainPolicy;
  field_cost: number;
  include_demand: boolean;
  diagonal_access: boolean;
  road_setback_m: number;
  water_setback_m: number;
  highway_setback_m: number | null;
  elevation_enabled: boolean;
  elevation_draft: string;
  exclusion_zones: { id: string; points: [number, number][] }[];
  feasible_zones: { id: string; points: [number, number][] }[];
  origin: { x: number; y: number } | null;
};

export type RestoredSitePlan<Pose extends SitePose> = {
  edit: SiteEdit<Pose>;
  rectW: string;
  rectH: string;
};

/**
 * `pending` is the length and width typed for the next search.
 * Solutions already on the map keep a separate size.
 */
export function serializeSitePlanningConfig(
  edit: SiteEdit,
  pending: { rectW: string; rectH: string },
): SitePlanningConfig {
  const size = BuildingSize.parse(pending.rectW, pending.rectH);
  const exclusionZones = [];
  const feasibleZones = [];
  for (const region of edit.regions) {
    if (region.ring.length < 3) throw new Error("未闭合区域不能保存。");
    const points = region.ring.map((point) => [point.x, point.y] as [number, number]);
    const zone = { id: region.id, points };
    if (region.kind === "exclusion") exclusionZones.push(zone);
    else if (region.kind === "feasible") feasibleZones.push(zone);
    else throw new Error(`不认识的范围：${region.kind}`);
  }
  const origins = edit.marks.filter((mark) => mark.kind === "origin");
  if (origins.length > 1) throw new Error("进货原点只能有一个。");
  const origin = origins[0];
  return {
    rect_w_m: size.widthM,
    rect_h_m: size.heightM,
    field_policy: edit.fieldPolicy === "blocked" ? "blocked" : "allowed",
    mountain_policy: edit.mountainPolicy,
    field_cost: 0.5,
    include_demand: false,
    diagonal_access: edit.diagonalAccess,
    road_setback_m: edit.roadSetbackM,
    water_setback_m: edit.waterSetbackM,
    highway_setback_m: edit.highwaySetbackM ?? null,
    elevation_enabled: edit.elevationEnabled,
    elevation_draft: edit.elevationDraft,
    exclusion_zones: exclusionZones,
    feasible_zones: feasibleZones,
    origin: origin ? { x: origin.x, y: origin.y } : null,
  };
}

/** Put a saved plan back on the current map edit without replacing solutions already drawn. */
export function restoreSitePlanningConfig<Pose extends SitePose>(
  displayed: SiteEdit<Pose>,
  config: SitePlanningConfig,
): RestoredSitePlan<Pose> {
  const regions = [
    ...config.exclusion_zones.map((zone) => ({
      id: zone.id,
      kind: "exclusion",
      ring: zone.points.map(([x, y]) => ({ x, y })),
    })),
    ...config.feasible_zones.map((zone) => ({
      id: zone.id,
      kind: "feasible",
      ring: zone.points.map(([x, y]) => ({ x, y })),
    })),
  ];
  const edit = new SiteEdit<Pose>(
    displayed.sceneName,
    displayed.widthM,
    displayed.heightM,
    config.mountain_policy,
    config.field_policy === "blocked" ? "blocked" : "allowed",
    0.5,
    config.origin ? [{ id: "origin", kind: "origin", x: config.origin.x, y: config.origin.y }] : [],
    regions,
    displayed.poses,
    displayed.selectedPoseId,
    [],
    false,
    config.diagonal_access,
    config.road_setback_m,
    config.water_setback_m,
    config.highway_setback_m ?? undefined,
    config.elevation_enabled,
    config.elevation_draft,
  );
  return { edit, rectW: String(config.rect_w_m), rectH: String(config.rect_h_m) };
}
