import type { SceneRecord } from "../api";
import { JOB_STATUS_LABEL } from "../run_status";
import { ROUTING_FIELD_LABELS } from "./routing_edit";
import { RoutingAlgorithmControls } from "./routing_algorithm_controls";
import type { RoutingEdit, RoutingFields } from "./routing_edit";
import type { RoutingController } from "./use_routing_controller";
import type { ReactNode } from "react";
import { useState } from "react";

type Controls = Pick<RoutingController, "edit" | "pick" | "draft" | "busy" | "jobId" | "job" | "error" | "notice" |
  "update" | "beginPick" | "removeRegion" | "start" | "cancel">;

export function RoutingControls({ state, scene, landuseBlocked, resizeHandle, children }: {
  state: Controls; scene: SceneRecord | null;
  landuseBlocked: boolean; resizeHandle?: ReactNode; children?: ReactNode;
}) {
  const { edit, pick, draft, busy, jobId, job, error, notice, update,
    beginPick, removeRegion, start, cancel } = state;
  const [minimized, setMinimized] = useState(false);
  return <aside className={`hud-panel routing-controls${minimized ? " minimized" : ""}`} aria-label="选线配置">
      {!minimized && resizeHandle}
      <div className="hud-panel-head"><p className="hud-kicker">选线优化</p>
        <button type="button" className="agent-min" aria-label={minimized ? "展开工作栏" : "最小化工作栏"}
          onClick={() => setMinimized((current) => !current)}>{minimized ? "▢" : "–"}</button></div>
      {!minimized && <div className="hud-panel-body">
      <fieldset disabled={busy || !scene?.ready || scene.read_only === true}>
        {(["start", "end"] as const).map((which) => <section key={which} className="routing-connection">
          <div className="routing-connection-head">
            <strong>{which === "start" ? "起点" : "终点"} · 固定接入点</strong>
            <button type="button" aria-pressed={pick === which} onClick={() => { beginPick(which); }}>地图点选{which === "start" ? "起点" : "终点"}</button>
          </div>
          <div className="routing-pair">
            <label>经度<input aria-label={`${which === "start" ? "起点" : "终点"}经度`} value={edit[which].lng}
              onChange={(event) => update(edit.connection(which, { ...edit[which], lng: event.target.value }))} /></label>
            <label>纬度<input aria-label={`${which === "start" ? "起点" : "终点"}纬度`} value={edit[which].lat}
              onChange={(event) => update(edit.connection(which, { ...edit[which], lat: event.target.value }))} /></label>
          </div>
        </section>)}
        <section className="routing-constraints">
          <strong>工程约束</strong>
          <div className="routing-pair">
            {(Object.keys(ROUTING_FIELD_LABELS) as RoutingFields[]).map((name) => <label key={name}>{ROUTING_FIELD_LABELS[name]}
              <input aria-label={ROUTING_FIELD_LABELS[name]} value={edit.values[name]} onChange={(event) => update(edit.copy({ values: { ...edit.values, [name]: event.target.value } }))} />
            </label>)}
          </div>
          <p className="hud-note">道路控制距离同时影响塔基避让与跨越长度。</p>
        </section>
        <div className="routing-adjust">
          <div className="hud-actions"><button type="button" aria-pressed={pick === "adjust-endpoints"} onClick={() => beginPick("adjust-endpoints")}>调整起终点</button></div>
          {pick && <p role="status">{pick === "start" || pick === "end" ? "请在地图范围内点选接入点，光标旁显示当前位置。"
            : pick === "adjust-endpoints" ? "拖动地图上的起点或终点，松开后更新坐标。"
            : pick.endsWith("-box") ? (draft.length ? "请单击对角点完成方框。" : "请单击方框第一个角点。")
            : "按住鼠标画圈，松开后自动闭合。"}</p>}
          {pick && <button type="button" onClick={() => { beginPick(null); }}>取消点选</button>}
          {edit.regions.map((region, index) => <div key={index} className="routing-region-row">
            <span>{region.kind === "no_cross" ? "禁跨越" : "禁落塔"}区域 {index + 1}</span>
            <button type="button" onClick={() => removeRegion(index)}>删除</button>
          </div>)}
        </div>
        <RoutingAlgorithmControls edit={edit} update={update} budget={routingBudget(edit)} />
      </fieldset>
      <div className="routing-actions">
        <button type="button" className="primary" onClick={() => void start()} disabled={busy || !scene?.ready || scene?.read_only === true || landuseBlocked}>开始选线</button>
        {busy && jobId && <button type="button" disabled={job?.status === "cancelling"} onClick={cancel}>
          {job?.status === "cancelling" ? "等待取消完成…" : "取消选线"}</button>}
      </div>
      {children}
      {(landuseBlocked || job || error || notice) && <section className="routing-status">
        {landuseBlocked && <p className="hud-note">保存或放弃土地类型修改后，才能开始选线。</p>}
        {job && <>
          <p role="status">{JOB_STATUS_LABEL[job.status]} · {Math.round(job.progress * 100)}%</p>
          <div className="build-progress" aria-hidden="true"><span style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
          {routingJobDetail(job, error) && <p className="hud-note">{routingJobDetail(job, error)}</p>}
        </>}
        {error && <p className="error" role="alert">{error}</p>}
        {notice && <p className="hud-note">{notice}</p>}
      </section>}
      </div>}
      {minimized && children}
    </aside>;
}

function routingBudget(edit: RoutingEdit): string | undefined {
  const popsize = edit.algorithm.popsize;
  if (edit.generationLimit === null || popsize === "" || popsize == null) return undefined;
  return `${edit.generationLimit} 代 · ${String(popsize)} 候选/代`;
}

function routingJobDetail(job: { status: string; message: string }, error: string | null): string {
  if (!job.message || job.message === error || (job.status === "succeeded" && job.message === "Job completed")) return "";
  return job.message;
}
