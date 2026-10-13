export type UpdateResult = "succeeded" | "rolled_back" | "failed";

export type UpdateStatus = {
  id: string;
  updating: boolean;
  result: UpdateResult | null;
  message: string;
  commit: string;
};

export type UpdateWait = {
  id: string;
  phase: "waiting" | UpdateResult;
  message: string;
  startedAt: number;
};

/** The script writes this run's id within a second of starting; past this, it never started. */
export const UPDATE_START_TIMEOUT_MS = 60_000;

export function canSubmitUpdate(password: string): boolean {
  return password.length > 0;
}

/** Ignore a status file from an older run. A dropped connection stays on waiting. */
export function reduceUpdatePoll(wait: UpdateWait, poll: UpdateStatus | null, now: number): UpdateWait {
  if (poll === null) {
    return { ...wait, phase: "waiting", message: "正在重启，页面会短暂断开。" };
  }
  if (poll.id !== wait.id) {
    if (!poll.updating && now - wait.startedAt > UPDATE_START_TIMEOUT_MS) {
      return { ...wait, phase: "failed", message: "更新没有开始。原因见 outputs/dev-servers/update.log。" };
    }
    return { ...wait, phase: "waiting", message: wait.message || "正在更新。" };
  }
  if (poll.updating || poll.result === null) {
    return { ...wait, phase: "waiting", message: poll.message || "正在更新。" };
  }
  return { ...wait, phase: poll.result, message: poll.message };
}
