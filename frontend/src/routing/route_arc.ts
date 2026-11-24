export type RouteXY = { x: number; y: number };

/** Horizontal arc length keeps routes with different tower counts comparable. */
export function routeArc(points: readonly RouteXY[]) {
  if (points.length < 2 || points.some((point) => !Number.isFinite(point.x) || !Number.isFinite(point.y))) {
    throw new Error("线路走廊需要至少两个有效平面点。");
  }
  const lengths = [0];
  for (let i = 1; i < points.length; i += 1) {
    lengths.push(lengths[i - 1] + Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y));
  }
  const total = lengths.at(-1)!;
  if (total === 0) throw new Error("零长度线路无法显示走廊。");
  return {
    vertices: points.map((point, index) => ({ point, fraction: lengths[index] / total })),
    pointAt(fraction: number): RouteXY {
      const distance = total * fraction;
      let segment = 1;
      while (segment < points.length - 1 && lengths[segment] < distance) segment += 1;
      const part = lengths[segment] === lengths[segment - 1] ? 0
        : (distance - lengths[segment - 1]) / (lengths[segment] - lengths[segment - 1]);
      return { x: points[segment - 1].x + part * (points[segment].x - points[segment - 1].x),
        y: points[segment - 1].y + part * (points[segment].y - points[segment - 1].y) };
    },
  };
}
