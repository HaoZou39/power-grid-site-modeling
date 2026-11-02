import type { LocalPoint } from "../map/site_frame.js";

function samePoint(a: LocalPoint, b: LocalPoint): boolean {
  return a.x === b.x && a.y === b.y;
}

function orientation(a: LocalPoint, b: LocalPoint, c: LocalPoint): number {
  const first = (b.x - a.x) * (c.y - a.y);
  const second = (b.y - a.y) * (c.x - a.x);
  const cross = first - second;
  const tolerance = Number.EPSILON * 16 * (Math.abs(first) + Math.abs(second));
  return Math.abs(cross) <= tolerance ? 0 : Math.sign(cross);
}

function onSegment(a: LocalPoint, b: LocalPoint, point: LocalPoint): boolean {
  return orientation(a, b, point) === 0 && point.x >= Math.min(a.x, b.x) && point.x <= Math.max(a.x, b.x)
    && point.y >= Math.min(a.y, b.y) && point.y <= Math.max(a.y, b.y);
}

function intersects(a: LocalPoint, b: LocalPoint, c: LocalPoint, d: LocalPoint): boolean {
  const abc = orientation(a, b, c), abd = orientation(a, b, d);
  const cda = orientation(c, d, a), cdb = orientation(c, d, b);
  return (abc * abd < 0 && cda * cdb < 0)
    || (!abc && onSegment(a, b, c)) || (!abd && onSegment(a, b, d))
    || (!cda && onSegment(c, d, a)) || (!cdb && onSegment(c, d, b));
}

/** Reject self-intersections and zero-area rings; never change the area drawn by the user. */
export function validateRoutingPolygon(points: readonly LocalPoint[]): void {
  if (points.some((point) => !Number.isFinite(point.x) || !Number.isFinite(point.y))) throw new Error("区域坐标无效。");
  const ring = points.filter((point, index) => index === 0 || !samePoint(point, points[index - 1]));
  if (ring.length > 1 && samePoint(ring[0], ring[ring.length - 1])) ring.pop();
  if (ring.length < 3) throw new Error("区域至少需要三个不同的顶点。");

  let areaTwice = 0;
  for (let i = 0; i < ring.length; i += 1) {
    const previous = ring[(i + ring.length - 1) % ring.length], current = ring[i], next = ring[(i + 1) % ring.length];
    areaTwice += (current.x - ring[0].x) * (next.y - ring[0].y) - (current.y - ring[0].y) * (next.x - ring[0].x);
    if (orientation(previous, current, next) === 0
      && (previous.x - current.x) * (next.x - current.x) + (previous.y - current.y) * (next.y - current.y) > 0) {
      throw new Error("区域边界不能重叠或交叉，请重新绘制。");
    }
    for (let j = i + 1; j < ring.length; j += 1) {
      if (j === i + 1 || (i === 0 && j === ring.length - 1)) continue;
      if (intersects(current, next, ring[j], ring[(j + 1) % ring.length])) {
        throw new Error("区域边界不能重叠或交叉，请重新绘制。");
      }
    }
  }
  if (areaTwice === 0) throw new Error("区域面积必须大于零，请重新绘制。");
}
