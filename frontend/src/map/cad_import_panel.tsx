import { useEffect, useRef, useState } from "react";
import { addCadFile, clearCadLanduse, confirmCadLanduse, getCadFiles, inspectCadFile, previewCadLanduse } from "../api";
import type { CadFileRecord, CadInspection, CadKind, CadLandusePreview } from "../api";
import { cadFileBody } from "./scene_data_import";
import type { FieldPolicy } from "./site_edit";

const KINDS: [CadKind, string][] = [["building", "建筑"], ["field", "农田"], ["road", "道路区域"], ["water", "水体"], ["ignore", "忽略"]];

export function CadImportPanel({ sceneId, disabled, canApply, fieldPolicy, onBusy, onApplied }: {
  sceneId: string; disabled: boolean; canApply: boolean; fieldPolicy: FieldPolicy;
  onBusy: (busy: boolean) => void; onApplied: (message: string, revision?: string) => void;
}) {
  const [files, setFiles] = useState<CadFileRecord[]>([]);
  const [selected, setSelected] = useState<CadFileRecord | null>(null);
  const [inspection, setInspection] = useState<CadInspection | null>(null);
  const [mapping, setMapping] = useState<Record<string, CadKind | "">>({});
  const [crs, setCrs] = useState("");
  const [preview, setPreview] = useState<CadLandusePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    getCadFiles(sceneId, controller.signal).then((value) => {
      if (!controller.signal.aborted) setFiles(value);
    }).catch((reason) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "CAD 文件列表读取失败");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { alive.current = false; controller.abort(); onBusy(false); };
  }, [sceneId, onBusy]);

  async function run(action: () => Promise<void>) {
    setBusy(true); onBusy(true); setError(""); setNotice("");
    try { await action(); }
    catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : "CAD 处理失败"); }
    finally { if (alive.current) { setBusy(false); onBusy(false); } }
  }

  function inspect(file: CadFileRecord) {
    setSelected(file); setInspection(null); setPreview(null); setMapping({}); setCrs("");
    void run(async () => {
      const value = await inspectCadFile(sceneId, file.id);
      if (!alive.current) return;
      setInspection(value);
      setMapping(Object.fromEntries(value.layers.map((layer) => [layer.name, layer.polygon_count ? layer.suggested_kind ?? "" : "ignore"])));
    });
  }

  const locked = disabled || busy || loading;
  const hasAreas = inspection?.layers.some((layer) => layer.polygon_count > 0) ?? false;
  const mappingReady = inspection?.layers.every((layer) => !!mapping[layer.name]) ?? false;
  return <section aria-label="CAD 文件">
    <h3>CAD 文件</h3>
    <input ref={input} type="file" accept=".dwg,.dxf" hidden disabled={locked} onChange={(event) => {
      const file = event.target.files?.[0]; event.target.value = "";
      if (file) void run(async () => {
        const record = await addCadFile(sceneId, cadFileBody(file));
        if (alive.current) { setFiles((items) => [record, ...items]); setNotice(`已添加 CAD 文件：${record.source_name}`); }
      });
    }} />
    <button type="button" disabled={locked} onClick={() => input.current?.click()}>添加CAD文件</button>
    <p className="hud-note">支持 DWG / DXF，最大 80 MiB。选择后保存附件；识别并确认应用后才更新地图用地与建设可行性。</p>
    {loading && <p role="status">正在读取 CAD 文件列表…</p>}
    {busy && <p role="status">正在处理 CAD，请稍候…</p>}
    {files.length > 0 && <ul className="cad-file-list" aria-label="已添加的 CAD 文件">{files.map((file) =>
      <li key={file.id}><span>{file.source_name} · {(file.size_bytes / 1024).toFixed(1)} KiB{file.active ? " · 当前分类来源" : " · 已添加"}</span>
        <button type="button" disabled={locked} onClick={() => inspect(file)}>识别用地图层</button></li>)}</ul>}
    {files.some((file) => file.active) && <button type="button" disabled={locked || !canApply} onClick={() => void run(async () => {
      const result = await clearCadLanduse(sceneId);
      if (!alive.current) return;
      setFiles((items) => items.map((file) => ({ ...file, active: false }))); setPreview(null);
      onApplied("已撤销 CAD 分类，原始用地和人工修正继续生效。", result.scene_revision);
    })}>撤销 CAD 分类</button>}
    {selected && inspection && <section aria-label="CAD 用地识别">
      <h4>{selected.source_name}</h4>
      <p className="hud-note">按图层名称建议类别。请核对，并为未知图层选择类别或忽略；文字、标注不参与分类。</p>
      <div className="cad-layer-list">{inspection.layers.map((layer) => <label key={layer.name}>
        <span>{layer.name} · {layer.polygon_count} 个面{layer.open_line_count > 0 ? ` · ${layer.open_line_count} 条未闭合线` : ""}
          {layer.invalid_count > 0 ? ` · ${layer.invalid_count} 个无效对象` : ""}
          {layer.unsupported_count > 0 ? ` · ${layer.unsupported_count} 个不支持对象` : ""}</span>
        <select aria-label={`${layer.name} 用地类别`} value={mapping[layer.name] ?? ""} disabled={locked || !layer.polygon_count}
          onChange={(event) => { setMapping((value) => ({ ...value, [layer.name]: event.target.value as CadKind })); setPreview(null); }}>
          <option value="">请选择类别</option>{KINDS.map(([kind, title]) => <option key={kind} value={kind}>{title}</option>)}
        </select>
      </label>)}</div>
      {!hasAreas && <p role="status">未读到可用于分类的闭合地物面。只有边界、文字或未闭合线时，不能自动识别建筑、农田等地物。</p>}
      <label>CAD 源坐标系<input value={crs} disabled={locked} placeholder="例如 EPSG:4549，请向数据提供方核实"
        onChange={(event) => { setCrs(event.target.value); setPreview(null); }} /></label>
      <p className="hud-note">坐标按所填坐标系的单位解释，不依据图纸单位标签自动缩放。仅处理与当前场景重叠的区域。</p>
      <button type="button" disabled={locked || !hasAreas || !mappingReady || !crs.trim()} onClick={() => void run(async () => {
        setPreview(null);
        const value = await previewCadLanduse(sceneId, selected.id, crs, mapping as Record<string, CadKind>);
        if (alive.current) setPreview(value);
      })}>生成 CAD 用地预览</button>
      {inspection.warnings.map((warning, index) => <p className="hud-note" key={index}>{warning}</p>)}
      {preview && <section aria-label="CAD 分类预览">
        <img className="farmland-preview" alt="CAD 用地分类预览" src={`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-files/preview/${preview.token}.png`} />
        <p>覆盖 {preview.covered_area_m2} m²；{KINDS.filter(([kind]) => kind !== "ignore").map(([kind, title]) => `${title} ${preview.cell_counts[kind] ?? 0} m²`).join("，")}</p>
        <p className="hud-note">图斑颜色与土地利用图层一致。将替换上一份 CAD 分类，人工修正保留。农田沿用当前策略：{fieldPolicy === "blocked" ? "不可建设" : fieldPolicy === "costly" ? "可建并计成本" : "允许建设"}。完整站址仍须通过退距等现有约束。</p>
        <button type="button" className="primary" disabled={locked || !canApply} onClick={() => void run(async () => {
          const result = await confirmCadLanduse(sceneId, preview.token);
          if (!alive.current) return;
          setFiles((items) => items.map((file) => ({ ...file, active: file.id === selected.id }))); setPreview(null);
          onApplied("已应用 CAD 用地分类，正在刷新建设可行性；农田策略保持原设置。旧方案需重新评价。", result.scene_revision);
        })}>应用 CAD 分类</button>
      </section>}
      {!canApply && <p className="hud-note">请先保存或放弃未提交的土地类型修改，再应用或撤销 CAD 分类。</p>}
    </section>}
    {notice && <p role="status">{notice}</p>}
    {error && <p className="scene-build-error" role="alert">{error}</p>}
  </section>;
}
