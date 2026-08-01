# Algorithm Common Components Plan

本文档记录当前项目中与具体优化器无关的多目标算法公共口径。CMA-ES、多起点 Adam 以及后续其他算法都应调用这里定义的公共逻辑，不各自维护目标顺序、normalization、切比雪夫公式或 Pareto 判定。

本文档只定义公共算法组件。具体搜索过程分别由 `markdown/CMA_ES.md`、`markdown/MULTISTART_ADAM.md` 等算法文档定义。

后续实现前以本文档为准。如果公共实验口径变化，先更新本文档，再修改代码。

## 1. 公共组件边界

公共组件负责：

- 固定目标顺序。
- 校验和生成偏好权重。
- 计算一次并保存 `ideal` 和 `scale`。
- 对当前候选目标应用固定 normalization。
- 执行切比雪夫标量化。
- 计算需求目标的 Weiszfeld ideal。
- 根据 hard feasible 候选提取 Pareto front。

公共组件不负责：

- 生成 CMA-ES population。
- 创建或更新 Adam optimizer。
- 决定每个算法的迭代次数、种群数量或起点数量。
- 读取原始 tif、csv 或 GeoJSON。
- 在算法内部重新实现建模目标。
- 选择一个最终推荐解。

数据模块负责生成标准数据产物，建模模块 evaluator 负责计算原始目标和 hard metrics，具体算法只负责产生候选。

## 2. 建议目录

```text
algorithms/
  common/
    __init__.py
    scalarization.py   # 权重、ideal/scale、normalization、切比雪夫
    weiszfeld.py       # demand ideal
    pareto.py          # hard feasible Pareto 提取
```

职责：

- `scalarization.py` 是目标顺序、权重、normalization 和切比雪夫公式的唯一来源。
- `weiszfeld.py` 只计算需求点加权几何中位点和 `demand_ideal`。
- `pareto.py` 只处理已经完成评价的候选记录，不调用任何优化器，也不重新计算目标。

## 3. 固定目标顺序

参与偏好权重和切比雪夫标量化的目标固定为：

```text
dem_soft
road_distance
demand_distance
```

三个目标均按最小化处理。

权重向量按同一顺序解释：

```python
weights = [weight_dem, weight_road, weight_demand]
```

如果调用方提供的目标顺序不匹配，直接 `ValueError`，不静默重排。

`obstacle_soft` 不进入三目标权重向量，只作为搜索阶段的独立可微惩罚项。

## 4. 权重生成与校验

每个权重必须满足：

```text
weight_dem >= 0
weight_road >= 0
weight_demand >= 0
weight_dem + weight_road + weight_demand = 1
```

公共模块提供：

```python
normalize_weight_vector(...)
generate_weight_grid(...)
```

权重网格由 `weight_grid_step` 显式控制。该步长必须能在容差范围内整除 `1.0`，否则直接 `ValueError`。

如果配置 `min_weight > 0`，先将每个分量提升到最小值，再重新归一化。生成顺序必须 deterministic，保证不同算法使用相同的偏好序列和 `weight_index`。

## 5. Normalization 固定口径

Normalization 不是 BatchNorm。它没有 running statistics，也不在任何优化器的迭代过程中更新。

每次完整实验在遍历偏好和执行搜索之前只计算一次：

```text
ideal_dem
ideal_road
ideal_demand
scale_dem
scale_road
scale_demand
```

默认 ideal：

```text
ideal_dem = 0
ideal_road = 0
ideal_demand = Weiszfeld 加权几何中位点对应的需求距离
```

默认 scale 使用固定 normalization 样本的目标差值高分位数：

```text
scale_i = percentile(
    max(0, sampled_objective_i - ideal_i),
    scale_percentile,
)
```

要求：

- normalization 样本数量、seed 和 percentile 显式配置。
- normalization 样本通过建模模块 evaluator 计算。
- 所有 scale 必须是有限正数，否则直接 `ValueError`。
- 同一次实验的所有算法轮次、偏好、候选和迭代使用同一个固定 normalization。
- 不按偏好重新估计 ideal/scale。
- 不在 CMA-ES generation、Adam step 或其他算法迭代中重新估计 ideal/scale。
- `normalization.json` 必须记录全部 ideal、scale、样本数量、percentile 和 seed。

候选位置变化后，只重新计算当前位置的原始目标，并应用同一组固定参数：

```text
normalized_i(x)
    = max(0, (objective_i(x) - ideal_i) / (scale_i + eps))
```

这里变化的是 `objective_i(x)` 和归一化后的目标值，不是 `ideal_i` 或 `scale_i`。

## 6. Weiszfeld Demand Ideal

`weiszfeld.py` 负责计算需求点的加权几何中位点：

```text
p* = argmin_p sum_n demand_weight_n * ||p - demand_point_n||
```

需求目标 ideal：

```text
demand_ideal
    = sum_n normalized_weight_n * ||p* - demand_point_n||
```

公共函数：

```python
compute_weighted_geometric_median(...)
compute_demand_ideal_value(...)
```

要求：

- `demand_weights is None` 时使用等权。
- 权重在函数内部归一化。
- 需求点为空、shape 不合法、权重为负或权重和为零时直接 `ValueError`。
- 迭代点与需求点距离过小时稳定处理，避免除零。
- Weiszfeld 只参与 normalization 初始化，不在每个偏好或每个优化 step 中重复计算。

## 7. 切比雪夫标量化

公共切比雪夫目标固定为：

```text
scalar(x, w)
    = max_i(weight_i * normalized_i(x))
    + obstacle_penalty_scale * obstacle_soft(x)
```

其中：

- `i` 按固定顺序遍历三个原始目标。
- `weights` 是当前偏好权重。
- `normalized_i(x)` 使用本次实验固定的 ideal 和 scale。
- `obstacle_penalty_scale` 必须非负。
- `obstacle_soft` 是搜索惩罚，不是 Pareto 目标。

公共模块提供两个明确入口：

```python
scalarize_tchebycheff_numpy(...)  # 黑盒优化算法使用
scalarize_tchebycheff_torch(...)  # 梯度算法使用，保留计算图
```

对于一个 batch 内每个候选使用不同偏好权重的条件生成算法，公共模块增加：

```python
scalarize_tchebycheff_torch_batched(
    objectives: dict[str, torch.Tensor],  # 每项 shape [N]
    weights: torch.Tensor,                # shape [N, 3]
    normalization: dict[str, float | int],
    obstacle_penalty_scale: float,
    eps: float = 0.0,
) -> torch.Tensor                         # shape [N]
```

要求：

- 每行权重均非负、有限且归一化为和 1。
- 第 `n` 个候选只使用 `weights[n]`，候选之间不混合目标或梯度。
- 与现有 Torch 入口共享相同的目标顺序、normalization、clamp、obstacle penalty 和数学实现，不维护第二套公式。
- 当 `weights` 每行相同时，输出必须与现有 `scalarize_tchebycheff_torch` 一致。
- 不能 detach、转换为 NumPy 或使用 `torch.no_grad()`，必须保留完整计算图。
- 现有 CMA-ES 和 multi-start Adam 调用方式保持不变；需要不同 batch 权重的算法显式调用 batched 入口。

所有 scalarization 入口必须使用相同的：

- 目标顺序。
- 权重校验。
- ideal 和 scale。
- clamp 规则。
- obstacle penalty。
- 数学公式。

不要在一个函数中隐式判断 NumPy 或 PyTorch 输入。PyTorch 入口不能 detach、转换为 NumPy 或在内部使用 `torch.no_grad()`。

`torch.max` 在分支相等处使用子梯度，在其他位置正常反向传播。这是切比雪夫标量化本身的分段可微性质。

## 8. Hard Feasible 公共口径

搜索阶段不使用 hard constraint 删除候选。候选搜索完成后，通过建模模块统一计算 hard metrics。

最终可行性只由以下条件判断：

```text
is_feasible = obstacle_hard_count == 0
```

以下内容不能改变 hard feasible 判定：

- `obstacle_soft`。
- scalar。
- 偏好权重。
- DEM hard range。
- DEM hard variance。

这些值可以记录和报告，但不替代 `obstacle_hard_count == 0`。

## 9. Pareto 提取

公共 `pareto.py` 接收已经包含原始目标和 `is_feasible` 的候选记录。

Pareto 只从：

```text
is_feasible == True
```

的候选中提取。

默认 Pareto 目标为三个原始值：

```text
dem_soft
road_distance
demand_distance
```

Pareto 判断不使用：

- scalar。
- 权重。
- normalized objectives。
- obstacle soft penalty。

候选 A 支配候选 B 当且仅当：

```text
A 在三个目标上都不大于 B
且 A 至少在一个目标上严格小于 B
```

公共函数：

```python
extract_feasible_pareto_front(...)
```

输出记录保留输入记录的所有字段。不可行候选继续保留在算法自己的 `solutions.csv` 中，但不进入 `pareto_solutions.csv`。

如果没有可行候选，Pareto 输出保留表头，并由实验摘要记录：

```text
no_feasible_solution = true
```

## 10. 公共配置

建议由公共多目标配置统一维护：

```text
normalization_samples
normalization_scale_percentile
normalization_seed
weight_grid_step
min_weight
obstacle_penalty_scale
scalarization_eps
weiszfeld_max_iters
weiszfeld_tol
weiszfeld_eps
```

具体算法配置不重复定义这些字段。CMA-ES 只维护 CMA-ES 搜索参数，多起点 Adam 只维护 Adam 和起点参数。

## 11. 公共输出字段语义

所有算法输出的候选记录至少共享：

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

具体算法可以增加自己的字段，例如 CMA-ES restart 或 Adam start id，但不能改变公共字段含义。

## 12. 公共测试重点

后续实现至少覆盖：

- 权重生成 deterministic，顺序和归一化正确。
- 非法权重和不能整除 `1.0` 的步长直接报错。
- normalization 使用固定 ideal 和 percentile scale。
- normalization 在同一次实验中只计算一次。
- 所有 scale 有限且大于零。
- Weiszfeld 等权、加权和非法输入。
- NumPy 和 PyTorch 切比雪夫入口对同一输入返回一致数值。
- PyTorch 切比雪夫入口保留计算图和有限梯度。
- Batched PyTorch 入口支持每个候选使用不同权重；权重行相同时与现有 PyTorch 入口数值一致，并保留有限梯度。
- obstacle soft penalty 会增加 scalar。
- hard feasible 只使用 `obstacle_hard_count == 0`。
- Pareto 只使用 hard feasible 候选和三个原始目标。
- Pareto 输出保留候选的全部输入字段。

## 13. 公共组件迁移顺序

后续实现按以下顺序进行：

1. 将 scalarization、Weiszfeld 和 Pareto 从 `algorithms/cma_es/` 移到 `algorithms/common/`。
2. 为 NumPy 和 PyTorch 建立公式一致的切比雪夫入口。
3. 调整 CMA-ES 从公共模块导入，保持现有 CMA-ES 行为和输出不变。
4. 运行现有 CMA-ES utility tests，确认迁移前后数值一致。
5. 再让多起点 Adam 调用公共模块。

## 14. 已确认决定

- normalization、切比雪夫和 Pareto 属于算法公共逻辑。
- ideal 和 scale 每次完整实验只计算一次，后续固定不动。
- 对新候选反复应用固定 normalization，不重新估计 normalization 参数。
- 使用切比雪夫形式，不改成线性加权和。
- obstacle soft 只作为搜索惩罚，不进入三目标权重和 Pareto。
- hard feasible 只使用 `obstacle_hard_count == 0`。
- Pareto 使用 hard feasible 候选的三个原始目标。
- CMA-ES 和多起点 Adam 必须共享同一套公共实现。
