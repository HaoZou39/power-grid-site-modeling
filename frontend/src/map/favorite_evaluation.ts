import type { SiteReport } from "./site_report_types.js";
import type { PoseObjectives } from "./decision_run.js";
import type { FavoritePointRecord } from "./favorite_points.js";
import { favoritePointPose } from "./favorite_points.js";
import type { SearchConfig } from "./site_edit.js";
import type { SiteFrame } from "./site_frame.js";

export type FavoriteEvaluation = {
  objectives?: PoseObjectives;
  report?: SiteReport;
  error?: string;
  reportError?: string;
};

export function favoriteEvaluationRequests(favorite: FavoritePointRecord, frame: SiteFrame, config: SearchConfig) {
  const pose = favoritePointPose(favorite, frame);
  const { scene_name: _scene, include_demand, ...settings } = config;
  const report = {
    ...settings, rect_w_m: favorite.width_m, rect_h_m: favorite.height_m,
    x: pose.center.x, y: pose.center.y, theta: pose.theta,
  };
  const { x, y, theta, ...constraints } = report;
  return { report, objectives: { ...constraints, include_demand, poses: [{ x, y, theta }] } };
}

export async function evaluateFavorite(
  sceneId: string,
  requests: ReturnType<typeof favoriteEvaluationRequests>,
  signal: AbortSignal,
  publish: (result: FavoriteEvaluation) => void,
  api: {
    objectives: (scene: string, body: ReturnType<typeof favoriteEvaluationRequests>["objectives"], signal: AbortSignal) => Promise<{ items: PoseObjectives[] }>;
    report: (scene: string, body: ReturnType<typeof favoriteEvaluationRequests>["report"], signal: AbortSignal) => Promise<SiteReport>;
  },
): Promise<void> {
  try {
    const result = await api.objectives(sceneId, requests.objectives, signal);
    if (signal.aborted) return;
    const objectives = result.items[0];
    if (result.items.length !== 1 || !objectives) throw new Error("单点评价未返回一个站址的结果。");
    publish({ objectives });
    try {
      const report = await api.report(sceneId, requests.report, signal);
      if (!signal.aborted) publish({ objectives, report });
    } catch (reason) {
      if (!signal.aborted) publish({ objectives, reportError: errorText(reason) });
    }
  } catch (reason) {
    if (!signal.aborted) publish({ error: errorText(reason) });
  }
}

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : "请求失败。";
}
