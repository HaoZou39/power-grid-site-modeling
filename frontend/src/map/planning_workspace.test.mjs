import assert from "node:assert/strict";
import { SiteEdit } from "../../.tmp-workspace/map/site_edit.js";
import { restoreSitePlanningConfig, serializeSitePlanningConfig } from "../../.tmp-workspace/map/site_plan.js";
import { RoutingEdit } from "../../.tmp-workspace/routing/routing_edit.js";
import { restoreRoutingPlanningConfig, serializeRoutingPlanningConfig } from "../../.tmp-workspace/routing/routing_plan.js";
import { resetAccountStorage } from "../../.tmp-workspace/account_storage.js";
import {
  acceptLoadedPlan, baseStatusNotice, bindCreatedWorkspace, conflictKind, followCreatedJob, historyViewDoesNotRestore,
  jobMatchesWorkspace, planDirty, readWorkspaceSelection, resultBaseNotice, revisionAfterSave, revisionPreview,
  RevisionChain, routingFormComplete, routingJobStorageKey, routingRunOptions, ROUTING_WORKSPACE_PLUGIN,
  runProvenance, siteRunOptions, SITE_WORKSPACE_PLUGIN, submissionBlock, submitEndpoint, submitRoute, switchChoice,
  visibleSelection, workspaceJobBody, workspaceResultFrameBlock, workspacesForScene, writeWorkspaceSelection,
} from "../../.tmp-workspace/map/planning_workspace.js";

const memory = () => {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key), clear: () => values.clear(), values };
};

const posed = () => new SiteEdit(
  "demo", 77, 51.5, "blocked", "costly", 0.3, [], [],
  [{ id: "pose-1", x: 12, y: 14, theta: 0.2 }], "pose-1", [],
).addExclusion([{ x: 1.25, y: 2 }, { x: 8.5, y: 2 }, { x: 8.5, y: 9.75 }])
  .addFeasible([{ x: 20, y: 20 }, { x: 30.5, y: 20 }, { x: 30.5, y: 40 }, { x: 20, y: 40 }])
  .putOrigin({ x: 3.5, y: 4.25 });

const storage = memory();
const created = { workspace_id: "w1", base_scene_id: "scene-a", display_name: "甲" };
bindCreatedWorkspace(storage, "user-a", created);
assert.equal(readWorkspaceSelection(storage, "user-a", "scene-a"), "w1");
assert.equal(readWorkspaceSelection(storage, "user-b", "scene-a"), null);
assert.deepEqual(workspacesForScene([created, { workspace_id: "w9", base_scene_id: "scene-b" }], "scene-a").map((item) => item.workspace_id), ["w1"]);

const savedSite = serializeSitePlanningConfig(posed(), { rectW: "210", rectH: "200" });
assert.equal(savedSite.rect_w_m, 210);
assert.notEqual(savedSite.rect_w_m, 77);
assert.equal(JSON.stringify(savedSite).includes("pose-1"), false);
const restored = restoreSitePlanningConfig(posed(), savedSite);
assert.equal(restored.edit.widthM, 77);
assert.equal(restored.rectW, "210");
assert.equal(restored.edit.poses.length, 1);

const schema = { properties: { algorithm: { default: { popsize: 8, pilot: { rrt_goal_bias: 0.2, enabled_mechanisms: ["rrt"] } } } } };
const routingEdit = new RoutingEdit().defaults(schema)
  .connection("start", { lng: "120.100000000", lat: "27.500000000" })
  .connection("end", { lng: "120.200000000", lat: "27.600000000" })
  .copy({ values: { max_span_m: "400", tower_radius_m: "8", max_turn_deg: "30", road_setback_m: "5", highway_setback_m: "20" } });
const savedRouting = serializeRoutingPlanningConfig(routingEdit);
const routingBack = restoreRoutingPlanningConfig(new RoutingEdit().defaults(schema), savedRouting);
assert.equal(routingBack.start.lng, "120.100000000");
assert.equal(routingBack.end.lat, "27.600000000");
assert.deepEqual(routingBack.algorithm.pilot.enabled_mechanisms, ["rrt"]);

const chain = new RevisionChain("r0");
const seen = [];
const first = chain.enqueue(async (revision) => {
  seen.push(revision);
  await new Promise((resolve) => setTimeout(resolve, 10));
  return { revision: "r1", value: "site" };
});
const second = chain.enqueue(async (revision) => {
  seen.push(revision);
  return { revision: "r2", value: "routing" };
});
assert.deepEqual(await Promise.all([first, second]), ["site", "routing"]);
assert.deepEqual(seen, ["r0", "r1"]);
assert.equal(chain.revision, "r2");
assert.equal(revisionAfterSave("r1", { workspace_revision: "r1", changed: false }), "r1");
assert.equal(revisionAfterSave("r1", { workspace_revision: "r2", changed: true }), "r2");
assert.throws(() => revisionAfterSave("r1", { workspace_revision: "r9", changed: false }));

const other = new SiteEdit("demo", 77, 51.5).addExclusion([{ x: 100, y: 100 }, { x: 110, y: 100 }, { x: 110, y: 120 }]);
const w2 = serializeSitePlanningConfig(other, { rectW: "77", rectH: "51.5" });
const switched = restoreSitePlanningConfig(restored.edit, w2);
assert.equal(switched.edit.regions.some((region) => region.ring[0].x === 1.25), false);
assert.equal(switched.edit.regions[0].ring[0].x, 100);
assert.equal(switchChoice(false, true), "prompt");
assert.equal(switchChoice(false, false), "apply");
assert.equal(switchChoice(true, true), "stay");
assert.equal(planDirty(savedSite, w2), true);

assert.equal(conflictKind(409, "workspace_revision_conflict"), "revision");
assert.equal(conflictKind(409, "workspace_base_changed"), "base");
assert.equal(conflictKind(200, "workspace_revision_conflict"), null);
assert.equal(baseStatusNotice("changed") !== null, true);
assert.equal(baseStatusNotice("missing") !== null, true);
assert.equal(submissionBlock({ selected: true, baseStatus: "changed", landusePending: false, complete: true }) !== null, true);
assert.equal(submissionBlock({ selected: true, baseStatus: "missing", landusePending: false, complete: true }) !== null, true);
assert.equal(submissionBlock({ selected: true, baseStatus: "current", landusePending: true, complete: true }).includes("不会自动发布"), true);
assert.equal(submissionBlock({ selected: true, baseStatus: "current", landusePending: false, complete: true }), null);

const siteBody = workspaceJobBody({ pluginId: SITE_WORKSPACE_PLUGIN, revision: "r2", experimentName: "site-run", runOptions: siteRunOptions() });
assert.equal(submitRoute("w1"), "workspace");
assert.equal(submitEndpoint("workspace", "w1"), "/api/v1/workspaces/w1/jobs");
assert.equal(siteBody.plugin_id, "site.guided_search");
assert.deepEqual(siteBody.run_options, {});
assert.equal(JSON.stringify(siteBody).includes("owner_id"), false);
assert.equal(JSON.stringify(siteBody).includes("snapshot_dir"), false);
assert.throws(() => workspaceJobBody({ pluginId: SITE_WORKSPACE_PLUGIN, revision: "r2", experimentName: "x", runOptions: { base_revision: "nope" } }));

const routingBody = workspaceJobBody({
  pluginId: ROUTING_WORKSPACE_PLUGIN, revision: "r2", experimentName: "route-run",
  runOptions: routingRunOptions(savedRouting.algorithm_overrides),
});
assert.equal(routingBody.plugin_id, "routing.nsga2");
assert.equal("start" in routingBody.run_options, false);
assert.equal("no_tower_zones" in routingBody.run_options, false);
assert.equal(submitRoute(null), "legacy");
assert.equal(submitEndpoint("legacy", null), "/api/v1/jobs");
assert.deepEqual(followCreatedJob({ job_id: "job-1", workspace_id: "w1" }, "w1"), { jobId: "job-1", workspaceId: "w1" });
assert.equal(jobMatchesWorkspace({ job_id: "job-1", workspace_id: "w1" }, "w1", "job-1"), true);
assert.equal(jobMatchesWorkspace({ job_id: "job-1", workspace_id: "w1" }, "w2", "job-1"), false);
assert.equal(routingJobStorageKey("scene-a", "w1") === routingJobStorageKey("scene-a", "w2"), false);

const userStore = memory();
writeWorkspaceSelection(userStore, "user-a", "scene-a", "w1");
resetAccountStorage(userStore, "user-a", null);
assert.equal(readWorkspaceSelection(userStore, "user-a", "scene-a"), null);
const split = memory();
writeWorkspaceSelection(split, "user-a", "scene-a", "w1");
writeWorkspaceSelection(split, "user-b", "scene-a", "w2");
assert.equal(readWorkspaceSelection(split, "user-b", "scene-a"), "w2");
resetAccountStorage(split, "user-a", "user-b");
assert.equal(readWorkspaceSelection(split, "user-a", "scene-a"), null);
assert.equal(visibleSelection("gone", ["w1"]), null);

const started = { token: 2, accountId: "user-a", sceneId: "scene-a", workspaceId: "w1" };
assert.equal(acceptLoadedPlan(started, started), true);
assert.equal(acceptLoadedPlan({ ...started, token: 1 }, started), false);
assert.equal(acceptLoadedPlan(started, { ...started, accountId: "user-b" }), false);
assert.equal(acceptLoadedPlan(started, { ...started, workspaceId: "w2" }), false);

const emptyRouting = serializeRoutingPlanningConfig(new RoutingEdit());
assert.equal(routingFormComplete(emptyRouting), false);
assert.equal(submissionBlock({ selected: true, baseStatus: "current", landusePending: false, complete: routingFormComplete(emptyRouting) }).includes("不能提交"), true);
assert.equal(routingFormComplete(savedRouting), true);

const viewed = historyViewDoesNotRestore("v1", "v2");
assert.equal(viewed.restored, false);
assert.equal(viewed.viewing, "v1");
assert.notEqual(viewed.viewing, viewed.editing);
const preview = revisionPreview({ revision_id: "v1-revision", site: savedSite, routing: savedRouting });
assert.equal(preview.includes("没有恢复"), true);
assert.equal(preview.includes("sha"), false);

const provenance = runProvenance({
  job: { job_id: "job-1", workspace_id: "w1", workspace_revision: "r2", base_revision: "base-old" },
  workspaceId: "w1", workspaceName: "甲", liveBaseRevision: "base-new",
});
assert.equal(provenance.historical.includes("历史基础版本"), true);
assert.equal(runProvenance({ job: provenance && { job_id: "job-1", workspace_id: "w2" }, workspaceId: "w1", workspaceName: "甲", liveBaseRevision: "base-new" }), null);
assert.equal(workspaceResultFrameBlock("grid-a", "grid-b") !== null, true);
assert.equal(workspaceResultFrameBlock("grid-a", "grid-a"), null);
assert.equal(JSON.stringify(provenance).includes("planning_content_hash"), false);
