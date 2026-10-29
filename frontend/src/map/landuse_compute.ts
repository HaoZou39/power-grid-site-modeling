/** Order land-use publish ahead of scoring or a search. This module does not call the network. */

import type { PoseFreshness } from "./pose_evaluation.js";
import { isAwaitingReview } from "./pose_evaluation.js";

export type LandusePublishOutcome =
  | { status: "unchanged"; sceneRevision: string }
  | { status: "published"; sceneRevision: string }
  | { status: "conflict" }
  | { status: "failed"; message: string }
  | { status: "cancelled" };

export type ComputeAction = "重新评价" | "优化";

export function publishBlocksCompute(outcome: LandusePublishOutcome): boolean {
  return outcome.status === "conflict" || outcome.status === "failed" || outcome.status === "cancelled";
}

export function revisionReady(outcome: LandusePublishOutcome, actual: string | undefined): boolean {
  if (outcome.status === "published") return actual === outcome.sceneRevision;
  return outcome.status === "unchanged";
}

export function computeStoppedNotice(action: ComputeAction, outcome: LandusePublishOutcome): string | null {
  if (outcome.status === "conflict") return `场景版本冲突，未开始${action}。土地类型修改仍保留。`;
  if (outcome.status === "failed") return `土地类型保存失败，未开始${action}。${outcome.message}`;
  return null;
}

export function computeFailedAfterSave(action: ComputeAction): string {
  return action === "重新评价"
    ? "土地类型已保存，但重新评价失败。"
    : "土地类型已保存，但优化任务没有启动。";
}

export const PARETO_LAYER_NOTE = "以上层级来自上次优化，土地类型更新后尚未重新分层。";

/** A selected scheme that is still awaiting review must not open a site report. */
export function siteReportAllowed(blocked: boolean, freshness: PoseFreshness): boolean {
  return !blocked && !isAwaitingReview(freshness);
}

export async function afterLandusePublish<T>(input: {
  publish: () => Promise<LandusePublishOutcome>;
  sceneRevision: () => string | undefined;
  run: () => Promise<T>;
}): Promise<{ outcome: LandusePublishOutcome; ran: boolean; value?: T }> {
  const outcome = await input.publish();
  if (publishBlocksCompute(outcome)) return { outcome, ran: false };
  if (!revisionReady(outcome, input.sceneRevision())) {
    return { outcome: { status: "failed", message: "场景版本尚未同步，未开始计算。" }, ran: false };
  }
  const value = await input.run();
  return { outcome, ran: true, value };
}

export function createActionGate() {
  let held: "review" | "optimize" | "save" | null = null;
  return {
    held: () => held,
    async run<T>(kind: "review" | "optimize" | "save", work: () => Promise<T>): Promise<{ skipped: true } | { skipped: false; value: T }> {
      if (held) return { skipped: true };
      held = kind;
      try {
        return { skipped: false, value: await work() };
      } finally {
        held = null;
      }
    },
  };
}
