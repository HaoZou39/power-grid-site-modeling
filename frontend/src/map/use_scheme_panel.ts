import { useCallback, useLayoutEffect, useState } from "react";
import type { RefObject } from "react";
import { clampPanelSize, useDraggablePanel } from "./use_draggable_panel.js";
import type { PanelPosition, PanelSize } from "./use_draggable_panel.js";
import { observePanelObstacles } from "./panel_obstacles.js";
import { placeSchemeCard, placeSchemePanel, sameScreenRects, SCHEME_PANEL_TOP } from "./scheme_panel_geometry.js";
import type { SchemeAnchor, SchemeScreenRect } from "./scheme_panel_geometry.js";

export type SchemePanelBounds = SchemeScreenRect & { width: number; height: number };
export type SchemePanelPlacement = PanelPosition & { selectionKey: string };

export function useSchemePanel(
  panelRef: RefObject<HTMLElement | null>,
  { anchor, obstacles, positionRef, selectionKey, waitForAnchor = false, defaultSize, minSize }: {
    anchor: SchemeAnchor | null; obstacles: readonly SchemeScreenRect[] | null;
    positionRef: RefObject<SchemePanelPlacement | null>; selectionKey: string;
    waitForAnchor?: boolean;
    defaultSize: PanelSize; minSize: PanelSize;
  },
) {
  const panel = useDraggablePanel(panelRef, {
    defaultSize, minSize, topInset: SCHEME_PANEL_TOP,
    initialPosition: (bounds, size) => positionRef.current ?? placeSchemeCard(null, bounds, size),
  });
  const [placedFor, setPlacedFor] = useState(positionRef.current?.selectionKey ?? null);
  const placed = placedFor === selectionKey;
  const [uiObstacles, setUiObstacles] = useState<SchemeScreenRect[] | null>(null);
  const [bounds, setBounds] = useState<SchemePanelBounds | null>(null);
  useLayoutEffect(() => {
    if (!panel.desktop || placed || !panelRef.current) return;
    return observePanelObstacles(panelRef.current, (next) => {
      setUiObstacles((old) => old && sameScreenRects(old, next) ? old : next);
    });
  }, [panel.desktop, panelRef, placed]);

  useLayoutEffect(() => {
    const node = panelRef.current;
    const current = panel.getFrame();
    if (!panel.desktop || placed || !node || !current || !uiObstacles || !obstacles
      || waitForAnchor && !anchor || panel.dragging || panel.resizing) return;
    const parent = node.offsetParent;
    if (!(parent instanceof HTMLElement)) return;
    const rect = parent.getBoundingClientRect();
    // Both map projections and DOM panels arrive in viewport pixels, not local map coordinates.
    const toLocal = (box: SchemeScreenRect) => ({
      left: box.left - rect.left + parent.scrollLeft, right: box.right - rect.left + parent.scrollLeft,
      top: box.top - rect.top + parent.scrollTop, bottom: box.bottom - rect.top + parent.scrollTop,
    });
    const schemes = obstacles.map(toLocal), panels = uiObstacles.map(toLocal);
    const localAnchor = anchor ? { left: anchor.left - rect.left + parent.scrollLeft,
      x: anchor.x - rect.left + parent.scrollLeft,
      top: anchor.top - rect.top + parent.scrollTop,
      y: anchor.y - rect.top + parent.scrollTop } : null;
    const bounds = { width: parent.clientWidth, height: parent.clientHeight };
    const size = clampPanelSize(defaultSize, bounds, minSize, SCHEME_PANEL_TOP);
    const next = placeSchemePanel(schemes, panels, bounds, size, minSize, localAnchor);
    positionRef.current = { x: next.x, y: next.y, selectionKey };
    panel.setFrame(next);
    setPlacedFor(selectionKey);
  }, [panel.desktop, panel.frame, panel.dragging, panel.resizing, panel.getFrame, panel.setFrame,
    placed, obstacles, uiObstacles, panelRef, positionRef, selectionKey, anchor, waitForAnchor,
    defaultSize.width, defaultSize.height, minSize.width, minSize.height]);

  useLayoutEffect(() => {
    if (placed && panel.frame) positionRef.current = { x: panel.frame.x, y: panel.frame.y, selectionKey };
  }, [placed, panel.frame, positionRef, selectionKey]);

  const measure = useCallback(() => {
    const rect = panelRef.current?.getBoundingClientRect();
    if (!rect) return;
    const next = { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height };
    setBounds((old) => old && sameScreenRects([old], [next]) && old.width === next.width && old.height === next.height ? old : next);
  }, [panelRef]);
  useLayoutEffect(measure);
  useLayoutEffect(() => {
    const node = panelRef.current;
    if (!node) return;
    const resize = new ResizeObserver(measure);
    resize.observe(node);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      resize.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [measure, panelRef]);

  return { ...panel, bounds, placed: placed || !panel.desktop };
}
