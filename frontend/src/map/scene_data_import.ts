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
