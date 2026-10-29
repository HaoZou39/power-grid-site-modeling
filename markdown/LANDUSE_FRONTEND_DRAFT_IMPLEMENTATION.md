# 土地类型图斑前端草稿

判定：**`LANDUSE_FRONTEND_DRAFT_READY`**

本轮只改前端草稿、预览和显式保存。没有改 Dijkstra、进站距离场、场景锁或批量发布协议。没有恢复 stash，没有提交。修改完成后按要求重启了本机 API 和前端，使新接口和新页面一起生效。

## 1. 草稿状态

`frontend/src/map/landuse_draft.ts` 分开保存：

- `publishedItems`：后端已经发布的图斑
- `draftItems`：用户希望最终保存的图斑
- `baseRevision`：开始编辑时读到的 `scene_revision`
- `dirty`、`saving`、`conflict`、`error`

初次 `GET /landuse-edits` 同时写入已发布集合和草稿。之后的增删改和撤销只动草稿。无语义差异时 `dirty` 为 false。比较的是 id、`class_id`、坐标和顺序。

## 2. 新增、修改和删除

画完一个图斑只生成稳定 id 并追加到草稿，不调用 `POST /landuse-edits`。id 由 `crypto.getRandomValues` 生成 32 位十六进制，局域网 HTTP 页面也能用。它符合 1–64 位字母、数字、下划线和连字符。修改保持原 id。删除只从草稿移除，已发布集合不变。刚完成土地类型增删后，切到橡皮擦或平移仍可用 Ctrl+Z / Ctrl+Shift+Z 撤销和恢复草稿；擦除禁区或进货原点后，Ctrl+Z 优先恢复那一项。非法图斑或重复 id 不会写入草稿。

## 3. 预览及其精度

地图上的土地类型 PNG 仍是已发布栅格，草稿期间不更换 `sceneVersion`。变化的图斑用虚线和半透明填充标成新增、修改或删除，并写明：

“土地类型修改预览，实际栅格将在保存后更新。”

这不是逐像元合成后的栅格。删除已发布水体时，PNG 里的水体还在，虚线只表示保存后会去掉。永久基本农田图层不进入这套草稿。

## 4. 保存和放弃

有未保存修改时，左侧工作栏底部显示「保存土地类型修改」和「放弃未保存修改」，切到橡皮擦或平移后仍然保留。保存按钮只在 `dirty` 且没有冲突时可用。保存期间不能继续改草稿，也不能再次提交。放弃前会确认，然后把草稿恢复成已发布集合，不请求后端。没有未保存修改时不显示这组按钮。橡皮擦删除已发布或草稿中的图斑只改草稿；与已发布集合不同时 `dirty` 为 true，删掉后若草稿回到已发布集合则 `dirty` 为 false。Ctrl+Z 恢复这次删除。

## 5. 与批量接口的对接

保存调用一次 `POST /landuse-edits/batch`，请求体是 `expected_scene_revision` 和完整 `items`。`changed: true` 时采用返回的新版本并刷新土地 PNG。`changed: false` 时不改场景版本。单项 POST、PUT、DELETE 不再由绘制或删除触发。

## 6. 版本和 409

`baseRevision` 来自 GET 的 `scene_revision`。迟到的 GET 若草稿已脏、正在保存或已经冲突，不会覆盖 `draftItems`。场景 id 或加载代次不符的响应也会丢掉，避免场景 A 的图斑写进场景 B。

409 且 `code` 为 `landuse_revision_conflict` 时保留全部草稿，不把 `expected_scene_revision` 改成新版本再提交。界面提供「重新加载已发布图斑」和「放弃未保存修改」。重新加载会先确认，然后才替换草稿。

## 7. 未保存草稿和候选方案

有草稿、正在保存或版本冲突时：

- 不自动调用 `pose-objectives` 或 `site-report`
- 不显示进站路线
- 开始优化和重新评价旧方案被停用，并提示先保存
- 不清空第一、第二、第三层帕累托方案

`changed: true` 之后，只把 `data_version.scene_revision` 更新为返回值。`poseFreshness` 把仅有场景版本变化标成 `revision-stale`，和禁区一样等待手动重评，不自动批量评价，也不自动重建进站距离场。方案数字按待重评显示。`changed: false` 不改这个版本，已有方案不会因此过期。收藏点的自动评价在草稿和这次待重评期间暂停。

农田文件签名、道路产品号或站址移动仍走原来的自动评价。

## 8. 刷新和切换场景

切换工具或退出编辑不保存。清空方案不清草稿。导入历史方案保留草稿，并说明没有提交。切换场景或重新准备数据时，有草稿会拦住，可先保存，或确认后放弃再继续。刷新和关闭用浏览器的未保存提示。没有把草稿写进 localStorage，刷新后未保存修改会丢失。

## 9. API 次数

单元测试模拟：已有 3 个图斑，再新增 3 个水体、2 个农田，删除 2 个，修改 1 个。保存前写请求、`pose-objectives` 和 `site-report` 都是 0。保存时 `POST /landuse-edits/batch` 为 1。连续新增 10 个图斑同样没有写请求。

## 10. 前端测试

`tsc -b` 和 `npm run build` 通过。`landuse_draft.test.mjs`、`pose_evaluation.test.mjs`、`decision_map.test.mjs` 以及其余不依赖本地实验输出的前端测试通过。

`problem_snapshot.test.mjs` 和 `solution_record.test.mjs` 要读 `outputs/cmaes_region_0.1/`，当前机器上没有这份输出，测试在打开文件时失败。这与本次草稿改动无关。

## 11. 后端回归

`tests/test_landuse_batch.py`、`tests/test_landuse_edits.py`、`tests/test_scene_version.py`：21 项通过。没有改 `_apply()`。

## 12. 运行中的服务

改代码前的 API 进程没有这条批量路由。重启后的进程加载了当前磁盘代码，`/api/v1/openapi.json` 含有 `POST /scenes/{scene_id}/landuse-edits/batch`。健康检查为 `{"status":"ok","service":"site-modeling-api","version":"0.1.0"}`。

## 13. 下一阶段 P0-S2-C

这一阶段已经完成，口径以 `markdown/LANDUSE_COMPUTE_TRIGGER_INTEGRATION.md` 为准。未保存草稿不再停用「开始优化」和「重新评价旧方案」。用户点击这两个按钮时先提交一次草稿，成功并确认新的场景版本后再计算。「保存土地类型修改」仍然只保存。退出编辑工具不提交。
