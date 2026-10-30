import { useEffect, useRef, useState } from "react";
import { fetchPoseObjectives, fetchSiteReport } from "../api";
import { evaluateFavorite, favoriteEvaluationRequests } from "./favorite_evaluation";
import type { FavoriteEvaluation } from "./favorite_evaluation";
import type { SearchConfig } from "./site_edit";
import type { FavoritePointRecord } from "./favorite_points";
import { favoritePointPose } from "./favorite_points";
import type { SiteFrame } from "./site_frame";
import { useDraggablePanel } from "./use_draggable_panel.js";

export function FavoritePanel({
  open, zIndex, sceneTitle, frame, config, sceneVersion, pauseEvaluation = false, ready, busy, favorites, selectedId,
  outOfRangeIds, loading, error, onBringToFront, onClose, onSelect, onDelete,
}: {
  open: boolean;
  zIndex: number;
  sceneTitle: string;
  frame: SiteFrame | null;
  config: SearchConfig;
  sceneVersion: number;
  pauseEvaluation?: boolean;
  ready: boolean;
  busy: boolean;
  favorites: readonly FavoritePointRecord[];
  selectedId: string | null;
  outOfRangeIds: ReadonlySet<string>;
  loading: boolean;
  error: string;
  onBringToFront: () => void;
  onClose: () => void;
  onSelect: (favoriteId: string) => void;
  onDelete: (favoriteId: string) => Promise<boolean>;
}) {
  const favorite = favorites.find((item) => item.id === selectedId) ?? favorites[0];
  const panelRef = useRef<HTMLElement>(null);
  const panel = useDraggablePanel(panelRef, {
    defaultSize: { width: 360, height: 540 },
    minSize: { width: 300, height: 280 },
    topInset: 148,
    resetKey: favorite?.id,
    positionKey: open ? "open" : "closed",
    initialPosition: (bounds, size) => ({ x: (bounds.width - size.width) / 2, y: 168 }),
  });
  const [pendingDelete, setPendingDelete] = useState(false);
  const [evaluation, setEvaluation] = useState<(FavoriteEvaluation & { key: string }) | null>(null);
  const pose = favorite && frame ? favoritePointPose(favorite, frame) : null;
  const outOfRange = !favorite || !frame || outOfRangeIds.has(favorite.id);
  const configKey = JSON.stringify(config);
  const evaluationKey = JSON.stringify([favorite, configKey, sceneVersion]);

  useEffect(() => {
    setPendingDelete(false);
  }, [favorite?.id]);

  useEffect(() => {
    if (!open || !ready || pauseEvaluation || !favorite || !frame || outOfRange) return;
    const controller = new AbortController();
    const requests = favoriteEvaluationRequests(favorite, frame, JSON.parse(configKey) as SearchConfig);
    void evaluateFavorite(favorite.scene_id, requests, controller.signal,
      (result) => setEvaluation({ key: evaluationKey, ...result }),
      { objectives: fetchPoseObjectives, report: fetchSiteReport });
    return () => controller.abort();
  }, [open, ready, pauseEvaluation, evaluationKey, outOfRange, frame]);

  if (!open) return null;
  const current = evaluation?.key === evaluationKey ? evaluation : null;
  const metrics = current?.objectives;
  const report = current?.report;
  const angle = pose ? frame!.widthBearing(pose.theta, pose.center) : 0;
  const number = (value: number | null | undefined | "") => typeof value === "number" ? value.toFixed(3) : "—";
  const rows = metrics ? [
    ["地形平整度", number(metrics.dem_soft)],
    ["进站长度（m）", number(metrics.offroad_haul_m)],
    ["进站累计高差（m）", number(metrics.haul_rise_m)],
    ["禁建覆盖格数", number(metrics.obstacle_hard_count)],
    ["道路距离（m）", number(metrics.road_distance)],
    ["进站坡度（°）", number(report?.access_slope_deg)],
    ...(config.origin_x !== undefined ? [["沿路长度（m）", number(metrics.road_haul_m)]] : []),
    ...(config.include_demand ? [["需求点距离（m）", number(metrics.demand_distance)]] : []),
  ] : [];

  return (
    <aside ref={panelRef}
      className={["scheme-card", panel.dragging ? "panel-dragging" : "", panel.resizing ? "panel-resizing" : ""].join(" ")}
      style={{ ...panel.style, zIndex }} aria-label="收藏点详情"
      onPointerDownCapture={onBringToFront} onFocusCapture={onBringToFront}
      onWheel={(event) => event.stopPropagation()}>
      <div className="scheme-card-head panel-drag-handle" {...panel.dragHandleProps}>
        <strong>收藏点 {favorite ? favorites.indexOf(favorite) + 1 : 0}/{favorites.length}</strong>
        <button type="button" className="drawer-close" onClick={onClose}>关闭</button>
      </div>
      <div className="scheme-card-content">
        <p className="favorite-panel-note">{sceneTitle}</p>
        {favorites.length > 1 && <label className="favorite-picker">切换收藏点
          <select value={favorite?.id ?? ""} onChange={(event) => onSelect(event.target.value)}>
            {favorites.map((item, index) => <option key={item.id} value={item.id}>
              收藏点 {index + 1} · {item.longitude.toFixed(6)}, {item.latitude.toFixed(6)}
            </option>)}
          </select>
        </label>}
        {loading && <p className="hud-notice">正在读取收藏…</p>}
        {error && <p className="hud-evaluation error">{error}</p>}
        {!loading && !favorite && <p className="hud-notice">当前场景还没有收藏点。可在方案详情卡点击「收藏站址」保存已有方案。</p>}
        {favorite && <>
          <p className="hud-kicker">决策变量</p>
          <dl className="hud-metrics">
            <div><dt>经度</dt><dd>{favorite.longitude.toFixed(6)}</dd></div>
            <div><dt>纬度</dt><dd>{favorite.latitude.toFixed(6)}</dd></div>
            <div><dt>方位角（宽边）</dt><dd>{pose ? `${angle.toFixed(1)}°` : "—"}</dd></div>
            <div><dt>可行性</dt><dd>{outOfRange ? "当前范围外" : metrics ? metrics.is_feasible ? "可行" : "不可行" : "—"}</dd></div>
          </dl>
          {!outOfRange && !ready && <p className="hud-notice">收藏已保存；准备当前场景数据后可评价目标与约束。</p>}
          {!outOfRange && ready && !current && <p className="hud-evaluation loading">正在评价目标与约束…</p>}
          {current?.error && <p className="hud-evaluation error">评价失败：{current.error}</p>}
          {current?.reportError && <p className="hud-evaluation error">运输报告失败：{current.reportError}</p>}
          {metrics && <><p className="hud-evaluation success">目标与约束已评价</p>
            <p className="hud-kicker">目标</p>
            <dl className="hud-metrics">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
          </>}
          <div className="hud-actions">
            {pendingDelete ? <>
              <button type="button" disabled={busy} onClick={() => void onDelete(favorite.id).then((deleted) => { if (deleted) setPendingDelete(false); })}>确认删除</button>
              <button type="button" disabled={busy} onClick={() => setPendingDelete(false)}>取消</button>
            </> : <button type="button" disabled={busy} onClick={() => setPendingDelete(true)}>删除收藏点</button>}
          </div>
        </>}
      </div>
      <button type="button" className="panel-resize" aria-label="调整收藏点详情面板大小" {...panel.resizeHandleProps} />
    </aside>
  );
}
