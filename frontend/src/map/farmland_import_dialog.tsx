import { useEffect, useRef, useState } from "react";
import { confirmProtectedFarmland, previewProtectedFarmland } from "../api";
import type { FarmlandPreview } from "../api";

/** Preview a farmland shapefile, then save it only after the user confirms. */
export function FarmlandImportDialog({
  open,
  sceneId,
  sceneTitle,
  onClose,
  onPreview,
  onCommitted,
}: {
  open: boolean;
  sceneId: string | null;
  sceneTitle: string;
  onClose: () => void;
  onPreview: (preview: { token: string; url: string } | null) => void;
  onCommitted: (message: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<FarmlandPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dialogRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  const onPreviewRef = useRef(onPreview);
  onCloseRef.current = onClose;
  onPreviewRef.current = onPreview;

  useEffect(() => {
    if (!open) {
      setFile(null);
      setPreview(null);
      setBusy(false);
      setError("");
      onPreviewRef.current(null);
      return;
    }
    dialogRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || busy) return;
      event.preventDefault();
      onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy]);

  if (!open || !sceneId) return null;

  async function readFile(next: File) {
    setFile(next);
    setPreview(null);
    setError("");
    onPreview(null);
    setBusy(true);
    try {
      const summary = await previewProtectedFarmland(sceneId as string, next);
      setPreview(summary);
      onPreview({
        token: summary.token,
        url: `/api/v1/scenes/${encodeURIComponent(sceneId as string)}/protected-farmland/preview/${summary.token}`,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取压缩包");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      await confirmProtectedFarmland(sceneId as string, preview.token);
      onCommitted(`已导入永久基本农田，场景内覆盖 ${formatArea(preview.area_m2)}。再次导入会替换这一层。`);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法保存永久基本农田");
      setBusy(false);
    }
  }

  return (
    <div className="scene-build-backdrop" onClick={() => { if (!busy) onClose(); }}>
      <section
        ref={dialogRef}
        className="scene-build-dialog farmland-import-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="farmland-import-title"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="scene-build-head">
          <div>
            <h2 id="farmland-import-title">导入永久基本农田</h2>
            <p className="scene-build-subtitle">上传 Shapefile 压缩包，确认位置后再写入当前场景</p>
          </div>
          <button type="button" className="drawer-close" aria-label="关闭" disabled={busy} onClick={onClose}>关闭</button>
        </div>
        <div className="scene-build-body">
          <p className="farmland-summary">当前目标场景：{sceneTitle}</p>
          <label>
            ZIP 文件
            <input
              type="file"
              accept=".zip,application/zip"
              disabled={busy}
              onChange={(event) => {
                const next = event.target.files?.[0];
                if (next) void readFile(next);
              }}
            />
          </label>
          {file && <p className="farmland-summary">已选择：{file.name}</p>}
          {busy && !preview && <p className="hud-note">正在读取坐标系并对齐到当前 1 m 网格…</p>}
          {preview && (
            <>
              <dl className="farmland-summary">
                <div><dt>原始坐标系</dt><dd>{preview.source_crs}</dd></div>
                <div><dt>目标场景坐标系</dt><dd>{preview.scene_crs}</dd></div>
                <div><dt>Shapefile 地块数量</dt><dd>{preview.feature_count}</dd></div>
                <div><dt>与当前场景相交的地块数量</dt><dd>{preview.intersecting_feature_count}</dd></div>
                <div><dt>场景内永农覆盖面积</dt><dd>{formatArea(preview.area_m2)}</dd></div>
                <div><dt>新建进站道路避让宽度</dt><dd>{preview.access_road_width_m} m</dd></div>
              </dl>
              {preview.empty_feature_count > 0 && (
                <p className="hud-note">有 {preview.empty_feature_count} 条空记录未计入地块。</p>
              )}
              {preview.osm_overlap_cells > 0 && (
                <p className="hud-note">已有 OSM 道路与永农重叠 {preview.osm_overlap_cells} 个格子。现状路网仍可运输，新建进站道路不会从这些格子接入。</p>
              )}
              <img
                className="farmland-preview"
                alt="永久基本农田在当前场景网格上的预览"
                src={`/api/v1/scenes/${encodeURIComponent(sceneId)}/protected-farmland/preview/${preview.token}`}
              />
              <p className="hud-note">紫色区域已叠加到当前地图。请对照卫星影像确认位置。取消不会保存；确认后会替换本场景已有的永久基本农田。</p>
            </>
          )}
          {error && <p className="scene-build-error" role="alert">{error}</p>}
        </div>
        <div className="scene-build-actions">
          <button type="button" disabled={busy} onClick={onClose}>取消</button>
          <button type="button" className="primary" disabled={busy || !preview} onClick={() => void confirm()}>
            {busy && preview ? "正在保存…" : "确认导入"}
          </button>
        </div>
      </section>
    </div>
  );
}

function formatArea(cellCount: number): string {
  if (cellCount >= 10000) return `${(cellCount / 10000).toFixed(2)} 公顷`;
  return `${cellCount.toLocaleString("zh-CN")} m²`;
}
