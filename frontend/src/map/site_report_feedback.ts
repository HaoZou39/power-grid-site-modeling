export function siteReportFailureNotice(selectedIndex: number, reason: unknown): string {
  const detail = reason instanceof Error ? reason.message : "未知错误";
  return `方案 ${selectedIndex + 1} 运输路线计算失败：${detail}`;
}
