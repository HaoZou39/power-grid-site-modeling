import assert from "node:assert/strict";
import { batches, evaluationKey, poseFreshness, autoPendingPoses } from "../../.tmp-problem-snapshot/map/pose_evaluation.js";
import {
  PARETO_LAYER_NOTE,
  afterLandusePublish,
  computeFailedAfterSave,
  computeStoppedNotice,
  createActionGate,
  revisionReady,
  siteReportAllowed,
} from "../../.tmp-problem-snapshot/map/landuse_compute.js";
import { retainLanduseDraft } from "../../.tmp-problem-snapshot/map/landuse_draft.js";

function pose(id, layer, revision, x = 1) {
  const body = { x, y: 2, theta: 0 };
  return { id, layer, x, y: 2, theta: 0, manual: false, evaluatedFor: evaluationKey("scene", { scene_revision: revision }, body) };
}

function freshness(item, revision) {
  return poseFreshness(item.evaluatedFor, "scene", { scene_revision: revision }, item);
}

function reviewBatches(items, revision) {
  const waiting = items.filter((item) => freshness(item, revision) === "revision-stale" || freshness(item, revision) === "zone-stale" || freshness(item, revision) === "history-stale");
  return batches(waiting);
}

const log = [];
function reset() { log.length = 0; }

async function clientPublish(draft, server) {
  if (!draft.dirty) return { status: "unchanged", sceneRevision: server.revision };
  if (server.fail === "conflict") return { status: "conflict" };
  if (server.fail === "publish") return { status: "failed", message: "写入失败" };
  log.push("batch");
  server.revision = server.nextRevision;
  server.batches += 1;
  draft.dirty = false;
  return { status: "published", sceneRevision: server.revision };
}

async function clickReview(draft, server, poses, seen) {
  const gate = seen.gate;
  const result = await gate.run("review", () => afterLandusePublish({
    publish: () => clientPublish(draft, server),
    sceneRevision: () => server.revision,
    run: async () => {
      const groups = reviewBatches(poses, server.revision);
      log.push(`pose:${groups.map((group) => group.length).join("+") || "0"}`);
      if (server.fail === "score") throw new Error("评价失败");
      for (const group of groups) {
        for (const item of group) {
          item.evaluatedFor = evaluationKey("scene", { scene_revision: server.revision }, item);
        }
      }
      const selected = poses[0];
      log.push(siteReportAllowed(false, freshness(selected, server.revision)) ? "report" : "report-blocked");
      return groups;
    },
  }));
  return result;
}

async function clickOptimize(draft, server, seen) {
  return seen.gate.run("optimize", () => afterLandusePublish({
    publish: () => clientPublish(draft, server),
    sceneRevision: () => server.revision,
    run: async () => {
      if (server.fail === "job") throw new Error("任务失败");
      log.push("job");
      server.jobs += 1;
      return true;
    },
  }));
}

const layers = [1, 2, 3];
let poses = layers.map((layer, index) => pose(`p${index + 1}`, layer, "v1"));
assert.deepEqual(poses.map((item) => item.layer), [1, 2, 3]);
let server = { revision: "v1", nextRevision: "v2", batches: 0, jobs: 0, fail: "" };
let draft = { dirty: false };
let seen = { gate: createActionGate() };
reset();
await clickOptimize(draft, server, seen);
assert.deepEqual(log, ["job"]);
assert.equal(server.batches, 0);

draft = { dirty: true };
server = { revision: "v1", nextRevision: "v2", batches: 0, jobs: 0, fail: "" };
seen = { gate: createActionGate() };
reset();
const blank = await clickOptimize(draft, server, seen);
assert.equal(blank.skipped, false);
assert.deepEqual(log, ["batch", "job"]);
assert.equal(server.batches, 1);
assert.equal(server.jobs, 1);
assert.equal(log.includes("pose:0"), false);

poses = layers.map((layer, index) => pose(`p${index + 1}`, layer, "v1"));
draft = { dirty: false };
server = { revision: "v1", nextRevision: "v2", batches: 0, jobs: 0, fail: "" };
seen = { gate: createActionGate() };
reset();
await clickReview(draft, server, poses, seen);
assert.deepEqual(log, ["pose:0", "report"]);
assert.equal(server.batches, 0);

poses = [pose("a", 1, "v1"), pose("b", 2, "v1"), pose("c", 3, "v1")];
draft = { dirty: true };
server = { revision: "v1", nextRevision: "v2", batches: 0, jobs: 0, fail: "" };
seen = { gate: createActionGate() };
reset();
assert.equal(poses.every((item) => freshness(item, "v1") === "current"), true);
const reviewed = await clickReview(draft, server, poses, seen);
assert.equal(reviewed.skipped, false);
assert.equal(log[0], "batch");
assert.equal(log[1], "pose:3");
assert.equal(log[2], "report");
assert.equal(server.batches, 1);
assert.deepEqual(poses.map((item) => item.id), ["a", "b", "c"]);
assert.equal(poses.every((item) => freshness(item, "v2") === "current"), true);
assert.equal(autoPendingPoses(poses, (item) => evaluationKey("scene", { scene_revision: "v2" }, item), new Set(), new Map(), (item) => freshness(item, "v2")).length, 0);

draft = { dirty: true };
server = { revision: "v1", nextRevision: "v1", batches: 0, jobs: 0, fail: "" };
const unchangedPublish = async () => {
  log.push("batch");
  draft.dirty = false;
  return { status: "unchanged", sceneRevision: "v1" };
};
poses = [pose("zoned", 1, "v1")];
poses[0].evaluatedFor = evaluationKey("scene", { scene_revision: "v1", exclusion_zones: [1] }, poses[0]);
reset();
await afterLandusePublish({
  publish: unchangedPublish,
  sceneRevision: () => server.revision,
  run: async () => {
    const waiting = poses.filter((item) => freshness(item, "v1") === "zone-stale");
    log.push(`pose:${waiting.length}`);
  },
});
assert.deepEqual(log, ["batch", "pose:1"]);
assert.equal(freshness(pose("kept", 1, "v1"), "v1"), "current");

server = { revision: "v1", nextRevision: "v9", batches: 0, jobs: 0, fail: "conflict" };
draft = { dirty: true };
poses = [pose("a", 1, "v1")];
reset();
const conflicted = await clickReview(draft, server, poses, { gate: createActionGate() });
assert.equal(conflicted.skipped, false);
assert.equal(conflicted.value.ran, false);
assert.equal(conflicted.value.outcome.status, "conflict");
assert.deepEqual(log, []);
assert.equal(computeStoppedNotice("重新评价", conflicted.value.outcome), "场景版本冲突，未开始重新评价。土地类型修改仍保留。");
assert.equal(draft.dirty, true);

server.fail = "publish";
reset();
const failed = await clickOptimize(draft, server, { gate: createActionGate() });
assert.equal(failed.value.ran, false);
assert.equal(log.length, 0);
assert.match(computeStoppedNotice("优化", failed.value.outcome), /未开始优化/);

server = { revision: "v1", nextRevision: "v2", batches: 0, jobs: 0, fail: "score" };
draft = { dirty: true };
reset();
await assert.rejects(() => clickReview(draft, server, [pose("a", 1, "v1")], { gate: createActionGate() }));
assert.deepEqual(log, ["batch", "pose:1"]);
assert.equal(server.batches, 1);
server.fail = "";
draft = { dirty: false };
reset();
await clickReview(draft, server, [pose("a", 2, "v2")], { gate: createActionGate() });
assert.equal(log.filter((item) => item === "batch").length, 0);

server = { revision: "v1", nextRevision: "v2", batches: 0, jobs: 0, fail: "job" };
draft = { dirty: true };
reset();
await assert.rejects(() => clickOptimize(draft, server, { gate: createActionGate() }));
assert.deepEqual(log, ["batch"]);
server.fail = "";
draft = { dirty: false };
reset();
await clickOptimize(draft, server, { gate: createActionGate() });
assert.equal(log.filter((item) => item === "batch").length, 0);
assert.equal(computeFailedAfterSave("优化"), "土地类型已保存，但优化任务没有启动。");
assert.equal(computeFailedAfterSave("重新评价"), "土地类型已保存，但重新评价失败。");

const gate = createActionGate();
let releases = 0;
const first = gate.run("optimize", () => new Promise((resolve) => { releases = resolve; }));
const second = await gate.run("review", async () => "again");
assert.equal(second.skipped, true);
releases("ok");
assert.equal((await first).skipped, false);

const many = Array.from({ length: 133 }, (_, index) => pose(`s${index}`, (index % 3) + 1, "v1"));
draft = { dirty: true };
server = { revision: "v1", nextRevision: "v2", batches: 0, jobs: 0, fail: "" };
reset();
await clickReview(draft, server, many, { gate: createActionGate() });
assert.equal(log[1], "pose:133");
const wide = Array.from({ length: 201 }, (_, index) => pose(`w${index}`, 1, "v1", index));
assert.deepEqual(reviewBatches(wide, "v2").map((group) => group.length), [200, 1]);
assert.equal(wide.every((item) => freshness(item, "v2") === "revision-stale"), true);

let visible = "v1";
const late = await afterLandusePublish({
  publish: async () => ({ status: "published", sceneRevision: "v2" }),
  sceneRevision: () => visible,
  run: async () => log.push("pose"),
});
assert.equal(late.ran, false);
assert.equal(late.outcome.status, "failed");
assert.equal(revisionReady({ status: "published", sceneRevision: "v2" }, "v2"), true);

const base = { scene_revision: "v1", landuse_revision: 1 };
const stored = { x: 4, y: 5, theta: 0, evaluatedFor: evaluationKey("scene", base, { x: 4, y: 5, theta: 0 }) };
assert.equal(poseFreshness(stored.evaluatedFor, "scene", { scene_revision: "v2", landuse_revision: 2 }, stored), "revision-stale");
assert.equal(autoPendingPoses([stored], (item) => evaluationKey("scene", { scene_revision: "v2", landuse_revision: 2 }, item), new Set(), new Map(), () => "revision-stale").length, 0);
assert.equal(poseFreshness(stored.evaluatedFor, "scene", { scene_revision: "v2", farmland_content_sha256: "next" }, stored), "pending");
assert.equal(siteReportAllowed(true, "current"), false);
assert.equal(siteReportAllowed(false, "revision-stale"), false);
assert.equal(siteReportAllowed(false, "current"), true);
const keptDraft = { dirty: true };
assert.equal(retainLanduseDraft(keptDraft), keptDraft);
assert.match(PARETO_LAYER_NOTE, /尚未重新分层/);

const started = Date.now();
await afterLandusePublish({
  publish: () => new Promise((resolve) => setTimeout(() => resolve({ status: "published", sceneRevision: "v2" }), 30)),
  sceneRevision: () => "v2",
  run: () => new Promise((resolve) => setTimeout(resolve, 20)),
});
const elapsed = Date.now() - started;
assert.ok(elapsed >= 50);
console.log(`PERF publish_then_score_ms=${elapsed}`);
console.log("landuse compute trigger: passed");
