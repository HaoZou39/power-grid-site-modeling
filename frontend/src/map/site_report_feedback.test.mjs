import assert from "node:assert/strict";

import { siteReportFailureNotice } from "../../.tmp-problem-snapshot/map/site_report_feedback.js";

assert.equal(
  siteReportFailureNotice(11, new Error("site cell is not buildable")),
  "方案 12 运输路线计算失败：site cell is not buildable",
);
assert.equal(siteReportFailureNotice(0, "failed"), "方案 1 运输路线计算失败：未知错误");

console.log("site report feedback assertions passed");
