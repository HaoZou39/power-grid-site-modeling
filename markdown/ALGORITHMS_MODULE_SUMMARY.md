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

选线迁移参考 PILOT_v2 的核心路径搜索能力，不迁移偏好反馈闭环。采用独立变长塔位序列与无权重四目标 NSGA-II，不继承站址专用 `SiteSearch`。所有目标和硬约束服从 `markdown/MODELING_MODULE_SUMMARY.md`「选线建模规格」。初始化、修复、演化与最终复核共用选线评价器，导线可跨越建筑、道路和水体，不能沿用旧项目将这些地物全部禁跨的生成器。

塔数搜索的松弛下界由最大水平档距直接推导。设两端的水平直线距离为 `D`，新增中间塔数为 `N`，则共有 `N + 1` 档，因此 `N >= max(0, ceil(D / D_max) - 1)`。这里不能改用三维距离；该下界忽略禁落塔区域、禁跨越区域及转角约束，不保证按下界布塔即可得到可行方案。

已确认塔数范围采用「直线松弛下界＋参考线路估计初始上限＋必要时扩展」：

1. 按上述公式计算新增塔数的理论下界。
2. 构造若干不掉头的参考曲线，结合最大档距布塔，检查塔基控制圆、禁落塔区、禁跨越区和最大单处转角等已定义约束，并在保持可行的前提下去除冗余塔。删塔若使跨越量等其他目标变差，应保留体现该取舍的原候选，不能把「仍可行」等同于「其余目标不变」。
3. 根据通过检查的参考线路估计紧凑的初始塔数上限。该值只是搜索范围的初始估计，不作为严格可行性上界，也不照搬原项目的固定塔数范围。
4. 搜索发现初始上限可能过紧时，在计算预算内逐步扩展。任务记录初始范围、最终范围和停止原因；不新增用户必填的最大塔数输入。具体扩展与停止规则在实施方案中集中说明。

「不掉头」仅用于构造参考线路，不作为所有候选解必须满足的额外约束。最大单处转角不单独决定塔数上界，总曲折度仍只是优化目标。可行参考线路只能为最小可行塔数提供上界，不能证明更多塔的线路在跨越量等其他目标上没有价值；扩展机制须保留对这些折中方案的搜索机会。参考线路生成失败或计算预算耗尽时，不得把未找到可行线路表述为已证明不存在可行线路。


初始参考线包括直线和侧向弯曲线；必要时用粗导航格的禁跨越绕行路径补充，最终按 1 m 数据验证。种群由插塔、删塔、移动和交叉产生，固定端点不进入基因。冗余塔删除须保留与其他目标的取舍。

主预算按评价次数控制。每到配置的扩展周期，按配置步长放开初始上限并探查新塔数，保留已有非支配档案；即使已有少塔可行解也执行探查。无可行参考线时从理论下界开始尝试和扩展，不报告已证明不可行。所有默认数值只在 `config/default_config.json` 的 `routing` 段中定义，包含种群、评价预算、参考线数量、移动尺度、扩展周期、修复尝试和导航步长。完整实现顺序与验收见 `markdown/DECISION_REQUIREMENTS.md`。

`algorithms/routing/initialization.py` 已实现直线/二次曲线参考线、仅避让人工禁跨越区的导航、按水平档距布塔、调用统一塔基检查的有限修复，以及保留目标取舍的删塔。`TowerRange` 按配置的扩展周期和步长放开初始上限，初始上限和理论下界保留用于报告。导航步长仅控制候选生成，最终仍用 1 m 数据评价。

`algorithms/routing/search.py` 已实现评价预算控制的变长 NSGA-II，初始化和删塔的目标评价均计入搜索预算；最终只读硬检查/报告另执行。`operators.py` 实现插塔、删塔、移动和交叉，调用同一塔基检查修复，绝不移动固定端点。每到扩展周期必做边界探查，已有非支配候选从全部已评价记录中保留。结果记录初始/最终范围、扩展历史、评价次数和停止原因；预算内无可行解不等于已证明不可行。

参考线修复顺序：先修复禁落塔点，再反复检查最大水平档距；超限档插入中间塔并重新执行同一塔基检查，迭代次数受已有修复尝试配置限制。最终仍由统一评价器完整判断，修复失败不伪装成可行。理论下界取整、按档距布塔、冗余塔删除与硬评价共用 `DISTANCE_TOL_M` 的数值舍入口径，避免经纬度/UTM 往返在整除处多算一档；该容差不是额外工程档距参数。

### 选线加速实施契约

用户已授权按 P0 基线、P1 张量演化、P2 精确批量评价、P3 显存/归档、P4 上下文复用、P5 质量实验、P6 双卡的顺序实施。每步先写对照、只改变一种机制，通过正确性与计时验收后提交。NumPy/CPU 参考实现保留，四目标、约束、算子含义、预算计数及塔数扩展不变。

演化使用 float64 的 `[B,K,2]` 塔位和有效数量，容量随上界扩展；固定接入点独立保存。公共张量排序由站址与选线共用。比较固定输入的支配、rank、拥挤度与选择；前沿成员按稳定候选序号处理平局。原 NumPy 前沿展开的历史顺序保留在原后端，张量后端的稳定候选序号单独记录；不将不同随机生成器的同 seed 轨迹当作逐位一致契约。移动、插塔、删塔、交叉和有限修复须通过受控随机输入及边界案例。

新增执行字段在唯一默认 JSON 中定义：`evolution_backend`（numpy/tensor）、`evaluation_backend`（reference/compiled_cpu/tensor）、`devices`、`evaluation_batch_size`、`gpu_memory_budget_mib`。设备列表首项承载张量演化，双 CUDA 设备同步分担评价后恢复候选顺序并统一选择，不采用岛模型。默认仍保留参考运行，不提高既有种群/预算；数值仅由 JSON 定义。显存预算只影响工作分块，不改变种群、评价次数、工程参数或数据分辨率；不足时明确失败。

性能报告拆分快照、上下文、初始化/修复、评价、排序、变异、归档、复核及写出，区分冷启动与预热并记录每卡 allocated/reserved 峰值。历史候选紧凑保存在 CPU，不堆积整代报告或 CUDA 历史。四目标前沿采用精确算法，不截断候选或用近似支配。大种群推荐路径须正确性全部通过且代表性端到端计时中位数至少降低 20%，小种群单独报告。

质量实验先单 seed 再使用 seed 123–127；固定预算比较种群 48/256/1024，固定种群 256 比较预算 8192/32768/131072。报告可行发现率、首次可行评价次数、覆盖、IGD+ 与加性 epsilon，并区分等评价次数和等时间。小型离散问题枚举确切前沿，真实场景只使用冻结的最佳已知参考集合；报告尺度不进入选择。不因加速同时引入新搜索策略。

P1 已实现共享张量排序、变长算子和 `evolution_backend=tensor` 的 CPU/CUDA 演化；仍调用 reference 评价，其他评价选项在安装对应实现前明确报错。高级参数保持类型并兼容旧历史配置。初始化与最终复核仍服从原精确口径。

P2/P3 已接入 reference、compiled_cpu 和 tensor 评价。搜索阶段只保留 CPU 数值记录，逐档与坡度报告在流式写出时生成，结果字段保持不变；所有可行候选先经原 CPU 逐条复核，再按复核目标重算最终前沿。四目标前沿使用字典序精确扫描与编译内核，重复目标不互相支配，返回顺序保持原候选顺序。它不截断归档，最坏仍可能二次比较，但不分配二次数量的数组。演化、排序与评价分配前检查显存工作空间，不因预算改变问题。

张量种群与 CPU 之间按整批打包传输。每次扩展的单条强制边界探查复用原 NumPy 变长算子，避免在 GPU 为同一条线路逐塔发射内核；它仍按最长档逐次插塔、同一评价器修复，不改变塔数扩展含义。搜索记录每个去重候选首次完成评价的序号与时间，仅用于性能/质量报告，不进入选择。

`experiments/benchmark_routing.py` 接收显式 manifest（tasks、cases、seeds、warmups、repeats、time_checkpoints_s），每个 case 只覆盖唯一 JSON 的配置。它保存独立快照、紧凑完整候选、CPU 复核目标、阶段耗时及每卡内存，重复运行检查坐标/目标内容哈希。所有完成前沿的并集冻结为最佳已知参考，统一 min/range 报告尺度；常数维 scale=1。IGD+、加性 epsilon 与覆盖由 `experiments/routing_metrics.py` 计算，不用于演化。等时间比较只按候选完成的搜索时间，明确不包含冷场景准备、最终复核和发布；完整耗时另报告。

双设备评价通过 `evaluation_session` 管理生命周期；`MultiDeviceRouteEvaluator` 按候选连续分片并行执行，每卡独立分块，返回时恢复原顺序，再进行一次全局选择。没有岛模型、梯度同步或异步代际更新。异常/取消必须等待评价线程结束，释放每卡场景张量与空闲缓存后才能释放任务。实际使用设备与请求设备分开记录；CPU 评价且 NumPy 演化不会因配置出现 CUDA 名称而假报 GPU 执行。
