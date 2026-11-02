import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { SiteEdit } from "../map/site_edit.js";
import type { ParetoChoice } from "../map/decision_run.js";
import { applyOps, describeOps } from "./edit_ops.js";
import type { EditOp } from "./edit_ops.js";
import { AiMark } from "./ai_mark.js";
import { chat } from "./agent_api.js";
import type { AgentChatMessage, AgentProposal } from "./agent_api.js";
import { readAgentSettings } from "./agent_settings_api.js";
import { describeMemoryOps, readMemory, writeMemory } from "./memory.js";
import type { MemoryEntry, MemoryOp } from "./memory.js";
import { safeMarkdownUrl } from "./markdown.js";
import { snapshotStamp, toSnapshot } from "./workspace_snapshot.js";
import type { WorkspaceLayerState } from "./workspace_snapshot.js";
import { IMPORTANCE_MAX, PREFERENCE_OBJECTIVES, importanceOf, readPreferences, writeDefaults } from "./preference.js";
import type { PreferenceState } from "./preference.js";
import { routingMessages } from "./routing_context.js";
import type { RoutingAssistantContext } from "./routing_context.js";
import { defaultRoutingPreference, readRoutingPreference, ROUTING_PREFERENCE_OBJECTIVES, writeRoutingPreference } from "./routing_preference.js";
import type { RoutingPreference } from "./routing_preference.js";

type PendingProposal = {
  rationale: string;
  ops: EditOp[];
  memory: MemoryOp[];
  lines: string[];
  stamp: string;
};

/** A request from the solution card. `nonce` makes a second click on the same solution re-attach it. */
export type AskPose = { id: string; label: string; nonce: number };
export type AskRouting = { label: string; nonce: number; context: RoutingAssistantContext & {
  inspected_target: { kind: string; point_index?: number; span_index?: number; endpoint?: string };
} };

/** Chat beside the map. A proposal changes the edit only after confirm. */
export function AgentPanel({
  edit,
  zIndex,
  onBringToFront,
  experimentId,
  layers,
  onValidate,
  onApply,
  onPreview,
  onRecommend,
  ask,
  askRouting,
  memoryDisabledToken,
  problemType = "site",
  routeContext = null,
}: {
  edit: SiteEdit<ParetoChoice>;
  zIndex: number;
  onBringToFront: () => void;
  experimentId: string | null;
  layers: WorkspaceLayerState;
  onValidate: (ops: readonly EditOp[]) => void;
  onApply: (ops: readonly EditOp[]) => Promise<void>;
  onPreview: (ops: readonly EditOp[] | null) => void;
  onRecommend: (ids: readonly string[]) => void;
  ask: AskPose | null;
  askRouting?: AskRouting | null;
  memoryDisabledToken: number;
  problemType?: "site" | "routing";
  routeContext?: RoutingAssistantContext | null;
}) {
  const [messages, setMessages] = useState<AgentChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [proposal, setProposal] = useState<PendingProposal | null>(null);
  const [page, setPage] = useState<"chat" | "preference">("chat");
  const [routingPreference, setRoutingPreference] = useState<RoutingPreference | null>(() => {
    try { return readRoutingPreference(window.localStorage); } catch { return null; }
  });
  const [attached, setAttached] = useState<AskPose | null>(null);
  const [attachedRouting, setAttachedRouting] = useState<AskRouting | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const lastMemoryDisabledToken = useRef(memoryDisabledToken);
  const editRef = useRef(edit);
  editRef.current = edit;
  const layersRef = useRef(layers);
  layersRef.current = layers;
  const previewSink = useRef(onPreview);
  previewSink.current = onPreview;
  const routingStamp = problemType === "routing" ? JSON.stringify(routeContext) : "";
  const stamp = snapshotStamp(toSnapshot(edit, { experimentId, layers, problemType })) + routingStamp;
  const stale = proposal !== null && proposal.stamp !== stamp;

  useEffect(() => {
    const active = proposal !== null && proposal.stamp === stamp;
    previewSink.current(active && proposal ? proposal.ops : null);
  }, [proposal, stamp]);

  useEffect(() => {
    requestRef.current?.abort(); requestRef.current = null;
    setBusy(false); setProposal(null); setAttached(null); setAttachedRouting(null); setMessages([]); setDraft(""); setError(""); setPage("chat"); previewSink.current(null);
  }, [problemType]);

  useEffect(() => () => {
    requestRef.current?.abort();
    requestRef.current = null;
    previewSink.current(null);
  }, []);

  useEffect(() => {
    if (lastMemoryDisabledToken.current === memoryDisabledToken) return;
    lastMemoryDisabledToken.current = memoryDisabledToken;
    requestRef.current?.abort();
    requestRef.current = null;
    setBusy(false);
    setProposal(null);
    setError("长期记忆已关闭，先前包含记忆改动的提案已失效。");
  }, [memoryDisabledToken]);

  async function send() {
    const content = draft.trim();
    if (!content || busy) return;
    const poseId = problemType === "site" && attached && hasPose(editRef.current, attached.id) ? attached.id : undefined;
    const next: AgentChatMessage[] = [...messages, poseId ? { role: "user", content, pose_id: poseId } : { role: "user", content }];
    setAttached(null);
    setAttachedRouting(null);
    setProposal(null);
    const sentEdit = editRef.current;
    const sentLayers = layersRef.current;
    const sent = toSnapshot(sentEdit, { experimentId, layers: sentLayers, problemType });
    setMessages([...next, { role: "assistant", content: "" }]);
    setDraft("");
    setBusy(true);
    setError("");
    const controller = new AbortController();
    requestRef.current = controller;
    try {
      const routingInfo = attachedRouting?.context ?? routeContext;
      const sentMessages = problemType === "routing" && routingInfo ? routingMessages(next, routingInfo, routingPreference) : next;
      const reply = await chat(sent, sentMessages, (text) => {
        if (requestRef.current === controller && !controller.signal.aborted) setMessages((current) => growLast(current, text));
      }, controller.signal);
      if (requestRef.current !== controller || controller.signal.aborted) return;
      setMessages([...next, { role: "assistant", content: reply.message }]);
      if (problemType === "site" && reply.recommended.length) onRecommend(reply.recommended);
      if (reply.proposal?.ops.length) {
        if (problemType === "routing") {
          setError("当前助手不能直接修改选线，请在选线面板操作。");
          return;
        }
        try {
          onValidate(reply.proposal.ops);
        } catch (reason) {
          setProposal(null);
          setError(reason instanceof Error ? reason.message : "这个提案不能修改进货原点");
          return;
        }
      }
      const entries = reply.proposal?.memory?.length ? (await readMemory()).entries : [];
      if (requestRef.current !== controller || controller.signal.aborted) return;
      setProposal(reply.proposal
        ? pendingProposal(sentEdit, sentLayers, reply.proposal, entries, snapshotStamp(sent) + routingStamp)
        : null);
    } catch (reason) {
      if (requestRef.current !== controller || controller.signal.aborted) return;
      // An empty assistant turn would be rejected by the API on the next send.
      setMessages(next);
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError(reason instanceof Error ? reason.message : "助手没有回应");
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        setBusy(false);
      }
    }
  }

  async function confirm() {
    if (!proposal || stale) return;
    setError("");
    try {
      if (proposal.ops.length) onValidate(proposal.ops);
      // Memory first: if the file write fails, the map stays as it was.
      if (proposal.memory.length) {
        const settings = await readAgentSettings();
        if (!settings.memory_enabled) {
          setProposal(null);
          throw new Error("长期记忆已关闭，这个记忆提案已经失效。");
        }
        await writeMemory(editRef.current.sceneName, proposal.memory);
      }
      if (proposal.ops.length) await onApply(proposal.ops);
      close(appliedNote(proposal));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "这个提案没法生效");
    }
  }

  /** The box goes away; the outcome stays in the chat as an assistant line. */
  function close(note: string) {
    setProposal(null);
    setMessages((current) => [...current, { role: "assistant", content: note }]);
  }

  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, busy]);

  const frame = useAgentFrame();
  const { setMinimized } = frame;
  const selectedPose = problemType === "site" ? edit.selected : null;
  useEffect(() => {
    if (!ask || problemType !== "site") return;
    setAttached(ask);
    setDraft("分析一下这个方案");
    setPage("chat");
    setMinimized(false);
  }, [ask, setMinimized, problemType]);
  useEffect(() => {
    if (!askRouting || problemType !== "routing") return;
    setAttachedRouting(askRouting);
    setDraft("分析一下这条线路及选中的位置");
    setPage("chat");
    setMinimized(false);
  }, [askRouting, setMinimized, problemType]);

  return (
    <aside
      className={frame.minimized ? "agent-drawer minimized" : "agent-drawer"}
      style={{ left: frame.x, top: frame.y, width: frame.width, height: frame.minimized ? undefined : frame.height, zIndex }}
      onPointerDownCapture={onBringToFront}
      onFocusCapture={onBringToFront}
    >
      <div
        className="agent-head"
        role="group"
        tabIndex={0}
        aria-label="移动助手窗口"
        onPointerDown={frame.beginMove}
        onPointerMove={frame.follow}
        onPointerUp={frame.end}
        onPointerCancel={frame.end}
        onLostPointerCapture={frame.end}
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
          <button type="button" role="tab" aria-selected={page === "preference"} className={page === "preference" ? "active" : ""} onClick={() => setPage("preference")}>偏好</button>
        </div>
      )}
      {!frame.minimized && problemType === "site" && page === "preference" && <PreferencePage />}
      {!frame.minimized && problemType === "routing" && page === "preference" && <RoutingPreferencePage preference={routingPreference} onSave={setRoutingPreference} />}
      {!frame.minimized && page === "chat" && <div className="agent-log" ref={logRef}>
        {messages.length === 0 && <MessageRow message={{ role: "assistant", content: problemType === "routing"
          ? "可以询问当前选线配置、禁落塔与禁跨越区域，以及已选线路的指标。接入点、区域和运行操作请在选线面板完成；线路净空未校核。"
          : "可以让它查看当前方案，或提议修改建筑、范围和进货原点。确认后才会改地图。" }} />}
        {problemType === "routing" && routeContext && <p className="hud-note">提问时会附带当前选线配置和已选线路指标；已修改配置的历史结果会标明。</p>}
        {messages.map((message, index) => (
          <MessageRow key={`${message.role}-${index}`} message={message} tag={poseTag(edit, message.pose_id)} live={busy && index === messages.length - 1} />
        ))}
      </div>}
      {!frame.minimized && page === "chat" && proposal && (
        <div className={stale ? "agent-proposal stale" : "agent-proposal"}>
          <strong>{proposal.rationale}</strong>
          {proposal.lines.map((line, index) => <span key={`${index}-${line}`}>{line}</span>)}
          {stale && <span>地图已经变了，这个提案过期了。</span>}
          <div className="hud-actions">
            <button type="button" onClick={() => void confirm()} disabled={stale || busy}>确认</button>
            <button type="button" onClick={() => close(stale ? "提案已过期，没有执行。" : "已拒绝这个提案，地图没有改。")} disabled={busy}>{stale ? "关闭" : "拒绝"}</button>
          </div>
        </div>
      )}
      {!frame.minimized && error && <p className="hud-note">{error}</p>}
      {!frame.minimized && problemType === "routing" && page === "chat" && attachedRouting && <div className="agent-attach">
        <span>附上 {attachedRouting.label}（点击时的快照）</span>
        <button type="button" aria-label="取消附上的线路" title="取消" onClick={() => setAttachedRouting(null)}>×</button>
      </div>}
      {!frame.minimized && problemType === "site" && page === "chat" && attached && hasPose(edit, attached.id) && (
        <div className="agent-attach">
          <span>附上 {attached.label}</span>
          <button type="button" aria-label="取消附上的方案" title="取消" onClick={() => setAttached(null)}>×</button>
        </div>
      )}
      {!frame.minimized && problemType === "site" && page === "chat" && !(attached && hasPose(edit, attached.id)) && selectedPose && (
        <button
          type="button"
          className="agent-attach add"
          onClick={() => setAttached({ id: selectedPose.id, label: `方案 ${edit.selectedIndex + 1}/${edit.poses.length}`, nonce: Date.now() })}
        >
          ＋ 附上方案 {edit.selectedIndex + 1}/{edit.poses.length}
        </button>
      )}
      {!frame.minimized && page === "chat" && (
        <form className="agent-form" onSubmit={(event) => { event.preventDefault(); void send(); }}>
          <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={busy ? "正在想…" : problemType === "routing" ? "询问选线参数或线路结果" : "想调整什么"} disabled={busy} />
          <button type="submit" disabled={busy || draft.trim() === ""}>发送</button>
        </form>
      )}
      {!frame.minimized && (
        <>
        <button type="button" className="agent-width-resize" role="separator"
          aria-label="调整助手窗口宽度" aria-orientation="vertical"
          aria-valuemin={Math.min(MIN_WIDTH, window.innerWidth - 16)}
          aria-valuemax={Math.round(frame.x + frame.width - 8)} aria-valuenow={Math.round(frame.width)}
          title="拖动调整助手窗口宽度，也可使用左右方向键"
          onPointerDown={frame.beginResizeLeft} onPointerMove={frame.follow} onPointerUp={frame.end}
          onPointerCancel={frame.end} onLostPointerCapture={frame.end}
          onKeyDown={(event) => frame.resizeKey(event, "left")} />
        <button
          type="button"
          className="agent-resize"
          aria-label="调整助手窗口宽度和高度"
          title="拖动调整助手窗口宽度和高度，也可使用方向键"
          onPointerDown={frame.beginResize}
          onPointerMove={frame.follow}
          onPointerUp={frame.end}
          onPointerCancel={frame.end}
          onLostPointerCapture={frame.end}
          onKeyDown={(event) => frame.resizeKey(event, "corner")}
        />
        </>
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
  const drag = useRef<{ kind: "move" | "resize" | "resize-left"; pointerId: number; x: number; y: number; frame: AgentFrame } | null>(null);

  useEffect(() => {
    const keepInBounds = () => setFrame((current) => clampFrame(current, minimized ? 48 : undefined));
    keepInBounds();
    window.addEventListener("resize", keepInBounds);
    return () => window.removeEventListener("resize", keepInBounds);
  }, [minimized]);

  function begin(kind: "move" | "resize" | "resize-left", event: ReactPointerEvent) {
    if (!event.isPrimary || event.button !== 0) return;
    if (kind === "move" && (event.target as HTMLElement).closest("button")) return;
    event.preventDefault();
    event.stopPropagation();
    drag.current = { kind, pointerId: event.pointerId, x: event.clientX, y: event.clientY, frame };
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // The pointer can already be gone. The move still follows events on this bar.
    }
  }

  function follow(event: ReactPointerEvent) {
    const active = drag.current;
    if (!active || active.pointerId !== event.pointerId) return;
    event.stopPropagation();
    const dx = event.clientX - active.x;
    const dy = event.clientY - active.y;
    if (active.kind === "move") {
      setFrame(clampFrame({ ...active.frame, x: active.frame.x + dx, y: active.frame.y + dy }, minimized ? 48 : undefined));
    } else {
      setFrame(resizeAgentFrame(active.frame, active.kind === "resize-left" ? "left" : "corner", dx, dy));
    }
  }

  function resizeKey(event: ReactKeyboardEvent, edge: "left" | "corner") {
    const dx = event.key === "ArrowLeft" ? -16 : event.key === "ArrowRight" ? 16 : 0;
    const dy = edge === "corner" ? (event.key === "ArrowUp" ? -16 : event.key === "ArrowDown" ? 16 : 0) : 0;
    if (!dx && !dy) return;
    event.preventDefault();
    event.stopPropagation();
    setFrame((current) => resizeAgentFrame(current, edge, dx, dy));
  }

  return {
    ...frame,
    minimized,
    setMinimized,
    beginMove: (event: ReactPointerEvent) => begin("move", event),
    beginResize: (event: ReactPointerEvent) => begin("resize", event),
    beginResizeLeft: (event: ReactPointerEvent) => begin("resize-left", event),
    resizeKey,
    follow,
    end: () => { drag.current = null; },
  };
}

function resizeAgentFrame(frame: AgentFrame, edge: "left" | "corner", dx: number, dy: number): AgentFrame {
  const margin = 8;
  if (edge === "left") {
    const right = frame.x + frame.width;
    const x = Math.min(Math.max(margin, frame.x + dx), right - Math.min(MIN_WIDTH, right - margin));
    return { ...frame, x, width: right - x };
  }
  return {
    ...frame,
    width: Math.min(Math.max(frame.width + dx, Math.min(MIN_WIDTH, window.innerWidth - frame.x - margin)), window.innerWidth - frame.x - margin),
    height: Math.min(Math.max(frame.height + dy, Math.min(MIN_HEIGHT, window.innerHeight - frame.y - margin)), window.innerHeight - frame.y - margin),
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
      <div className={live ? "agent-bubble live" : "agent-bubble"}>
        {tag && <span className="agent-bubble-tag">{tag}</span>}
        {message.role === "assistant" ? (
          <div className="agent-markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              urlTransform={safeMarkdownUrl}
              components={{
                a: ({ node: _node, href, ...props }) => (
                  <a {...props} href={safeMarkdownUrl(href ?? "") || undefined} target="_blank" rel="noopener noreferrer" />
                ),
              }}
            >
              {text || "…"}
            </ReactMarkdown>
          </div>
        ) : <span className="agent-plain-text">{text || "…"}</span>}
      </div>
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
  layers: WorkspaceLayerState,
  proposal: AgentProposal,
  entries: readonly MemoryEntry[],
  stamp: string,
): PendingProposal {
  const memory = proposal.memory ?? [];
  let lines: string[];
  try {
    const applied = applyOps(edit, proposal.ops, layers);
    lines = describeOps(edit, applied.edit, proposal.ops, layers);
  } catch (reason) {
    lines = [reason instanceof Error ? reason.message : "这个提案无法套用"];
  }
  lines = [...lines, ...describeMemoryOps(memory, entries)];
  return { rationale: proposal.rationale, ops: proposal.ops, memory, lines, stamp };
}

function appliedNote(proposal: PendingProposal): string {
  if (proposal.ops.some((op) => op.kind === "clear_poses")) {
    return "已确认，已清空当前方案，历史优化结果已保留。";
  }
  const layerChanged = proposal.ops.some((op) =>
    op.kind === "set_layer_visibility" || op.kind === "set_dem_opacity" || op.kind === "set_layer_panel_open");
  const editChanged = proposal.ops.some((op) =>
    op.kind !== "set_layer_visibility" && op.kind !== "set_dem_opacity" && op.kind !== "set_layer_panel_open");
  const done = [
    editChanged ? "选址数据已更新" : "",
    layerChanged ? "图层显示已更新" : "",
    proposal.memory.length ? "记忆已写入" : "",
  ].filter(Boolean);
  return `已确认，${done.join("，")}。`;
}

function RoutingPreferencePage({ preference, onSave }: {
  preference: RoutingPreference | null; onSave: (preference: RoutingPreference) => void;
}) {
  const [importance, setImportance] = useState(() => preference ?? defaultRoutingPreference());
  const [note, setNote] = useState("");

  function save() {
    try {
      writeRoutingPreference(window.localStorage, importance);
      onSave(importance);
      setNote("已保存在当前浏览器，之后的选线对话会附带这组偏好。");
    } catch {
      setNote("偏好保存失败，请检查浏览器是否允许存储数据。");
    }
  }

  return <div className="agent-log agent-memory">
    <p className="hud-note">设置四个选线目标的重要程度：0 表示不关注，5 表示最看重。助手会在对话中参考已保存的偏好；它不会改变选线搜索或自动排序。</p>
    <p className="hud-note">{preference ? "已设定选线偏好" : "还没设定，目前各目标同样重要"}</p>
    {ROUTING_PREFERENCE_OBJECTIVES.map(({ key, label }) => <label className="agent-preference-row" key={key}>
      <span>{label}</span>
      <input type="range" min={0} max={IMPORTANCE_MAX} step={1} value={importance[key]}
        onChange={(event) => setImportance((current) => ({ ...current, [key]: Number(event.target.value) }))} />
      <strong>{importance[key]}</strong>
    </label>)}
    <div className="hud-actions"><button type="button" onClick={save}>保存偏好</button></div>
    {note && <p className="hud-note" role="status">{note}</p>}
  </div>;
}

function PreferencePage() {
  const [state, setState] = useState<PreferenceState | null>(null);
  const [importance, setImportance] = useState<Record<string, number>>(importanceOf(null));
  const [note, setNote] = useState("");

  useEffect(() => {
    readPreferences().then(
      (next) => { setState(next); setImportance(importanceOf(next)); },
      (reason) => setNote(reason instanceof Error ? reason.message : "偏好读取失败"),
    );
  }, []);

  async function save() {
    try {
      const next = await writeDefaults(importance);
      setState(next);
      setNote("已保存。之后让助手推荐方案时，会以这组重要程度为起点。");
    } catch (reason) {
      setNote(reason instanceof Error ? reason.message : "偏好保存失败");
    }
  }

  return (
    <div className="agent-log agent-memory">
      <p className="hud-note">
        给每个目标设重要程度，0 表示不看，{IMPORTANCE_MAX} 表示最看重。推荐方案时先按这组设定排序；
        在方案小窗点「记为我的选择」越多，越按你实际的取舍调整。本次搜索没有比较的目标会自动略过。
      </p>
      <p className="hud-note">
        {state?.defaults ? "已设定" : "还没设定，目前各目标同样重要"} · 已记下 {state?.choice_count ?? 0} 次选择
      </p>
      {PREFERENCE_OBJECTIVES.map(({ key, label }) => (
        <label className="agent-preference-row" key={key}>
          <span>{label}</span>
          <input
            type="range"
            min={0}
            max={IMPORTANCE_MAX}
            step={1}
            value={importance[key]}
            onChange={(event) => setImportance((current) => ({ ...current, [key]: Number(event.target.value) }))}
          />
          <strong>{importance[key]}</strong>
        </label>
      ))}
      <div className="hud-actions">
        <button type="button" onClick={() => void save()}>保存偏好</button>
      </div>
      {note && <p className="hud-note">{note}</p>}
    </div>
  );
}
