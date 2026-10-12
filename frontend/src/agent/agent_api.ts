import type { EditOp } from "./edit_ops.js";
import type { WorkspaceSnapshot } from "./workspace_snapshot.js";

export type AgentChatMessage = { role: "user" | "assistant"; content: string };

export type AgentReply = {
  message: string;
  proposal: { rationale: string; ops: EditOp[] } | null;
  tool_trace: { name: string; ok: boolean }[];
};

export async function chat(snapshot: WorkspaceSnapshot, messages: readonly AgentChatMessage[]): Promise<AgentReply> {
  const response = await fetch("/api/v1/agent/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ snapshot, messages }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail?.message ?? `请求失败 (${response.status})`);
  }
  return response.json() as Promise<AgentReply>;
}
