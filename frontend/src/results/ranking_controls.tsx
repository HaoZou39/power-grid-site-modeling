import type { CSSProperties } from "react";
import type { RankingDirection, RankingDisplaySort, RankingMapMode } from "./ranking_pipeline.js";
import { rankingStageColor } from "./ranking_pipeline.js";
import type { RankingWorkflow } from "./use_ranking_pipeline.js";
import "./ranking.css";

export type RankingField<Key extends string> = { key: Key; label: string };
export type { RankingDisplaySort };

export type { RankingMapMode };
export function RankingMapOptions({ mode, onChange }: { mode: RankingMapMode; onChange: (mode: RankingMapMode) => void }) {
  return <div className="ranking-map-options" onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>
    <label title="地图显示保留项的前十名，保存和导出仍包含全部保留项"><input type="checkbox" checked={mode === "top-ten"}
      onChange={(event) => onChange(event.target.checked ? "top-ten" : "retained")} />只看前十</label>
    <label title="地图显示当前结果范围内的所有候选，包括筛除项；不改变筛选结果"><input type="checkbox" checked={mode === "all"}
      onChange={(event) => onChange(event.target.checked ? "all" : "retained")} />全部方案</label>
  </div>;
}

export function RankingRecorder<T, Key extends string>({ fields, workflow, onEdit, onRemove, onUndo, onClear, onMove }: {
  fields: readonly RankingField<Key>[];
  workflow: RankingWorkflow<T, Key>;
  onEdit: (index: number) => void;
  onRemove: (index: number) => void;
  onUndo: () => void;
  onClear: () => void;
  onMove: (index: number, offset: -1 | 1) => void;
}) {
  const fieldLabel = (key: Key) => fields.find((field) => field.key === key)?.label ?? String(key);
  return <section className="ranking-workflow" aria-label="多轮排序筛选记录">
    <div className="ranking-workflow-head">
      <strong>轮次记录</strong>
      <div>
        <button type="button" disabled={!workflow.stages.length} onClick={onUndo}>撤销上一轮</button>
        <button type="button" disabled={!workflow.stages.length} onClick={onClear}>清空</button>
      </div>
    </div>
    {workflow.stages.length === 0 && <span className="ranking-note">点击表头排序或拖动区间会即时记录。</span>}
    {workflow.stages.map((stage, index) => <div className="ranking-stage" key={stage.key} style={{ "--ranking-color": rankingStageColor(index + 1) } as CSSProperties}>
      <span className="ranking-round">第 {index + 1} 轮</span>
      <span title={stage.direction === "original" ? "按载入时的编号顺序排列，仍保留区间筛选" : undefined}>{fieldLabel(stage.key)} · {directionLabel(stage.direction)} · {formatValue(stage.lower)}–{formatValue(stage.upper)}</span>
      <span>保留 {workflow.result.retainedByStage[index] ?? 0}</span>
      <div className="ranking-stage-actions">
        <button type="button" onClick={() => onEdit(index)}>修改</button>
        <button type="button" onClick={() => onRemove(index)}>移除</button>
        <button type="button" disabled={index === 0} aria-label={`第 ${index + 1} 轮上移`} onClick={() => onMove(index, -1)}>上移</button>
        <button type="button" disabled={index === workflow.stages.length - 1} aria-label={`第 ${index + 1} 轮下移`} onClick={() => onMove(index, 1)}>下移</button>
      </div>
    </div>)}
  </section>;
}

export function nextRankingDisplaySort<Key extends string>(current: RankingDisplaySort<Key>, key: Key): RankingDisplaySort<Key> {
  if (current?.key !== key || current.direction === "original") return { key, direction: "ascending" };
  if (current.direction === "ascending") return { key, direction: "descending" };
  return { key, direction: "original" };
}

export function RankingColumnHeader<T, Key extends string>({
  label, field, sort, workflow, onSort,
}: {
  label: string;
  field: Key;
  sort: RankingDisplaySort<Key>;
  workflow: RankingWorkflow<T, Key>;
  onSort: (field: Key) => void;
}) {
  const stageIndex = workflow.stages.findIndex((stage) => stage.key === field);
  const stage = stageIndex >= 0 ? workflow.stages[stageIndex] : null;
  const filtered = stageIndex >= 0 && workflow.result.filteredByStage[stageIndex] > 0;
  const marker = sort?.key === field
    ? (sort.direction === "ascending" ? " ↑" : sort.direction === "descending" ? " ↓" : " ↕")
    : " ↕";

  return <div className={stage ? "ranking-column is-ranked" : "ranking-column"}
    style={stage ? { "--ranking-color": rankingStageColor(stageIndex + 1) } as CSSProperties : undefined}
    title="点击切换排序方向；在轮次记录中调整顺序">
    <button type="button" className="ranking-sort-button" onClick={() => onSort(field)}>{label}{marker}</button>
    <span className="ranking-column-state" style={{ visibility: stage ? "visible" : "hidden" }}>
      {stage ? `第${stageIndex + 1}轮 · ${directionLabel(stage.direction)}${filtered ? " · 区间" : ""}` : "未排序"}
    </span>
  </div>;
}

export function formatValue(value: number | null): string {
  return value === null ? "—" : Number(value.toPrecision(6)).toString();
}

export function directionLabel(direction: RankingDirection): string {
  return direction === "ascending" ? "升序" : direction === "descending" ? "降序" : "载入顺序";
}

