import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createFavoritePoint, deleteFavoritePoint, getFavoritePoints, updateFavoritePoint } from "../api";
import type { FavoritePointInput } from "./favorite_points";
import { bearingToTheta, favoritePointPose, favoritePoseInsideFrame } from "./favorite_points";
import { FavoriteStore } from "./favorite_store";
import type { SiteFrame } from "./site_frame";

export function useFavoritePoints(sceneId: string | null, frame: SiteFrame | null, notify: (text: string) => void) {
  const [store] = useState(() => new FavoriteStore({
    list: getFavoritePoints, create: createFavoritePoint, update: updateFavoritePoint, remove: deleteFavoritePoint,
  }));
  const state = useSyncExternalStore(store.subscribe, store.snapshot);
  const notifyRef = useRef(notify);
  notifyRef.current = notify;

  useEffect(() => {
    void store.load(sceneId).catch((reason: unknown) => notifyRef.current(`读取收藏失败：${errorText(reason)}`));
    return () => store.invalidate();
  }, [store, sceneId]);

  async function persist(action: () => Promise<unknown>, success: string): Promise<boolean> {
    try {
      const result = await action();
      if (result == null || result === false) return false;
      notifyRef.current(success);
      return true;
    } catch (reason) {
      notifyRef.current(`收藏操作失败：${errorText(reason)}`);
      return false;
    }
  }

  function requireFrame(): SiteFrame {
    if (!frame || store.snapshot().sceneId !== sceneId) throw new Error("当前场景没有可用的坐标框架。");
    return frame;
  }

  function save(input: FavoritePointInput): Promise<boolean> {
    return persist(async () => {
      const currentFrame = requireFrame();
      const center = currentFrame.lngLatToLocal({ lng: input.longitude, lat: input.latitude });
      if (!favoritePoseInsideFrame(center, bearingToTheta(input.bearing_deg, input.width_m, input.height_m), input.width_m, input.height_m, currentFrame)) {
        throw new Error("收藏建筑必须完整位于当前场景的数据覆盖范围内。");
      }
      notifyRef.current("正在保存收藏站址…");
      return store.create(input);
    }, "收藏站址已保存。");
  }

  const items = state.sceneId === sceneId ? state.items : [];
  const outOfRangeIds = new Set(items.flatMap((item) => {
    if (!frame) return [item.id];
    const pose = favoritePointPose(item, frame);
    return favoritePoseInsideFrame(pose.center, pose.theta, pose.widthM, pose.heightM, frame) ? [] : [item.id];
  }));
  const overlays = frame ? items.flatMap((item) => {
    if (outOfRangeIds.has(item.id)) return [];
    const saved = favoritePointPose(item, frame);
    const preview = state.preview?.id === item.id ? state.preview : null;
    return [{ ...saved, center: preview?.center ?? saved.center, id: item.id, selected: item.id === state.selectedId }];
  }) : [];

  return {
    items, outOfRangeIds, overlays,
    selectedId: state.selectedId, loading: state.loading, saving: state.saving, error: state.error,
    select: (id: string) => store.select(id),
    save,
    remove: (id: string) => persist(() => store.remove(id), "收藏站址已删除。"),
  };
}

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : "请求失败。";
}
