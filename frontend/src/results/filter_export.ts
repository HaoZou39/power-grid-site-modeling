import { exportSolutionsCsv, exportSolutionsJson } from "../map/solution_export.js";
import type { ParetoChoice } from "../map/decision_run.js";
import { routingCsv, routingJson } from "../routing/routing_export.js";
import type { RoutingBundle, RoutingSolution } from "../routing/routing_result.js";
import type { FilterSnapshot } from "./filter_snapshot.js";

export function retainedFilterData(snapshot: FilterSnapshot) {
  const byId = new Map(snapshot.candidates.map((item) => [item.id, item]));
  return snapshot.retained_ids.map((id) => byId.get(id)!.data);
}

/** Use the same domain documents as full exports, with the trace attached to JSON. */
export function exportFilterResult(snapshot: FilterSnapshot, format: "csv" | "json"): string {
  const retained = retainedFilterData(snapshot);
  let content: string;
  if (snapshot.problem_type === "site") {
    const choices = retained as ParetoChoice[];
    content = format === "csv" ? exportSolutionsCsv(choices)
      : exportSolutionsJson(snapshot.scene_name, Number(snapshot.context.widthM), Number(snapshot.context.heightM), choices, snapshot.captured_at);
  } else {
    const bundle: RoutingBundle = { schema_version: 1, problem_type: "routing", scene_name: snapshot.scene_name,
      frame: snapshot.context.frame as RoutingBundle["frame"], data_version: snapshot.scene_version, routes: retained as RoutingSolution[] };
    content = format === "csv" ? routingCsv(bundle) : routingJson(bundle, snapshot.context.task as Record<string, unknown>);
  }
  return format === "csv" ? content : JSON.stringify({ ...JSON.parse(content), filter_snapshot: snapshot }, null, 2);
}
