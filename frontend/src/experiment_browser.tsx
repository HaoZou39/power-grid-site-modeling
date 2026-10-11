import { useEffect, useMemo, useState } from "react";
import { getExperiments } from "./api";
import type { ExperimentRecord } from "./api";
import { ResultExplorer } from "./result_explorer";
import { experimentListStats } from "./solution_record";

/** Read-only catalog of completed experiments. Solution details live in ResultExplorer. */

export function ExperimentBrowser() {
  const [experiments, setExperiments] = useState<ExperimentRecord[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getExperiments()
      .then((items) => {
        setExperiments(items);
        if (items.length > 0) setSelectedId(items[0].id);
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, []);

  const selected = useMemo(
    () => experiments.find((experiment) => experiment.id === selectedId),
    [experiments, selectedId],
  );

  if (error) return <p className="error">实验目录加载失败：{error}</p>;
  if (loading) return <p className="muted">正在加载实验目录...</p>;
  if (experiments.length === 0) return <p className="muted">暂无已完成实验。请先运行一个实验并生成 run_summary.json。</p>;

  return (
    <div className="experiment-layout">
      <aside className="experiment-list">
        <p className="eyebrow">实验结果</p>
        {experiments.map((experiment) => {
          const stats = experimentListStats(experiment.summary);
          return (
            <button
              className={`experiment-item ${selectedId === experiment.id ? "selected" : ""}`}
              key={experiment.id}
              onClick={() => setSelectedId(experiment.id)}
            >
              <strong>{experiment.name}</strong>
              <span>{experiment.algorithm}</span>
              <small>完成时间：{stats.finishedAt}</small>
              <small>{stats.total} 个方案 · 可行 {stats.feasible} · Pareto {stats.pareto}</small>
            </button>
          );
        })}
      </aside>
      {selected && <ResultExplorer experiment={selected} />}
    </div>
  );
}
