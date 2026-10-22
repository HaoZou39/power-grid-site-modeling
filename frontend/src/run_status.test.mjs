import assert from "node:assert/strict";
import {
  configSummary,
  failurePresentation,
  isConfigOnlyResult,
  progressRatio,
  runExperimentName,
  shouldPoll,
  stageLabel,
} from "../.tmp-problem-snapshot/run_status.js";

assert.equal(shouldPoll("queued"), true);
assert.equal(shouldPoll("running"), true);
assert.equal(shouldPoll("succeeded"), false);
assert.equal(shouldPoll("failed"), false);
assert.equal(progressRatio(1.4), 1);
assert.equal(progressRatio(Number.NaN), 0);
assert.equal(runExperimentName({}), "未提供");
assert.equal(runExperimentName({ experiment_name: " cmaes " }), "cmaes");
assert.equal(stageLabel("validated"), "已校验配置");
assert.equal(stageLabel("generating_data"), "正在生成数据");
assert.equal(stageLabel("validating_data"), "正在校验数据");
assert.equal(stageLabel("rebuilding_scene"), "正在重建场景");
assert.equal(stageLabel("ready"), "场景已就绪");
assert.equal(stageLabel("custom-stage"), "custom-stage");

const summary = configSummary({ seed: 42, rect_w_m: 80, extra_flag: true });
assert.deepEqual(summary, [
  { label: "随机 seed", value: "42" },
  { label: "建筑矩形宽度（m）", value: "80" },
  { label: "extra_flag", value: "是" },
]);

const hidden = failurePresentation({
  message: "Job failed",
  error: { message: "boom", traceback: "Traceback (most recent call last):\n  File \"x.py\", line 1" },
});
assert.equal(hidden.summary, "boom");
assert.match(hidden.technical ?? "", /Traceback/);
assert.equal(hidden.summary.includes("Traceback"), false);

const inline = failurePresentation({
  message: "Traceback (most recent call last):\n  File \"x.py\"",
  error: null,
});
assert.equal(inline.summary, "运行失败。技术细节已折叠。");
assert.match(inline.technical ?? "", /File/);

assert.equal(isConfigOnlyResult({ data: { optimizer_executed: false } }), true);
assert.equal(isConfigOnlyResult({ data: { optimizer_executed: true } }), false);
assert.equal(isConfigOnlyResult(null), false);

console.log("run_status assertions passed");
