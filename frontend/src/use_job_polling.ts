import { useEffect, useState } from "react";
import { ApiRequestError, getJob } from "./api";
import type { JobRecord } from "./api";
import { shouldPoll } from "./run_status";

/** Sequential polling, shared by task pages and the routing workspace. */
export function useJobPolling(jobId: string | null) {
  const [job, setJob] = useState<JobRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missingJobId, setMissingJobId] = useState<string | null>(null);
  useEffect(() => {
    setJob(null); setError(null); setMissingJobId(null);
    if (!jobId) return;
    let cancelled = false;
    let timer = 0;
    async function poll() {
      let again = true;
      try {
        const record = await getJob(jobId!);
        if (cancelled) return;
        setJob(record); setError(null); again = shouldPoll(record.status);
      } catch (reason) {
        if (cancelled) return;
        setError(reason instanceof Error ? reason.message : "无法读取任务状态");
        if (reason instanceof ApiRequestError && reason.status === 404) { setMissingJobId(jobId); again = false; }
      }
      if (!cancelled && again) timer = window.setTimeout(poll, 1000);
    }
    void poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [jobId]);
  return { job: job?.job_id === jobId ? job : null, error, missing: !!jobId && missingJobId === jobId };
}
