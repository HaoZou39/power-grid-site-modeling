import assert from "node:assert/strict";
import { SiteFrame } from "../../.tmp-problem-snapshot/map/site_frame.js";
import {
  bearingToTheta,
  favoritePointPose,
  favoritePoseInsideFrame,
  normalizeDegrees,
  thetaToBearing,
  favoritePoseSnapshot,
  favoriteMatches,
} from "../../.tmp-problem-snapshot/map/favorite_points.js";

const frame = new SiteFrame(13379105, 3187189, 1, -1, 200, 200);
const northSouth = bearingToTheta(0, 77, 51.5);
assert.ok(Math.abs(Math.cos(northSouth)) < 1e-12);
assert.ok(Math.abs(Math.sin(northSouth) + 1) < 1e-12);
assert.equal(thetaToBearing(northSouth, 77, 51.5), 0);
assert.equal(normalizeDegrees(-10), 350);
assert.equal(normalizeDegrees(720), 0);

const northSouthTall = bearingToTheta(0, 51.5, 77);
assert.ok(Math.abs(northSouthTall - Math.PI) < 1e-12);
assert.equal(thetaToBearing(northSouthTall, 51.5, 77), 0);

const center = { x: 100, y: 100 };
assert.equal(favoritePoseInsideFrame(center, northSouth, 77, 51.5, frame), true);
assert.equal(favoritePoseInsideFrame({ x: 10, y: 10 }, northSouth, 77, 51.5, frame), false);

const point = frame.localToLngLat(center);
const favorite = {
  id: "favorite-1",
  scene_id: "cangnan",
  longitude: point.lng,
  latitude: point.lat,
  width_m: 77,
  height_m: 51.5,
  bearing_deg: 0,
  created_at: "",
  updated_at: "",
};
const pose = favoritePointPose(favorite, frame);
assert.ok(Math.abs(pose.center.x - center.x) < 1e-6);
assert.ok(Math.abs(pose.center.y - center.y) < 1e-6);
assert.ok(Math.abs(Math.cos(pose.theta)) < 1e-12);
assert.ok(Math.abs(Math.sin(pose.theta) + 1) < 1e-12);

const rotated = favoritePoseSnapshot(center, 0.73, 77, 51.5, frame);
assert.equal(rotated.width_m, 77);
assert.equal(rotated.height_m, 51.5);
assert.ok(Math.abs(bearingToTheta(rotated.bearing_deg, 77, 51.5) - 0.73) < 1e-12);
assert.equal(rotated.longitude, favorite.longitude);
assert.equal(rotated.latitude, favorite.latitude);
const saved = { ...favorite, ...rotated, scene_id: "new-scene" };
assert.equal(favoriteMatches(saved, "new-scene", rotated), true);
assert.equal(favoriteMatches(saved, "cangnan", rotated), false);
assert.equal(favoriteMatches(saved, "new-scene", { ...rotated, width_m: 80 }), false);
assert.equal(favoriteMatches(saved, "new-scene", { ...rotated, bearing_deg: 0 }), false);
console.log("favorite_points assertions passed");
