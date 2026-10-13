import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent, RefObject } from "react";

export type PanelPosition = { x: number; y: number };
export type PanelSize = { width: number; height: number };
export type PanelFrame = PanelPosition & PanelSize;

type DraggablePanelOptions = {
  defaultSize: PanelSize;
  minSize: PanelSize;
  initialPosition: (bounds: PanelSize, size: PanelSize) => PanelPosition;
  resetKey?: string;
  positionKey?: string;
  margin?: number;
  topInset?: number;
};

const DEFAULT_MARGIN = 8;
const DESKTOP_QUERY = "(min-width: 901px)";

export function clampPanelSize(
  size: PanelSize,
  bounds: PanelSize,
  minimum: PanelSize,
  topInset = 0,
  margin = DEFAULT_MARGIN,
): PanelSize {
  const maxWidth = Math.max(1, bounds.width - margin * 2);
  const maxHeight = Math.max(1, bounds.height - Math.max(topInset, margin) - margin);
  return {
    width: Math.min(Math.max(size.width, Math.min(minimum.width, maxWidth)), maxWidth),
    height: Math.min(Math.max(size.height, Math.min(minimum.height, maxHeight)), maxHeight),
  };
}

export function clampPanelPosition(
  position: PanelPosition,
  size: PanelSize,
  bounds: PanelSize,
  topInset = 0,
  margin = DEFAULT_MARGIN,
): PanelPosition {
  const minY = Math.max(topInset, margin);
  return {
    x: Math.min(Math.max(position.x, margin), Math.max(margin, bounds.width - size.width - margin)),
    y: Math.min(Math.max(position.y, minY), Math.max(minY, bounds.height - size.height - margin)),
  };
}

export function clampPanelFrame(
  frame: PanelFrame,
  bounds: PanelSize,
  minimum: PanelSize,
  topInset = 0,
  margin = DEFAULT_MARGIN,
): PanelFrame {
  const size = clampPanelSize(frame, bounds, minimum, topInset, margin);
  const position = clampPanelPosition(frame, size, bounds, topInset, margin);
  return { ...position, ...size };
}

export function clampPanelResize(
  frame: PanelFrame,
  bounds: PanelSize,
  minimum: PanelSize,
  margin = DEFAULT_MARGIN,
): PanelFrame {
  const maxWidth = Math.max(1, bounds.width - frame.x - margin);
  const maxHeight = Math.max(1, bounds.height - frame.y - margin);
  return {
    ...frame,
    width: Math.min(Math.max(frame.width, Math.min(minimum.width, maxWidth)), maxWidth),
    height: Math.min(Math.max(frame.height, Math.min(minimum.height, maxHeight)), maxHeight),
  };
}
export function useDraggablePanel<T extends HTMLElement>(
  panelRef: RefObject<T | null>,
  {
    defaultSize,
    minSize,
    initialPosition,
    resetKey = "",
    positionKey = "",
    margin = DEFAULT_MARGIN,
    topInset = 0,
  }: DraggablePanelOptions,
) {
  const [desktop, setDesktop] = useState(() => (
    typeof window === "undefined" || window.matchMedia(DESKTOP_QUERY).matches
  ));
  const [frame, setFrameState] = useState<PanelFrame | null>(null);
  const [dragging, setDragging] = useState(false);
  const [resizing, setResizing] = useState(false);
  const frameRef = useRef(frame);
  const initialPositionRef = useRef(initialPosition);
  initialPositionRef.current = initialPosition;
  const manuallyPositioned = useRef(false);
  const lastResetKey = useRef(resetKey);
  const lastPositionKey = useRef(positionKey);
  const gesture = useRef<{
    kind: "move" | "resize";
    pointerId: number;
    clientX: number;
    clientY: number;
    frame: PanelFrame;
  } | null>(null);

  const setFrame = useCallback((next: PanelFrame) => {
    const current = frameRef.current;
    if (
      current
      && current.x === next.x
      && current.y === next.y
      && current.width === next.width
      && current.height === next.height
    ) return;
    frameRef.current = next;
    setFrameState(next);
  }, []);

  const boundsFor = useCallback((node: HTMLElement): PanelSize => {
    const parent = node.offsetParent;
    if (parent instanceof HTMLElement) {
      return {
        width: parent.clientWidth || window.innerWidth,
        height: parent.clientHeight || window.innerHeight,
      };
    }
    return { width: window.innerWidth, height: window.innerHeight };
  }, []);

  const defaultFrame = useCallback((node: HTMLElement, size = defaultSize): PanelFrame => {
    const bounds = boundsFor(node);
    const constrainedSize = clampPanelSize(size, bounds, minSize, topInset, margin);
    const position = clampPanelPosition(
      initialPositionRef.current(bounds, constrainedSize),
      constrainedSize,
      bounds,
      topInset,
      margin,
    );
    return { ...position, ...constrainedSize };
  }, [
    boundsFor,
    defaultSize.height,
    defaultSize.width,
    margin,
    minSize.height,
    minSize.width,
    topInset,
  ]);

  const captureFrame = useCallback((): PanelFrame | null => {
    const node = panelRef.current;
    if (!node) return null;
    const rect = node.getBoundingClientRect();
    const bounds = boundsFor(node);
    const next = clampPanelFrame(
      {
        x: node.offsetLeft,
        y: node.offsetTop,
        width: rect.width,
        height: rect.height,
      },
      bounds,
      minSize,
      topInset,
      margin,
    );
    setFrame(next);
    return next;
  }, [
    boundsFor,
    margin,
    minSize.height,
    minSize.width,
    panelRef,
    setFrame,
    topInset,
  ]);

  const keepInBounds = useCallback(() => {
    const node = panelRef.current;
    if (!node || !desktop) return;
    const current = frameRef.current ?? captureFrame();
    if (!current) return;
    setFrame(clampPanelFrame(current, boundsFor(node), minSize, topInset, margin));
  }, [
    boundsFor,
    captureFrame,
    desktop,
    margin,
    minSize.height,
    minSize.width,
    panelRef,
    setFrame,
    topInset,
  ]);

  useEffect(() => {
    const media = window.matchMedia(DESKTOP_QUERY);
    const update = () => setDesktop(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useLayoutEffect(() => {
    const node = panelRef.current;
    if (!node || !desktop) return;
    const reset = frameRef.current === null || lastResetKey.current !== resetKey;
    const reposition = lastPositionKey.current !== positionKey && !manuallyPositioned.current;
    if (reset) {
      manuallyPositioned.current = false;
      setFrame(defaultFrame(node));
    } else if (reposition) {
      const current = frameRef.current;
      if (current) setFrame(defaultFrame(node, { width: current.width, height: current.height }));
    } else {
      keepInBounds();
    }
    lastResetKey.current = resetKey;
    lastPositionKey.current = positionKey;
  }, [defaultFrame, desktop, keepInBounds, panelRef, positionKey, resetKey, setFrame]);

  useLayoutEffect(() => {
    const node = panelRef.current;
    if (!node || !desktop) return;
    const parent = node.offsetParent;
    window.addEventListener("resize", keepInBounds);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(keepInBounds);
    if (parent instanceof HTMLElement) observer?.observe(parent);
    return () => {
      window.removeEventListener("resize", keepInBounds);
      observer?.disconnect();
    };
  }, [desktop, keepInBounds, panelRef]);

  function begin(kind: "move" | "resize", event: ReactPointerEvent<HTMLElement>) {
    if (!desktop || !event.isPrimary || event.button !== 0) return;
    if (
      kind === "move"
      && (event.target as HTMLElement).closest("button, a, input, select, textarea, [data-panel-drag-ignore]")
    ) return;
    const current = frameRef.current ?? captureFrame();
    if (!current) return;
    event.preventDefault();
    event.stopPropagation();
    if (kind === "move") manuallyPositioned.current = true;
    gesture.current = {
      kind,
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      frame: current,
    };
    setDragging(kind === "move");
    setResizing(kind === "resize");
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      gesture.current = null;
      setDragging(false);
      setResizing(false);
    }
  }

  function follow(event: ReactPointerEvent<HTMLElement>) {
    const active = gesture.current;
    const node = panelRef.current;
    if (!active || !node || active.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    const dx = event.clientX - active.clientX;
    const dy = event.clientY - active.clientY;
    const bounds = boundsFor(node);
    if (active.kind === "move") {
      setFrame(clampPanelFrame(
        { ...active.frame, x: active.frame.x + dx, y: active.frame.y + dy },
        bounds,
        minSize,
        topInset,
        margin,
      ));
      return;
    }
    setFrame(clampPanelResize(
      { ...active.frame, width: active.frame.width + dx, height: active.frame.height + dy },
      bounds,
      minSize,
      margin,
    ));
  }

  function end(event: ReactPointerEvent<HTMLElement>) {
    const active = gesture.current;
    if (!active || active.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    gesture.current = null;
    setDragging(false);
    setResizing(false);
    try {
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    } catch {
      // Pointer capture can already be gone after cancel/lost capture.
    }
  }

  const style: CSSProperties | undefined = desktop && frame
    ? {
        position: "absolute",
        left: frame.x,
        top: frame.y,
        right: "auto",
        bottom: "auto",
        width: frame.width,
        height: frame.height,
        margin: 0,
      }
    : undefined;

  return {
    style,
    dragging,
    resizing,
    dragHandleProps: {
      onPointerDown: (event: ReactPointerEvent<HTMLElement>) => begin("move", event),
      onPointerMove: follow,
      onPointerUp: end,
      onPointerCancel: end,
      onLostPointerCapture: end,
    },
    resizeHandleProps: {
      onPointerDown: (event: ReactPointerEvent<HTMLElement>) => begin("resize", event),
      onPointerMove: follow,
      onPointerUp: end,
      onPointerCancel: end,
      onLostPointerCapture: end,
    },
  };
}