import { useEffect, useRef, useState } from "react";
import { EXPORT_LAYERS, defaultExportFilename } from "./scene_export";
import type { ExportExtent, ExportLayerChoice, ExportLayerFlags, ExportLayerId } from "./scene_export";
import type { ParetoLayer } from "./solution_diversity";

export type SceneExportDialogValue = {
  layers: ExportLayerFlags;
  pareto: Record<ParetoLayer, boolean>;
  showRecommendRanks: boolean;
  extent: ExportExtent;
  filename: string;
};

/** Export settings only. Closing does not cancel optimization or a running capture. */
export function SceneExportDialog({
  open,
  sceneTitle,
  layers,
  paretoCounts,
  busy,
  error,
  onClose,
  onExport,
}: {
  open: boolean;
  sceneTitle: string;
  layers: readonly ExportLayerChoice[];
  paretoCounts: Record<ParetoLayer, number>;
  busy: boolean;
  error: string;
  onClose: () => void;
  onExport: (value: SceneExportDialogValue) => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(busy);
  const touched = useRef(new Set<ExportLayerId>());
  onCloseRef.current = onClose;
  busyRef.current = busy;
  const [checked, setChecked] = useState<ExportLayerFlags>(() => flagsFrom(layers));
  const [pareto, setPareto] = useState<Record<ParetoLayer, boolean>>(() => ({
    1: paretoCounts[1] > 0,
    2: paretoCounts[2] > 0,
    3: paretoCounts[3] > 0,
  }));
  const [showRanks, setShowRanks] = useState(false);
  const [extent, setExtent] = useState<ExportExtent>("site");
  const [filename, setFilename] = useState(() => defaultExportFilename(sceneTitle));

  useEffect(() => {
    setChecked((current) => {
      const next = { ...current };
      let changed = false;
      for (const layer of layers) {
        const desired = layer.disabled || touched.current.has(layer.id) ? (layer.disabled ? false : current[layer.id]) : layer.checked;
        if (next[layer.id] !== desired) {
          next[layer.id] = desired;
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [layers]);

  const layersRef = useRef(layers);
  const countsRef = useRef(paretoCounts);
  const titleRef = useRef(sceneTitle);
  layersRef.current = layers;
  countsRef.current = paretoCounts;
  titleRef.current = sceneTitle;

  useEffect(() => {
    if (!open) return;
    touched.current.clear();
    setChecked(flagsFrom(layersRef.current));
    const counts = countsRef.current;
    setPareto({
      1: counts[1] > 0,
      2: counts[2] > 0,
      3: counts[3] > 0,
    });
    setShowRanks(false);
    setExtent("site");
    setFilename(defaultExportFilename(titleRef.current));
    dialogRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || busyRef.current) return;
      event.preventDefault();
      onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;
  return (
    <div className="scene-build-backdrop" onClick={() => { if (!busy) onClose(); }}>
      <section
        ref={dialogRef}
        className="scene-build-dialog scene-export-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="scene-export-title"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="scene-build-head">
          <div>
            <h2 id="scene-export-title">导出优化场景 PNG</h2>
            <p className="scene-build-subtitle">只影响这次图片，不改变当前地图</p>
          </div>
          <button type="button" className="drawer-close" aria-label="关闭" disabled={busy} onClick={onClose}>关闭</button>
        </div>
        <form
          className="scene-build-body"
          onSubmit={(event) => {
            event.preventDefault();
            if (busy) return;
            onExport({ layers: checked, pareto, showRecommendRanks: showRanks, extent, filename });
          }}
        >
          <div className="scene-export-groups">
            <fieldset disabled={busy}>
              <legend>GIS 图层</legend>
              <div className="scene-export-checks">
                {layers.map((layer) => (
                  <label key={layer.id} className="scene-export-check" title={layer.disabled ? layer.reason : undefined}>
                    <input
                      type="checkbox"
                      checked={layer.disabled ? false : checked[layer.id]}
                      disabled={layer.disabled}
                      onChange={(event) => {
                        touched.current.add(layer.id);
                        setChecked((current) => ({ ...current, [layer.id]: event.target.checked }));
                      }}
                    />
                    <span>{layer.label}{layer.disabled && layer.reason ? `（${layer.reason}）` : ""}</span>
                  </label>
                ))}
              </div>
              <p className="hud-note">选址范围边界会保留在图片中。</p>
            </fieldset>
            <fieldset disabled={busy}>
              <legend>Pareto 方案</legend>
              <div className="scene-export-checks">
                {([1, 2, 3] as const).map((layer) => (
                  <label key={layer} className="scene-export-check">
                    <input
                      type="checkbox"
                      checked={pareto[layer]}
                      onChange={(event) => setPareto((current) => ({ ...current, [layer]: event.target.checked }))}
                    />
                    <span>第 {layer} 层（{paretoCounts[layer]}）</span>
                  </label>
                ))}
                <label className="scene-export-check">
                  <input type="checkbox" checked={showRanks} onChange={(event) => setShowRanks(event.target.checked)} />
                  <span>显示推荐方案排名编号</span>
                </label>
              </div>
            </fieldset>
            <fieldset disabled={busy}>
              <legend>截图范围</legend>
              <div className="scene-export-checks">
                <label className="scene-export-check">
                  <input type="radio" name="export-extent" checked={extent === "site"} onChange={() => setExtent("site")} />
                  <span>完整选址范围</span>
                </label>
                <label className="scene-export-check">
                  <input type="radio" name="export-extent" checked={extent === "view"} onChange={() => setExtent("view")} />
                  <span>当前地图视角</span>
                </label>
              </div>
            </fieldset>
            <label>图片文件名
              <input value={filename} disabled={busy} onChange={(event) => setFilename(event.target.value)} />
            </label>
          </div>
          {error ? <p className="scene-build-error" role="alert">{error}</p> : null}
          <div className="scene-build-actions">
            <button type="button" disabled={busy} onClick={onClose}>取消</button>
            <button type="submit" className="primary" disabled={busy}>{busy ? "正在生成图片…" : "导出 PNG"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

function flagsFrom(layers: readonly ExportLayerChoice[]): ExportLayerFlags {
  return Object.fromEntries(EXPORT_LAYERS.map((item) => {
    const choice = layers.find((layer) => layer.id === item.id);
    return [item.id, Boolean(choice && !choice.disabled && choice.checked)];
  })) as ExportLayerFlags;
}
