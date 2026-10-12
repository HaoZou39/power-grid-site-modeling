import { useEffect, useRef, useState } from "react";
import { cancelJob, createJob, deleteExperiment, fetchArtifactText, fetchSiteReport, getExperiments, getJob, getScenes, pickLandusePatch } from "../api";
import type { ExperimentRecord, JobRecord, SceneRecord, SiteReport } from "../api";
import { JOB_STATUS_LABEL, messageLabel } from "../run_status";
import { WorldMap } from "./world_map";
import { BuildingFootprint } from "./building_footprint";
import { BuildingSize, JobFollowUp, Nsga2DecisionRun, buildingSizeFromResolvedConfig, compareChart, schemeCard } from "./decision_run";
import type { StatusRow } from "./decision_run";
import type { ParetoChoice } from "./decision_run";
import { SiteEdit } from "./site_edit";
import type { FieldPolicy, RegionKind } from "./site_edit";
import type { LocalPoint } from "./site_frame";
import { HistoryPanel } from "./history_panel";
import { MapToolbar } from "./map_toolbar";
import { LANDUSE_CLASSES, hiddenLanduseClasses } from "./toolbar_commands";
import type { MapToolName } from "./toolbar_commands";
import { MapShortcuts } from "./map_shortcuts";
import type { MapCommands } from "./map_shortcuts";

const PREPARE_PLUGIN = "site.prepare_scene";
const DEFAULT_SCENE = "cangnan";

/** Decision map. Scene data is prepared once. Optimization only reads that scene. */
export function MapWorkspace({ health }: { health: string }) {
  const [tool, setTool] = useState<MapToolName>("pan");
  const [adjusting, setAdjusting] = useState(false);
  const [edit, setEdit] = useState(() => new SiteEdit<ParetoChoice>());
  const editRef = useRef(edit);
  editRef.current = edit;
  const [notice, setNoticeText] = useState("");
  const [noticeToken, setNoticeToken] = useState(0);
  const [noticeFading, setNoticeFading] = useState(false);
  function setNotice(message: string) {
    setNoticeFading(false);
    setNoticeText(message);
    setNoticeToken((token) => token + 1);
  }
  const [rectW, setRectW] = useState("77");
  const [rectH, setRectH] = useState("51.5");
  const [job, setJob] = useState<JobRecord | null>(null);
  const [focusToken, setFocusToken] = useState(0);
  const [scene, setScene] = useState<SceneRecord | null>(null);
  const [shownClasses, setShownClasses] = useState(hiddenLanduseClasses);
  const [fieldCost, setFieldCost] = useState("0.5");
  const [report, setReport] = useState<SiteReport | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<ExperimentRecord[] | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [loadedCaseId, setLoadedCaseId] = useState<string | null>(null);
  const [closedCardId, setClosedCardId] = useState<string | null>(null);
  const [comparedIds, setComparedIds] = useState<string[]>([]);
  const run = useRef(new Nsga2DecisionRun({ getExperiments, fetchArtifactText }));
  const followUp = useRef(new JobFollowUp());
  const commands = useRef<MapCommands>(idleCommands);

  const selected = edit.selected;
  const origin = edit.origin;
  const liveReport = report ? {
    offroadHaulM: report.offroad_haul_m,
    haulRiseM: report.haul_rise_m,
    accessSlopeDeg: report.access_slope_deg,
    accessWarning: report.access_warning,
    roadHaulM: report.road_haul_m,
  } : null;
  const compared = comparedIds.flatMap((id) => {
    const index = edit.poses.findIndex((pose) => pose.id === id);
    const pose = edit.poses[index];
    if (!pose) return [];
    return [{ id, name: `方案 ${index + 1}`, choice: pose, colorIndex: index }];
  });
  const running = job !== null && JobFollowUp.isActive(job.status);
  const preparing = running && job?.plugin_id === PREPARE_PLUGIN;
  const sceneReady = scene?.ready === true;

  useEffect(() => {
    if (!notice) {
      setNoticeFading(false);
      return;
    }
    setNoticeFading(false);
    const fade = window.setTimeout(() => setNoticeFading(true), 4500);
    const clear = window.setTimeout(() => setNoticeText(""), 5400);
    return () => {
      window.clearTimeout(fade);
      window.clearTimeout(clear);
    };
  }, [noticeToken]);

  async function refreshScene() {
    const scenes = await getScenes();
    setScene(scenes.find((item) => item.id === DEFAULT_SCENE) ?? scenes[0] ?? null);
  }

  function sketchKind(): RegionKind {
    return tool === "feasible" ? "feasible" : "exclusion";
  }

  function addDraftPoint(point: LocalPoint) {
    setEdit((current) => current.addDraftPoint(point, sketchKind()));
    setNotice("");
  }

  function previewStroke(points: LocalPoint[]) {
    setEdit((current) => current.replaceDraft(points));
  }

  function finishStroke(points: LocalPoint[]) {
    try {
      setEdit(editRef.current.finishStroke(points, sketchKind()));
      setNotice("");
    } catch (reason) {
      setEdit(editRef.current.cancelDraft());
      setNotice(reason instanceof Error ? reason.message : "无法闭合禁行区");
    }
  }

  async function pickPatch(point: LocalPoint) {
    if (!scene) {
      setNotice("场景还没有准备好，不能点选用地。");
      return;
    }
    try {
      const patch = await pickLandusePatch(scene.id, point.x, point.y);
      const points = patch.points.map(([x, y]) => ({ x, y }));
      setEdit(editRef.current.addExclusion(points));
      setNotice(`已标出 ${patch.cell_count} 个同类格子。`);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法标出这块用地");
    }
  }

  function closeDraft() {
    try {
      setEdit(editRef.current.closeDraft(sketchKind()));
      setTool("pan");
      setNotice("");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法闭合禁行区");
    }
  }

  async function prepareScene() {
    if (running) return;
    setNotice("");
    setEdit((current) => current.clearPoses());
    setComparedIds([]);
    setClosedCardId(null);
    setLoadedCaseId(null);
    try {
      setJob(await createJob({ plugin_id: PREPARE_PLUGIN, config: { scene_name: scene?.id ?? DEFAULT_SCENE } }));
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法构建场景数据");
    }
  }

  async function stopPrepare() {
    if (!job || job.plugin_id !== PREPARE_PLUGIN) return;
    try {
      setJob(await cancelJob(job.job_id));
      setNotice("构建已终止。正在进行的这一步结束后不再继续。");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法终止构建");
    }
  }

  async function toggleHistory() {
    if (historyOpen) {
      setHistoryOpen(false);
      setPendingDeleteId(null);
      return;
    }
    setHistoryOpen(true);
    setHistoryError("");
    setPendingDeleteId(null);
    try {
      setHistory(await getExperiments());
    } catch (reason) {
      setHistory(null);
      setHistoryError(reason instanceof Error ? reason.message : "无法读取历史结果");
    }
  }

  async function importHistory(experimentId: string) {
    if (running) {
      setNotice("优化进行中，结束后再导入历史结果。");
      return;
    }
    try {
      const experiments = history ?? await getExperiments();
      const experiment = experiments.find((item) => item.id === experimentId);
      const choices = await run.current.loadPareto(experimentId);
      const size = await importedBuildingSize(experiment);
      setEdit((current) => {
        const sized = size ? current.withBuilding(size.widthM, size.heightM) : current;
        return sized.withPoses(choices);
      });
      if (size) {
        setRectW(String(size.widthM));
        setRectH(String(size.heightM));
      }
      setComparedIds([]);
      setClosedCardId(null);
      setLoadedCaseId(experimentId);
      setFocusToken((token) => token + 1);
      setHistoryOpen(false);
      setNotice(`已导入 ${experimentId}，共 ${choices.length} 个可行帕累托方案。`);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法导入这次结果");
    }
  }

  async function confirmDeleteHistory(experimentId: string) {
    const activeName = running ? String(job?.config.experiment_name ?? "") : "";
    if (activeName && activeName === experimentId) {
      setPendingDeleteId(null);
      setNotice("这次优化还在写入该目录，结束后才能删除。");
      return;
    }
    try {
      await deleteExperiment(experimentId);
      setHistory((current) => current?.filter((item) => item.id !== experimentId) ?? null);
      setPendingDeleteId(null);
      if (loadedCaseId === experimentId) {
        setEdit((current) => current.clearPoses());
        setComparedIds([]);
        setClosedCardId(null);
        setLoadedCaseId(null);
      }
      setNotice(`已删除 ${experimentId}。`);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法删除这次结果");
    }
  }

  async function startOptimization() {
    if (running) return;
    if (!sceneReady) {
      setNotice("请先完成场景数据构建。优化不会在搜索时重新生成 DEM、道路和需求点。");
      return;
    }
    try {
      const current = editRef.current;
      const size = BuildingSize.parse(rectW, rectH);
      const cost = current.fieldPolicy === "costly" ? Number(fieldCost) : 0.5;
      if (current.fieldPolicy === "costly" && (!Number.isFinite(cost) || cost <= 0 || cost > 1)) {
        setNotice("农田代价系数必须在 0 到 1 之间。");
        return;
      }
      const submitted = current
        .withScene(scene?.id ?? DEFAULT_SCENE)
        .withBuilding(size.widthM, size.heightM)
        .withPolicies("allowed", current.fieldPolicy, cost)
        .clearPoses();
      setNotice("");
      setEdit(submitted);
      setComparedIds([]);
      setClosedCardId(null);
      setLoadedCaseId(null);
      setJob(await createJob(run.current.createRequest(submitted, new Date())));
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法开始优化");
    }
  }

  commands.current = {
    drawing: tool === "exclusion" || tool === "feasible",
    pan: () => setTool("pan"),
    draw: () => setTool("exclusion"),
    focus: () => setFocusToken((token) => token + 1),
    closeDraft,
    cancelDraft: () => {
      setEdit((current) => current.cancelDraft());
      setTool("pan");
    },
    undoPoint: () => setEdit((current) => current.undoPoint()),
    previous: () => setEdit((current) => current.stepPose(-1)),
    next: () => setEdit((current) => current.stepPose(1)),
    optimize: () => void startOptimization(),
  };

  useEffect(() => {
    if (!job || !JobFollowUp.isActive(job.status)) return;
    let stopped = false;
    const poll = async () => {
      try {
        const record = await getJob(job.job_id);
        if (stopped) return;
        setJob(record);
        const failed = followUp.current.failureNotice(record);
        if (failed) setNotice(failed);
        if (record.plugin_id === PREPARE_PLUGIN) {
          if (followUp.current.opened(record.job_id, record.status)) {
            await refreshScene();
            setNotice("场景数据已更新。之后的优化会直接读取它，不会重新构建。");
          }
          return;
        }
        const experimentId = followUp.current.claimExperiment(record);
        if (!experimentId) return;
        const choices = await run.current.loadPareto(experimentId);
        setEdit((current) => current.withPoses(choices));
        setComparedIds([]);
        setClosedCardId(null);
        setLoadedCaseId(experimentId);
        setFocusToken((token) => token + 1);
        setNotice("");
      } catch (reason) {
        if (!stopped) setNotice(reason instanceof Error ? reason.message : "无法读取任务状态");
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [job?.job_id, job?.status]);

  useEffect(() => {
    refreshScene().catch((reason) => {
      setNotice(reason instanceof Error ? reason.message : "无法读取场景");
    });
  }, []);

  useEffect(() => {
    if (!scene || !selected || adjusting) {
      if (!selected) setReport(null);
      return;
    }
    let stopped = false;
    const body = edit.reportRequest();
    if (!body) return;
    fetchSiteReport(scene.id, body)
      .then((value) => {
        if (!stopped) setReport(value);
      })
      .catch(() => {
        if (!stopped) setNotice("这次报告没有更新");
      });
    return () => {
      stopped = true;
    };
  }, [scene?.id, selected, edit.marks, edit.widthM, edit.heightM, adjusting]);

  useEffect(() => {
    const shortcuts = new MapShortcuts(() => commands.current);
    const onKeyDown = (event: KeyboardEvent) => shortcuts.handle(event);
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="map-app">
      <WorldMap
        tool={tool}
        zones={edit.zones}
        draft={edit.draft}
        footprints={BuildingFootprint.layer(edit.poses, { widthM: edit.widthM, heightM: edit.heightM }, edit.selectedIndex)}
        landuseLayers={sceneReady && scene ? LANDUSE_CLASSES.map((item) => ({
          id: item.id,
          url: `/api/v1/scenes/${scene.id}/landuse-overlay/${item.id}`,
          visible: shownClasses[item.id],
        })) : []}
        haulPath={(report?.haul_path ?? []).map(([x, y]) => ({ x, y }))}
        origin={origin}
        focusToken={focusToken}
        onAddDraftPoint={addDraftPoint}
        onPreviewStroke={previewStroke}
        onFinishStroke={finishStroke}
        onPickPoint={(point) => void pickPatch(point)}
        onPickOrigin={(point) => {
          try {
            setEdit((current) => current.putOrigin(point));
            setNotice(`已标出进货原点 (${point.x.toFixed(0)}, ${point.y.toFixed(0)}) m。这次优化会比较沿路运输。`);
          } catch (reason) {
            setNotice(reason instanceof Error ? reason.message : "无法标出进货原点");
          }
        }}
        onCloseDraft={closeDraft}
        onDrawOutside={() => setNotice("范围只能画在选址范围框内。")}
        onSelectFootprint={(id) => setEdit((current) => current.selectPose(id))}
        onEraseZone={(id) => {
          if (!id) {
            setNotice("这里没有可擦掉的范围。");
            return;
          }
          setEdit((current) => current.removeRegion(id));
          setNotice("已擦掉这块范围。");
        }}
        onMoveFootprint={(dx, dy) => {
          setAdjusting(true);
          setEdit((current) => current.moveSelected(dx, dy));
        }}
        onFinishMove={() => setAdjusting(false)}
      />
      <header className="hud-top">
        <div>
          <p>温州电力设计院</p>
          <strong>苍南选址规划</strong>
        </div>
        <span className={health.includes("失败") ? "hud-health bad" : "hud-health"}>{health}</span>
      </header>
      <MapToolbar
        tool={tool}
        shownClasses={shownClasses}
        notify={setNotice}
        focusSite={() => setFocusToken((token) => token + 1)}
        setTool={setTool}
        toggleClass={(id) => setShownClasses((current) => ({ ...current, [id]: !current[id] }))}
        hasSelection={selected !== null}
        sceneLabel={preparing ? "终止构建" : sceneReady ? "更新场景数据" : "构建场景数据"}
        sceneDisabled={!preparing && running}
        onPrepare={() => void (preparing ? stopPrepare() : prepareScene())}
        optimizeLabel={running && !preparing ? "正在优化…" : "开始优化"}
        optimizeDisabled={running || !sceneReady}
        onOptimize={() => void startOptimization()}
        historyOpen={historyOpen}
        onImportCase={() => void toggleHistory()}
      />
      {historyOpen && (
        <HistoryPanel
          experiments={history ?? []}
          loading={history === null && !historyError}
          error={historyError}
          pendingDeleteId={pendingDeleteId}
          onClose={() => {
            setHistoryOpen(false);
            setPendingDeleteId(null);
          }}
          onImport={(experimentId) => void importHistory(experimentId)}
          onAskDelete={setPendingDeleteId}
          onConfirmDelete={(experimentId) => void confirmDeleteHistory(experimentId)}
          onCancelDelete={() => setPendingDeleteId(null)}
        />
      )}
      <aside className="hud-panel">
        <p className="hud-kicker">1. 场景数据</p>
        <p className="hud-note">{scene ? `${scene.title} · ${scene.ready ? "已准备" : "尚未构建"}` : "正在读取场景"}</p>
        <p className="hud-note">选定范围后的 DEM、不可建设区域、道路和需求点在这里构建一次。之后可以再更新，但不会在每次优化时重做。构建和更新用上方「主页」里的按钮。</p>
        <p className="hud-kicker">2. 优化</p>
        <label>变电站长度（m）<input value={rectW} onChange={(event) => setRectW(event.target.value)} /></label>
        <label>变电站宽度（m）<input value={rectH} onChange={(event) => setRectH(event.target.value)} /></label>
        <p className="hud-note">110 kV 变电站默认占地尺寸：长 77 m × 宽 51.5 m，可修改。</p>
        <label>农田
          <select value={edit.fieldPolicy} onChange={(event) => setEdit((current) => current.withPolicies("allowed", event.target.value as FieldPolicy, current.fieldCost))}>
            <option value="allowed">按坡度和进场判断</option>
            <option value="blocked">一律不可建设</option>
            <option value="costly">允许建设，计入成本</option>
          </select>
        </label>
        {edit.fieldPolicy === "costly" && (
          <label>农田代价系数<input value={fieldCost} onChange={(event) => setFieldCost(event.target.value)} /></label>
        )}
        <button type="button" className="primary" onClick={() => void startOptimization()} disabled={running || !sceneReady}>
          {running && !preparing ? "正在优化…" : "开始优化 P"}
        </button>
        {job && <p className="hud-note">{JOB_STATUS_LABEL[job.status]} · {messageLabel(job.message)}</p>}
        {origin ? (
          <p className="hud-note">进货原点 ({origin.x.toFixed(0)}, {origin.y.toFixed(0)}) m，地图上的黄点。这次会比较沿路运输。</p>
        ) : (
          <p className="hud-note">未设置进货原点，这次不比较沿路运输。需要时点「进货原点」再在图上点一下。</p>
        )}
        {selected && (
          <p className="hud-note">方案 {edit.selectedIndex + 1}/{edit.poses.length}。点矩形或按 [ ] 切换。要移动时先点「调整方案」。</p>
        )}
        <p className="hud-note">范围 {edit.zones.length} 处，禁区 {edit.zones.filter((zone) => zone.kind === "exclusion").length}，可行域 {edit.zones.filter((zone) => zone.kind === "feasible").length}。在「编辑」里画禁区或可行域，橡皮擦点中可删，或点选同类用地。这些范围进入这次优化。</p>
        {edit.zones.map((zone) => (
          <button key={zone.id} type="button" className="legend-toggle" onClick={() => setEdit((current) => current.removeRegion(zone.id))}>
            删除 {zone.kind === "feasible" ? "可行域" : "禁区"} {zone.id}
          </button>
        ))}
        <p className="hud-keys">V 拖拽 · B 禁区 · 点选同类单击闭合 · Esc 取消 · F 定位 · [ ] 切换方案 · P 开始优化</p>
      </aside>
      {notice && <p className={noticeFading ? "map-toast fading" : "map-toast"} role="status">{notice}</p>}
      {selected && closedCardId !== selected.id && (
        <SchemeCard
          title={`方案 ${edit.selectedIndex + 1}/${edit.poses.length}`}
          card={schemeCard(selected, liveReport, origin !== null)}
          onClose={() => setClosedCardId(selected.id)}
          compared={comparedIds.includes(selected.id)}
          onToggleCompare={() => {
            if (comparedIds.includes(selected.id)) {
              setComparedIds((current) => current.filter((id) => id !== selected.id));
              return;
            }
            if (comparedIds.length >= 5) {
              setNotice("最多同时对比 5 个方案。");
              return;
            }
            setComparedIds((current) => (
              current.includes(selected.id) || current.length >= 5 ? current : [...current, selected.id]
            ));
          }}
        />
      )}
      {compared.length > 0 && (
        <ComparePanel items={compared} scale={edit.poses} onClear={() => setComparedIds([])} />
      )}
    </div>
  );
}

async function importedBuildingSize(experiment: ExperimentRecord | undefined): Promise<BuildingSize | null> {
  const url = experiment?.artifacts.find((item) => item.name === "resolved_config.json")?.url;
  if (!url) return null;
  try {
    return buildingSizeFromResolvedConfig(JSON.parse(await fetchArtifactText(url)));
  } catch {
    return null;
  }
}

function SchemeCard({
  title,
  card,
  compared,
  onToggleCompare,
  onClose,
}: {
  title: string;
  card: { decisions: StatusRow[]; objectives: StatusRow[] };
  compared: boolean;
  onToggleCompare: () => void;
  onClose: () => void;
}) {
  return (
    <aside className="scheme-card">
      <div className="scheme-card-head">
        <strong>{title}</strong>
        <button type="button" className="drawer-close" onClick={onClose}>关闭</button>
      </div>
      <p className="hud-kicker">决策变量</p>
      <dl className="hud-metrics">{card.decisions.map((row) => <Metric key={row.label} row={row} />)}</dl>
      <p className="hud-kicker">目标</p>
      <dl className="hud-metrics">{card.objectives.map((row) => <Metric key={row.label} row={row} />)}</dl>
      <button type="button" className="legend-toggle" onClick={onToggleCompare}>{compared ? "移出对比" : "加入对比"}</button>
    </aside>
  );
}

function Metric({ row }: { row: StatusRow }) {
  return <div><dt>{row.label}</dt><dd>{row.value}</dd></div>;
}

const COMPARE_COLORS = ["#39f3ff", "#ff8b96", "#ffd166", "#3dd68c", "#d78bff"];

function ComparePanel({
  items,
  scale,
  onClear,
}: {
  items: { id: string; name: string; choice: ParetoChoice; colorIndex: number }[];
  scale: readonly ParetoChoice[];
  onClear: () => void;
}) {
  const chart = compareChart(items, scale);
  const width = 640;
  const height = 210;
  const padLeft = 36;
  const padRight = 16;
  const padTop = 12;
  const padBottom = 44;
  const span = Math.max(chart.labels.length - 1, 1);
  const inner = height - padTop - padBottom;
  const xAt = (index: number) => padLeft + (index * (width - padLeft - padRight)) / span;
  const yAt = (value: number) => height - padBottom - value * inner;
  return (
    <section className="compare-panel">
      <div className="scheme-card-head">
        <strong>方案对比</strong>
        <button type="button" className="drawer-close" onClick={onClear}>清空</button>
      </div>
      <p className="hud-note">每条线是一个方案。各项都是越小越好，线越低越优。纵轴按这次全部帕累托方案固定，再加入一条线不会改动已经画出的线。</p>
      {items.length < 2 ? <p className="hud-note">再加入一个方案，折线才会叠在一起。</p> : (
        <svg className="compare-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="方案目标折线对比">
          {chart.labels.map((label, index) => (
            <g key={label}>
              <line x1={xAt(index)} y1={padTop} x2={xAt(index)} y2={height - padBottom} stroke="rgb(120 230 255 / 25%)" />
              <text x={xAt(index)} y={height - 14} textAnchor="middle" fill="#d7f6ff" fontSize="22">{label}</text>
            </g>
          ))}
          {chart.series.map((series, seriesIndex) => {
            const points = series.values.flatMap((value, index) => value === null ? [] : [`${xAt(index)},${yAt(value)}`]);
            const color = COMPARE_COLORS[items[seriesIndex].colorIndex % COMPARE_COLORS.length];
            return <polyline key={series.id} points={points.join(" ")} fill="none" stroke={color} strokeWidth="2.5" />;
          })}
        </svg>
      )}
      <div className="compare-legend">
        {items.map((item) => (
          <span key={item.id}><i style={{ background: COMPARE_COLORS[item.colorIndex % COMPARE_COLORS.length] }} />{item.name}</span>
        ))}
      </div>
    </section>
  );
}

const idleCommands: MapCommands = {
  drawing: false,
  pan: () => undefined,
  draw: () => undefined,
  focus: () => undefined,
  closeDraft: () => undefined,
  cancelDraft: () => undefined,
  undoPoint: () => undefined,
  previous: () => undefined,
  next: () => undefined,
  optimize: () => undefined,
};
