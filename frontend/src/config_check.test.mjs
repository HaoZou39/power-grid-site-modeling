import assert from "node:assert/strict";
import { checkConfig, formGroups, hasSitingFields, resolveSchemaRefs, weightLocation } from "../.tmp-problem-snapshot/config_check.js";

const sitingSchema = {
  type: "object",
  properties: {
    experiment_name: { type: "string", title: "实验名称" },
    seed: { type: "integer", title: "随机 seed", default: 1 },
    rect_w_m: { type: "number", title: "建筑矩形宽度", minimum: 0, "x-unit": "m" },
    rect_h_m: { type: "number", minimum: 0 },
    dem_soft: { type: "number" },
    road_distance: { type: "number" },
    demand_distance: { type: "number" },
    popsize: { type: "integer", minimum: 1, "x-group": "algorithm" },
  },
  required: ["experiment_name", "rect_w_m", "rect_h_m", "dem_soft", "road_distance", "demand_distance"],
};

const valid = {
  experiment_name: "new-run",
  seed: 7,
  rect_w_m: 80,
  rect_h_m: 50,
  dem_soft: 0.2,
  road_distance: 0.3,
  demand_distance: 0.5,
  popsize: 8,
};
assert.deepEqual(checkConfig(sitingSchema, valid, { existingExperimentIds: ["old-run"] }), []);

const groups = formGroups(sitingSchema);
assert.deepEqual(groups.map((group) => group.title), ["数据与实验身份", "站点和约束", "目标偏好", "算法和运行参数"]);
assert.deepEqual(groups.find((group) => group.id === "site").names, ["rect_w_m", "rect_h_m"]);
assert.equal(hasSitingFields(sitingSchema), true);

const draft = {
  experiment_name: "old-run",
  rect_w_m: -1,
  rect_h_m: "",
  dem_soft: 0.5,
  road_distance: 0.5,
  demand_distance: 0.5,
};
const invalid = checkConfig(sitingSchema, draft, { existingExperimentIds: ["old-run"], dataMissing: ["data_metadata.json"] });
assert.equal(invalid.find((issue) => issue.path === "experiment_name").message.includes("覆盖"), true);
assert.equal(invalid.find((issue) => issue.path === "rect_w_m").message, "不能小于 0");
assert.equal(invalid.find((issue) => issue.path === "rect_h_m").message.includes("请填写"), true);
assert.equal(invalid.find((issue) => issue.path === "dem_soft").message.includes("权重总和"), true);
assert.equal(invalid.find((issue) => issue.path === "").message, "数据产物尚未准备好：data_metadata.json");

assert.equal(draft.experiment_name, "old-run");
assert.equal(draft.dem_soft, 0.5);

const overwritten = checkConfig(sitingSchema, { ...valid, experiment_name: "old-run" }, {
  existingExperimentIds: ["old-run"],
  allowOverwrite: true,
});
assert.deepEqual(overwritten, []);

const demoSchema = {
  type: "object",
  properties: {
    values: { type: "array", items: { type: "number" }, minItems: 1, title: "数值列表", "x-group": "algorithm" },
    multiplier: { type: "number", title: "乘数", default: 1 },
  },
};
assert.equal(hasSitingFields(demoSchema), false);
assert.equal(checkConfig(demoSchema, { values: "", multiplier: 1 }).length > 0, true);
assert.deepEqual(checkConfig(demoSchema, { values: "1, 2", multiplier: "3" }, { dataMissing: ["data_metadata.json"] }), []);

const resolved = resolveSchemaRefs({
  $defs: {
    ObjectiveWeights: {
      type: "object",
      properties: {
        dem_soft: { type: "number" },
        road_distance: { type: "number" },
        demand_distance: { type: "number" },
      },
    },
  },
  type: "object",
  properties: {
    objective_weights: { allOf: [{ $ref: "#/$defs/ObjectiveWeights" }], title: "目标权重", "x-group": "preference" },
    rect_w_m: { type: "number", exclusiveMinimum: 0, "x-group": "site" },
  },
});
assert.equal(resolved.properties.objective_weights.properties.dem_soft.type, "number");
assert.equal(resolved.properties.objective_weights["x-group"], "preference");
assert.equal(weightLocation(resolved), "nested");
assert.equal(checkConfig(resolved, {
  rect_w_m: 0,
  objective_weights: { dem_soft: 1, road_distance: 0, demand_distance: 0 },
}).some((issue) => issue.path === "rect_w_m" && issue.message.includes("必须大于")), true);

console.log("config_check assertions passed");
