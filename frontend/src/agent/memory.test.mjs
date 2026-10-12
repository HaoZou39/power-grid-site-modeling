import assert from "node:assert/strict";
import { describeMemoryOps, visibleIn } from "../../.tmp-problem-snapshot/agent/memory.js";

const entries = [
  { id: "m1", section: "preference", scene: null, date: "2026-10-12", source: "stated", text: "农田系数 0.3" },
  { id: "m2", section: "scene_note", scene: "cangnan", date: "2026-10-12", source: "inferred", text: "北侧是规划用地" },
];

assert.deepEqual(visibleIn(entries, "cangnan").map((entry) => entry.id), ["m1", "m2"]);
assert.deepEqual(visibleIn(entries, "other").map((entry) => entry.id), ["m1"]);

assert.deepEqual(describeMemoryOps([
  { kind: "remember", section: "command", scene: null, source: "stated", text: "老规矩 = 先跑一遍" },
  { kind: "revise", memory_id: "m1", text: "农田系数 0.25" },
  { kind: "forget", memory_id: "m2" },
  { kind: "forget", memory_id: "m9" },
], entries), [
  "将记下（常用指令，全局）：老规矩 = 先跑一遍",
  "将改写 [m1]：农田系数 0.3 → 农田系数 0.25",
  "将忘掉 [m2]：北侧是规划用地",
  "将忘掉 [m9]：（已不存在）",
]);

console.log("memory assertions passed");
