import type { EditOp } from "./edit_ops.js";
import type { WorkspaceSnapshot } from "./workspace_snapshot.js";

export type AgentChatMessage = { role: "user" | "assistant"; content: string };

export type AgentReply = {
  message: string;
  proposal: { rationale: string; ops: EditOp[] } | null;
  tool_trace: { name: string; ok: boolean }[];
};

/** Read one turn as newline-delimited JSON. `onDelta` receives each text piece as it arrives. */
export async function chat(
  snapshot: WorkspaceSnapshot,
  messages: readonly AgentChatMessage[],
  onDelta: (text: string) => void,
): Promise<AgentReply> {
  const response = await fetch("/api/v1/agent/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ snapshot, messages }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail?.message ?? `请求失败 (${response.status})`);
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error("助手没有回应");
  const decoder = new TextDecoder();
  let buffer = "";
  let reply: AgentReply | null = null;
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      reply = takeLine(line, onDelta) ?? reply;
    }
  }
  reply = takeLine(buffer, onDelta) ?? reply;
  if (!reply) throw new Error("助手没有回应");
  return reply;
}

function takeLine(line: string, onDelta: (text: string) => void): AgentReply | null {
  const text = line.trim();
  if (!text) return null;
  const event = JSON.parse(text) as { type: string; text?: string; message?: string; reply?: AgentReply };
  if (event.type === "delta" && event.text) onDelta(event.text);
  if (event.type === "error") throw new Error(event.message || "助手没有回应");
  return event.type === "done" && event.reply ? event.reply : null;
}
