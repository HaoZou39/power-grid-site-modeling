import type { FavoritePointInput, FavoritePointRecord } from "./favorite_points.js";
import { bearingToTheta, favoriteMatches, favoritePointPose, favoritePoseInsideFrame, normalizeDegrees } from "./favorite_points.js";
import type { LocalPoint, SiteFrame } from "./site_frame.js";

type FavoriteUpdate = Pick<FavoritePointInput, "longitude" | "latitude" | "bearing_deg">;
type FavoritePreview = { id: string; center: LocalPoint; bearingDeg: number };
type FavoriteState = {
  sceneId: string | null;
  items: readonly FavoritePointRecord[];
  selectedId: string | null;
  preview: FavoritePreview | null;
  loading: boolean;
  saving: boolean;
  error: string;
};
type FavoriteAPI = {
  list: (scene: string) => Promise<FavoritePointRecord[]>;
  create: (scene: string, input: FavoritePointInput) => Promise<FavoritePointRecord>;
  update: (scene: string, id: string, input: FavoriteUpdate) => Promise<FavoritePointRecord>;
  remove: (scene: string, id: string) => Promise<void>;
};

const emptyState = (sceneId: string | null): FavoriteState => ({
  sceneId, items: [], selectedId: null, preview: null, loading: false, saving: false, error: "",
});

/** A scene-local collection. Only acknowledged writes change saved records. */
export class FavoriteStore {
  private state = emptyState(null);
  private generation = 0;
  private listeners = new Set<() => void>();

  constructor(private readonly api: FavoriteAPI) {}

  snapshot = (): FavoriteState => this.state;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private set(change: Partial<FavoriteState>) {
    this.state = { ...this.state, ...change };
    this.listeners.forEach((listener) => listener());
  }

  invalidate() { this.generation++; }

  async load(sceneId: string | null): Promise<void> {
    const generation = ++this.generation;
    this.state = emptyState(sceneId);
    this.set({ loading: sceneId !== null });
    if (!sceneId) return;
    try {
      const items = await this.api.list(sceneId);
      if (generation === this.generation) this.set({ items, error: "" });
    } catch (reason) {
      if (generation !== this.generation) return;
      this.set({ error: message(reason) });
      throw reason;
    } finally {
      if (generation === this.generation) this.set({ loading: false });
    }
  }

  select(id: string) {
    if (this.state.items.some((item) => item.id === id)) this.set({ selectedId: id });
  }

  private async write<T>(request: (scene: string) => Promise<T>, accept: (value: T) => Partial<FavoriteState>): Promise<T | null> {
    const { sceneId, loading, saving } = this.state;
    const blocked = !sceneId ? "请先选择场景。" : loading ? "正在读取收藏，请稍后重试。" : saving ? "正在保存收藏，请稍后重试。" : "";
    if (blocked) {
      this.set({ error: blocked });
      throw new Error(blocked);
    }
    const generation = this.generation;
    this.set({ saving: true, error: "" });
    try {
      const value = await request(sceneId!);
      if (generation !== this.generation) return null;
      this.set({ ...accept(value), error: "" });
      return value;
    } catch (reason) {
      if (generation !== this.generation) return null;
      this.set({ error: message(reason) });
      throw reason;
    } finally {
      if (generation === this.generation) this.set({ saving: false });
    }
  }

  async create(input: FavoritePointInput): Promise<FavoritePointRecord | null> {
    const existing = this.state.items.find((item) => favoriteMatches(item, this.state.sceneId ?? "", input));
    if (existing) {
      this.select(existing.id);
      return existing;
    }
    return this.write((scene) => this.api.create(scene, input), (saved) => ({
      items: [...this.state.items, saved], selectedId: saved.id, preview: null,
    }));
  }

  async updatePose(id: string, center: LocalPoint, bearingDeg: number, frame: SiteFrame): Promise<FavoritePointRecord | null> {
    const favorite = this.state.items.find((item) => item.id === id);
    if (!favorite) throw new Error("收藏站址不存在，请重新选择。");
    const bearing = normalizeDegrees(bearingDeg);
    if (!favoritePoseInsideFrame(center, bearingToTheta(bearing, favorite.width_m, favorite.height_m), favorite.width_m, favorite.height_m, frame)) {
      throw new Error("收藏建筑必须完整位于当前场景的数据覆盖范围内。");
    }
    const point = frame.localToLngLat(center);
    return this.write((scene) => this.api.update(scene, id, {
      longitude: point.lng, latitude: point.lat, bearing_deg: bearing,
    }), (saved) => ({ items: this.state.items.map((item) => item.id === id ? saved : item) }));
  }

  previewMove(id: string, dx: number, dy: number, frame: SiteFrame) {
    if (this.state.saving || this.state.loading) return;
    const favorite = this.state.items.find((item) => item.id === id);
    if (!favorite) return;
    const pose = favoritePointPose(favorite, frame);
    const current = this.state.preview?.id === id ? this.state.preview : { id, center: pose.center, bearingDeg: pose.bearingDeg };
    const center = { x: current.center.x + dx, y: current.center.y + dy };
    if (!favoritePoseInsideFrame(center, pose.theta, pose.widthM, pose.heightM, frame)) {
      throw new Error("收藏建筑必须完整位于当前场景的数据覆盖范围内。");
    }
    this.set({ selectedId: id, preview: { ...current, center }, error: "" });
  }

  async finishMove(frame: SiteFrame): Promise<FavoritePointRecord | null> {
    const preview = this.state.preview;
    if (!preview) return null;
    try {
      return await this.updatePose(preview.id, preview.center, preview.bearingDeg, frame);
    } finally {
      if (this.state.preview === preview) this.set({ preview: null });
    }
  }

  async remove(id: string): Promise<boolean> {
    const result = await this.write(async (scene) => {
      await this.api.remove(scene, id);
      return true;
    }, () => {
      const items = this.state.items.filter((item) => item.id !== id);
      return {
        items,
        selectedId: this.state.selectedId === id ? items[0]?.id ?? null : this.state.selectedId,
        preview: this.state.preview?.id === id ? null : this.state.preview,
      };
    });
    return result === true;
  }
}

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : "收藏请求失败。";
}
