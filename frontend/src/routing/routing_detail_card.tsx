import { useRef } from "react";
import type { SiteFrame } from "../map/site_frame";
import { useDraggablePanel } from "../map/use_draggable_panel";
import { routingHoverText } from "./routing_hover";
import type { RoutingInspection, RoutingMapState } from "./routing_layer";
import type { RoutingSolution } from "./routing_result";

export function RoutingDetailCard({ route, target, state, frame, compared, onToggleCompare, onAsk, onClose, zIndex, onBringToFront }: {
  route: RoutingSolution; target: RoutingInspection; state: RoutingMapState; frame: SiteFrame;
  compared: boolean; onToggleCompare: () => void; onAsk: () => void; onClose: () => void;
  zIndex: number; onBringToFront: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const anchor = target.anchor;
  const panel = useDraggablePanel(panelRef, {
    defaultSize: { width: 360, height: 460 }, minSize: { width: 300, height: 260 }, topInset: 148,
    resetKey: route.id,
    positionKey: anchor ? `${anchor.x}:${anchor.y}` : "results-table",
    initialPosition: (bounds, size) => ({ x: anchor ? anchor.x + 12 : (bounds.width - size.width) / 2, y: anchor ? anchor.y + 12 : 168 }),
  });
  const properties = target.kind === "tower" ? { kind: "tower", route_id: route.id, point_index: target.pointIndex }
    : target.kind === "endpoint" ? { kind: "endpoint", endpoint: target.endpoint }
    : { kind: "route", route_id: route.id };
  const detail = routingHoverText(properties, state, frame, target.spanIndex ?? null);
  const routeSummary = target.kind === "route" ? null : routingHoverText({ kind: "route", route_id: route.id }, state, frame);
  const number = state.routeNumbers?.[route.id];
  return <aside ref={panelRef} aria-label="线路详情"
    className={["scheme-card", panel.dragging ? "panel-dragging" : "", panel.resizing ? "panel-resizing" : ""].filter(Boolean).join(" ")}
    style={{ ...panel.style, zIndex }} onPointerDownCapture={onBringToFront} onFocusCapture={onBringToFront}
    onWheel={(event) => event.stopPropagation()}>
    <div className="scheme-card-head panel-drag-handle" {...panel.dragHandleProps}>
      <strong>{number ? `线路 ${number}` : "线路详情"}</strong><button type="button" className="drawer-close" onClick={onClose}>关闭</button>
    </div>
    <div className="scheme-card-content">
      <p className="hud-kicker">{target.kind === "tower" ? "塔位信息" : target.kind === "endpoint" ? "接入点信息" : "线路信息"}</p>
      {detail && <p className="routing-inspection-text">{detail}</p>}
      {routeSummary && <><p className="hud-kicker">线路目标</p><p className="routing-inspection-text">{routeSummary}</p></>}
      <div className="hud-actions">
        <button type="button" onClick={onToggleCompare}>{compared ? "移出对比" : "加入对比"}</button>
        <button type="button" onClick={onAsk}>问 AI</button>
      </div>
      <details><summary>逐档指标</summary>
        {route.spans.map((span, index) => <p className="hud-note" key={index}>第 {index + 1} 档：水平 {span.horizontal_m.toFixed(1)} m · 三维 {span.length_3d_m.toFixed(1)} m · 跨越 {span.crossing_3d_m.toFixed(1)} m</p>)}
        {!route.spans.length && <p className="hud-note">没有逐档数据。</p>}
      </details>
    </div>
    <button type="button" className="panel-resize" aria-label="调整线路详情面板大小" title="调整大小" {...panel.resizeHandleProps} />
  </aside>;
}
