import type { SceneFrameInfo } from "../map/site_frame.js";
import { parseRoutingResult } from "./routing_result.js";
import type { RoutingBundle, RoutingSolution, RoutingSort } from "./routing_result.js";
import { sortRoutingSolutions } from "./routing_result.js";

export const ROUTING_PAGE_SIZE = 50;
export type RoutingDisplayMode = "recommended" | "groups" | "all";

export type RoutingGroup = {
  group_id: string;
  representative_route_id: string;
  member_route_ids: string[];
  member_count: number;
  group_risk_flags: string[];
  engineering_review_status: string;
  max_tower_offset_m: number | null;
};

export type RoutingRecommendation = {
  route_id: string;
  recommendation_tags: string[];
  recommendation_reasons: string;
  recommendation_rank: number;
  review_flags: string[];
  group_id: string;
};

export type RoutingPortfolio = {
  status: "complete" | "legacy_published_only" | "failed";
  message: string | null;
  routes: RoutingSolution[];
  groups: RoutingGroup[];
  recommendations: RoutingRecommendation[];
  counts: { all: number | null; groups: number | null; recommended: number | null };
};

const PALETTE = ["#7aa2ff", "#ffb86b", "#7dffa1", "#ff7ad9", "#ffe56b", "#6ad7ff", "#ff8f7a", "#c8a2ff", "#8dffd4", "#f4f4f4"];

declare const __ROUTING_THREE_MODE_PREVIEW__: boolean | undefined;

export function routingPreviewEnabled(): boolean {
  return __ROUTING_THREE_MODE_PREVIEW__ === true;
}

export function routingDisplayColor(index: number): string {
  return PALETTE[index % PALETTE.length];
}

export function groupNeedsReview(group: RoutingGroup | undefined): boolean {
  return !!group && group.group_risk_flags.some((flag) => flag === "TOWER_OFFSET" || flag === "CROSSING_TYPE_REVIEW" || flag === "HIGH_TOWER_OFFSET");
}

export function parseRoutingPortfolio(
  manifestText: string,
  allText: string | null,
  groupsText: string | null,
  recommendationsText: string | null,
  sceneName: string,
  frame: SceneFrameInfo,
): RoutingPortfolio {
  const manifest = JSON.parse(manifestText) as {
    schema_version?: number;
    status?: RoutingPortfolio["status"];
    message?: string;
    all_pareto_count?: number | null;
    a5_group_count?: number | null;
    recommended_count?: number | null;
  };
  if (manifest.schema_version !== 1) throw new Error("三层结果清单版本无法读取。");
  if (manifest.status !== "complete") {
    return {
      status: manifest.status === "failed" ? "failed" : "legacy_published_only",
      message: manifest.message || "该历史结果只有旧发布线路，不能显示全部 Pareto。",
      routes: [], groups: [], recommendations: [],
      counts: { all: null, groups: null, recommended: null },
    };
  }
  if (!allText || !groupsText || !recommendationsText) throw new Error("三层结果文件不完整。");
  const bundle = parseRoutingResult(allText, sceneName, frame);
  const groupsFile = JSON.parse(groupsText) as { groups?: RoutingGroup[] };
  const recommendationsFile = JSON.parse(recommendationsText) as { recommendations?: RoutingRecommendation[] };
  const groups = groupsFile.groups ?? [];
  const recommendations = recommendationsFile.recommendations ?? [];
  const routes = bundle.routes;
  const ids = new Set(routes.map((route) => route.id));
  const seen = new Set<string>();
  for (const group of groups) {
    if (!ids.has(group.representative_route_id) || group.member_count !== group.member_route_ids.length) {
      throw new Error("相似线路分组与完整前沿不一致。");
    }
    for (const member of group.member_route_ids) {
      if (!ids.has(member) || seen.has(member)) throw new Error("相似线路成员无法对应到唯一原始线路。");
      seen.add(member);
    }
  }
  if (seen.size !== ids.size) throw new Error("有帕累托线路没有进入任何相似组。");
  const representatives = new Set(groups.map((group) => group.representative_route_id));
  for (const item of recommendations) {
    if (!representatives.has(item.route_id)) throw new Error("推荐线路不是相似组代表。");
  }
  if (manifest.all_pareto_count !== routes.length || manifest.a5_group_count !== groups.length
    || manifest.recommended_count !== recommendations.length) {
    throw new Error("三层数量与清单不一致。");
  }
  return {
    status: "complete",
    message: null,
    routes, groups, recommendations,
    counts: { all: routes.length, groups: groups.length, recommended: recommendations.length },
  };
}

export async function readRoutingPortfolio(
  record: { artifacts: readonly { name: string; url: string }[] },
  scene: { id: string; frame: SceneFrameInfo | null },
  readText: (url: string) => Promise<string>,
): Promise<RoutingPortfolio | null> {
  if (!routingPreviewEnabled() || !scene.frame) return null;
  const find = (name: string) => record.artifacts.find((item) => item.name === name)?.url;
  const manifestUrl = find("routing_portfolio_manifest.json");
  if (!manifestUrl) return null;
  const manifestText = await readText(manifestUrl);
  const status = (JSON.parse(manifestText) as { status?: string }).status;
  if (status !== "complete") return parseRoutingPortfolio(manifestText, null, null, null, scene.id, scene.frame);
  const [allText, groupsText, recommendationsText] = await Promise.all([
    readText(required(find("routes_all_pareto.json"), "完整帕累托")),
    readText(required(find("routing_a5_groups.json"), "相似线路")),
    readText(required(find("routing_recommendations.json"), "推荐方案")),
  ]);
  return parseRoutingPortfolio(manifestText, allText, groupsText, recommendationsText, scene.id, scene.frame);
}

function required(url: string | undefined, label: string): string {
  if (!url) throw new Error(`${label}文件缺失。`);
  return url;
}

export function routingModeContent(
  portfolio: RoutingPortfolio,
  mode: RoutingDisplayMode,
  options: { expandedGroupId: string | null; query: string; page: number; sort: RoutingSort | null; pinnedIds: readonly string[] },
) {
  const byId = new Map(portfolio.routes.map((route) => [route.id, route]));
  const groupByRoute = new Map<string, RoutingGroup>();
  for (const group of portfolio.groups) for (const member of group.member_route_ids) groupByRoute.set(member, group);
  const query = options.query.trim();
  let listed: RoutingSolution[] = [];
  if (mode === "recommended") {
    listed = sortRoutingSolutions(portfolio.recommendations.flatMap((item) => {
      const route = byId.get(item.route_id);
      return route ? [route] : [];
    }), options.sort).map((row) => row.route);
  } else if (mode === "groups") {
    const representatives = sortRoutingSolutions(portfolio.groups.flatMap((group) => {
      const route = byId.get(group.representative_route_id);
      return route ? [route] : [];
    }), options.sort).map((row) => row.route);
    for (const representative of representatives) {
      listed.push(representative);
      const group = groupByRoute.get(representative.id);
      if (!group || options.expandedGroupId !== group.group_id) continue;
      for (const member of group.member_route_ids) {
        if (member === group.representative_route_id) continue;
        const route = byId.get(member);
        if (route) listed.push(route);
      }
    }
  } else {
    listed = sortRoutingSolutions(portfolio.routes.filter((route) => !query || route.id.includes(query)), options.sort)
      .map((row) => row.route);
  }
  const matched = listed;
  const pageCount = Math.max(1, Math.ceil(matched.length / ROUTING_PAGE_SIZE));
  const page = Math.min(Math.max(options.page, 0), pageCount - 1);
  const pageRows = mode === "all" ? matched.slice(page * ROUTING_PAGE_SIZE, (page + 1) * ROUTING_PAGE_SIZE) : matched;
  const visible = new Set(pageRows.map((route) => route.id));
  const pinned = options.pinnedIds.flatMap((id) => {
    if (visible.has(id)) return [];
    const route = byId.get(id);
    return route ? [route] : [];
  });
  return {
    rows: [...pinned, ...pageRows],
    mapRoutes: uniqueRoutes([...pinned, ...pageRows]),
    page, pageCount, matchedCount: matched.length,
    groupByRoute,
    recommendationByRoute: new Map(portfolio.recommendations.map((item) => [item.route_id, item])),
  };
}

function uniqueRoutes(routes: RoutingSolution[]): RoutingSolution[] {
  const seen = new Set<string>();
  return routes.filter((route) => seen.has(route.id) ? false : (seen.add(route.id), true));
}

export function sameRouteGeometry(left: RoutingSolution, right: RoutingSolution): boolean {
  return JSON.stringify(left.objectives) === JSON.stringify(right.objectives)
    && JSON.stringify(left.points) === JSON.stringify(right.points);
}

export function publishedBundleUnchanged(bundle: RoutingBundle, publishedIds: readonly string[]): boolean {
  return bundle.routes.every((route, index) => route.id === publishedIds[index]);
}
