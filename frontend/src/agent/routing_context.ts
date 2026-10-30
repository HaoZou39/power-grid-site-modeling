import type { RoutingEdit } from "../routing/routing_edit.js";
import type { RoutingSolution } from "../routing/routing_result.js";
import type { AgentChatMessage } from "./agent_api.js";
import type { RoutingPreference } from "./routing_preference.js";

/** A read-only summary; the server's workspace schema does not yet contain routing fields. */
export function routingContext(input: {
  sceneName: string;
  edit: RoutingEdit;
  selected: RoutingSolution | null;
  resultStale: boolean;
  jobStatus: string | null;
  regionVisibility: { no_tower: boolean; no_cross: boolean };
}) {
  const { edit, selected } = input;
  return {
    scene_name: input.sceneName,
    coordinates: "WGS84 经度和纬度，空字符串表示尚未填写",
    start: { ...edit.start }, end: { ...edit.end },
    constraints: { ...edit.values },
    algorithm: edit.algorithm,
    no_tower_count: edit.regions.filter((region) => region.kind === "no_tower").length,
    no_cross_count: edit.regions.filter((region) => region.kind === "no_cross").length,
    region_visibility: { ...input.regionVisibility },
    regions_local_m: edit.regions.map((region) => ({ kind: region.kind, points: region.points })),
    job_status: input.jobStatus,
    selected_route: selected ? {
      id: selected.id,
      is_feasible: selected.is_feasible,
      objectives: selected.objectives,
      points_local_m: selected.points,
      spans: selected.spans,
      turns_deg: selected.turns_deg,
      tower_slopes_deg: selected.tower_slopes_deg,
      result_stale: input.resultStale,
    } : null,
    objective_units: { tower_count: "座", length_3d_m: "米", bend_sum_rad: "弧度", crossing_3d_m: "米" },
    clearance_status: "净空未校核",
  };
}

export type RoutingAssistantContext = ReturnType<typeof routingContext>;

/** Add current data to the request only; keep the user's visible message unchanged. */
export function routingMessages(messages: readonly AgentChatMessage[], context: RoutingAssistantContext, preference: RoutingPreference | null = null): AgentChatMessage[] {
  if (!messages.length || messages[messages.length - 1].role !== "user") return [...messages];
  const last = messages[messages.length - 1];
  return [...messages.slice(0, -1), {
    role: "user",
    content: `${last.content}\n\n【界面提供的当前选线信息，仅供本次对话参考】\n${JSON.stringify(context)}\n${preference ? `用户设置的选线目标重要程度（0 为不关注，5 为最看重）：${JSON.stringify(preference)}。仅供解释和讨论，不会改变搜索或自动排序。\n` : ""}用户可以在选线结果表点击目标列标题切换升降序，或恢复原顺序；这只改变显示，不修改搜索和结果。用户可通过编辑工具绘制两类区域、调整起终点；助手不能代为执行这些操作。区域和线路点使用场景局部米坐标，x 向东、y 向南。兼容快照中的建筑尺寸、站址策略与选址方案不适用于选线。result_stale 为 true 时，线路指标属于修改前的配置。`,
  }];
}
