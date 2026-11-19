import type { RankingDisplaySort, RankingRow, RankingStage } from "./ranking_pipeline.js";


export type FilterCandidate = {
  id: string; original_number: number;
  metrics: Record<string, number | null>;
  geometry: Record<string, unknown>;
  data: Record<string, unknown>;
};
export type FilterSnapshot = {
  schema_version: 1; problem_type: "site" | "routing"; scene_name: string;
  source_experiment_id: string | null; scene_version: Record<string, unknown>;
  captured_at: string; scope: Record<string, unknown>; context: Record<string, unknown>;
  candidates: FilterCandidate[]; retained_ids: string[];
  stages: (RankingStage<string> & { retained_count: number })[];
  display_sort: RankingDisplaySort<string>;
};
export type FilterCaseContext = Pick<FilterSnapshot,
  "problem_type" | "scene_name" | "source_experiment_id" | "scene_version" | "scope" | "context">;

/** Copy at the click, before awaiting the name or the network. */
export function captureFilterSnapshot<T, Key extends string>(context: FilterCaseContext,
  candidates: FilterCandidate[], rows: readonly RankingRow<T>[], idOf: (item: T) => string,
  stages: readonly RankingStage<Key>[], counts: readonly number[], sort: RankingDisplaySort<Key>): FilterSnapshot {
  return structuredClone({ ...context, schema_version: 1, captured_at: new Date().toISOString(), candidates,
    retained_ids: rows.filter((row) => row.state === "active").map((row) => idOf(row.item)),
    stages: stages.map((stage, index) => ({ ...stage, retained_count: counts[index] })), display_sort: sort });
}

export async function readFilterSnapshot(record: { artifacts: readonly { name: string; url: string }[] },
  readText: (url: string) => Promise<string>): Promise<FilterSnapshot | null> {
  const artifact = record.artifacts.find((item) => item.name === "filter_snapshot.json");
  if (!artifact) return null;
  const snapshot = JSON.parse(await readText(artifact.url)) as FilterSnapshot;
  if (snapshot.schema_version !== 1 || !Array.isArray(snapshot.candidates) || !Array.isArray(snapshot.stages)
    || !Array.isArray(snapshot.retained_ids)) throw new Error("筛选案例格式无效。");
  return snapshot;
}
