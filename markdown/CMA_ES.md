# CMA-ES Region Optimization Plan

本文档记录当前项目使用 CMA-ES 搜索区域站址候选解的实验口径。后续实现算法模块或实验脚本时，必须先服从本文档；如果实验口径变化，应先更新本文档，再修改代码。

## 1. 总体口径

CMA-ES 是单目标黑盒优化算法。本项目用切比雪夫加权把多个目标压成一个标量目标，对多组权重分别运行 CMA-ES，得到一批候选解；再从可行候选中提取 Pareto 最优解。

CMA-ES 不读取原始 DEM、landuse、OSM GeoJSON，也不生成需求点。它只使用数据模块已经生成的 1 m 局部栅格产物，并通过建模模块 evaluator 计算目标值和 hard 指标。

当前真实区域实验中，数据模块以 landuse / obstacle 的主栅格为统一空间基准。DEM 必须重投影 / 重采样到该主栅格，道路 Voronoi 和 `road_segments_local` 必须由 OSM 道路投影到参考 GeoTIFF CRS 后映射到该主栅格。CMA-ES 只消费对齐后的 DEM、obstacle、道路和需求点产物，不在算法模块内处理 CRS、bounds 或经纬度转换。

算法子包：

```text
algorithms/cma_es/
  __init__.py
  weiszfeld.py       # 兼容导出，真实实现来自 algorithms/common/
  cma_es.py          # CMA-ES 搜索与候选记录
  pareto.py          # 兼容导出，真实实现来自 algorithms/common/
  cma_es_main.py     # 总入口与输出编排
```

职责边界：

- `algorithms/common/weiszfeld.py` 只计算需求点加权几何中位点和 `demand_ideal`。
- `cma_es.py` 负责 CMA-ES 搜索、候选解记录和可行性标记。
- `algorithms/common/pareto.py` 只根据候选记录提取 Pareto 最优解，不调用 CMA-ES，不重新计算目标。
- `cma_es_main.py` 只负责串联数据准备、CMA-ES、Pareto、绘图和文件输出。
- 目标顺序、权重、normalization、切比雪夫和 Weiszfeld 参数统一服从 `markdown/ALGORITHM_COMMON.md`。

## 2. 优化变量

CMA-ES 优化无边界变量：

```python
raw_pose = [raw_x, raw_y, raw_theta]
```

每个候选 `raw_pose` 必须通过建模模块的 `decode_raw_pose` 解码为真实站址：

```python
pose = [x, y, theta]
```

约定：

- `raw_pose` 是无边界实数变量。
- `x`、`y` 是 1 m 局部栅格连续坐标。
- `theta` 是矩形站址朝向角。
- 坐标系原点在矩阵左上角，`x` 向右，`y` 向下，单位为米。
- 算法模块不直接优化整数像素，也不绕过 `decode_raw_pose` 自己处理边界。

## 3. 目标与可行性

默认参与切比雪夫加权的目标为：

```text
dem_soft
road_distance
demand_distance
```

三者均为越小越好：

- `dem_soft`：站址 footprint 内 DEM soft variance。
- `road_distance`：站址中心到道路的距离。
- `demand_distance`：站址中心到需求点集合的加权距离。

`obstacle_soft` 不作为多目标之一，只作为搜索阶段惩罚项加入标量目标。

hard constraint 不在 CMA-ES 搜索过程中删除候选，只在结果阶段标记：

```text
is_feasible = obstacle_hard_count == 0
```

## 4. Utopian Point 与 Scale

切比雪夫加权前先做归一化。默认 `ideal`：

```text
dem_soft ideal = 0
road_distance ideal = 0
demand_distance ideal = Weiszfeld 加权几何中位点对应需求距离
```

由于 `dem_soft` 是方差，数值可能变化很大，不使用随机样本最大值作为尺度。默认使用采样目标差值的高分位数作为 scale：

```text
dem_scale = p95(sampled_dem_soft - dem_ideal)
road_scale = p95(sampled_road_distance - road_ideal)
demand_scale = p95(sampled_demand_distance - demand_ideal)
```

要求：

- 默认分位数为 `95`，其他分位数必须通过配置控制。
- 所有 scale 必须大于 0，否则直接 `ValueError`。
- 归一化样本数量和 seed 必须写入 `normalization.json`。
- normalization 样本数量、分位数、seed、Weiszfeld 参数和 scalarization eps 属于公共配置 `common`，不属于 `cma_es` 配置。

归一化公式：

```text
normalized_objective_i = (objective_i - ideal_i) / (scale_i + eps)
normalized_objective_i = max(0, normalized_objective_i)
```

## 5. Weiszfeld 模块

`algorithms/common/weiszfeld.py` 负责计算需求目标的 ideal value。`algorithms/cma_es/weiszfeld.py` 仅作为兼容导出入口，不维护另一份实现。

加权几何中位点：

```text
p* = argmin_p sum_n demand_weight_n * ||p - demand_point_n||
```

需求目标 ideal value：

```text
demand_ideal = sum_n normalized_weight_n * ||p* - demand_point_n||
```

建议公开函数：

```python
compute_weighted_geometric_median(
    demand_points: np.ndarray,
    demand_weights: np.ndarray | None,
    max_iters: int,
    tol: float,
    eps: float,
) -> np.ndarray

compute_demand_ideal_value(
    demand_points: np.ndarray,
    demand_weights: np.ndarray | None,
    max_iters: int,
    tol: float,
    eps: float,
) -> float
```

要求：

- `demand_weights is None` 时使用等权。
- 权重在函数内部归一化。
- 需求点为空、shape 不合法、权重为负或权重和为 0 时，直接 `ValueError`。
- 迭代点与需求点距离过小时必须稳定处理，避免除零。

## 6. CMA-ES 模块

`algorithms/cma_es/cma_es.py` 负责运行 CMA-ES 并生成候选记录。

切比雪夫标量目标：

```text
scalar = max_i(weight_i * normalized_objective_i) + obstacle_penalty_scale * obstacle_soft
```

目标顺序固定为：

```text
dem_soft
road_distance
demand_distance
```

权重必须满足：

```text
weight_dem >= 0
weight_road >= 0
weight_demand >= 0
weight_dem + weight_road + weight_demand = 1
```

`cma_es.py` 至少返回或生成以下记录：

- `normalization.json` 所需记录。
- `runs.csv` 所需记录。
- `solutions.csv` 所需记录。

每个候选解必须记录 `raw_pose`、解码后的 `[x, y, theta]`、scalar、soft objectives、hard metrics 和 `is_feasible`。

## 7. Pareto 模块

`algorithms/common/pareto.py` 只负责从候选记录中提取 Pareto 最优解。`algorithms/cma_es/pareto.py` 仅作为兼容导出入口，不维护另一份实现。

建议公开函数：

```python
extract_feasible_pareto_front(
    records: Sequence[Mapping[str, object]],
    objective_names: Sequence[str],
    feasible_key: str = "is_feasible",
) -> list[dict[str, object]]
```

要求：

- 只从 `is_feasible == True` 的候选中提取。
- 不可行候选保留在 `solutions.csv` 中，但不进入 Pareto 最优解集合。
- 使用原始目标值，不使用归一化目标值。
- 默认目标均按最小化处理。
- 输出记录保留输入记录的所有字段。

默认 Pareto 目标：

```text
dem_soft
road_distance
demand_distance
```

候选 A 支配候选 B 当且仅当：

```text
A 在三个目标上都不大于 B
且 A 至少在一个目标上严格小于 B
```

如果没有任何可行候选，`pareto_solutions.csv` 为空，并在运行摘要中记录 `no_feasible_solution`。

## 8. 主入口与输出

`algorithms/cma_es/cma_es_main.py` 负责总调用：

1. 准备数据模块和建模模块上下文。
2. 调用 `cma_es.py` 运行多组权重 CMA-ES。
3. 写出 `normalization.json`、`runs.csv`、`solutions.csv`。
4. 调用 `pareto.py` 提取 Pareto 最优解。
5. 写出 `pareto_solutions.csv`。
6. 生成四张空间分布图。
7. 生成 Pareto 3D interactive HTML。

推荐输出目录：

```text
outputs/cmaes_region/
```

推荐输出文件：

```text
resolved_config.json
normalization.json
runs.csv
solutions.csv
pareto_solutions.csv
all_candidates_points_map.png
all_candidates_footprints_map.png
pareto_points_map.png
pareto_footprints_map.png
pareto_3d_interactive.html
```

当前不输出 `best_solution.json`，也不默认用均衡权重从结果中选一个最终推荐点。

## 9. 输出字段

`normalization.json` 至少记录：

```text
ideal_dem
ideal_road
ideal_demand
scale_dem
scale_road
scale_demand
scale_percentile
normalization_samples
normalization_seed
```

`solutions.csv` 至少记录：

```text
run_id
weight_dem
weight_road
weight_demand
raw_x
raw_y
raw_theta
x
y
theta
scalar
dem_soft
obstacle_soft
road_distance
demand_distance
dem_hard_var
dem_hard_range
obstacle_hard_count
obstacle_hard_ratio
is_feasible
```

`pareto_solutions.csv` 只记录 hard feasible 的 Pareto 最优解，字段与 `solutions.csv` 保持一致。

## 10. 空间分布图

必须输出四张空间分布图：

```text
all_candidates_points_map.png
all_candidates_footprints_map.png
pareto_points_map.png
pareto_footprints_map.png
```

含义：

- `all_candidates_points_map.png`：所有 hard feasible 候选解中心点。
- `all_candidates_footprints_map.png`：所有 hard feasible 候选解站址矩形 footprint。
- `pareto_points_map.png`：Pareto 最优解中心点。
- `pareto_footprints_map.png`：Pareto 最优解站址矩形 footprint。

所有图都使用 1 m DEM 作为底图，叠加不可建设区域 `obstacle_mask`，并用单独颜色标出需求点。绘图坐标必须使用 1 m 局部栅格坐标系，不混用经纬度坐标。

还必须输出 Pareto 3D interactive HTML：

```text
pareto_3d_interactive.html
```

该 HTML 使用 `pareto_solutions.csv` 对应记录，三轴固定为：

```text
dem_soft
road_distance
demand_distance
```

HTML 只展示已经提取好的 Pareto records，不重新计算 Pareto、不重新计算目标函数、不重新计算 scalar。

## 11. 建议配置项

CMA-ES 专属配置只维护搜索参数：

```python
algorithm_name: str = "cma_es"
seed: int
popsize: int
sigma0: float
max_iters: int
restarts_per_weight: int
```

以下参数属于公共多目标配置 `common`，CMA-ES 和多起点 Adam 共享，不在 `cma_es` 中重复定义：

```python
normalization_samples: int
normalization_scale_percentile: float
normalization_seed: int
weight_grid_step: float
min_weight: float
obstacle_penalty_scale: float
scalarization_eps: float
weiszfeld_max_iters: int
weiszfeld_tol: float
weiszfeld_eps: float
```

这些参数不应硬编码在实验脚本内部，也不应在具体算法配置中重复维护。

## 12. 依赖约定

默认使用现成 Python CMA-ES 实现库，例如 `cma` / `pycma`。如果环境中缺少依赖，应在使用 CMA-ES 功能时明确报错。

不建议在当前阶段从零手写 CMA-ES 算法核心，除非后续文档明确要求。

## 13. 测试重点

后续实现时至少需要覆盖：

- Weiszfeld 等权和加权结果。
- Weiszfeld 非法输入报错。
- 权重生成 deterministic。
- normalization 使用 `ideal` 和分位数 scale，且结果非负。
- 切比雪夫标量化数值正确。
- `obstacle_soft` 惩罚会增加 scalar。
- CMA-ES smoke test 能在小型合成数据上输出有限数值。
- 输出候选解的 `[x, y, theta]` 来自 `decode_raw_pose`，且在合法范围内。
- hard feasible 判断只使用 `obstacle_hard_count == 0`。
- Pareto 提取只使用 hard feasible 候选，且支配关系按三个原始目标最小化判断。
- CSV 输出字段完整。
- 四张空间分布图能正常生成。
- Pareto 3D HTML 能正常生成，并包含三目标字段。

## 14. Assumptions

- 用户之前说的 `cmsea` 在本文档中按 `CMA-ES` 理解。
- CMA-ES 本身是单目标算法；多目标口径通过切比雪夫加权和多组权重重复运行实现。
- `obstacle_soft` 默认用于搜索惩罚，最终可行性由 hard obstacle 指标决定。
- DEM 方差目标使用 `ideal=0` 和采样分位数 scale，避免极端 DEM 方差支配归一化尺度。
- 输出以 CSV 和空间分布图为主，不输出 `best_solution.json`。
- 本文档只定义算法实验口径，不包含具体代码实现。
