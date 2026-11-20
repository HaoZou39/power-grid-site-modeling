import type { SchemeProjection, SchemeScreenRect } from "../map/scheme_panel_geometry";
import { SchemeConnector } from "../map/scheme_connector";
import type { WorkspaceBounds } from "../map/scheme_connector";
import { useRef } from "react";
import type { RefObject } from "react";
import type { SchemePanelPlacement } from "../map/use_scheme_panel";
import type { SiteFrame } from "../map/site_frame";
import { useSchemePanel } from "../map/use_scheme_panel";
import { routingHoverText } from "./routing_hover";
import type { RoutingInspection, RoutingMapState } from "./routing_layer";
import { formatFinite, visibleSpanColumns } from "./routing_result";
import type { RoutingSolution } from "./routing_result";

export function RoutingDetailCard({ positionRef, obstacles, projection, workspaceBounds, selectionKey, route, target, state, frame, compared, onToggleCompare, onAsk, onClose, zIndex, onBringToFront }: {
  positionRef: RefObject<SchemePanelPlacement | null>;
  obstacles: readonly SchemeScreenRect[] | null;
  projection: SchemeProjection | null; workspaceBounds: WorkspaceBounds | null;
  selectionKey: string;
  route: RoutingSolution; target: RoutingInspection; state: RoutingMapState; frame: SiteFrame;
  compared: boolean; onToggleCompare: () => void; onAsk: () => void; onClose: () => void;
  zIndex: number; onBringToFront: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const currentProjection = projection?.target.schemeId === route.id ? projection : null;
  const anchor = currentProjection?.anchor ?? null;
  const panel = useSchemePanel(panelRef, {
    defaultSize: { width: 360, height: 460 }, minSize: { width: 300, height: 280 },
    anchor, obstacles, positionRef, selectionKey, waitForAnchor: true,
  });
  const properties = target.kind === "tower" ? { kind: "tower", route_id: route.id, point_index: target.pointIndex }
    : target.kind === "endpoint" ? { kind: "endpoint", endpoint: target.endpoint }
    : { kind: "route", route_id: route.id };
  const detail = routingHoverText(properties, state, frame, target.spanIndex ?? null);
  const routeSummary = target.kind === "route" ? null : routingHoverText({ kind: "route", route_id: route.id }, state, frame);
  const number = state.routeNumbers?.[route.id];
  const spanColumns = visibleSpanColumns(route.spans);
  return <><SchemeConnector target={currentProjection?.target ?? null} cardBounds={panel.bounds} workspaceBounds={workspaceBounds} visible={true} /><aside ref={panelRef} aria-label="线路详情"
    className={["scheme-card scheme-detail-panel", panel.dragging ? "panel-dragging" : "", panel.resizing ? "panel-resizing" : ""].filter(Boolean).join(" ")}
    style={{ ...panel.style, zIndex, visibility: panel.placed ? undefined : "hidden" }} onPointerDownCapture={onBringToFront} onFocusCapture={onBringToFront}
    onWheel={(event) => event.stopPropagation()}>
    <div className="scheme-card-head panel-drag-handle" {...panel.dragHandleProps}>
      <strong>{number ? `线路 ${number}` : "线路详情"}</strong><button type="button" className="drawer-close" onClick={onClose}>关闭</button>
    </div>
    <div className="scheme-card-content">
      <p className="hud-kicker">{target.kind === "tower" ? "塔位信息" : target.kind === "endpoint" ? "接入点信息" : "线路信息"}</p>
      {detail && <p className="routing-inspection-text">{detail}</p>}
      {routeSummary && <><p className="hud-kicker">线路目标</p><p className="routing-inspection-text">{routeSummary}</p></>}
      <div className="hud-actions">
        <button type="button" disabled={!route.is_feasible} onClick={onToggleCompare}>{compared ? "移出对比" : "加入对比"}</button>
        <button type="button" onClick={onAsk}>问 AI</button>
      </div>
      {spanColumns.length > 0 && <details><summary>逐档指标</summary>
        <table><thead><tr><th>档</th>{spanColumns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>
          {route.spans.map((span, index) => <tr key={index}><td>{index + 1}</td>{spanColumns.map((column) => <td key={column.key}>{formatFinite(span[column.key])}</td>)}</tr>)}
        </tbody></table>
      </details>}
    </div>
    <button type="button" className="panel-resize" aria-label="调整线路详情面板大小" title="调整大小" {...panel.resizeHandleProps} />
  </aside></>;
}
