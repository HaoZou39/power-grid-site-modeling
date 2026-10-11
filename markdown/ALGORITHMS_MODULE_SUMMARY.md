# Algorithms Module Summary

算法模块当前包含公共多目标组件、NSGA-II、CMA-ES、多起点 Adam，以及 VAE-like multi-head 候选生成器。决策界面使用 NSGA-II。CMA-ES 保留为研究入口。

具体口径分别服从：

- `markdown/ALGORITHM_COMMON.md`：目标顺序、权重、normalization、切比雪夫、Weiszfeld 和 Pareto。
- `markdown/NSGA2.md`：决策界面的 NSGA-II。它不使用目标权重。
- `markdown/CMA_ES.md`：CMA-ES 搜索流程和输出。
- `markdown/MULTISTART_ADAM.md`：多起点 Adam 搜索流程和输出。
- `markdown/VAE_LIKE_MULTIHEAD_ALGORITHM.md`：VAE-like multi-head 的网络、训练、评价、输出和执行流程。
- `markdown/VALIDATION.md`：不同算法验证流程共用的等间距偏好 CSV 生成口径。
- `markdown/FIGURES_MODULE_SUMMARY.md`：公共 figure 输出。

算法模块不读取原始 tif/csv/GeoJSON，不重新实现建模目标。数据读取由 `data_tools/` 完成，目标和 hard metrics 由 `modeling/` 完成。

## 模块和对象

人工改搜索时，先看对象再改实现。每个对象只做下面这一件事。

- `algorithms/common/search.py` 的 `SiteSearch`：所有选址搜索的父类。子类实现 `search`。父类不写权重，也不写约束名字。
- `algorithms/nsga2/nsga2.py` 的 `Nsga2Search`：决策界面的多目标搜索。不指定进货原点时比较四项，指定后加上沿路长度，名单以 `markdown/NSGA2.md` 为准。`dominates` 是两条方案谁更优的判断。`run_nsga2` 是与具体场景无关的进化循环。`guided_search.py` 在进化前用可微进场场做短程引导，支配阶段仍用精确查表。
- `algorithms/cma_es/cma_es.py` 的 `CmaEsSearch`：研究用的单目标搜索。切比雪夫和权重网格写在这个类的 `search` 里。`run_cma_es_search` 只负责构造它。
- `algorithms/common/scalarization.py`：目标顺序 `OBJECTIVE_NAMES`，以及把目标向量收成一个数的公式。只有单目标子类调用它。
- `algorithms/common/pareto.py`：从已经算好的候选记录里取出可行且互不支配的方案。它不运行搜索。
- `algorithms/multistart_adam/`：多起点 Adam，目前仍是函数入口，还没有继承 `SiteSearch`。
- `algorithms/vae_like_multihead/`：候选生成器。它不是选址搜索，不继承 `SiteSearch`。

## 扩展时改哪里

- 增加一个算法：新建一个类继承 `algorithms/common/search.py` 里的 `SiteSearch`，并实现 `search`。多目标子类直接比较 `evaluate_site_objectives` 返回的目标向量。单目标子类在自己的 `search` 里调用 `algorithms/common/scalarization.py`，父类不出现权重。然后在 `plugins/site_plugin.py` 增加配置和插件，在 `backend/app/application/registry.py` 注册，并在 `experiments/launch_site_run.py` 增加一条入口。不改数据模块，也不重写已有算法。
- 修改现有目标公式：改 `modeling/site_model.py` 里对应的 `SiteObjective` 子类。这些子类调用 `modeling/dem_model.py`、`modeling/road_model.py`、`modeling/demand_model.py` 里的公式。CMA-ES 的目标名单和顺序只维护在 `OBJECTIVE_NAMES`。决策搜索的名单在 `nsga2_objective_names`，口径见 `markdown/NSGA2.md`。
- 修改硬约束：用地类别和手绘禁区改 `experiments/constraint_mask.py`。可行性数值由 `ObstacleCountConstraint` 汇总为 `constraint_violation`。新的硬约束继承 `SiteConstraint`。算法读取这个数值，不自己挑选某个计数字段。
