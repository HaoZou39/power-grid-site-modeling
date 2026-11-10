import { useState } from "react";
import type { PlanningWorkspace, WorkspaceRevisionSummary } from "../api";
import { baseStatusNotice, shortId } from "./planning_workspace";

export function PlanningWorkspacePanel({
  sceneTitle, items, selected, revision, dirty, busy, error, notice, conflict, pending, confirmDelete,
  history, historyView, provenance, onClose, onCreate, onRename, onSelect, onLeave, onSave, onReload,
  onDismissConflict, onShowHistory, onViewRevision, onCloseHistory, onSaveAndSwitch, onDiscardAndSwitch,
  onCancelSwitch,   onAskDelete, onDelete, onCancelDelete, sceneSwitch,
}: {
  sceneTitle: string;
  items: PlanningWorkspace[];
  selected: PlanningWorkspace | null;
  revision: string;
  dirty: boolean;
  busy: boolean;
  error: string;
  notice: string;
  conflict: string;
  pending: { workspaceId: string | null; canSave: boolean } | null;
  confirmDelete: boolean;
  history: WorkspaceRevisionSummary[];
  historyView: string | null;
  provenance: { workspace: string; revision: string; baseRevision: string; jobId: string; historical: string | null } | null;
  onClose: () => void;
  onCreate: (name: string) => void;
  onRename: (name: string) => void;
  onSelect: (workspaceId: string) => void;
  onLeave: () => void;
  onSave: () => void;
  onReload: () => void;
  onDismissConflict: () => void;
  onShowHistory: () => void;
  onViewRevision: (revisionId: string) => void;
  onCloseHistory: () => void;
  onSaveAndSwitch: () => void;
  onDiscardAndSwitch: () => void;
  onCancelSwitch: () => void;
  onAskDelete: () => void;
  onDelete: () => void;
  onCancelDelete: () => void;
  sceneSwitch: { onSave: () => void; onDiscard: () => void; onCancel: () => void } | null;
}) {
  const [name, setName] = useState("");
  const status = selected?.base_status ?? null;
  const statusText = status === "current" ? "公共场景一致" : status === "changed" ? "公共场景版本已变化" : status === "missing" ? "公共场景不可用" : "未选择工作区";
  return (
    <section className="planning-workspace" role="dialog" aria-modal="true" aria-label="个人工作区">
      <div className="row">
        <strong>个人工作区</strong>
        <button type="button" onClick={onClose}>关闭</button>
      </div>
      <p className="account-hint">{sceneTitle}。土地分类、道路、场景重建和永农仍是公共数据，不是个人工作区里的私有修改。</p>
      {error && <p role="alert">{error}</p>}
      {notice && <p className="account-hint">{notice}</p>}
      {conflict && (
        <div className="row">
          <p role="alert">{conflict}</p>
          <button type="button" onClick={onReload}>重新加载</button>
          <button type="button" onClick={onDismissConflict}>取消</button>
        </div>
      )}
      {sceneSwitch && (
        <div className="row">
          <p role="alert">切换场景前，个人工作区还有未保存修改。</p>
          <button type="button" onClick={sceneSwitch.onSave} disabled={busy}>保存并切换场景</button>
          <button type="button" onClick={sceneSwitch.onDiscard} disabled={busy}>放弃并切换场景</button>
          <button type="button" onClick={sceneSwitch.onCancel}>取消切换</button>
        </div>
      )}
      {pending && (
        <div className="row">
          <p role="alert">{pending.canSave ? "有未保存修改。请保存、放弃或取消切换。" : "当前修改还没进入工作区。进入后会改用该工作区的规划。"}</p>
          {pending.canSave && <button type="button" onClick={onSaveAndSwitch} disabled={busy}>保存并切换</button>}
          <button type="button" onClick={onDiscardAndSwitch} disabled={busy}>放弃并切换</button>
          <button type="button" onClick={onCancelSwitch}>取消切换</button>
        </div>
      )}
      <p>状态：{statusText}{revision ? ` · 修订 ${shortId(revision)}` : ""}{dirty ? " · 未保存" : ""}</p>
      {status && baseStatusNotice(status) && <p role="alert">{baseStatusNotice(status)}</p>}
      <div className="row">
        {items.map((item) => (
          <button type="button" key={item.workspace_id} aria-pressed={item.workspace_id === selected?.workspace_id} disabled={busy}
            onClick={() => onSelect(item.workspace_id)}>{item.display_name}</button>
        ))}
        {selected && <button type="button" onClick={onLeave} disabled={busy}>返回公共场景</button>}
      </div>
      <label>新建工作区
        <input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} />
      </label>
      <div className="row">
        <button type="button" disabled={busy || !name.trim()} onClick={() => { onCreate(name); setName(""); }}>创建</button>
        {selected && <button type="button" disabled={busy || !name.trim()} onClick={() => onRename(name)}>重命名</button>}
        {selected && !confirmDelete && <button type="button" disabled={busy} onClick={onAskDelete}>删除</button>}
        {confirmDelete && <button type="button" disabled={busy} onClick={onDelete}>确认删除</button>}
        {confirmDelete && <button type="button" onClick={onCancelDelete}>取消</button>}
        {selected && <button type="button" disabled={busy || status !== "current"} onClick={onSave}>保存规划</button>}
      </div>
      {selected && (
        <div className="row">
          <button type="button" onClick={onShowHistory}>查看修订</button>
          {historyView && <button type="button" onClick={onCloseHistory}>关闭历史</button>}
        </div>
      )}
      {historyView && <p className="account-hint">{historyView}</p>}
      {history.length > 0 && (
        <ul>
          {history.map((item) => (
            <li key={item.revision_id}>
              <button type="button" onClick={() => onViewRevision(item.revision_id)}>{shortId(item.revision_id)} · {item.created_at}</button>
            </li>
          ))}
        </ul>
      )}
      {provenance && (
        <details>
          <summary>本次运行</summary>
          <p>工作区 {provenance.workspace}</p>
          <p>修订 {provenance.revision}</p>
          <p>基础版本 {provenance.baseRevision}</p>
          <p>任务 {provenance.jobId}</p>
          {provenance.historical && <p role="alert">{provenance.historical}</p>}
        </details>
      )}
    </section>
  );
}
