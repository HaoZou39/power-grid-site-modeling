# 土地类型图斑批量发布

判定：**`BATCH_PUBLISH_READY`**

本轮只加了后端一次性替换接口。前端、进站距离场、Dijkstra 和场景锁类型都没有改。没有恢复 stash，没有提交，也没有重启服务。

## 1. 代码和 stash

实施前工作区干净，`HEAD` 是 `89ea20b`。四个 stash 都还在，没有 pop、apply 或 drop。P0-S1 预热仍在 `stash@{0}`。

当前运行的 API 是这次改动之前启动的，不会自动带上新接口。

## 2. 协议

```http
POST /api/v1/scenes/{scene_id}/landuse-edits/batch
```

请求：

```json
{
  "expected_scene_revision": "编辑开始时看到的场景版本",
  "items": [
    {"id": "pond", "class_id": 5, "points": [[3, 3], [6, 3], [6, 6], [3, 6]]}
  ]
}
```

`class_id` 仍是 `1` 农田、`2` 建筑、`3` 道路、`5` 水体。`points` 是 1 m 局部坐标，顺序就是覆盖顺序。后续还可混入 `operation: water_to_other` 的条件性水体纠正，口径见 `markdown/WATER_MISCLASSIFICATION_CORRECTION.md`。

成功响应：

```json
{
  "items": [],
  "scene_revision": "发布后的版本",
  "changed": true
}
```

`GET /landuse-edits` 在原有 `items` 之外增加 `scene_revision`。旧客户端只读 `items`，不受影响。没有显式版本的旧场景仍用 `scene_data_version` 的文件身份哈希，不另造一套版本。

限制：最多 128 个图斑、每个图斑最多 2000 个顶点、一批合计最多 8000 个顶点。超出或字段多余时返回 422，不写文件。

## 3. ID、顺序和覆盖

服务端不改客户端送来的 `id`，也不给已有图斑重新编号。`id` 必须是 1 到 64 位的字母、数字、下划线或连字符，且整批不能重复。P0-S2-B 在前端生成 id，修改时沿用原来的 id，删除就是从 `items` 里拿掉。

列表后面的图斑盖住前面的。同一批里先农田、后水体，重叠格子是水体；把两者对调后，重叠格子是农田。空列表表示不再保留任何图斑，栅格回到基准土地，并发布一次新版本。这和逐个删光的栅格一致，和 `DELETE /landuse-edits` 不同：清空接口还会删掉基准栅格和图斑文件。

## 4. 版本和 409

批量写入在原有非阻塞场景锁里进行。先读当前 `scene_revision`，和 `expected_scene_revision` 不一致就抛出冲突，此时还没有做无变化判断，也没有写文件。

HTTP 409 的 `detail.code` 是 `landuse_revision_conflict`，`detail.scene_revision` 是服务器当前版本。只读场景仍返回 422，文件不变。锁被占用时仍是原来的 `CoordinateSceneError`，第二个客户端进不了发布。

## 5. 发布和原子性

`replace_landuse_edits` 校验整批之后只调用一次 `_apply`。`_apply` 仍按现有规则从基准栅格依次盖上图斑，然后替换土地利用、障碍掩膜、类别 PNG、图斑 JSON 和 `data_metadata.json`。

单个 `os.replace` 不能让这五个步骤合成一个事务。发布前把将被替换的栅格、PNG 和图斑文件换到同目录临时名；元数据因为发布函数还要读取，所以先复制一份。任一步抛错时，按相反顺序把这些旧文件换回去，并删掉本不该出现的新文件。校验失败和版本冲突发生在这次替换之前，磁盘保持原样。

进程若在替换过程中被强行杀掉，目录里可能留下 `*.bak`，对应的正式文件可能短暂缺失。这次没有做跨进程的发布日志。读取图斑列表会等同一把锁，所以锁内的失败回滚完成后，读者看到的是回滚前的整套文件，而不是新栅格配旧版本。

不跑 Dijkstra，不写进站距离场，不改 DEM、道路和永农文件。

## 6. 旧接口

以下接口仍是一次编辑一次发布：

```http
GET    /landuse-edits
POST   /landuse-edits
PUT    /landuse-edits/{edit_id}
DELETE /landuse-edits/{edit_id}
DELETE /landuse-edits
```

`/batch` 是独立的 POST 路径，不会被 `/{edit_id}` 的 PUT 或 DELETE 接走。`pose-objectives` 和 `site-report` 的代码没有改。

## 7. 测试

`tests/test_landuse_batch.py`、`tests/test_landuse_edits.py`、`tests/test_scene_version.py`：21 项通过。

覆盖了多图斑初次提交、在已有图斑上增删改、重叠和顺序、空集合、与逐项编辑的土地利用和障碍掩膜逐像元一致、PNG 字节一致、ID 保持不变、重复提交不写文件、过期版本 409 且快照不变、非法多边形和类别、重复 ID、只读场景、并发时后者拿不到锁、发布失败后的文件回滚、读者在锁释放前不会读到半套结果、永农文件字节不变，以及发布后进站距离场源文件签名变化、无变化时签名不变。

## 8. 性能

隔离的 256×256 场景，五个矩形，没有打正在运行的 API，也没有动正式场景缓存。

| 指标 | 五次单项创建 | 一次批量 |
| --- | ---: | ---: |
| 请求数 | 5 | 1 |
| `_apply` | 5 | 1 |
| 栅格 `np.save` 替换 | 11 | 3 |
| PNG 生成 | 5 | 1 |
| 场景版本写入 | 5 | 1 |
| 墙钟 | 0.068 s | 0.017 s |
| tracemalloc 峰值 | 663 KiB | 625 KiB |
| 最终土地利用和障碍掩膜 | 基准 | `array_equal` |

11 次栅格写入里，单项路径第一次还会多写一份基准 `landuse_base_1m.npy`，其后每次 `_apply` 写土地利用和障碍掩膜。批量只写一次基准和一次这两份结果。

0.068 秒对 0.017 秒是这张小网格上的实测，不是 9000×9000 的 4.4 秒乘五。小网格上 PNG 和距离变换都不重，所以耗时不是严格的五分之一。峰值内存几乎一样，因为两边同时只握着一张网格。9000 场景上省下的是重复的整幅写出，本轮没有重测那一档。

## 9. 无变化提交

版本一致，且 id、`class_id`、坐标和顺序都相同，则 `changed` 为 false。不写栅格、PNG、图斑 JSON，也不调用 `write_scene_revision`。进站距离场用的源文件签名保持不变。版本不一致时直接 409，不会被当成无变化成功。

## 10. 已知风险

强杀进程的窗口见第 5 节。批量空列表不会删除基准文件；需要连基准一起去掉时仍用原来的清空接口。客户端必须自己保存 id。退距或禁区不在这批图斑里，提交土地类型不会自动重算方案。

## 11. P0-S2-B 对接

编辑开始时读 `GET /landuse-edits` 的 `scene_revision` 和 `items`。草稿在前端改。确认时把最终列表按绘制顺序 POST 到 `/landuse-edits/batch`，带上开始时的版本。

- `changed: true`：使用返回的新 `scene_revision`。土地文件签名已变，旧进站距离场不能复用。重评仍由后续前端步骤发起。
- `changed: false`：版本没变，不必因为这次提交而重算。
- 409：用响应里的当前版本重新读取，不要用旧草稿覆盖。
- 新图斑的 `id` 在进入草稿时生成，之后不要换。
