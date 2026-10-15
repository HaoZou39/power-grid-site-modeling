import type { LanduseEditClass } from "./toolbar_commands.js";
import type { LocalPoint } from "./site_frame.js";

export type LanduseClassId = 1 | 2 | 3 | 5;

export function landuseEditClassId(value: LanduseEditClass): LanduseClassId {
  if (value === "field") return 1;
  if (value === "building") return 2;
  if (value === "road") return 3;
  return 5;
}

export function pointInLanduseRing(point: LocalPoint, ring: readonly LocalPoint[]): boolean {
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index, index += 1) {
    const left = ring[index];
    const right = ring[previous];
    const crosses = (left.y > point.y) !== (right.y > point.y)
      && point.x < (right.x - left.x) * (point.y - left.y) / (right.y - left.y) + left.x;
    if (crosses) inside = !inside;
  }
  return inside;
}
