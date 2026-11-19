import { useState } from "react";
import { saveFilterCase } from "../api.js";
import { filteredCsv, type FilterSnapshot } from "./filter_snapshot.js";

export function FilterCaseActions({ total, retained, capture, onlyRetained, onOnlyRetained }: {
  total: number; retained: number; capture?: () => FilterSnapshot;
  onlyRetained: boolean; onOnlyRetained: (value: boolean) => void;
}) {
  const [pending, setPending] = useState<FilterSnapshot | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function save() {
    if (!pending || busy || !name.trim()) return;
    setBusy(true); setMessage("");
    try {
      const result = await saveFilterCase({ name: name.trim(), snapshot: pending });
      setPending(null); setMessage(`已保存「${result.name}」，共 ${result.solution_count} 个，可从导入案例打开。`);
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }
  function exportResult(format: "csv" | "json") {
    if (!capture) return;
    try {
      const snapshot = capture();
      const content = format === "csv" ? filteredCsv(snapshot) : JSON.stringify(snapshot, null, 2);
      const url = URL.createObjectURL(new Blob([content], { type: format === "csv" ? "text/csv;charset=utf-8" : "application/json" }));
      const link = document.createElement("a"); link.href = url;
      link.download = `筛选结果-${snapshot.retained_ids.length}.${format}`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
  }
  return <section className="filter-case-actions ranking-workflow" aria-label="筛选结果保存">
    <strong>参与筛选 {total} 个 → 最终保留 {retained} 个</strong>
    <div className="filter-case-buttons">
      <button disabled={!capture || retained === 0 || busy} onClick={() => {
        try { setPending(capture!()); setName(`筛选结果 ${new Date().toLocaleString()}`); setMessage(""); }
        catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
      }}>保存筛选结果（{retained}）</button>
      <button disabled={!capture || retained === 0} onClick={() => exportResult("csv")}>导出保留结果 CSV</button>
      <button disabled={!capture || retained === 0} onClick={() => exportResult("json")}>导出保留结果 JSON</button>
      <label><input type="checkbox" checked={onlyRetained} onChange={(event) => onOnlyRetained(event.target.checked)} />只看保留结果</label>
    </div>
    {pending && <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <label>案例名称 <input aria-label="筛选案例名称" value={name} maxLength={200} disabled={busy} onChange={(event) => setName(event.target.value)} /></label>
      <span>已固定点击时的 {pending.retained_ids.length} 个方案及筛选记录</span>
      <button disabled={busy || !name.trim()} type="submit">{busy ? "保存中…" : "确认保存"}</button>
      <button disabled={busy} type="button" onClick={() => setPending(null)}>取消</button>
    </form>}
    {message && <p role="status">{message}</p>}
  </section>;
}
