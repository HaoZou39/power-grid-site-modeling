/** Screen-space padding that keeps the site frame inside the map area not covered by chrome. */

/** Gap between the site frame and the chrome that covers the map. */
export const SITE_VIEW_CLEARANCE_PX = 12;

/** Inner size reserved so fitBounds still has a frame to show on a very small map. */
const MIN_INNER_PX = 64;

export type ViewportPadding = { top: number; right: number; bottom: number; left: number };

export type ScreenBox = { left: number; top: number; right: number; bottom: number };

export type ScreenObstruction = {
  box: ScreenBox;
  /** False when the element is in normal flow and does not cover the map. */
  overlays: boolean;
};

export function viewportPadding(
  mapBox: ScreenBox,
  obstructions: readonly ScreenObstruction[],
  clearance = SITE_VIEW_CLEARANCE_PX,
): ViewportPadding {
  const padding: ViewportPadding = { top: clearance, right: clearance, bottom: clearance, left: clearance };
  for (const item of obstructions) {
    if (!item.overlays) continue;
    const overlap = intersection(mapBox, item.box);
    if (!overlap) continue;
    const edge = nearestEdge(mapBox, overlap);
    if (edge === "top") padding.top = Math.max(padding.top, overlap.bottom - mapBox.top + clearance);
    else if (edge === "bottom") padding.bottom = Math.max(padding.bottom, mapBox.bottom - overlap.top + clearance);
    else if (edge === "left") padding.left = Math.max(padding.left, overlap.right - mapBox.left + clearance);
    else padding.right = Math.max(padding.right, mapBox.right - overlap.left + clearance);
  }
  return capPadding(mapBox, padding);
}

export function capPadding(mapBox: ScreenBox, padding: ViewportPadding, minInner = MIN_INNER_PX): ViewportPadding {
  const maxX = Math.max(0, mapBox.right - mapBox.left - minInner);
  const maxY = Math.max(0, mapBox.bottom - mapBox.top - minInner);
  const [left, right] = capPair(padding.left, padding.right, maxX);
  const [top, bottom] = capPair(padding.top, padding.bottom, maxY);
  return { top, right, bottom, left };
}

/** Positive x moves the box right; positive y moves it down. Uses the full box, not its center. */
export function containShift(box: ScreenBox, view: ScreenBox): { x: number; y: number } {
  return {
    x: containAxis(box.left, box.right, view.left, view.right),
    y: containAxis(box.top, box.bottom, view.top, view.bottom),
  };
}

export function paddedView(width: number, height: number, padding: ViewportPadding): ScreenBox {
  return {
    left: padding.left,
    top: padding.top,
    right: Math.max(padding.left, width - padding.right),
    bottom: Math.max(padding.top, height - padding.bottom),
  };
}

export function screenBounds(points: readonly { x: number; y: number }[]): ScreenBox {
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const point of points) {
    left = Math.min(left, point.x);
    top = Math.min(top, point.y);
    right = Math.max(right, point.x);
    bottom = Math.max(bottom, point.y);
  }
  return { left, top, right, bottom };
}

export function siteLngLatBounds(ring: readonly [number, number][]): [[number, number], [number, number]] {
  const lngs = ring.map((point) => point[0]);
  const lats = ring.map((point) => point[1]);
  return [
    [Math.min(...lngs), Math.min(...lats)],
    [Math.max(...lngs), Math.max(...lats)],
  ];
}

function intersection(a: ScreenBox, b: ScreenBox): ScreenBox | null {
  const left = Math.max(a.left, b.left);
  const top = Math.max(a.top, b.top);
  const right = Math.min(a.right, b.right);
  const bottom = Math.min(a.bottom, b.bottom);
  if (right - left < 1 || bottom - top < 1) return null;
  return { left, top, right, bottom };
}

function nearestEdge(mapBox: ScreenBox, overlap: ScreenBox): keyof ViewportPadding {
  const midX = (overlap.left + overlap.right) / 2;
  const midY = (overlap.top + overlap.bottom) / 2;
  const distances: [keyof ViewportPadding, number][] = [
    ["top", midY - mapBox.top],
    ["bottom", mapBox.bottom - midY],
    ["left", midX - mapBox.left],
    ["right", mapBox.right - midX],
  ];
  return distances.reduce((best, item) => (item[1] < best[1] ? item : best))[0];
}

/** Keeps the larger inset when both sides cannot fit, so the bigger obstruction still clears the frame. */
function capPair(a: number, b: number, maxSum: number): [number, number] {
  if (a + b <= maxSum) return [a, b];
  if (a >= b) {
    const kept = Math.min(a, maxSum);
    return [kept, Math.max(0, maxSum - kept)];
  }
  const kept = Math.min(b, maxSum);
  return [Math.max(0, maxSum - kept), kept];
}

function containAxis(min: number, max: number, viewMin: number, viewMax: number): number {
  const room = viewMax - viewMin;
  if (max - min <= room) {
    if (min < viewMin) return viewMin - min;
    if (max > viewMax) return viewMax - max;
    return 0;
  }
  if (min > viewMin) return viewMin - min;
  if (max < viewMax) return viewMax - max;
  return 0;
}
