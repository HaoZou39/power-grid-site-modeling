import { useEffect, useState } from "react";
import { getExperiments, loadProblemSnapshot } from "./api";
import type { ExperimentRecord } from "./api";
import { emptyExperimentOverview } from "./problem_snapshot";
import type { ProblemSnapshot } from "./problem_snapshot";

const OBJECTIVE_LABEL: Record<ProblemSnapshot["objectiveOrder"][number], string> = {
  dem_soft: "地形平整度",
  road_distance: "道路距离（m）",
  demand_distance: "需求点距离（m）",
};

/** Problem context shown before a run. It renders a snapshot and does not interpret metrics. */
export function ProblemOverview() {
  const [experiments, setExperiments] = useState<ExperimentRecord[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<ProblemSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getExperiments()
      .then((items) => {
        if (cancelled) return;
        setExperiments(items);
        setSelectedId(items[0]?.id ?? null);
        if (items.length === 0) setLoading(false);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setError(messageOf(reason));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!experiments || !selectedId) return;
    const experiment = experiments.find((item) => item.id === selectedId);
    if (!experiment) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    loadProblemSnapshot(experiment)
      .then((next) => {
        if (!cancelled) setSnapshot(next);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setSnapshot(null);
          setError(messageOf(reason));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [experiments, selectedId]);

  const empty = experiments && experiments.length === 0 ? emptyExperimentOverview() : null;

  return (
    <section className="card problem-overview" aria-labelledby="problem-overview-title">
      <p className="eyebrow">步骤 1</p>
      <h2 id="problem-overview-title">问题概览</h2>
      {experiments && experiments.length > 1 && (
        <ExperimentPicker experiments={experiments} selectedId={selectedId} onSelect={setSelectedId} />
      )}
      {loading && <p className="muted">正在读取问题概览…</p>}
      {error && <p className="error">无法读取问题概览：{error}</p>}
      {empty && (
        <div className="problem-empty">
          <p>当前没有可展示的选址问题。</p>
          <MissingList missing={empty.missing} nextAction={empty.nextAction} />
        </div>
      )}
      {!loading && !error && snapshot && <ProblemSnapshotView snapshot={snapshot} />}
    </section>
  );
}

function ExperimentPicker({
  experiments,
  selectedId,
  onSelect,
}: {
  experiments: ExperimentRecord[];
  selectedId: string | null;
  onSelect: (experimentId: string) => void;
}) {
  return (
    <label className="experiment-picker">
      实验
      <select value={selectedId ?? ""} onChange={(event) => onSelect(event.target.value)}>
        {experiments.map((experiment) => (
          <option key={experiment.id} value={experiment.id}>{experiment.name}</option>
        ))}
      </select>
    </label>
  );
}

function ProblemSnapshotView({ snapshot }: { snapshot: ProblemSnapshot }) {
  return (
    <div className="problem-body">
      <p className="source-note">{snapshot.sourceLabel}</p>
      <dl className="problem-facts">
        <Fact label="实验名称" value={snapshot.experimentName} />
        <Fact label="栅格宽度" value={withUnit(snapshot.gridWidth, "格")} />
        <Fact label="栅格高度" value={withUnit(snapshot.gridHeight, "格")} />
        <Fact label="分辨率" value={snapshot.resolutionM} />
        <Fact label="坐标约定" value={snapshot.coordinateConvention} />
        <Fact label="数据来源" value={snapshot.dataSource} />
        <Fact label="需求点 seed" value={snapshot.seed} />
        <Fact label="建筑矩形宽度" value={snapshot.rectWidthM} />
        <Fact label="建筑矩形高度" value={snapshot.rectHeightM} />
      </dl>
      <h3>数据图层</h3>
      <ul className="layer-list">
        <LayerItem loaded={snapshot.layers.dem} label="DEM" />
        <LayerItem loaded={snapshot.layers.obstacle} label="不可建设区域" />
        <LayerItem loaded={snapshot.layers.roads} label="道路" />
        <LayerItem loaded={snapshot.layers.demandPoints} label="需求点" />
      </ul>
      <h3>目标顺序</h3>
      <ol className="objective-order">
        {snapshot.objectiveOrder.map((objective) => (
          <li key={objective}>
            {OBJECTIVE_LABEL[objective]}
            <span>{objective}</span>
          </li>
        ))}
      </ol>
      <p className="constraint-note">可行性规则：{snapshot.hardFeasibility}</p>
      <h3>基础地图</h3>
      <ul className="map-legend" aria-label="地图图例">
        <li><i className="swatch dem" />DEM：连续色带</li>
        <li><i className="swatch obstacle" />不可建设区域：半透明红色</li>
        <li><i className="swatch road" />道路：深色线</li>
        <li><i className="swatch demand" />需求点：橙色点</li>
      </ul>
      {snapshot.mapImageUrl ? (
        <img className="problem-map" src={snapshot.mapImageUrl} alt={`${snapshot.experimentName} 的基础地图预览`} />
      ) : (
        <p className="muted">没有可预览的地图。</p>
      )}
      {snapshot.missing.length > 0 && (
        <MissingList
          missing={snapshot.missing}
          nextAction="补齐列出的实验产物后，再查看完整的问题概览。"
        />
      )}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function LayerItem({ loaded, label }: { loaded: boolean; label: string }) {
  return <li className={loaded ? "loaded" : "unloaded"}>{label}：{loaded ? "已加载" : "未加载"}</li>;
}

function MissingList({ missing, nextAction }: { missing: readonly string[]; nextAction: string }) {
  return (
    <div className="problem-missing">
      <p>缺少：</p>
      <ul>
        {missing.map((item) => <li key={item}>{item}</li>)}
      </ul>
      <p>下一步：{nextAction}</p>
    </div>
  );
}

function withUnit(value: string, unit: string): string {
  return value === "未提供" ? value : `${value} ${unit}`;
}

function messageOf(reason: unknown): string {
  return reason instanceof Error && reason.message ? reason.message : "请求失败";
}
