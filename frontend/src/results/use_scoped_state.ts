import { useState } from "react";

/** Keep view-specific edits until the underlying result is replaced. */
export function useScopedState<T>(source: unknown, scope: string, initial: T) {
  const [stored, setStored] = useState<{ source: unknown; values: Record<string, T> }>({ source, values: {} });
  const values = stored.source === source ? stored.values : {};
  if (stored.source !== source) setStored({ source, values });
  const value = values[scope] ?? initial;
  const update = (change: (current: T) => T) => setStored((current) => {
    const entries = current.source === source ? current.values : {};
    return { source, values: { ...entries, [scope]: change(entries[scope] ?? initial) } };
  });
  return [value, update] as const;
}
