import type { LocalPoint } from "./site_frame.js";

/** A closed ring in local meters. `kind` says whether the ring blocks construction or limits the search. */
export class ExclusionZone {
  constructor(
    readonly id: string,
    readonly points: LocalPoint[],
    readonly kind: "exclusion" | "feasible" = "exclusion",
  ) {}
}

const CLOSE_DISTANCE_M = 8;
const STROKE_TOLERANCE_M = 4;

/** Draft vertices plus the zones already closed in this session. */
export class ExclusionSketch {
  constructor(readonly zones: readonly ExclusionZone[] = [], readonly draft: readonly LocalPoint[] = []) {}

  addPoint(point: LocalPoint): ExclusionSketch {
    if (this.draft.length >= 3 && distance(point, this.draft[0]) <= CLOSE_DISTANCE_M) {
      return this.close();
    }
    return new ExclusionSketch(this.zones, [...this.draft, point]);
  }

  undoPoint(): ExclusionSketch {
    return new ExclusionSketch(this.zones, this.draft.slice(0, -1));
  }

  cancel(): ExclusionSketch {
    return new ExclusionSketch(this.zones, []);
  }

  replaceDraft(points: readonly LocalPoint[]): ExclusionSketch {
    return new ExclusionSketch(this.zones, points);
  }

  /** Simplify a freehand loop and close it back to the first vertex. */
  finishStroke(points: readonly LocalPoint[]): ExclusionSketch {
    const ring = simplifyStroke(points, STROKE_TOLERANCE_M);
    if (ring.length < 3) throw new Error("请沿禁区画一圈，松手后会自动闭合。");
    const zone = new ExclusionZone(`zone-${this.zones.length + 1}`, ring);
    return new ExclusionSketch([...this.zones, zone], []);
  }

  close(): ExclusionSketch {
    if (this.draft.length < 3) throw new Error("禁行区至少需要三个顶点。");
    const zone = new ExclusionZone(`zone-${this.zones.length + 1}`, [...this.draft]);
    return new ExclusionSketch([...this.zones, zone], []);
  }

  addZone(points: readonly LocalPoint[]): ExclusionSketch {
    if (points.length < 3) throw new Error("禁行区至少需要三个顶点。");
    const zone = new ExclusionZone(`zone-${this.zones.length + 1}`, [...points]);
    return new ExclusionSketch([...this.zones, zone], this.draft);
  }

  removeZone(id: string): ExclusionSketch {
    return new ExclusionSketch(this.zones.filter((zone) => zone.id !== id), this.draft);
  }
}

export function simplifyStroke(points: readonly LocalPoint[], toleranceM: number): LocalPoint[] {
  if (points.length < 3) return [...points];
  const keep = points.map((_, index) => index === 0 || index === points.length - 1);
  const stack: [number, number][] = [[0, points.length - 1]];
  while (stack.length > 0) {
    const [start, end] = stack.pop() as [number, number];
    let farthest = 0;
    let index = -1;
    for (let cursor = start + 1; cursor < end; cursor += 1) {
      const gap = distanceToSegment(points[cursor], points[start], points[end]);
      if (gap > farthest) {
        farthest = gap;
        index = cursor;
      }
    }
    if (index >= 0 && farthest > toleranceM) {
      keep[index] = true;
      stack.push([start, index], [index, end]);
    }
  }
  return points.filter((_, index) => keep[index]);
}

function distance(left: LocalPoint, right: LocalPoint): number {
  return Math.hypot(left.x - right.x, left.y - right.y);
}

function distanceToSegment(point: LocalPoint, start: LocalPoint, end: LocalPoint): number {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const length2 = dx * dx + dy * dy;
  if (length2 === 0) return distance(point, start);
  const t = Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / length2));
  return Math.hypot(point.x - (start.x + t * dx), point.y - (start.y + t * dy));
}
