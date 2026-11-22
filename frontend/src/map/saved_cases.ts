export type SavedCaseSummary = {
  problem_type?: unknown;
  scene_name?: unknown;
};

export type CaseSearchField = "name" | "date" | "feasible";

export function savedCaseDateLabel(value: string | undefined): string {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "时间未记录";
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function searchSavedCases<T extends { name: string; modified_at?: string; summary: Record<string, unknown> }>(
  records: readonly T[], field: CaseSearchField, query: string,
): T[] {
  const text = query.trim().toLocaleLowerCase();
  if (!text) return [...records];
  return records.filter((item) => {
    if (field === "name") return item.name.toLocaleLowerCase().includes(text);
    if (field === "date") return savedCaseDateLabel(item.modified_at).startsWith(text);
    return /^\d+$/.test(text) && Number.isSafeInteger(Number(text)) && item.summary.n_feasible === Number(text);
  });
}

/** 案例归属只用保存下来的场景 id，空字符串和显示名都不算。 */
export function savedCaseSceneId(summary: SavedCaseSummary): string | null {
  return typeof summary.scene_name === "string" && summary.scene_name !== "" ? summary.scene_name : null;
}

export function visibleSavedCases<T extends { summary: SavedCaseSummary }>(
  records: readonly T[],
  mode: "site" | "routing",
  sceneId: string | undefined,
): T[] {
  if (typeof sceneId !== "string" || sceneId === "") return [];
  return records.filter((item) => {
    if (savedCaseSceneId(item.summary) !== sceneId) return false;
    const routing = item.summary.problem_type === "routing";
    return mode === "routing" ? routing : !routing;
  });
}

export function siteImportSceneError(
  historyScene: string | null,
  sceneId: string | undefined,
  sceneTitle: string | undefined,
  ownerTitle: string | undefined,
): string | null {
  if (!historyScene) return "这次历史结果没有记录 scene_name，不能安全导入当前地图。";
  if (historyScene !== sceneId) {
    return `这次历史结果属于${ownerTitle || historyScene}，不能导入${sceneTitle ?? "当前场景"}。`;
  }
  return null;
}

export function acceptCaseListResponse(
  requestToken: number,
  currentToken: number,
  requestSceneId: string | undefined,
  currentSceneId: string | undefined,
): boolean {
  return requestToken === currentToken
    && typeof requestSceneId === "string"
    && requestSceneId !== ""
    && requestSceneId === currentSceneId;
}
