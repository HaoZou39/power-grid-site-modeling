# 代码地图

本文是当前仓库的阅读入口。先按“数据 → 建模 → 算法 → 实验输出 → 软件外壳”的顺序理解，
再进入具体文件。文件只在所属目录内承担一种职责；跨目录调用应遵守下面的依赖方向。

```text
data/                 原始输入文件，只读，不放 Python 代码
data_tools/           四类数据 tool：读取、坐标转换、校验和标准化输出
modeling/             PyTorch 目标、约束、pose 和共享问题上下文
algorithms/           可替换的算法实现和多目标公共数学工具
experiments/          把数据、建模和算法组装成可运行实验，并写出结果
figures/              公共图件生成；不读取原始数据，也不计算目标
config/               dataclass 配置和默认 JSON
frontend/             React 用户界面
backend/              FastAPI 接口、用例编排和基础设施适配器
agent/                只读助手、偏好建模和方案推荐。提出编辑操作，确认前不改地图
worker/               生产形态下的后台任务进程入口
plugins/              显式注册的插件实现
tests/                小型、确定性的回归测试
markdown/             权威设计口径、运行指南和实验记录
deploy/               Docker Compose 部署编排
masking_pipeline/     卫星、分割、道路和 DEM 四文件流水线；由 worker 调用，不单独提供网站
```

## 研究代码

地图的三档「方案多样性」由 `frontend/src/map/solution_diversity.ts` 从已评价的可行候选逐层选取，`decision_run.ts` 读取实验快照，`map_workspace.tsx` 管理显示范围和未显示方案缓存。分层规则见 `markdown/GUIDED_SEARCH.md`，控件行为见 `markdown/FRONTEND_IMPLEMENTATION_SPEC.md`。

### 根目录和配置

- `pyproject.toml`：Python 工具链和项目元数据。
- `environment.yml`：研究环境及 CUDA/PyTorch 依赖。pip 包名单在 `requirements.txt`。
- `requirements.txt`：本机 `torch311` 的 pip 依赖，含 `requests`、`mercantile`、`transformers`。CUDA 版 PyTorch 仍只写在 `environment.yml`。
- `restart.sh`：先快进拉取当前分支，再停掉本仓库占用 8010 和 5176 的进程并重新启动。工作区不干净、不能快进或依赖安装失败时不停止正在运行的进程。停进程时跳过脚本自己。新进程没有就绪时退回拉取前的提交再启动。页面上的「软件更新」走同一脚本，密码是 `UPDATE_PASSWORD`。
- `.gitattributes`：shell 脚本和 `.githooks/` 固定 LF。本机 `core.autocrlf=true`，拉取后若成了 CRLF，bash 跑不了 `restart.sh`。
- `config/default_config.json`：建模与算法参数唯一的取值处，不放算法实现。插件表单默认值、助手说明和测试都经 `load_default_config()` 读取它；变电站占地 `rect_w_m`、`rect_h_m` 也在这里，决策界面和接口都可以改。前端地图的初始尺寸仍单独写在 `frontend/src/map/`。
- `config/project_config.py`：各配置段的 dataclass，只定义字段和类型，不写数值默认值；`load_project_config` 对缺字段或多字段直接报错，`load_default_config` 缓存读取上面的 JSON。
- `validation_data/build_preferences.py`：生成固定的验证偏好权重表。
- `validation_data/preferences_step_0.1.csv`：验证集的确定性输入数据。

### `data_tools/`：数据处理工具

- `dem_tool.py`：读取 DEM，并重采样到统一的 1 m 局部栅格。
- `landuse_tool.py`：读取 landuse，执行类别映射并生成 obstacle mask。
- `landuse_prompt.py`：点击分割的可替换接口。当前占位实现明确报错，不加载模型。
- `traffic_tool.py`：读取 OSM GeoJSON，转换局部坐标，按原始共享节点分段做拓扑保持简化，并生成与新线段一一对应的 Voronoi 图。
- `road_voronoi.py` / `road_voronoi_cuda.py`：最近连续线段标签的统一分派、原版 CPU 搜索及分块 CUDA 融合归约；精度和显存口径见 `markdown/DATA_MODULE_SUMMARY.md`。
- `demand_tool.py`：按数量和 seed 生成连续需求点。
- `io_utils.py`：研究产物的 JSON、数组和路径写入辅助函数。

数据 tool 不读取算法配置，也不计算目标函数。它们的正式输入输出口径见
`markdown/DATA_MODULE_SUMMARY.md`。

### `modeling/`：可微建模层

- `context.py`：`SiteProblemContext`，一次实验共享的 numpy/PyTorch 数据包；分别保存 HaulField 使用的土地约束掩膜，以及建筑硬评价使用的土地约束、道路退距和水体退距合并掩膜。道路退距是遥感类别 3 与 OSM 中心线并集的 1 m 距离变换，默认 5 m。水体退距是土地类别 5 的 1 m 距离变换，默认 5 m，只进入建筑硬掩膜。
- `pose.py`：raw pose 到 bounded pose 的参数化和边界计算。
- `masks.py`：候选矩形的 soft footprint 和 hard footprint。
- `dem_model.py`：DEM soft/hard 指标。
- `slope.py`：足迹内最大坡度，只用于报告。
- `footprint_terrain.py`：足迹内各用地类别占比和高程落差，只用于助手的方案分析。
- `logistics_cost.py`：一次构建道路端点图，并为一个进货原点预计算单源最短路；查询站址路径和分段长度，以专用异常区分真实道路不连通。
- `construction_cost.py`：保留的独立单点进站路径与对照接口，不再作为方案报告或地图黄线的权威路径；`rasterize_road_mask()` 复用 Gate 的 `_road_cells()` 栅格化规则，提供无宽度的 OSM 中心线格，再由 `context.py` 做建筑退距。
- `haul_field.py`：一次优化建一次的进站距离场。用 Numba 加速多源 Dijkstra，按逐步水平距离加高程惩罚选路，长度和累计高差分别报告；进站固定八连通，斜步不抄障碍角。有进货原点时只让同一道路分量内的 Gate 初始化距离场；同时记录紧凑前驱、Gate 归属、道路接触点和接触路段。优化查表、方案报告和地图黄线由同一字段给出。可选的 `connector_blocked` 拒绝穿过永久基本农田缓冲区的 Gate 到道路中心线短线；不传时与原来相同。
- `haul_model.py`：距离场的双线性插值，只给前期梯度引导使用。格子中心上等于精确查表。
- `access_path.py`：直线进站路径，只留作对照测试。报告和搜索不再使用它。
- `obstacle_model.py`：障碍物 soft overlap 和 hard count/ratio。
- `road_model.py`：候选点到道路的距离。
- `demand_model.py`：候选点到需求点的加权距离。
- `site_model.py`：`SiteObjective`、`SiteConstraint` 和 `SiteModel`。改一个目标或一条硬约束时继承这里的类。
- `evaluator.py`：调用默认 `SiteModel`，保持原来的函数入口。
- `numpy_evaluator.py`：原版 soft/硬指标/精确进站评价装配，支持 CPU 和 CUDA 模型。
- `tensor_evaluator.py`：演化用的分批设备评价器，缓存硬掩膜与进站距离场；道路格候选保留精确 CPU 查询。

### `algorithms/`：算法层

- `guided_search/search.py`：决策界面的引导式多目标搜索。默认比较平整度、进站长度与累计高差；需求目标和进货原点按配置增加比较项。支配比较用精确查表，不收成权重。
- `guided_search/evolution.py`：配置后端分派、CPU 时选择 NumPy，以及两后端共用的退火日程与输出。
- `guided_search/numpy_nsga2.py`：原版逐对支配排序与 NumPy 随机流，供显式对照或 CPU 回退。
- `guided_search/tensor_nsga2.py`：设备常驻种群、批量锦标赛/算术交叉/高斯变异、约束分层、拥挤距离与环境选择。
- `guided_search/initialization.py`：原始高斯、均匀和田口采样，以及允许域内按面积均匀采样与实际方法选择。
- `guided_search/guide.py`：进化前的短程梯度引导；初始化和每步引导检查中心点硬格与原始多边形。损失不参加支配。
- `cma_es/`：CMA-ES 搜索核心和该算法的入口。研究脚本仍使用它。
- `multistart_adam/`：多起点 Adam 搜索核心和入口。
- `vae_like_multihead/`：VAE-like multi-head 模型、训练和入口。
- `common/`：多个算法共享的多目标工具，包括 `SiteSearch` 父类、scalarization、Weiszfeld 和 Pareto。新的搜索继承 `SiteSearch`。
  其中 `cma_es/pareto.py` 与 `cma_es/weiszfeld.py` 只是兼容导出，不维护第二份实现。

每个算法目录中，`*_main.py` 只负责加载配置、组装实验和写输出；算法数学和搜索循环留在同目录的核心文件中。
算法口径见 `markdown/ALGORITHMS_MODULE_SUMMARY.md` 及其链接文档。

### `experiments/`：实验装配层

`validate_evolution_backends.py` 验证显式后端选择和无 GPU 的真实场景回退；`compare_tensor_nsga2.py` 在同一场景下对照旧 Git 版本与多个张量版种群规模，保存完整搜索耗时、显存及共同参考下的前沿质量。

`scene_store.py` 还登记苍南/永嘉的固定四文件输入，把完整构建先写到临时目录再发布到 `scenes/`，并为未构建的预置场景提供真实 GeoTIFF 预览 frame。

- `problem_context.py`：调用四个数据 tool，构造一个共享的 `SiteProblemContext`。`scene_store.py` 把构建好的场景放在 `scenes/`，优化只读取这个目录；它还提供只重建道路 bundle 的备份、临时验证、发布标记和失败恢复流程，从现有 DEM 生成不影响场景就绪状态的彩色地图缓存，以只读形式提供现有局部道路段，并把土地硬约束与道路退距合成的建筑禁建格渲染为内存中的建设可行性 PNG。这张图不是旋转站址的完整判定，也不进入进站距离场。`constraint_mask.py` 在搜索前按用地类别和手绘禁区、可行域合成硬掩膜与软代价掩膜，不改写场景文件。`protected_farmland.py` 把确认后的永农栅格并入这组硬掩膜，并生成进站通行缓冲；没有该文件的场景不增加约束。`official_water.py` 在写出最终用地前，把 `masking_pipeline/data/regional/water_polygons` 里 `fclass=water` 的面按场景仿射变换栅格化并并入类别 5，其他类别跳过。`water_lines.py` 先把 `water_lines` 纠偏到遥感河道中心，再估计河宽。两端可靠且不超过 200 m 的缺口用两端河岸直线连成面；其余缺口沿纠偏后的官方线按已有宽度做窄走廊，只跳过明显拐折或贴着别的水面的局部。融合前的道路和建筑格子不改成水体。结果补进类别 5。建设可行性 PNG 同时包含当前水体退距。`landuse_patch.py` 把点击处的四连通同类区域收成禁区外环；`landuse_edits.py` 按场景保存人工分类图斑，并从原始场景基准栅格重建有效土地利用、建设掩膜和着色图层。`haul_field_cache.py` 用安全数组文件和 JSON 清单在共享场景卷中发布按源文件/实际数组/完整约束/原点寻址的 `HaulField`，供 Worker、`site-report` 和 `pose-objectives` 跨进程复用，并负责原子写入、损坏回退和容量清理。`site_report.py` 汇总足迹坡度、运输成本和进站坡度；新请求复用 `constraint_mask.py` 合成当前 hard mask，先查容量 1 的进程内缓存，再查共享距离场缓存，旧请求保持静态掩膜兼容，不运行搜索。`launch_site_run.py` 在引导式搜索前取得并发布共享距离场，另存 `site_form_snapshot.json`，保留重现约束所需的已校验原始任务表单。
- `output_writer.py`：统一写入 CSV、摘要、候选图和 Pareto HTML。界面搜索由 `launch_site_run.py` 在临时目录写完后整体发布，覆盖失败保留旧实验，成功时不混入旧文件。
- `partitioned_search.py`：把统一场景安全中心范围切成矩形，限流并发运行有界 Guided Search，共享全局 HaulField，在全局坐标上复核候选并写入一个合并实验结果；算法口径见 `markdown/GUIDED_SEARCH.md`。
- `run_cma_es_region.py`、`run_multistart_adam_region.py`、`run_vae_like_multihead_region.py`：三个算法的命令入口。
- `validate_modeling.py`：小规模端到端建模验证。
- `compare_initialization.py`：固定场景及其余参数，对比高斯、均匀和田口正交初始化；保存阶段位姿及共同参考下的前沿质量。`plot_initialization_comparison.py` 只读取已完成结果，生成指标箱线图和阶段点位图。
- `diagnose_road_alignment.py`：道路坐标对齐的诊断脚本，不属于正式算法流程。
- `compare_road_voronoi.py`：原始 CPU 与 GPU 的完整栅格构建对照，包含原场景和明确标注的 9 km 压力场景，保存精确标签哈希、时间和显存。
- `diagnose_road_topology.py`：只读比较原始、旧简化和拓扑保持简化网络，并可报告指定原点在已发布场景中的分量及 Gate 可达数。
- `agent_eval.py`、`agent_eval_cases.json`：用固定请求给助手打分。它复用 `backend/app/application/agent_gateway.py` 的工具上下文，让评测和线上对话用同一套工具。这是 `experiments/` 里唯一引用 `backend/` 的文件。

## 软件外壳

### `agent/`

独立于 HTTP 的助手包。`config.py` 读取模型环境变量。`workspace.py` 定义工作区快照、编辑操作和 `validate_ops`。`tools.py` 注册只读工具。`llm.py` 调用 OpenAI 兼容接口。`loop.py` 跑一轮对话，连续出错的只读工具会在本轮内撤下。`prompts.py` 放系统规则、每种操作的说明卡，并把记忆拼进系统提示。`memory.py` 读写本机 `memory/MEMORY.md`，校验并执行记忆改动。`analysis.py` 用快照里的目标值给一个方案排名，并定出本次比较的目标和可参加比较的方案（有目标值且未标为不可行），供 `analyze_pose` 和 `recommend_poses` 使用。`preference/` 读本机 `memory/` 下用户设的默认重要程度和点下的选择，以前者为起点、用 SLFN 学效用，给快照里的方案排出带多样性和占优理由的推荐。它不读原始栅格，也不修改地图；确认后的地图写入在前端 `edit_ops.ts`，记忆和选择记录分别走各自的 Agent API。

### `backend/app/`

- `main.py`：FastAPI application factory，组装 service、queue、repository 和 experiment catalog。
- `api/routes.py`：HTTP 请求/响应模型和路由；不写算法实现。方案重算接口只转调 `experiments.launch_site_run.evaluate_form_poses`；建设可行性接口只转调场景层的只读 hard mask PNG 渲染。`/software-update` 只校验密码和是否允许快进，真正的拉取和重启在 `restart.sh`。
- `software_update.py`：核对 `UPDATE_PASSWORD`、拒绝脏工作区，并在新会话里启动 `restart.sh`（脚本停 API 时跳过自己）。密码不进入命令行。
- `api/agent_routes.py`：agent 对话、操作 schema、记忆读写和偏好（默认重要程度、选择记录）接口。对话只组装配置、记忆、工具上下文和 `run_turn`，并把正文增量按行转给页面。
- `application/agent_gateway.py`：把场景、实验目录、插件、单点报告和选择记录装进 agent 的 `ToolContext`。
- `domain/plugins.py`、`domain/jobs.py`、`domain/experiments.py`：领域协议和不可变记录。
- `application/registry.py`：显式插件注册；`application/service.py`：提交、执行和查询任务的用例。
- `infrastructure/repository.py`：任务存储适配器。
- `infrastructure/queue.py`：内存队列和 Redis 队列适配器。
- `infrastructure/postgres_repository.py`：PostgreSQL 任务存储适配器。
- `infrastructure/experiment_catalog.py`：扫描 `outputs/` 下已完成的实验目录，安全地暴露产物，并删除其中一个已完成目录。

### `frontend/src/`

地图工作区从场景 API 取得 `SiteFrame`。顶部苍南/永嘉切换会重挂地图，并清空上一场景的临时编辑、方案、比较和图层缓存；历史方案只有 `scene_name` 与当前场景相同才允许导入。

- `App.tsx`：应用外壳。当前只挂决策地图，并显示服务健康状态。
- `agent/`：决策地图上的助手。`workspace_snapshot.ts` 把 `SiteEdit` 收成快照，并从快照拼出一次选择记录，`edit_ops.ts` 把提案应用到这份编辑，`agent_api.ts` 发送对话和选择记录，`memory.ts` 读写记忆并描述记忆改动，`preference.ts` 读写各目标的默认重要程度，`agent_panel.tsx` 展示差异、等待确认，并有「记忆」「偏好」页。读写口径见 `markdown/AGENT_MODULE.md`。
- `map/`：公开卫星世界地图。`basemap.ts` 只放瓦片地址。`SiteFrame` 保存局部米网格，并按旋转后矩形的真实角点限制完整建筑边界。`BuildingFootprint` 计算带朝向的建筑矩形。`SiteEdit` 统一保存禁区、可行域、点选同类、进货原点和候选方案，再生成搜索、单点报告和精确重算请求。`favorite_points.ts` 封装 WGS84 收藏记录与局部坐标/建筑朝向转换；`favorite_store.ts` 管理按场景访问代次隔离的收藏列表、写请求和拖动预览，`use_favorite_points.ts` 将它接入 React；`favorite_evaluation.ts` 组装当前约束与收藏自身尺寸，依次调用既有目标和运输报告接口；共享报告类型放在 `site_report_types.ts`。`favorite_panel.tsx` 展示详情、宽边方位调整和删除。人工点图与优化方案收藏共用同一个保存入口，收藏状态不进入 `SiteEdit`；功能口径见 `markdown/FRONTEND_IMPLEMENTATION_SPEC.md` 7.5。`landuse_sketch.ts` 负责土地类型类别映射和已保存图斑的点位查询；自由勾画复用禁区/可行域的拖动笔迹简化，场景 API 保存图斑，刷新页面后仍读取这些图斑，不进入 `SiteEdit`。已保存图斑的边线默认不显示。图斑类别为农田、建筑、道路区域和水体。`GuidedDecisionRun` 提交 `site.guided_search`（含方框内的局部优化）并读取该次帕累托方案；`refinedChoices` 挑出局部优化并入地图的方案，`measuredChoice` 把 `pose-objectives` 的重算记录写回方案。`decision_run.ts` 同时保存原始 pose 和原始指标，负责度/弧度转换、合法移动、合法旋转、单步恢复，以及“原值 → 调整后值”文本。`ExclusionSketch` 负责把自由笔迹简化成闭合圈。`MapShortcuts` 处理快捷键，包括 Ctrl+Z 恢复最近一次擦除的范围或进货原点。`toolbar_commands.ts` 和 `map_toolbar.tsx` 是顶部功能区，页签为文件、主页、视图、编辑、设置；「文件 → 新建场景…」打开 `scene_build_dialog.tsx`，经纬度表单和构建进度在这个弹窗里，关闭窗口不取消任务，任务轮询仍在 `map_workspace.tsx`。「文件 → 导出优化场景 PNG…」打开 `scene_export_dialog.tsx`，用当前 MapLibre 画布合成 PNG。「文件 → 导入数据」打开 `farmland_import_dialog.tsx`，预览并确认永久基本农田；GIS 面板只控制显示。图层和 Pareto 勾选只作用于这一次导出；`scene_export.ts` 从已有 `diversityPool` 按 `paretoLayer` 筛选，不重算层级，也不改工作区图层、方案或视角。左侧工作栏只保留选址优化。主页预置场景准备的文案是「准备当前场景数据」。主页和左侧工作栏的「清空方案」以及 Agent 的 `clear_poses` 最终都调用 `map_workspace.tsx` 的统一清理流程，方案代次号阻止导入、优化、重算和报告的旧响应回填。「设置」里的「浅色主题」由 `theme.ts` 记在浏览器里，只改面板和文字。「软件更新」由 `software_update_dialog.tsx` 打开密码框，轮询逻辑在 `software_update.ts`。常驻「图层」入口打开 `layer_panel.tsx`，集中控制 DEM、四类 landuse、建设可行性、OSM 道路和两类用户范围。`feasibility_overlay.ts` 只负责从搜索配置提取约束请求，以及旧请求和 Blob URL 生命周期。禁区和可行域在编辑页各有画圈、方框两个二级选项；橡皮擦依次命中进货原点、收藏点、人工土地图斑、用户绘制范围，悬停目标由 `site_overlay.tsx` 高亮。「导入案例」由 `history_panel.tsx` 列出、导入和删除已完成结果。`world_map.tsx` 负责平移缩放、连续拖拽事件及土地类型图斑编辑和橡皮擦删除，`site_overlay.tsx` 管理栅格、道路、范围、候选和交互对象的叠放，`scene_build.ts` 只做坐标表单的换算、校验和建成场景的精确选择。`map_workspace.tsx` 组装页面状态，并管理场景图斑读写、坐标构建进度、角度输入、单步恢复和带配置快照校验的重新评价状态。
- `problem_overview.tsx`：问题概览，展示区域、数据图层、目标顺序、可行性规则和地图预览。
- `problem_snapshot.ts`：把实验 manifest 中的产物适配成 `ProblemSnapshot`，不计算目标、约束或坐标。
- `job_workspace.tsx`：任务功能模块，封装插件列表和配置提交。它不轮询任务。
- `run_monitor.tsx`：配置页的任务轮询模块，展示排队、运行、完成、失败、配置摘要和重新运行。决策地图不挂这个模块，它只对自己提交的任务调用 `getJob`。
- `run_status.ts`：把任务状态、配置和失败信息格式化成展示文本，不发起请求。
- `experiment_browser.tsx`：实验结果列表，展示算法、完成时间和摘要数量。
- `result_explorer.tsx`：单个实验的地图、方案详情、目标对比、Pareto HTML 和方案表格。表格、对比图和详情共用同一个选中方案。
- `solution_record.ts`：从 `solutions.csv` 与 `pareto_solutions.csv` 读取方案字段，不计算目标或 Pareto。
- `config_form.tsx`：根据 JSON Schema 递归渲染配置表单，按领域分组显示单位、默认值和权重预设。
- `config_check.ts`：提交前检查必填、数值范围、权重和与实验名覆盖；不代替后端校验。
- `api.ts`：前端 API 类型和请求函数；`site-report` 接收 pose 和当前完整搜索约束，按搜索同一 hard mask 返回施工与进站报告；`pose-objectives` 接收当前搜索配置和一个或多个 pose，按搜索同一口径返回精确 objective 与 hard constraint 字段；`construction-feasibility-overlay` 接收当前约束并返回 PNG Blob；`loadProblemSnapshot` 只按 manifest URL 读取问题概览。`generated/api.ts` 是 OpenAPI 自动生成文件，不手工编辑。
- `backend/app/api/favorites_routes.py`：收藏点 CRUD 的 HTTP/schema 边界；`backend/app/infrastructure/favorite_repository.py`：SQLite 持久化，数据与场景栅格隔离。
- `main.tsx`：React 挂载点；`styles.css`：全局视觉样式。

前端模块通过 `api.ts` 访问后端，不直接读取 `outputs/`，也不包含算法逻辑。当前打开的页面只有决策地图。`job_workspace.tsx`、`experiment_browser.tsx` 和 `problem_overview.tsx` 仍留在仓库里，没有挂到 `App.tsx`。

### `plugins/`、`worker/`、`deploy/`

- `plugins/demo/plugin.py`：用于验证软件外壳链路的确定性 Demo 插件。
- `plugins/site_plugin.py`：引导式多目标搜索、矩形分区并行搜索、CMA-ES、多起点 Adam、预置场景构建和 `site.build_scene` 的配置 schema。决策界面使用 `site.guided_search`；`site.partitioned_guided_search` 通过现有 Jobs API 调用，不改前端。界面不注册 VAE-like。
- `experiments/coordinate_scene.py`：校验经纬度和边长，调用 masking pipeline，检查四文件，再把现有场景重建接到该 bundle。
- `masking_pipeline/`：上游流水线源码。`run.py` 是 CLI 和 `run_pipeline`。区域 PBF、DEM、水系面 `water_polygons` 和水系线 `water_lines` 都在 `masking_pipeline/data/regional/`。
- `experiments/launch_site_run.py`：把表单配置交给引导式多目标搜索、CMA-ES 或 Adam 入口，并写入一个实验目录。它读取 `scenes/` 里已构建的数据，不在这次搜索里重建 DEM、道路或需求点。引导式多目标搜索不使用目标权重。`constrained_problem` 是搜索和单点重算共用的场景加约束装配；`evaluate_form_poses` 按同一口径重算搜索之外的位姿，供 `pose-objectives` 接口使用。研究用的 CMA-ES 仍沿项目 `weight_grid_step` 搜索。Adam 仍使用提交的一组权重。`site.prepare_scene` 才负责重新构建场景。
- `worker/main.py`：独立 worker 进程入口，复用 backend 的 service 和基础设施适配器。
- `deploy/compose.yaml`：API、worker、Redis、PostgreSQL 和前端的生产形态编排；API 与 worker 共用只读 `data/` 和可写 `scenes/`、`outputs/` 绑定挂载。`deploy/compose.masking.yaml` 只补充 worker 的模型缓存和设备设置。
- `worker/requirements.txt`：worker 镜像的地理处理和 CPU PyTorch 依赖。API 镜像仍只用 `backend/requirements.txt`，所以 API 启动链（含 `config/project_config.py`）不能在模块顶层导入 PyTorch；`tests/test_project_config.py` 保护这一点。

## 测试文件的对应关系

测试文件按被保护的职责命名，不按实现细节命名：

- `conftest.py`：CUDA 测试夹具。
- `fixtures/`：landuse 类别样例，供映射测试读取。
- `test_landuse_mapping.py`：landuse 类别到 obstacle mask 的映射。
- `test_landuse_prompt.py`、`test_landuse_patch.py`：分割占位接口和点选同类区域。
- `test_pose_and_masks_cuda.py`、`test_objectives_cuda.py`：CUDA pose、footprint 和 soft objective。
- `test_hard_metrics.py`、`test_site_model.py`：hard metrics、可行性口径和建模对象。
- `test_construction_cost.py`、`test_construction_report.py`、`test_site_report_api.py`：单点进站长度、动态约束方案报告、静态掩膜兼容、字段缓存复用/失效和 API 完整约束校验。
- `test_traffic_topology.py`、`test_haul_field.py`、`test_haul_model.py`、`test_cangnan_haul_field.py`：道路简化拓扑、进站距离场查表及前驱回溯、道路连通性、5 cm 末段规则、真实场景 40 个参考位置的可达/不可达与指标一致、Gate 过滤和可微插值。固定输入在 `tests/fixtures/cangnan_p2b_reference.csv`。`test_osm_building_avoidance.py` 检查 OSM 中心线建筑禁建、旋转足迹、土地/手绘约束叠加、Pareto 过滤、道路更新失效和 HaulField 隔离。`test_road_setback.py` 检查遥感道路与 OSM 中心线的并集退距、零退距、非法参数、进站隔离，以及优化、重算和可行性预览的同一建筑掩膜。
- `test_evolution_backends.py`：双后端配置、原版固定 seed、CPU 全流程和无 GPU 任务产物、分区继承及 CPU/CUDA 评价一致性。
- `test_tensor_nsga2.py`、`test_tensor_hard_metrics.py`：张量算子对照标量参考、固定 seed 复现，以及批量硬足迹与报告几何一致。
- `test_guided_search.py`、`test_search_guide.py`：引导式多目标搜索的支配比较、一次建场、重算与方案表一致，以及前期引导。
- `test_constrained_initialization.py`：只测撒点和前期引导，独立几何检查中心点位于可行域并集内、禁区外；不运行演化。
- `test_cma_es_utils.py`、`test_multistart_adam.py`、`test_vae_like_multihead.py`：其余算法的公共数学和搜索组件。
- `test_constraint_mask.py`、`test_construction_feasibility_overlay.py`、`test_landuse_edits.py`、`test_scene_store.py`、`test_launch_site_run.py`、`test_coordinate_scene.py`：用地掩膜、人工图斑写入与恢复、建设可行性 PNG/API、场景目录、坐标构建任务和决策任务装配。
- `test_site_plugin_schema.py`：选址插件的配置校验。
- `test_figures.py`、`test_experiment_output_writer.py`：公共图件和实验输出契约。
- `test_v0_plugins.py`、`test_v0_api.py`、`test_v0_experiments.py`：插件、任务 API 和实验 artifact API。
- `test_agent.py`：编辑操作校验（含 `refine_pose` 的限制和前后端半宽界限）、前后端 op 清单、说明卡覆盖、只读工具循环和护栏、评测打分规则，以及未配置时的 503。
- `test_agent_memory.py`：记忆文件格式和报错行号、缺文件时自动创建、三种记忆改动、按场景筛选、只带记忆的提案、记忆接口和记忆评测打分。
- `test_agent_analysis.py`：足迹地形统计、方案排名、`analyze_pose` 在进站报告出错时的返回、附件消息的转写和 422，以及方案重算接口的表单装配和 422。
- `test_invalid_inputs.py`：明确拒绝非法输入，而不是静默兜底。

## 测试和文档

- `tests/test_*.py`：模块边界和协议的轻量回归测试，不运行完整大实验。
- `markdown/TESTING_STRATEGY.md`：pytest 与端到端验收的边界。
- `markdown/LOCAL_RUN_GUIDE.md`：本机运行命令。
- `markdown/EXPERIMENT_LOG.md`：已经完成的实验唯一记录。
- `markdown/V0_ARCHITECTURE.md`：软件外壳的任务流、插件协议和部署结构。
- `markdown/DECISION_REQUIREMENTS.md`：尚未实现的分割、点选标注和施工成本需求。

如果新增文件不能在本地图中归入一个明确职责，应先调整模块边界或补充本文，再开始实现。
