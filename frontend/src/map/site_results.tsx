import { useFilterCaseSource, type FilterCaseSource } from "../results/use_filter_case_source.js";
import { captureFilterSnapshot, type FilterCaseContext, type FilterSnapshot } from "../results/filter_snapshot.js";
import type { RankingStage } from "../results/ranking_pipeline.js";
import { useEffect, useMemo, useRef, useState } from "react";
import { comparedFields, presentChoice, UNMEASURED, type ParetoChoice } from "./decision_run.js";
import type { PoseFreshness } from "./pose_evaluation.js";
import { siteObjectiveValue, type SiteSortKey } from "./site_solution_sort.js";
import { useDraggablePanel } from "./use_draggable_panel.js";
import { RankingColumnHeader, RankingMapOptions, RankingRecorder, nextRankingDisplaySort, type RankingDisplaySort, type RankingField, type RankingMapMode } from "../results/ranking_controls.js";
import { RankingRangeHeader } from "../results/ranking_range_control.js";
import { useRankingPipeline } from "../results/use_ranking_pipeline.js";
import { hasRankingFilter, rankingMapIds, sortRankingRows } from "../results/ranking_pipeline.js";

const COLUMNS: readonly { key: SiteSortKey; label: string }[] = [
  { key: "demSoft", label: "地形平整度" },
  { key: "offroadHaul", label: "进站长度 m" },
  { key: "haulRise", label: "进站累计高差 m" },
  { key: "roadHaul", label: "沿路运输 m" },
  { key: "demandDistance", label: "需求点距离 m" },
];

export function SiteResults({
  active = true,
  poses,
  selectedId,
  hasOrigin,
  includeDemand,
  freshness,
  comparedIds,
  onToggleCompare,
  onSelect,
  sourceKey,
  onRetainedChange, caseContext, restoredSnapshot, onFilterSourceChange,
}: {
  active?: boolean;
  onFilterSourceChange?: (source: FilterCaseSource | null) => void;
  caseContext?: FilterCaseContext;
  restoredSnapshot?: FilterSnapshot | null;
  poses: readonly ParetoChoice[];
  selectedId: string | null;
  hasOrigin: boolean;
  includeDemand: boolean;
  freshness: (pose: ParetoChoice) => PoseFreshness;
  comparedIds: readonly string[];
  onToggleCompare: (id: string) => void;
  onSelect: (id: string) => void;
  sourceKey: string;
  onRetainedChange: (ids: string[]) => void;
}) {
  const [mapMode, setMapMode] = useState<RankingMapMode>("retained");
  const [minimized, setMinimized] = useState(false);
  const [displaySort, setDisplaySort] = useState<RankingDisplaySort<SiteSortKey>>(null);
  const [activeMetric, setActiveMetric] = useState<SiteSortKey>("demSoft");
  const [rangeExpanded, setRangeExpanded] = useState(false);
  const expandedHeight = useRef(320);
  const fields = useMemo(() => new Set(comparedFields(hasOrigin, includeDemand)), [hasOrigin, includeDemand]);
  const columns = COLUMNS.filter((column) => fields.has(column.key));
  const rankingFields: RankingField<SiteSortKey>[] = columns;
  const shown = useMemo(
    () => poses.map((pose) => {
      const state = freshness(pose);
      const presented = presentChoice(pose, state);
      if (state !== "pending") return presented;
      return {
        ...presented,
        demSoft: UNMEASURED,
        offroadHaul: UNMEASURED,
        haulRise: UNMEASURED,
        roadHaul: UNMEASURED,
        demandDistance: UNMEASURED,
      };
    }),
    [poses, freshness],
  );
  const candidateKey = poses.map(({ id }) => id).join(",");
  const rankingSourceKey = `${sourceKey}:${candidateKey}:${columns.map(({ key }) => key).join(",")}`;
  const ranking = useRankingPipeline(shown, rankingSourceKey,
    rankingFields.map(({ key }) => key), siteChoiceValue, restoredSnapshot?.stages as RankingStage<SiteSortKey>[] | undefined);
  const displayRows = useMemo(() => sortRankingRows(ranking.result.rows, displaySort?.key ?? null,
    displaySort?.direction ?? "ascending", siteChoiceValue), [ranking.result.rows, displaySort]);
  const featuredIds = rankingMapIds(displayRows, siteChoiceId, mapMode);
  const featuredKey = featuredIds.join("\u001f");
  useEffect(() => { onRetainedChange(featuredIds); }, [featuredKey, onRetainedChange]);
  useEffect(() => () => onRetainedChange([]), [onRetainedChange]);
  useEffect(() => {
    setDisplaySort(restoredSnapshot?.display_sort as RankingDisplaySort<SiteSortKey> ?? null);
    const field = restoredSnapshot?.display_sort?.key ?? restoredSnapshot?.stages.at(-1)?.key;
    if (field && columns.some((column) => column.key === field)) setActiveMetric(field as SiteSortKey);
    setRangeExpanded(false);
  }, [rankingSourceKey]);
  useEffect(() => {
    if (!columns.some(({ key }) => key === activeMetric) && columns[0]) setActiveMetric(columns[0].key);
  }, [rankingSourceKey]);
  const captureFilter = caseContext ? () => {
    if (displayRows.some(({ item, state }) => state === "active" && (!item.rawMetrics || freshness(item) !== "current"))) {
      throw new Error("保留项需有完整精度的有效指标。请等待重算完成；旧页面数据请重新导入来源案例后再保存。");
    }
    return captureFilterSnapshot(caseContext,
      shown.map((choice, index) => ({ id: choice.id, original_number: index + 1,
        data: { ...choice }, geometry: { x: choice.x, y: choice.y, theta: choice.theta,
          width_m: caseContext.context.widthM, height_m: caseContext.context.heightM },
        metrics: Object.fromEntries([...new Set([...Object.keys(choice.rawMetrics ?? {}), ...rankingFields.map(({ key }) => key)])]
          .map((key) => [key, siteChoiceValue(choice, key as SiteSortKey)])) })),
      displayRows, siteChoiceId, ranking.stages, ranking.result.retainedByStage, displaySort);
  } : undefined;
  useFilterCaseSource(rankingSourceKey, captureFilter ? { total: shown.length, retained: ranking.result.active.length,
    hasFilter: hasRankingFilter(shown, ranking.stages, siteChoiceValue), capture: captureFilter } : null, onFilterSourceChange);
  function changeColumnSort(field: SiteSortKey) {
    const next = nextRankingDisplaySort(displaySort, field);
    setDisplaySort(next);
    setActiveMetric(field);
    const direction = next?.direction ?? "original";
    ranking.open(field, direction);
    ranking.setStageDirection(field, direction);
  }
  function moveRankingStage(index: number, offset: -1 | 1) {
    const from = ranking.stages[index], to = ranking.stages[index + offset];
    if (!from || !to) return;
    ranking.reorder(from.key, to.key);
    setDisplaySort(null);
  }
  function editRankingStage(index: number) {
    const stage = ranking.stages[index];
    if (stage) { setActiveMetric(stage.key); ranking.edit(index); setRangeExpanded(true); }
  }
  function removeRankingStage(index: number) {
    const stage = ranking.stages[index];
    ranking.remove(index);
    if (stage && displaySort?.key === stage.key) setDisplaySort(null);
  }
  function undoRankingStage() {
    const stage = ranking.stages.at(-1);
    ranking.undo();
    if (stage && displaySort?.key === stage.key) setDisplaySort(null);
  }
  function clearRanking() { ranking.clear(); setDisplaySort(null); }
  const firstLayer = poses.filter((pose) => !pose.manual && (pose.paretoLayer ?? 1) === 1).length;
  const extraLayers = poses.filter((pose) => !pose.manual && (pose.paretoLayer ?? 1) > 1).length;
  const manual = poses.filter((pose) => pose.manual).length;
  const panelRef = useRef<HTMLElement>(null);
  const panel = useDraggablePanel(panelRef, {
    defaultSize: { width: 720, height: 320 },
    minSize: { width: 320, height: 160 },
    margin: 18,
    positionKey: poses.length === 0 ? "hidden" : "shown",
    initialPosition: (bounds, size) => ({
      x: bounds.width - size.width - 18,
      y: bounds.height - size.height - 18,
    }),
  });
  function toggleMinimized() {
    const frame = panel.getFrame();
    if (frame) {
      if (minimized) panel.setFrame({ ...frame, height: expandedHeight.current });
      else {
        expandedHeight.current = frame.height;
        panel.setFrame({ ...frame, height: 64 });
      }
    }
    setMinimized((value) => !value);
  }
  if (poses.length === 0) return null;
  return <section
    ref={panelRef}
    className={["site-results", panel.dragging ? "panel-dragging" : "", panel.resizing ? "panel-resizing" : "", minimized ? "minimized" : ""].filter(Boolean).join(" ")}
    style={{ ...panel.style, maxHeight: "none", ...(minimized ? { height: "auto" } : {}), display: active ? undefined : "none" }}
    aria-label="选址方案"
  >
    <div className="site-results-head panel-drag-handle" title="拖动选址列表" {...panel.dragHandleProps}>
      <h2>选址方案 · {firstLayer} 个可行 Pareto 站址</h2>
      <RankingMapOptions mode={mapMode} onChange={setMapMode} />
      <button type="button" className="agent-min" aria-label={minimized ? "展开选址方案" : "最小化选址方案"} title={minimized ? "展开" : "最小化"}
        onClick={toggleMinimized}>{minimized ? "▢" : "–"}</button>
    </div>
    {!minimized && <div className="site-results-body"><div className="site-results-meta">
      <p>地图随筛选实时更新；筛除项在列表中置灰。</p>
      {(extraLayers > 0 || manual > 0) && <p>
        {extraLayers > 0 ? `另显示第 2、3 层 ${extraLayers} 个。` : ""}
        {manual > 0 ? `手动方案 ${manual} 个，不计入 Pareto 层。` : ""}
      </p>}
      <RankingRecorder fields={rankingFields} workflow={ranking} onEdit={editRankingStage} onRemove={removeRankingStage}
        onUndo={undoRankingStage} onClear={clearRanking} onMove={moveRankingStage} />
    </div>
    <table className="ranking-results-table">
      <colgroup><col style={{ width: 32 }} /><col style={{ width: 65 }} />{columns.map(({ key }) => <col key={key} />)}</colgroup>
      <thead>
        <tr>
          <th scope="col">对比</th>
          <th scope="col">编号</th>
          {columns.map(({ key, label }) => <th key={key} scope="col"><div className="ranking-header-stack">
            <RankingColumnHeader label={label} field={key} sort={displaySort} workflow={ranking}
              onSort={changeColumnSort} />
            {activeMetric === key && <RankingRangeHeader field={key} fields={rankingFields}
              valueOf={siteChoiceValue} workflow={ranking} sort={displaySort}
              expanded={active && rangeExpanded} onExpandedChange={setRangeExpanded} />}
          </div></th>)}
        </tr>
      </thead>
      <tbody>
        {displayRows.map(({ item: choice, sourceIndex, state, filteredAt }) => <tr key={choice.id}
          className={state === "filtered" ? "ranking-filtered" : state === "unavailable" ? "ranking-unavailable" : undefined}
          aria-selected={choice.id === selectedId} onClick={() => onSelect(choice.id)}>
          <td onClick={(event) => event.stopPropagation()}>
            <input type="checkbox" aria-label={`对比方案 ${sourceIndex + 1}`} checked={comparedIds.includes(choice.id)} onChange={() => onToggleCompare(choice.id)} />
          </td>
          <td><button type="button" onClick={(event) => { event.stopPropagation(); onSelect(choice.id); }}>{sourceIndex + 1}</button>
            {state === "filtered" && <span>已筛除·第{filteredAt}轮</span>}
            {state === "unavailable" && <span>指标不可用</span>}
          </td>
          {columns.map(({ key }) => <td key={key}>{String(choice[key])}</td>)}
        </tr>)}
      </tbody>
    </table>
    </div>}
    {!minimized && <button type="button" className="panel-resize" aria-label="调整选址方案面板大小" title="调整大小" {...panel.resizeHandleProps} />}
  </section>;
}

function siteChoiceId(choice: ParetoChoice): string { return choice.id; }

function siteChoiceValue(choice: ParetoChoice, key: SiteSortKey): number | null {
  const shown = siteObjectiveValue(String(choice[key]));
  return shown === null ? null : choice.rawMetrics?.[key] ?? shown;
}
