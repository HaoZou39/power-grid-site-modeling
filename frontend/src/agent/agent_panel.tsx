import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { SiteEdit } from "../map/site_edit.js";
import type { ParetoChoice } from "../map/decision_run.js";
import { applyOps, describeOps } from "./edit_ops.js";
import type { EditOp } from "./edit_ops.js";
import { AiMark } from "./ai_mark.js";
import { chat } from "./agent_api.js";
import type { AgentChatMessage } from "./agent_api.js";
import { snapshotStamp, toSnapshot } from "./workspace_snapshot.js";

type PendingProposal = {
  rationale: string;
  ops: EditOp[];
  lines: string[];
  stamp: string;
  status: "pending" | "rejected" | "applied";
};

/** Chat beside the map. A proposal changes the edit only after confirm. */
export function AgentPanel({
  edit,
  experimentId,
  onApply,
  onPreview,
}: {
  edit: SiteEdit<ParetoChoice>;
  experimentId: string | null;
  onApply: (ops: readonly EditOp[]) => Promise<void>;
  onPreview: (ops: readonly EditOp[] | null) => void;
}) {
  const [messages, setMessages] = useState<AgentChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [proposal, setProposal] = useState<PendingProposal | null>(null);
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

  async function send() {
    const content = draft.trim();
    if (!content || busy) return;
    const next = [...messages, { role: "user" as const, content }];
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
      setProposal(reply.proposal ? pendingProposal(sentEdit, reply.proposal, snapshotStamp(sent)) : null);
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
      await onApply(proposal.ops);
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
      {!frame.minimized && <div className="agent-log" ref={logRef}>
        {messages.length === 0 && <MessageRow message={{ role: "assistant", content: "可以让它查看当前方案，或提议修改建筑、范围和进货原点。确认后才会改地图。" }} />}
        {messages.map((message, index) => (
          <MessageRow key={`${message.role}-${index}`} message={message} live={busy && index === messages.length - 1} />
        ))}
      </div>}
      {!frame.minimized && proposal && (
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
          {proposal.status === "applied" && <span>已确认，地图已更新。</span>}
          {proposal.status === "rejected" && <span>已拒绝。</span>}
        </div>
      )}
      {!frame.minimized && error && <p className="hud-note">{error}</p>}
      {!frame.minimized && (
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

function MessageRow({ message, live = false }: { message: AgentChatMessage; live?: boolean }) {
  const text = message.content.trim();
  return (
    <div className={`agent-row ${message.role}`}>
      {message.role === "assistant" && <AiMark />}
      <p className={live ? "agent-bubble live" : "agent-bubble"}>{text || "…"}</p>
    </div>
  );
}

function growLast(messages: AgentChatMessage[], text: string): AgentChatMessage[] {
  const last = messages[messages.length - 1];
  if (!last || last.role !== "assistant") return messages;
  return [...messages.slice(0, -1), { role: "assistant", content: last.content + text }];
}

function pendingProposal(
  edit: SiteEdit<ParetoChoice>,
  proposal: { rationale: string; ops: EditOp[] },
  stamp: string,
): PendingProposal {
  let lines: string[];
  try {
    const applied = applyOps(edit, proposal.ops);
    lines = describeOps(edit, applied.edit, proposal.ops);
  } catch (reason) {
    lines = [reason instanceof Error ? reason.message : "这个提案无法套用"];
  }
  return { rationale: proposal.rationale, ops: proposal.ops, lines, stamp, status: "pending" };
}
