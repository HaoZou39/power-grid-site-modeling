import { RoutingControls } from "./routing_controls";
import { RoutingResults } from "./routing_results";
import { RoutingDetailCard } from "./routing_detail_card";
import { RoutingComparePanel } from "./routing_compare_panel";
import type { ReactNode } from "react";
import type { RoutingController, RoutingWorkspaceProps } from "./use_routing_controller";
import "./routing.css";

export function RoutingWorkspace(props: RoutingWorkspaceProps & { state: RoutingController; resizeHandle?: ReactNode; children?: ReactNode;
  onAsk: () => void; zIndex: number; onBringToFront: () => void; compareZIndex: number; onCompareBringToFront: () => void }) {
  const { state } = props;
  return <div style={{ display: props.active ? "contents" : "none" }}>
    <RoutingControls state={state} scene={props.scene} scenes={props.scenes}
      onSceneChange={props.onSceneChange} onFocus={props.onFocus} landuseBlocked={props.landuseBlocked} resizeHandle={props.resizeHandle}>{props.children}</RoutingControls>
    {state.bundle && <RoutingResults state={state} />}
    {props.active && state.compared.length > 0 && <RoutingComparePanel routes={state.front} compared={state.compared}
      stale={state.resultStale} onClear={state.clearCompared} onSelect={state.selectRoute}
      zIndex={props.compareZIndex} onBringToFront={props.onCompareBringToFront} />}
    {props.active && props.frame && state.selected && state.inspection && state.layer && <RoutingDetailCard
      route={state.selected} target={state.inspection} state={state.layer} frame={props.frame}
      compared={state.compared.includes(state.selected.id)} onToggleCompare={() => state.toggleCompared(state.selected!.id)}
      onAsk={props.onAsk} onClose={state.closeInspection} zIndex={props.zIndex} onBringToFront={props.onBringToFront} />}
  </div>;
}
