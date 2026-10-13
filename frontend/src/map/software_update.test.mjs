import assert from "node:assert/strict";
import { UPDATE_START_TIMEOUT_MS, canSubmitUpdate, reduceUpdatePoll } from "../../.tmp-problem-snapshot/map/software_update.js";

assert.equal(canSubmitUpdate(""), false);
assert.equal(canSubmitUpdate("secret"), true);

const waiting = { id: "run-1", phase: "waiting", message: "即将更新，页面会断开。内存中的任务会被清空。", startedAt: 0 };
const older = { id: "old", updating: false, result: "succeeded", message: "上一回", commit: "aaa" };
assert.equal(reduceUpdatePoll(waiting, older, 1_000).phase, "waiting");
assert.equal(reduceUpdatePoll(waiting, null, 1_000).message.includes("断开"), true);

// The script never wrote this run's id: give up instead of waiting forever.
const never = reduceUpdatePoll(waiting, older, UPDATE_START_TIMEOUT_MS + 1);
assert.equal(never.phase, "failed");
assert.ok(never.message.includes("update.log"));
assert.equal(reduceUpdatePoll(waiting, null, UPDATE_START_TIMEOUT_MS + 1).phase, "waiting");
assert.equal(reduceUpdatePoll(waiting, { ...older, updating: true }, UPDATE_START_TIMEOUT_MS + 1).phase, "waiting");

const started = { id: "run-1", updating: true, result: null, message: "正在拉取", commit: "aaa" };
assert.equal(reduceUpdatePoll(waiting, started, 1_000).phase, "waiting");
assert.equal(reduceUpdatePoll(waiting, started, 1_000).message, "正在拉取");

const done = { id: "run-1", updating: false, result: "succeeded", message: "已拉取远端并重新启动。", commit: "bbb" };
assert.equal(reduceUpdatePoll(waiting, done, 1_000).phase, "succeeded");

const rolled = { id: "run-1", updating: false, result: "rolled_back", message: "已退回", commit: "aaa" };
assert.equal(reduceUpdatePoll(waiting, rolled, 1_000).phase, "rolled_back");
assert.equal(reduceUpdatePoll(waiting, rolled, 1_000).message, "已退回");

console.log("software update assertions passed");
