import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { SiteEdit } from "../map/site_edit.js";
import type { ParetoChoice } from "../map/decision_run.js";
import { applyOps, describeOps } from "./edit_ops.js";
import type { EditOp } from "./edit_ops.js";
import { AiMark } from "./ai_mark.js";
import { chat } from "./agent_api.js";
import type { AgentChatMessage, AgentProposal } from "./agent_api.js";
import { SECTION_TITLES, SOURCE_LABELS, describeMemoryOps, readMemory, visibleIn, writeMemory } from "./memory.js";
import type { MemoryEntry, MemoryOp, MemorySection, MemoryState } from "./memory.js";
import { snapshotStamp, toSnapshot } from "./workspace_snapshot.js";

type PendingProposal = {
  rationale: string;
  ops: EditOp[];
  memory: MemoryOp[];
  lines: string[];
  stamp: string;
  status: "pending" | "rejected" | "applied";
};

/** A request from the solution card. `nonce` makes a second click on the same solution re-attach it. */
export type AskPose = { id: string; label: string; nonce: number };

/** Chat beside the map. A proposal changes the edit only after confirm. */
export function AgentPanel({
  edit,
  experimentId,
  onApply,
  onPreview,
  ask,
}: {
  edit: SiteEdit<ParetoChoice>;
  experimentId: string | null;
  onApply: (ops: readonly EditOp[]) => Promise<void>;
  onPreview: (ops: readonly EditOp[] | null) => void;
  ask: AskPose | null;
}) {
  const [messages, setMessages] = useState<AgentChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [proposal, setProposal] = useState<PendingProposal | null>(null);
  const [page, setPage] = useState<"chat" | "memory">("chat");
  const [memory, setMemory] = useState<MemoryState | null>(null);
  const [attached, setAttached] = useState<AskPose | null>(null);
  const editRef = useRef(edit);
  editRef.current = edit;
  const previewSink = useRef(onPreview);
  previewSink.current = onPreview;
  const stamp = snapshotStamp(toSnapshot(edit, { experimentId }));
  const stale = proposal?.status === "pending" && proposal.stamp !== stamp;

  useEffect(() => {
    const active = proposal?.status === "pending" && proposal.stamp === snapshotStamp(toSnapshot(editRef.current, { experimentId }));
    previewSink.current(active && proposal ? proposal.ops : null);
  }, [proposal, edit, experimentId]);

  useEffect(() => () => previewSink.current(null), []);

  const [memoryError, setMemoryError] = useState("");

  // Re-read on every visit to the memory page: the file can be edited by hand.
  useEffect(() => {
    readMemory().then(
      (state) => { setMemory(state); setMemoryError(""); },
      (reason) => setMemoryError(reason instanceof Error ? reason.message : "记忆读取失败"),
    );
  }, [page]);

  async function changeMemory(ops: readonly MemoryOp[]) {
    setMemory(await writeMemory(editRef.current.sceneName, ops));
    setMemoryError("");
  }

  async function send() {
    const content = draft.trim();
    if (!content || busy) return;
    const poseId = attached && hasPose(editRef.current, attached.id) ? attached.id : undefined;
    const next: AgentChatMessage[] = [...messages, poseId ? { role: "user", content, pose_id: poseId } : { role: "user", content }];
    setAttached(null);
    const sentEdit = editRef.current;
    const sent = toSnapshot(sentEdit, { experimentId });
    setMessages([...next, { role: "assistant", content: "" }]);
    setDraft("");
    setBusy(true);
    setError("");
    try {
      const reply = await chat(sent, next, (text) => {
        setMessages((current) => growLast(current, text));
      });
      setMessages([...next, { role: "assistant", content: reply.message }]);
      setProposal(reply.proposal ? pendingProposal(sentEdit, reply.proposal, memory?.entries ?? [], snapshotStamp(sent)) : null);
    } catch (reason) {
      // An empty assistant turn would be rejected by the API on the next send.
      setMessages(next);
      setError(reason instanceof Error ? reason.message : "助手没有回应");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!proposal || proposal.status !== "pending" || stale) return;
    setError("");
    try {
      // Memory first: if the file write fails, the map stays as it was.
      if (proposal.memory.length) await changeMemory(proposal.memory);
      if (proposal.ops.length) await onApply(proposal.ops);
      setProposal({ ...proposal, status: "applied" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "这个提案没法生效");
    }
  }

  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, busy]);

  const frame = useAgentFrame();
  const { setMinimized } = frame;
  useEffect(() => {
    if (!ask) return;
    setAttached(ask);
    setDraft("分析一下这个方案");
    setPage("chat");
    setMinimized(false);
  }, [ask, setMinimized]);

  return (
    <aside
      className={frame.minimized ? "agent-drawer minimized" : "agent-drawer"}
      style={{ left: frame.x, top: frame.y, width: frame.width, height: frame.minimized ? undefined : frame.height }}
    >
      <div
        className="agent-head"
        role="group"
        tabIndex={0}
        aria-label="移动助手窗口"
        onPointerDown={frame.beginMove}
        onPointerMove={frame.follow}
        onPointerUp={frame.end}
      >
        <AiMark />
        <strong>AI 助手</strong>
        <button
          type="button"
          className="agent-min"
          aria-label={frame.minimized ? "还原" : "最小化"}
          title={frame.minimized ? "还原" : "最小化"}
          onClick={() => frame.setMinimized((value) => !value)}
        >
          {frame.minimized ? "▢" : "–"}
        </button>
      </div>
      {!frame.minimized && (
        <div className="agent-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={page === "chat"} className={page === "chat" ? "active" : ""} onClick={() => setPage("chat")}>对话</button>
          <button type="button" role="tab" aria-selected={page === "memory"} className={page === "memory" ? "active" : ""} onClick={() => setPage("memory")}>
            记忆{memory ? ` ${memory.entries.length}` : ""}
          </button>
        </div>
      )}
      {!frame.minimized && page === "memory" && (
        <MemoryPage
          memory={memory}
          error={memoryError}
          sceneName={edit.sceneName}
          onForget={(id) => changeMemory([{ kind: "forget", memory_id: id }]).catch((reason) => setMemoryError(reason instanceof Error ? reason.message : "删除失败"))}
        />
      )}
      {!frame.minimized && page === "chat" && <div className="agent-log" ref={logRef}>
        {messages.length === 0 && <MessageRow message={{ role: "assistant", content: "可以让它查看当前方案，或提议修改建筑、范围和进货原点。确认后才会改地图。" }} />}
        {messages.map((message, index) => (
          <MessageRow key={`${message.role}-${index}`} message={message} tag={poseTag(edit, message.pose_id)} live={busy && index === messages.length - 1} />
        ))}
      </div>}
      {!frame.minimized && page === "chat" && proposal && (
        <div className={stale ? "agent-proposal stale" : "agent-proposal"}>
          <strong>{proposal.rationale}</strong>
          {proposal.lines.map((line, index) => <span key={`${index}-${line}`}>{line}</span>)}
          {stale && <span>地图已经变了，这个提案过期了。</span>}
          {proposal.status === "pending" && (
            <div className="hud-actions">
              <button type="button" onClick={() => void confirm()} disabled={stale || busy}>确认</button>
              <button type="button" onClick={() => setProposal({ ...proposal, status: "rejected" })} disabled={busy}>拒绝</button>
            </div>
          )}
          {proposal.status === "applied" && <span>{appliedNote(proposal)}</span>}
          {proposal.status === "rejected" && <span>已拒绝。</span>}
        </div>
      )}
      {!frame.minimized && error && <p className="hud-note">{error}</p>}
      {!frame.minimized && page === "chat" && attached && hasPose(edit, attached.id) && (
        <div className="agent-attach">
          <span>附上 {attached.label}</span>
          <button type="button" aria-label="取消附上的方案" title="取消" onClick={() => setAttached(null)}>×</button>
        </div>
      )}
      {!frame.minimized && page === "chat" && (
        <form className="agent-form" onSubmit={(event) => { event.preventDefault(); void send(); }}>
          <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={busy ? "正在想…" : "想调整什么"} disabled={busy} />
          <button type="submit" disabled={busy || draft.trim() === ""}>发送</button>
        </form>
      )}
      {!frame.minimized && (
        <button
          type="button"
          className="agent-resize"
          aria-label="调整大小"
          onPointerDown={frame.beginResize}
          onPointerMove={frame.follow}
          onPointerUp={frame.end}
        />
      )}
    </aside>
  );
}

type AgentFrame = { x: number; y: number; width: number; height: number };
const MIN_WIDTH = 280;
const MIN_HEIGHT = 240;

function useAgentFrame() {
  const [frame, setFrame] = useState<AgentFrame>(defaultFrame);
  const [minimized, setMinimized] = useState(false);
  const drag = useRef<{ kind: "move" | "resize"; x: number; y: number; frame: AgentFrame } | null>(null);

  function begin(kind: "move" | "resize", event: ReactPointerEvent) {
    if (kind === "move" && (event.target as HTMLElement).closest("button")) return;
    drag.current = { kind, x: event.clientX, y: event.clientY, frame };
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // The pointer can already be gone. The move still follows events on this bar.
    }
  }

  function follow(event: ReactPointerEvent) {
    const active = drag.current;
    if (!active) return;
    const dx = event.clientX - active.x;
    const dy = event.clientY - active.y;
    const next = active.kind === "move"
      ? { ...active.frame, x: active.frame.x + dx, y: active.frame.y + dy }
      : { ...active.frame, width: active.frame.width + dx, height: active.frame.height + dy };
    setFrame(clampFrame(next, active.kind === "move" && minimized ? 48 : undefined));
  }

  return {
    ...frame,
    minimized,
    setMinimized,
    beginMove: (event: ReactPointerEvent) => begin("move", event),
    beginResize: (event: ReactPointerEvent) => begin("resize", event),
    follow,
    end: () => { drag.current = null; },
  };
}

function defaultFrame(): AgentFrame {
  return clampFrame({
    x: window.innerWidth - 500,
    y: 148,
    width: 380,
    height: Math.min(520, window.innerHeight - 180),
  });
}

function clampFrame(frame: AgentFrame, occupied?: number): AgentFrame {
  const margin = 8;
  const width = Math.min(Math.max(frame.width, MIN_WIDTH), window.innerWidth - margin * 2);
  const height = Math.min(Math.max(frame.height, MIN_HEIGHT), window.innerHeight - margin * 2);
  const used = occupied ?? height;
  return {
    width,
    height,
    x: Math.min(Math.max(frame.x, margin), window.innerWidth - width - margin),
    y: Math.min(Math.max(frame.y, margin), Math.max(margin, window.innerHeight - used - margin)),
  };
}

function MessageRow({ message, tag, live = false }: { message: AgentChatMessage; tag?: string; live?: boolean }) {
  const text = message.content.trim();
  return (
    <div className={`agent-row ${message.role}`}>
      {message.role === "assistant" && <AiMark />}
      <p className={live ? "agent-bubble live" : "agent-bubble"}>
        {tag && <span className="agent-bubble-tag">{tag}</span>}
        {text || "…"}
      </p>
    </div>
  );
}

function hasPose(edit: SiteEdit<ParetoChoice>, poseId: string): boolean {
  return edit.poses.some((pose) => pose.id === poseId);
}

/** The solution's current position in the list; the id alone once it has been removed. */
function poseTag(edit: SiteEdit<ParetoChoice>, poseId: string | undefined): string | undefined {
  if (!poseId) return undefined;
  const index = edit.poses.findIndex((pose) => pose.id === poseId);
  return index < 0 ? poseId : `方案 ${index + 1}`;
}

function growLast(messages: AgentChatMessage[], text: string): AgentChatMessage[] {
  const last = messages[messages.length - 1];
  if (!last || last.role !== "assistant") return messages;
  return [...messages.slice(0, -1), { role: "assistant", content: last.content + text }];
}

function pendingProposal(
  edit: SiteEdit<ParetoChoice>,
  proposal: AgentProposal,
  entries: readonly MemoryEntry[],
  stamp: string,
): PendingProposal {
  const memory = proposal.memory ?? [];
  let lines: string[];
  try {
    const applied = applyOps(edit, proposal.ops);
    lines = describeOps(edit, applied.edit, proposal.ops);
  } catch (reason) {
    lines = [reason instanceof Error ? reason.message : "这个提案无法套用"];
  }
  lines = [...lines, ...describeMemoryOps(memory, entries)];
  return { rationale: proposal.rationale, ops: proposal.ops, memory, lines, stamp, status: "pending" };
}

function appliedNote(proposal: PendingProposal): string {
  const done = [proposal.ops.length ? "地图已更新" : "", proposal.memory.length ? "记忆已写入" : ""].filter(Boolean);
  return `已确认，${done.join("，")}。`;
}

function MemoryPage({
  memory,
  error,
  sceneName,
  onForget,
}: {
  memory: MemoryState | null;
  error: string;
  sceneName: string;
  onForget: (id: string) => void;
}) {
  if (!memory) return <div className="agent-log"><p className="hud-note">{error || "正在读取记忆…"}</p></div>;
  const visible = visibleIn(memory.entries, sceneName).length;
  return (
    <div className="agent-log agent-memory">
      <p className="hud-note">在对话里说「记住…」「忘掉…」，确认后写入。也可以直接改后端的 memory/MEMORY.md。</p>
      {error && <p className="agent-memory-warn">{error}</p>}
      {visible > memory.prompt_limit && (
        <p className="agent-memory-warn">当前场景可见 {visible} 条，超过 {memory.prompt_limit} 条。建议在对话里说「整理一下记忆」。</p>
      )}
      {(Object.keys(SECTION_TITLES) as MemorySection[]).map((section) => {
        const items = memory.entries.filter((entry) => entry.section === section);
        return (
          <section key={section}>
            <h4>{SECTION_TITLES[section]}</h4>
            {items.length === 0 && <p className="hud-note">暂无</p>}
            {items.map((entry) => (
              <div className="agent-memory-item" key={entry.id}>
                <span>
                  <em>[{entry.id}] {entry.scene ?? "全局"} · {SOURCE_LABELS[entry.source]} · {entry.date}</em>
                  {entry.text}
                </span>
                <button type="button" aria-label={`删除 ${entry.id}`} title="删除" onClick={() => onForget(entry.id)}>×</button>
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}
