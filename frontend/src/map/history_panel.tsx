import { experimentListStats } from "../solution_record";
import type { ExperimentRecord } from "../api";

function newestFirst(left: ExperimentRecord, right: ExperimentRecord): number {
  const byTime = (right.modified_at ?? "").localeCompare(left.modified_at ?? "");
  if (byTime !== 0) return byTime;
  return right.id.localeCompare(left.id);
}

function finishedLabel(value: string | undefined): string {
  if (!value) return "时间未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未记录";
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Completed output folders the decision map can open or remove. */
export function HistoryPanel({
  experiments,
  loading,
  error,
  pendingDeleteId,
  onClose,
  onImport,
  onAskDelete,
  onConfirmDelete,
  onCancelDelete,
  routing = false,
  busy = false,
}: {
  routing?: boolean;
  busy?: boolean;
  experiments: ExperimentRecord[];
  loading: boolean;
  error: string;
  pendingDeleteId: string | null;
  onClose: () => void;
  onImport: (experimentId: string) => void;
  onAskDelete: (experimentId: string) => void;
  onConfirmDelete: (experimentId: string) => void;
  onCancelDelete: () => void;
}) {
  const rows = [...experiments].sort(newestFirst);
  return (
    <aside className="history-drawer" aria-label="历史优化结果">
      <div className="history-head">
        <p className="hud-kicker">历史优化结果</p>
        <button type="button" className="legend-toggle" onClick={onClose}>关闭</button>
      </div>
      <p className="hud-note">{routing ? "可重新打开当前场景的选线结果。删除案例需要再次确认。" : "可重新打开优化结果或手动保存的实验。另存案例保留当时未删除的方案。删除案例需要再次确认。"}</p>
      {loading && <p className="hud-note">正在读取历史结果…</p>}
      {error && <p className="hud-notice">{error}</p>}
      {!loading && !error && rows.length === 0 && <p className="hud-note">还没有已完成的优化结果。</p>}
      <ul className="history-list">
        {rows.map((item) => {
          const stats = experimentListStats(item.summary);
          const pending = pendingDeleteId === item.id;
          return (
            <li key={item.id} className="history-row">
              <strong>{item.name}</strong>
              <span>{finishedLabel(item.modified_at)} · {item.algorithm === "workspace_snapshot" ? "手动保存" : item.algorithm} · 可行 {stats.feasible} · Pareto {stats.pareto}</span>
              <div className="hud-actions">
                <button type="button" className="primary" disabled={busy} onClick={() => onImport(item.id)}>导入</button>
                {pending ? (
                  <>
                    <button type="button" disabled={busy} onClick={() => onConfirmDelete(item.id)}>确认删除</button>
                    <button type="button" onClick={onCancelDelete}>取消</button>
                  </>
                ) : (
                  <button type="button" disabled={busy} onClick={() => onAskDelete(item.id)}>删除</button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
