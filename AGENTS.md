# AGENTS.md

这个项目后续会重新建一个新仓库来维护和重写。新仓库不兼容旧代码，也不从旧代码直接构建。所有用于新仓库建设的信息都必须先沉淀到 markdown 文档里，agent 构建新仓库时只服从这些 md。

新仓库的目标是服务科研实验和算法开发：结构清晰、参数可控、实验可复现、算法模块容易替换和扩展。不要把它做成大量兜底的工程产品。

## 文档分工

`AGENTS.md` 只负责新仓库的主题框架、设计原则和执行优先级。同一件事只在一份权威文档里写完整，其他地方只保留路径。

| 文档 | 职责 |
| --- | --- |
| `markdown/DATA_MODULE_SUMMARY.md` | 数据读取、坐标转换和四个数据 tool 的输出 |
| `markdown/MODELING_MODULE_SUMMARY.md` | geometry、objective、constraint、metric 和 evaluator |
| `markdown/ALGORITHMS_MODULE_SUMMARY.md` | 算法模块总览，并指向下面的算法文档 |
| `markdown/ALGORITHM_COMMON.md` | 目标顺序、权重、normalization、切比雪夫、Weiszfeld、Pareto |
| `markdown/CMA_ES.md` | CMA-ES |
| `markdown/NSGA2.md` | 决策界面使用的 NSGA-II |
| `markdown/MULTISTART_ADAM.md` | 多起点 Adam |
| `markdown/VAE_LIKE_MULTIHEAD_ALGORITHM.md` | VAE-like multi-head |
| `markdown/VALIDATION.md` | 等间距偏好验证集 |
| `markdown/FIGURES_MODULE_SUMMARY.md` | 公共作图 |
| `markdown/TESTING_STRATEGY.md` | pytest 与验收脚本的边界 |
| `markdown/LOCAL_RUN_GUIDE.md` | 本机端到端运行 |
| `markdown/EXPERIMENT_LOG.md` | 已完成实验的唯一记录 |
| `markdown/V0_ARCHITECTURE.md` | v0 软件外壳、插件边界、任务流和部署结构 |
| `markdown/AGENT_MODULE.md` | agent 与软件数据的读写接口、工具和确认流程 |
| `markdown/CODE_MAP.md` | 当前目录、文件职责和跨模块依赖方向 |
| `markdown/FRONTEND_IMPLEMENTATION_SPEC.md` | 前端页面、交互、可视化和分阶段实施验收 |
| `markdown/DECISION_REQUIREMENTS.md` | 尚未实现的分割、点选标注和施工成本需求 |
| `README.md` | 环境、入口命令和公开函数 |

后续 agent 的工作顺序：

1. 先读 `AGENTS.md`，理解总体架构和本文的维护规则。
2. 再读上表中与本次任务对应的权威文档。继续做实验时，同时读 `markdown/EXPERIMENT_LOG.md`。
3. 按这些 md 实现或修改。
4. 权威文档信息不足时，先补充对应 md，不回看旧仓库代码。
5. 改完后同步权威文档；若本次是一次完成的实验，追加实验记录。满足下文 Git 联动条件时提交。

## 总体原则

- 不兼容旧代码。旧仓库不是新仓库的接口约束，也不是直接实现来源。
- 新仓库建设只服从 md 中已经整理出的信息。
- 优先做参数化和模块化设计，不要把实验参数写死在函数内部。
- 保持科研代码的直接性：输入缺失、参数不合法、数据格式不对时，明确报错。
- 每个模块只负责自己的事情：数据模块不写算法，算法模块不偷偷找数据，实验脚本只负责组装实验。
- 新增功能优先提供清晰配置入口，例如 dataclass config、CLI 参数或显式函数参数。
- 目标顺序、坐标变换和实验输出口径必须写清楚。

## 新仓库三大模块

### 1. 数据模块

负责数据读取、转换、校验和实验数据包构建。数据模块当前只聚焦四类核心数据：DEM、不可建设区域掩膜、OSM 道路 Voronoi、随机需求点。

数据模块最终输出给后续模块的矩阵必须统一到同一个 1 m 分辨率局部栅格。当前默认输入为 10 m DEM tif、1 m landuse csv、WGS84 道路 GeoJSON 和随机需求点；数据模块负责把最终矩阵产物统一成 1 m。除需求点以外，DEM、landuse、obstacle mask、road Voronoi 都应是空间范围一致、shape 一致、分辨率一致的 `np.ndarray`。需求点是与这些 1 m 输出矩阵处于同一空间范围和坐标原点下的连续二维坐标数组，不是矩阵，也不要求坐标为整数像素。具体输入、输出和坐标系约定以 `markdown/DATA_MODULE_SUMMARY.md` 为准。

职责：

- 读取 DEM tif，按局部栅格数据处理，生成 1 m DEM 矩阵。
- 读取 landuse csv，按局部栅格数据处理，生成不可建设区域掩膜。
- landuse 类别含义必须显式记录：`0=other/其他区域`、`4=mountain_natural/山体自然区域` 为可建设，映射到 obstacle mask `0`；`1=field/农田区域`、`2=building/建筑区域`、`3=road/道路区域`、`5=water/水体区域` 为不可建设，映射到 obstacle mask `1`。
- 读取 OSM 下载的道路 GeoJSON，经纬度转局部坐标后处理生成道路 Voronoi 图。
- 随机生成需求点，需求点数量和随机 seed 必须可配置。
- 输出四个数据 tool 的标准产物，后续模块按需读取。
- 记录数据来源、分辨率、坐标系、生成参数和 seed。

数据模块建议按四个数据处理 tool 理解，而不是按通用工程职责拆成 loaders/transforms。为避免原始数据和代码混放，新仓库中 `data/` 只存放原始输入数据文件，数据处理代码放在 `data_tools/`：

```text
data/                 # 原始输入数据，不放 Python 代码
data_tools/
  dem_tool.py        # 读取/处理 DEM，生成 1 m 对齐 DEM 矩阵
  landuse_tool.py    # 读取 landuse/obstacle，生成不可建设区域矩阵
  traffic_tool.py    # 读取 OSM 道路，简化道路并生成道路 Voronoi 交通图矩阵
  demand_tool.py     # 随机生成连续需求点
```

数据模块不要做算法训练，也不要计算目标函数。需求点可以随机生成，但必须由显式参数控制数量和 seed。

### 2. 建模模块

负责把数据模块四个 tool 的输出转成 PyTorch 可计算的建模目标。建模模块整体使用 PyTorch 框架维护，核心计算应支持批量输入，返回 shape 为 `[B]` 的张量或语义明确的字典。

职责：

- pose 参数化：连续 1 m 局部坐标 `[x, y, theta]`。
- raw pose 到 bounded pose 的 sigmoid reparameterization。
- DEM 建模：计算 DEM soft variance、hard variance、hard range。
- 不可建设区域建模：计算 obstacle soft overlap、hard count、hard ratio。
- 道路建模：基于 `road_segments_local` 和 `road_voronoi` 计算候选点到道路的距离。
- 需求点建模：计算候选点到需求点集合的加权距离。
- 所有建模输入都来自数据模块产物，不在建模模块读取原始 tif/csv/GeoJSON。

建模模块分为四个独立 py 文件构建：

```text
modeling/
  dem_model.py        # DEM 平整度建模
  obstacle_model.py   # 不可建设区域建模
  road_model.py       # 道路距离建模
  demand_model.py     # 需求点距离建模
```

关键约定：

- 建模模块不再使用 `cx10/cy10`，也不再做 10 m / 1 m 坐标映射。
- 数据模块已经统一到 1 m 局部坐标，建模模块直接使用 `[x, y, theta]`。
- 每个 py 文件只负责自己的建模目标，不互相读取原始数据。
- soft loss 使用 PyTorch 计算，用于训练。
- hard 指标不参与反向传播，只用于后验评价和报告。
- 具体函数输入、输出和公式以 `markdown/MODELING_MODULE_SUMMARY.md` 为准。

### 3. 算法模块

算法口径以 `markdown/ALGORITHMS_MODULE_SUMMARY.md` 及其指向的算法文档为准。`AGENTS.md` 不展开具体算法。

算法模块不读取原始 tif/csv/GeoJSON，也不重新实现建模目标。数据读取由 `data_tools/` 完成，目标和 hard 指标由 `modeling/` 完成。未写入上述文档的新算法，先补文档再写代码。

### 4. 软件交互外壳

v0 软件外壳由以下目录组成：

```text
frontend/   # React + TypeScript 用户界面
backend/    # FastAPI、领域协议、用例和基础设施适配器
worker/     # 后台任务执行入口
plugins/    # 显式注册的内置插件
agent/      # 对话、只读工具和编辑提案。确认前不改地图
deploy/     # Docker Compose 部署文件
```

外壳的接口和任务流以 `markdown/V0_ARCHITECTURE.md` 为准。Agent 的读写接口以 `markdown/AGENT_MODULE.md` 为准。外壳通过插件协议调用 `data_tools/`、`modeling/` 和 `algorithms/`，不把算法实现写入 API 或前端流程。

## 参数化要求

以下内容不应散落硬编码：

- 数据路径和四个数据 tool 的输出路径
- 分辨率：`res_grad_m`, `res_obs_m`
- 建筑矩形尺寸：`rect_w_m`, `rect_h_m`
- objective scales
- random seed
- device
- 输出目录和实验名称

优先使用 dataclass config。CLI 参数应映射到 config，而不是直接塞进长函数调用里。

## 不需要大量兜底

这个项目是科研实验代码，不需要把所有异常都吞掉或猜测用户意图。

推荐行为：

- 缺少正式输入：直接 `FileNotFoundError`
- shape 不符合预期：直接 `ValueError`
- objective order 不匹配：直接 `ValueError`
- 缺少可选依赖：在使用该功能时明确报错

不推荐行为：

- 找不到真实数据就自动生成随机数据继续跑正式实验
- 一个函数里尝试十几种路径命名规则
- 静默改变坐标方向或目标顺序
- 捕获所有异常后只打印 warning 然后继续

## 新仓库建设优先级

1. 先设计新仓库目录结构：`data/`、`data_tools/`、`modeling/`、`algorithms/`、`experiments/`、`tests/`。
2. 建立四个数据 tool 的输出格式和 config 数据结构。
3. 实现四个建模 py 文件：`dem_model.py`、`obstacle_model.py`、`road_model.py`、`demand_model.py`。
4. 算法实现服从 `markdown/ALGORITHMS_MODULE_SUMMARY.md` 及其指向的算法文档。
5. 如果需要补充实现细节，先补充对应权威 md，再继续实现。

## 测试与验证

重写时优先保护小型 deterministic 测试，而不是一上来跑完整大实验。

验证重点：

- objective order 清楚且有测试。
- hard feasible 判断清楚且有测试。
- 1 m 局部坐标、边界范围和 pose bounds 清楚且有测试。
- 新仓库的 TSV/JSON 输出字段统一、清晰，并记录字段含义。

## 代码风格

写代码时同时遵守这三条：尽量短、只加必要注释、按职责拆开。没有第二个使用方、也看不出要替换实现时，不要为扩展预留接口、配置或抽象。

- 函数名体现领域含义，例如 `evaluate_site_objectives`, `build_problem_context`, `compute_hard_constraints`。
- 能用现有函数或语言自带能力完成的，不另写一层。长函数按职责拆，不为减少行数做机械切分。
- 注释只解释非显而易见的口径，例如坐标方向、单位、目标顺序，或为什么把边界划在这里。不复述代码在做什么。
- 一个模块只做一件事，模块之间用明确数据结构传递，不依赖全局变量。绘图、文件写入、训练循环、目标计算分开。
- 研究参数写进 config，实验结论写进 markdown 或 summary 输出，不写在算法核心里。

## 文档维护

项目文档必须可读、干净、规范。框架留在 `AGENTS.md`，口径留在上表的权威文档，完成的实验留在 `markdown/EXPERIMENT_LOG.md`。

写作时遵守：

- 中文文档保持中文。`README.md`、`markdown/LOCAL_RUN_GUIDE.md`、`markdown/TESTING_STRATEGY.md` 保持英文，不在同一节里中英混写。
- 标题层级连续。路径使用仓库相对路径，并保证文件真实存在。
- 改口径时只改权威文档，再检查文档地图里的索引是否仍指向它。
- 发现断链、两处口径不一致，或文档和仓库现状不符时，先改正文档，再改代码。

### 过期文件

过期文件是指：已被新文档整篇替代且不再被引用的草稿，实验记录里标为作废并确认不再保留的输出目录或压缩包，以及编辑器残留和重复临时文件。

每次完成一次实验或一轮文档更新时核对一次。不另建待清理清单。尚未判定的存疑产物写在 `markdown/EXPERIMENT_LOG.md` 的「存疑产物」中，判定后再删。

清除时：

- 先写明删除对象和原因，再删除。
- 不删除 `data/` 中的原始输入。
- 不删除仍被文档地图引用的权威文档。
- 不删除实验记录中状态仍为「有效」的产物。
- 一次清理单独提交，提交说明写清删了什么、为什么删。

## 实验记录

`markdown/EXPERIMENT_LOG.md` 是已完成实验的唯一记录。实验没跑完不写入。一次实验追加一条，不另开散落笔记，也不把结果数字复制进 `AGENTS.md`。

每条记录包含：记录日期、实验名、目的、入口脚本、关键配置、输出目录、主要结果、相关 git 提交、状态。状态只用「有效」或「作废」。作废后保留条目，产物按过期文件规则处理。

## Git 联动

有效且必要的改动，在权威文档和实验记录已经同步之后，用 git 提交，使仓库保持最新项目状态。

同时满足以下三条才提交：

1. 有效：代码、权威文档、测试口径和实验记录一致。
2. 必要：这次改动完成了一项目标，而不是试探性中间态。
3. 已同步：被影响的权威文档已更新；若是一次完成的实验，`markdown/EXPERIMENT_LOG.md` 已追加。

一次提交包含这次更新的代码、对应权威文档和实验记录。提交说明写清为什么改。不提交密钥和 `.env`。不把未完成、未记录的临时输出提交成正式状态。不 push，除非用户明确要求。

## 给后续 agent 的一句话

新仓库按数据、建模、算法三层维护。实现依据来自 `AGENTS.md` 和文档地图中的权威 md。文档只保留一份可读口径，过期文件按记录清除，完成的实验写入 `markdown/EXPERIMENT_LOG.md`，有效且必要的更新用 git 提交到最新项目状态。
