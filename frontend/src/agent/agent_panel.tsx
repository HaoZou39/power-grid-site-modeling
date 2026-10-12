import { useEffect, useRef, useState } from "react";
import type { SiteEdit } from "../map/site_edit.js";
import type { ParetoChoice } from "../map/decision_run.js";
import { applyOps, describeOps } from "./edit_ops.js";
import type { EditOp } from "./edit_ops.js";
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
    const sentStamp = snapshotStamp(toSnapshot(editRef.current, { experimentId }));
    setMessages(next);
    setDraft("");
    setBusy(true);
    setError("");
    try {
      const reply = await chat(toSnapshot(editRef.current, { experimentId }), next);
      setMessages([...next, { role: "assistant", content: reply.message }]);
      setProposal(reply.proposal ? pendingProposal(editRef.current, reply.proposal, sentStamp) : null);
    } catch (reason) {
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

  return (
    <aside className="agent-drawer">
      <p className="hud-kicker">AI 助手</p>
      <div className="agent-log">
        {messages.length === 0 && <p className="hud-note">可以让它查看当前方案，或提议修改建筑、范围和进货原点。确认后才会改地图。</p>}
        {messages.map((message, index) => (
          <p key={`${message.role}-${index}`} className={`agent-line ${message.role}`}>{message.content}</p>
        ))}
      </div>
      {proposal && (
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
      {error && <p className="hud-note">{error}</p>}
      <form className="agent-form" onSubmit={(event) => { event.preventDefault(); void send(); }}>
        <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={busy ? "正在想…" : "想调整什么"} disabled={busy} />
        <button type="submit" disabled={busy || draft.trim() === ""}>发送</button>
      </form>
    </aside>
  );
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
