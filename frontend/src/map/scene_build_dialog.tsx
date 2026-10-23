import { useEffect, useRef } from "react";
import type { JobRecord } from "../api";
import { JOB_STATUS_LABEL, failurePresentation, messageLabel, stageLabel } from "../run_status";
import { elapsedSeconds, sceneBuildExtentLines } from "./scene_build";

/** Coordinate scene form. Closing this dialog does not cancel a running build. */
export function SceneBuildDialog({
  open,
  lat,
  lon,
  side,
  name,
  onLat,
  onLon,
  onSide,
  onName,
  submitDisabled,
  formError,
  job,
  onClose,
  onSubmit,
  onRetry,
  onStop,
}: {
  open: boolean;
  lat: string;
  lon: string;
  side: string;
  name: string;
  onLat: (value: string) => void;
  onLon: (value: string) => void;
  onSide: (value: string) => void;
  onName: (value: string) => void;
  submitDisabled: boolean;
  formError: string;
  job: JobRecord | null;
  onClose: () => void;
  onSubmit: () => void;
  onRetry: () => void;
  onStop: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const latRef = useRef<HTMLInputElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const active = job !== null && (job.status === "queued" || job.status === "running");
  const extent = sceneBuildExtentLines(Number(side));

  useEffect(() => {
    if (!open) return;
    (active ? dialogRef.current : latRef.current)?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, active]);

  if (!open) return null;
  const failure = job?.status === "failed" ? failurePresentation({ message: job.message, error: job.error }).summary : "";
  const elapsed = job ? elapsedSeconds(job.created_at, job.updated_at) : null;
  return (
    <div className="scene-build-backdrop" onClick={onClose}>
      <section
        ref={dialogRef}
        className="scene-build-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="scene-build-title"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="scene-build-head">
          <div>
            <h2 id="scene-build-title">新建场景</h2>
            <p className="scene-build-subtitle">通过地理坐标生成站址基础数据</p>
          </div>
          <button type="button" className="drawer-close" aria-label="关闭" onClick={onClose}>关闭</button>
        </div>
        <form
          className="scene-build-body"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <div className="scene-build-pair">
            <label>纬度
              <input ref={latRef} value={lat} inputMode="decimal" placeholder="27.501662" disabled={submitDisabled} onChange={(event) => onLat(event.target.value)} />
            </label>
            <label>经度
              <input value={lon} inputMode="decimal" placeholder="120.194639" disabled={submitDisabled} onChange={(event) => onLon(event.target.value)} />
            </label>
          </div>
          <label>场景边长（m）
            <input value={side} inputMode="numeric" disabled={submitDisabled} onChange={(event) => onSide(event.target.value)} />
          </label>
          <label>场景名称（可选）
            <input value={name} placeholder="可以使用中文" disabled={submitDisabled} onChange={(event) => onName(event.target.value)} />
          </label>
          {extent && (
            <p className="hud-note scene-build-extent">{extent.grid}<br />{extent.resolution}<br />{extent.mercator}</p>
          )}
          {formError && <p className="scene-build-error" role="alert">{formError}</p>}
          {job && (
            <section className="origin-status" aria-label="场景构建状态">
              <strong>{JOB_STATUS_LABEL[job.status]} · {stageLabel(job.stage)}</strong>
              <div className="build-progress" aria-hidden="true">
                <span style={{ width: `${Math.round(Math.min(1, Math.max(0, job.progress)) * 100)}%` }} />
              </div>
              <p className="hud-note">任务 {job.job_id}</p>
              <p className="hud-note">{messageLabel(job.message)}</p>
              {elapsed !== null && <p className="hud-note">已用时 {elapsed} 秒</p>}
              {job.status === "succeeded" && <p className="hud-note">场景已构建。地图会切换到这个新场景。</p>}
              {job.status === "failed" && (
                <>
                  <p className="hud-note">{failure}</p>
                  <button type="button" onClick={onRetry} disabled={submitDisabled}>重试</button>
                </>
              )}
              {active && <button type="button" onClick={onStop}>终止构建</button>}
            </section>
          )}
          <div className="scene-build-actions">
            <button type="button" onClick={onClose}>取消</button>
            <button type="submit" className="primary" disabled={submitDisabled}>
              {active ? "正在构建…" : "构建场景"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
