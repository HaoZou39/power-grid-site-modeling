import type { SearchConfig } from "./site_edit.js";

type FeasibilityRequest = Pick<
  SearchConfig,
  "mountain_policy" | "field_policy" | "field_cost" | "exclusion_zones" | "feasible_zones" | "road_setback_m"
>;

export function feasibilityRequest(config: SearchConfig): FeasibilityRequest {
  return {
    mountain_policy: config.mountain_policy,
    field_policy: config.field_policy,
    field_cost: config.field_cost,
    exclusion_zones: config.exclusion_zones,
    feasible_zones: config.feasible_zones,
    road_setback_m: config.road_setback_m,
  };
}

/** Prevent an older asynchronous image response from replacing a newer one. */
export class LatestOverlayRequest {
  private serial = 0;

  begin(): number {
    this.serial += 1;
    return this.serial;
  }

  isCurrent(token: number): boolean {
    return token === this.serial;
  }
}

export function replaceOverlayObjectUrl(
  current: string | null,
  next: string | null,
  revoke: (url: string) => void,
): string | null {
  if (current && current !== next) revoke(current);
  return next;
}
