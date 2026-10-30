import assert from "node:assert/strict";
import proj4 from "proj4";
import { rectToSceneConfig } from "../../.tmp-problem-snapshot/map/scene_rect_select.js";

const utmCrs = (lat, lon) => `EPSG:${(lat >= 0 ? 32600 : 32700) + Math.min(60, Math.floor((lon + 180) / 6) + 1)}`;
const ensure = (crs) => {
  const m = /^EPSG:(326|327)([0-9]{2})$/.exec(crs);
  if (m && !proj4.defs(crs)) proj4.defs(crs, `+proj=utm +zone=${Number(m[2])} ${m[1] === "327" ? "+south" : ""} +datum=WGS84 +units=m +no_defs`);
};
const toUtm = (crs, p) => { ensure(crs); return proj4("EPSG:4326", crs, [p.lng, p.lat]); };

// Wenzhou rectangle: center and UTM side computed independently.
const a = { lng: 120.19, lat: 27.49 };
const b = { lng: 120.21, lat: 27.51 };
const cfg = rectToSceneConfig(a, b);
assert.ok(cfg, "expected a valid config");
assert.ok(Math.abs(cfg.lat - 27.5) < 1e-9, "center lat");
assert.ok(Math.abs(cfg.lon - 120.2) < 1e-9, "center lon");
const crs = utmCrs(cfg.lat, cfg.lon);
const [x1, y1] = toUtm(crs, a);
const [x2, y2] = toUtm(crs, b);
const longSide = Math.max(Math.abs(x1 - x2), Math.abs(y1 - y2));
assert.equal(cfg.sideLengthM % 2, 0, "side must be even");
assert.ok(cfg.sideLengthM >= longSide, `side ${cfg.sideLengthM} must cover long side ${longSide}`);
assert.ok(cfg.sideLengthM < longSide + 2, `side ${cfg.sideLengthM} rounds up to the next even metre`);

// The built square (center ± side/2) covers the dragged rectangle.
const [cx, cy] = toUtm(crs, { lng: cfg.lon, lat: cfg.lat });
for (const [x, y] of [[x1, y1], [x2, y2]]) {
  assert.ok(Math.abs(x - cx) <= cfg.sideLengthM / 2 + 1e-6, "x covered");
  assert.ok(Math.abs(y - cy) <= cfg.sideLengthM / 2 + 1e-6, "y covered");
}

// Non-square rectangle takes the longer UTM dimension of its real corners.
const wide = rectToSceneConfig({ lng: 120.1, lat: 27.5 }, { lng: 120.2, lat: 27.51 });
const tall = rectToSceneConfig({ lng: 120.1, lat: 27.4 }, { lng: 120.11, lat: 27.5 });
assert.ok(wide && tall);
const dims = (c, p, q) => {
  const crs2 = utmCrs(c.lat, c.lon);
  const [px, py] = toUtm(crs2, p);
  const [qx, qy] = toUtm(crs2, q);
  return [Math.abs(px - qx), Math.abs(py - qy)];
};
const [wdx, wdy] = dims(wide, { lng: 120.1, lat: 27.5 }, { lng: 120.2, lat: 27.51 });
assert.ok(wdx > wdy && wide.sideLengthM >= wdx && wide.sideLengthM < wdx + 2, "wide takes dx");
const [tdx, tdy] = dims(tall, { lng: 120.1, lat: 27.4 }, { lng: 120.11, lat: 27.5 });
assert.ok(tdy > tdx && tall.sideLengthM >= tdy && tall.sideLengthM < tdy + 2, "tall takes dy");

// Clamp to the 20 km ceiling.
const huge = rectToSceneConfig({ lng: 120.0, lat: 27.0 }, { lng: 120.4, lat: 27.4 });
assert.equal(huge.sideLengthM, 20000);

// Degenerate and out-of-range rectangles are rejected.
assert.equal(rectToSceneConfig({ lng: 120.1, lat: 27.5 }, { lng: 120.1, lat: 27.5 }), null);
assert.equal(rectToSceneConfig({ lng: 120.1, lat: 90 }, { lng: 120.2, lat: 91 }), null);
assert.equal(rectToSceneConfig({ lng: Number.NaN, lat: 27.5 }, { lng: 120.2, lat: 27.6 }), null);

// Southern hemisphere picks EPSG:327xx and still produces a valid metric side.
const south = rectToSceneConfig({ lng: 120.19, lat: -27.51 }, { lng: 120.21, lat: -27.49 });
assert.ok(south);
assert.equal(utmCrs(south.lat, south.lon), "EPSG:32751");
assert.ok(south.sideLengthM >= 2 && south.sideLengthM % 2 === 0);

console.log("scene rect select: center, UTM side, coverage, clamp, rejection, hemisphere passed");
