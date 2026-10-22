import type { SolutionRecord } from "../solution_record.js";

export type ParetoLayer = 1 | 2 | 3;
export const PARETO_LAYER_COLORS = ["#7dfff1", "#ff9f1a", "#b48aff"] as const;

/** Peel the saved feasible population using the run's objectives at CSV precision. */
export function solutionLayers(
  records: readonly SolutionRecord[],
  form: { include_demand?: boolean; origin_x?: number | null; origin_y?: number | null },
): ReadonlyMap<string, ParetoLayer> {
  const fields: (keyof SolutionRecord)[] = ["demSoft", "offroadHaul", "haulRise"];
  if (form.include_demand) fields.push("demandDistance");
  if (form.origin_x != null && form.origin_y != null) fields.push("roadHaul");
  const feasible = records.filter((record) => record.isFeasible === true);
  const values = new Map(feasible.map((record) => [record.id, fields.map((field) => {
    const text = String(record[field]);
    const value = Number(text);
    if (!text.trim() || !Number.isFinite(value)) throw new Error(`方案 ${record.id} 缺少有效的分层目标 ${field}。`);
    return value;
  })]));
  const layers = new Map<string, ParetoLayer>();
  feasible.filter((record) => record.isPareto === true).forEach((record) => layers.set(record.id, 1));
  let remaining = feasible.filter((record) => !layers.has(record.id));
  for (const layer of [2, 3] as const) {
    const front = remaining.filter((candidate) => {
      const right = values.get(candidate.id)!;
      return !remaining.some((other) => {
        const left = values.get(other.id)!;
        return left.every((value, index) => value <= right[index])
          && left.some((value, index) => value < right[index]);
      });
    });
    front.forEach((record) => layers.set(record.id, layer));
    remaining = remaining.filter((record) => !layers.has(record.id));
  }
  return layers;
}

/** Keep edits to visible poses when changing the cumulative display depth. */
export function mergeDisplayedChoices<T extends { id: string }>(pool: readonly T[], displayed: readonly T[]): T[] {
  const edits = new Map(displayed.map((choice) => [choice.id, choice]));
  const known = new Set(pool.map((choice) => choice.id));
  return [...pool.map((choice) => edits.get(choice.id) ?? choice), ...displayed.filter((choice) => !known.has(choice.id))];
}
