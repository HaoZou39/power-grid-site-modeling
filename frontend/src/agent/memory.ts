/** Assistant memory as served by /api/v1/agent/memory. The file itself lives on the backend. */

export type MemorySection = "preference" | "command" | "scene_note";

export type MemoryEntry = {
  id: string;
  section: MemorySection;
  scene: string | null;
  date: string;
  source: "stated" | "inferred";
  text: string;
};

export type MemoryOp =
  | { kind: "remember"; section: MemorySection; scene: string | null; source: "stated" | "inferred"; text: string }
  | { kind: "revise"; memory_id: string; text: string }
  | { kind: "forget"; memory_id: string };

export type MemoryState = { entries: MemoryEntry[]; prompt_limit: number };

export const SECTION_TITLES: Record<MemorySection, string> = {
  preference: "偏好",
  command: "常用指令",
  scene_note: "场景备注",
};

export const SOURCE_LABELS = { stated: "明说", inferred: "推断" } as const;

export async function readMemory(): Promise<MemoryState> {
  return parseResponse(await fetch("/api/v1/agent/memory"));
}

export async function writeMemory(sceneName: string, ops: readonly MemoryOp[]): Promise<MemoryState> {
  return parseResponse(await fetch("/api/v1/agent/memory", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scene_name: sceneName, ops }),
  }));
}

/** Entries the model sees in this scene: global ones plus this scene's. */
export function visibleIn(entries: readonly MemoryEntry[], sceneName: string): MemoryEntry[] {
  return entries.filter((entry) => entry.scene === null || entry.scene === sceneName);
}

export function describeMemoryOps(ops: readonly MemoryOp[], entries: readonly MemoryEntry[]): string[] {
  const textOf = (id: string) => entries.find((entry) => entry.id === id)?.text ?? "（已不存在）";
  return ops.map((op) => {
    if (op.kind === "remember") {
      const scope = op.scene ? `只在 ${op.scene}` : "全局";
      return `将记下（${SECTION_TITLES[op.section]}，${scope}）：${op.text}`;
    }
    if (op.kind === "revise") return `将改写 [${op.memory_id}]：${textOf(op.memory_id)} → ${op.text}`;
    return `将忘掉 [${op.memory_id}]：${textOf(op.memory_id)}`;
  });
}

async function parseResponse(response: Response): Promise<MemoryState> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body?.detail?.message ?? `记忆读写失败 (${response.status})`);
  return body as MemoryState;
}
