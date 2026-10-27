import { RoutingControls } from "./routing_controls";
import { RoutingResults } from "./routing_results";
import { useRoutingController } from "./use_routing_controller";
import type { RoutingWorkspaceProps } from "./use_routing_controller";
import "./routing.css";

export function RoutingWorkspace(props: RoutingWorkspaceProps) {
  const state = useRoutingController(props);
  return <div style={{ display: props.active ? "contents" : "none" }}>
    <RoutingControls state={state} scene={props.scene} scenes={props.scenes}
      onSceneChange={props.onSceneChange} onFocus={props.onFocus} />
    {state.bundle && <RoutingResults state={state} />}
  </div>;
}
