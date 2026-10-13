export type ViewportPoint = { x: number; y: number };

export type ViewportRect = {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};

export type WorkspaceBounds = ViewportRect & {
  scrollLeft: number;
  scrollTop: number;
};

export type SchemeTarget = ViewportPoint & { schemeId: string };
export type SchemeCardBounds = { schemeId: string; bounds: ViewportRect };

export type SchemeConnectorGeometry = {
  start: ViewportPoint;
  target: ViewportPoint;
  control: ViewportPoint;
  path: string;
};

const EDGE_INSET = 16;
const HEADER_BUTTON_CLEARANCE = 88;

export function schemeConnectorGeometry(
  target: ViewportPoint,
  card: ViewportRect,
  workspace: WorkspaceBounds,
): SchemeConnectorGeometry | null {
  if (![target.x, target.y, card.left, card.top, card.right, card.bottom].every(Number.isFinite)) return null;
  if (target.x < workspace.left || target.x > workspace.right || target.y < workspace.top || target.y > workspace.bottom) return null;
  if (target.x >= card.left && target.x <= card.right && target.y >= card.top && target.y <= card.bottom) return null;

  const center = {
    x: (card.left + card.right) / 2,
    y: (card.top + card.bottom) / 2,
  };
  const dx = target.x - center.x;
  const dy = target.y - center.y;
  const halfWidth = Math.max(0, card.width / 2);
  const halfHeight = Math.max(0, card.height / 2);
  const scaleX = dx === 0 ? Number.POSITIVE_INFINITY : halfWidth / Math.abs(dx);
  const scaleY = dy === 0 ? Number.POSITIVE_INFINITY : halfHeight / Math.abs(dy);
  const scale = Math.min(scaleX, scaleY);
  if (!Number.isFinite(scale)) return null;

  const edge = {
    x: center.x + dx * scale,
    y: center.y + dy * scale,
  };
  const onVerticalEdge = scaleX <= scaleY;
  if (onVerticalEdge) {
    const topInset = edge.x >= card.right - 1 ? 56 : EDGE_INSET;
    edge.y = clampEdge(edge.y, card.top + topInset, card.bottom - EDGE_INSET);
  } else {
    const rightInset = edge.y <= card.top + 1 ? HEADER_BUTTON_CLEARANCE : EDGE_INSET;
    edge.x = clampEdge(edge.x, card.left + EDGE_INSET, card.right - rightInset);
  }

  const start = {
    x: edge.x - workspace.left + workspace.scrollLeft,
    y: edge.y - workspace.top + workspace.scrollTop,
  };
  const end = {
    x: target.x - workspace.left + workspace.scrollLeft,
    y: target.y - workspace.top + workspace.scrollTop,
  };
  const localDx = end.x - start.x;
  const localDy = end.y - start.y;
  const distance = Math.hypot(localDx, localDy);
  if (distance < 1) return null;
  const bend = Math.min(30, distance * 0.08);
  const control = {
    x: (start.x + end.x) / 2 - (localDy / distance) * bend,
    y: (start.y + end.y) / 2 + (localDx / distance) * bend,
  };
  return {
    start,
    target: end,
    control,
    path: `M ${format(start.x)} ${format(start.y)} Q ${format(control.x)} ${format(control.y)} ${format(end.x)} ${format(end.y)}`,
  };
}

export function SchemeConnector({
  target,
  cardBounds,
  workspaceBounds,
  visible,
}: {
  target: ViewportPoint | null;
  cardBounds: ViewportRect | null;
  workspaceBounds: WorkspaceBounds | null;
  visible: boolean;
}) {
  if (!visible || !target || !cardBounds || !workspaceBounds) return null;
  const geometry = schemeConnectorGeometry(target, cardBounds, workspaceBounds);
  if (!geometry) return null;
  return (
    <svg
      className="scheme-connector"
      style={{ width: workspaceBounds.width, height: workspaceBounds.height }}
      viewBox={`0 0 ${workspaceBounds.width} ${workspaceBounds.height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      <path d={geometry.path} />
      <circle className="scheme-connector-ring" cx={geometry.target.x} cy={geometry.target.y} r="7" />
      <circle className="scheme-connector-dot" cx={geometry.target.x} cy={geometry.target.y} r="3.5" />
    </svg>
  );
}

function clampEdge(value: number, minimum: number, maximum: number): number {
  if (maximum < minimum) return (minimum + maximum) / 2;
  return Math.min(maximum, Math.max(minimum, value));
}

function format(value: number): string {
  return value.toFixed(2);
}
