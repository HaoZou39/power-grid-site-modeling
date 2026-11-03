import type { ToolbarCommand } from "../map/toolbar_commands.js";
import type { RoutingTool } from "./routing_interaction.js";

export type RoutingToolbar = {
  busy: boolean;
  editDisabled: boolean;
  endpointsLocked?: boolean;
  allowStopPrepare?: boolean;
  picking: RoutingTool | null;
  beginPick: (kind: RoutingTool) => void;
};

/** Keep shared scene tools, but never expose station-specific edits in routing mode. */
export function routingToolbarCommands(commands: ToolbarCommand[], routing: RoutingToolbar): ToolbarCommand[] {
  const stationOnly = new Set(["exclusion", "exclusion-box", "feasible", "feasible-box", "origin", "pose-add", "adjust"]);
  const locked = new Set(["new-scene", "import-data", "prepare-scene", "import-case", "erase", "landuse-field", "landuse-building", "landuse-road", "landuse-water", "landuse-clear-water"]);
  const shared = commands.filter((item) => !stationOnly.has(item.id)).map((item) => {
    const lockedDuringTask = routing.busy && locked.has(item.id) && !(item.id === "prepare-scene" && routing.allowStopPrepare);
    return { ...item, label: item.id === "focus-site" ? "定位选线区" : item.label,
      active: item.id === "pan" ? item.active && routing.picking === null : item.active,
      disabled: item.disabled || lockedDuringTask };
  });
  const picks = ([
    ["start", "点选起点"], ["end", "点选终点"],
    ["adjust-endpoints", "调整起终点"],
    ["no_tower", "画圈"], ["no_tower-box", "方框"],
    ["no_cross", "画圈"], ["no_cross-box", "方框"],
  ] as const).map(([kind, label]): ToolbarCommand => ({
    id: `routing-${kind}`, group: "编辑", label, active: routing.picking === kind,
    quick: false, disabled: routing.busy || routing.editDisabled || (!!routing.endpointsLocked && ["start", "end", "adjust-endpoints"].includes(kind)), run: () => routing.beginPick(kind),
  }));
  return [...shared, ...picks];
}
