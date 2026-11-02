import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("./site_solution_sort.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exports = {};
vm.runInNewContext(compiled, {
  exports,
  require(name) {
    if (String(name).includes("decision_run")) return { STALE: "待重评", UNMEASURED: "重算中" };
    if (String(name).includes("solution_record")) return { NOT_PROVIDED: "未提供" };
    throw new Error(`Unexpected dependency: ${name}`);
  },
});

const { nextSiteSort, sortSiteSolutions, siteObjectiveValue } = exports;
const pose = (id, demSoft, extra = {}) => ({
  id, demSoft, offroadHaul: "1", haulRise: "1", roadHaul: "1", demandDistance: "1", ...extra,
});

assert.equal(siteObjectiveValue("1.250"), 1.25);
assert.equal(siteObjectiveValue("待重评"), null);
assert.equal(siteObjectiveValue("重算中"), null);
assert.equal(siteObjectiveValue("未提供"), null);
assert.equal(siteObjectiveValue(""), null);
assert.equal(siteObjectiveValue("nan"), null);

const choices = [pose("a", "2"), pose("b", "1"), pose("c", "1"), pose("d", "待重评")];
const original = choices.map((item) => item.id);
assert.deepEqual(sortSiteSolutions(choices, null).map((row) => row.choice.id), original);
assert.deepEqual(choices.map((item) => item.id), original);

const ascending = sortSiteSolutions(choices, { objective: "demSoft", direction: "ascending" });
assert.deepEqual(ascending.map((row) => row.choice.id), ["b", "c", "a", "d"]);
assert.deepEqual(ascending.filter((row) => row.choice.demSoft === "1").map((row) => row.index), [1, 2]);

const descending = sortSiteSolutions(choices, nextSiteSort({ objective: "demSoft", direction: "ascending" }, "demSoft"));
assert.equal(descending[0].choice.id, "a");
assert.equal(descending.at(-1).choice.id, "d");
assert.deepEqual(sortSiteSolutions(choices, { objective: "demSoft", direction: "descending" }).map((row) => row.choice.id).slice(-1), ["d"]);
