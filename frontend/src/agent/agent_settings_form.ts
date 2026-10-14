export const SETTINGS_SECTION_ORDER = ["模型 API 配置", "长期记忆"] as const;

export const MODEL_SAVED = "模型配置已保存";
export const MEMORY_ENABLED_NOTE = "长期记忆已开启。";
export const MEMORY_DISABLED_NOTE = "长期记忆已关闭，文字记忆已清除。";
export const KEY_PLACEHOLDER_SET = "输入新的 API Key，留空则保持不变";
export const KEY_PLACEHOLDER_EMPTY = "请输入 API Key";

export function canSaveModel(busy: boolean): boolean {
  return !busy;
}

export function keyPlaceholder(configured: boolean): string {
  return configured ? KEY_PLACEHOLDER_SET : KEY_PLACEHOLDER_EMPTY;
}

export function configSourceLabel(source: string): string {
  return `当前配置来源：${source}`;
}
