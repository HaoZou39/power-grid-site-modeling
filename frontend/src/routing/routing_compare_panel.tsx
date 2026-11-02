import { useRef } from "react";
import { useDraggablePanel } from "../map/use_draggable_panel";
import { ROUTING_COMPARE_AXES, routingComparison } from "./routing_compare";
import type { RoutingSolution } from "./routing_result";

export function RoutingComparePanel({ routes, compared, stale, onClear, onSelect, zIndex, onBringToFront }: {
  routes: readonly RoutingSolution[]; compared: readonly string[]; stale: boolean;
  onClear: () => void; onSelect: (id: string) => void; zIndex: number; onBringToFront: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const panel = useDraggablePanel(panelRef, {
    defaultSize: { width: 680, height: 400 }, minSize: { width: 420, height: 260 }, topInset: 148,
    initialPosition: (bounds, size) => ({ x: Math.max(18, (bounds.width - size.width) / 2), y: bounds.height - size.height - 18 }),
  });
  const series = routingComparison(routes, compared);
  const width = 680, height = 240, left = 70, right = 70, top = 15, bottom = 48;
  const xAt = (index: number) => left + index * (width - left - right) / (ROUTING_COMPARE_AXES.length - 1);
  const yAt = (value: number) => height - bottom - value * (height - top - bottom);
  return <section ref={panelRef} aria-label="线路对比"
    className={["compare-panel", panel.dragging ? "panel-dragging" : "", panel.resizing ? "panel-resizing" : ""].filter(Boolean).join(" ")}
    style={{ ...panel.style, zIndex }} onPointerDownCapture={onBringToFront} onFocusCapture={onBringToFront}
    onWheel={(event) => event.stopPropagation()}>
    <div className="scheme-card-head panel-drag-handle" {...panel.dragHandleProps}>
      <strong>线路对比</strong><button type="button" className="drawer-close" onClick={onClear}>清空</button>
    </div>
    <div className="compare-panel-body">
      <p className="hud-note">每条折线代表一条线路。四项指标均越小越好，线越低越优；每项按全部可行 Pareto 线路分别归一化，不能跨指标比较绝对数值。</p>
      {stale && <p className="hud-note">当前配置已修改，图中显示的是修改前的线路指标。</p>}
      {series.length < 2 && <p className="hud-note">再加入一条线路，即可叠加比较。</p>}
      <svg className="compare-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet"
        role="img" aria-label="线路四目标折线对比">
        {ROUTING_COMPARE_AXES.map(({ label }, index) => <g key={label}>
          <line x1={xAt(index)} y1={top} x2={xAt(index)} y2={height - bottom} stroke="currentColor" opacity="0.28" />
          <text x={xAt(index)} y={height - 16} textAnchor="middle" fill="currentColor" fontSize="18">{label}</text>
        </g>)}
        {series.map((line) => <g key={line.id}>
          <polyline points={line.values.map((value, index) => `${xAt(index)},${yAt(value)}`).join(" ")}
            fill="none" stroke={line.color} strokeWidth="2.5" />
          {line.values.map((value, index) => <circle key={index} cx={xAt(index)} cy={yAt(value)} r="3.5" fill={line.color} />)}
        </g>)}
      </svg>
      <div className="compare-legend">{series.map((line) => {
        const number = routes.findIndex((route) => route.id === line.id) + 1;
        return <button type="button" className="routing-compare-legend-item" key={line.id} onClick={() => onSelect(line.id)}>
          <i style={{ background: line.color }} />线路 {number}</button>;
      })}</div>
    </div>
    <button type="button" className="panel-resize" aria-label="调整线路对比面板大小" title="调整大小" {...panel.resizeHandleProps} />
  </section>;
}
