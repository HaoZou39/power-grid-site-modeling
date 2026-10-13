import { useState } from "react";
import type { ReactNode } from "react";
import type { SceneLayerInfo } from "../api";
import { LANDUSE_CLASSES } from "./toolbar_commands";
import type { LanduseClassId } from "./toolbar_commands";
import type { RegionVisibility } from "./site_overlay";

export function LayerPanel({
  open,
  sceneReady,
  info,
  error,
  shownClasses,
  demVisible,
  demOpacity,
  roadsVisible,
  roadError,
  regionVisibility,
  onClose,
  onToggleClass,
  onToggleDem,
  onDemOpacity,
  onToggleRoads,
  onToggleRegion,
}: {
  open: boolean;
  sceneReady: boolean;
  info: SceneLayerInfo | null;
  error: string;
  shownClasses: Record<LanduseClassId, boolean>;
  demVisible: boolean;
  demOpacity: number;
  roadsVisible: boolean;
  roadError: string;
  regionVisibility: RegionVisibility;
  onClose: () => void;
  onToggleClass: (id: LanduseClassId) => void;
  onToggleDem: () => void;
  onDemOpacity: (opacity: number) => void;
  onToggleRoads: () => void;
  onToggleRegion: (kind: keyof RegionVisibility) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  if (!open) return null;
  const loading = sceneReady && !info && !error;
  const demAvailable = info?.dem.available === true;
  const roadsAvailable = info?.roads.available === true;
  const missingLanduse = info
    ? LANDUSE_CLASSES.filter((item) => !info.landuse[item.id]).map((item) => item.label)
    : [];
  const resourceMessage = !sceneReady ? "场景尚未准备完成" : error || (loading ? "正在读取图层资源…" : "");

  return (
    <aside className={collapsed ? "layer-panel collapsed" : "layer-panel"} aria-label="GIS 图层">
      <header className="layer-panel-head">
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
                <p className="layer-note">
                  原始 DEM 空间分辨率约 {formatResolution(info.dem.source_resolution_m)} m；当前 1 m 网格为重采样结果。
                </p>
              </div>
            )}
          </LayerGroup>

          <LayerGroup title="土地利用">
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
            {missingLanduse.length > 0 && (
              <p className="layer-status error">缺少图层资源：{missingLanduse.join("、")}</p>
            )}
          </LayerGroup>

          <LayerGroup title="交通与规划">
            <LayerSwitch
              label="OSM 道路网络"
              checked={roadsVisible}
              disabled={!sceneReady || !roadsAvailable}
              swatch="osm-road"
              onChange={onToggleRoads}
            />
            {(roadError || (info && !roadsAvailable)) && (
              <p className="layer-status error">{roadError || info?.roads.error || "OSM 道路资源缺失"}</p>
            )}
            <LayerSwitch
              label="禁区"
              checked={regionVisibility.exclusion}
              swatch="exclusion"
              onChange={() => onToggleRegion("exclusion")}
            />
            <LayerSwitch
              label="可行域"
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

function formatResolution(value: number | null | undefined): string {
  return typeof value === "number" ? value.toFixed(value < 10 ? 1 : 0) : "10";
}
