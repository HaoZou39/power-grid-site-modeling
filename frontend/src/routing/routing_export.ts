import type { RoutingBundle } from "./routing_result.js";

/** Preserve the saved geometry and task alongside the reported objectives. */
export function routingJson(bundle: RoutingBundle, task: Record<string, unknown>): string {
  return JSON.stringify({ ...bundle, task }, null, 2);
}

export function routingCsv(bundle: RoutingBundle): string {
  const rows: unknown[][] = [["线路编号", "可行性", "Pareto", "新增塔数", "三维长度(m)", "水平曲折(°)", "跨越长度(m)", "线路点(局部米坐标JSON)"]];
  for (const route of bundle.routes) {
    rows.push([route.id, route.is_feasible ? "可行" : "不可行", route.is_pareto ? "是" : "否",
      route.objectives?.tower_count ?? "", route.objectives?.length_3d_m ?? "",
      Number.isFinite(route.objectives?.bend_sum_rad) ? route.objectives.bend_sum_rad * 180 / Math.PI : "",
      route.objectives?.crossing_3d_m ?? "", JSON.stringify(route.points)]);
  }
  return "\ufeff" + rows.map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(",")).join("\r\n") + "\r\n";
}
