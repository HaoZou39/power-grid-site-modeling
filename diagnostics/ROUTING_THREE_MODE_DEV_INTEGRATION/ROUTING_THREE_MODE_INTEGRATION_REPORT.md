# ROUTING_THREE_MODE_DEV_INTEGRATION

开发分支 `feat/routing-three-mode-preview`。未合并主分支，未部署生产环境。

功能开关默认关闭。后端读 `ENABLE_ROUTING_THREE_MODE_PREVIEW`，前端由 Vite `define` 编译 `VITE_ENABLE_ROUTING_THREE_MODE_PREVIEW=1`。两处都要设上并重启进程，界面才会出现三档。

## 修改文件

接入代码：

- `algorithms/routing/three_mode.py`：加载已验证的 A5 与 P8-R3，检查子集不变式。
- `experiments/routing_three_mode_output.py`：在 `routes.json` 写完之后附加三层文件。失败只写 `status=failed` 的清单，不删已写出的 `routes.json`。
- `experiments/routing_output.py`：末尾调用上述写出。`routes.json` 仍只含 `published_indices`。
- `experiments/materialize_routing_three_mode_preview.py`：用苍南 E1 已保存前沿生成预览案例，不重跑搜索。
- `backend/app/api/routes.py`：四个新文件名进入已有产物读取名单，并沿用自动结果的查看记录。
- `frontend/vite.config.ts`、`frontend/src/routing/routing_portfolio.ts`、`routing_results.tsx`、`use_routing_controller.ts`、`routing_layer.ts`、`routing_result.ts`、`routing_workspace.tsx`、`routing.css`、`routing.test.mjs`、`package.json`。
- `markdown/AGENT_MODULE.md`、`agent/prompts.py`：助手知道开关默认关闭，分组不是工程等效，缺完整前沿不能当成全部 Pareto。

测试：`tests/test_routing_three_mode.py`。

未纳入本次提交的既有未提交改动：`algorithms/common/nsga2.py`、`algorithms/routing/archive.py`、pilot_reference、`postprocess.py`、`active_objectives.py`、`epsilon_boxes.py`、P4–P10 诊断与对应测试、`markdown/EXPERIMENT_LOG.md`。

## 新增数据结构

开关打开且本次结果带有完整 `pareto_indices` 时，任务目录多四个文件。`routes.json` 语义不变。

| 文件 | 内容 |
| --- | --- |
| `routes_all_pareto.json` | 本次严格 Pareto：`route_id`、四目标、可行性、折线、塔位、档距 |
| `routing_a5_groups.json` | `group_id`、`representative_route_id`、`member_route_ids`、`member_count`、`group_risk_flags`、`engineering_review_status=NOT_REVIEWED` |
| `routing_recommendations.json` | `recommended_route_ids`、标签、理由、`recommendation_rank`、`review_flags` |
| `routing_portfolio_manifest.json` | `schema_version`、`scene_id`、`experiment_id`、`data_version`、`algorithm_version`、`source_revision`、三层数量与来源 |

冻结口径：

- A5：Hausdorff ≤ 20 m，塔数差 0，长度差 ≤ 30 m，转角差 ≤ 3°，跨越差 ≤ 10 m。只与已保留代表比较，不连锁合并。
- R3：四目标极值、稳定且切口 ≥ 400 m 的主要宏观走廊、跨越减少超过 10 m 且另一目标变差的典型折中。不补足到固定条数。
- 不使用 P2-B、epsilon-box、动态收益拐点、40 m 全覆盖。

不变式：`RECOMMENDED ⊆ A5_REPRESENTATIVES ⊆ ALL_PARETO`。分组不标工程等效。缺少跨越对象或农田时写 `CROSSING_OBJECTS_DATA_MISSING`、`FARMLAND_DATA_MISSING`。塔位偏移超过 10 m 写 `TOWER_OFFSET`，超过 50 m 再写 `HIGH_TOWER_OFFSET`，界面显示「工程差异待复核」。

历史任务没有完整前沿时，清单 `status=legacy_published_only`，`all_pareto_count` 为空，文案说明只保存了旧发布线路、不能恢复非支配前沿。不自动重跑。

## 后端样例

预览案例 `outputs/routing-three-mode-preview-cangnan-e1/`（本地输出，不入库）：

```json
{
  "status": "complete",
  "scene_id": "cangnan-utm-v2",
  "experiment_id": "routing-three-mode-preview-cangnan-e1",
  "algorithm_version": "A5-hausdorff20-tower0-length30-bend3-crossing10+R3-extremes-stable-macro-crossing-tradeoff",
  "all_pareto_count": 449,
  "a5_group_count": 46,
  "recommended_count": 5,
  "subset": "RECOMMENDED ⊆ A5_REPRESENTATIVES ⊆ ALL_PARETO"
}
```

推荐编号：`E1-119812` 最少塔、`E1-72417` 最短线路、`E1-24715` 最小转角、`E1-163528` 最小跨越、`E1-151929` 长度—跨越折中。`group-E1-151929` 有 10 名成员，含 `E1-145323`，组内最大塔位偏移 93.381 m。

## 各模式真实数量

产品路径按本次前沿下标排序后取代表。与已发表 P8 文件的差别只出在 Hausdorff 完全相同的平局：苍南当时按档案顺序，永嘉当时按 `a5_keep` 返回顺序。两组都跑过，A5 组数相同。

| 前沿 | 完整 Pareto | A5 组 | 产品推荐（前沿下标） | 已发表 P8（`a5_keep` 顺序） |
| --- | ---: | ---: | ---: | ---: |
| 苍南 E1 | 449 | 46 | 5 | 6 |
| 苍南 E4 | 428 | 47 | 5 | 5 |
| 永嘉 123 | 701 | 242 | 10 | 9 |
| 永嘉 124 | 976 | 288 | 7 | 6 |
| 永嘉 125 | 671 | 161 | 6 | 6 |

苍南 E1 的产品推荐五条与已发表 R3 的五条编号一致。永嘉 123 的产品结果把一条塔数—跨越折中单独留下，并在走廊平局里取了更小的前沿下标。

## 前端实测

开发服务器 `http://127.0.0.1:5176/`，API `8010`，开关打开。导入案例「三档预览 苍南 E1」。

- 默认「推荐方案：5 条」。地图上五条线颜色可区分，可点开四目标、标签和理由。`E1-119812` 显示所属组 `group-E1-119812`、成员 44 条、`NOT_REVIEWED`、工程差异待复核、跨越对象 `DATA_MISSING`。
- 「相似线路：46 组」。点开 `E1-151929` 后列出 9 名成员。点 `E1-145323` 后，详情是它自己的档距（首档水平 103.1 m，总长 1045.2 m，转角 19.5° 起），代表线路是首档 104.5 m、总长 1039.7 m、转角 20.9° 起。地图上选中塔位与代表塔位分两种颜色，沿线路错开，比例尺约 30 m 时错开约一个档距，对应沿线路约 93.4 m。没有把代表塔位说成全组成员共用。
- 「全部 Pareto：449 条」。搜索 `E1-151929` 只留下该编号，已对比的 `E1-145323` 仍钉在列表里。分页按钮存在，上一页在第一页禁用。标题数量仍是 449，分页没有删数据。
- 从相似线路勾选 `E1-145323` 后切到全部 Pareto，对比面板里的「线路 332」还在。切换没有重新优化，`route_id` 未改。

逐档三维长度和跨越在这个预览案例里是「无数据」：几何和线路级四目标来自已保存前沿，没有为展示重算 DEM 高程。正式任务走评价器，`report=True` 会写出真实档距。

## 三档切换与塔位对比

| 检查 | 结果 |
| --- | --- |
| 三档按钮与真实数量 5 / 46 / 449 | 通过 |
| 推荐理由、风险提示、查看相似线路 | 通过 |
| 展开 `group-E1-151929` 并选中 `E1-145323` | 通过 |
| 成员塔位与代表塔位同时可见且位置不同 | 通过 |
| 搜索 `route_id`、分页、对比列表跨模式保留 | 通过 |

截图在本次开发会话的浏览器记录中：推荐五线叠在苍南影像上；放大后黄点为 `E1-145323` 塔位、橙色圈为 `E1-151929` 塔位；全部 Pareto 页同时保留搜索结果和对比折线。

## 实际任务冒烟

未新开一次 NSGA-II。地图上的三档来自苍南 E1 已保存的 449 条严格前沿，经同一套 `build_three_mode` 落成案例后，由现有前端导入。优化完成、写出和失败隔离由 `tests/test_routing_three_mode.py` 覆盖：开关关闭不写附加文件；合成前沿分组与推荐满足子集；历史清单不编造完整前沿。五个历史前沿的数量断言已通过（约 14 秒，5 项）。

因此「在开发环境再跑一遍优化并自动落下三层文件」这一项没有在本轮执行。写出函数已经接在 `write_routing_outputs` 末尾，开关打开的下一次正式选线会走这条路径。

## 性能

前端测试用 1000 条合成线路分页，搜索加钉选后地图只保留 2 条，耗时低于 200 ms。浏览器里 449 条前沿可搜索、可翻页，页面没有卡死。相似线路模式当前把全部代表画到地图上：苍南 46 条可以操作；永嘉 288 个代表会更重，全部 Pareto 才按 50 条分页并按需画当前页。

## 历史兼容与留存

- 开关关闭：不写四个新文件，界面仍读 `routes.json`。
- 只有旧 `routes.json` 的任务：明确提示不能恢复完整前沿，不把 10 m 发布集显示成全部 Pareto。
- 自动结果仍只保留每个场景、每种问题最近 2 次。本次预览案例 `is_case=true`，不进这 2 次清理。三层文件跟着任务目录走，任务被清理时一起消失。

## 已知问题

- 产品推荐条数与已发表 P8 在平局顺序上不一致，见上表。算法没有改。
- 预览案例的逐档三维和塔基坡度是空值。
- 跨越对象和农田在这条写出路径上标为缺失，塔位偏移仍会计算。
- 相似线路模式一次绘制全部代表，永嘉组数下地图会更重。
- 本轮没有新的优化任务来验证开关打开后的端到端写出。

## 回滚

去掉两个环境变量并重启 API 与 Vite。已有 `routes.json` 的读取不变。带三层文件的任务在开关关闭后回到原来的发布线路列表。不要合并本分支即可保持主分支不变。

## 验收

| 标签 | 结果 |
| --- | --- |
| FULL_PARETO_OUTPUT | PASS |
| A5_GROUPING_INTEGRATED | PASS |
| R3_RECOMMENDATION_INTEGRATED | PASS |
| THREE_MODE_FRONTEND | PASS |
| GROUP_EXPANSION | PASS |
| ROUTE_ID_CONSISTENCY | PASS |
| ORIGINAL_GEOMETRY_PRESERVED | PASS |
| LEGACY_COMPATIBILITY | PASS |
| FEATURE_FLAG_ROLLBACK | PASS |
| DEV_SMOKE_TEST | FAIL |
| FRONTEND_PERFORMANCE | PARTIAL |
| READY_FOR_DEV_REVIEW | YES |
| READY_FOR_PRODUCTION | NO |

`DEV_SMOKE_TEST` 为 FAIL：地图三档已在现有前端上用苍南 E1 完整前沿看过，但没有再跑一次新的选线优化。`R3` 的 PASS 指冻结规则已接入；永嘉推荐条数相对已发表文件差在平局顺序，上表已写明。
