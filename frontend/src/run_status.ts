/**
 * Display rules for a submitted job. Polling stays in the run monitor;
 * this module only formats status, config, and failure text.
 */

export const JOB_STATUS_LABEL = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已终止",
} as const;

export type JobStatusName = keyof typeof JOB_STATUS_LABEL;

const STAGE_LABEL: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  validated: "已校验配置",
  computed: "已完成计算",
  assembling_result: "正在整理结果",
  completed: "已完成",
  failed: "失败",
  cancelled: "已终止",
};

const MESSAGE_LABEL: Record<string, string> = {
  "Job started": "任务已开始",
  "Job completed": "任务已完成",
  "Job failed": "任务失败",
  "Configuration validated": "配置已校验",
  "Computed aggregate values": "已完成汇总计算",
  "Preparing result": "正在整理结果",
};

const CONFIG_LABEL: Record<string, string> = {
  experiment_name: "实验名称",
  seed: "随机 seed",
  rect_w_m: "建筑矩形宽度（m）",
  rect_h_m: "建筑矩形高度（m）",
  demand_on_buildable_only: "只在可建设区域生成需求点",
  dem_soft: "地形平整度权重",
  road_distance: "道路距离权重",
  demand_distance: "需求点距离权重",
  values: "数值列表",
  multiplier: "乘数",
};

export type ConfigLine = { label: string; value: string };

export function submittedExperimentId(result: Record<string, unknown> | null): string | null {
  const data = result?.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const experimentId = (data as Record<string, unknown>).experiment_id;
  return typeof experimentId === "string" && experimentId.trim() ? experimentId : null;
}

export function isConfigOnlyResult(result: Record<string, unknown> | null): boolean {
  const data = result?.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) return false;
  return (data as Record<string, unknown>).optimizer_executed === false;
}

export function shouldPoll(status: JobStatusName | null): boolean {
  return status === "queued" || status === "running";
}

export function progressRatio(progress: number): number {
  if (!Number.isFinite(progress)) return 0;
  return Math.min(1, Math.max(0, progress));
}

export function runExperimentName(config: Record<string, unknown>): string {
  const name = config.experiment_name;
  return typeof name === "string" && name.trim() ? name.trim() : "未提供";
}

export function stageLabel(stage: string): string {
  return STAGE_LABEL[stage] ?? (stage.trim() || "未提供");
}

export function messageLabel(message: string): string {
  return MESSAGE_LABEL[message] ?? (message.trim() || "未提供");
}

export function configSummary(config: Record<string, unknown>): ConfigLine[] {
  return Object.entries(config).map(([key, value]) => ({
    label: CONFIG_LABEL[key] ?? key,
    value: formatConfigValue(value),
  }));
}

export function failurePresentation(input: {
  message: string;
  error: Record<string, unknown> | null;
}): { summary: string; technical: string | null } {
  const errorMessage = typeof input.error?.message === "string" ? input.error.message : "";
  const traceback = typeof input.error?.traceback === "string" ? input.error.traceback : "";
  const summarySource = errorMessage || input.message;
  const summary = looksLikeTraceback(summarySource) ? "运行失败。技术细节已折叠。" : (summarySource.trim() || "运行失败");
  const technical = traceback || (looksLikeTraceback(summarySource) ? summarySource : "");
  return { summary: MESSAGE_LABEL[summary] ?? summary, technical: technical || null };
}

function formatConfigValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "string") return value.trim() ? value : "未提供";
  if (Array.isArray(value)) return value.map((item) => formatConfigValue(item)).join("，");
  if (value && typeof value === "object") return JSON.stringify(value);
  return "未提供";
}

function looksLikeTraceback(value: string): boolean {
  return value.includes("Traceback") || value.includes("\n  File ");
}
