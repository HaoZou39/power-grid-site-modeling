import type { components } from "./generated/api";

export type PluginSpec = {
  id: string;
  version: string;
  kind: string;
  name: string;
  description: string;
  config_schema: Record<string, unknown>;
};

export type JobRecord = {
  job_id: string;
  plugin_id: string;
  plugin_version: string;
  config: Record<string, unknown>;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  stage: string;
  message: string;
  result: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail?.message ?? `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const getHealth = () => request<{ status: string; service: string; version: string }>("/api/v1/health");
export const getPlugins = () => request<{ items: PluginSpec[] }>("/api/v1/plugins");
export const createJob = (payload: JobCreateRequest) =>
  request<JobRecord>("/api/v1/jobs", { method: "POST", body: JSON.stringify(payload) });
export const getJob = (jobId: string) => request<JobRecord>(`/api/v1/jobs/${jobId}`);

export type JobCreateRequest = components["schemas"]["JobCreateRequest"];
