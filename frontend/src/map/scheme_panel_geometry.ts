// Projections and DOM measurements use viewport pixels; convert once at the panel boundary.
export type SchemeScreenRect = { left: number; top: number; right: number; bottom: number };
export type SchemeAnchor = { x: number; y: number; left: number; top: number };
export type SchemeProjection = { anchor: SchemeAnchor; target: { x: number; y: number; schemeId: string } };

export const SCHEME_PANEL_MARGIN = 8;
export const SCHEME_PANEL_TOP = 148;
export const SCHEME_CLEARANCE = 12;

export function sameScreenRects(left: readonly SchemeScreenRect[], right: readonly SchemeScreenRect[]): boolean {
  return left.length === right.length && left.every((box, i) =>
    box.left === right[i].left && box.right === right[i].right
    && box.top === right[i].top && box.bottom === right[i].bottom);
}

export function findClearSchemePosition(
  obstacles: readonly SchemeScreenRect[],
  bounds: { width: number; height: number },
  size: { width: number; height: number },
  preferred: { x: number; y: number },
): { x: number; y: number } | null {
  const minX = SCHEME_PANEL_MARGIN, minY = SCHEME_PANEL_TOP;
  const maxX = bounds.width - size.width - minX, maxY = bounds.height - size.height - minX;
  if (maxX < minX || maxY < minY) return null;
  // Search the panel's top-left point, expanding obstacles by panel size and clearance.
  const forbidden = obstacles.map((box) => ({
    left: box.left - size.width - SCHEME_CLEARANCE, right: box.right + SCHEME_CLEARANCE,
    top: box.top - size.height - SCHEME_CLEARANCE, bottom: box.bottom + SCHEME_CLEARANCE,
  }));
  const clampX = (x: number) => Math.max(minX, Math.min(x, maxX));
  const clampY = (y: number) => Math.max(minY, Math.min(y, maxY));
  const preferredX = clampX(preferred.x), preferredY = clampY(preferred.y);
  if (forbidden.every((box) => preferredX <= box.left || preferredX >= box.right
    || preferredY <= box.top || preferredY >= box.bottom)) return { x: preferredX, y: preferredY };
  const xs = new Set([minX, maxX, preferredX,
    ...forbidden.flatMap((box) => [clampX(box.left), clampX(box.right)])]);
  let best: { x: number; y: number } | null = null;
  let distance = Infinity;
  for (const x of xs) {
    const intervals = forbidden.filter((box) => x > box.left && x < box.right).sort((a, b) => a.top - b.top);
    let bottom = minY;
    const offer = (top: number, end: number) => {
      if (end < top) return;
      const y = Math.max(top, Math.min(preferredY, end));
      const cost = (x - preferred.x) ** 2 + (y - preferred.y) ** 2;
      if (cost < distance) { best = { x, y }; distance = cost; }
    };
    for (const box of intervals) {
      if (box.bottom <= minY || box.top >= maxY) continue;
      offer(bottom, Math.min(maxY, box.top));
      bottom = Math.max(bottom, box.bottom);
      if (bottom > maxY) break;
    }
    offer(bottom, maxY);
  }
  return best;
}

export function leastCoveredSchemePosition(
  schemes: readonly SchemeScreenRect[], panels: readonly SchemeScreenRect[],
  bounds: { width: number; height: number }, size: { width: number; height: number },
  preferred: { x: number; y: number },
): { x: number; y: number } {
  // When no full gap exists, protect information panels before minimizing scheme coverage.
  const minX = SCHEME_PANEL_MARGIN, minY = SCHEME_PANEL_TOP;
  const maxX = Math.max(minX, bounds.width - size.width - minX);
  const maxY = Math.max(minY, bounds.height - size.height - minX);
  const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(value, max));
  const samples = (min: number, max: number, preferredValue: number, edges: number[]) => new Set([
    clamp(preferredValue, min, max),
    ...Array.from({ length: 25 }, (_, index) => min + (max - min) * index / 24),
    ...edges.map((edge) => clamp(edge, min, max)),
  ]);
  const xs = samples(minX, maxX, preferred.x, panels.flatMap((box) => [box.left - size.width, box.right]));
  const ys = samples(minY, maxY, preferred.y, panels.flatMap((box) => [box.top - size.height, box.bottom]));
  const overlap = (x: number, y: number, box: SchemeScreenRect) =>
    Math.max(0, Math.min(x + size.width, box.right) - Math.max(x, box.left))
    * Math.max(0, Math.min(y + size.height, box.bottom) - Math.max(y, box.top));
  let best = { x: minX, y: minY }, bestPanels = Infinity, bestSchemes = Infinity, bestDistance = Infinity;
  for (const x of xs) for (const y of ys) {
    const panelArea = panels.reduce((sum, box) => sum + overlap(x, y, box), 0);
    if (panelArea > bestPanels) continue;
    const schemeArea = schemes.reduce((sum, box) => sum + overlap(x, y, box), 0);
    const distance = (x - preferred.x) ** 2 + (y - preferred.y) ** 2;
    if (panelArea < bestPanels || panelArea === bestPanels && (schemeArea < bestSchemes
      || schemeArea === bestSchemes && distance < bestDistance)) {
      best = { x, y }; bestPanels = panelArea; bestSchemes = schemeArea; bestDistance = distance;
    }
  }
  return best;
}

export function placeSchemePanel(
  schemes: readonly SchemeScreenRect[], panels: readonly SchemeScreenRect[],
  bounds: { width: number; height: number }, size: { width: number; height: number },
  minimum: { width: number; height: number }, anchor: SchemeAnchor | null,
): { x: number; y: number; width: number; height: number } {
  const obstacles = [...schemes, ...panels];
  const minWidth = Math.min(size.width, minimum.width), minHeight = Math.min(size.height, minimum.height);
  const locate = (width: number, height: number) => {
    const candidate = { width, height };
    return findClearSchemePosition(obstacles, bounds, candidate, placeSchemeCard(anchor, bounds, candidate));
  };
  const full = locate(size.width, size.height);
  if (full) return { ...full, ...size };
  // Keep the card wide enough for its fields; reduce height before width and scroll its contents.
  const widths = [...new Set([size.width, Math.max(minWidth, Math.round((size.width + minWidth) / 2)), minWidth])];
  for (const width of widths) {
    let height = minHeight;
    let position = locate(width, height);
    if (!position) continue;
    let limit = size.height;
    while (limit - height > 24) {
      const middle = Math.floor((height + limit) / 2);
      const found = locate(width, middle);
      if (found) { height = middle; position = found; }
      else limit = middle;
    }
    return { ...position, width, height };
  }
  const smallest = { width: minWidth, height: minHeight };
  const preferred = placeSchemeCard(anchor, bounds, smallest);
  return { ...leastCoveredSchemePosition(schemes, panels, bounds, smallest, preferred), ...smallest };
}

export function placeSchemeCard(
  anchor: SchemeAnchor | null,
  bounds: { width: number; height: number },
  size: { width: number; height: number },
): { x: number; y: number } {
  const preferred = {
    x: anchor ? (anchor.left + anchor.x - size.width) / 2 : (bounds.width - size.width) / 2,
    y: anchor ? (anchor.top + anchor.y - size.height) / 2 : SCHEME_PANEL_TOP,
  };
  return findClearSchemePosition(anchor ? [{ left: anchor.left, top: anchor.top, right: anchor.x, bottom: anchor.y }] : [],
    bounds, size, preferred) ?? { x: SCHEME_PANEL_MARGIN, y: SCHEME_PANEL_TOP };
}
