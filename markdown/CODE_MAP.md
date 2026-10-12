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
```

## 研究代码

### 根目录和配置

- `pyproject.toml`：Python 工具链和项目元数据。
- `environment.yml`：研究环境及 CUDA/PyTorch 依赖。
- `config/project_config.py`：配置 dataclass、JSON 读取、校验和保存。
- `config/default_config.json`：默认实验参数，不放算法实现。110 kV 变电站占地默认 `rect_w_m=77`、`rect_h_m=51.5`，决策界面和接口都可以改。
- `validation_data/build_preferences.py`：生成固定的验证偏好权重表。
- `validation_data/preferences_step_0.1.csv`：验证集的确定性输入数据。

### `data_tools/`：数据处理工具

- `dem_tool.py`：读取 DEM，并重采样到统一的 1 m 局部栅格。
- `landuse_tool.py`：读取 landuse，执行类别映射并生成 obstacle mask。
- `landuse_prompt.py`：点击分割的可替换接口。当前占位实现明确报错，不加载模型。
- `traffic_tool.py`：读取 OSM GeoJSON，转换局部坐标、简化道路并生成 Voronoi 图。
- `demand_tool.py`：按数量和 seed 生成连续需求点。
- `io_utils.py`：研究产物的 JSON、数组和路径写入辅助函数。

数据 tool 不读取算法配置，也不计算目标函数。它们的正式输入输出口径见
`markdown/DATA_MODULE_SUMMARY.md`。

### `modeling/`：可微建模层

- `context.py`：`SiteProblemContext`，一次实验共享的 numpy/PyTorch 数据包。
- `pose.py`：raw pose 到 bounded pose 的参数化和边界计算。
- `masks.py`：候选矩形的 soft footprint 和 hard footprint。
- `dem_model.py`：DEM soft/hard 指标。
- `slope.py`：足迹内最大坡度，只用于报告。
- `footprint_terrain.py`：足迹内各用地类别占比和高程落差，只用于助手的方案分析。
- `logistics_cost.py`：从进货原点沿道路到站址的路径和分段长度。
- `construction_cost.py`：单点进场折线。方案报告和地图黄线用这里的格子路径，返回长度和高差，不乘权重。
- `haul_field.py`：一次优化建一次的进场距离场。格子中心上的长度和高差与 `TerrainHaulCost` 一致。
- `haul_model.py`：距离场的双线性插值，只给前期梯度引导使用。格子中心上等于精确查表。
- `access_path.py`：直线进场，只留作对照测试。报告和搜索不再使用它。
- `obstacle_model.py`：障碍物 soft overlap 和 hard count/ratio。
- `road_model.py`：候选点到道路的距离。
- `demand_model.py`：候选点到需求点的加权距离。
- `site_model.py`：`SiteObjective`、`SiteConstraint` 和 `SiteModel`。改一个目标或一条硬约束时继承这里的类。
- `evaluator.py`：调用默认 `SiteModel`，保持原来的函数入口。

### `algorithms/`：算法层

- `guided_search/search.py`：决策界面的引导式多目标搜索。不指定进货原点时比较四项，指定后加上沿路长度。支配比较用精确查表，不收成权重。
- `guided_search/guide.py`：进化前的短程梯度引导。损失只用于把种子推进可行区域，不参加支配。
- `cma_es/`：CMA-ES 搜索核心和该算法的入口。研究脚本仍使用它。
- `multistart_adam/`：多起点 Adam 搜索核心和入口。
- `vae_like_multihead/`：VAE-like multi-head 模型、训练和入口。
- `common/`：多个算法共享的多目标工具，包括 `SiteSearch` 父类、scalarization、Weiszfeld 和 Pareto。新的搜索继承 `SiteSearch`。
  其中 `cma_es/pareto.py` 与 `cma_es/weiszfeld.py` 只是兼容导出，不维护第二份实现。

每个算法目录中，`*_main.py` 只负责加载配置、组装实验和写输出；算法数学和搜索循环留在同目录的核心文件中。
算法口径见 `markdown/ALGORITHMS_MODULE_SUMMARY.md` 及其链接文档。

### `experiments/`：实验装配层

- `problem_context.py`：调用四个数据 tool，构造一个共享的 `SiteProblemContext`。`scene_store.py` 把构建好的场景放在 `scenes/`，优化只读取这个目录。`constraint_mask.py` 在搜索前按用地类别和手绘禁区合成硬掩膜与软代价掩膜，不改写场景文件。`landuse_patch.py` 把点击处的四连通同类区域收成禁区外环。`site_report.py` 汇总足迹坡度、运输成本和进场坡度，并读取场景栅格给出足迹地形统计，不运行搜索。
- `output_writer.py`：统一写入 CSV、摘要、候选图和 Pareto HTML。
- `run_cma_es_region.py`、`run_multistart_adam_region.py`、`run_vae_like_multihead_region.py`：三个算法的命令入口。
- `validate_modeling.py`：小规模端到端建模验证。
- `diagnose_road_alignment.py`：道路坐标对齐的诊断脚本，不属于正式算法流程。
- `agent_eval.py`、`agent_eval_cases.json`：用固定请求给助手打分。它复用 `backend/app/application/agent_gateway.py` 的工具上下文，让评测和线上对话用同一套工具。这是 `experiments/` 里唯一引用 `backend/` 的文件。

## 软件外壳

### `agent/`

独立于 HTTP 的助手包。`config.py` 读取模型环境变量。`workspace.py` 定义工作区快照、编辑操作和 `validate_ops`。`tools.py` 注册只读工具。`llm.py` 调用 OpenAI 兼容接口。`loop.py` 跑一轮对话，连续出错的只读工具会在本轮内撤下。`prompts.py` 放系统规则、每种操作的说明卡，并把记忆拼进系统提示。`memory.py` 读写本机 `memory/MEMORY.md`，校验并执行记忆改动。`analysis.py` 用快照里的目标值给一个方案排名，并定出本次比较的目标，供 `analyze_pose` 和 `recommend_poses` 使用。`preference/` 读本机 `memory/` 下用户设的默认重要程度和点下的选择，以前者为起点、用 SLFN 学效用，给快照里的方案排出带多样性和占优理由的推荐。它不读原始栅格，也不修改地图；确认后的地图写入在前端 `edit_ops.ts`，记忆和选择记录分别走各自的 Agent API。

### `backend/app/`

- `main.py`：FastAPI application factory，组装 service、queue、repository 和 experiment catalog。
- `api/routes.py`：HTTP 请求/响应模型和路由；不写算法实现。
- `api/agent_routes.py`：agent 对话、操作 schema、记忆读写和偏好（默认重要程度、选择记录）接口。对话只组装配置、记忆、工具上下文和 `run_turn`，并把正文增量按行转给页面。
- `application/agent_gateway.py`：把场景、实验目录、插件、单点报告和选择记录装进 agent 的 `ToolContext`。
- `domain/plugins.py`、`domain/jobs.py`、`domain/experiments.py`：领域协议和不可变记录。
- `application/registry.py`：显式插件注册；`application/service.py`：提交、执行和查询任务的用例。
- `infrastructure/repository.py`：任务存储适配器。
- `infrastructure/queue.py`：内存队列和 Redis 队列适配器。
- `infrastructure/postgres_repository.py`：PostgreSQL 任务存储适配器。
- `infrastructure/experiment_catalog.py`：扫描 `outputs/` 下已完成的实验目录，安全地暴露产物，并删除其中一个已完成目录。

### `frontend/src/`

- `App.tsx`：应用外壳。当前只挂决策地图，并显示服务健康状态。
- `agent/`：决策地图上的助手。`workspace_snapshot.ts` 把 `SiteEdit` 收成快照，并从快照拼出一次选择记录，`edit_ops.ts` 把提案应用到这份编辑，`agent_api.ts` 发送对话和选择记录，`memory.ts` 读写记忆并描述记忆改动，`preference.ts` 读写各目标的默认重要程度，`agent_panel.tsx` 展示差异、等待确认，并有「记忆」「偏好」页。读写口径见 `markdown/AGENT_MODULE.md`。
- `map/`：公开卫星世界地图。`basemap.ts` 只放瓦片地址。`SiteFrame` 保存一块局部米网格。`BuildingFootprint` 计算带朝向的建筑矩形。`SiteEdit` 是地图编辑：禁区、可行域、点选同类、进货原点和拖动方案都改这一份，再翻成现有的优化配置和单点报告。`GuidedDecisionRun` 提交 `site.guided_search` 并读取该次帕累托方案。`ExclusionSketch` 负责把自由笔迹简化成闭合圈。`MapShortcuts` 处理快捷键。`toolbar_commands.ts` 和 `map_toolbar.tsx` 是顶部功能区，页签为文件、主页、视图、编辑；拖拽、点选同类和定位留在地图右侧。禁区和可行域在编辑页各有画圈、方框两个二级选项，橡皮擦也在编辑页。新按钮加在命令表里。「导入案例」由 `history_panel.tsx` 列出已完成结果，导入后走 `GuidedDecisionRun.loadPareto`，删除调用实验目录删除接口。`world_map.tsx` 负责平移缩放，`site_overlay.tsx` 把这些对象画到地图上，`map_workspace.tsx` 只把它们组装成侧栏。
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
- `api.ts`：前端 API 类型和请求函数；`loadProblemSnapshot` 只按 manifest URL 读取问题概览。`generated/api.ts` 是 OpenAPI 自动生成文件，不手工编辑。
- `main.tsx`：React 挂载点；`styles.css`：全局视觉样式。

前端模块通过 `api.ts` 访问后端，不直接读取 `outputs/`，也不包含算法逻辑。当前打开的页面只有决策地图。`job_workspace.tsx`、`experiment_browser.tsx` 和 `problem_overview.tsx` 仍留在仓库里，没有挂到 `App.tsx`。

### `plugins/`、`worker/`、`deploy/`

- `plugins/demo/plugin.py`：用于验证软件外壳链路的确定性 Demo 插件。
- `plugins/site_plugin.py`：引导式多目标搜索、CMA-ES 和多起点 Adam 的选址配置 schema。决策界面使用 `site.guided_search`。界面不注册 VAE-like。
- `experiments/launch_site_run.py`：把表单配置交给引导式多目标搜索、CMA-ES 或 Adam 入口，并写入一个实验目录。它读取 `scenes/` 里已构建的数据，不在这次搜索里重建 DEM、道路或需求点。引导式多目标搜索不使用目标权重。研究用的 CMA-ES 仍沿项目 `weight_grid_step` 搜索。Adam 仍使用提交的一组权重。`site.prepare_scene` 才负责重新构建场景。
- `worker/main.py`：独立 worker 进程入口，复用 backend 的 service 和基础设施适配器。
- `deploy/compose.yaml`：API、worker、Redis、PostgreSQL 和前端的生产形态编排。

## 测试文件的对应关系

测试文件按被保护的职责命名，不按实现细节命名：

- `conftest.py`：CUDA 测试夹具。
- `fixtures/`：landuse 类别样例，供映射测试读取。
- `test_landuse_mapping.py`：landuse 类别到 obstacle mask 的映射。
- `test_landuse_prompt.py`、`test_landuse_patch.py`：分割占位接口和点选同类区域。
- `test_pose_and_masks_cuda.py`、`test_objectives_cuda.py`：CUDA pose、footprint 和 soft objective。
- `test_hard_metrics.py`、`test_site_model.py`：hard metrics、可行性口径和建模对象。
- `test_construction_cost.py`、`test_construction_report.py`：单点进场长度和方案报告。
- `test_haul_field.py`、`test_haul_model.py`：进场距离场查表和可微插值。
- `test_guided_search.py`、`test_search_guide.py`：引导式多目标搜索的支配比较、一次建场和前期引导。
- `test_cma_es_utils.py`、`test_multistart_adam.py`、`test_vae_like_multihead.py`：其余算法的公共数学和搜索组件。
- `test_constraint_mask.py`、`test_scene_store.py`、`test_launch_site_run.py`：用地掩膜、场景目录和决策任务装配。
- `test_site_plugin_schema.py`：选址插件的配置校验。
- `test_figures.py`、`test_experiment_output_writer.py`：公共图件和实验输出契约。
- `test_v0_plugins.py`、`test_v0_api.py`、`test_v0_experiments.py`：插件、任务 API 和实验 artifact API。
- `test_agent.py`：编辑操作校验、前后端 op 清单、说明卡覆盖、只读工具循环和护栏、评测打分规则，以及未配置时的 503。
- `test_agent_memory.py`：记忆文件格式和报错行号、缺文件时自动创建、三种记忆改动、按场景筛选、只带记忆的提案、记忆接口和记忆评测打分。
- `test_agent_analysis.py`：足迹地形统计、方案排名、`analyze_pose` 在进场报告出错时的返回、附件消息的转写和 422。
- `test_invalid_inputs.py`：明确拒绝非法输入，而不是静默兜底。

## 测试和文档

- `tests/test_*.py`：模块边界和协议的轻量回归测试，不运行完整大实验。
- `markdown/TESTING_STRATEGY.md`：pytest 与端到端验收的边界。
- `markdown/LOCAL_RUN_GUIDE.md`：本机运行命令。
- `markdown/EXPERIMENT_LOG.md`：已经完成的实验唯一记录。
- `markdown/V0_ARCHITECTURE.md`：软件外壳的任务流、插件协议和部署结构。
- `markdown/DECISION_REQUIREMENTS.md`：尚未实现的分割、点选标注和施工成本需求。

如果新增文件不能在本地图中归入一个明确职责，应先调整模块边界或补充本文，再开始实现。
