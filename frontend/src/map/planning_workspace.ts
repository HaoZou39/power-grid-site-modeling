/** Personal workspace selection, save conflicts, and job payloads. The map renders this; it does not read scenes. */

export const SITE_WORKSPACE_PLUGIN = "site.guided_search";
export const ROUTING_WORKSPACE_PLUGIN = "routing.nsga2";

const FORBIDDEN_JOB_FIELDS = [
  "owner_id",
  "base_snapshot_id",
  "base_revision",
  "base_frame_id",
  "planning_content_hash",
  "effective_config_hash",
  "snapshot_dir",
] as const;

const ROUTING_PLAN_FIELDS = ["start", "end", "no_tower_zones", "no_cross_zones"] as const;

export type BaseStatus = "current" | "changed" | "missing";
export type SubmitRoute = "legacy" | "workspace";
export type SwitchChoice = "stay" | "apply" | "prompt";

export type WorkspaceJobBody = {
  plugin_id: string;
  expected_workspace_revision: string;
  experiment_name: string;
  overwrite_existing: boolean;
  run_options: Record<string, unknown>;
};

export type PlanningScope = {
  token: number;
  accountId: string;
  sceneId: string;
  workspaceId: string | null;
};

export function workspaceSelectionKey(accountId: string, sceneId: string): string {
  return `planning-workspace:${accountId}:${sceneId}`;
}

export function readWorkspaceSelection(storage: Pick<Storage, "getItem">, accountId: string, sceneId: string): string | null {
  const value = storage.getItem(workspaceSelectionKey(accountId, sceneId));
  return value && value.trim() ? value : null;
}

export function writeWorkspaceSelection(storage: Pick<Storage, "setItem">, accountId: string, sceneId: string, workspaceId: string): void {
  storage.setItem(workspaceSelectionKey(accountId, sceneId), workspaceId);
}

export function clearWorkspaceSelection(storage: Pick<Storage, "removeItem">, accountId: string, sceneId: string): void {
  storage.removeItem(workspaceSelectionKey(accountId, sceneId));
}

export function bindCreatedWorkspace(
  storage: Pick<Storage, "setItem">,
  accountId: string,
  workspace: { workspace_id: string; base_scene_id: string },
): void {
  writeWorkspaceSelection(storage, accountId, workspace.base_scene_id, workspace.workspace_id);
}

export function workspacesForScene<T extends { base_scene_id: string }>(items: readonly T[], sceneId: string): T[] {
  return items.filter((item) => item.base_scene_id === sceneId);
}

export function visibleSelection(stored: string | null, workspaceIds: readonly string[]): string | null {
  return stored && workspaceIds.includes(stored) ? stored : null;
}

export function canonicalPlan(value: unknown): string {
  return JSON.stringify(value ?? null);
}

export function planDirty(saved: unknown, current: unknown): boolean {
  return canonicalPlan(saved) !== canonicalPlan(current);
}

export function switchChoice(sameWorkspace: boolean, dirty: boolean): SwitchChoice {
  if (sameWorkspace) return "stay";
  return dirty ? "prompt" : "apply";
}

export function acceptLoadedPlan(request: PlanningScope, current: PlanningScope): boolean {
  return request.token === current.token
    && request.accountId === current.accountId
    && request.sceneId === current.sceneId
    && request.workspaceId === current.workspaceId;
}

export function baseStatusNotice(status: BaseStatus): string | null {
  if (status === "current") return null;
  if (status === "changed") return "公共场景版本已变化，不能保存或提交。请新建工作区。";
  return "公共场景不可用，不能保存或提交。";
}

export function submissionBlock(input: {
  selected: boolean;
  baseStatus: BaseStatus | null;
  landusePending: boolean;
  complete: boolean;
}): string | null {
  if (!input.selected) return "请先选择个人工作区。";
  const base = input.baseStatus ? baseStatusNotice(input.baseStatus) : "工作区状态未知，不能提交。";
  if (base) return base;
  if (input.landusePending) return "请先保存或放弃公共土地分类草稿。个人工作区不会自动发布公共场景。";
  if (!input.complete) return "规划尚未填完，可以保存，但不能提交。";
  return null;
}

export function routingFormComplete(config: {
  start: { lng: string; lat: string };
  end: { lng: string; lat: string };
  max_span_m: string;
  tower_radius_m: string;
  max_turn_deg: string;
  road_setback_m: string;
  highway_setback_m: string;
}): boolean {
  const endpoints = [config.start.lng, config.start.lat, config.end.lng, config.end.lat];
  const numbers = [config.max_span_m, config.tower_radius_m, config.max_turn_deg, config.road_setback_m, config.highway_setback_m];
  return endpoints.every((value) => value.trim() !== "")
    && numbers.every((value) => value.trim() !== "" && Number.isFinite(Number(value)));
}

export function siteRunOptions(): Record<string, unknown> {
  return {};
}

export function routingRunOptions(algorithm: Record<string, unknown> | null | undefined): Record<string, unknown> {
  for (const key of ROUTING_PLAN_FIELDS) {
    if (algorithm && Object.prototype.hasOwnProperty.call(algorithm, key)) throw new Error(`选线运行参数不能包含${key}`);
  }
  if (!algorithm || Object.keys(algorithm).length === 0) return {};
  return { algorithm };
}

export function workspaceJobBody(input: {
  pluginId: string;
  revision: string;
  experimentName: string;
  runOptions?: Record<string, unknown>;
}): WorkspaceJobBody {
  const runOptions = input.runOptions ?? {};
  for (const key of FORBIDDEN_JOB_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(runOptions, key)) throw new Error(`不能提交 ${key}`);
  }
  return {
    plugin_id: input.pluginId,
    expected_workspace_revision: input.revision,
    experiment_name: input.experimentName,
    overwrite_existing: false,
    run_options: runOptions,
  };
}

export function submitRoute(workspaceId: string | null): SubmitRoute {
  return workspaceId ? "workspace" : "legacy";
}

export function submitEndpoint(route: SubmitRoute, workspaceId: string | null): string {
  if (route === "legacy") return "/api/v1/jobs";
  if (!workspaceId) throw new Error("个人工作区提交缺少工作区");
  return `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/jobs`;
}

export function revisionAfterSave(current: string, saved: { workspace_revision: string; changed: boolean }): string {
  if (!saved.changed && saved.workspace_revision !== current) throw new Error("未改内容时修订号不能变化");
  if (saved.changed && (!saved.workspace_revision || saved.workspace_revision === current)) {
    throw new Error("保存后没有拿到新的修订号");
  }
  return saved.workspace_revision;
}

export function conflictKind(status: number, code: string | null): "revision" | "base" | "other" | null {
  if (status !== 409) return null;
  if (code === "workspace_revision_conflict") return "revision";
  if (code === "workspace_base_changed" || code === "workspace_base_missing") return "base";
  return "other";
}

export function routingJobStorageKey(sceneId: string, workspaceId: string | null): string {
  return workspaceId ? `routing-job:${sceneId}:${workspaceId}` : `routing-job:${sceneId}`;
}

export function jobMatchesWorkspace(
  job: { job_id?: string; workspace_id?: string | null } | null,
  workspaceId: string | null,
  followedJobId: string | null,
): boolean {
  if (!job || !workspaceId || !followedJobId) return false;
  return job.job_id === followedJobId && job.workspace_id === workspaceId;
}

export function followCreatedJob(
  record: { job_id: string; workspace_id?: string | null },
  workspaceId: string,
): { jobId: string; workspaceId: string } {
  if (record.workspace_id !== workspaceId) throw new Error("任务不属于当前工作区");
  return { jobId: record.job_id, workspaceId };
}

export function shortId(value: string): string {
  return value.length > 8 ? value.slice(0, 8) : value;
}

export function resultBaseNotice(jobBaseRevision: string | null | undefined, liveBaseRevision: string | null | undefined): string | null {
  if (!jobBaseRevision || !liveBaseRevision || jobBaseRevision === liveBaseRevision) return null;
  return `这次结果基于历史基础版本 ${shortId(jobBaseRevision)}，不是当前公共场景的计算结果。`;
}

export function workspaceResultFrameBlock(jobFrame: string | null | undefined, liveFrame: string | null | undefined): string | null {
  if (!jobFrame || !liveFrame || jobFrame === liveFrame) return null;
  return "这次结果的网格与当前场景不一致，没有画到地图上。";
}

export function runProvenance(input: {
  job: { job_id: string; workspace_id?: string | null; workspace_revision?: string | null; base_revision?: string | null } | null;
  workspaceId: string | null;
  workspaceName: string;
  liveBaseRevision: string | null;
}): { workspace: string; revision: string; baseRevision: string; jobId: string; historical: string | null } | null {
  const job = input.job;
  if (!job || !input.workspaceId || job.workspace_id !== input.workspaceId) return null;
  return {
    workspace: input.workspaceName || input.workspaceId,
    revision: shortId(job.workspace_revision ?? ""),
    baseRevision: shortId(job.base_revision ?? ""),
    jobId: job.job_id,
    historical: resultBaseNotice(job.base_revision, input.liveBaseRevision),
  };
}

export function revisionPreview(detail: {
  revision_id: string;
  site: { exclusion_zones: readonly unknown[] } | null;
  routing: { start: { lng: string } } | null;
}): string {
  const site = detail.site ? `选址禁区 ${detail.site.exclusion_zones.length} 处` : "选址为空";
  const routing = detail.routing?.start.lng ? `选线起点 ${detail.routing.start.lng}` : "选线为空或不完整";
  return `${shortId(detail.revision_id)}：${site}；${routing}。这是历史查看，没有恢复成当前配置。`;
}

export function historyViewDoesNotRestore(viewedRevision: string, currentRevision: string): {
  viewing: string;
  editing: string;
  restored: false;
} {
  return { viewing: viewedRevision, editing: currentRevision, restored: false };
}

export class RevisionChain {
  revision: string;
  private tail: Promise<void> = Promise.resolve();

  constructor(revision: string) {
    this.revision = revision;
  }

  enqueue<T>(run: (revision: string) => Promise<{ revision: string; value: T }>): Promise<T> {
    const job = this.tail.then(async () => {
      const result = await run(this.revision);
      this.revision = result.revision;
      return result.value;
    });
    this.tail = job.then(() => undefined, () => undefined);
    return job;
  }
}
