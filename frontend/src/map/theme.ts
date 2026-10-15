export type MapTheme = "dark" | "light";

const KEY = "site-map-theme";

type ThemeStore = Pick<Storage, "getItem" | "setItem">;

export function readMapTheme(storage: ThemeStore): MapTheme {
  return storage.getItem(KEY) === "light" ? "light" : "dark";
}

export function writeMapTheme(storage: ThemeStore, theme: MapTheme): void {
  storage.setItem(KEY, theme);
}

export function toggleMapTheme(theme: MapTheme): MapTheme {
  return theme === "light" ? "dark" : "light";
}
