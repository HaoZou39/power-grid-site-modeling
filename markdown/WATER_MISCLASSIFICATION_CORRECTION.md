# 去除误识别水体

判定：**`WATER_CORRECTION_CONDITIONALLY_READY`**

本轮在现有土地类型草稿与 `landuse-edits/batch` 上扩展条件性纠正。未改 Dijkstra、进站距离场缓存、场景锁类型或优化算法。未恢复 stash，未 commit，未 push，未重启服务。

## 当前口径

「去除水体」已扩展为一个工具 **去除类别**。新图斑写 `operation: class_to_other` 和 `target_class_id`（`1` 农田、`2` 建筑、`3` 道路、`5` 水体）。合成时只把圈内当前等于该类别的像元改为 `0`，圈内其他类别和圈外全部保持不变。旧 `water_to_other` 继续接受，等价于只去除 `5`，不迁移已有 `landuse_edits.json`。

此操作只改土地分类栅格，以及由它生成的障碍掩膜和土地类型 PNG。永久基本农田、OSM 道路中心线及退距、DEM、坡度和手绘禁区都不改。不能用 `class_id: 0` 的普通图斑代替，也没有清除全部类别的操作。圈内当时没有目标类别时整批拒绝，已发布场景保持原样。

## 1. 本地代码和工作区

实施基于 `74c9a12`（土地类型草稿与批量发布）之上的工作区改动。四个 stash 仍在，未 pop。

## 2. 工具入口

「编辑」里的「土地分类」与其它工具同一行：一个下拉选 **设置**（设置类别）或 **清除**（清除指定类别），另一个下拉选农田、建筑、道路、水体。菜单浮在工具栏下方，不另起一行。

- 说明：保存后仅将圈内当前属于指定类别的像元改为其他，其他类别保持不变。
- 操作：与普通土地类型相同，按住左键画圈，松开后进入草稿。
- 选中类别时自动打开对应图层，其他图层的显示状态不变。

## 3. 图斑数据结构

普通覆盖（旧格式，兼容）：

```json
{"id": "pond", "class_id": 5, "points": [[x, y], ...]}
```

条件性纠正（新图斑）：

```json
{"id": "clear-1", "operation": "class_to_other", "target_class_id": 2, "points": [[x, y], ...]}
```

已有水体纠正仍可读：

```json
{"id": "clear-1", "operation": "water_to_other", "points": [[x, y], ...]}
```

`landuse_edits.json` 仍为 `version: 1`。旧条目无 `operation` 时继续按 `class_id` 覆盖。不允许 `class_id: 0` 的普通图斑冒充纠正。`water_to_other` 不得带 `class_id` 或 `target_class_id`。`class_to_other` 必须带 `target_class_id`，且不得带 `class_id`。

## 4. 条件性计算

`experiments/landuse_edits.py` 的 `compose_landuse`：

1. 从基准栅格复制 `effective`。
2. 按列表顺序：
   - 普通图斑：`effective[polygon_mask] = class_id`
   - `class_to_other`：`effective[polygon_mask & (effective == target_class_id)] = 0`。`water_to_other` 的目标固定为水体 `5`。圈内没有该类别时整批报错，例如「圈选区域内没有需要纠正的建筑」。
3. 障碍掩膜仍由最终 `effective` 中的农田/建筑/道路/水体生成。

`class_id=0` 只表示其他。永农、OSM 道路、禁区、坡度和高程等独立约束照旧。

## 5. 与普通覆盖的区别

| | 普通图斑 | class_to_other / water_to_other |
| --- | --- | --- |
| 写入 | 圈内全部像元设为 `class_id` | 仅当前等于目标类别的像元改为 0 |
| 可否设 0 | 否（可编辑类仅 1/2/3/5） | 是（仅此路径） |
| 预览 | 类别色较实的填充 | 同一类别色、更低的填充和更粗的虚线，只标修正范围 |

## 6. 顺序与重叠

后面的图斑基于已经应用了前面全部图斑后的 `effective`。例如：先画水体，再纠正，再画水体，最后一层水体可盖回。删除纠正图斑后按剩余列表重新合成，不会把范围一律恢复成水体。

## 7. 旧格式兼容

`_read_edits` / `_normalize_batch` 对缺 `operation` 的条目走原覆盖逻辑。单项 `POST /landuse-edits` 仍只接受普通 `class_id`。批量接口一次 `_apply`，409、无变化、回滚与永农文件保护保持原样。

## 8. 前端草稿

新图斑写入 `operation: class_to_other` 和 `target_class_id`。读到的旧 `water_to_other` 仍可显示、删除和撤销。撤销、重做、橡皮擦删除、保存、放弃、先发布后评价/优化均复用 `landuse_draft` / `landuse_compute`。退出工具不发布。圈内是否有目标类别在保存时由后端按完整草稿顺序判定；无效纠正返回 422，草稿保留。

## 9. 批量发布与版本

仍用 `POST /api/v1/scenes/{id}/landuse-edits/batch`。混合普通图斑与纠正图斑一次提交。`expected_scene_revision` 不符 → 409，不写文件。

## 10. 无水体区域

合成时若该纠正图斑在当时 `effective` 上碰不到目标类别，整批拒绝。水体仍提示「圈选区域内没有需要纠正的水体」，其他类别同样点名。不把其余类别改成 0。

## 11. 栅格测试

`tests/test_water_misclassification.py` 保留原水体纠正。`tests/test_landuse_class_correction.py` 覆盖去除建筑、农田、道路、水体，以及旧 `water_to_other`、图斑顺序、删除恢复、缺类别拒绝、栅格与 PNG 一致、永农和 OSM 道路文件不变、失败回滚、历史 JSON 与批量接口兼容。

## 12. 前端测试

`landuse_draft.test.mjs`：纠正项 dirty、undo/redo 保留 operation、与普通图斑混合保存、parse 拒绝非法组合。`decision_map.test.mjs`：工具入口与轮廓显示条件。`favorite_interaction.test.mjs`：橡皮擦优先级。

## 13. 重评与空白优化

未改 P0-S2-C 路径。未在隔离实景上点「重新评价旧方案」或「开始优化」，故未升为 READY。

## 14. 性能与请求

画圈、删除、撤销只改前端草稿，不调后端。保存或计算前发布仍是一次 batch、一次 `_apply`。不因纠正图斑单独 Dijkstra。

## 15. 已知风险

- 前端无法在画圈当下用完整草稿顺序像元判定“圈内无水体”，依赖保存时后端拒绝。
- 预览是条件性范围示意，不是逐像元最终栅格。
- 实景流程 A–D 未点击验证。

## 判定说明

单元与契约测试通过，协议向后兼容，计算语义符合需求。因缺少隔离场景端到端点击，判定为 **CONDITIONALLY_READY**。
