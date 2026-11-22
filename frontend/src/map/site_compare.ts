/** Shared by the site comparison chart and map footprints, in comparison insertion order. */
const SITE_COMPARE_COLORS = ["#39f3ff", "#ff8b96", "#ffd166", "#3dd68c", "#d78bff"] as const;

export function siteCompareColor(index: number): string {
  return SITE_COMPARE_COLORS[index % SITE_COMPARE_COLORS.length];
}
