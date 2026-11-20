import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  acceptCaseListResponse,
  siteImportSceneError,
  visibleSavedCases,
} from "../../.tmp-problem-snapshot/map/saved_cases.js";

const cases = [
  { id: "A1", summary: { scene_name: "cangnan", problem_type: "site" } },
  { id: "A2", summary: { scene_name: "cangnan" } },
  { id: "B1", summary: { scene_name: "yongjia", algorithm: "workspace_snapshot" } },
  { id: "R1", summary: { scene_name: "cangnan", problem_type: "routing" } },
  { id: "R2", summary: { scene_name: "yongjia", problem_type: "routing" } },
  { id: "legacy", summary: { display_name: "苍南旧案例" } },
  { id: "blank", summary: { scene_name: "" } },
  { id: "near", summary: { scene_name: "cangnan-utm" } },
];

assert.deepEqual(visibleSavedCases(cases, "site", "cangnan").map((item) => item.id), ["A1", "A2"]);
assert.deepEqual(visibleSavedCases(cases, "site", "yongjia").map((item) => item.id), ["B1"]);
assert.deepEqual(visibleSavedCases(cases, "routing", "cangnan").map((item) => item.id), ["R1"]);
assert.deepEqual(visibleSavedCases(cases, "routing", "yongjia").map((item) => item.id), ["R2"]);
assert.deepEqual(visibleSavedCases(cases, "site", undefined), []);
assert.equal(visibleSavedCases(cases, "site", "cangnan").some((item) => item.id === "legacy" || item.id === "B1" || item.id === "R1"), false);
assert.equal(siteImportSceneError("cangnan", "cangnan", "苍南", "苍南"), null);
assert.match(siteImportSceneError("yongjia", "cangnan", "苍南", "永嘉"), /属于永嘉，不能导入苍南/);
assert.match(siteImportSceneError(null, "cangnan", "苍南", undefined), /没有记录 scene_name/);
assert.equal(acceptCaseListResponse(2, 2, "cangnan", "cangnan"), true);
assert.equal(acceptCaseListResponse(1, 2, "cangnan", "yongjia"), false);
assert.equal(acceptCaseListResponse(2, 2, "cangnan", "yongjia"), false);

const historyPanel = readFileSync(new URL("./history_panel.tsx", import.meta.url), "utf8");
const workspace = readFileSync(new URL("./map_workspace.tsx", import.meta.url), "utf8");
assert.equal(historyPanel.includes("当前场景暂无已保存的选址案例。"), true);
assert.equal(historyPanel.includes("还没有手动保存的案例。"), true);
assert.equal(historyPanel.includes("确认删除"), true);
assert.equal(workspace.includes("visibleSavedCases"), true);
assert.equal(workspace.includes("acceptCaseListResponse"), true);
assert.equal(workspace.includes("siteImportSceneError"), true);
assert.equal(workspace.includes("sourceFrame !== dataVersion.frame_id"), true);

console.log("saved cases: scene filter, import guard, and stale list response passed");
