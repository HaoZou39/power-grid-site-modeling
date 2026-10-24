# 引导式多目标搜索

决策界面使用引导式多目标搜索。一次搜索同时比较当前打开的目标，不把它们收成一个标量，也不要求填写目标权重。

研究入口 `experiments/run_cma_es_region.py` 仍按 `markdown/CMA_ES.md` 使用切比雪夫和权重网格。本文档不改变那条研究口径。

## 目标与约束

决策搜索的目标全部最小化。`road_distance` 和默认关闭的 `demand_distance` 仍写入方案表，不参加支配比较。

1. `dem_soft`：房子脚印里的地面平不平
2. `demand_distance`：到需求点的加权距离。需求点目前是随机生成的，默认不比较。`include_demand` 为真时，排在 `dem_soft` 后面。点的来源以后可以换成新能源负荷预测，目标名字不变
3. `road_haul_m`：从进货原点沿道路到进站口的长度。只有点了进货原点才加入比较
4. `offroad_haul_m`：进站口到房子、只走可建设格子的进站长度
5. `haul_rise_m`：这段进站路径的累计高差

后三项不乘单价，也不把高差乘进长度。不点进货原点时，搜索不比较 `road_haul_m`。点了之后，地图上会标出这个点，并把它作为沿路运输目标。默认因此比较三项；打开需求点距离后是四项；再点进货原点则加上沿路长度。CMA-ES 仍使用 `dem_soft`、`road_distance`、`demand_distance`。

比较规则：

- 硬约束违例读取建模模块返回的 `constraint_violation`。当前它等于足迹压到土地约束硬格、道路退距格或水体退距格的数量，违例为 0 才可行。
- 可行个体支配不可行个体。
- 两个都不可行时，违例更小的个体更优；违例相等时仍按目标 Pareto 支配。
- 两个都可行时，按当前打开的目标做普通 Pareto 支配。
- 同一前沿内用拥挤距离保留分布更开的个体。

建筑、遥感道路、水体以及手绘禁区进入土地约束硬掩膜。遥感道路类别 3 与 OSM 中心线的并集再按 `road_setback_m`（默认 5 m，0 表示只禁道路格子本身）做 1 m 栅格缓冲，类别 5 水体再按 `water_setback_m`（默认 5 m，0 表示只禁水体格子本身）做同样的缓冲。两层都只追加到建筑足迹硬评价，不进入 HaulField 的通行掩膜，也不改变目标定义或 Pareto 规则。进站路径走不通的个体不可行。足迹坡度还不是硬约束。口径见 `markdown/MODELING_MODULE_SUMMARY.md`。

## 搜索

`GuidedSearch` 继承 `algorithms/common/search.py` 的 `SiteSearch`。`run_guided_search` 只负责构造这个子类。决策变量仍是无界 raw pose `[x, y, theta]`，经现有 `decode_raw_pose` 变成 1 m 局部坐标。演化阶段通过建模模块的批量评价器读取当前目标与硬约束，不在算法里重写目标。完整报告仍使用原有评价入口。

进站相关目标不在每一代里重新寻路。搜索开始时按本次硬掩膜建一次距离场，见 `markdown/MODELING_MODULE_SUMMARY.md`。之后每代用精确查表得到 `offroad_haul_m`、`haul_rise_m`，有进货原点时再加上 `road_haul_m`。指定原点后只用其道路分量内的 Gate 初始化距离场；其他 Gate 被跳过，依赖它们且无法从可达 Gate 接近的个体仍判为不可行。一个不可达 Gate 不终止搜索，全部 Gate 不可达才明确报错。距离场还记录 Gate 归属和逐格前驱，单方案报告及地图黄线只回溯这份结果，不再从站址独立跑一次 BFS，因此 Gate、沿路长度、进站长度和累计高差与优化表一致。

路径选择使用多源 Dijkstra。每一步以 `水平距离 + access_elevation_weight × 相邻格高程差绝对值` 累加排序；`access_elevation_weight` 由 `config/default_config.json` 的 `guided_search` 段显式提供，仅用于选路，不替代或合并 Pareto 目标。默认四连通，正交一步为 1 m；侧栏「进站允许斜向」（`diagonal_access`）打开后改为八连通，斜向一步为 √2 m，且斜步两侧格子都必须可走，不能从障碍角切过。道路 Gate 到连续道路接触点的初始步长和高差也纳入同一累计代价；有进货原点时沿路距离本身不纳入站址到道路的进场选路代价。最终路径仍分别报告水平进站长度、累计高程变化和最大局部坡度。缓存键包含连通方式和高程惩罚系数；改变它们会生成不同距离场。已经写入方案的目标数需等下一次优化才会重算；当前选中方案的黄线会立即重画。

搜索分两段，目标名单不变，决策侧栏不增加权重：

1. 前期引导。多起点 Adam 下降一个归一化目标和。项是脚印平整度、进站长度、进站累计高差，有原点时加上沿路长度，`include_demand` 为真时再加上需求距离，另外加上乘以 `guide_obstacle_penalty` 的软障碍惩罚。进站相关目标用距离场的插值，所以这一段有梯度。直线 `road_distance` 不进入这个和。归一化尺度取距离场有限值的分位数，不是用户偏好。
2. 细粒度。把引导终点当作进化阶段的初始种群，用 `refine_sigma` 变异，支配比较使用精确查表。

种群 `popsize`、代数 `generations`、引导步数 `guide_steps`、引导学习率 `guide_lr`、引导障碍惩罚 `guide_obstacle_penalty`、引导分块 `guide_batch_size`、细阶段步长 `refine_sigma`、seed，以及末段退火 `anneal_last_generations` 和 `anneal_sigma_end`，取值都只写在 `config/default_config.json` 的 `guided_search` 段。插件 `site.guided_search` 的表单默认值从这份 JSON 读取，这些参数不出现在决策侧栏。历史种群规模的实验结论和数值只在 `markdown/EXPERIMENT_LOG.md` 保留。

`guide_batch_size` 只控制显存：前期 Adam 按块前向和反向传播，梯度在块间累加；归一化 scale 先用无梯度的分块前向在整个种群上算一次。每个个体的损失只依赖自己，所以结果与整批计算相同。最终报告同理，`search.py` 的 `REPORT_BATCH` 按块评价方案。

演化结束后直接对最终种群计算报告并输出，不再执行后期局部微调。原有后期微调实现及其步数、学习率、方向混合参数已经移除；前期 Adam 引导和末段变异步长递减仍按上文执行。

### 演化后端与设备选择

`GuidedSearchConfig.evolution_backend` 和插件同名参数接受 `tensor`、`numpy`，默认值见 `config/default_config.json`。`tensor_nsga2.py` 负责张量批量算子，`numpy_nsga2.py` 保留原版 `Individual`、NumPy 随机流和逐对非支配排序；`evolution.py` 统一选择后端、变异退火与最终 raw pose 输出。两者共用初始化、前期 Adam、同一建模目标/硬约束和报告，不增加演化后局部微调。

| 请求后端 | 实际评价设备 | 实际演化后端 |
| --- | --- | --- |
| `tensor`（默认） | CUDA | `tensor` |
| `numpy` | CUDA | `numpy`；soft 评价仍使用 CUDA |
| 任一后端 | CPU | `numpy`；soft 评价与 Adam 使用 CPU |

引导搜索插件的 `device` 接受 `auto`、`cpu`、`cuda` 和 `cuda:编号`。表单默认值取 `config/default_config.json` 的 `modeling.device`；这个值也是 CMA-ES 和多起点 Adam 的默认设备，所以读配置时只接受 `cuda` 或 `cuda:编号`，写 `auto` 或 `cpu` 直接报错。两条写法规则只定义在 `config/project_config.py`，插件校验和运行入口共用。`auto` 或首选 `cuda` 在 CUDA 不可用时自动选 CPU；显式 `cpu` 在有 GPU 的机器上也可复现回退路径。错误的设备名称、可见 GPU 的非法编号仍明确报错；不以 OOM 或算法异常作为切换后端的理由。其他研究算法的 CUDA 校验保持原有约定。

任务入口在创建场景张量之前解析设备，整场景搜索、矩形分区搜索和方案重算使用同一规则。已有 `SiteProblemContext` 的直接调用依据该 context 的实际设备选后端。结果元数据记录请求/实际演化后端、实际评价设备及回退原因；配置保存请求值，元数据保存本次实际执行值。原版后端允许在 GPU 机器上显式选择，用于对照研究。

运行时将实际执行方式写入进度消息，并在 `normalization.json` 保存 `execution_description`，区分 GPU 张量演化、CPU NumPy 演化配合 GPU 评价、完整 CPU 执行。距离场、初始化/引导、演化和最终报告分别报告阶段，界面显示口径见 `markdown/FRONTEND_IMPLEMENTATION_SPEC.md` 5.4。此信息不改变种群、随机数或停止条件；当前仍按配置代数运行，没有早停。

`modeling/numpy_evaluator.py` 组装原版批量 soft 评价、完整硬指标和精确进站查询；`tensor_evaluator.py` 组装张量版分批评价。二者复用现有模型公式。CPU 回退保留种群规模、代数、初始化、引导步数、学习率和全部目标/约束，只改变执行设备与演化后端。种群增大可能使 CPU 搜索变慢，不做隐式降配。

### 张量化 NSGA-II

设备常驻种群的组织方式参考 [EvoX NSGA-II](https://github.com/EMI-Group/evox/blob/main/src/evox/algorithms/mo/nsga2.py)，本项目用现有 PyTorch 依赖实现自己的算子。

`algorithms/guided_search/tensor_nsga2.py` 维护整批 genes、objectives、violation、rank 和 crowding 张量。锦标赛选择、交叉、变异、约束支配矩阵、前沿分层和拥挤距离均按种群批量计算；环境选择合并父代与子代后只做一次非支配排序，截断后沿用 rank 并重新计算拥挤距离。不同违例组先并行求局部前沿，再按违例顺序累计层数，避免每个不同违例都单独触发一次前沿循环。前沿推进仍有 Python 控制与设备同步。支配关系按行分块计算，每块最多 `TILE_PAIRS` 个个体对（模块常量），只保存每个个体被支配的计数，不再整幅保存 N×N 支配矩阵；名次与整幅计算完全相同。显存因此是 O(块大小)，比较次数仍是 O(N²)：每行先算一次初始计数，所在前沿剥离时再算一次。扩大种群不意味着任意规模都保持相同耗时。

算子沿用原策略：两两锦标赛优先 rank 小、其次 crowding 大，完全平局选择右侧；以 0.9 概率取双亲算术均值，否则复制第一亲本；每个基因均加独立高斯扰动。步长及末代退火不变。拥挤距离逐目标按前沿归一化，边界为无穷，即使该目标跨度为零也保留边界标记。目标和拥挤距离完全相同时用合并种群的原行号稳定决定顺序，不再依赖旧版 Python 前沿遍历的副作用。

genes 和支配比较用 float64，进入现有 pose 解码与 soft 目标时仍转 float32。初始化方式和前期 Adam 不变；演化随机数改用每次搜索独立的 PyTorch Generator，固定配置与 seed 在同一设备后端可复现，但不承诺与旧 NumPy 随机流产生相同轨迹。

`modeling/tensor_evaluator.py` 缓存建筑硬掩膜和距离场的设备张量，分批评价当前参与比较的目标，不在每代计算仅供报告的 DEM hard variance/range 或未打开的目标。`evaluation_batch_size` 的默认值在项目 JSON，显式插件表单可覆盖，控制足迹评价的单批数量，不改变总种群数或选择策略。建筑足迹硬计数保持格子中心与越界角点规则；精确进站查表保持 floor 映射、5 cm 末段规则、不可达标记和原点目标。有道路中心线格的候选仍走原有精确道路接触点计算，该小批次允许 CPU 计算，不能用插值或近似路程替代。默认关闭的自适应 HV 步长监测仍在 CPU 上；最终报告统一转回原有报告路径。前期引导、一次建场和输出阶段不属于全设备常驻的演化算子。

性能验证入口为 `experiments/compare_tensor_nsga2.py`。固定同一数据、约束、初始化方式、90 代、8 步引导与多个 seed，对照改动前的 100 个体以及张量版多个种群规模。分别记录建场、首次运行、预热后的完整搜索耗时、峰值显存、可行率和共同经验参考下的 HV/IGD+，不以单个 seed 或只计选择算子的耗时宣布整体加速。历史对照仍可从 Git 读取源码快照；正式搜索通过上述参数维护两种演化后端。

### 初始化

`algorithms/guided_search/initialization.py` 生成 `[popsize, 3]` 的 raw pose，默认 `uniform`。正式搜索先读取本次建筑硬掩膜：中心点只从值为零的格子与场景安全边界（或分区 `pose_bounds`）的交集中采样，包含可行域并集、手绘禁区、土地硬约束、道路退距和水体退距。只要该中心搜索范围内存在禁止格子，实际采用约束域均匀采样；请求的高斯或田口方式不用于不规则约束域。`requested_initialization`、实际 `initialization` 和 `initialization_fallback_reason` 随搜索摘要保存，运行消息也说明实际方式。显式 API 表单仍可配置请求方式，界面不增加参数控件。

- `gaussian`：保留旧实现，在 raw 空间按 `N(0, sigma0²)` 独立采样，用于历史对照。
- `uniform`：在归一化的位置和角度范围 `(0, 1)` 内独立均匀采样，再用 `log(u / (1-u))` 转回 raw。解码后覆盖现有安全边距内的整个位置范围和 `[-pi, pi]` 角度范围；数值转换前按 float32 epsilon 限制到开区间。`sigma0` 不改变这种初始化的覆盖范围。
- `taguchi`：使用田口式三因素正交表 `OA(s², 3, s, 2)`。枚举 `a,b=0,...,s-1`，三列为 `a`、`b`、`(a+b) mod s`。每列随机重标水平、再随机打乱行，水平中心映射为 `(level+0.5)/s`，最后转成 raw。任意两列的每种水平组合恰好出现一次。100 个体时 `s=10`，恰好生成 100 行；种群必须为不小于 4 的完全平方数，不截断或补随机点破坏正交性。这是用于初始化的正交设计，不额外做信噪比优化或修改 Pareto 选择。正交表定义参考 [NIST 论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC4927234/)。

上述三种原始采样定义保留给没有内部禁止格子的矩形域及独立采样调用；田口正交性不延伸到不规则约束域。约束域采样先按允许格子在连续中心边界内的面积选格，再在格内均匀取连续坐标，角度仍独立均匀取样；用 float32 数值安全边距避免解码舍入跨过格子边界。按行计数和选列，不为大场景建立全部允许点的二维坐标表。没有可用中心格时直接报错，不无限拒绝重采样。相同 seed 可复现，初始化数量保持 `popsize`。

任务装配还把原始可行域和禁区多边形传入 context。初始化对实际设备解码后的中心坐标再做连续多边形检查，避免 `all_touched` 栅格化把画线外的边缘点接纳进来；在可行域并集内、禁区外且通过硬格检查的点才保留。`sample_initial_population` 的 `max_sampling_batches` 默认 100，达到上限仍无法填满时明确报错，不用圈外点补齐。

前期 Adam 每步检查更新后的中心点，进入禁止格子或越过多边形边界的个体恢复到该步前的位置，因此实际交给演化的初始种群中心也在允许域内。此保证针对中心点；旋转建筑的完整足迹及进站可达性仍由已有硬约束评价，后续交叉变异继续允许产生不可行候选。初始化不改写场景数据，不改变演化算子或停止条件。

### 初始化对照实验

`experiments/compare_initialization.py` 只在已准备的同一个场景上直接运行正式搜索，不启动浏览器，不读取覆盖度研究分支。默认比较 `gaussian/40`、`gaussian/100`、`uniform/100`、`taguchi/100`，使用相同的 10 个 seed、90 代、8 步引导和全部其他参数；各 seed 内轮换运行顺序。三种 100 个体方法的预算相同；40 个体只用于描述增大种群后的质量和耗时变化，不能当作等预算优势。

当前正式搜索在不规则约束域统一使用均匀采样，因此该三方法对照入口在检测到此类域时明确拒绝运行，避免把请求田口、实际均匀的结果写成田口实验。既有对照是变更前的历史口径，源码版本及结果以 `markdown/EXPERIMENT_LOG.md` 为准。

同一约束下距离场只构建一次并复用，单独记录建场耗时；搜索计时包含初始化、引导、演化和最终复评，不包含作图与指标汇总。保存每次完整配置、引导前和引导后位姿、最终方案与可行前沿。空间覆盖按固定 100 m 格统计，明确不是全局可行域覆盖率。前沿质量以所有运行最终可行前沿合并后的经验非支配集为共同参考，在统一 ideal/nadir 归一化及每维 1.1 的参考点下计算 HV、IGD+，另外记录可行率、目标极值、空间格数和耗时。该参考只用于本轮相对比较，不证明全局最优。

## 结果显示分层

决策界面的「方案多样性」只对最终 `solutions.csv` 中已完成评价且 `is_feasible=true` 的候选分层，不修改演化算法、种群或正式 `pareto_solutions.csv`。第一层仍以该文件的成员为准，保持原有显示不变。移除第一层后，在剩余可行候选中取非支配集作为第二层；再移除第二层，取第三层。各层的严格支配比较使用 CSV 原始精度，所有目标最小化，相等目标互不支配；不使用显示时四舍五入后的值、权重或归一化。

参与比较的目标来自该实验的 `site_form_snapshot.json`：默认 `dem_soft`、`offroad_haul_m`、`haul_rise_m`；`include_demand=true` 时加入 `demand_distance`，记录了有效进货原点时加入 `road_haul_m`。不使用当前侧栏设置替代实验配置，不比较 `road_distance`。缺少必需目标或非有限值应明确报错。无后续层时显示实际已有方案，不补点。缺少这份目标开关快照的旧结果只保留原有第一层，不猜测第二、三层的比较目标。分区结果若含同一标准快照则按合并后候选分层。

层级是显示元数据，由 `frontend/src/map/solution_diversity.ts` 计算并随已加载方案缓存；不写回实验 CSV。UI 行为与颜色以 `markdown/FRONTEND_IMPLEMENTATION_SPEC.md` 为准。

## 矩形分区并行搜索

Jobs API 的 `site.partitioned_guided_search` 插件把同一场景的安全站址中心搜索范围等分为 4 或 6 个矩形分区，每个分区运行一份现有 `GuidedSearch`，再合并为一个标准实验目录。它不改前端交互；通过现有 `POST /api/v1/jobs` 提交，任务状态、取消和实验产物仍走现有 Job 与 Experiment API。

各分区继承相同的 `initialization` 和 `popsize`；种群数表示每个分区的数量，合并前候选总数为 `partition_count × popsize`，合并去重后可能更少。均匀、田口和高斯初始化沿用本文的同一配置与校验规则。

`partition_count` 只接受 4 或 6。后端根据搜索矩形的长宽比选择网格行列数，让分区尽量接近正方形；默认搜索矩形是整幅场景中可容纳建筑 footprint 的安全中心范围。可选 `search_bounds_m = [x_min, y_min, x_max, y_max]` 将它缩小到场景局部米坐标中的一个矩形，范围表示建筑中心的搜索范围，并必须位于整幅场景的安全边界内。分区边界连续相接；站址中心由有界 pose 解码器限制在对应分区内。

分区共享相同的全局场景数组、用地约束、道路数据和一次构建的全局 HaulField；本功能不裁切或拼接栅格。这样道路连通、目标评价、进场路线、坐标原点和最终地图都保持整幅场景口径。每个分区使用由基础 seed 确定性派生的 seed；`max_parallel_tiles` 限制同一批次实际并行的搜索数量，默认 2，不需要与分区数相同。各搜索共享同一实际设备；CUDA 时共享全局上下文，因此应从低并发开始，并按运行机器的显存和耗时验证并发上限。无 CUDA 时各分区沿用 NumPy/CPU 回退规则。

全部分区成功后，汇总器按全局坐标去重，用同一个全局 problem 与 HaulField 对合并候选重新计算目标和硬约束，再从合并候选集中计算一次 Pareto 前沿。输出的 `solutions.csv`、`pareto_solutions.csv` 和地图仍覆盖全场景；额外的 `partition_manifest.json` 与 `partitions.csv` 记录范围、seed 和分区候选数。任一分区失败时整批任务失败，不发布看似成功的部分实验。全局重算保证指标口径一致，但搜索仍是有限候选生成，不保证数学上的全局最优。

2026-10-12 改名前写出的结果目录里，算法名仍是旧名 `nsga2`。目录文件不改写，`backend/app/infrastructure/experiment_catalog.py` 读取时显示为 `guided_search`。

最终种群由 `pose_records` 逐行算出后写入 `solutions.csv`。搜索之外放下的位姿（拖动、助手改位、改约束后的重算）也走 `pose_records`，所以和搜索结果同列、同口径；这类记录的 `raw_*` 列为空。可行且互不支配的个体写入 `pareto_solutions.csv`。权重列留空，因为这次搜索没有使用权重。

## 不在本文档内

- 不把 CMA-ES 改成多目标。`cma` 库的 `CMAEvolutionStrategy` 只接受一个标量。
- 不把支配比较收成一个加权标量。前期引导用的归一化和只负责把种子推进可行区域。
- 不在前端计算支配关系。
