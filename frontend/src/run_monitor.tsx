import { useEffect, useState } from "react";
import { getJob } from "./api";
import type { JobRecord } from "./api";
import {
  JOB_STATUS_LABEL,
  configSummary,
  failurePresentation,
  isConfigOnlyResult,
  submittedExperimentId,
  messageLabel,
  progressRatio,
  runExperimentName,
  shouldPoll,
  stageLabel,
} from "./run_status";

const POLL_INTERVAL_MS = 1000;

/**
 * The only job poller. The timer follows job id, so a status update does not
 * open a second request loop. Cancellation stays absent until the backend has one.
 */
export function RunMonitor({
  jobId,
  config,
  pluginName,
  onReturnToConfig,
  onRerun,
}: {
  jobId: string | null;
  config: Record<string, unknown> | null;
  pluginName: string;
  onReturnToConfig: () => void;
  onRerun: () => void;
}) {
  const [job, setJob] = useState<JobRecord | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    setJob(null);
    setPollError(null);
    let timer = 0;
    const poll = () => {
      getJob(jobId)
        .then((record) => {
          if (cancelled) return;
          setJob(record);
          setPollError(null);
          if (!shouldPoll(record.status)) window.clearInterval(timer);
        })
        .catch((reason: unknown) => {
          if (cancelled) return;
          setPollError(reason instanceof Error && reason.message ? reason.message : "无法读取任务状态");
        });
    };
    poll();
    timer = window.setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [jobId]);

  return (
    <article className="card run-monitor" aria-labelledby="run-monitor-title">
      <p className="eyebrow">步骤 3</p>
      <h2 id="run-monitor-title">运行状态</h2>
      {!jobId || !config ? <p className="muted">提交任务后在这里查看状态。</p> : (
        <RunStatusBody
          job={job}
          config={config}
          pluginName={pluginName}
          pollError={pollError}
          onReturnToConfig={onReturnToConfig}
          onRerun={onRerun}
        />
      )}
    </article>
  );
}

function RunStatusBody({
  job,
  config,
  pluginName,
  pollError,
  onReturnToConfig,
  onRerun,
}: {
  job: JobRecord | null;
  config: Record<string, unknown>;
  pluginName: string;
  pollError: string | null;
  onReturnToConfig: () => void;
  onRerun: () => void;
}) {
  const status = job?.status ?? "queued";
  const ratio = progressRatio(job?.progress ?? 0);
  const failure = status === "failed" && job ? failurePresentation({ message: job.message, error: job.error }) : null;
  const summary = configSummary(config);
  const busy = job ? shouldPoll(job.status) : true;

  return (
    <div>
      <p className={`status-pill ${status}`}>{JOB_STATUS_LABEL[status]}</p>
      <dl className="problem-facts">
        <div>
          <dt>实验名称</dt>
          <dd>{runExperimentName(config)}</dd>
        </div>
        <div>
          <dt>算法</dt>
          <dd>{pluginName || "未提供"}</dd>
        </div>
        <div>
          <dt>任务编号</dt>
          <dd className="job-id">{job?.job_id ?? "未提供"}</dd>
        </div>
        <div>
          <dt>当前阶段</dt>
          <dd>{job ? stageLabel(job.stage) : "排队中"}</dd>
        </div>
      </dl>
      <div className={`progress ${status}`} aria-hidden="true"><span style={{ width: `${ratio * 100}%` }} /></div>
      <p className="muted">{job ? messageLabel(job.message) : "正在读取任务状态…"}</p>
      {job?.status === "succeeded" && submittedExperimentId(job.result) && (
        <p className="muted">实验结果目录：{submittedExperimentId(job.result)}。可在「实验结果」中查看。</p>
      )}
      {job?.status === "succeeded" && isConfigOnlyResult(job.result) && (
        <p className="muted">配置已保存。此任务没有运行优化器，也没有产生新的选址方案。</p>
      )}
      {pollError && <p className="error">无法刷新状态：{pollError}</p>}
      {failure && <p className="error">失败原因：{failure.summary}</p>}
      <h3>配置摘要</h3>
      {summary.length === 0 ? <p className="muted">这次运行没有配置项。</p> : (
        <ul className="config-summary">
          {summary.map((line) => <li key={line.label}><span>{line.label}</span><strong>{line.value}</strong></li>)}
        </ul>
      )}
      {failure?.technical && (
        <details>
          <summary>技术详情</summary>
          <pre>{failure.technical}</pre>
        </details>
      )}
      <div className="run-actions">
        <button type="button" onClick={onReturnToConfig}>返回配置</button>
        <button type="button" onClick={onRerun} disabled={busy}>重新运行</button>
      </div>
    </div>
  );
}
