export type FloatingPanelId = "agent" | "gis" | "scheme" | "compare";

const FLOATING_PANEL_Z_INDEX_BASE = 20;

export function bringPanelToFront(
  order: readonly FloatingPanelId[],
  id: FloatingPanelId,
): readonly FloatingPanelId[] {
  if (order[order.length - 1] === id) return order;
  return [...order.filter((item) => item !== id), id];
}

export function floatingPanelZIndex(
  order: readonly FloatingPanelId[],
  id: FloatingPanelId,
): number {
  return FLOATING_PANEL_Z_INDEX_BASE + Math.max(order.indexOf(id), 0);
}
