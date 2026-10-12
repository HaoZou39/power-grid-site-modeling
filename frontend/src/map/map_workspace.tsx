import { useEffect, useRef, useState } from "react";
import { cancelJob, createJob, fetchArtifactText, fetchSiteReport, getExperiments, getJob, getScenes, pickLandusePatch } from "../api";
import type { JobRecord, SceneRecord, SiteReport } from "../api";
import { JOB_STATUS_LABEL, messageLabel } from "../run_status";
import { WorldMap } from "./world_map";
import { BuildingFootprint } from "./building_footprint";
import { BuildingSize, JobFollowUp, Nsga2DecisionRun, ParetoSelection, angleDegreesToRadians, choiceStatus, isChoiceEdited, radiansToDegrees } from "./decision_run";
import type { FieldPolicy, MountainPolicy } from "./decision_run";
import { ExclusionSketch } from "./exclusion_sketch";
import type { LocalPoint } from "./site_frame";
import { MapToolbar } from "./map_toolbar";
import { LANDUSE_CLASSES, hiddenLanduseClasses } from "./toolbar_commands";
import type { MapToolName } from "./toolbar_commands";
import { MapShortcuts } from "./map_shortcuts";
import type { MapCommands } from "./map_shortcuts";

const PREPARE_PLUGIN = "site.prepare_scene";
const DEFAULT_SCENE = "cangnan";
type EvaluationState = "idle" | "loading" | "success" | "error";

/** Decision map. Scene data is prepared once. Optimization only reads that scene. */
export function MapWorkspace({ health }: { health: string }) {
  const [tool, setTool] = useState<MapToolName>("pan");
  const [adjusting, setAdjusting] = useState(false);
  const [sketch, setSketch] = useState(() => new ExclusionSketch());
  const [notice, setNotice] = useState("");
  const [rectW, setRectW] = useState("77");
  const [rectH, setRectH] = useState("51.5");
  const [job, setJob] = useState<JobRecord | null>(null);
  const [selection, setSelection] = useState(() => new ParetoSelection([], 0));
  const [footprintSize, setFootprintSize] = useState(() => new BuildingSize(77, 51.5));
  const [focusToken, setFocusToken] = useState(0);
  const [scene, setScene] = useState<SceneRecord | null>(null);
  const [shownClasses, setShownClasses] = useState(hiddenLanduseClasses);
  const [fieldPolicy, setFieldPolicy] = useState<FieldPolicy>("allowed");
  const [mountainPolicy, setMountainPolicy] = useState<MountainPolicy>("allowed");
  const [fieldCost, setFieldCost] = useState("0.5");
  const [origin, setOrigin] = useState<LocalPoint | null>(null);
  const [report, setReport] = useState<SiteReport | null>(null);
  const [angleDeg, setAngleDeg] = useState("");
  const [evaluationState, setEvaluationState] = useState<EvaluationState>("idle");
  const [evaluationError, setEvaluationError] = useState("");
  const run = useRef(new Nsga2DecisionRun({ getExperiments, fetchArtifactText }));
  const followUp = useRef(new JobFollowUp());
  const commands = useRef<MapCommands>(idleCommands);

  const selected = selection.selected;
  const running = job !== null && JobFollowUp.isActive(job.status);
  const preparing = running && job?.plugin_id === PREPARE_PLUGIN;
  const sceneReady = scene?.ready === true;

  async function refreshScene() {
    const scenes = await getScenes();
    setScene(scenes.find((item) => item.id === DEFAULT_SCENE) ?? scenes[0] ?? null);
  }

  function addDraftPoint(point: LocalPoint) {
    setSketch((current) => current.addPoint(point));
    setNotice("");
  }

  function previewStroke(points: LocalPoint[]) {
    setSketch((current) => current.replaceDraft(points));
  }

  function finishStroke(points: LocalPoint[]) {
    try {
      setSketch((current) => current.finishStroke(points));
      setNotice("");
    } catch (reason) {
      setSketch((current) => current.replaceDraft([]));
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
      setSketch((current) => current.addZone(points));
      setNotice(`已标出 ${patch.cell_count} 个同类格子。`);
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法标出这块用地");
    }
  }

  function closeDraft() {
    try {
      setSketch(sketch.close());
      setTool("pan");
      setNotice("");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法闭合禁行区");
    }
  }

  async function prepareScene() {
    if (running) return;
    setNotice("");
    setSelection(new ParetoSelection([], 0));
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

  async function startOptimization() {
    if (running) return;
    if (!sceneReady) {
      setNotice("请先完成场景数据构建。优化不会在搜索时重新生成 DEM、道路和需求点。");
      return;
    }
    try {
      const size = BuildingSize.parse(rectW, rectH);
      const cost = fieldPolicy === "costly" ? Number(fieldCost) : 0.5;
      if (fieldPolicy === "costly" && (!Number.isFinite(cost) || cost <= 0 || cost > 1)) {
        setNotice("农田代价系数必须在 0 到 1 之间。");
        return;
      }
      setNotice("");
      setSelection(new ParetoSelection([], 0));
      setFootprintSize(size);
      setJob(await createJob(run.current.createRequest(size, scene?.id ?? DEFAULT_SCENE, new Date(), {
        fieldPolicy,
        mountainPolicy,
        fieldCost: cost,
        exclusionZones: sketch.zones.map((zone) => ({
          points: zone.points.map((point) => [point.x, point.y] as [number, number]),
        })),
      }, origin ?? undefined)));
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "无法开始优化");
    }
  }

  function applyAngle() {
    if (!selected) return;
    try {
      if (angleDeg.trim() === "") throw new Error("请输入旋转角度。");
      const theta = angleDegreesToRadians(Number(angleDeg));
      setSelection((current) => current.rotateSelected(theta, footprintSize));
      setNotice("");
    } catch (reason) {
      setAngleDeg(formatAngleDegrees(selected.theta));
      setNotice(reason instanceof Error ? reason.message : "无法应用这个旋转角度");
    }
  }

  function restoreOriginal() {
    if (!selected) return;
    setSelection((current) => current.restoreSelected());
    setNotice("");
  }

  commands.current = {
    drawing: tool === "draw",
    pan: () => setTool("pan"),
    draw: () => setTool("draw"),
    focus: () => setFocusToken((token) => token + 1),
    closeDraft,
    cancelDraft: () => {
      setSketch((current) => current.cancel());
      setTool("pan");
    },
    undoPoint: () => setSketch((current) => current.undoPoint()),
    previous: () => setSelection((current) => current.step(-1)),
    next: () => setSelection((current) => current.step(1)),
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
        setSelection(new ParetoSelection(choices, 0));
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
    setAngleDeg(selected ? formatAngleDegrees(selected.theta) : "");
  }, [selected?.id, selected?.theta]);

  useEffect(() => {
    if (!scene || !selected) {
      setReport(null);
      setEvaluationState("idle");
      setEvaluationError("");
      return;
    }
    if (adjusting) {
      setReport(null);
      setEvaluationState("loading");
      setEvaluationError("");
      return;
    }
    const cost = fieldPolicy === "costly" ? Number(fieldCost) : 0.5;
    if (!Number.isFinite(cost) || cost <= 0 || cost > 1) {
      setReport(null);
      setEvaluationState("error");
      setEvaluationError("农田代价系数必须在 0 到 1 之间，暂未重新评价。");
      return;
    }
    let stopped = false;
    setReport(null);
    setEvaluationState("loading");
    setEvaluationError("");
    const body = {
      x: selected.x,
      y: selected.y,
      theta: selected.theta,
      rect_w_m: footprintSize.widthM,
      rect_h_m: footprintSize.heightM,
      field_policy: fieldPolicy,
      mountain_policy: mountainPolicy,
      field_cost: cost,
      exclusion_zones: sketch.zones.map((zone) => ({
        points: zone.points.map((point) => [point.x, point.y] as [number, number]),
      })),
      ...(origin ? { origin_x: origin.x, origin_y: origin.y } : {}),
    };
    fetchSiteReport(scene.id, body)
      .then((value) => {
        if (!stopped) {
          setReport(value);
          setEvaluationState("success");
        }
      })
      .catch((reason) => {
        if (!stopped) {
          setReport(null);
          setEvaluationState("error");
          setEvaluationError(reason instanceof Error ? reason.message : "这次报告没有更新");
        }
      });
    return () => {
      stopped = true;
    };
  }, [scene?.id, selected, origin?.x, origin?.y, footprintSize.widthM, footprintSize.heightM, adjusting, fieldPolicy, mountainPolicy, fieldCost, sketch]);

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
        zones={sketch.zones}
        draft={sketch.draft}
        footprints={BuildingFootprint.layer(selection.choices, footprintSize, selection.index)}
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
          setOrigin(point);
          setNotice(`已标出进货原点 (${point.x.toFixed(0)}, ${point.y.toFixed(0)}) m。这次优化会比较沿路运输。`);
        }}
        onCloseDraft={closeDraft}
        onDrawOutside={() => setNotice("禁行区只能画在选址范围框内。")}
        onSelectFootprint={(id) => setSelection((current) => current.select(id))}
        onMoveFootprint={(dx, dy) => {
          setAdjusting(true);
          setSelection((current) => current.moveSelected(dx, dy, footprintSize));
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
      />
      <aside className="hud-panel">
        <p className="hud-kicker">1. 场景数据</p>
        <p className="hud-note">{scene ? `${scene.title} · ${scene.ready ? "已准备" : "尚未构建"}` : "正在读取场景"}</p>
        <p className="hud-note">选定范围后的 DEM、不可建设区域、道路和需求点在这里构建一次。之后可以再更新，但不会在每次优化时重做。</p>
        {preparing ? (
          <button type="button" className="scene-action" onClick={() => void stopPrepare()}>终止构建</button>
        ) : (
          <button type="button" className="scene-action" onClick={() => void prepareScene()} disabled={running}>
            {sceneReady ? "更新场景数据" : "构建场景数据"}
          </button>
        )}
        <p className="hud-kicker">2. 优化</p>
        <label>变电站宽度（m）<input value={rectW} onChange={(event) => setRectW(event.target.value)} /></label>
        <label>变电站高度（m）<input value={rectH} onChange={(event) => setRectH(event.target.value)} /></label>
        <p className="hud-note">默认按 110 kV 变电站占地 77 m × 51.5 m，可以改。</p>
        <label>山体
          <select value={mountainPolicy} onChange={(event) => setMountainPolicy(event.target.value as MountainPolicy)}>
            <option value="allowed">按坡度和进场判断</option>
            <option value="blocked">一律不可建设</option>
          </select>
        </label>
        <label>农田
          <select value={fieldPolicy} onChange={(event) => setFieldPolicy(event.target.value as FieldPolicy)}>
            <option value="allowed">按坡度和进场判断</option>
            <option value="blocked">一律不可建设</option>
            <option value="costly">允许建设，计入成本</option>
          </select>
        </label>
        {fieldPolicy === "costly" && (
          <label>农田代价系数<input value={fieldCost} onChange={(event) => setFieldCost(event.target.value)} /></label>
        )}
        <p className="hud-note">搜索使用 NSGA-II，直接比较五个目标，不需要填写权重。</p>
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
          <>
            <p className="hud-note">方案 {selection.index + 1}/{selection.choices.length}。点矩形或按 [ ] 切换。要移动时先点「调整方案」。</p>
            <label>旋转角度（°）
              <input
                type="number"
                step="1"
                value={angleDeg}
                onChange={(event) => setAngleDeg(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    applyAngle();
                  }
                }}
              />
            </label>
            <div className="hud-actions hud-edit-actions">
              <button type="button" onClick={applyAngle}>应用角度</button>
              <button type="button" onClick={restoreOriginal} disabled={!isChoiceEdited(selected)}>恢复原始方案</button>
            </div>
            {evaluationState === "loading" && (
              <p className="hud-evaluation loading">{adjusting ? "调整中，松手后重新评价…" : "正在重新评价…"}</p>
            )}
            {evaluationState === "success" && <p className="hud-evaluation success">报告已更新</p>}
            {evaluationState === "error" && <p className="hud-evaluation error">重新评价失败：{evaluationError}</p>}
            <dl className="hud-metrics">
              {choiceStatus(selected, report ? {
                demSoft: report.dem_soft ?? null,
                roadDistance: report.road_distance ?? null,
                demandDistance: report.demand_distance ?? null,
                obstacleHardCount: report.obstacle_hard_count ?? null,
                isFeasible: report.is_feasible ?? null,
                offroadHaulM: report.offroad_haul_m,
                haulRiseM: report.haul_rise_m,
                accessSlopeDeg: report.access_slope_deg,
                accessWarning: report.access_warning,
              } : null).map((row) => (
                <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>
              ))}
            </dl>
          </>
        )}
        <p className="hud-note">手绘禁区 {sketch.zones.length} 处。画圈松手闭合，或点选同类用地。这些范围进入这次优化。</p>
        {sketch.zones.map((zone) => (
          <button key={zone.id} type="button" className="legend-toggle" onClick={() => setSketch((current) => current.removeZone(zone.id))}>
            删除 {zone.id}
          </button>
        ))}
        <p className="hud-keys">V 拖拽 · B 画圈 · 点选同类单击闭合 · Esc 取消 · F 定位 · [ ] 切换方案 · P 开始优化</p>
        {notice && <p className="hud-notice">{notice}</p>}
      </aside>
    </div>
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

function formatAngleDegrees(theta: number): string {
  return radiansToDegrees(theta).toFixed(1).replace(/\.0$/, "");
}
