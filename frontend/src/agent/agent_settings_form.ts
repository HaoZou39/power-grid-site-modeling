export const SETTINGS_SECTION_ORDER = ["管理员验证", "模型 API 配置", "长期记忆"] as const;

export const PASSWORD_HINT = "修改设置前请先输入管理员密码。";
export const PASSWORD_REQUIRED = "请先填写管理员密码。";
export const PASSWORD_PLACEHOLDER = "请输入管理员密码";
export const MODEL_SAVED = "模型配置已保存";
export const MEMORY_ENABLED_NOTE = "长期记忆已开启。";
export const MEMORY_DISABLED_NOTE = "长期记忆已关闭，文字记忆已清除。";
export const KEY_PLACEHOLDER_SET = "已配置，留空保持不变";
export const KEY_PLACEHOLDER_EMPTY = "请输入 API Key";
export const CLEAR_KEY_LABEL = "清除已保存的 API Key";
export const CLEAR_AND_REPLACE = "清除 API Key 和填写新密钥不能同时进行。";

export function canSaveModel(password: string, busy: boolean): boolean {
  return !busy && password.trim() !== "";
}

export function keyPlaceholder(configured: boolean): string {
  return configured ? KEY_PLACEHOLDER_SET : KEY_PLACEHOLDER_EMPTY;
}

export function configSourceLabel(source: string): string {
  return `当前配置来源：${source}`;
}
