export type RankingDirection = "ascending" | "descending" | "original";
export type RankingStage<Key extends string> = {
  key: Key;
  direction: RankingDirection;
  lower: number;
  upper: number;
};

export type RankingRow<T> = {
  item: T;
  sourceIndex: number;
  state: "active" | "filtered" | "unavailable";
  filteredAt: number | null;
};

export type RankingResult<T> = {
  rows: RankingRow<T>[];
  active: RankingRow<T>[];
  retainedByStage: number[];
  filteredByStage: number[];
};

export const RANKING_STAGE_COLORS = [
  "#00d6c7", "#ff9f1a", "#b48aff", "#ff6b8a", "#59a8ff",
  "#a6d94f", "#ff78d1", "#65c8ff", "#e8c547", "#9a86ff",
] as const;

export function rankingStageColor(round: number): string {
  return RANKING_STAGE_COLORS[(round - 1) % RANKING_STAGE_COLORS.length];
}

export function rankThroughThresholds<T, Key extends string>(
  items: readonly T[], stages: readonly RankingStage<Key>[],
  valueOf: (item: T, key: Key) => number | null,
): RankingResult<T> {
  const rows = items.map((item, sourceIndex): RankingRow<T> => ({
    item, sourceIndex, state: "active", filteredAt: null,
  }));
  let active = rows.slice();
  const retainedByStage: number[] = [];
  const filteredByStage: number[] = [];

  stages.forEach((stage, index) => {
    const round = index + 1;
    active.sort((left, right) => {
      const a = valueOf(left.item, stage.key), b = valueOf(right.item, stage.key);
      if (a === null && b === null) return left.sourceIndex - right.sourceIndex;
      if (a === null) return 1;
      if (b === null) return -1;
      if (stage.direction === "original") return left.sourceIndex - right.sourceIndex;
      return (stage.direction === "ascending" ? a - b : b - a) || left.sourceIndex - right.sourceIndex;
    });
    const next: RankingRow<T>[] = [];
    let filteredCount = 0;
    for (const row of active) {
      const value = valueOf(row.item, stage.key);
      if (value === null) {
        row.state = "unavailable";
      } else if (value >= stage.lower && value <= stage.upper) {
        next.push(row);
      } else {
        row.state = "filtered";
        row.filteredAt = round;
        filteredCount += 1;
      }
    }
    active = next;
    retainedByStage.push(active.length);
    filteredByStage.push(filteredCount);
  });

  const excluded = rows.filter((row) => row.state === "filtered")
    .sort((a, b) => (a.filteredAt ?? 0) - (b.filteredAt ?? 0) || a.sourceIndex - b.sourceIndex);
  const unavailable = rows.filter((row) => row.state === "unavailable").sort((a, b) => a.sourceIndex - b.sourceIndex);
  return { rows: [...active, ...excluded, ...unavailable], active, retainedByStage, filteredByStage };
}

/** Only final retained rows may fill the normally displayed group. */
export function featuredRankingIds<T>(rows: readonly RankingRow<T>[], idOf: (item: T) => string): string[] {
  return rows.filter((row) => row.state === "active").slice(0, 10).map(({ item }) => idOf(item));
}

export function valueExtent<T, Key extends string>(items: readonly T[], key: Key,
  valueOf: (item: T, key: Key) => number | null): { min: number; max: number } | null {
  let min = Infinity, max = -Infinity;
  for (const item of items) {
    const value = valueOf(item, key);
    if (value === null) continue;
    min = Math.min(min, value);
    max = Math.max(max, value);
  }
  return min === Infinity ? null : { min, max };
}

export function valueDistribution<T, Key extends string>(items: readonly T[], key: Key,
  valueOf: (item: T, key: Key) => number | null, min: number, max: number, binCount = 24): number[] {
  const bins = Array.from({ length: binCount }, () => 0);
  for (const item of items) {
    const value = valueOf(item, key);
    if (value === null) continue;
    const index = max === min ? 0 : Math.min(binCount - 1, Math.floor((value - min) / (max - min) * binCount));
    bins[index] += 1;
  }
  return bins;
}

export function sortRankingRows<T, Key extends string>(rows: readonly RankingRow<T>[], key: Key | null,
  direction: RankingDirection, valueOf: (item: T, key: Key) => number | null): RankingRow<T>[] {
  const stateOrder = { active: 0, filtered: 1, unavailable: 2 };
  if (key === null) return [...rows];
  return [...rows].sort((a, b) => stateOrder[a.state] - stateOrder[b.state]
    || compareValues(valueOf(a.item, key), valueOf(b.item, key), direction)
    || a.sourceIndex - b.sourceIndex);
}

function compareValues(a: number | null, b: number | null, direction: RankingDirection): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  if (direction === "original") return 0;
  return direction === "ascending" ? a - b : b - a;
}

