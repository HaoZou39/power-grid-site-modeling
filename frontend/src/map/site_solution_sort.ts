import { NOT_PROVIDED } from "../solution_record.js";
import { STALE, UNMEASURED, type ParetoChoice } from "./decision_run.js";

export type SiteSortKey = "demSoft" | "offroadHaul" | "haulRise" | "roadHaul" | "demandDistance";

export type SiteSort = {
  objective: SiteSortKey;
  direction: "ascending" | "descending";
};

/** Display strings keep three decimals from `formatObjective`. Sort uses that number, not the rounded label text. */
export function siteObjectiveValue(text: string): number | null {
  if (!text.trim() || text === STALE || text === UNMEASURED || text === NOT_PROVIDED) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

export function nextSiteSort(current: SiteSort | null, objective: SiteSortKey): SiteSort {
  return {
    objective,
    direction: current?.objective === objective && current.direction === "ascending" ? "descending" : "ascending",
  };
}

export function sortSiteSolutions(choices: readonly ParetoChoice[], sort: SiteSort | null) {
  const rows = choices.map((choice, index) => ({ choice, index }));
  if (!sort) return rows;
  return rows.slice().sort((left, right) => {
    const leftValue = siteObjectiveValue(String(left.choice[sort.objective]));
    const rightValue = siteObjectiveValue(String(right.choice[sort.objective]));
    if (leftValue === null && rightValue === null) return left.index - right.index;
    if (leftValue === null) return 1;
    if (rightValue === null) return -1;
    const difference = leftValue - rightValue;
    return (sort.direction === "ascending" ? difference : -difference) || left.index - right.index;
  });
}
