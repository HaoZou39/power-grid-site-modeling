# 土地类型草稿与计算触发

判定：**`LANDUSE_COMPUTE_TRIGGER_CONDITIONALLY_READY`**

编辑期间仍然只改前端草稿。用户点击「重新评价旧方案」或「开始优化」时，先走 P0-S2-B 的同一次批量发布，确认返回的 `scene_revision` 已经写入评价快照，再执行原来的评价或优化。「保存土地类型修改」只保存。退出土地类型工具、切换平移、关闭土地类型面板都不发布、不计算。

没有改 Dijkstra、进站距离场缓存、场景锁、批量发布协议、土地栅格或优化算法。没有恢复 stash，没有提交，没有重启服务。没有改正式楠溪江场景和磁盘缓存。

条件就绪的原因：按钮顺序由前端异步测试锁定，后端发布由既有 pytest 覆盖。本轮没有在隔离场景上点击真实页面，因此没有测量真实的土地发布、批量评价和优化任务创建耗时，也不能证明运行中的页面已经走过这条路径。Vite 直接提供源码，刷新即可加载，但刷新本身没有在本轮执行。

## 1. 按钮触发流程

三个入口共用 `map_workspace.tsx` 里的 `publishLanduseDraft()`，它调用原来的 `beginLanduseSave` 和 `replaceLanduseEdits`。

```text
显式「保存土地类型修改」
    → publishLanduseDraft()
    → 只更新草稿和场景版本
    → 不评价、不提交优化

「重新评价旧方案」
    → 占用 review 操作门
    → publishLanduseDraft()
    → 确认 evaluationSnapshot 的 scene_revision
    → scoreWaiting()，仍是原来的 batches + fetchPoseObjectives

「开始优化」
    → 先校验建筑尺寸和农田代价
    → 校验失败则不发布
    → submitSearch()
    → publishLanduseDraft()
    → 确认版本
    → 原来的 createTrackedJob
```

`frontend/src/map/landuse_compute.ts` 的 `afterLandusePublish` 规定：发布结果是 `conflict`、`failed` 或 `cancelled` 时不调用后续计算；`published` 时，快照里的 `scene_revision` 必须等于接口返回值，否则也不计算。

操作门 `createActionGate` 同时只允许保存、重评、优化其中一件。它不是 `jobStartingRef`。优化是否已经在跑仍由原来的 `optimizationActive()` 判断，避免发布阶段被误判成任务已启动。

## 2. 已有能力的复用

- 发布协议、409 和 `changed: false` 不改场景版本，沿用 P0-S2-A。
- 草稿、预览、显式保存、放弃和场景切换拦截，沿用 P0-S2-B。
- 待重评筛选仍是 `isAwaitingReview`，对象仍是当前显示方案加上 `diversityPool.current` 里隐藏的层。
- 评价仍是 `reevaluateStaleSolutions` → `scoreWaiting` → `fetchPoseObjectives`，每批最多 200。
- 优化仍是 `submitSearch` / `submitRefine` → `createTrackedJob`。没有先调用 `pose-objectives`。
- 进站距离场仍只由既有评分和 `site-report` 构建或复用。本轮没有新增缓存。

## 3. 保存与评价版本同步

`changed: true` 时，`rememberPublishedRevision` 在发起评价或优化之前同步写入：

- `sceneRevisionOverride`
- `layerInfoRef`
- `evaluationSnapshot.current.dataVersion.scene_revision`

然后再 `setLayerInfo` 和 `setSceneVersion`。下一次渲染用这个覆盖值组装 `dataVersion`，直到 `layerInfo.data_version.scene_revision` 与它相同，覆盖值才去掉。因此不能只靠 `setState` 已经调用就认为评价身份已更新。

`changed: false` 不写这个覆盖值，不增加场景版本，不把已评价方案改成过期。若禁区、可行域或历史方案本来就待重评，这次点击仍会评价它们。

`poseFreshness` 把单独的 `landuse_revision` 与 `scene_revision` 同样视为 `revision-stale`。两个土地版本字段先后到达时，不会降成 `pending` 并自动评价。农田内容签名、道路产品号和站址移动仍是 `pending`，自动评价规则不变。

## 4. 已有方案和空白场景

已有保留方案且草稿未保存时，「重新评价旧方案」可以直接点，不必等保存之后才出现 `revision-stale`。发布成功后按新版本重新筛选待重评方案，包含当前显示的方案、多样性池里隐藏的第一到第三层，以及原来的禁区、历史待重评方案。

空白场景点击「开始优化」时，先发布草稿，再提交原来的优化任务，不先评价不存在的旧方案。已有旧方案时点击「开始优化」，仍按原来的方式开始新搜索，不强制先重评。

## 5. Pareto 多层方案

重评和发布不删除、不重编号方案，也不改已保存的 `paretoLayer`。发布且仍有保留方案时，多样性图例下显示：

「以上层级来自上次优化，土地类型更新后尚未重新分层。」

新的优化结果写回、导入历史、清空方案或切换场景时去掉这句。本轮没有重算帕累托层级。

## 6. 自动评价与手动重评

手动重评在发布之前就把 `reevaluatingRef` 设为 true，全部批次结束后才清掉。草稿从脏变干净触发的渲染因此不会再启动一批自动 `pose-objectives`。

`autoPendingPoses` 继续排除 `revision-stale`、`zone-stale` 和 `history-stale`。手动重评完成后，已经按新评价键写回的方案不会再被自动评价。站址位置或朝向变化仍会自动评价。

同一评价键仍在 `evaluationInFlight` 里时不会重复提交。旧响应在写回前会核对场景 id 和评价键。

## 7. site-report

`siteReportAllowed` 在草稿未提交、正在保存、版本冲突，或选中方案仍是待重评时返回 false，效果里不请求报告。选中方案完成评价后，沿用原来的 effect 获取报告，不等所有批次结束。报告请求发生在对应 `pose-objectives` 已经发出之后，因为评分请求在渲染 effect 之前就已经开始。本轮没有新增进站距离场快速路径。

## 8. 409、失败与重试

| 情况 | 计算 | 草稿和方案 | 提示 |
| --- | --- | --- | --- |
| 409 | 不开始 | 保留草稿和全部方案，不改 `expected_scene_revision` 重试 | 场景版本冲突，未开始重新评价或优化 |
| 发布失败 | 不开始 | 保留草稿 | 土地类型保存失败，未开始重新评价或优化 |
| 发布成功，评价失败 | 不再次发布 | 土地已保存，方案保持待重评或失败，可再点重评 | 土地类型已保存，但重新评价失败。 |
| 发布成功，优化任务没启动 | 不再次发布 | 土地已保存，可直接再点开始优化 | 土地类型已保存，但优化任务没有启动。 |

保存过程中切换场景仍被「正在保存」拦住。保存过程中不能继续改草稿。连续点击由操作门挡住，同一次动作只会发布一次、启动一个任务。

## 9. 端到端 API 调用顺序

前端异步测试记录的顺序：

- 无草稿开始优化：只有 `job`，没有 batch。
- 有草稿开始优化：`batch`，然后 `job`。没有 `pose-objectives`。
- 有草稿且方案仍显示为 current：先 `batch`，再 `pose:N`，选中方案变 current 之后才允许 `report`。
- 409 或发布失败：日志为空，不评价、不建任务。
- 发布成功后评价或建任务失败：batch 只有一次；草稿变干净后再次点击不再 batch。
- 133 个方案是一批 `pose:133`。201 个方案分成 200 和 1。
- 显式保存不进入 `run`。`retainLanduseDraft` 原样返回草稿。

这些顺序是测试里的替身客户端，不是运行中的 API 进程。

## 10. 正确性测试

`npx tsc -b` 通过。`npx vite build` 通过。

`landuse_compute.test.mjs`、`landuse_draft.test.mjs`、`pose_evaluation.test.mjs`、`decision_map.test.mjs` 通过。其余不依赖 `outputs/cmaes_region_0.1/` 的前端测试也通过。

`problem_snapshot.test.mjs` 缺少 `outputs/cmaes_region_0.1/data_metadata.json`。`solution_record.test.mjs` 缺少同目录的 `solutions.csv`。没有为它们补正式输出。

后端 `tests/test_landuse_batch.py`、`tests/test_landuse_edits.py`、`tests/test_scene_version.py`：21 项通过。没有改 `_apply()`。

## 11. 真实性能测量

没有在隔离场景或楠溪江场景上点击按钮，因此没有土地发布完成时间、发布到评价请求的间隔、批量评价总耗时或优化任务创建耗时。

异步测试里人为等待 30 ms 发布和 20 ms 计算，测得 `publish_then_score_ms=51`。这只说明计算开始于发布之后，不能外推到 9000×9000，也不能说明进站距离场是否重复构建。运行中的 API 和前端没有重启。

## 12. 剩余风险

- 真实页面尚未按工作流 A–D 点过。刷新前，已经打开的页面仍是旧脚本。
- 若发布返回的新版本与随后一次图层刷新短暂不一致，评价使用发布返回值。另一个客户端的更新版本要等这次覆盖被图层信息接上之后才会进入评价键。
- 多文件发布仍不是崩溃事务，与 P0-S2-A 相同。
- 帕累托层级数字仍是上次搜索写下的，图例已说明尚未重新分层。

## 13. 是否需要后续帕累托分层

需要。当前没有可靠的客户端重分层。土地类型更新后的目标值可以变，图上的层号不是新约束下重新计算的帕累托层。后续应单独做分层重算，不要在评价流程里顺手改 NSGA-II。

## 验收对照

- 连续编辑只改草稿，退出工具不发布、不计算。
- 有保留方案时，未保存草稿可以直接点「重新评价旧方案」，先发布再按新版本评价。
- 空白场景点「开始优化」先校验参数，再发布，再提交原优化任务。
- 无草稿不调用 batch。一次操作最多一次批量发布。
- 409 和发布失败停止计算并保留草稿。发布成功后的评价或任务失败不重复发布。
- 评价键使用发布返回的 `scene_revision`。`revision-stale` 不会被自动评价。
- 多层方案保留，并标明层级尚未重算。
- 待重评的选中方案不提前请求 `site-report`。
- 禁区、可行域、站址移动、永久基本农田和收藏点暂停逻辑没有另写路径。
- 进站距离场算法、缓存和场景锁没有改。stash 未恢复，未提交，未重启。

未完成的是隔离场景上的真实点击和对应耗时。因此本轮是条件就绪，不是 `LANDUSE_COMPUTE_TRIGGER_READY`。
