# 2026-10-26 代码审查修复验收

本轮以 `9d93677` 为基线，处理审查清单中的 28 项问题。代码修复已完成并验证；真实场景迁移完成三处，楠溪江因缺原始永农 `1.zip` 尚未迁移。提交保留在本地，未推送远程。

## 逐项核对

编号沿用原审查清单顺序。下表记录修复和验证入口；坐标、建模及任务规则仍以相应权威文档为准。

| 编号 | 问题 | 本轮处理 | 验证证据 |
| --- | --- | --- | --- |
| 1 | Web Mercator 投影米被当作地面米 | 新场景和默认科研入口改为显式 1 m UTM 网格；地图显示单独重投影，真北角包含网格收敛角。旧场景不缩放覆盖 | `tests/test_metric_grid.py`、`test_metric_products.py`、`test_display_grid.py`；前端 `site_frame.test.mjs`；真实迁移和默认 CUDA 验证。楠溪江迁移待原始数据 |
| 2 | 硬链接写穿历史实验 | 独立备份、核对哈希并拆开共享文件；场景接收使用复制，发布前解除共享 inode | `tests/test_scene_link_audit.py`、`test_road_import.py`；`outputs/scene-link-audits/20261026-before-isolation/audit.json` |
| 3 | 匝道漏退距 | 匝道与高速地表段共用建筑退距，建模和可建图一致 | `tests/test_road_kinds.py`、`test_road_setback.py`、`test_construction_feasibility_overlay.py` |
| 4 | 软惩罚遗漏建筑退距 | 缓存包含建筑硬禁建带的软掩膜，供 CMA-ES、Adam 和 VAE 使用；进站通行掩膜保持独立 | `tests/test_site_model.py`、`test_multistart_adam.py`、`test_vae_like_multihead.py`；CPU/CUDA 梯度回归 |
| 5 | 取消后立即释放场景 | 运行任务进入 cancelling，执行器确认退出才 cancelled；迟到进度和终态用条件更新 | `tests/test_job_lifecycle.py`、`test_job_database.py`、`test_v0_api.py` |
| 6 | Worker 崩溃后永久占用 | 单 Worker 内核所有权锁；重启回收遗留 running/cancelling 并恢复 queued；重复消息不能重复领取 | `tests/test_job_database.py`、`test_job_lifecycle.py`；真实 PostgreSQL/Redis 杀进程验收 |
| 7 | 重建和其他写操作未统一加锁 | 重建、导入、永农删除、土地修改及 API 写入准入共用场景锁 | `tests/test_scene_lock.py`、`test_scene_store.py`、`test_scene_data_import.py`、`test_landuse_edits.py` |
| 8 | 设置无鉴权及密钥转发风险 | 模型设置复用管理员验证及限流；地址变化必须提供新密钥或明确清除，环境密钥锁定时不能换地址 | `tests/test_agent_settings.py`；隔离浏览器设置验收，全程使用虚构密钥 |
| 9 | 多位角度输入被格式化打断 | 输入保留草稿，合法值可预览，失焦后格式化 | 前端断言；Chromium 实际连续输入 123 |
| 10 | PNG 使用旧位姿 | 导出前合并当前工作区位姿和保留集合，再筛选显示层 | 前端导出断言；实际 PNG 的方案边框像素中心随拖动改变 |
| 11 | 旧结果被盖当前版本 | 数据持久记录 frame_id/scene_revision，任务保存实际读取版本；同网格旧数据重算，跨网格拒绝导入 | `tests/test_scene_version.py`；前端评价与导入断言 |
| 12 | Nginx 上传和读超时不足 | 代理上限匹配双文件导入并设置读超时 | 实际 Nginx 容器联合边界上传验收，详见实验记录 |
| 13 | 预览与备份无限保留 | 新预览有过期清理和令牌锁；成功预览只留回执，原始永农 ZIP 随正式图层保存；只裁剪已核实成功的备份 | `tests/test_import_retention.py`、`test_scene_data_import.py`；历史备份审计没有删除未核实项 |
| 14 | 道路返回值解包损坏 | 三个验证/诊断入口全部接收四个返回值，并共用配置目标网格 | `tests/test_validation_entries.py`；真实默认 UTM/CUDA 建模验证 |
| 15 | 自定义高速退距丢失 | context、分区搜索、重算、可建图显式传递同一配置 | `tests/test_partitioned_search.py`、`test_construction_feasibility_overlay.py`、`test_project_config.py` |
| 16 | sigma0 文案错误 | 明确为 Gaussian 初始化分布宽度，说明对其他初始化不生效 | 插件 schema、助手契约和前端配置断言 |
| 17 | 保存沿用旧 Pareto 层 | 保存时重测目标，对当前可行非手动方案重算 is_pareto 和前沿 CSV；保留历史 pareto_layer | `tests/test_save_workspace.py` |
| 18 | Esc 后 adjusting 不释放 | 鼠标结束、取消、工具切换及卸载共用手势收尾 | 前端手势断言；Chromium 拖动中 Esc 后评价和导出成功 |
| 19 | 只重试选中方案 | 全部失败评价可一次重试，已成功批次不重复提交 | 前端断言；真实浏览器 501 方案、多批次失败及重试 |
| 20 | 收藏显示宽边、保存长边的换算 | 按确认方案保留长边真北角存储格式，修正宽边输入的逆变换；覆盖宽小于高和 UTM | 前端 `favorite_points.test.mjs`；`tests/test_metric_migration.py` 收藏复制回归 |
| 21 | 隐藏数值默认值 | dataclass 无数值默认值，配置缺项/多项拒绝；所有退距入口显式传参；默认场景和目标网格也来自 JSON | `tests/test_project_config.py`、`test_site_plugin_schema.py` |
| 22 | CMA-ES seed=0 不可复现 | CMA 配置拒绝 0，避免 pycma 按时间生成随机种子 | `tests/test_cma_es_utils.py`、`test_site_plugin_schema.py` |
| 23 | DEM 覆盖外静默补零 | 目标初始化 NaN，覆盖不足拒绝；合法零高程保留，源无 nodata 但全部有效时可正常处理 | `tests/test_dem_nodata.py` |
| 24 | query_exact 吞掉 ValueError | 只捕获专用不可达异常，形状或内部状态错误继续报出 | `tests/test_haul_field.py` |
| 25 | 三目标 Pareto 二次复杂度 | 三目标使用精确排序扫描，等值组保持重复点和输入顺序；其他维度保持原实现 | `tests/test_pareto_front.py`；四万记录与旧实现的独立进程对照 |
| 26 | PID 锁、半发布读取和缓存竞争 | 内核锁代替 PID 存活推断，重入校验进程；数组/元数据/图片/预览读取同一快照；缓存目录竞争校验胜者 | `tests/test_scene_lock.py`、`test_scene_store.py`、`test_haul_origin_cache.py`、`test_scene_data_import.py` |
| 27 | 上传内存、BFS 阻塞及 traceback 泄露 | 分块读取并限制单文件；BFS 在线程池执行；traceback 只写服务日志 | `tests/test_scene_data_import.py`、`test_landuse_patch.py`、`test_job_lifecycle.py` |
| 28 | 退距逐键重测和重复报告 | 退距输入失焦/Enter 提交，箭头和步进按钮立即提交；报告使用稳定请求 key 并取消过期请求 | 前端断言；Chromium 验证输入、Enter、箭头和报告请求去重 |

## 验证结果与复核入口

- 完整 Python 回归：671 passed，4 skipped。跳过项仅为需要 `TEST_JOB_DATABASE_URL` 的四项 PostgreSQL 用例；它们在真实临时 PostgreSQL/Redis 验收中另行执行通过。完整测试包含本机 CUDA。
- 前端 `npm run test:problem-snapshot`、`npm run build` 通过；按最终 OpenAPI 重新生成类型，未出现契约差异。构建仍提示原有大体积 bundle，不影响通过。
- 真实 Chromium 验证输入、拖动、Esc、PNG、全批重试、另存场景身份、设置密码、首次准备及历史只读。底图使用固定本地瓦片以消除外网加载波动；React、MapLibre WebGL、目标评价、保存及准备接口实际运行。
- 完整回归 XML：`outputs/validation/review-fixes-20261026/regression.xml`。
- 浏览器：`outputs/validation/browser-20261026/summary.json`、`batch.json`、`settings.json`、`default.json`。
- PostgreSQL/Redis：`outputs/validation/job-recovery-final-20261026/summary.json`。
- Nginx：`outputs/validation/nginx-import-20261026/summary.json`。
- Pareto：`outputs/validation/pareto-40000-20261026/summary.json`。
- 实际迁移：`outputs/validation/utm-migration-20261026/publication/verified.json`。

实验参数和结果只在 [实验记录](EXPERIMENT_LOG.md) 完整维护；上述输出保留本机，不作为源代码提交。

## 数据状态与尚缺输入

1. 苍南、永嘉及中心为 `(27.543840, 120.449097)` 的 1800 m 场景已生成并发布独立 UTM 版本，旧八个核心产物逐文件哈希不变。旧场景封存，原始输入和有效输出保留。
2. 默认苍南新覆盖输入的区域 DEM 原始间距约 30 m；旧约 10 m 裁剪输入保留。1 m 是工作网格，不能声称获得 1 m 实测精度，也不直接把新旧场景当同一输入做算法比较。默认四文件快照和哈希在 `data/sites/cangnan-utm-v2/SOURCES.json`。
3. 楠溪江旧场景含导入道路和永农。扩大到实际 9000 m 时必须重新裁剪原始向量，现有已裁剪永农掩膜无法证明新增范围无永农。原始 `1.zip` 尚未找到，旧场景已封存并标记迁移待办，未发布不完整替代品。收到原文件路径后，使用现有迁移入口生成、验收并发布。
4. `outputs/cmaes_region_0.1` 已受历史硬链接污染，无法核实最早版本，按确认方案标为作废并保留证据。没有用“某次道路备份”猜测恢复原实验。
5. 历史未核实备份继续保留。原审查中的大范围去重、死代码删除及工作区拆分属于后续重构建议，本轮没有顺带执行。

## 权威口径

- [数据、坐标、迁移与保留](DATA_MODULE_SUMMARY.md)
- [建模与约束](MODELING_MODULE_SUMMARY.md)
- [任务与部署](V0_ARCHITECTURE.md)
- [前端行为](FRONTEND_IMPLEMENTATION_SPEC.md)
- [助手接口与说明同步](AGENT_MODULE.md)
- [测试边界](TESTING_STRATEGY.md)
