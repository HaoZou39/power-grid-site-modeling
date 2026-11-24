import type { RoutingSolution } from "./routing_result.js";
import { routeArc } from "./route_arc.js";

export type CorridorConfig = {
  corridor_max_groups: number;
  corridor_sample_points: number;
  corridor_max_diameter_m: number;
};

export type CorridorGroup = {
  id: string;
  member_route_ids: string[];
  representative_route_id: string;
  max_pair_distance_m: number;
};

export type CorridorSnapshot = { version: 1; config: CorridorConfig; groups: CorridorGroup[] };

function shapeDistance(a: readonly { x: number; y: number }[], b: readonly { x: number; y: number }[]): number {
  return Math.max(...a.map((point, index) => Math.hypot(point.x - b[index].x, point.y - b[index].y)));
}

/** Complete linkage prevents a chain of locally similar routes from silently becoming one broad group. */
export function groupRoutingCorridors(routes: readonly RoutingSolution[], config: CorridorConfig): CorridorSnapshot {
  const { corridor_max_groups: limit, corridor_sample_points: samples, corridor_max_diameter_m: threshold } = config;
  if (!Number.isInteger(limit) || limit < 1 || !Number.isInteger(samples) || samples < 2 || !Number.isFinite(threshold) || threshold <= 0) {
    throw new Error("线路走廊分组参数无效。");
  }
  if (new Set(routes.map((route) => route.id)).size !== routes.length) throw new Error("线路编号重复，无法分组。");
  const geometry = routes.map((route) => {
    const arc = routeArc(route.points);
    return Array.from({ length: samples }, (_, index) => arc.pointAt(index / (samples - 1)));
  });
  const distances = geometry.map((a, i) => geometry.map((b, j) => i === j ? 0 : shapeDistance(a, b)));
  const clusterDistance = distances.map((row) => [...row]);
  const clusters = routes.map((_, index) => ({ key: index, members: [index] }));
  while (clusters.length > 1) {
    let best = Infinity, left = -1, right = -1;
    for (let i = 0; i < clusters.length; i += 1) {
      for (let j = i + 1; j < clusters.length; j += 1) {
        const distance = clusterDistance[clusters[i].key][clusters[j].key];
        if (distance < best) { best = distance; left = i; right = j; }
      }
    }
    if (clusters.length <= limit && best > threshold) break;
    const leftKey = clusters[left].key, rightKey = clusters[right].key;
    for (const cluster of clusters) {
      const key = cluster.key;
      clusterDistance[leftKey][key] = clusterDistance[key][leftKey]
        = Math.max(clusterDistance[leftKey][key], clusterDistance[rightKey][key]);
    }
    clusters[left].members = [...clusters[left].members, ...clusters[right].members].sort((a, b) => a - b);
    clusters.splice(right, 1);
  }
  clusters.sort((a, b) => a.members[0] - b.members[0]);
  return { version: 1, config: { corridor_max_groups: limit, corridor_sample_points: samples, corridor_max_diameter_m: threshold },
    groups: clusters.map(({ members }) => {
    const representative = members.reduce((best, candidate) => {
      const score = members.reduce((sum, member) => sum + distances[candidate][member], 0);
      const bestScore = members.reduce((sum, member) => sum + distances[best][member], 0);
      return score < bestScore ? candidate : best;
    }, members[0]);
    return { id: routes[members[0]].id, member_route_ids: members.map((index) => routes[index].id),
      representative_route_id: routes[representative].id,
      max_pair_distance_m: Math.max(...members.flatMap((i) => members.map((j) => distances[i][j]))) };
    }) };
}

export function readCorridorSnapshot(value: unknown, routes: readonly RoutingSolution[]): CorridorSnapshot | null {
  if (!value || typeof value !== "object") return null;
  const snapshot = value as Partial<CorridorSnapshot>;
  if (snapshot.version !== 1 || !Array.isArray(snapshot.groups) || !snapshot.config
    || !Number.isInteger(snapshot.config.corridor_max_groups) || !Number.isInteger(snapshot.config.corridor_sample_points)
    || !Number.isFinite(snapshot.config.corridor_max_diameter_m)) return null;
  const ids = routes.map((route) => route.id);
  if (snapshot.groups.some((group) => !group || !Array.isArray(group.member_route_ids)
    || typeof group.id !== "string" || !Number.isFinite(group.max_pair_distance_m))) return null;
  const members = snapshot.groups.flatMap((group) => group.member_route_ids);
  if (members.length !== ids.length || new Set(members).size !== ids.length || members.some((id) => !ids.includes(id))
    || new Set(snapshot.groups.map((group) => group.id)).size !== snapshot.groups.length
    || snapshot.groups.some((group) => !group.member_route_ids.includes(group.id)
      || !group.member_route_ids.includes(group.representative_route_id))) return null;
  return snapshot as CorridorSnapshot;
}

export function corridorMapRouteIds(groups: readonly CorridorGroup[], activeIds: readonly string[], selectedId: string | null,
  comparedIds: readonly string[], focusedGroupId: string | null = null): string[] {
  const active = new Set(activeIds);
  if (focusedGroupId) return groups.find((group) => group.id === focusedGroupId)?.member_route_ids.filter((id) => active.has(id)) ?? [];
  const visible = groups.flatMap((group) => {
    const members = group.member_route_ids.filter((id) => active.has(id));
    if (!members.length) return [];
    if (group.id === focusedGroupId) return members;
    return [selectedId && members.includes(selectedId) ? selectedId
      : members.includes(group.representative_route_id) ? group.representative_route_id
      : activeIds.find((id) => members.includes(id))!];
  });
  for (const id of comparedIds) if (active.has(id) && !visible.includes(id)) visible.push(id);
  return visible;
}
