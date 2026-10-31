import { useEffect, useRef, useState } from "react";
import { confirmSceneData, getRoadPreview, previewSceneData, restoreOsmRoads } from "../api";
import type { RoadSegment, SceneDataPreview } from "../api";
import { dataImportBody } from "./scene_data_import";
import { CadImportPanel } from "./cad_import_panel";
import type { FieldPolicy } from "./site_edit";

export type ImportMapPreview = { farmlandUrl: string | null; roads: { segments: RoadSegment[]; kinds: number[] } | null };

export function SceneDataImportDialog({ open, sceneId, sceneTitle, roadProvider, hasUnsavedLanduse, fieldPolicy, onClose, onPreview, onCommitted }: {
  open: boolean;
  sceneId: string | null;
  sceneTitle: string;
  roadProvider: string;
  hasUnsavedLanduse: boolean;
  fieldPolicy: FieldPolicy;
  onClose: () => void;
  onPreview: (value: ImportMapPreview | null) => void;
  onCommitted: (message: string, cadChanged?: boolean, revision?: string) => void;
}) {
  const [farmland, setFarmland] = useState<File | null>(null);
  const [roads, setRoads] = useState<File | null>(null);
  const [provider, setProvider] = useState("");
  const [preview, setPreview] = useState<SceneDataPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [restoreConfirm, setRestoreConfirm] = useState(false);
  const [cadBusy, setCadBusy] = useState(false);
  const generation = useRef(0);
  const previewCallback = useRef(onPreview);
  previewCallback.current = onPreview;

  useEffect(() => {
    generation.current++;
    setFarmland(null); setRoads(null); setProvider(""); setPreview(null);
    setBusy(false); setError(""); setRestoreConfirm(false);
    setCadBusy(false);
    previewCallback.current(null);
    return () => { generation.current++; };
  }, [open, sceneId]);

  if (!open || !sceneId) return null;

  function invalidate() { setPreview(null); setError(""); onPreview(null); }

  async function buildPreview() {
    const stamp = generation.current;
    setBusy(true); setError(""); setPreview(null); onPreview(null);
    try {
      const value = await previewSceneData(sceneId!, dataImportBody(farmland, roads, provider));
      const roadPreview = value.roads ? await getRoadPreview(sceneId!, value.token) : null;
      if (stamp !== generation.current) return;
      setPreview(value);
      onPreview({ roads: roadPreview, farmlandUrl: value.farmland
        ? `/api/v1/scenes/${encodeURIComponent(sceneId!)}/data-import/preview/${value.token}/farmland.png` : null });
    } catch (reason) {
      if (stamp === generation.current) setError(reason instanceof Error ? reason.message : "预览失败");
    } finally { if (stamp === generation.current) setBusy(false); }
  }

  async function publish(restore = false) {
    if (!restore && !preview) return;
    const stamp = generation.current;
    setBusy(true); setError("");
    try {
      if (restore) await restoreOsmRoads(sceneId!);
      else await confirmSceneData(sceneId!, preview!.token);
      if (stamp !== generation.current) return;
      onPreview(null);
      onCommitted(restore ? "已恢复该场景登记的 OSM 道路。" : "已导入所选数据，正在刷新图层并重新评价当前方案。");
      onClose();
    } catch (reason) {
      if (stamp === generation.current) setError(reason instanceof Error ? reason.message : "发布失败");
    } finally { if (stamp === generation.current) setBusy(false); }
  }

  const area = preview?.farmland?.area_m2 ?? 0;
  const processing = busy || cadBusy;
  return <div className="scene-build-backdrop" onClick={() => { if (!processing) onClose(); }}>
    <section className="scene-build-dialog farmland-import-dialog" role="dialog" aria-modal="true" aria-label="导入数据"
      onClick={(event) => event.stopPropagation()} onKeyDown={(event) => { if (event.key === "Escape" && !processing) onClose(); }}>
      <div className="scene-build-head"><div><h2>导入数据</h2><p>{sceneTitle} · CAD 选择后保存，道路和永农确认后更新</p></div>
        <button type="button" disabled={processing} onClick={onClose}>关闭</button></div>
      <div className="scene-build-body">
        <CadImportPanel key={sceneId} sceneId={sceneId} disabled={processing} canApply={!hasUnsavedLanduse}
          fieldPolicy={fieldPolicy} onBusy={setCadBusy} onApplied={(message, revision) => onCommitted(message, true, revision)} />
        <label>永久基本农田 ZIP（可选）<input type="file" accept=".zip" disabled={processing}
          onChange={(event) => { invalidate(); setFarmland(event.target.files?.[0] ?? null); }} /></label>
        <label>道路 ZIP / RAR（可选）<input type="file" accept=".zip,.rar" disabled={processing}
          onChange={(event) => { invalidate(); setRoads(event.target.files?.[0] ?? null); }} /></label>
        <label>道路来源名称<input value={provider} disabled={processing} placeholder="例如：高德"
          onChange={(event) => { invalidate(); setProvider(event.target.value); }} /></label>
        <p className="hud-note">压缩包需包含同名 shp、shx、dbf、prj。道路保留在场景内，重建时继续使用。</p>
        <button type="button" disabled={processing || (!farmland && !roads)} onClick={() => void buildPreview()}>生成预览</button>
        {busy && <p role="status">正在处理场景数据，请稍候…</p>}
        {preview?.farmland && <section aria-label="永农预览">
          <h3>永久基本农田</h3><p>源坐标系：{preview.farmland.source_crs}；相交地块 {preview.farmland.intersecting_feature_count} 个</p>
          <p>覆盖面积 {area >= 10000 ? `${(area / 10000).toFixed(2)} 公顷` : `${area} m²`}</p>
          <img className="farmland-preview" alt="永农预览" src={`/api/v1/scenes/${encodeURIComponent(sceneId)}/data-import/preview/${preview.token}/farmland.png`} />
        </section>}
        {preview?.roads && <section aria-label="道路预览"><h3>道路网络</h3>
          <p>来源 {preview.roads.provider}，共 {preview.roads.n_segments} 条线段，已叠加至地图。</p>
          <dl>{["普通道路（可接入）", "匝道（不可接入）", "高速地表段（不可接入）", "隧道（不可接入）"].map((label, kind) =>
            <div key={kind}><dt>{label}</dt><dd>{preview.roads!.segment_kind_counts[String(kind)] ?? 0}</dd></div>)}</dl>
          <p>纳入类别：{Object.entries(preview.roads.import.included_classes).map(([name, count]) => `${name} ${count}`).join("、")}</p>
          <p>排除类别：{preview.roads.import.excluded_classes.join("、")}</p>
          <p>排除记录：{Object.entries(preview.roads.import.excluded_feature_counts).map(([name, count]) => `${name} ${count}`).join("、") || "无"}</p>
        </section>}
        {preview && typeof preview.access_overlap_cells === "number" && <p>现有可接入道路与永农重叠 {preview.access_overlap_cells} 个格子。</p>}
        {preview && <p className="hud-note">预览已叠加到地图，请核对位置后确认。未上传的项目保持原样。</p>}
        {roadProvider !== "osm" && roadProvider !== "" && <div>
          <button type="button" disabled={processing} onClick={() => setRestoreConfirm(true)}>改回 OSM 道路</button>
          {restoreConfirm && <><p>将恢复该场景原始 OSM 道路，永农保持原样。</p>
            <button type="button" disabled={processing} onClick={() => void publish(true)}>确认改回 OSM</button>
            <button type="button" disabled={processing} onClick={() => setRestoreConfirm(false)}>取消</button></>}
        </div>}
        {error && <p className="scene-build-error" role="alert">{error}</p>}
      </div>
      <div className="scene-build-actions"><button type="button" disabled={processing} onClick={onClose}>取消</button>
        <button type="button" className="primary" disabled={processing || !preview} onClick={() => void publish()}>确认导入</button></div>
    </section>
  </div>;
}
