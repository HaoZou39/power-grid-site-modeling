import { useMemo, useRef, useState } from "react";
import { comparedFields, presentChoice, UNMEASURED, type ParetoChoice } from "./decision_run.js";
import type { PoseFreshness } from "./pose_evaluation.js";
import { nextSiteSort, sortSiteSolutions, type SiteSort, type SiteSortKey } from "./site_solution_sort.js";
import { useDraggablePanel } from "./use_draggable_panel.js";

const COLUMNS: readonly { key: SiteSortKey; label: string }[] = [
  { key: "demSoft", label: "地形平整度" },
  { key: "offroadHaul", label: "进站长度 m" },
  { key: "haulRise", label: "进站累计高差 m" },
  { key: "roadHaul", label: "沿路运输 m" },
  { key: "demandDistance", label: "需求点距离 m" },
];

export function SiteResults({
  poses,
  selectedId,
  hasOrigin,
  includeDemand,
  freshness,
  comparedIds,
  onToggleCompare,
  onSelect,
}: {
  poses: readonly ParetoChoice[];
  selectedId: string | null;
  hasOrigin: boolean;
  includeDemand: boolean;
  freshness: (pose: ParetoChoice) => PoseFreshness;
  comparedIds: readonly string[];
  onToggleCompare: (id: string) => void;
  onSelect: (id: string) => void;
}) {
  const [sort, setSort] = useState<SiteSort | null>(null);
  const fields = useMemo(() => new Set(comparedFields(hasOrigin, includeDemand)), [hasOrigin, includeDemand]);
  const columns = COLUMNS.filter((column) => fields.has(column.key));
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
  const rows = useMemo(() => sortSiteSolutions(shown, sort), [shown, sort]);
  const firstLayer = poses.filter((pose) => !pose.manual && (pose.paretoLayer ?? 1) === 1).length;
  const extraLayers = poses.filter((pose) => !pose.manual && (pose.paretoLayer ?? 1) > 1).length;
  const manual = poses.filter((pose) => pose.manual).length;
  const panelRef = useRef<HTMLElement>(null);
  const panel = useDraggablePanel(panelRef, {
    defaultSize: { width: 720, height: 280 },
    minSize: { width: 280, height: 120 },
    manageSize: false,
    margin: 18,
    positionKey: poses.length === 0 ? "hidden" : "shown",
    initialPosition: (bounds, size) => ({
      x: bounds.width - size.width - 18,
      y: bounds.height - size.height - 18,
    }),
  });
  if (poses.length === 0) return null;
  return <section
    ref={panelRef}
    className={["site-results", panel.dragging ? "panel-dragging" : ""].filter(Boolean).join(" ")}
    style={panel.style}
    aria-label="选址方案"
  >
    <div className="site-results-head panel-drag-handle" title="拖动选址列表" {...panel.dragHandleProps}>
      <h2>选址方案 · {firstLayer} 个可行 Pareto 站址</h2>
      <p>点击目标列标题排序，再次点击切换升降序。勾选对比可比较多个站址。点击编号可在地图中定位并高亮。</p>
      {(extraLayers > 0 || manual > 0) && <p>
        {extraLayers > 0 ? `另显示第 2、3 层 ${extraLayers} 个。` : ""}
        {manual > 0 ? `手动方案 ${manual} 个，不计入 Pareto 层。` : ""}
      </p>}
      <div className="site-sort-help">
        <button type="button" onClick={() => setSort(null)} disabled={sort === null}>恢复原顺序</button>
      </div>
    </div>
    <div className="site-results-body">
    <table>
      <thead>
        <tr>
          <th scope="col">对比</th>
          <th scope="col">编号</th>
          {columns.map(({ key, label }) => <th key={key} scope="col" aria-sort={sort?.objective === key ? sort.direction : "none"}>
            <button type="button" className="site-sort-button" onClick={() => setSort((current) => nextSiteSort(current, key))}
              aria-label={`${label}，${sort?.objective === key ? (sort.direction === "ascending" ? "当前升序，点击降序" : "当前降序，点击升序") : "点击升序排序"}`}>
              {label} <span aria-hidden="true">{sort?.objective === key ? (sort.direction === "ascending" ? "▲" : "▼") : "↕"}</span>
            </button>
          </th>)}
        </tr>
      </thead>
      <tbody>
        {rows.map(({ choice, index }) => <tr key={choice.id} aria-selected={choice.id === selectedId} onClick={() => onSelect(choice.id)}>
          <td onClick={(event) => event.stopPropagation()}>
            <input type="checkbox" aria-label={`对比方案 ${index + 1}`} checked={comparedIds.includes(choice.id)} onChange={() => onToggleCompare(choice.id)} />
          </td>
          <td><button type="button" onClick={(event) => { event.stopPropagation(); onSelect(choice.id); }}>{index + 1}</button></td>
          {columns.map(({ key }) => <td key={key}>{String(choice[key])}</td>)}
        </tr>)}
      </tbody>
    </table>
    </div>
  </section>;
}
