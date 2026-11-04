import { useEffect, useRef, useState } from "react";
import { addCadFile, confirmCadFeasible, getCadFiles, inspectCadFile, previewCadFeasible } from "../api";
import type { CadFileRecord, CadInspection, CadFeasiblePreview, CadFeasibleZones } from "../api";
import { cadFileBody } from "./scene_data_import";

export function CadImportPanel({ sceneId, disabled, onBusy, onApplied }: {
  sceneId: string; disabled: boolean;
  onBusy: (busy: boolean) => void; onApplied: (zones: CadFeasibleZones) => void;
}) {
  const [files, setFiles] = useState<CadFileRecord[]>([]);
  const [selected, setSelected] = useState<CadFileRecord | null>(null);
  const [inspection, setInspection] = useState<CadInspection | null>(null);
  const [crs, setCrs] = useState("");
  const [preview, setPreview] = useState<CadFeasiblePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
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
    setBusy(true); onBusy(true); setError("");
    try { await action(); }
    catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : "CAD 处理失败"); }
    finally { if (alive.current) { setBusy(false); onBusy(false); } }
  }

  async function inspect(file: CadFileRecord) {
    setSelected(file); setInspection(null); setPreview(null); setCrs("");
    const value = await inspectCadFile(sceneId, file.id);
    if (alive.current) setInspection(value);
  }

  const locked = disabled || busy || loading;
  const layers = inspection?.layers.filter((layer) => layer.polygon_count || layer.open_line_count || layer.invalid_count || layer.unsupported_count) ?? [];
  const usable = layers.length === 1 && layers[0].polygon_count > 0 && !layers[0].open_line_count && !layers[0].invalid_count && !layers[0].unsupported_count;
  return <section className="import-section" aria-label="CAD 可行域">
    <div className="import-section-head"><h3>CAD 可行域</h3><span>DWG / DXF · 最大 80 MiB</span></div>
    <input ref={input} type="file" accept=".dwg,.dxf" hidden disabled={locked} onChange={(event) => {
      const file = event.target.files?.[0]; event.target.value = "";
      if (file) void run(async () => {
        const record = await addCadFile(sceneId, cadFileBody(file));
        if (!alive.current) return;
        setFiles((items) => [record, ...items]);
        await inspect(record);
      });
    }} />
    {files.length > 0 && <ul className="cad-file-list" aria-label="已添加的 CAD 文件">{files.map((file) =>
      <li key={file.id}>
        <span className="cad-file-name" title={file.source_name}>{file.source_name}</span>
        <span className="cad-file-size">{(file.size_bytes / 1024).toFixed(1)} KiB</span>
        <button type="button" disabled={locked} onClick={() => void run(() => inspect(file))}>生成可行域</button>
      </li>)}</ul>}
    <div className="import-cad-upload">
      <button type="button" disabled={locked} onClick={() => input.current?.click()}>导入 CAD</button>
      <p className="hud-note">根据CAD图层自动生成可行域</p>
    </div>
    <p className="hud-note">选择后保存附件，预览确认后应用范围。</p>
    {loading && <p role="status">正在读取 CAD 文件列表…</p>}
    {busy && <p role="status">正在处理 CAD，请稍候…</p>}
    {selected && inspection && <section aria-label="CAD 可行域导入">
      <h4>{selected.source_name}</h4>
      <div className="cad-layer-list">{layers.map((layer) => <p key={layer.name}>
        {layer.name} · {layer.polygon_count} 个闭合面
        {layer.open_line_count > 0 ? ` · ${layer.open_line_count} 条未闭合线` : ""}
        {layer.invalid_count > 0 ? ` · ${layer.invalid_count} 个无效对象` : ""}
        {layer.unsupported_count > 0 ? ` · ${layer.unsupported_count} 个不支持对象` : ""}
      </p>)}</div>
      {!usable && <p role="alert">需要唯一几何图层中的有效闭合区域，请修正多图层、未闭合或无效图形后重新导入。</p>}
      <label>CAD 源坐标系<input value={crs} disabled={locked} placeholder="例如 EPSG:4549，请向数据提供方核实"
        onChange={(event) => { setCrs(event.target.value); setPreview(null); }} /></label>
      <p className="hud-note">按所填坐标系转换，保留真实轮廓，仅取当前选址区内的部分。</p>
      <button type="button" disabled={locked || !usable || !crs.trim()} onClick={() => void run(async () => {
        setPreview(null);
        const value = await previewCadFeasible(sceneId, selected.id, crs);
        if (alive.current) setPreview(value);
      })}>生成 CAD 可行域预览</button>
      {inspection.warnings.map((warning, index) => <p className="hud-note" key={index}>{warning}</p>)}
      {preview && <section aria-label="CAD 可行域预览">
        <img className="farmland-preview" alt="CAD 可行域轮廓预览" src={`/api/v1/scenes/${encodeURIComponent(sceneId)}/cad-files/preview/${preview.token}.png`} />
        <p>可行域面积 {preview.covered_area_m2.toFixed(1)} m²</p>
        <p className="hud-note">应用后追加 CAD 范围，保留已有可行域和禁区，允许搜索范围取所有可行域的并集，可继续编辑、删除。范围内仍须满足永农、土地及退距等约束；已有方案需重新评价。</p>
        <button type="button" className="primary" disabled={locked} onClick={() => void run(async () => {
          const result = await confirmCadFeasible(sceneId, preview.token);
          if (!alive.current) return;
          setPreview(null);
          onApplied(result.feasible_zones);
        })}>应用 CAD 可行域</button>
      </section>}
    </section>}
    {error && <p className="scene-build-error" role="alert">{error}</p>}
  </section>;
}
