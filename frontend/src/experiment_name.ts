function safeSceneName(name: string): string {
  return name.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").trim().slice(0, 80) || "场景";
}

export function siteExperimentName(scene: string, width: number, height: number): string {
  return `${safeSceneName(scene)}_变电站_${width}×${height}m`;
}

export function routingExperimentName(scene: string, start: { lng: number; lat: number }, end: { lng: number; lat: number }): string {
  const point = (value: { lng: number; lat: number }) => `${value.lng.toFixed(6)},${value.lat.toFixed(6)}`;
  return `${safeSceneName(scene)}_起点${point(start)}_终点${point(end)}`;
}
