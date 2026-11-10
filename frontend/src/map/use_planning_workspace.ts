import { useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  createPlanningWorkspace,
  createWorkspaceJob,
  deletePlanningWorkspace,
  getWorkspacePlan,
  getWorkspaceRevision,
  listPlanningWorkspaces,
  listWorkspaceRevisions,
  renamePlanningWorkspace,
  saveWorkspaceRoutingPlan,
  saveWorkspaceSitePlan,
} from "../api";
import type { JobRecord, PlanningWorkspace, WorkspaceRevisionDetail, WorkspaceRevisionSummary } from "../api";
import type { SitePlanningConfig } from "./site_plan";
import type { RoutingPlanningConfig } from "../routing/routing_plan";
import {
  acceptLoadedPlan,
  baseStatusNotice,
  bindCreatedWorkspace,
  clearWorkspaceSelection,
  conflictKind,
  planDirty,
  readWorkspaceSelection,
  revisionAfterSave,
  revisionPreview,
  RevisionChain,
  routingFormComplete,
  routingRunOptions,
  ROUTING_WORKSPACE_PLUGIN,
  siteRunOptions,
  SITE_WORKSPACE_PLUGIN,
  submissionBlock,
  switchChoice,
  visibleSelection,
  workspaceJobBody,
  workspacesForScene,
  writeWorkspaceSelection,
} from "./planning_workspace";
import type { BaseStatus } from "./planning_workspace";

type Bridge = {
  readSite: () => SitePlanningConfig;
  blankSite: () => SitePlanningConfig;
  applySite: (config: SitePlanningConfig) => void;
  readRouting: () => RoutingPlanningConfig;
  blankRouting: () => RoutingPlanningConfig;
  applyRouting: (config: RoutingPlanningConfig | null) => void;
  onDetached: () => void;
  strokeOpen: () => boolean;
  publicDirty: () => boolean;
};

export function usePlanningWorkspace(input: {
  accountId: string;
  sceneId: string | null;
  landusePending: boolean;
  bridge: { current: Bridge };
}) {
  const [items, setItems] = useState<PlanningWorkspace[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [revision, setRevision] = useState("");
  const [baseStatus, setBaseStatus] = useState<BaseStatus | null>(null);
  const [baseRevision, setBaseRevision] = useState<string | null>(null);
  const [baselineSite, setBaselineSite] = useState<SitePlanningConfig | null>(null);
  const [baselineRouting, setBaselineRouting] = useState<RoutingPlanningConfig | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState("");
  const [pending, setPending] = useState<{ workspaceId: string | null; canSave: boolean } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [history, setHistory] = useState<WorkspaceRevisionSummary[]>([]);
  const [historyView, setHistoryView] = useState<string | null>(null);
  const chain = useRef(new RevisionChain(""));
  const token = useRef(0);
  const accountRef = useRef(input.accountId);
  const sceneRef = useRef(input.sceneId);
  const selectedRef = useRef<string | null>(null);
  const busyRef = useRef(false);
  const seenAccount = useRef<string | null>(null);
  accountRef.current = input.accountId;
  sceneRef.current = input.sceneId;
  selectedRef.current = selectedId;

  function scope(workspaceId: string | null) {
    return { token: token.current, accountId: accountRef.current, sceneId: sceneRef.current ?? "", workspaceId };
  }

  function fail(reason: unknown): string {
    const message = reason instanceof Error ? reason.message : "请求失败";
    if (reason instanceof ApiRequestError && conflictKind(reason.status, reason.code)) {
      setConflict(reason.message || "工作区已被其他页面修改。可以重新加载，或取消这次操作。");
    }
    setError(message);
    return message;
  }

  function applyLoaded(workspaceId: string, plan: { workspace_revision: string; base_status: BaseStatus; site: SitePlanningConfig | null; routing: RoutingPlanningConfig | null }, detach: boolean) {
    const site = plan.site ?? input.bridge.current.blankSite();
    if (detach) input.bridge.current.onDetached();
    input.bridge.current.applySite(site);
    input.bridge.current.applyRouting(plan.routing);
    chain.current = new RevisionChain(plan.workspace_revision);
    setSelectedId(workspaceId);
    setRevision(plan.workspace_revision);
    setBaseStatus(plan.base_status);
    setBaselineSite(site);
    setBaselineRouting(plan.routing);
    setReady(true);
    setConflict("");
    setHistoryView(null);
  }

  async function loadWorkspace(workspaceId: string, issued: number, detach: boolean) {
    const accountId = accountRef.current;
    const sceneId = sceneRef.current;
    if (!sceneId) return;
    const plan = await getWorkspacePlan(workspaceId);
    const record = await getPlanningRecord(workspaceId);
    if (!acceptLoadedPlan(scope(workspaceId), { token: issued, accountId, sceneId, workspaceId })) return;
    if (plan.workspace_id !== workspaceId) return;
    writeWorkspaceSelection(sessionStorage, accountId, sceneId, workspaceId);
    setBaseRevision(record?.base_revision ?? null);
    applyLoaded(workspaceId, plan, detach);
  }

  async function getPlanningRecord(workspaceId: string): Promise<PlanningWorkspace | null> {
    const sceneId = sceneRef.current;
    if (!sceneId) return null;
    const listed = workspacesForScene(await listPlanningWorkspaces(sceneId), sceneId);
    setItems(listed);
    return listed.find((item) => item.workspace_id === workspaceId) ?? null;
  }

  useEffect(() => {
    const issued = ++token.current;
    const accountChanged = seenAccount.current !== null && seenAccount.current !== input.accountId;
    seenAccount.current = input.accountId;
    const accountId = input.accountId;
    const sceneId = input.sceneId;
    if (!sceneId) return;
    void (async () => {
      try {
        const listed = workspacesForScene(await listPlanningWorkspaces(sceneId), sceneId);
        if (token.current !== issued || accountRef.current !== accountId || sceneRef.current !== sceneId) return;
        setItems(listed);
        const raw = readWorkspaceSelection(sessionStorage, accountId, sceneId);
        const stored = visibleSelection(raw, listed.map((item) => item.workspace_id));
        if (!stored) {
          clearWorkspaceSelection(sessionStorage, accountId, sceneId);
          if (accountChanged || raw) {
            input.bridge.current.onDetached();
            input.bridge.current.applySite(input.bridge.current.blankSite());
            input.bridge.current.applyRouting(null);
          }
          setSelectedId(null);
          setRevision("");
          setBaseStatus(null);
          setBaseRevision(null);
          setReady(false);
          if (raw) setNotice("已保存的工作区不存在或已删除。");
          return;
        }
        await loadWorkspace(stored, issued, true);
      } catch (reason) {
        if (token.current !== issued) return;
        if (reason instanceof ApiRequestError && reason.status === 404) {
          clearWorkspaceSelection(sessionStorage, accountId, sceneId);
          setSelectedId(null);
          setNotice("已保存的工作区不存在或已删除。");
          return;
        }
        fail(reason);
      }
    })();
  }, [input.accountId, input.sceneId]);

  function isDirty(): boolean {
    if (!selectedId || !ready) return input.bridge.current.publicDirty();
    if (input.bridge.current.strokeOpen()) return true;
    try {
      const site = input.bridge.current.readSite();
      const routing = input.bridge.current.readRouting();
      const routingBaseline = baselineRouting ?? input.bridge.current.blankRouting();
      return planDirty(baselineSite, site) || planDirty(routingBaseline, routing);
    } catch {
      return true;
    }
  }

  function requestSelect(workspaceId: string | null) {
    const next = switchChoice(workspaceId === selectedId, isDirty());
    if (next === "stay") return;
    if (next === "prompt") {
      setPending({ workspaceId, canSave: selectedId !== null });
      return;
    }
    void commitSelect(workspaceId);
  }

  async function commitSelect(workspaceId: string | null) {
    const issued = ++token.current;
    const accountId = accountRef.current;
    const sceneId = sceneRef.current;
    setPending(null);
    setError("");
    if (!sceneId) return;
    if (!workspaceId) {
      clearWorkspaceSelection(sessionStorage, accountId, sceneId);
      if (!acceptLoadedPlan(scope(null), { token: issued, accountId, sceneId, workspaceId: null })) return;
      input.bridge.current.onDetached();
      const site = input.bridge.current.blankSite();
      input.bridge.current.applySite(site);
      input.bridge.current.applyRouting(null);
      setSelectedId(null);
      setRevision("");
      setBaseStatus(null);
      setBaseRevision(null);
      setBaselineSite(null);
      setBaselineRouting(null);
      setReady(false);
      setNotice("已返回公共场景。优化会读取当前公共场景。");
      return;
    }
    setBusy(true);
    busyRef.current = true;
    try {
      await loadWorkspace(workspaceId, issued, true);
    } catch (reason) {
      if (token.current !== issued) return;
      if (reason instanceof ApiRequestError && (reason.status === 404 || reason.status === 403)) {
        clearWorkspaceSelection(sessionStorage, accountId, sceneId);
        setSelectedId(null);
        setNotice(reason.status === 404 ? "工作区不存在或已删除。" : "没有权限读取这个工作区。");
        return;
      }
      fail(reason);
    } finally {
      if (token.current === issued) {
        busyRef.current = false;
        setBusy(false);
      }
    }
  }

  async function saveSide(kind: "site" | "routing") {
    const workspaceId = selectedRef.current;
    const sceneId = sceneRef.current;
    if (!workspaceId || !sceneId) throw new Error("请先选择个人工作区。");
    const status = baseStatus;
    if (status && baseStatusNotice(status)) throw new Error(baseStatusNotice(status) ?? "");
    return chain.current.enqueue(async (expected) => {
      if (selectedRef.current !== workspaceId || sceneRef.current !== sceneId) throw new Error("工作区已切换，这次保存已取消。");
      const saved = kind === "site"
        ? await saveWorkspaceSitePlan(workspaceId, { expected_workspace_revision: expected, site: input.bridge.current.readSite() })
        : await saveWorkspaceRoutingPlan(workspaceId, { expected_workspace_revision: expected, routing: input.bridge.current.readRouting() });
      if (selectedRef.current !== workspaceId) throw new Error("工作区已切换，这次保存已取消。");
      const next = revisionAfterSave(expected, saved);
      return { revision: next, value: { ...saved, workspace_revision: next } };
    });
  }

  async function persistDirty(): Promise<boolean> {
    if (!selectedRef.current) throw new Error("请先选择个人工作区。");
    if (input.bridge.current.strokeOpen()) throw new Error("未闭合草稿不能保存。请先闭合或取消绘制。");
    if (baseStatus && baseStatusNotice(baseStatus)) throw new Error(baseStatusNotice(baseStatus) ?? "");
    const site = input.bridge.current.readSite();
    const routing = input.bridge.current.readRouting();
    const routingBaseline = baselineRouting ?? input.bridge.current.blankRouting();
    let changed = false;
    if (planDirty(baselineSite, site)) {
      const saved = await saveSide("site");
      setBaselineSite(site);
      setRevision(saved.workspace_revision);
      changed = changed || saved.changed;
    }
    if (planDirty(routingBaseline, routing)) {
      const saved = await saveSide("routing");
      setBaselineRouting(routing);
      setRevision(saved.workspace_revision);
      changed = changed || saved.changed;
    }
    return changed;
  }

  async function saveDirty() {
    if (busyRef.current) throw new Error("正在处理上一次保存或提交。");
    setBusy(true);
    busyRef.current = true;
    setError("");
    try {
      const changed = await persistDirty();
      setNotice(changed ? "规划已保存。" : "没有新的修改。");
    } catch (reason) {
      fail(reason);
      throw reason;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function submit(kind: "site" | "routing", experimentName: string): Promise<JobRecord> {
    if (busyRef.current) throw new Error("正在处理上一次保存或提交。");
    const workspaceId = selectedRef.current;
    const complete = kind === "site" ? true : routingFormComplete(input.bridge.current.readRouting());
    const blocked = submissionBlock({
      selected: workspaceId !== null,
      baseStatus,
      landusePending: input.landusePending,
      complete,
    });
    if (blocked) throw new Error(blocked);
    if (!workspaceId) throw new Error("请先选择个人工作区。");
    setBusy(true);
    busyRef.current = true;
    setError("");
    try {
      await persistDirty();
      if (selectedRef.current !== workspaceId) throw new Error("工作区已切换，这次提交已取消。");
      const body = workspaceJobBody({
        pluginId: kind === "site" ? SITE_WORKSPACE_PLUGIN : ROUTING_WORKSPACE_PLUGIN,
        revision: chain.current.revision,
        experimentName,
        runOptions: kind === "site" ? siteRunOptions() : routingRunOptions(input.bridge.current.readRouting().algorithm_overrides),
      });
      return await createWorkspaceJob(workspaceId, body);
    } catch (reason) {
      fail(reason);
      throw reason;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function create(name: string) {
    const sceneId = sceneRef.current;
    const cleaned = name.trim();
    if (!sceneId) throw new Error("当前没有场景。");
    if (!cleaned || cleaned.length > 80) throw new Error("工作区名称需要 1 到 80 个字。");
    setBusy(true);
    try {
      const created = await createPlanningWorkspace({ base_scene_id: sceneId, display_name: cleaned });
      if (sceneRef.current !== sceneId) return;
      bindCreatedWorkspace(sessionStorage, accountRef.current, created);
      setItems((current) => [...current.filter((item) => item.workspace_id !== created.workspace_id), created]);
      await commitSelect(created.workspace_id);
    } catch (reason) {
      fail(reason);
    } finally {
      setBusy(false);
    }
  }

  async function rename(name: string) {
    const workspaceId = selectedRef.current;
    const cleaned = name.trim();
    if (!workspaceId) return;
    if (!cleaned || cleaned.length > 80) {
      setError("工作区名称需要 1 到 80 个字。");
      return;
    }
    try {
      const updated = await renamePlanningWorkspace(workspaceId, cleaned);
      if (selectedRef.current !== workspaceId) return;
      setItems((current) => current.map((item) => item.workspace_id === workspaceId ? updated : item));
      setNotice("工作区已改名。");
    } catch (reason) {
      fail(reason);
    }
  }

  async function remove() {
    const workspaceId = selectedRef.current;
    const sceneId = sceneRef.current;
    if (!workspaceId || !sceneId) return;
    try {
      await deletePlanningWorkspace(workspaceId);
      if (selectedRef.current !== workspaceId) return;
      clearWorkspaceSelection(sessionStorage, accountRef.current, sceneId);
      setItems((current) => current.filter((item) => item.workspace_id !== workspaceId));
      setConfirmDelete(false);
      await commitSelect(null);
      setNotice("工作区已删除。服务器上的任务不会被取消。");
    } catch (reason) {
      fail(reason);
    }
  }

  async function reload() {
    const workspaceId = selectedRef.current;
    if (!workspaceId) return;
    setConflict("");
    const issued = token.current;
    try {
      await loadWorkspace(workspaceId, issued, true);
      setNotice("已重新加载工作区。本地未保存修改已放弃。");
    } catch (reason) {
      fail(reason);
    }
  }

  async function showHistory() {
    const workspaceId = selectedRef.current;
    if (!workspaceId) return;
    try {
      const rows = await listWorkspaceRevisions(workspaceId);
      if (selectedRef.current !== workspaceId) return;
      setHistory(rows);
    } catch (reason) {
      fail(reason);
    }
  }

  async function viewRevision(revisionId: string) {
    const workspaceId = selectedRef.current;
    const editing = revision;
    if (!workspaceId) return;
    try {
      const detail: WorkspaceRevisionDetail = await getWorkspaceRevision(workspaceId, revisionId);
      if (selectedRef.current !== workspaceId || revision !== editing) return;
      setHistoryView(revisionPreview(detail));
    } catch (reason) {
      fail(reason);
    }
  }

  const selected = items.find((item) => item.workspace_id === selectedId) ?? null;

  return {
    items, selected, selectedId, revision, baseStatus, baseRevision, busy, error, notice, conflict,
    pending, confirmDelete, history, historyView, ready,
    isDirty, requestSelect, commitSelect, saveDirty, submitSite: (name: string) => submit("site", name),
    submitRouting: (name: string) => submit("routing", name), create, rename, remove, reload, showHistory, viewRevision,
    askDelete: () => setConfirmDelete(true), cancelDelete: () => setConfirmDelete(false),
    cancelSwitch: () => setPending(null), dismissConflict: () => setConflict(""), closeHistory: () => setHistoryView(null),
  };
}
