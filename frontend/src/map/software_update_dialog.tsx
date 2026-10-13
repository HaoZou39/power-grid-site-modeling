import { useEffect, useRef, useState } from "react";
import { getSoftwareUpdate, postSoftwareUpdate } from "../api";
import type { SoftwareUpdateStatus } from "../api";
import { canSubmitUpdate, reduceUpdatePoll } from "./software_update";
import type { UpdateWait } from "./software_update";

export function useSoftwareUpdate(notify: (message: string) => void) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [configured, setConfigured] = useState(true);
  const [session, setSession] = useState<UpdateWait | null>(null);

  useEffect(() => {
    if (!open) return;
    let stop = false;
    getSoftwareUpdate()
      .then((status) => {
        if (stop) return;
        setConfigured(status.configured);
        if (!status.configured) setError("这台机器还没设置更新密码。");
      })
      .catch(() => undefined);
    return () => {
      stop = true;
    };
  }, [open]);

  const waitingId = session?.phase === "waiting" ? session.id : "";
  const notified = useRef("");
  useEffect(() => {
    if (!session || session.phase === "waiting") return;
    const key = `${session.id}:${session.phase}`;
    if (notified.current === key) return;
    notified.current = key;
    notify(session.message);
  }, [notify, session]);

  useEffect(() => {
    if (!waitingId) return;
    let stop = false;
    const tick = async () => {
      let poll: SoftwareUpdateStatus | null = null;
      try {
        poll = await getSoftwareUpdate();
      } catch {
        poll = null;
      }
      if (stop) return;
      setSession((current) => {
        if (!current || current.id !== waitingId || current.phase !== "waiting") return current;
        return reduceUpdatePoll(current, poll, Date.now());
      });
    };
    const timer = window.setInterval(() => void tick(), 2000);
    void tick();
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [waitingId]);

  async function submit() {
    if (!canSubmitUpdate(password)) {
      setError("请输入更新密码。");
      return;
    }
    setError("");
    try {
      const accepted = await postSoftwareUpdate(password);
      setPassword("");
      setSession({ id: accepted.id, phase: "waiting", message: accepted.message, startedAt: Date.now() });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "更新没有开始。");
    }
  }

  return {
    open,
    openDialog: () => {
      setError("");
      setOpen(true);
    },
    close: () => {
      if (session?.phase === "waiting") return;
      setOpen(false);
      setPassword("");
      setError("");
      setSession(null);
    },
    password,
    setPassword,
    error,
    configured,
    session,
    submit,
    busy: session?.phase === "waiting",
  };
}

export function SoftwareUpdateDialog({
  update,
}: {
  update: ReturnType<typeof useSoftwareUpdate>;
}) {
  if (!update.open && !update.session) return null;
  const waiting = update.session?.phase === "waiting";
  const finished = update.session !== null && update.session.phase !== "waiting";
  return (
    <section className="update-dialog" role="dialog" aria-labelledby="software-update-title">
      <div className="scheme-card-head">
        <strong id="software-update-title">软件更新</strong>
        {waiting ? null : (
          <button type="button" className="drawer-close" onClick={update.close}>关闭</button>
        )}
      </div>
      <p className="hud-note">
        将快进拉取当前分支，并重新启动本机的页面和接口。内存中的任务会被清空，页面会断开大约一分钟。
      </p>
      {update.session ? <p className="hud-note">{update.session.message}</p> : null}
      {finished || waiting || !update.configured ? null : (
        <label>
          更新密码
          <input
            type="password"
            autoComplete="current-password"
            value={update.password}
            onChange={(event) => update.setPassword(event.target.value)}
          />
        </label>
      )}
      {update.error ? <p className="hud-note">{update.error}</p> : null}
      {update.session?.phase === "succeeded" || update.session?.phase === "rolled_back" ? (
        <button type="button" className="primary" onClick={() => window.location.reload()}>
          刷新页面
        </button>
      ) : null}
      {finished || waiting ? null : (
        <button
          type="button"
          className="primary"
          disabled={!update.configured || !canSubmitUpdate(update.password)}
          onClick={() => void update.submit()}
        >
          开始更新
        </button>
      )}
    </section>
  );
}
