import { useEffect, useMemo, useState } from "react";
import { fetchArtifactText } from "./api";
import type { ExperimentRecord } from "./api";
import {
  NOT_PROVIDED,
  adaptSolutions,
  comparisonPoints,
  resultSummary,
  selectResultArtifacts,
  sortSolutions,
  toggleCompared,
} from "./solution_record";
import type { ComparisonPoint, SolutionRecord, SortKey } from "./solution_record";

/** Solution detail for one completed experiment. It only renders artifact contents. */
export function ResultExplorer({ experiment }: { experiment: ExperimentRecord }) {
  const artifacts = useMemo(() => selectResultArtifacts(experiment.artifacts), [experiment]);
  const [solutions, setSolutions] = useState<SolutionRecord[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [mapName, setMapName] = useState(artifacts.maps[0]?.name ?? "");
  const [sortKey, setSortKey] = useState<SortKey>("feasible");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [showInfeasible, setShowInfeasible] = useState(false);
  const [comparedKeys, setComparedKeys] = useState<string[]>([]);
  const [compareNotice, setCompareNotice] = useState("");

  useEffect(() => {
    setMapName(artifacts.maps[0]?.name ?? "");
    setSelectedKey(null);
    setComparedKeys([]);
    setCompareNotice("");
    setSolutions(null);
    if (!artifacts.solutionsUrl) {
      setSolutions(null);
      setLoading(false);
      setError("");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([
      fetchArtifactText(artifacts.solutionsUrl),
      artifacts.paretoSolutionsUrl ? fetchArtifactText(artifacts.paretoSolutionsUrl) : Promise.resolve(null),
    ])
      .then(([solutionsCsv, paretoCsv]) => {
        if (!cancelled) setSolutions(adaptSolutions(solutionsCsv, paretoCsv));
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error && reason.message ? reason.message : "无法读取方案表");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [experiment.id, artifacts]);

  const summary = resultSummary(experiment.summary, solutions);
  const sorted = useMemo(
    () => solutions ? sortSolutions(solutions, sortKey, sortDirection) : [],
    [solutions, sortKey, sortDirection],
  );
  const visible = sorted.filter((item) => showInfeasible || item.isFeasible !== false);
  const selected = visible.find((item) => item.key === selectedKey) ?? sorted.find((item) => item.key === selectedKey) ?? null;
  const activeMap = artifacts.maps.find((item) => item.name === mapName) ?? artifacts.maps[0] ?? null;

  function chooseSolution(key: string) {
    setSelectedKey(key);
  }

  function pinSolution(key: string) {
    const next = toggleCompared(comparedKeys, key);
    setComparedKeys(next.keys);
    setCompareNotice(next.rejected ? "最多同时比较 3 个方案。" : "");
    setSelectedKey(key);
  }

  const compared = comparedKeys
    .map((key) => sorted.find((item) => item.key === key))
    .filter((item): item is SolutionRecord => item !== undefined);

  function chooseSort(next: SortKey) {
    if (sortKey === next) {
      setSortDirection((direction) => direction === "asc" ? "desc" : "asc");
      return;
    }
    setSortKey(next);
    setSortDirection(next === "feasible" || next === "pareto" ? "desc" : "asc");
  }

  return (
    <div className="experiment-detail">
      <div className="experiment-title">
        <div>
          <p className="eyebrow">结果探索</p>
          <h2>{experiment.name}</h2>
        </div>
        <span className="badge">{experiment.algorithm}</span>
      </div>
      <p className="source-note">来自实验产物</p>
      <h3>结果摘要</h3>
      <div className="summary-grid">
        <SummaryItem label="总解数" value={summary.total} />
        <SummaryItem label="可行解数" value={summary.feasible} />
        <SummaryItem label="Pareto 解数" value={summary.pareto} />
        <SummaryItem label="是否存在可行解" value={summary.hasFeasible} />
      </div>
      <h3>主地图</h3>
      {artifacts.maps.length === 0 ? <p className="muted">缺少地图 PNG。下一步：确认实验目录里有 pareto_footprints_map.png 或其他地图产物。</p> : (
        <>
          <div className="map-switch" role="tablist" aria-label="地图切换">
            {artifacts.maps.map((map) => (
              <button key={map.name} type="button" className={activeMap?.name === map.name ? "active" : ""} onClick={() => setMapName(map.name)}>{map.label}</button>
            ))}
          </div>
          {activeMap && <img className="problem-map" src={activeMap.url} alt={`${experiment.name} 的${activeMap.label}`} />}
        </>
      )}
      <h3>方案详情</h3>
      {selected ? <SolutionDetail solution={selected} /> : <p className="muted">在方案表格或目标对比图中选择一个方案后，这里显示坐标、目标值和约束状态。</p>}
      <h3>目标对比</h3>
      {loading ? <p className="muted">正在读取方案表…</p> : (
        <ObjectiveComparison
          records={visible}
          selectedKey={selected?.key ?? null}
          onSelect={chooseSolution}
        />
      )}
      <h3>目标权衡</h3>
      {artifacts.paretoHtml ? (
        <article className="artifact-card artifact-html">
          <div className="artifact-heading">
            <strong>Pareto 三维图</strong>
            <a href={artifacts.paretoHtml.url} target="_blank" rel="noreferrer">新窗口打开</a>
          </div>
          <iframe src={artifacts.paretoHtml.url} title={`${experiment.name} 的 Pareto 三维图`} sandbox="allow-scripts" />
        </article>
      ) : <p className="muted">缺少 Pareto HTML。下一步：生成 pareto_3d_interactive.html 后再查看目标权衡。</p>}
      <h3>方案比较</h3>
      {compareNotice && <p className="muted">{compareNotice}</p>}
      {compared.length === 0 ? <p className="muted">在表格中把方案加入比较，最多三个。这里并排显示它们的坐标、目标和约束状态。</p> : (
        <div className="solution-compare">
          {compared.map((solution) => (
            <article key={solution.key} className={solution.key === selected?.key ? "selected" : ""}>
              <header>
                <strong>方案 {solution.id}</strong>
                <button type="button" onClick={() => pinSolution(solution.key)}>移出</button>
              </header>
              <button type="button" className="compare-focus" onClick={() => chooseSolution(solution.key)}>在表格和对比图中定位</button>
              <SolutionDetail solution={solution} />
            </article>
          ))}
        </div>
      )}
      <h3>方案表格</h3>
      {loading && <p className="muted">正在读取方案表…</p>}
      {error && <p className="error">无法读取方案表：{error}</p>}
      {!loading && !error && !artifacts.solutionsUrl && <p className="muted">缺少 solutions.csv。下一步：完成实验并保留方案表。</p>}
      {!loading && !error && artifacts.solutionsUrl && solutions && solutions.length === 0 && <p className="muted">solutions.csv 里没有方案行。</p>}
      {!loading && !error && visible.length > 0 && (
        <>
          <label className="checkbox-label">
            <input type="checkbox" checked={showInfeasible} onChange={(event) => setShowInfeasible(event.target.checked)} />
            显示不可行方案
          </label>
          <div className="solution-table-wrap">
            <table className="solution-table">
              <thead>
                <tr>
                  <th>方案</th>
                  <SortHeader label="可行性" sortKey="feasible" activeKey={sortKey} direction={sortDirection} onSort={chooseSort} />
                  <SortHeader label="Pareto" sortKey="pareto" activeKey={sortKey} direction={sortDirection} onSort={chooseSort} />
                  <th>x（m）</th>
                  <th>y（m）</th>
                  <SortHeader label="地形平整度" sortKey="demSoft" activeKey={sortKey} direction={sortDirection} onSort={chooseSort} />
                  <SortHeader label="道路距离（m）" sortKey="roadDistance" activeKey={sortKey} direction={sortDirection} onSort={chooseSort} />
                  <SortHeader label="需求点距离（m）" sortKey="demandDistance" activeKey={sortKey} direction={sortDirection} onSort={chooseSort} />
                </tr>
              </thead>
              <tbody>
                {visible.map((solution) => (
                  <tr
                    key={solution.key}
                    className={rowClass(solution, solution.key === selected?.key)}
                    tabIndex={0}
                    onClick={() => chooseSolution(solution.key)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") chooseSolution(solution.key);
                      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
                      event.preventDefault();
                      const index = visible.findIndex((item) => item.key === solution.key);
                      const next = visible[event.key === "ArrowDown" ? index + 1 : index - 1];
                      if (next) setSelectedKey(next.key);
                    }}
                  >
                    <td>
                      {solution.id}
                      <button type="button" onClick={(event) => { event.stopPropagation(); pinSolution(solution.key); }}>
                        {comparedKeys.includes(solution.key) ? "移出比较" : "加入比较"}
                      </button>
                    </td>
                    <td>{flagText(solution.isFeasible, "可行", "不可行")}</td>
                    <td>{flagText(solution.isPareto, "Pareto", "非 Pareto")}</td>
                    <td>{solution.x}</td>
                    <td>{solution.y}</td>
                    <td>{solution.demSoft}</td>
                    <td>{solution.roadDistance}</td>
                    <td>{solution.demandDistance}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <h3>原始产物</h3>
      {artifacts.downloads.length === 0 ? <p className="muted">没有 JSON 或 CSV 产物。</p> : (
        <div className="artifact-links">
          {artifacts.downloads.map((artifact) => (
            <a className="artifact-link" key={artifact.name} href={artifact.url} target="_blank" rel="noreferrer">
              <strong>{artifact.name}</strong>
              <span>{artifact.kind === "table" ? "CSV 表格" : "JSON 数据"}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function ObjectiveComparison({
  records,
  selectedKey,
  onSelect,
}: {
  records: SolutionRecord[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
}) {
  const points = comparisonPoints(records);
  if (points.length === 0) {
    return <p className="muted">缺少可对比的道路距离或需求点距离。下一步：确认 solutions.csv 含有这两列。</p>;
  }
  const plotted = plotPoints(points);
  return (
    <div className="comparison">
      <p className="field-description">横轴是道路距离，纵轴是需求点距离，单位都是 m。两个目标都按最小化解释。坐标范围只取当前表格中的数值，不是建模里的 normalization。</p>
      <svg viewBox="0 0 640 360" role="img" aria-label="道路距离与需求点距离对比">
        <line x1="48" y1="24" x2="48" y2="312" />
        <line x1="48" y1="312" x2="616" y2="312" />
        <text x="332" y="348">道路距离（m）</text>
        <text x="16" y="168" transform="rotate(-90 16 168)">需求点距离（m）</text>
        {plotted.map((point) => (
          <circle
            key={point.key}
            cx={point.cx}
            cy={point.cy}
            r={point.key === selectedKey ? 7 : 4.5}
            className={pointClass(point, point.key === selectedKey)}
            tabIndex={0}
            role="button"
            aria-label={`方案 ${point.id}`}
            onClick={() => onSelect(point.key)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onSelect(point.key);
            }}
          >
            <title>{`方案 ${point.id}`}</title>
          </circle>
        ))}
      </svg>
      <ul className="map-legend" aria-label="对比图例">
        <li><i className="swatch feasible-dot" />可行方案</li>
        <li><i className="swatch infeasible-dot" />不可行方案</li>
        <li><i className="swatch pareto-dot" />Pareto 方案</li>
        <li><i className="swatch selected-dot" />当前选中</li>
      </ul>
    </div>
  );
}

function plotPoints(points: ComparisonPoint[]): Array<ComparisonPoint & { cx: number; cy: number }> {
  const roads = points.map((point) => point.roadDistance);
  const demands = points.map((point) => point.demandDistance);
  const roadMin = Math.min(...roads);
  const roadMax = Math.max(...roads);
  const demandMin = Math.min(...demands);
  const demandMax = Math.max(...demands);
  return points.map((point) => ({
    ...point,
    cx: scale(point.roadDistance, roadMin, roadMax, 64, 600),
    cy: scale(point.demandDistance, demandMin, demandMax, 296, 40),
  }));
}

function scale(value: number, min: number, max: number, start: number, end: number): number {
  if (max === min) return (start + end) / 2;
  return start + ((value - min) / (max - min)) * (end - start);
}

function pointClass(point: ComparisonPoint, selected: boolean): string {
  const names = ["comparison-point"];
  if (point.isFeasible === false) names.push("infeasible");
  else names.push("feasible");
  if (point.isPareto) names.push("pareto");
  if (selected) names.push("selected");
  return names.join(" ");
}

function SolutionDetail({ solution }: { solution: SolutionRecord }) {
  return (
    <dl className="problem-facts">
      <Fact label="方案" value={solution.id} />
      <Fact label="x（m）" value={solution.x} />
      <Fact label="y（m）" value={solution.y} />
      <Fact label="theta（rad）" value={solution.theta} />
      <Fact label="地形平整度" value={solution.demSoft} />
      <Fact label="道路距离（m）" value={solution.roadDistance} />
      <Fact label="需求点距离（m）" value={solution.demandDistance} />
      <Fact label="不可建设区域 hard count" value={solution.obstacleHardCount} />
      <Fact label="可行性" value={flagText(solution.isFeasible, "可行", "不可行")} />
      <Fact label="Pareto" value={flagText(solution.isPareto, "Pareto 方案", "非 Pareto 方案")} />
    </dl>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function SummaryItem({ label, value }: { label: string; value: string }) {
  return <div className="summary-item"><span>{label}</span><strong>{value}</strong></div>;
}

function SortHeader({
  label,
  sortKey,
  activeKey,
  direction,
  onSort,
}: {
  label: string;
  sortKey: SortKey;
  activeKey: SortKey;
  direction: "asc" | "desc";
  onSort: (key: SortKey) => void;
}) {
  const active = activeKey === sortKey;
  return (
    <th>
      <button type="button" onClick={() => onSort(sortKey)}>
        {label}{active ? (direction === "asc" ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );
}

function flagText(value: boolean | null, yes: string, no: string): string {
  if (value === null) return NOT_PROVIDED;
  return value ? yes : no;
}

function rowClass(solution: SolutionRecord, selected: boolean): string {
  const names = ["solution-row"];
  if (solution.isFeasible === false) names.push("infeasible");
  if (solution.isFeasible === true) names.push("feasible");
  if (solution.isPareto) names.push("pareto");
  if (selected) names.push("selected");
  return names.join(" ");
}
