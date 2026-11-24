import { routeArc, type RouteXY } from "./route_arc.js";

function cross(a: RouteXY, b: RouteXY, c: RouteXY): number {
  return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
}

function convexHull(points: RouteXY[]): RouteXY[] {
  const sorted = points.sort((a, b) => a.x - b.x || a.y - b.y);
  const lower: RouteXY[] = [], upper: RouteXY[] = [];
  for (const point of sorted) {
    while (lower.length > 1 && cross(lower.at(-2)!, lower.at(-1)!, point) <= 0) lower.pop();
    lower.push(point);
  }
  for (let index = sorted.length - 1; index >= 0; index -= 1) {
    const point = sorted[index];
    while (upper.length > 1 && cross(upper.at(-2)!, upper.at(-1)!, point) <= 0) upper.pop();
    upper.push(point);
  }
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

/** Adjacent padded hulls cover every original route segment without filling large bends between them. */
export function corridorEnvelope(routes: readonly { points: readonly RouteXY[] }[], samples: number,
  paddingM: number): RouteXY[][] {
  if (!Number.isInteger(samples) || samples < 2 || !Number.isFinite(paddingM) || paddingM <= 0) {
    throw new Error("走廊区域参数无效。");
  }
  if (!routes.length) return [];
  const arcs = routes.map((route) => routeArc(route.points));
  const directions = Array.from({ length: 8 }, (_, index) => ({
    x: paddingM * Math.cos(index * Math.PI / 4), y: paddingM * Math.sin(index * Math.PI / 4),
  }));
  return Array.from({ length: samples - 1 }, (_, index) => {
    const from = index / (samples - 1), to = (index + 1) / (samples - 1);
    const section = arcs.flatMap((arc) => [arc.pointAt(from),
      ...arc.vertices.filter(({ fraction }) => fraction > from && fraction < to).map(({ point }) => point),
      arc.pointAt(to)]);
    return convexHull(section.flatMap((point) => directions.map((offset) => ({
      x: point.x + offset.x, y: point.y + offset.y,
    }))));
  });
}
