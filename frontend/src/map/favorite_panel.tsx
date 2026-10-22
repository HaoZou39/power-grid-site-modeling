import { useEffect, useRef, useState } from "react";
import { fetchPoseObjectives, fetchSiteReport } from "../api";
import type { SiteReport } from "../api";
import type { PoseObjectives } from "./decision_run";
import { widthAzimuthDeg } from "./decision_run";
import type { SearchConfig } from "./site_edit";
import type { FavoritePointRecord } from "./favorite_points";
import { favoritePointPose, favoritePoseInsideFrame, normalizeDegrees, thetaToBearing } from "./favorite_points";
import type { SiteFrame } from "./site_frame";
import { useDraggablePanel } from "./use_draggable_panel.js";

export function FavoritePanel({
  open, zIndex, sceneTitle, frame, config, sceneVersion, favorites, selectedId,
  outOfRangeIds, loading, error, onBringToFront, onClose, onSelect, onAdjust, onUpdate, onDelete,
}: {
  open: boolean;
  zIndex: number;
  sceneTitle: string;
  frame: SiteFrame | null;
  config: SearchConfig;
  sceneVersion: number;
  favorites: readonly FavoritePointRecord[];
  selectedId: string | null;
  outOfRangeIds: ReadonlySet<string>;
  loading: boolean;
  error: string;
  onBringToFront: () => void;
  onClose: () => void;
  onSelect: (favoriteId: string) => void;
  onAdjust: (favoriteId: string) => void;
  onUpdate: (favoriteId: string, bearingDeg: number) => Promise<void>;
  onDelete: (favoriteId: string) => Promise<void>;
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
  const [angleDraft, setAngleDraft] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState(false);
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState("");
  const [evaluation, setEvaluation] = useState<{
    key: string; objectives?: PoseObjectives; report?: SiteReport; error?: string;
  } | null>(null);
  const pose = favorite && frame ? favoritePointPose(favorite, frame) : null;
  const outOfRange = !favorite || !frame || outOfRangeIds.has(favorite.id);
  const configKey = JSON.stringify(config);
  const evaluationKey = JSON.stringify([favorite, configKey, sceneVersion]);

  useEffect(() => {
    setAngleDraft(null);
    setPendingDelete(false);
    setLocalError("");
  }, [favorite?.id, favorite?.bearing_deg]);

  useEffect(() => {
    if (!open || !favorite || !pose || outOfRange) return;
    let active = true;
    const { scene_name: _scene, include_demand, ...settings } = JSON.parse(configKey) as SearchConfig;
    const request = {
      ...settings, rect_w_m: favorite.width_m, rect_h_m: favorite.height_m,
      x: pose.center.x, y: pose.center.y, theta: pose.theta,
    };
    const { x, y, theta, ...objectiveConfig } = request;
    void fetchPoseObjectives(favorite.scene_id, { ...objectiveConfig, include_demand, poses: [{ x, y, theta }] }).then(async (result) => {
      if (!active) return;
      const objectives = result.items[0];
      setEvaluation({ key: evaluationKey, objectives });
      try {
        const report = await fetchSiteReport(favorite.scene_id, request);
        if (active) setEvaluation({ key: evaluationKey, objectives, report });
      } catch (reason) {
        if (active) setEvaluation({ key: evaluationKey, objectives, error: reason instanceof Error ? reason.message : "运输报告失败" });
      }
    }).catch((reason: unknown) => {
      if (active) setEvaluation({ key: evaluationKey, error: reason instanceof Error ? reason.message : "评价失败" });
    });
    return () => { active = false; };
  }, [open, evaluationKey, outOfRange, frame]);

  if (!open) return null;
  const current = evaluation?.key === evaluationKey ? evaluation : null;
  const metrics = current?.objectives;
  const report = current?.report;
  const angle = pose ? widthAzimuthDeg(pose.theta) : 0;
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

  async function saveAngle() {
    if (!favorite || !frame || !pose || angleDraft === null || saving) return;
    const value = Number(angleDraft);
    if (!angleDraft.trim() || !Number.isFinite(value)) {
      setLocalError("方位角必须是有限数字。");
      setAngleDraft(null);
      return;
    }
    const theta = (normalizeDegrees(value) - 90) * Math.PI / 180;
    if (!favoritePoseInsideFrame(pose.center, theta, favorite.width_m, favorite.height_m, frame)) {
      setLocalError("旋转后的建筑必须完整位于当前选址范围内。");
      setAngleDraft(null);
      return;
    }
    setLocalError("");
    setSaving(true);
    try {
      await onUpdate(favorite.id, thetaToBearing(theta, favorite.width_m, favorite.height_m));
      setAngleDraft(null);
    } finally { setSaving(false); }
  }

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
        {localError && <p className="hud-evaluation error">{localError}</p>}
        {!loading && !favorite && <p className="hud-notice">点击「编辑 → 添加收藏点」，再点击地图添加。</p>}
        {favorite && <>
          <p className="hud-kicker">决策变量</p>
          <dl className="hud-metrics">
            <div><dt>经度</dt><dd>{favorite.longitude.toFixed(6)}</dd></div>
            <div><dt>纬度</dt><dd>{favorite.latitude.toFixed(6)}</dd></div>
            <div className="scheme-azimuth"><dt>方位角（宽边）</dt><dd>
              <input type="number" step="any" aria-label="收藏点方位角（宽边）"
                value={angleDraft ?? angle.toFixed(1)} disabled={outOfRange || saving}
                onChange={(event) => setAngleDraft(event.target.value)}
                onBlur={() => void saveAngle()}
                onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} />
            </dd></div>
            <div><dt>可行性</dt><dd>{outOfRange ? "当前范围外" : metrics ? metrics.is_feasible ? "可行" : "不可行" : "—"}</dd></div>
          </dl>
          {!outOfRange && !current && <p className="hud-evaluation loading">正在评价目标与约束…</p>}
          {current?.error && <p className="hud-evaluation error">评价失败：{current.error}</p>}
          {metrics && <><p className="hud-evaluation success">目标与约束已评价</p>
            <p className="hud-kicker">目标</p>
            <dl className="hud-metrics">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
          </>}
          <div className="hud-actions">
            <button type="button" disabled={outOfRange} onClick={() => onAdjust(favorite.id)}>地图拖动</button>
            {pendingDelete ? <>
              <button type="button" onClick={() => void onDelete(favorite.id).then(() => setPendingDelete(false))}>确认删除</button>
              <button type="button" onClick={() => setPendingDelete(false)}>取消</button>
            </> : <button type="button" onClick={() => setPendingDelete(true)}>删除收藏点</button>}
          </div>
        </>}
      </div>
      <button type="button" className="panel-resize" aria-label="调整收藏点详情面板大小" {...panel.resizeHandleProps} />
    </aside>
  );
}
