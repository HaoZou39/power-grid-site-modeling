import type { RoutingEdit } from "../routing/routing_edit.js";
import type { RoutingSolution } from "../routing/routing_result.js";
import type { AgentChatMessage } from "./agent_api.js";
import type { RoutingPreference } from "./routing_preference.js";
import type { RoutingInspection } from "../routing/routing_layer.js";

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

export function routingAttachment(context: RoutingAssistantContext, target: RoutingInspection) {
  // Freeze the visible result and clicked object even if the user changes selection before sending.
  return JSON.parse(JSON.stringify({ ...context, inspected_target: {
    kind: target.kind, point_index: target.pointIndex, span_index: target.spanIndex, endpoint: target.endpoint,
  } })) as RoutingAssistantContext & { inspected_target: { kind: string; point_index?: number; span_index?: number; endpoint?: string } };
}

/** Add current data to the request only; keep the user's visible message unchanged. */
export function routingMessages(messages: readonly AgentChatMessage[], context: RoutingAssistantContext, preference: RoutingPreference | null = null): AgentChatMessage[] {
  if (!messages.length || messages[messages.length - 1].role !== "user") return [...messages];
  const last = messages[messages.length - 1];
  return [...messages.slice(0, -1), {
    role: "user",
    content: `${last.content}\n\n【界面提供的当前选线信息，仅供本次对话参考】\n${JSON.stringify(context)}\n${preference ? `用户设置的选线目标重要程度（0 为不关注，5 为最看重）：${JSON.stringify(preference)}。仅供解释和讨论，不会改变搜索或自动排序。\n` : ""}inspected_target 如存在则为用户附上的点击对象，其中 point_index 和 span_index 从 0 开始；这是点击时的快照。地图显示搜索的可行 Pareto 线路，手动案例还保留重评后不可行的线路；用户可以点击线路或塔位查看详情，可行线路可加入对比。对比折线按全部可行线路逐目标归一化，越低表示该目标越小，不是跨目标的绝对数值比较。选线结果表的指标表头直接切换升序、降序和载入顺序（按载入时编号排列，保留筛选条件），每次排序即时写入轮次；当前指标表头保留小滑条，点击或拖动时在上方展开放大的完整分布明细，随指标和区间实时更新。轮次记录保留修改、移除、撤销和清空，并用上移、下移按钮调整顺序；表头不再支持拖动换序。选线列表与 CSV 使用数字编号，详情和对比图的“线路 X”使用同一编号；JSON 和案例持久化 number，重开或筛选不重新编号，原始 route id 只用于内部关联；帕累托解和筛选方案各自保留轮次、排序和区间，切换不互相覆盖；另存筛选版取当前档，另存当前实验、全部方案 CSV/JSON 和优化场景 PNG 共用结果栏“筛选方案”的曲折系数限制及去重清单（导入筛选案例时为全部候选），不随手动多轮筛选或显示档变化；普通另存仍重评。地图默认显示全部保留项；结果栏角落的「只看前十」与「全部方案」互斥，分别显示保留项前十、当前结果范围的所有候选（包括筛除项），都不勾选时显示全部保留项，不改变筛选、列表或保存范围。保存和 CSV/JSON/PNG 导出位于「文件」栏的筛选版分组，数量说明紧挨另存入口之前，只有收窄区间筛选且保留项非空时启用，仅排序不能启用。命名和窗口沿用完整结果，默认名称及导出文件名末尾加「筛选版」；导出复用完整结果领域结构，JSON 另附筛选快照；筛选版 PNG 复用图片设置，仅绘制全部最终保留方案及塔位，不受地图显示开关影响。独立案例保存完整候选、最终顺序和轮次，不优化、不重评，重新导入可继续调整。助手不能查看或代为操作这些筛选与保存。用户可通过编辑工具绘制两类区域；已有线路时必须先清空线路才能调整起终点。自动结果保存在后端，用户点击文件里的另存当前实验才能创建案例；另存按当前约束重新评价，不重新优化。助手不能代为执行这些操作。区域和线路点使用场景局部米坐标，x 向东、y 向南。兼容快照中的建筑尺寸、站址策略与选址方案不适用于选线。result_stale 为 true 时，线路指标属于修改前的配置。`,
  }];
}
