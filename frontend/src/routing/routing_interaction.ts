import { simplifyStroke } from "../map/exclusion_sketch.js";
import { rectangleCorners } from "../map/site_edit.js";
import type { LocalPoint } from "../map/site_frame.js";
import type { RegionKind } from "./routing_edit.js";
import { validateRoutingPolygon } from "./routing_polygon.js";

export type RoutingTool = "start" | "end" | "adjust-endpoints" | "no_tower" | "no_tower-box" | "no_cross" | "no_cross-box";

export function routingRegionKind(tool: RoutingTool | null): RegionKind | null {
  if (tool === "no_tower" || tool === "no_tower-box") return "no_tower";
  if (tool === "no_cross" || tool === "no_cross-box") return "no_cross";
  return null;
}

export function routingLoop(tool: RoutingTool | null): boolean {
  return tool === "no_tower" || tool === "no_cross";
}

export function routingBox(tool: RoutingTool | null): boolean {
  return tool === "no_tower-box" || tool === "no_cross-box";
}

export function routingStroke(points: readonly LocalPoint[]): LocalPoint[] {
  const ring = simplifyStroke(points, 4);
  if (ring.length < 3) throw new Error("请沿区域画一圈，松手后会自动闭合。");
  validateRoutingPolygon(ring);
  return ring;
}

export function routingRectangle(first: LocalPoint, second: LocalPoint): LocalPoint[] {
  if (first.x === second.x || first.y === second.y) throw new Error("方框需要有宽度和高度。");
  return rectangleCorners(first, second);
}
