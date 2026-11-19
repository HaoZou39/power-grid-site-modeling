import { useEffect, useLayoutEffect, useRef } from "react";
import type { FilterSnapshot } from "./filter_snapshot.js";

export type FilterCaseSource = {
  total: number; retained: number; hasFilter: boolean; capture: () => FilterSnapshot;
};

/** Publish availability, while capture always reads the latest ranking without a render loop. */
export function useFilterCaseSource(sourceKey: string, source: FilterCaseSource | null,
  onChange?: (source: FilterCaseSource | null) => void) {
  const latest = useRef(source);
  useLayoutEffect(() => { latest.current = source; });
  const total = source?.total, retained = source?.retained, hasFilter = source?.hasFilter;
  useEffect(() => {
    onChange?.(total === undefined ? null : { total, retained: retained!, hasFilter: hasFilter!, capture: () => {
      if (!latest.current) throw new Error("当前筛选结果已失效。");
      return latest.current.capture();
    } });
    return () => onChange?.(null);
  }, [sourceKey, total, retained, hasFilter, onChange]);
}
