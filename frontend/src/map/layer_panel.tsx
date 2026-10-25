import { useRef, useState } from "react";
import type { ReactNode } from "react";
import type { SceneLayerInfo } from "../api";
import { LANDUSE_CLASSES } from "./toolbar_commands";
import type { LanduseClassId } from "./toolbar_commands";
import type { RegionVisibility } from "./site_overlay";
import { useDraggablePanel } from "./use_draggable_panel.js";

const AGENT_DEFAULT_CENTER_FROM_RIGHT = 310;
const DEFAULT_BOTTOM_OFFSET = 72;

export function LayerPanel({
  open,
  zIndex,
  onBringToFront,
  sceneReady,
  info,
  error,
  shownClasses,
  demVisible,
  demOpacity,
  roadsVisible,
  roadError,
  regionVisibility,
  feasibilityVisible,
  feasibilityPreparing,
  farmlandVisible,
  farmlandDeleting,
  onClose,
  onToggleClass,
  onToggleDem,
  onDemOpacity,
  onToggleRoads,
  onToggleRegion,
  onToggleFeasibility,
  onToggleFarmland,
  onReplaceFarmland,
  onDeleteFarmland,
}: {
  open: boolean;
  zIndex: number;
  onBringToFront: () => void;
  sceneReady: boolean;
  info: SceneLayerInfo | null;
  error: string;
  shownClasses: Record<LanduseClassId, boolean>;
  demVisible: boolean;
  demOpacity: number;
  roadsVisible: boolean;
  roadError: string;
  regionVisibility: RegionVisibility;
  feasibilityVisible: boolean;
  feasibilityPreparing: boolean;
  farmlandVisible: boolean;
  farmlandDeleting: boolean;
  onClose: () => void;
  onToggleClass: (id: LanduseClassId) => void;
  onToggleDem: () => void;
  onDemOpacity: (opacity: number) => void;
  onToggleRoads: () => void;
  onToggleRegion: (kind: keyof RegionVisibility) => void;
  onToggleFeasibility: () => void;
  onToggleFarmland: () => void;
  onReplaceFarmland: () => void;
  onDeleteFarmland: () => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const panelRef = useRef<HTMLElement>(null);
  const panel = useDraggablePanel(panelRef, {
    defaultSize: { width: 310, height: 560 },
    minSize: { width: 1, height: 1 },
    topInset: 148,
    positionKey: open ? "open" : "closed",
    manageSize: false,
    initialPosition: (bounds, size) => ({
      x: bounds.width - AGENT_DEFAULT_CENTER_FROM_RIGHT - size.width / 2,
      y: bounds.height - size.height - DEFAULT_BOTTOM_OFFSET,
    }),
  });
  if (!open) return null;
  const loading = sceneReady && !info && !error;
  const demAvailable = info?.dem.available === true;
  const roadsAvailable = info?.roads.available === true;
  const missingLanduse = info
    ? LANDUSE_CLASSES.filter((item) => !info.landuse[item.id]).map((item) => item.label)
    : [];
  const resourceMessage = !sceneReady ? "场景尚未准备完成" : error || (loading ? "正在读取图层资源…" : "");

  return (
    <aside
      ref={panelRef}
      className={`layer-panel${collapsed ? " collapsed" : ""}${panel.dragging ? " panel-dragging" : ""}`}
      style={{ ...panel.style, zIndex }}
      onPointerDownCapture={onBringToFront}
      onFocusCapture={onBringToFront}
      aria-label="GIS 图层"
    >
      <header className="layer-panel-head panel-drag-handle" {...panel.dragHandleProps}>
        <strong>GIS 图层</strong>
        <span>
          <button type="button" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? "展开图层面板" : "折叠图层面板"}>
            {collapsed ? "展开" : "折叠"}
          </button>
          <button type="button" onClick={onClose} aria-label="关闭图层面板">关闭</button>
        </span>
      </header>
      {!collapsed && (
        <div className="layer-panel-body">
          {resourceMessage && <p className="layer-status">{resourceMessage}</p>}
          <LayerGroup title="地形分析">
            <LayerSwitch
              label="DEM 高程"
              checked={demVisible}
              disabled={!sceneReady || !demAvailable}
              swatch="dem"
              onChange={onToggleDem}
            />
            {info && !demAvailable && <p className="layer-status error">{info.dem.error || "DEM 高程资源缺失"}</p>}
            {info && demAvailable && (
              <div className="dem-controls">
                <div className="dem-legend" aria-label="DEM 高程色带">
                  <span>{formatElevation(info.dem.min_elevation_m)} m</span>
                  <i />
                  <span>{formatElevation(info.dem.max_elevation_m)} m</span>
                </div>
                <label>
                  <span>透明度 {Math.round(demOpacity * 100)}%</span>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={Math.round(demOpacity * 100)}
                    onChange={(event) => onDemOpacity(Number(event.target.value) / 100)}
                  />
                </label>
              </div>
            )}
          </LayerGroup>

          <LayerGroup title="土地利用">
            <div className="landuse-layer-grid">
              {LANDUSE_CLASSES.map((item) => (
                <LayerSwitch
                  key={item.id}
                  label={item.label}
                  checked={shownClasses[item.id]}
                  disabled={!sceneReady || info?.landuse[item.id] !== true}
                  swatch={item.id}
                  onChange={() => onToggleClass(item.id)}
                />
              ))}
            </div>
            {missingLanduse.length > 0 && (
              <p className="layer-status error">缺少图层资源：{missingLanduse.join("、")}</p>
            )}
          </LayerGroup>

          <LayerGroup title="永久基本农田">
            <LayerSwitch
              label="永久基本农田"
              checked={farmlandVisible}
              disabled={!sceneReady || info?.protected_farmland?.available !== true}
              swatch="protected-farmland"
              onChange={onToggleFarmland}
            />
            {info?.protected_farmland?.available === true && (
              <p className="layer-note">
                {info.protected_farmland.source_crs || "坐标系未记录"}
                {typeof info.protected_farmland.feature_count === "number"
                  ? `，地块 ${info.protected_farmland.feature_count} 个`
                  : ""}
                {typeof info.protected_farmland.intersecting_feature_count === "number"
                  ? `，场景内 ${info.protected_farmland.intersecting_feature_count} 个`
                  : ""}
                。隐藏只影响显示，不取消禁建。
              </p>
            )}
            {info?.protected_farmland?.available !== true && sceneReady && (
              <p className="layer-status">尚未导入永久基本农田</p>
            )}
            {info?.protected_farmland?.available === true && (
              <p className="layer-note">现有可接入道路与永农重叠 {info?.protected_farmland?.osm_overlap_cells} 个格子，新建进站道路不会从这些格子接入。</p>
            )}
            <div className="layer-actions">
              <button type="button" disabled={!sceneReady} onClick={onReplaceFarmland}>
                {info?.protected_farmland?.available ? "替换" : "导入"}
              </button>
              <button
                type="button"
                disabled={!sceneReady || info?.protected_farmland?.available !== true}
                onClick={onDeleteFarmland}
              >
                {farmlandDeleting ? "确认删除" : "删除"}
              </button>
            </div>
          </LayerGroup>

          <LayerGroup title="建设约束分析">
            <LayerSwitch
              label="建设可行性"
              checked={feasibilityVisible}
              disabled={!sceneReady}
              swatch="construction-feasibility"
              onChange={onToggleFeasibility}
            />
            {feasibilityPreparing ? (
              <p className="layer-status">正在生成</p>
            ) : feasibilityVisible && (
              <div className="feasibility-legend" aria-label="建设可行性图例">
                <span><i className="allowed" />可建设</span>
                <span><i className="blocked" />不可建设</span>
              </div>
            )}
          </LayerGroup>

          <LayerGroup title="交通与规划">
            <LayerSwitch
              label="道路网络"
              checked={roadsVisible}
              disabled={!sceneReady || !roadsAvailable}
              swatch="osm-road"
              onChange={onToggleRoads}
            />
            {(roadError || (info && !roadsAvailable)) && (
              <p className="layer-status error">{roadError || info?.roads.error || "道路资源缺失"}</p>
            )}
            {info?.roads.provider && (
              <p className="layer-note">来源：{info.roads.provider === "gaode" ? "高德" : info.roads.provider === "osm" ? "OpenStreetMap" : info.roads.provider}</p>
            )}
            {roadsVisible && <div className="layer-note" aria-label="道路类别图例">
              <p style={{ color: "#76e6ff" }}>━ 普通道路 · 可接入</p>
              <p style={{ color: "#f6ae55" }}>┄ 匝道 · 不可接入</p>
              <p style={{ color: "#ff647c" }}>━ 高速地表段 · 不可接入</p>
              <p style={{ color: "#b8a2f5" }}>┄ 隧道 · 不可接入</p>
            </div>}
            <LayerSwitch
              label="手绘禁区"
              checked={regionVisibility.exclusion}
              swatch="exclusion"
              onChange={() => onToggleRegion("exclusion")}
            />
            <LayerSwitch
              label="手绘可行域"
              checked={regionVisibility.feasible}
              swatch="feasible"
              onChange={() => onToggleRegion("feasible")}
            />
          </LayerGroup>
        </div>
      )}
    </aside>
  );
}

function LayerGroup({ title, children }: { title: string; children: ReactNode }) {
  return <section className="layer-group"><h3>{title}</h3>{children}</section>;
}

function LayerSwitch({
  label,
  checked,
  disabled = false,
  swatch,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  swatch: string;
  onChange: () => void;
}) {
  return (
    <label className={disabled ? "layer-switch disabled" : "layer-switch"}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={onChange} />
      <i className={`layer-swatch ${swatch}`} />
      <span>{label}</span>
    </label>
  );
}

function formatElevation(value: number | undefined): string {
  return typeof value === "number" ? value.toFixed(1) : "—";
}
