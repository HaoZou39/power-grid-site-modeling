/** Published land-use patches versus the unsaved draft. This module does not call the network. */

export const LANDUSE_PREVIEW_NOTE = "土地类型修改预览，实际栅格将在保存后更新。";
export const LANDUSE_DRAFT_NOTICE = "土地类型存在未保存修改，当前方案仍基于已发布场景。";
export const LANDUSE_SAVE_FIRST = "请先保存土地类型修改。";
export const LANDUSE_CONFLICT = "场景版本已变化，未保存的土地类型修改仍保留。请重新加载已发布图斑，或放弃这些修改。";
export const LANDUSE_REFRESH_WARNING = "刷新或关闭页面会丢失未保存的土地类型修改。";

const ID_PATTERN = /^[0-9A-Za-z_-]{1,64}$/;
const CLASSES = new Set([1, 2, 3, 5]);

export type LanduseClassId = 1 | 2 | 3 | 5;

export type LanduseDraftItem = {
  id: string;
  class_id: LanduseClassId;
  points: [number, number][];
};

export type LandusePreviewStatus = "added" | "modified" | "removed";

export type LandusePreviewMark = LanduseDraftItem & { status: LandusePreviewStatus };

export type LanduseSaveRequest = {
  sceneId: string;
  expected_scene_revision: string;
  items: LanduseDraftItem[];
};

export type LanduseDraftState = {
  sceneId: string | null;
  publishedItems: LanduseDraftItem[];
  draftItems: LanduseDraftItem[];
  baseRevision: string | null;
  dirty: boolean;
  saving: boolean;
  conflict: boolean;
  error: string | null;
  undo: LanduseDraftItem[][];
  redo: LanduseDraftItem[][];
  loadToken: number;
};

export function emptyLanduseDraft(): LanduseDraftState {
  return {
    sceneId: null,
    publishedItems: [],
    draftItems: [],
    baseRevision: null,
    dirty: false,
    saving: false,
    conflict: false,
    error: null,
    undo: [],
    redo: [],
    loadToken: 0,
  };
}

function randomLanduseId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function newLanduseEditId(
  existing: readonly { id: string }[],
  random: () => string = randomLanduseId,
): string {
  const used = new Set(existing.map((item) => item.id));
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const id = random().replace(/[^0-9A-Za-z_-]/g, "").slice(0, 64);
    if (ID_PATTERN.test(id) && !used.has(id)) return id;
  }
  throw new Error("无法生成不重复的图斑编号。");
}

export function sameLanduseItems(left: readonly LanduseDraftItem[], right: readonly LanduseDraftItem[]): boolean {
  if (left.length !== right.length) return false;
  return left.every((item, index) => sameLanduseItem(item, right[index]));
}

export function landusePreviewMarks(
  published: readonly LanduseDraftItem[],
  draft: readonly LanduseDraftItem[],
): LandusePreviewMark[] {
  const publishedById = new Map(published.map((item) => [item.id, item]));
  const draftIds = new Set(draft.map((item) => item.id));
  const reordered = reorderedIds(published, draft);
  const marks: LandusePreviewMark[] = [];
  for (const item of draft) {
    const previous = publishedById.get(item.id);
    if (!previous) {
      marks.push({ ...cloneItem(item), status: "added" });
      continue;
    }
    if (!sameLanduseItem(previous, item) || reordered.has(item.id)) {
      marks.push({ ...cloneItem(item), status: "modified" });
    }
  }
  for (const item of published) {
    if (!draftIds.has(item.id)) marks.push({ ...cloneItem(item), status: "removed" });
  }
  return marks;
}

export function landuseSaveEnabled(state: LanduseDraftState): boolean {
  return state.dirty && !state.saving && !state.conflict && state.baseRevision !== null && state.sceneId !== null;
}

/** Draft edits must not start optimization, reevaluation, pose scoring, or a site report. */
export function landuseComputeBlocked(state: LanduseDraftState): string | null {
  if (state.conflict) return LANDUSE_CONFLICT;
  if (state.dirty || state.saving) return LANDUSE_SAVE_FIRST;
  return null;
}

export function noteLanduseScene(state: LanduseDraftState, sceneId: string): LanduseDraftState {
  if (state.sceneId === sceneId) return state;
  if (state.dirty || state.saving || state.conflict) return state;
  return bindLanduseScene(state, sceneId);
}

export function landuseSceneSwitch(
  state: LanduseDraftState,
  nextSceneId: string,
  reload = false,
): { allowed: true; state: LanduseDraftState } | { allowed: false; state: LanduseDraftState } {
  if (state.saving) return { allowed: false, state };
  const same = state.sceneId === nextSceneId;
  if ((state.dirty || state.conflict) && (!same || reload)) return { allowed: false, state };
  if (same && !reload) return { allowed: true, state };
  return { allowed: true, state: bindLanduseScene(state, nextSceneId) };
}

export function acceptPublishedLanduse(
  state: LanduseDraftState,
  input: { sceneId: string; items: readonly LanduseDraftItem[]; sceneRevision: string; token: number },
): LanduseDraftState {
  if (input.token !== state.loadToken || state.sceneId !== input.sceneId) return state;
  if (state.dirty || state.saving || state.conflict) return state;
  if (!input.sceneRevision) {
    return { ...state, error: "当前服务没有返回场景版本，不能保存土地类型。" };
  }
  const items = input.items.map(cloneItem);
  if (
    state.baseRevision === input.sceneRevision
    && sameLanduseItems(state.publishedItems, items)
    && sameLanduseItems(state.draftItems, items)
  ) return state;
  return {
    ...state,
    publishedItems: items,
    draftItems: items.map(cloneItem),
    baseRevision: input.sceneRevision,
    dirty: false,
    error: null,
    undo: [],
    redo: [],
  };
}

export function addLanduseDraft(state: LanduseDraftState, item: LanduseDraftItem): LanduseDraftState {
  if (!canEdit(state) || !validItem(item) || state.draftItems.some((current) => current.id === item.id)) return state;
  return pushDraft(state, [...state.draftItems, cloneItem(item)]);
}

export function removeLanduseDraft(state: LanduseDraftState, id: string): LanduseDraftState {
  if (!canEdit(state) || !state.draftItems.some((item) => item.id === id)) return state;
  return pushDraft(state, state.draftItems.filter((item) => item.id !== id));
}

export function updateLanduseDraft(
  state: LanduseDraftState,
  id: string,
  patch: { class_id?: LanduseClassId; points?: [number, number][] },
): LanduseDraftState {
  const index = state.draftItems.findIndex((item) => item.id === id);
  if (!canEdit(state) || index < 0) return state;
  const current = state.draftItems[index];
  const next = cloneItem({
    id: current.id,
    class_id: patch.class_id ?? current.class_id,
    points: patch.points ?? current.points,
  });
  if (!validItem(next) || sameLanduseItem(current, next)) return state;
  const draft = state.draftItems.map((item) => item.id === id ? next : item);
  return pushDraft(state, draft);
}

export function undoLanduseDraft(state: LanduseDraftState): LanduseDraftState {
  if (!canEdit(state) || state.undo.length === 0) return state;
  const previous = state.undo[state.undo.length - 1];
  return {
    ...state,
    draftItems: previous.map(cloneItem),
    dirty: !sameLanduseItems(state.publishedItems, previous),
    undo: state.undo.slice(0, -1),
    redo: [...state.redo, state.draftItems.map(cloneItem)],
    error: null,
  };
}

export function redoLanduseDraft(state: LanduseDraftState): LanduseDraftState {
  if (!canEdit(state) || state.redo.length === 0) return state;
  const next = state.redo[state.redo.length - 1];
  return {
    ...state,
    draftItems: next.map(cloneItem),
    dirty: !sameLanduseItems(state.publishedItems, next),
    redo: state.redo.slice(0, -1),
    undo: [...state.undo, state.draftItems.map(cloneItem)],
    error: null,
  };
}

export function discardLanduseDraft(state: LanduseDraftState): LanduseDraftState {
  if (state.saving) return state;
  return {
    ...state,
    draftItems: state.publishedItems.map(cloneItem),
    dirty: false,
    conflict: false,
    error: null,
    undo: [],
    redo: [],
  };
}

/** Leaving the drawing tool keeps the draft and does not publish it. */
export function retainLanduseDraft(state: LanduseDraftState): LanduseDraftState {
  return state;
}

export function beginLanduseSave(
  state: LanduseDraftState,
): { state: LanduseDraftState; request: LanduseSaveRequest | null } {
  if (!landuseSaveEnabled(state) || state.sceneId === null || state.baseRevision === null) {
    return { state, request: null };
  }
  return {
    state: { ...state, saving: true, error: null },
    request: {
      sceneId: state.sceneId,
      expected_scene_revision: state.baseRevision,
      items: state.draftItems.map(cloneItem),
    },
  };
}

export function completeLanduseSave(
  state: LanduseDraftState,
  response: { items: readonly LanduseDraftItem[]; scene_revision: string; changed: boolean },
): LanduseDraftState {
  if (!state.saving) return state;
  const items = response.items.map(cloneItem);
  return {
    ...state,
    publishedItems: items,
    draftItems: items.map(cloneItem),
    baseRevision: response.scene_revision,
    dirty: false,
    saving: false,
    conflict: false,
    error: null,
    undo: [],
    redo: [],
    loadToken: state.loadToken + 1,
  };
}

export function failLanduseSave(state: LanduseDraftState, message: string): LanduseDraftState {
  if (!state.saving) return state;
  return { ...state, saving: false, error: message };
}

export function conflictLanduseSave(state: LanduseDraftState): LanduseDraftState {
  if (!state.saving) return state;
  return { ...state, saving: false, conflict: true, error: LANDUSE_CONFLICT };
}

/** Explicit recovery after a conflict. It replaces the draft and must not be called from a 409 handler. */
export function reloadPublishedLanduse(
  state: LanduseDraftState,
  items: readonly LanduseDraftItem[],
  sceneRevision: string,
): LanduseDraftState {
  if (state.saving || !sceneRevision) return state;
  const published = items.map(cloneItem);
  return {
    ...state,
    publishedItems: published,
    draftItems: published.map(cloneItem),
    baseRevision: sceneRevision,
    dirty: false,
    conflict: false,
    error: null,
    undo: [],
    redo: [],
    loadToken: state.loadToken + 1,
  };
}

function bindLanduseScene(state: LanduseDraftState, sceneId: string): LanduseDraftState {
  return { ...emptyLanduseDraft(), sceneId, loadToken: state.loadToken + 1 };
}

function canEdit(state: LanduseDraftState): boolean {
  return !state.saving && !state.conflict && state.sceneId !== null;
}

function pushDraft(state: LanduseDraftState, draftItems: LanduseDraftItem[]): LanduseDraftState {
  return {
    ...state,
    draftItems,
    dirty: !sameLanduseItems(state.publishedItems, draftItems),
    error: null,
    undo: [...state.undo, state.draftItems.map(cloneItem)].slice(-50),
    redo: [],
  };
}

function validItem(item: LanduseDraftItem): boolean {
  return ID_PATTERN.test(item.id) && CLASSES.has(item.class_id) && validRing(item.points);
}

function validRing(points: readonly [number, number][]): boolean {
  return points.length >= 3 && points.every((point) => Number.isFinite(point[0]) && Number.isFinite(point[1]));
}

function sameLanduseItem(left: LanduseDraftItem | undefined, right: LanduseDraftItem | undefined): boolean {
  if (!left || !right) return false;
  return left.id === right.id && left.class_id === right.class_id && samePoints(left.points, right.points);
}

function samePoints(left: readonly [number, number][], right: readonly [number, number][]): boolean {
  return left.length === right.length && left.every((point, index) => point[0] === right[index][0] && point[1] === right[index][1]);
}

function reorderedIds(published: readonly LanduseDraftItem[], draft: readonly LanduseDraftItem[]): Set<string> {
  const draftIds = new Set(draft.map((item) => item.id));
  const publishedIds = new Set(published.map((item) => item.id));
  const publishedOrder = published.map((item) => item.id).filter((id) => draftIds.has(id));
  const draftOrder = draft.map((item) => item.id).filter((id) => publishedIds.has(id));
  const changed = new Set<string>();
  draftOrder.forEach((id, index) => {
    if (id !== publishedOrder[index]) {
      changed.add(id);
      changed.add(publishedOrder[index]);
    }
  });
  return changed;
}

function cloneItem(item: LanduseDraftItem): LanduseDraftItem {
  return { id: item.id, class_id: item.class_id, points: item.points.map((point) => [point[0], point[1]]) };
}
