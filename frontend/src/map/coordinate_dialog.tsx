import { useId, useRef, type ReactNode } from "react";
import { useDraggablePanel } from "./use_draggable_panel";

export function CoordinateDialog({ title, children, onClose }: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const titleId = useId();
  const panelRef = useRef<HTMLElement>(null);
  const panel = useDraggablePanel(panelRef, {
    defaultSize: { width: 320, height: 200 },
    minSize: { width: 220, height: 120 },
    manageSize: false,
    topInset: 148,
    initialPosition: () => ({
      x: panelRef.current?.offsetLeft ?? 0,
      y: panelRef.current?.offsetTop ?? 0,
    }),
  });
  return (
    <section ref={panelRef} className={`coordinate-dialog${panel.dragging ? " panel-dragging" : ""}`}
      style={panel.style} role="dialog" aria-labelledby={titleId} onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        event.stopPropagation();
        onClose();
      }}>
      <div className="coordinate-dialog-head panel-drag-handle" {...panel.dragHandleProps}>
        <h2 id={titleId}>{title}</h2><button type="button" className="drawer-close" aria-label={`关闭${title}`} onClick={onClose}>×</button>
      </div>
      <div className="coordinate-dialog-body">{children}</div>
    </section>
  );
}
