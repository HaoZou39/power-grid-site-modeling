import { landuseEditClass } from "./toolbar_commands.js";
import type { LanduseClassId, LanduseEditClass, MapToolName } from "./toolbar_commands.js";

/** Paint uses the tool name. Clear keeps one tool and changes the target class. */
export function editingLanduseClass(tool: MapToolName, target: LanduseEditClass): LanduseClassId | null {
  return landuseEditClass(tool) ?? (tool === "landuse-clear-class" ? target : null);
}

/** Clear mode shares one tool name, so the selection identity includes the target class. */
export function landuseHighlightKey(tool: MapToolName, target: LanduseEditClass): string | null {
  const editing = editingLanduseClass(tool, target);
  if (editing === null) return null;
  return `${tool === "landuse-clear-class" ? "clear" : "paint"}:${editing}`;
}

/** A new edit selection drops the hide. Opening the same selection again does not. */
export function highlightSuppressedAfterChange(
  suppressed: boolean,
  previousKey: string | null,
  nextKey: string | null,
): boolean {
  return previousKey === nextKey && suppressed;
}

/** Manual layers stay. Auto highlight is added only while this edit selection is not suppressed. */
export function effectiveShownClasses(
  manual: Record<LanduseClassId, boolean>,
  editing: LanduseClassId | null,
  suppressed: boolean,
): Record<LanduseClassId, boolean> {
  if (editing === null || suppressed || manual[editing]) return manual;
  return { ...manual, [editing]: true };
}

/** The switch sees the map. The first click during auto highlight hides, instead of storing true. */
export function toggleLanduseVisibility(
  manual: Record<LanduseClassId, boolean>,
  editing: LanduseClassId | null,
  suppressed: boolean,
  id: LanduseClassId,
): { manual: Record<LanduseClassId, boolean>; suppressed: boolean } {
  const visible = effectiveShownClasses(manual, editing, suppressed)[id];
  if (visible) {
    return {
      manual: { ...manual, [id]: false },
      suppressed: id === editing ? true : suppressed,
    };
  }
  return {
    manual: { ...manual, [id]: true },
    suppressed: id === editing ? false : suppressed,
  };
}

/** Agent writes the manual flags and leaves a manual hide of the current edit target in place. */
export function applyAgentLanduseVisibility(
  suppressed: boolean,
  next: Record<LanduseClassId, boolean>,
): { manual: Record<LanduseClassId, boolean>; suppressed: boolean } {
  return {
    manual: {
      field: next.field,
      building: next.building,
      road: next.road,
      water: next.water,
    },
    suppressed,
  };
}
