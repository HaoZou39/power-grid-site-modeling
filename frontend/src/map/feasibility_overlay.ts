import type { SearchConfig } from "./site_edit.js";

type FeasibilityRequest = Pick<
  SearchConfig,
  "mountain_policy" | "field_policy" | "field_cost" | "exclusion_zones" | "feasible_zones" | "road_setback_m" | "water_setback_m" | "highway_setback_m"
>;

export function feasibilityRequest(config: SearchConfig): FeasibilityRequest {
  return {
    mountain_policy: config.mountain_policy,
    field_policy: config.field_policy,
    field_cost: config.field_cost,
    exclusion_zones: config.exclusion_zones,
    feasible_zones: config.feasible_zones,
    road_setback_m: config.road_setback_m,
    water_setback_m: config.water_setback_m,
    ...(config.highway_setback_m !== undefined ? { highway_setback_m: config.highway_setback_m } : {}),
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

/** Same cutoff as the backend distance-field cache. Larger grids stay on demand. */
export const FEASIBILITY_PRELOAD_MAX_CELLS = 4_000_000;

export function scheduleIdle(task: () => void, timeoutMs = 2000): () => void {
  const request = window.requestIdleCallback;
  if (typeof request === "function") {
    const id = request(() => task(), { timeout: timeoutMs });
    return () => window.cancelIdleCallback(id);
  }
  const timer = window.setTimeout(task, 300);
  return () => window.clearTimeout(timer);
}

export function feasibilityCacheKey(
  sceneId: string,
  sceneVersion: number,
  farmlandVersion: number,
  requestKey: string,
): string {
  return `${sceneId}\n${sceneVersion}\n${farmlandVersion}\n${requestKey}`;
}

type CachedOverlay = { key: string; url: string };

/** Small blob-URL cache. The pinned URL is the one on the map and is not revoked. */
export class FeasibilityImageCache {
  private entries: CachedOverlay[] = [];
  private pinned: string | null = null;

  constructor(
    private readonly limit: number,
    private readonly revoke: (url: string) => void,
  ) {}

  get(key: string): string | null {
    const index = this.entries.findIndex((item) => item.key === key);
    if (index < 0) return null;
    const [hit] = this.entries.splice(index, 1);
    this.entries.push(hit);
    return hit.url;
  }

  put(key: string, url: string): void {
    this.entries = this.entries.filter((item) => {
      if (item.key !== key) return true;
      if (item.url !== url && item.url !== this.pinned) this.revoke(item.url);
      return false;
    });
    this.entries.push({ key, url });
    while (this.entries.length > this.limit) {
      const index = this.entries.findIndex((item) => item.url !== this.pinned);
      if (index < 0) return;
      const [removed] = this.entries.splice(index, 1);
      this.revoke(removed.url);
    }
  }

  pin(url: string | null): void {
    this.pinned = url;
  }

  releaseAll(): void {
    for (const entry of this.entries) this.revoke(entry.url);
    this.entries = [];
    this.pinned = null;
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
