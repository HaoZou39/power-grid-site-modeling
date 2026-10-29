# Algorithms Module Summary

算法模块当前包含公共多目标组件、引导式多目标搜索、CMA-ES、多起点 Adam，以及 VAE-like multi-head 候选生成器。决策界面使用引导式多目标搜索。CMA-ES 保留为研究入口。

具体口径分别服从：

- `markdown/ALGORITHM_COMMON.md`：目标顺序、权重、normalization、切比雪夫、Weiszfeld 和 Pareto。
- `markdown/GUIDED_SEARCH.md`：决策界面的引导式多目标搜索。它不使用目标权重。
- `markdown/CMA_ES.md`：CMA-ES 搜索流程和输出。
- `markdown/MULTISTART_ADAM.md`：多起点 Adam 搜索流程和输出。
- `markdown/VAE_LIKE_MULTIHEAD_ALGORITHM.md`：VAE-like multi-head 的网络、训练、评价、输出和执行流程。
- `markdown/VALIDATION.md`：不同算法验证流程共用的等间距偏好 CSV 生成口径。
- `markdown/FIGURES_MODULE_SUMMARY.md`：公共 figure 输出。

算法模块不读取原始 tif/csv/GeoJSON，不重新实现建模目标。数据读取由 `data_tools/` 完成，目标和 hard metrics 由 `modeling/` 完成。

## 模块和对象

人工改搜索时，先看对象再改实现。每个对象只做下面这一件事。

- `algorithms/common/search.py` 的 `SiteSearch`：所有选址搜索的父类。子类实现 `search`。父类不写权重，也不写约束名字。
- `algorithms/guided_search/search.py` 的 `GuidedSearch`：决策界面的多目标搜索，名单以 `markdown/GUIDED_SEARCH.md` 为准。`evolution.py` 按配置和实际设备选择 `tensor_nsga2.py` 的张量算子或 `numpy_nsga2.py` 的原版算子；默认张量版，无 CUDA 时使用 NumPy/CPU。两条评价装配在 `modeling/tensor_evaluator.py` 与 `modeling/numpy_evaluator.py`，复用同一模型公式。`initialization.py` 生成可配置的初始种群，`guide.py` 在进化前用可微进站距离场做短程引导，支配阶段仍用精确查表。
- `algorithms/cma_es/cma_es.py` 的 `CmaEsSearch`：研究用的单目标搜索。切比雪夫和权重网格写在这个类的 `search` 里。`run_cma_es_search` 只负责构造它。
- `algorithms/common/scalarization.py`：目标顺序 `OBJECTIVE_NAMES`，以及把目标向量收成一个数的公式。只有单目标子类调用它。
- `algorithms/common/pareto.py`：从已经算好的候选记录里取出可行且互不支配的方案。它不运行搜索。
- `algorithms/multistart_adam/`：多起点 Adam，目前仍是函数入口，还没有继承 `SiteSearch`。
- `algorithms/vae_like_multihead/`：候选生成器。它不是选址搜索，不继承 `SiteSearch`。

## 扩展时改哪里

- 增加一个选址算法：新建一个类继承 `algorithms/common/search.py` 里的 `SiteSearch`，并实现 `search`。多目标子类直接比较 `evaluate_site_objectives` 返回的目标向量。单目标子类在自己的 `search` 里调用 `algorithms/common/scalarization.py`，父类不出现权重。然后在 `plugins/site_plugin.py` 增加配置和插件，在 `backend/app/application/registry.py` 注册，并在 `experiments/launch_site_run.py` 增加一条入口。不改数据模块，也不重写已有算法。
- 修改现有目标公式：改 `modeling/site_model.py` 里对应的 `SiteObjective` 子类。这些子类调用 `modeling/dem_model.py`、`modeling/road_model.py`、`modeling/demand_model.py` 里的公式。CMA-ES 的目标名单和顺序只维护在 `OBJECTIVE_NAMES`。决策搜索的名单在 `guided_objective_names`，口径见 `markdown/GUIDED_SEARCH.md`。
- 修改硬约束：用地类别和手绘禁区改 `experiments/constraint_mask.py`。可行性数值由 `ObstacleCountConstraint` 汇总为 `constraint_violation`。新的硬约束继承 `SiteConstraint`。算法读取这个数值，不自己挑选某个计数字段。

## 选线算法规格

### 行为等价的模块化改造

选线链路采用显式 Python 内部装配，不改变 HTTP、任务 JSON、默认数值、页面交互、四目标或工程约束。验收要求同配置、同后端、同设备、同 seed 的候选轨迹与预算一致，不能把算法优化混入重构。

搜索入口只装配评价会话、初始化、演化驱动与最终归档。`initial_population.py` 编排初始化，`initialization.py` 生成参考路径；`ranges.py` 维护塔数范围，`repair.py` 维护几何修复，`postprocess.py` 维护带预算的删塔。旧初始化模块保留原名称导出。初始化策略返回 CPU 已选种群、张量初选使用的有序已评价候选、塔数状态及诊断；张量驱动显式接收候选集合，评价历史只负责记账，不替初始化器决定初代。默认张量候选仍是范围内的全部初期试探，保持原生选择顺序；现有 legacy/pruned/balanced/bounded 的行为分别保留。初始化填充与正式演化显式获得各自的变异依赖，避免替换演化算子改变初代。范围策略统一描述扩展与探查目标，后端仍保留现有执行位置。

变异分为动作调度和具体移动/插塔/删塔/交叉，修复与路径后处理独立维护。默认仍互斥抽取一种动作，不改成交叉后独立变异。NumPy 与张量使用各自原生算子集合；张量保持批量采样与掩膜计算，不转成逐条 Python 算子。父代/环境选择由 `selection.py` 的原生 bundle 装配，默认直接复用既有公共实现。`numpy_search.py` 与 `tensor_search.py` 各自维护驱动，`archive.py` 负责归档与复核。`components.py` 显式选择内置驱动，`search.run_with_components()` 接受 Python 的 `SearchComponents(initializer, driver)`；研究代码用 `functools.partial` 注入算子、选择、生成与范围策略。CPU 的 `generate` 回调通过共享窗口执行内部试探，可返回 `EvaluatedCandidate` 复用窗口中的评价；正式演化不再次评价该候选。研究装配可替换初始化、算子和生成策略，不经前端/API；NumPy/张量驱动要求配置中的后端与自身一致，不支持的组合明确报错。

完整评价统一经过账本与阶段窗口。窗口公开已用/剩余量和评价请求，候选历史由账本只读提供；初始化不再通过窗口的父对象读取内部列表。内部试探与已评价候选复用须保持现有计数，不重复评价。随机流的所有者、创建位置和抽样顺序保持：参考初始化与 NumPy 演化共享原流；PILOT、填充、张量演化及其 CPU 修复保留各自原流。

运行结果契约在 `algorithms/routing/types.py`，任务配置在 `config/routing_task.py`。公共道路占地/退距在 `modeling/road_control.py`，目录创建在 `experiments/output_writer.py`。运行结果类型独立于搜索实现，归档保留首次候选顺序、精确去重、原 CPU 复核和 Pareto 提取。既有 Python 入口及导入名称保留兼容导出。配置类型与插件实现分离，公共输出/道路几何只保留一份实现，不把选线强制继承站址专用 SiteSearch。

验证先冻结 Git 源码与输入，再按职责拆分逐轮核对。小型固定输入覆盖全部现有模式和支持的后端；真实三工况进行逐候选对照。计时、资源、源码版本/哈希和隔离输出根允许变化，其余语义字段不放宽。最终记录资源量；重复性超过 10% 的耗时或内存增长须先定位。完成的真实验证只记入唯一实验记录。


内部研究替换示例（`problem` 已由实验层构建，`my_crossover` 与现有交叉签名一致）：

```python
from dataclasses import replace
from functools import partial
from algorithms.routing.components import builtin_components
from algorithms.routing.numpy_search import evolve
from algorithms.routing.operators import numpy_operators, offspring
from algorithms.routing.search import run_with_components

operators = replace(numpy_operators(), crossover=my_crossover)
components = replace(builtin_components(config), driver=partial(
    evolve, variation=partial(offspring, operators=operators)))
result = run_with_components(problem, config, components)
```

此例要求 `config.evolution_backend == "numpy"`。替换参考生成可用 `partial(initialize_population, reference_initializer=...)`；单独替换初代填充可用 `fill_variation`，与演化的 `variation` 分离。选择 bundle、`range_policy` 通过对应驱动的显式参数注入。张量动作通过 `partial(vary, operators=...)` 注入张量驱动，仍接收完整 batch；CPU 边界探查与修复分别是 `boundary_variation`、`repair`。不建立全局动态插件发现，也不经 Jobs/API 选择研究算子。

完整 PILOT 的张量化契约、T0–T9 实施与预算批处理规则统一维护在 `markdown/PILOT_ROUTING_MIGRATION.md`「完整 PILOT 的张量化加速」。标准策略与完整 PILOT 的张量驱动独立，后者已接入显式 tensor/tensor 配置与 Jobs；初始化和新种子规划仍保留 CPU 边界。实测时间和质量仅在 `markdown/EXPERIMENT_LOG.md` 记录，不由后端名称推断收益。

PILOT 独立 CPU 驱动继续作为参考，完整张量驱动复用公共排序与建模内核；不设置逐组件或功能组的质量收益门槛。执行契约见 `markdown/PILOT_ROUTING_MIGRATION.md`。

PILOT 原机制逐项迁移已获用户授权，完整边界、源码对照、阶段与验收门槛见 `markdown/PILOT_ROUTING_MIGRATION.md`。当前默认选线配置使用完整 PILOT 主线，启用 A*/RRT 初始化、精英局部搜索和条件式全局注入；standard 仍保留为显式对照，不把已完成的加速对照当作质量收益证明。

选线迁移参考 PILOT_v2 的核心路径搜索能力，不迁移偏好反馈闭环。采用独立变长塔位序列与无权重四目标 NSGA-II，不继承站址专用 `SiteSearch`。所有目标和硬约束服从 `markdown/MODELING_MODULE_SUMMARY.md`「选线建模规格」。修复、演化与最终复核共用选线评价器的严格延伸判断。初始化的 RRT 与 A* 只铺可立塔走廊，完整约束仍由随后的完整评价和演化执行。导线可跨越建筑、道路和水体，不能沿用旧项目将这些地物全部禁跨的生成器。

塔数搜索的松弛下界由最大水平档距直接推导。设两端的水平直线距离为 `D`，新增中间塔数为 `N`，则共有 `N + 1` 档，因此 `N >= max(0, ceil(D / D_max) - 1)`。这里不能改用三维距离；该下界忽略禁落塔区域、禁跨越区域及转角约束，不保证按下界布塔即可得到可行方案。

已确认塔数范围采用「直线松弛下界＋参考线路估计初始上限＋必要时扩展」：

1. 按上述公式计算新增塔数的理论下界。
2. 构造若干不掉头的参考曲线，结合最大档距布塔，检查塔基控制圆、禁落塔区、禁跨越区和最大单处转角等已定义约束，并在保持可行的前提下去除冗余塔。删塔若使跨越量等其他目标变差，应保留体现该取舍的原候选，不能把「仍可行」等同于「其余目标不变」。
3. 根据通过检查的参考线路估计紧凑的初始塔数上限。若所有参考线均不可行，则用已评价参考线的最大塔数作为探索范围，保留这些候选参加约束优先选择；不能退回理论下界并把接近可行的参考线排除在种群之外。该值只是搜索范围的初始估计，不作为严格可行性上界，也不照搬原项目的固定塔数范围。
4. 搜索发现初始上限可能过紧时，在计算预算内逐步扩展。任务记录初始范围、最终范围和停止原因；不新增用户必填的最大塔数输入。具体扩展与停止规则在实施方案中集中说明。

「不掉头」仅用于构造参考线路，不作为所有候选解必须满足的额外约束。最大单处转角不单独决定塔数上界，总曲折度仍只是优化目标。可行参考线路只能为最小可行塔数提供上界，不能证明更多塔的线路在跨越量等其他目标上没有价值；扩展机制须保留对这些折中方案的搜索机会。参考线路生成失败或计算预算耗尽时，不得把未找到可行线路表述为已证明不存在可行线路。


初始参考线包括直线和侧向弯曲线；必要时用粗导航格的禁跨越绕行路径补充，最终按 1 m 数据验证。种群由插塔、删塔、移动和交叉产生，固定端点不进入基因。冗余塔删除须保留与其他目标的取舍。

搜索按迭代次数停止。一次迭代是一整代：该代的子代生成与评价、环境选择，以及这一代配置里排到的精英局部搜索和全局注入。初始化在循环外完成，不计入代数。跑满 `max_generations` 即停，不再因评价次数用完而提前结束，最后一代也不再少算子代。评价次数仍写入结果。每到配置的扩展周期，按配置步长放开初始上限并探查新塔数，保留已有非支配档案；即使已有少塔可行解也执行探查。无可行参考线时保留已评价参考线继续修复和扩展，不报告已证明不可行。所有默认数值只在 `config/default_config.json` 的 `routing` 段中定义，包含种群、迭代次数、参考线数量、移动尺度、扩展周期、修复尝试和导航步长。旧任务配置没有 `max_generations` 时，按 `ceil(max_evaluations / popsize)` 补上代数；该字段不再决定停止。完整实现顺序与验收见 `markdown/DECISION_REQUIREMENTS.md`。

`algorithms/routing/initialization.py` 已实现直线/二次曲线参考线、仅避让人工禁跨越区的导航、按水平档距布塔、调用统一塔基检查的有限修复，以及保留目标取舍的删塔。`TowerRange` 按配置的扩展周期和步长放开初始上限，初始上限和理论下界保留用于报告。导航步长仅控制候选生成，最终仍用 1 m 数据评价。

`algorithms/routing/search.py` 已实现按代数停止的变长 NSGA-II。标准搜索每一代评价 `popsize` 个子代。PILOT 在同一代内还可按配置执行局部搜索和全局注入；这两段仍使用各自的阶段评价上限，但用尽阶段上限不会结束整个搜索。初始化与删塔的目标评价继续记入评价次数，不减少代数。最终只读硬检查/报告另执行。`operators.py` 实现插塔、删塔、移动和交叉，调用同一塔基检查修复，绝不移动固定端点。每到扩展周期必做边界探查，已有非支配候选从全部已评价记录中保留。结果记录初始/最终范围、扩展历史、评价次数、实际代数和停止原因 `generation_limit`。跑满代数仍无可行解，不等于已证明不可行。

界面在提交前显示迭代次数和每代候选数，并说明初始化不计入代数。摘要分别保存 `initialization_evaluations` 与 `generation_count`。历史回读保留原算法参数；没有代数的旧配置按上一节换算。用户可显式恢复当前 JSON 默认算法参数，接入点与工程约束不受该按钮影响。

参考线修复顺序：先修复禁落塔点，再反复检查最大水平档距；超限档插入中间塔并重新执行同一塔基检查，迭代次数受已有修复尝试配置限制。最终仍由统一评价器完整判断，修复失败不伪装成可行。理论下界取整、按档距布塔、冗余塔删除与硬评价共用 `DISTANCE_TOL_M` 的数值舍入口径，避免经纬度/UTM 往返在整除处多算一档；该容差不是额外工程档距参数。

若曲线参考线均不可行，追加一次合法塔位导航参考线。`algorithms/routing/navigation.py` 在局部米坐标下构造稀疏候选图，网格间距取已有导航步长和塔基直径的较大值，节点用同一评价器检查整个塔基；任意两个网格节点只要水平距离不超过最大档距，就可连边，不能把连线经过的建筑、道路、水体或永农当作禁跨区。人工禁跨区单独检查边的相交；起终点作为固定接入点连接可达节点，不施加新塔基限制。A* 用水平长度及直线距离启发搜索，结果直接作为塔位序列，不能再次等距插入可能位于禁落塔区域的中点。完整四目标、转角及所有硬约束仍由统一评价器判断，候选评价与删塔计入主预算。网格没有路径或候选未通过检查，只表示本次启发式初始化失败，不证明连续问题无解；导航节点数不算完整线路目标评价，单独接受取消检查。

### 选线加速实施契约

用户已授权按 P0 基线、P1 张量演化、P2 精确批量评价、P3 显存/归档、P4 上下文复用、P5 质量实验、P6 双卡的顺序实施。每步先写对照、只改变一种机制，通过正确性与计时验收后提交。NumPy/CPU 参考实现保留，四目标、约束、算子含义、预算计数及塔数扩展不变。

演化使用 float64 的 `[B,K,2]` 塔位和有效数量，容量随上界扩展；固定接入点独立保存。公共张量排序由站址与选线共用。比较固定输入的支配、rank、拥挤度与选择；前沿成员按稳定候选序号处理平局。原 NumPy 前沿展开的历史顺序保留在原后端，张量后端的稳定候选序号单独记录；不将不同随机生成器的同 seed 轨迹当作逐位一致契约。移动、插塔、删塔、交叉和有限修复须通过受控随机输入及边界案例。

新增执行字段在唯一默认 JSON 中定义：`evolution_backend`（numpy/tensor）、`evaluation_backend`（reference/compiled_cpu/tensor）、`devices`、`evaluation_batch_size`、`gpu_memory_budget_mib`。设备列表首项承载张量演化，双 CUDA 设备同步分担评价后恢复候选顺序并统一选择，不采用岛模型。P0–P6 加速对照保留原参考运行与预算，以隔离加速收益；当前软件默认执行与预算以唯一 JSON 为准。显存预算只影响工作分块，不改变种群、评价次数、工程参数或数据分辨率；不足时明确失败。

性能报告拆分快照、上下文、初始化/修复、评价、排序、变异、归档、复核及写出，区分冷启动与预热并记录每卡 allocated/reserved 峰值。历史候选紧凑保存在 CPU，不堆积整代报告或 CUDA 历史。四目标前沿采用精确算法，不截断候选或用近似支配。大种群推荐路径须正确性全部通过且代表性端到端计时中位数至少降低 20%，小种群单独报告。

质量实验先单 seed 再使用 seed 123–127；固定预算比较种群 48/256/1024，固定种群 256 比较预算 8192/32768/131072。报告可行发现率、首次可行评价次数、覆盖、IGD+ 与加性 epsilon，并区分等评价次数和等时间。小型离散问题枚举确切前沿，真实场景只使用冻结的最佳已知参考集合；报告尺度不进入选择。不因加速同时引入新搜索策略。

P1 已实现共享张量排序、变长算子和 `evolution_backend=tensor` 的 CPU/CUDA 演化；该阶段仅使用 reference 评价，其他后端在 P2 独立接入。高级参数保持类型并兼容旧历史配置。初始化与最终复核仍服从原精确口径。

P2/P3 已接入 reference、compiled_cpu 和 tensor 评价。搜索阶段只保留 CPU 数值记录，逐档与坡度报告在流式写出时生成；搜索结束后只对最终帕累托前沿做原 CPU 复核；前沿目标与可行性必须和搜索评价一致，其余可行线路保留搜索评价。复核按整批前沿进行，全部替换后再重新提取一次前沿，只对新进入前沿的线路补复核，不逐条复核后重算前沿。四目标前沿使用字典序精确扫描与编译内核，重复目标不互相支配，返回顺序保持原候选顺序。它不截断归档，最坏仍可能二次比较，但不分配二次数量的数组。演化、排序与评价分配前检查显存工作空间，不因预算改变问题。
标准 `evolution_backend=tensor` 且 `evaluation_backend=tensor` 时，演化子代直接以 `TowerBatch` 调用原生批量评价；native 路径先在设备端按有效坐标和塔数做精确去重，评价完成后才一次性生成 CPU `Route` 记录。`compiled_cpu` 和 reference 仍保留逐条 CPU 评价路径。重复线路的 CPU 评价在单次任务预算内按精确坐标身份复用，预算记录和候选顺序不省略。
原生张量评价的账本传输合并为单个紧凑批次，人工区域先进行包围盒保守筛选，批次索引张量在 evaluator 生命周期内复用；标准张量排序不因计时而强制同步 CUDA。
场景 crossing mask 为空时，原生评价在 evaluator 初始化阶段记录该事实并跳过 crossing kernel；人工禁跨 polygon 仍由独立精确分支处理。
PILOT 初始化和其他 CPU 批量评价在无人工 polygon 且不需要详细报告时使用 packed Numba 并行 evaluator；需要 polygon 或详细报告时保留原逐路线精确路径。
CUDA 标准张量演化的普通子代使用设备端批量塔基修复；CPU 仍保留原逐路线修复，带人工禁落塔多边形的边界路径也使用原 CPU 精确修复，避免把栅格判断当成 Shapely 语义。
种群不超过稠密排序阈值且工作空间允许时，四目标约束排序复用一次精确支配矩阵，避免逐前沿重复计算；评价批次内的完全重复线路只算一次，预算记录仍逐请求保留。

张量种群与 CPU 之间按整批打包传输。每次扩展的单条强制边界探查复用原 NumPy 变长算子，避免在 GPU 为同一条线路逐塔发射内核；它仍按最长档逐次插塔、同一评价器修复，不改变塔数扩展含义。搜索记录每个去重候选首次完成评价的序号与时间，仅用于性能/质量报告，不进入选择。

`experiments/benchmark_routing.py` 接收显式 manifest（tasks、cases、seeds、warmups、repeats、time_checkpoints_s），每个 case 只覆盖唯一 JSON 的配置。它保存独立快照、紧凑完整候选、CPU 复核目标、阶段耗时及每卡内存，重复运行检查坐标/目标内容哈希。所有完成前沿的并集冻结为最佳已知参考，统一 min/range 报告尺度；常数维 scale=1。IGD+、加性 epsilon 与覆盖由 `experiments/routing_metrics.py` 计算，不用于演化。等时间比较只按候选完成的搜索时间，明确不包含冷场景准备、最终复核和发布；完整耗时另报告。

双设备评价通过 `evaluation_session` 管理生命周期；`MultiDeviceRouteEvaluator` 按候选连续分片并行执行，每卡独立分块，返回时恢复原顺序，再进行一次全局选择。没有岛模型、梯度同步或异步代际更新。异常/取消必须等待评价线程结束，释放每卡场景张量与空闲缓存后才能释放任务。实际使用设备与请求设备分开记录；CPU 评价且 NumPy 演化不会因配置出现 CUDA 名称而假报 GPU 执行。

基准 case 可设置 `publish: true`，另行重放完整任务并记录包括快照、冷上下文、最终报告和写出的耗时；它是显式第二次运行，不混入搜索评价预算。等搜索时间从评价器建立前开始，包含设备场景上传，不能通过排除 GPU 准备时间制造收益。

质量报告同时记录初始/最终塔数范围和扩展历史。固定评价次数下不同种群意味着不同代数及扩展次数，这一耦合必须呈现，不能将全部差异都归因于种群大小。

#### 发布前沿

`RoutingResult` 在内存中保留全部去重候选和精确前沿 `pareto_indices`，供基准与质量指标使用。发布只写精简后的前沿 `published_indices`：`routes.json`、`solutions.csv` 和 `pareto_solutions.csv` 都只含这些线路，其余候选不写出。精简不影响搜索、前沿提取和 CPU 复核，在复核完成后进行：

1. 四个目标按精确前沿内的最小值与范围归一化，范围为 0 的维取 1，四维求和。
2. 按和从小到大排序，相同时保持原候选顺序。依次检查，与已保留的任一条塔数相同、且每个对应塔位的平面距离都不超过 `front_merge_distance_m` 时丢弃，否则保留。

阈值只在 `config/default_config.json` 的 `routing` 段定义。`run_summary.json` 中 `n_candidates` 为去重候选数，`n_feasible` 为其中可行数，`n_pareto` 为精确前沿数，`n_solutions` 为发布线路数；`validation_evaluations` 为最终 CPU 复核的线路数，`output_evaluations` 为写出时逐条重建报告的线路数。

本轮 P0–P6 已完成：共享张量演化、两种精确加速评价、显存与归档控制、只读缓存、五 seed 质量阶梯及同步双卡均完成对应验收。推荐执行配置与入口见 `markdown/LOCAL_RUN_GUIDE.md`，完整结果与版本身份只记录在 `markdown/EXPERIMENT_LOG.md`。该轮验收未改变默认预算和种群，不混入搜索策略变化。

楠溪江可行性修复后，软件默认使用完整 PILOT 张量演化与张量评价；默认设备保持 CPU，可显式选择 CUDA。种群与预算仅在默认 JSON 维护，界面显示两者对应的代数上限，不能再把小规模验证预算当作正式搜索预算。standard、NumPy、reference 和 compiled_cpu 仍可显式选择。该轮同时验证原失败配置和当前默认配置，四目标、工程约束及最终 CPU 精确复核口径不变。

### 选线默认参数校准

目标是一套默认参数，长、短、绕障和紧档距场景都给出还不错的方案；不按场景分档。只有一套参数在某类场景始终明显落后时，才另议分档规则。入口是 `experiments/tune_routing.py`，候选参数写在显式 manifest 中，每套候选只覆盖 `config/default_config.json` 的字段。

- 资源：每次运行按相同搜索时间 60 秒比较，设备 CPU，张量演化与张量评价。时间从搜索开始计，含初始化，不含场景准备与最终复核。运行可超过 60 秒，前沿按候选首次完成评价的时间截到 60 秒。并行进程各自固定 1 个数值线程，并记录并发数。
- 场景：六类，端点在已有场景内按距离区间与直线障碍比例随机抽取。苍南 0.8–1.3 km、档距 500 m、直线少障碍；苍南 1.1–1.6 km、档距 160 m、直线多障碍；永嘉 0.9–1.5 km、档距 180 m、直线多障碍；楠溪江 2–3 km、档距 200 m；楠溪江 4–6 km、档距 200 m、直线多障碍；楠溪江 4–6 km、档距 500 m。塔基半径 3 m，转角 90°，道路与高速退距取默认 JSON。
- 调参集与复验集：每类调参用 4 组端点 × 2 个搜索种子。复验每类另抽 4 组未用过的端点，配 3 个新种子。复验集只用于最终比较，不参与选择。
- 指标：每组端点把该轮全部运行的 60 秒前沿合成参考前沿，按参考前沿的最小值与范围归一化，常数维取 1。每次运行算 IGD+；一套参数在一类场景的成绩是该类全部运行的 IGD+ 平均值。倍数为它除以该类最好的平均值，分子分母各加 0.02，写在 manifest 的 `ratio_floor`。归一化 IGD+ 相差不到 0.02 视为没有工程差别，避免各方都接近最优的简单场景把很小的绝对差距放大成高倍数。按六类中最大的倍数排序，越小越好。任何一次运行在 60 秒内没有可行线路即淘汰；若某组端点所有候选都没有可行线路，该组从评分中去掉并记录。另报告各类的最少塔数与最小跨越长度。
- 搜索空间分两轮。第一轮比机制组合：标准模式与旧版初始化；PILOT 混合初始化（只开 `astar`、`rrt`）接标准演化；当前完整 PILOT；完整 PILOT 改为每 9 代局部搜索、局部预算倍数 4；完整 PILOT 去掉 `global_injection`；PILOT 去掉 `elite_local_search` 与 `global_injection`。第二轮在第一轮胜者上一次只改一个参数：种群 24、48、96；扩展间隔 4、8、16 代；变异步长 `mutation_scale` 0.1、0.2、0.4。
- 落地：复验集上胜者的最大倍数小于当前默认参数时，才写入 `config/default_config.json`；否则保留现有默认，只记录结果。默认 `max_generations` 看逐代收敛定：取短距绕障与中距离场景 IGD+ 仍有明显下降、而耗时还在几分钟内的代数。最初约定按中距离场景 60 秒反推，实测只有 3–7 代；改按短距绕障 60 秒取 40 代后，收敛补测显示这两类在 40 代后仍在改进，用户定为 80 代。各场景实际耗时与收敛数据写入实验记录。塔数上界的扩展规则本轮不改。
