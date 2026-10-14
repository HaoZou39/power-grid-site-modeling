import type { LanduseEditClass } from "./toolbar_commands.js";
import type { LocalPoint } from "./site_frame.js";

export type LanduseClassId = 1 | 2 | 5;

export function landuseEditClassId(value: LanduseEditClass): LanduseClassId {
  if (value === "field") return 1;
  if (value === "building") return 2;
  return 5;
}

export function addLanduseVertex(points: readonly LocalPoint[], point: LocalPoint): LocalPoint[] {
  return [...points, point];
}

export function removeLastLanduseVertex(points: readonly LocalPoint[]): LocalPoint[] {
  return points.slice(0, -1);
}

export function removeLanduseRingVertex(points: readonly LocalPoint[], index: number): LocalPoint[] {
  if (!Number.isInteger(index) || index < 0 || index >= points.length) {
    throw new RangeError("图斑折点不存在。");
  }
  if (points.length <= 3) {
    throw new RangeError("图斑至少需要三个折点，不能再删除。");
  }
  return points.filter((_, pointIndex) => pointIndex !== index);
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
