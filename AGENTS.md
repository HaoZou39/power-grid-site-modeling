# AGENTS.md

这个项目后续会重新建一个新仓库来维护和重写。新仓库不兼容旧代码，也不从旧代码直接构建。所有用于新仓库建设的信息都必须先沉淀到 markdown 文档里，agent 构建新仓库时只服从这些 md。

新仓库的目标是服务科研实验和算法开发：结构清晰、参数可控、实验可复现、算法模块容易替换和扩展。不要把它做成大量兜底的工程产品。

## 文档分工

`AGENTS.md` 只负责新仓库的主题框架、设计原则和执行优先级。

三个 summary md 负责保存具体模块信息：

- `markdown/DATA_MODULE_SUMMARY.md`：数据读取、数据构建、坐标转换和四个数据 tool 的输出逻辑。
- `markdown/MODELING_MODULE_SUMMARY.md`：建模逻辑，包括 geometry、objective、constraint、metric 和 evaluator。
- `markdown/ALGORITHMS_MODULE_SUMMARY.md`：算法模块占位，当前暂不定义具体内容。

后续 agent 的工作顺序：

1. 先读 `AGENTS.md`，理解新仓库的总体架构。
2. 再读三个 summary md，获得实现细节和实验口径。
3. 按 summary md 的内容重写新仓库模块。
4. 如果 summary md 信息不足，先补充或要求补充对应 md，不直接回看旧代码。

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

算法模块当前只占位，暂不定义具体内容。

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
4. 算法模块暂不实现，只保留目录占位。
5. 如果需要补充实现细节，先补充对应 summary md，再继续实现。

## 测试与验证

重写时优先保护小型 deterministic 测试，而不是一上来跑完整大实验。

验证重点：

- objective order 清楚且有测试。
- hard feasible 判断清楚且有测试。
- 1 m 局部坐标、边界范围和 pose bounds 清楚且有测试。
- 新仓库的 TSV/JSON 输出字段统一、清晰，并记录字段含义。

## 代码风格

- 函数名体现领域含义，例如 `evaluate_site_objectives`, `build_problem_context`, `compute_hard_constraints`。
- 长函数优先按职责拆，不要只为了减少行数做机械切分。
- 模块之间用明确数据结构传递，不要依赖全局变量。
- 绘图、文件写入、训练循环、目标计算分开。
- 研究参数写进 config，实验结论写进 markdown 或 summary 输出，不写在算法核心里。

## 给后续 agent 的一句话

新仓库先按“数据、建模、算法占位”三层重新设计。不要兼容旧代码，也不要直接参考旧代码；所有实现依据都必须来自 `AGENTS.md` 和三个 summary md。少写隐式兜底，多写显式参数；少堆大脚本，多做可替换模块；任何实验口径变化都要写清楚。
