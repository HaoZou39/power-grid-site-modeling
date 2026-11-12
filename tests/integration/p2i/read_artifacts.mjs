import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [compiled, siteCsv, paretoCsv, routesPath, summaryPath, framePath, sceneName] = process.argv.slice(2);
const base = pathToFileURL(compiled.endsWith("/") ? compiled : `${compiled}/`);
const { adaptSolutions, experimentListStats } = await import(new URL("solution_record.js", base));
const { parseRoutingResult } = await import(new URL("routing/routing_result.js", base));

const rows = adaptSolutions(readFileSync(siteCsv, "utf8"), readFileSync(paretoCsv, "utf8"));
if (!rows.some((row) => row.isFeasible === true && Number.isFinite(row.sort.roadDistance))) {
  throw new Error("选址解析没有读到可行方案");
}
const stats = experimentListStats(JSON.parse(readFileSync(summaryPath, "utf8")));
if (stats.total === "未提供" || stats.feasible === "未提供") {
  throw new Error("实验摘要缺少方案数量");
}
const bundle = parseRoutingResult(readFileSync(routesPath, "utf8"), sceneName, JSON.parse(readFileSync(framePath, "utf8")));
if (!bundle.routes.some((route) => route.is_feasible && route.points.length >= 2)) {
  throw new Error("选线解析没有读到可行线路");
}
console.log(`frontend-parser-ok site=${rows.length} routes=${bundle.routes.length}`);
