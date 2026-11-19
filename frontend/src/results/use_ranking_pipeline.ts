import { useMemo } from "react";
import { useScopedState } from "./use_scoped_state.js";
import { rankThroughThresholds, valueExtent } from "./ranking_pipeline.js";
import type { RankingDirection, RankingResult, RankingStage } from "./ranking_pipeline.js";

export type RankingDraft<Key extends string> = RankingStage<Key> & { lowerText: string; upperText: string };
type State<Key extends string> = { stages: RankingStage<Key>[]; draft: RankingDraft<Key> | null; editIndex: number | null };

export type RankingWorkflow<T, Key extends string> = {
  stages: RankingStage<Key>[];
  draft: RankingDraft<Key> | null;
  editIndex: number | null;
  result: RankingResult<T>;
  itemsBeforeStage: (field: Key) => T[];
  open: (field: Key, direction?: RankingDirection) => void;
  edit: (index: number) => void;
  setStageDirection: (key: Key, direction: RankingDirection) => void;
  reorder: (from: Key, to: Key) => void;
  updateDraft: (change: Partial<Pick<RankingDraft<Key>, "key" | "direction" | "lower" | "upper" | "lowerText" | "upperText">>) => void;
  remove: (index: number) => void;
  undo: () => void;
  clear: () => void;
};

export function useRankingPipeline<T, Key extends string>(
  items: readonly T[], sourceKey: unknown, fields: readonly Key[],
  valueOf: (item: T, key: Key) => number | null,
  initialStages: readonly RankingStage<Key>[] = [],
  scope = "default",
) {
  const [state, update] = useScopedState<State<Key>>(sourceKey, scope,
    { stages: [...initialStages], draft: null, editIndex: null });

  const result = useMemo(() => rankThroughThresholds(items, state.stages, valueOf),
    [items, state.stages, valueOf]);
  function open(field: Key, direction: RankingDirection = "ascending") {
    if (!fields.includes(field)) return;
    const existingIndex = state.stages.findIndex((stage) => stage.key === field);
    if (existingIndex >= 0) { edit(existingIndex); return; }
    const activeItems = rankThroughThresholds(items, state.stages, valueOf).active.map((row) => row.item);
    const extent = valueExtent(activeItems, field, valueOf);
    update((current) => ({ ...current, draft: {
      key: field, direction, lower: extent?.min ?? 0, upper: extent?.max ?? 0,
      lowerText: String(extent?.min ?? 0), upperText: String(extent?.max ?? 0),
    }, editIndex: null }));
  }
  function edit(index: number) {
    const stage = state.stages[index];
    if (!stage) return;
    update((current) => ({ ...current, draft: { ...stage, lowerText: String(stage.lower), upperText: String(stage.upper) }, editIndex: index }));
  }
  function setStageDirection(key: Key, direction: RankingDirection) {
    update((current) => {
      const index = current.stages.findIndex((stage) => stage.key === key);
      if (index >= 0) return { ...current,
        stages: current.stages.map((stage, i) => i === index ? { ...stage, direction } : stage),
        draft: current.draft?.key === key ? { ...current.draft, direction } : current.draft,
      };
      const active = rankThroughThresholds(items, current.stages, valueOf).active.map((row) => row.item);
      const extent = valueExtent(active, key, valueOf);
      if (!extent) return current;
      const matchingDraft = current.draft?.key === key ? { ...current.draft, direction } : null;
      const stage = matchingDraft ? { key, direction, lower: Number(matchingDraft.lowerText), upper: Number(matchingDraft.upperText) }
        : { key, direction, lower: extent.min, upper: extent.max };
      return { ...current, stages: [...current.stages, stage],
        draft: matchingDraft ?? current.draft, editIndex: matchingDraft ? current.stages.length : current.editIndex };
    });
  }
  function reorder(from: Key, to: Key) {
    update((current) => {
      const fromIndex = current.stages.findIndex((stage) => stage.key === from);
      const toIndex = current.stages.findIndex((stage) => stage.key === to);
      if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return current;
      const stages = [...current.stages];
      const [moved] = stages.splice(fromIndex, 1);
      stages.splice(toIndex, 0, moved);
      const editIndex = current.draft ? stages.findIndex((stage) => stage.key === current.draft?.key) : null;
      return { ...current, stages, editIndex: editIndex !== null && editIndex >= 0 ? editIndex : null };
    });
  }
  function updateDraft(change: Partial<Pick<RankingDraft<Key>, "key" | "direction" | "lower" | "upper" | "lowerText" | "upperText">>) {
    update((current) => {
      if (!current.draft) return current;
      const draft = { ...current.draft, ...change };
      const lower = Number(draft.lowerText), upper = Number(draft.upperText);
      if (!Number.isFinite(lower) || !Number.isFinite(upper) || lower > upper) return { ...current, draft };
      const stage: RankingStage<Key> = { key: draft.key, direction: draft.direction, lower, upper };
      const index = current.editIndex ?? current.stages.findIndex((item) => item.key === draft.key);
      const stages = index < 0 ? [...current.stages, stage]
        : current.stages.map((item, i) => i === index ? stage : item);
      return { ...current, stages, draft, editIndex: index < 0 ? stages.length - 1 : index };
    });
  }
  function remove(index: number) {
    update((current) => ({ ...current, stages: current.stages.filter((_, i) => i !== index), draft: null, editIndex: null }));
  }
  function undo() {
    update((current) => ({ ...current, stages: current.stages.slice(0, -1), draft: null, editIndex: null }));
  }
  function clear() {
    update((current) => ({ ...current, stages: [], draft: null, editIndex: null }));
  }
  function itemsBeforeStage(field: Key) {
    const index = state.stages.findIndex((stage) => stage.key === field);
    const stages = index < 0 ? state.stages : state.stages.slice(0, index);
    return rankThroughThresholds(items, stages, valueOf).active.map((row) => row.item);
  }
  return { stages: state.stages, draft: state.draft, editIndex: state.editIndex, result, itemsBeforeStage, open, edit, setStageDirection, reorder, updateDraft, remove, undo, clear };
}

export type { RankingDirection };
