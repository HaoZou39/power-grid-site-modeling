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
  /** Set when a finished run reports its code version. */
  commit?: string;
  /** Recalled after the dev server reloaded the page, so the page already runs the new code. */
  reloaded?: boolean;
};

/** The script writes this run's id within a second of starting; past this, it never started. */
export const UPDATE_START_TIMEOUT_MS = 60_000;

/** The Vite client reloads the page when the dev server comes back, so the pending run is kept across that reload. */
const PENDING_KEY = "software-update-pending";

type KeyValue = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function rememberUpdate(storage: KeyValue, wait: UpdateWait): void {
  storage.setItem(PENDING_KEY, JSON.stringify({ id: wait.id, startedAt: wait.startedAt }));
}

export function recallUpdate(storage: KeyValue): UpdateWait | null {
  const text = storage.getItem(PENDING_KEY);
  if (!text) return null;
  const saved = JSON.parse(text) as { id: string; startedAt: number };
  return { id: saved.id, startedAt: saved.startedAt, phase: "waiting", message: "页面已重新载入，正在确认更新结果。", reloaded: true };
}

export function forgetUpdate(storage: KeyValue): void {
  storage.removeItem(PENDING_KEY);
}

export const UPDATE_RESULT_TITLE: Record<UpdateResult, string> = {
  succeeded: "更新完成",
  rolled_back: "更新失败，已退回原版本",
  failed: "更新失败",
};

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
  return { ...wait, phase: poll.result, message: poll.message, commit: poll.commit };
}
