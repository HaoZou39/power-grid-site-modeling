import { experimentListStats } from "../solution_record";
import type { ExperimentRecord } from "../api";
import { useState } from "react";
import { savedCaseDateLabel, searchSavedCases, type CaseSearchField } from "./saved_cases";

function newestFirst(left: ExperimentRecord, right: ExperimentRecord): number {
  const byTime = (right.modified_at ?? "").localeCompare(left.modified_at ?? "");
  if (byTime !== 0) return byTime;
  return right.id.localeCompare(left.id);
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
  const [searchField, setSearchField] = useState<CaseSearchField>("name");
  const [query, setQuery] = useState("");
  const rows = searchSavedCases(experiments, searchField, query).sort(newestFirst);
  return (
    <aside className="history-drawer" aria-label="已保存案例">
      <div className="history-head">
        <p className="hud-kicker">已保存案例</p>
        <button type="button" className="legend-toggle" onClick={onClose}>关闭</button>
      </div>
      <p className="hud-note">{routing ? "可重新打开当前场景手动保存的选线案例。删除案例需要再次确认。" : "可重新打开当前场景手动保存的选址案例。另存案例保留当时未删除的方案。删除案例需要再次确认。"}</p>
      <div className="history-search" role="search" aria-label="搜索已保存案例">
        <select aria-label="案例搜索字段" value={searchField} onChange={(event) => { setSearchField(event.target.value as CaseSearchField); setQuery(""); }}>
          <option value="name">名称</option><option value="date">日期</option><option value="feasible">可行数</option>
        </select>
        <input aria-label="搜索案例" type={searchField === "feasible" ? "number" : "search"} min="0" step="1"
          placeholder={searchField === "name" ? "输入案例名称" : searchField === "date" ? "例如 2026-11 或 2026-11-22" : "输入可行方案数量"}
          value={query} onChange={(event) => setQuery(event.target.value)} />
        {query && <button type="button" className="legend-toggle" onClick={() => setQuery("")}>清空搜索</button>}
      </div>
      {!loading && !error && experiments.length > 0 && <p className="hud-note" role="status">显示 {rows.length} / {experiments.length} 个案例</p>}
      {loading && <p className="hud-note">正在读取历史结果…</p>}
      {error && <p className="hud-notice">{error}</p>}
      {!loading && !error && experiments.length === 0 && <p className="hud-note">{routing ? "还没有手动保存的案例。" : "当前场景暂无已保存的选址案例。"}</p>}
      {!loading && !error && experiments.length > 0 && rows.length === 0 && <p className="hud-note">没有匹配的案例，请调整搜索条件。</p>}
      <ul className="history-list">
        {rows.map((item) => {
          const stats = experimentListStats(item.summary);
          const pending = pendingDeleteId === item.id;
          return (
            <li key={item.id} className="history-row">
              <strong>{item.name}{item.summary.case_kind === "filter_result" ? " · 筛选版" : ""}</strong>
              <span>{savedCaseDateLabel(item.modified_at)} · {item.algorithm === "workspace_snapshot" || item.algorithm === "routing_workspace" ? "手动保存" : item.algorithm} · 可行 {stats.feasible} · Pareto {stats.pareto}</span>
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
