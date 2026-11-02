import type { RoutingObjectives, RoutingSolution } from "./routing_result.js";

export const ROUTING_COMPARE_AXES: readonly { key: keyof RoutingObjectives; label: string }[] = [
  { key: "tower_count", label: "新增塔" },
  { key: "length_3d_m", label: "三维长度" },
  { key: "bend_sum_rad", label: "水平曲折" },
  { key: "crossing_3d_m", label: "跨越长度" },
];
const COLORS = ["#39f3ff", "#ff8b96", "#ffd166", "#3dd68c", "#d78bff", "#ffae5b", "#94a7ff", "#f1a0e7"];

export function routingCompareColor(index: number): string {
  return COLORS[index] ?? `hsl(${Math.round((index * 137.508) % 360)}, 85%, 65%)`;
}

/** Each axis uses the same full Pareto set, so selecting another route does not move existing lines. */
export function routingComparison(routes: readonly RoutingSolution[], compared: readonly string[]) {
  const bounds = ROUTING_COMPARE_AXES.map(({ key }) => routes.reduce(
    (range, route) => ({ min: Math.min(range.min, route.objectives[key]), max: Math.max(range.max, route.objectives[key]) }),
    { min: Infinity, max: -Infinity },
  ));
  return compared.flatMap((id, index) => {
    const route = routes.find((item) => item.id === id);
    if (!route) return [];
    return [{ id, color: routingCompareColor(index), values: ROUTING_COMPARE_AXES.map(({ key }, axis) => {
      const { min, max } = bounds[axis];
      return max === min ? 0 : (route.objectives[key] - min) / (max - min);
    }) }];
  });
}
