import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { createRoot } from "react-dom/client";
import type { SchemePanelPlacement } from "../src/map/use_scheme_panel";
import { useSchemePanel } from "../src/map/use_scheme_panel";
import "../src/styles.css";

const blocked = [{ left: -1000, top: -1000, right: 3000, bottom: 3000 }];
const scheme = { left: 650, top: 330, right: 750, bottom: 540 };
const projectedScheme = { left: scheme.left + 30, top: scheme.top + 20, right: scheme.right + 30, bottom: scheme.bottom + 20 };
const initiallyBlocked = new URLSearchParams(window.location.search).get("blocked") !== "0";
const delayedProjection = new URLSearchParams(window.location.search).has("delayed");
const panels = [".hud-panel", ".site-results", ".agent-drawer", ".layer-panel", ".compare-panel", ".history-drawer", "[data-scheme]"];
type Scenario = { id: string; blocked: boolean; click: number; dx: number; dy: number };
let change: (value: Scenario) => void;

function App() {
  const [scenario, setScenario] = useState<Scenario>({ id: "A", blocked: initiallyBlocked, click: 0, dx: 0, dy: 0 });
  const [projection, setProjection] = useState({ click: 0, dx: 0, dy: 0 });
  const [projected, setProjected] = useState(!delayedProjection);
  const [anchorReady, setAnchorReady] = useState(!delayedProjection);
  const positionRef = useRef<SchemePanelPlacement | null>(null);
  useEffect(() => {
    if (!delayedProjection) return;
    const timeout = setTimeout(() => setProjected(true), 500);
    const anchorTimeout = setTimeout(() => setAnchorReady(true), 700);
    return () => { clearTimeout(timeout); clearTimeout(anchorTimeout); };
  }, []);
  useEffect(() => {
    if (scenario.id === "closed") return;
    const timeout = setTimeout(() => setProjection({ click: scenario.click, dx: scenario.dx, dy: scenario.dy }), 80);
    return () => clearTimeout(timeout);
  }, [scenario.click, scenario.dx, scenario.dy, scenario.id]);
  change = setScenario;
  return <div className="map-app" style={{ width: "calc(100vw - 60px)", height: "calc(100vh - 40px)", margin: "20px 30px" }}>
    <div className="map-viewport-shell" />
    <div className="hud-panel" style={{ left: 0, top: 150, width: 160, bottom: 0 }} />
    <div className="site-results" style={{ right: 0, top: 150, width: 160, bottom: 0 }} />
    <div className="agent-drawer" style={{ right: 0, top: 150, width: 160, height: "80vh" }} />
    <div className="layer-panel" style={{ right: 0, top: 150, width: 160, height: "80vh" }} />
    <div className="compare-panel" style={{ right: 0, left: "auto", top: 150, width: 160, height: "80vh" }} />
    <div className="history-drawer" style={{ right: 0, left: "auto", top: 150, width: 160, height: "80vh" }} />
    {!scenario.blocked && <div data-scheme style={{ position: "absolute", left: scheme.left + scenario.dx, top: scheme.top + scenario.dy,
      width: scheme.right - scheme.left, height: scheme.bottom - scheme.top }} />}
    {scenario.id !== "closed" && <Panel scenario={scenario} projection={projection} projected={projected}
      anchorReady={anchorReady} positionRef={positionRef} />}
  </div>;
}

function Panel({ scenario, projection, projected, anchorReady, positionRef }: {
  scenario: Scenario; projection: { click: number; dx: number; dy: number };
  projected: boolean; anchorReady: boolean;
  positionRef: RefObject<SchemePanelPlacement | null>;
}) {
  const ref = useRef<HTMLElement>(null);
  const current = projected && projection.click === scenario.click;
  const shifted = { left: projectedScheme.left + projection.dx, top: projectedScheme.top + projection.dy,
    right: projectedScheme.right + projection.dx, bottom: projectedScheme.bottom + projection.dy };
  const panel = useSchemePanel(ref, {
    anchor: !current || !anchorReady ? null : scenario.id === "A"
      ? { left: shifted.left, top: shifted.top, x: shifted.right, y: shifted.bottom }
      : { left: 900 + projection.dx, top: 400 + projection.dy,
        x: 1000 + projection.dx, y: 600 + projection.dy },
    obstacles: current ? scenario.blocked ? blocked : [shifted] : null, positionRef,
    selectionKey: `site:${scenario.id}:${scenario.click}`, waitForAnchor: true,
    defaultSize: { width: 360, height: 540 }, minSize: { width: 300, height: 280 },
  });
  return <aside ref={ref} className="scheme-card scheme-detail-panel"
    style={{ ...panel.style, visibility: panel.placed ? undefined : "hidden" }} data-id={scenario.id}>
    <div data-drag className="panel-drag-handle" {...panel.dragHandleProps}>Drag</div>
  </aside>;
}

createRoot(document.getElementById("root")!).render(<App />);
const pause = () => new Promise((resolve) => setTimeout(resolve, 300));
const box = (selector: string) => document.querySelector(selector)!.getBoundingClientRect();
const position = () => {
  const rect = box(".scheme-detail-panel");
  return { x: rect.left, y: rect.top, width: rect.width, height: rect.height };
};
const samePosition = (a: ReturnType<typeof position>, b: ReturnType<typeof position>) =>
  a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height;
const separated = (a: DOMRect, b: DOMRect) => a.right + 12 <= b.left || a.left >= b.right + 12
  || a.bottom + 12 <= b.top || a.top >= b.bottom + 12;
const check = (condition: boolean, message: string) => { if (!condition) throw new Error(message); };

(async () => {
  try {
    await pause();
    if (delayedProjection) {
      check(getComputedStyle(document.querySelector(".scheme-detail-panel")!).visibility === "hidden",
        "panel appeared before the current map projection arrived");
      await pause();
      check(getComputedStyle(document.querySelector(".scheme-detail-panel")!).visibility === "hidden",
        "panel appeared before the selected anchor arrived");
      await pause();
    }
    const initial = position();
    check(getComputedStyle(document.querySelector(".scheme-detail-panel")!).visibility === "visible",
      "panel did not appear after projection arrived");
    check(initiallyBlocked ? initial.width === 300 && initial.height === 280
      : initial.width === 360 && initial.height === 540,
    "detail size did not match the available page space");
    if (!initiallyBlocked) check(panels.every((selector) => separated(box(".scheme-detail-panel"), box(selector))),
      "initial placement overlapped a scheme or information panel despite available space");
    check(!document.querySelector(".detail-below-map"), "details moved below the map");
    const mapBefore = box(".map-viewport-shell").height;
    change({ id: "B", blocked: false, click: 1, dx: 0, dy: 0 });
    await pause();
    check(!samePosition(initial, position()), "switching schemes did not reposition the panel");
    change({ id: "A", blocked: false, click: 2, dx: 0, dy: 0 });
    await pause();
    if (!initiallyBlocked) check(samePosition(initial, position()),
      "returning to the original selection changed its placement");
    const atA = position();
    const agent = document.querySelector<HTMLElement>(".agent-drawer")!;
    agent.style.left = `${atA.x - box(".map-app").left}px`;
    agent.style.right = "auto";
    agent.style.top = `${atA.y - box(".map-app").top}px`;
    await pause();
    check(samePosition(atA, position()), "another panel moved the details");
    agent.style.left = "";
    agent.style.right = "0";
    agent.style.top = "150px";

    const handle = document.querySelector<HTMLElement>("[data-drag]")!;
    handle.setPointerCapture = () => {};
    handle.hasPointerCapture = () => false;
    const fire = (type: string, x: number, y: number, buttons: number) => handle.dispatchEvent(new PointerEvent(type, {
      bubbles: true, cancelable: true, pointerId: 7, isPrimary: true, button: 0, buttons, clientX: x, clientY: y,
    }));
    fire("pointerdown", atA.x + 20, atA.y + 20, 1);
    fire("pointermove", atA.x + 60, atA.y + 50, 1);
    fire("pointerup", atA.x + 60, atA.y + 50, 0);
    await pause();
    const moved = position();
    check(moved.x === atA.x + 40 && moved.y === atA.y + 30, "manual dragging did not move the panel");
    change({ id: "A", blocked: false, click: 3, dx: 0, dy: 0 });
    await pause();
    check(!samePosition(moved, position()), "clicking the same scheme kept a stale dragged position");
    check(panels.every((selector) => separated(box(".scheme-detail-panel"), box(selector))),
      "clicking the same scheme overlapped visible content");

    const prePan = position();
    const shift = { dx: prePan.x + 100 - projectedScheme.left, dy: prePan.y + 100 - projectedScheme.top };
    change({ id: "A", blocked: false, click: 3, ...shift });
    await pause();
    check(samePosition(prePan, position()), "map dragging moved the already open detail panel");
    check(!separated(box(".scheme-detail-panel"), box("[data-scheme]")),
      "map drag did not reproduce the overlap before a new click");
    change({ id: "A", blocked: false, click: 4, ...shift });
    await pause();
    check(!samePosition(prePan, position()), "clicking after map drag kept the old detail position");
    check(panels.every((selector) => separated(box(".scheme-detail-panel"), box(selector))),
      "clicking after map drag overlapped a scheme or information panel");

    change({ id: "closed", blocked: false, click: 4, dx: 0, dy: 0 });
    await pause();
    check(!document.querySelector(".scheme-detail-panel"), "details did not close");
    change({ id: "A", blocked: false, click: 5, dx: 0, dy: 0 });
    await new Promise((resolve) => setTimeout(resolve, 20));
    check(getComputedStyle(document.querySelector(".scheme-detail-panel")!).visibility === "hidden",
      "reopening used a stale map projection before the new request completed");
    await pause();
    check(samePosition(prePan, position()), "reopening after map drag did not recompute the empty placement");
    check(panels.every((selector) => separated(box(".scheme-detail-panel"), box(selector))),
      "reopening after map drag overlapped visible content");
    check(box(".map-viewport-shell").height === mapBefore, "details changed the map area");
    document.body.dataset.result = "PASS";
  } catch (error) {
    document.body.dataset.result = `FAIL: ${String(error)}`;
  }
})();
