export const MAX_CAD_FILE_BYTES = 80 * 1024 * 1024;

export function cadFileBody(file: File): FormData {
  if (!/\.(dwg|dxf)$/i.test(file.name)) throw new Error("CAD 文件必须为 DWG 或 DXF。");
  if (!file.size) throw new Error("CAD 文件不能为空。");
  if (file.size > MAX_CAD_FILE_BYTES) throw new Error("CAD 文件不能超过 80 MiB。");
  const body = new FormData();
  body.append("file", file);
  return body;
}

export function dataImportBody(farmland: File | null, roads: File | null, provider: string): FormData {
  if (!farmland && !roads) throw new Error("请至少选择一项数据。");
  if (roads && !provider.trim()) throw new Error("请填写道路来源名称。");
  const body = new FormData();
  if (farmland) body.append("farmland", farmland);
  if (roads) {
    body.append("roads", roads);
    body.append("provider", provider.trim());
  }
  return body;
}
