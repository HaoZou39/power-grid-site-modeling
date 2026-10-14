export type AgentSettings = {
  memory_enabled: boolean;
  base_url: string;
  model: string;
  api_key_configured: boolean;
  config_source: string;
  base_url_editable: boolean;
  model_editable: boolean;
  api_key_editable: boolean;
  external_notice: string;
};

export type SettingsField = "base_url" | "model" | "api_key";

export class SettingsRequestError extends Error {
  field?: SettingsField;

  constructor(message: string, field?: SettingsField) {
    super(message);
    this.name = "SettingsRequestError";
    this.field = field;
  }
}

export type AgentSettingsAction =
  | {
    action: "update_model";
    base_url: string;
    model: string;
    api_key?: string;
    clear_api_key: boolean;
  }
  | { action: "enable_memory" }
  | { action: "disable_memory_and_clear" };

export async function readAgentSettings(): Promise<AgentSettings> {
  return parseResponse(await fetch("/api/v1/agent/settings"));
}

export async function writeAgentSettings(action: AgentSettingsAction): Promise<AgentSettings> {
  return parseResponse(await fetch("/api/v1/agent/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(action),
  }));
}

async function parseResponse(response: Response): Promise<AgentSettings> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new SettingsRequestError(errorMessage(body, response.status), errorField(body));
  return body as AgentSettings;
}

function errorField(body: unknown): SettingsField | undefined {
  const detail = detailOf(body);
  if (detail && typeof detail === "object" && !Array.isArray(detail) && "field" in detail) {
    const field = (detail as { field: unknown }).field;
    if (field === "base_url" || field === "model" || field === "api_key") return field;
  }
  return undefined;
}

function errorMessage(body: unknown, status: number): string {
  const detail = detailOf(body);
  if (detail && typeof detail === "object" && !Array.isArray(detail) && "message" in detail) {
    const message = (detail as { message: unknown }).message;
    if (typeof message === "string" && message) return message;
  }
  return `设置操作失败 (${status})`;
}

function detailOf(body: unknown): unknown {
  return body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : null;
}
