import { useRef } from "react";
import type { KeyboardEvent, PointerEvent } from "react";

const MIN_WIDTH = 260;
const MAX_WIDTH = 720;

export function workPanelMaxWidth(viewportWidth: number) {
  return Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, viewportWidth - 200));
}

export function clampWorkPanelWidth(width: number, viewportWidth: number) {
  return Math.min(workPanelMaxWidth(viewportWidth), Math.max(MIN_WIDTH, width));
}

export function WorkPanelResize({ width, viewportWidth, onChange }: {
  width: number; viewportWidth: number; onChange: (width: number) => void;
}) {
  const gesture = useRef<{ pointerId: number; x: number; width: number } | null>(null);
  const maximum = workPanelMaxWidth(viewportWidth);

  function onPointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (!event.isPrimary || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    gesture.current = { pointerId: event.pointerId, x: event.clientX, width };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function onPointerMove(event: PointerEvent<HTMLButtonElement>) {
    const start = gesture.current;
    if (!start || start.pointerId !== event.pointerId) return;
    event.stopPropagation();
    onChange(clampWorkPanelWidth(start.width + event.clientX - start.x, viewportWidth));
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const next = event.key === "ArrowLeft" ? width - 16 : event.key === "ArrowRight" ? width + 16
      : event.key === "Home" ? MIN_WIDTH : event.key === "End" ? maximum : null;
    if (next === null) return;
    event.preventDefault();
    event.stopPropagation();
    onChange(clampWorkPanelWidth(next, viewportWidth));
  }

  return <button type="button" className="work-panel-resizer" role="separator"
    aria-label="调整工作栏宽度" aria-orientation="vertical"
    aria-valuemin={MIN_WIDTH} aria-valuemax={maximum} aria-valuenow={Math.round(width)}
    title="拖动调整工作栏宽度，也可使用左右方向键"
    onPointerDown={onPointerDown} onPointerMove={onPointerMove}
    onPointerUp={() => { gesture.current = null; }}
    onPointerCancel={() => { gesture.current = null; }}
    onLostPointerCapture={() => { gesture.current = null; }} onKeyDown={onKeyDown} />;
}
