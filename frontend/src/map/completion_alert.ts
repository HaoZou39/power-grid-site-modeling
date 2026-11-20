/** 优化结束提醒。安全来源且已允许通知时走系统通知，否则闪标签标题并响一声。 */

export type SearchKind = "search" | "refine";
export type SearchEnd = "succeeded" | "failed" | "cancelled";
export type AlertPermission = "granted" | "denied" | "default" | "unsupported";

const PENDING = "待查看 · ";
const BLINKS = 8;

const TITLE: Record<SearchKind, Record<SearchEnd, string>> = {
  search: { succeeded: "优化完成", failed: "优化失败", cancelled: "优化已取消" },
  refine: { succeeded: "局部优化完成", failed: "局部优化失败", cancelled: "局部优化已取消" },
};

export function optimizationReminder(kind: SearchKind, status: SearchEnd, detail: string): { title: string; body: string } {
  return { title: TITLE[kind][status], body: detail };
}

export type AlertHost = {
  readonly secure: boolean;
  readonly permission: AlertPermission;
  requestPermission(): Promise<NotificationPermission>;
  notify(title: string, body: string): void;
  title(): string;
  setTitle(value: string): void;
  arm(): void;
  beep(): void;
  schedule(fn: () => void, ms: number): number;
  cancel(id: number): void;
};

export class CompletionAlert {
  private sent = new Set<string>();
  private base: string | null = null;
  private timer: number | null = null;

  constructor(private readonly host: AlertHost) {}

  /** 必须在点击「开始优化」或确认搜索提案的同步阶段调用，任务结束时再问会被浏览器拦住。 */
  prime(): void {
    try { this.host.arm(); } catch { /* 音频不可用时仍可使用文字提醒。 */ }
    if (this.host.secure && this.host.permission === "default") {
      try { void this.host.requestPermission().catch(() => {}); } catch { /* 保留页面提醒。 */ }
    }
  }

  /** 同一个任务只提醒一次。 */
  finish(jobId: string, kind: SearchKind, status: SearchEnd, detail: string): boolean {
    if (this.sent.has(jobId)) return false;
    this.sent.add(jobId);
    const message = optimizationReminder(kind, status, detail);
    if (this.host.secure && this.host.permission === "granted") {
      try {
        this.host.notify(message.title, message.body);
        return true;
      } catch {
        // 浏览器拒绝弹出时改走标题和声音，避免这次结束没有任何提醒。
      }
    }
    this.blink(message.title);
    try { this.host.beep(); } catch { /* 不让浏览器音频错误改变计算结果。 */ }
    return true;
  }

  private rememberBase(): void {
    if (this.base !== null) return;
    const current = this.host.title();
    this.base = current.startsWith(PENDING) ? current.slice(PENDING.length) : current;
  }

  private blink(title: string): void {
    if (this.timer !== null) {
      this.host.cancel(this.timer);
      this.timer = null;
    }
    this.rememberBase();
    const pending = `${PENDING}${title}`;
    let on = false;
    const draw = () => {
      on = !on;
      this.host.setTitle(on ? pending : this.base ?? "");
    };
    draw();
    let left = BLINKS;
    const next = () => {
      left -= 1;
      if (left <= 0) {
        this.host.setTitle(this.base ?? "");
        this.timer = null;
        return;
      }
      draw();
      this.timer = this.host.schedule(next, 1000);
    };
    this.timer = this.host.schedule(next, 1000);
  }
}
