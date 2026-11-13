import type { SchemeScreenRect } from "./scheme_panel_geometry.js";

const PANEL_OBSTACLES = ".hud-panel, .hud-top, .map-toolbar, .map-quick, .site-results, .routing-results, .agent-drawer, .layer-panel, .compare-panel, .history-drawer";

export function observePanelObstacles(node: HTMLElement, publish: (boxes: SchemeScreenRect[]) => void): () => void {
  const root = node.closest(".map-app");
  if (!root) throw new Error("Scheme details must be mounted in .map-app");
  let pending = 0;
  const observed = new Set<Element>();
  const resize = new ResizeObserver(schedule);

  function measure() {
    pending = 0;
    const panels = [...root!.querySelectorAll<HTMLElement>(PANEL_OBSTACLES)]
      .filter((element) => element !== node && !element.contains(node));
    const current = new Set<Element>([root!, ...panels]);
    for (const element of observed) {
      if (!current.has(element)) { resize.unobserve(element); observed.delete(element); }
    }
    // Re-observing unchanged nodes would retrigger ResizeObserver even while idle.
    for (const element of current) {
      if (!observed.has(element)) { resize.observe(element); observed.add(element); }
    }
    publish(panels.flatMap((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display === "none" || style.visibility === "hidden" || !rect.width || !rect.height ? []
        : [{ left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }];
    }));
  }

  function schedule() { if (!pending) pending = requestAnimationFrame(measure); }
  const mutation = new MutationObserver((changes) => {
    if (changes.some(({ target, type }) => !node.contains(target) && (target === root
      || target instanceof Element && target.closest(PANEL_OBSTACLES)
      || type === "childList" && target instanceof Element && !target.closest(".map-viewport-shell, .scheme-connector")))) schedule();
  });
  mutation.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ["style", "class", "hidden"] });
  window.addEventListener("resize", schedule);
  window.addEventListener("scroll", schedule, true);
  measure();
  return () => {
    cancelAnimationFrame(pending);
    mutation.disconnect();
    resize.disconnect();
    window.removeEventListener("resize", schedule);
    window.removeEventListener("scroll", schedule, true);
  };
}
