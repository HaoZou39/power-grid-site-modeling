import assert from "node:assert/strict";
import { readMapTheme, toggleMapTheme, writeMapTheme } from "../../.tmp-problem-snapshot/map/theme.js";

const store = new Map();
const storage = {
  getItem: (key) => store.get(key) ?? null,
  setItem: (key, value) => store.set(key, value),
};

assert.equal(readMapTheme(storage), "dark");
writeMapTheme(storage, "light");
assert.equal(readMapTheme(storage), "light");
writeMapTheme(storage, "dark");
assert.equal(readMapTheme(storage), "dark");
storage.setItem("site-map-theme", "other");
assert.equal(readMapTheme(storage), "dark");
assert.equal(toggleMapTheme("dark"), "light");
assert.equal(toggleMapTheme("light"), "dark");

console.log("theme assertions passed");
