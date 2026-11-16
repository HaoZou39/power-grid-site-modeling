import type { SceneFrameInfo } from "../map/site_frame.js";
import { parseRoutingResult } from "./routing_result.js";
import type { RoutingBundle, RoutingSolution, RoutingSort } from "./routing_result.js";
import { sortRoutingSolutions } from "./routing_result.js";

export const ROUTING_PAGE_SIZE = 50;
export type RoutingDisplayMode = "filtered" | "all";

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
  filteredRouteIds: string[] | null;
  maxTortuosity: number | null;
  counts: { all: number | null; filtered: number | null };
};

const PALETTE = ["#7aa2ff", "#ffb86b", "#7dffa1", "#ff7ad9", "#ffe56b", "#6ad7ff", "#ff8f7a", "#c8a2ff", "#8dffd4", "#f4f4f4"];

export const ROUTING_MODES = [
  { id: "filtered", label: "筛选方案" },
  { id: "all", label: "帕累托解" },
] as const satisfies readonly { id: RoutingDisplayMode; label: string }[];

export const DEFAULT_ROUTING_MODE: RoutingDisplayMode = "filtered";
export const LEGACY_PORTFOLIO_MESSAGE = "该历史任务未保存完整非支配解，无法使用全部结果展示功能。";
export const FILTERED_EMPTY_MESSAGE = "当前条件下无符合要求的线路";
export const HISTORICAL_FILTER_MESSAGE = "该结果保存时没有曲折系数筛选清单，不能把当时的相似线路组当作筛选方案。";

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
  _recommendationsText: string | null,
  sceneName: string,
  frame: SceneFrameInfo,
): RoutingPortfolio {
  const manifest = JSON.parse(manifestText) as {
    schema_version?: number;
    status?: RoutingPortfolio["status"];
    message?: string;
    all_pareto_count?: number | null;
    a5_group_count?: number | null;
    filtered_count?: number | null;
    filtered_route_ids?: string[];
    max_tortuosity?: number | null;
  };
  if (manifest.schema_version !== 1) throw new Error("结果清单版本无法读取。");
  if (manifest.status !== "complete") {
    const failed = manifest.status === "failed";
    return {
      status: failed ? "failed" : "legacy_published_only",
      message: failed ? (manifest.message || "结果清单没有生成。") : LEGACY_PORTFOLIO_MESSAGE,
      routes: [], groups: [], filteredRouteIds: null, maxTortuosity: null,
      counts: { all: null, filtered: null },
    };
  }
  if (!allText) throw new Error("完整帕累托文件缺失。");
  const bundle = parseRoutingResult(allText, sceneName, frame);
  const groups = groupsText ? (JSON.parse(groupsText) as { groups?: RoutingGroup[] }).groups ?? [] : [];
  const routes = bundle.routes;
  const ids = new Set(routes.map((route) => route.id));
  const seen = new Set<string>();
  for (const group of groups) {
    if (!ids.has(group.representative_route_id) || group.member_count !== group.member_route_ids.length) {
      throw new Error("筛选追溯与完整前沿不一致。");
    }
    for (const member of group.member_route_ids) {
      if (!ids.has(member) || seen.has(member)) throw new Error("筛选追溯成员无法对应到唯一原始线路。");
      seen.add(member);
    }
  }
  if (manifest.all_pareto_count !== routes.length || (groupsText != null && manifest.a5_group_count != null && manifest.a5_group_count !== groups.length)) {
    throw new Error("帕累托数量与清单不一致。");
  }
  const hasFilter = Array.isArray(manifest.filtered_route_ids);
  const filteredRouteIds = hasFilter ? manifest.filtered_route_ids ?? [] : null;
  if (filteredRouteIds) {
    if (new Set(filteredRouteIds).size !== filteredRouteIds.length || filteredRouteIds.some((id) => !ids.has(id))) {
      throw new Error("筛选线路无法对应到原始帕累托线路。");
    }
    if (manifest.filtered_count !== filteredRouteIds.length) throw new Error("筛选数量与清单不一致。");
  }
  const maxTortuosity = typeof manifest.max_tortuosity === "number" && Number.isFinite(manifest.max_tortuosity) ? manifest.max_tortuosity : null;
  return {
    status: "complete",
    message: null,
    routes, groups, filteredRouteIds, maxTortuosity,
    counts: { all: routes.length, filtered: filteredRouteIds ? filteredRouteIds.length : null },
  };
}

export async function readRoutingPortfolio(
  record: { artifacts: readonly { name: string; url: string }[] },
  scene: { id: string; frame: SceneFrameInfo | null },
  readText: (url: string) => Promise<string>,
): Promise<RoutingPortfolio | null> {
  if (!scene.frame) return null;
  const find = (name: string) => record.artifacts.find((item) => item.name === name)?.url;
  const manifestUrl = find("routing_portfolio_manifest.json");
  if (!manifestUrl) return {
    status: "legacy_published_only",
    message: LEGACY_PORTFOLIO_MESSAGE,
    routes: [], groups: [], filteredRouteIds: null, maxTortuosity: null,
    counts: { all: null, filtered: null },
  };
  const manifestText = await readText(manifestUrl);
  const status = (JSON.parse(manifestText) as { status?: string }).status;
  if (status !== "complete") return parseRoutingPortfolio(manifestText, null, null, null, scene.id, scene.frame);
  const groupsUrl = find("routing_a5_groups.json");
  const [allText, groupsText] = await Promise.all([
    readText(required(find("routes_all_pareto.json"), "完整帕累托")),
    groupsUrl ? readText(groupsUrl) : Promise.resolve(null),
  ]);
  return parseRoutingPortfolio(manifestText, allText, groupsText, null, scene.id, scene.frame);
}

function required(url: string | undefined, label: string): string {
  if (!url) throw new Error(`${label}文件缺失。`);
  return url;
}

export function routingModeContent(
  portfolio: RoutingPortfolio,
  mode: RoutingDisplayMode,
  options: { query: string; page: number; sort: RoutingSort | null; pinnedIds: readonly string[] },
) {
  const byId = new Map(portfolio.routes.map((route) => [route.id, route]));
  const query = options.query.trim();
  const source = mode === "filtered"
    ? (portfolio.filteredRouteIds ?? []).flatMap((id) => {
      const route = byId.get(id);
      return route ? [route] : [];
    })
    : portfolio.routes.filter((route) => !query || route.id.includes(query));
  const matched = sortRoutingSolutions(source, options.sort).map((row) => row.route);
  const pageCount = Math.max(1, Math.ceil(matched.length / ROUTING_PAGE_SIZE));
  const page = Math.min(Math.max(options.page, 0), pageCount - 1);
  const pageRows = matched.slice(page * ROUTING_PAGE_SIZE, (page + 1) * ROUTING_PAGE_SIZE);
  const visible = new Set(pageRows.map((route) => route.id));
  const pinned = [...new Set(options.pinnedIds)].flatMap((id) => {
    if (visible.has(id)) return [];
    const route = byId.get(id);
    return route ? [route] : [];
  });
  return {
    rows: [...pinned, ...pageRows],
    mapRoutes: uniqueRoutes([...pinned, ...pageRows]),
    page, pageCount, matchedCount: matched.length,
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
