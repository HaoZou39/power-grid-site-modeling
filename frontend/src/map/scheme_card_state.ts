export type SchemeCardSelectionSource = "automatic" | "user";

export function schemeCardShouldOpen(
  source: SchemeCardSelectionSource,
  hasSelection: boolean,
): boolean {
  return source === "user" && hasSelection;
}

export function isSchemeCardVisible(selectedId: string | null, open: boolean): boolean {
  return open && selectedId !== null;
}
