import { RoutingControls } from "./routing_controls";
import { RoutingResults } from "./routing_results";
import type { ReactNode } from "react";
import type { RoutingController, RoutingWorkspaceProps } from "./use_routing_controller";
import "./routing.css";

export function RoutingWorkspace(props: RoutingWorkspaceProps & { state: RoutingController; resizeHandle?: ReactNode; children?: ReactNode }) {
  const { state } = props;
  return <div style={{ display: props.active ? "contents" : "none" }}>
    <RoutingControls state={state} scene={props.scene} scenes={props.scenes}
      onSceneChange={props.onSceneChange} onFocus={props.onFocus} landuseBlocked={props.landuseBlocked} resizeHandle={props.resizeHandle}>{props.children}</RoutingControls>
    {state.bundle && <RoutingResults state={state} />}
  </div>;
}
