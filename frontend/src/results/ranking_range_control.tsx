import { useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, RefObject } from "react";
import { createPortal } from "react-dom";
import { directionLabel, formatValue } from "./ranking_controls.js";
import type { RankingDisplaySort, RankingField } from "./ranking_controls.js";
import { valueDistribution, valueExtent } from "./ranking_pipeline.js";
import type { RankingWorkflow } from "./use_ranking_pipeline.js";

export function RankingRangeHeader<T, Key extends string>({ field, fields, valueOf, workflow, sort, expanded, onExpandedChange }: {
  field: Key;
  fields: readonly RankingField<Key>[];
  valueOf: (item: T, key: Key) => number | null;
  workflow: RankingWorkflow<T, Key>;
  sort: RankingDisplaySort<Key>;
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
}) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const stage = workflow.stages.find((item) => item.key === field);
  const direction = stage?.direction ?? (sort?.key === field ? sort.direction : "ascending");
  const draft = workflow.draft?.key === field ? workflow.draft : null;
  // The histogram shows this round's input even after another record is removed or moved.
  const items = workflow.itemsBeforeStage(field);
  const extent = valueExtent(items, field, valueOf);
  const lower = Number(draft?.lowerText ?? stage?.lower ?? extent?.min ?? 0);
  const upper = Number(draft?.upperText ?? stage?.upper ?? extent?.max ?? 0);
  const retained = items.filter((item) => {
    const value = valueOf(item, field);
    return value !== null && value >= lower && value <= upper;
  });
  const bins = extent ? valueDistribution(items, field, valueOf, extent.min, extent.max, 16) : [];
  const retainedBins = extent ? valueDistribution(retained, field, valueOf, extent.min, extent.max, 16) : [];
  const percent = (value: number) => extent && extent.max > extent.min
    ? Math.max(0, Math.min(100, (value - extent.min) / (extent.max - extent.min) * 100)) : 0;
  const rangeStyle = {
    "--range-start": `${percent(lower)}%`,
    "--range-width": `${percent(upper) - percent(lower)}%`,
  } as CSSProperties;
  const label = fields.find((item) => item.key === field)?.label ?? String(field);
  function inspect() {
    workflow.open(field, direction);
    onExpandedChange(true);
  }

  return <><div ref={anchorRef} className="ranking-range-header" aria-label={`${label} 区间筛选`}>
    <div className="ranking-range-slider" style={rangeStyle} onPointerDownCapture={inspect} onFocusCapture={inspect}>
      <input aria-label={`${label} 区间下界`} type="range" min={extent?.min ?? 0} max={extent?.max ?? 0}
        step={extent ? Math.max((extent.max - extent.min) / 1000, Number.EPSILON) : 1}
        disabled={!extent || extent.min === extent.max} value={lower}
        onChange={(event) => {
          inspect();
          const value = Math.min(Number(event.target.value), upper);
          workflow.updateDraft({ lower: value, lowerText: String(value) });
        }} />
      <input aria-label={`${label} 区间上界`} type="range" min={extent?.min ?? 0} max={extent?.max ?? 0}
        step={extent ? Math.max((extent.max - extent.min) / 1000, Number.EPSILON) : 1}
        disabled={!extent || extent.min === extent.max} value={upper}
        onChange={(event) => {
          inspect();
          const value = Math.max(Number(event.target.value), lower);
          workflow.updateDraft({ upper: value, upperText: String(value) });
        }} />
    </div>
    <span className="ranking-range-summary">{extent ? `${formatValue(lower)}–${formatValue(upper)}` : "无有效数值"}</span>
  </div>
    {expanded && <RankingRangeDetail anchorRef={anchorRef} label={label} direction={directionLabel(direction)}
      extent={extent} lower={lower} upper={upper} bins={bins} retainedBins={retainedBins}
      retainedCount={retained.length} rangeStyle={rangeStyle} onExpandedChange={onExpandedChange} />}
  </>;
}

function RankingRangeDetail({ anchorRef, label, direction, extent, lower, upper, bins, retainedBins, retainedCount, rangeStyle, onExpandedChange }: {
  anchorRef: RefObject<HTMLDivElement | null>;
  label: string;
  direction: string;
  extent: { min: number; max: number } | null;
  lower: number;
  upper: number;
  bins: number[];
  retainedBins: number[];
  retainedCount: number;
  rangeStyle: CSSProperties;
  onExpandedChange: (expanded: boolean) => void;
}) {
  const detailRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<CSSProperties>({ visibility: "hidden" });
  useLayoutEffect(() => {
    function place() {
      const anchor = anchorRef.current?.getBoundingClientRect();
      const detail = detailRef.current?.getBoundingClientRect();
      if (!anchor || !detail) return;
      const above = anchor.top - detail.height - 10;
      const top = above >= 12 ? above : Math.min(anchor.bottom + 10, window.innerHeight - detail.height - 12);
      setPosition({ left: Math.max(12, Math.min(anchor.right - detail.width, window.innerWidth - detail.width - 12)), top: Math.max(12, top) });
    }
    function dismiss(event: PointerEvent) {
      if (event.target instanceof Node && !anchorRef.current?.contains(event.target) && !detailRef.current?.contains(event.target)) onExpandedChange(false);
    }
    function keydown(event: KeyboardEvent) { if (event.key === "Escape") onExpandedChange(false); }
    place();
    const observer = new ResizeObserver(place);
    if (detailRef.current) observer.observe(detailRef.current);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    document.addEventListener("pointerdown", dismiss, true);
    document.addEventListener("keydown", keydown);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      document.removeEventListener("pointerdown", dismiss, true);
      document.removeEventListener("keydown", keydown);
    };
  }, [anchorRef, label, onExpandedChange]);
  const maxBin = Math.max(1, ...bins);
  const binWidth = extent && bins.length ? (extent.max - extent.min) / bins.length : 0;

  // A portal keeps opening the readable view from moving the thumb under the pointer.
  return createPortal(<div ref={detailRef} className="ranking-range-detail" style={position} role="dialog" aria-label={`${label} 分布明细`}
    data-theme={anchorRef.current?.closest("[data-theme]")?.getAttribute("data-theme") ?? "dark"}>
    <div className="ranking-range-title"><strong>{label}</strong><span>{direction}</span>
      <b>本轮保留 {retainedCount} 个</b><button type="button" onClick={() => onExpandedChange(false)}>关闭</button></div>
    <div className="ranking-range-values">保留区间：{extent ? `${formatValue(lower)} – ${formatValue(upper)}` : "无有效数值"}</div>
    <p className="ranking-note">柱顶为该值段总数（括号内为本轮保留数）；柱下为完整值段。区间外的柱子变暗。</p>
    <div className="ranking-distribution-scroll"><div className="ranking-distribution" role="img" aria-label="各值段的总数、本轮保留数和上下界">
      {bins.map((count, index) => {
        const binMin = extent!.min + index * binWidth;
        const binMax = index === bins.length - 1 ? extent!.max : binMin + binWidth;
        return <div className="ranking-bin" key={index} style={{ opacity: retainedBins[index] ? 1 : .45 }}>
          <strong>{count} <small>({retainedBins[index]})</small></strong>
          <div className="ranking-bin-bar"><i style={{ height: `${count / maxBin * 100}%` }} /></div>
          <span>{formatValue(binMin)}</span><span>– {formatValue(binMax)}</span>
        </div>;
      })}
    </div></div>
    <div className="ranking-range-slider ranking-range-mirror" style={rangeStyle} aria-hidden="true" />
    <div className="ranking-range-extents"><span>最小 {formatValue(extent?.min ?? null)}</span><span>最大 {formatValue(extent?.max ?? null)}</span></div>
  </div>, document.body);
}
