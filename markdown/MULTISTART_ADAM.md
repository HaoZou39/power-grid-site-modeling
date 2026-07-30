# Multi-start Adam Region Optimization Plan

本文档只记录多起点 Adam 搜索区域站址候选解的专属口径。目标顺序、权重生成、normalization、切比雪夫标量化、hard feasible 和 Pareto 提取统一服从 `markdown/ALGORITHM_COMMON.md`，不在本文档重复定义。

本文档与 `markdown/CMA_ES.md` 并列维护。多起点 Adam 不调用 CMA-ES，也不依赖 CMA-ES 的搜索过程。

后续实现前以本文档为准。如果多起点 Adam 的实验口径变化，先更新本文档，再修改代码。

## 1. 目标与边界

多起点 Adam 使用 PyTorch 对站址 `raw_pose` 直接做梯度优化。

多起点 Adam 负责：

- 逐个遍历公共模块生成的偏好权重。
- 为每个偏好权重生成多个随机起点。
- 为每个偏好权重独立创建 Adam optimizer。
- 在一个 batch 中并行更新当前偏好的全部起点。
- 记录每个起点在下降过程中的历史最佳解。
- 把全部候选交给公共 hard feasible 和 Pareto 后处理。
- 写出本算法的运行记录、候选解、空间分布图和 Pareto 3D HTML。

多起点 Adam 不负责：

- 自己定义目标顺序、权重网格或切比雪夫公式。
- 自己估计另一套 ideal/scale。
- 自己实现 Pareto 判定。
- 自己实现公共绘图逻辑。
- 调用 CMA-ES。
- 读取原始 tif、csv 或 GeoJSON。
- 在算法内部重新实现 DEM、obstacle、road 或 demand 建模。

数据产物来自数据模块，原始 soft objectives 和 hard metrics 来自建模模块 evaluator，标量化和 Pareto 来自 `algorithms/common/`，公共展示图来自 `figures/`。

## 2. 建议目录

```text
algorithms/
  common/                  # 见 ALGORITHM_COMMON.md
  multistart_adam/
    __init__.py
    multistart_adam.py     # 起点初始化、Adam 更新、历史最佳记录
    multistart_adam_main.py # 实验组装、后处理和输出

experiments/
  run_multistart_adam_region.py

figures/                    # 见 FIGURES_MODULE_SUMMARY.md
  candidate_maps.py
  pareto_3d.py
```

职责：

- `multistart_adam.py` 只负责搜索过程，输入已准备的问题上下文和固定公共参数，返回运行记录与候选解。
- `multistart_adam_main.py` 负责准备数据与建模上下文、调用搜索、调用公共 Pareto、调用 `figures/` 和文件输出。
- `run_multistart_adam_region.py` 是独立实验入口，不与 CMA-ES 入口合并。

## 3. 优化变量

当前偏好下的优化变量为一个 batch：

```python
raw_pose_batch.shape == [K, 3]
```

其中：

- `K = starts_per_weight`。
- 每行是一个独立起点 `[raw_x, raw_y, raw_theta]`。
- `raw_pose_batch` 是需要梯度的叶子张量或 `torch.nn.Parameter`。

每一步必须通过建模模块的 `decode_raw_pose` 解码：

```python
pose_batch.shape == [K, 3]  # [x, y, theta]
```

算法不能绕过 `decode_raw_pose` 自己裁剪 `x`、`y` 或 `theta`。安全边距、坐标范围和角度范围继续服从建模模块定义。

## 4. 逐偏好执行与 batch 语义

多起点 Adam 使用“外层逐偏好、内层批量起点”：

```python
normalization = compute_normalization_stats(...)  # 整个实验一次
weight_vectors = generate_weight_grid(...)

for weight_index, weights in enumerate(weight_vectors):
    raw_pose_batch = initialize_starts(K, ...)
    optimizer = torch.optim.Adam([raw_pose_batch], lr=learning_rate)

    for step in range(max_steps):
        ...
```

语义：

- 一个偏好权重对应一轮完整优化。
- 一轮完整优化包含 `max_steps` 次 Adam 更新，不是只下降一步。
- 当前轮次的 `K` 个起点共享同一组偏好权重。
- 每个起点的位置、目标值、scalar 和梯度彼此独立。
- 下一组偏好重新初始化起点，并重新创建 Adam optimizer。
- 不允许把上一偏好的 Adam 一阶矩或二阶矩状态带到下一偏好。

暂不把“全部权重 × 全部起点”合成一个超大 optimizer batch。逐偏好执行便于控制显存、记录每轮结果和定位异常，也符合“每个偏好是一轮计算”的实验定义。

## 5. Adam 更新

每个偏好独立创建：

```python
optimizer = torch.optim.Adam(
    [raw_pose_batch],
    lr=learning_rate,
)
```

每一步执行：

```python
optimizer.zero_grad()

pose_batch = decode_raw_pose(raw_pose_batch, ...)
objectives = evaluate_site_objectives(..., pose_batch)
scalar_per_start = scalarize_tchebycheff_torch(
    objectives=objectives,
    weights=weights,
    normalization=normalization,
    obstacle_penalty_scale=obstacle_penalty_scale,
)

loss = scalar_per_start.sum()
loss.backward()
optimizer.step()
```

要求：

- `objectives` 中每个值的 shape 都是 `[K]`。
- `scalar_per_start.shape == [K]`。
- 使用公共 PyTorch 切比雪夫入口，不能复制一份 Adam 专用公式。
- 公共入口必须保留计算图，算法中不能对 soft objectives 或 scalar 做 detach 后再 backward。
- 使用 `sum()`，避免起点数量 `K` 通过 `mean()` 额外缩小每行梯度。
- evaluator 和 scalarization 不能跨 batch 行平均不同起点的目标。

第 `k` 行的 scalar 只依赖第 `k` 行的 `raw_pose`。多个起点共享 GPU batch 计算，但不互相改变下降方向。

每一步都需要重新计算当前位置的原始目标和 scalar，以建立当前 `raw_pose` 到 loss 的计算图。公共 normalization 的 ideal 和 scale 始终固定，不在 Adam step 中更新。

## 6. 多起点初始化

起点数量和 seed 必须显式配置并可复现。

默认不使用：

```python
raw_pose ~ Normal(0, 1)
```

因为 sigmoid 会使这种初始化偏向合法区域中心。默认在 sigmoid 输出空间均匀采样，再转换为 raw pose：

```python
u = Uniform(init_eps, 1 - init_eps)  # shape [K, 3]
raw_pose = logit(u)
```

这样解码后的 `x`、`y` 和 `theta` 能更均匀覆盖各自合法范围。

要求：

- `0 < init_eps < 0.5`，避免 `logit(0)` 和 `logit(1)`。
- 起点直接创建在配置指定的 CUDA device 上。
- 同一配置重复运行时，每个偏好的起点 batch 一致。
- 每个偏好使用确定性派生 seed，例如：

```text
preference_seed = base_seed + weight_index
```

## 7. 历史最佳解记录

不能只将 Adam 最后一步作为结果，因为最后一步不保证优于之前步骤。

当前偏好的每个起点分别维护：

```python
best_scalar.shape == [K]
best_raw_pose.shape == [K, 3]
best_step.shape == [K]
```

每一步 forward 后逐行比较：

```python
improved = scalar_per_start < best_scalar
```

只更新发生改进的行。保存历史最佳 raw pose 时必须 detach 并复制，不能让它继续被 optimizer 原地更新。

最后一次 `optimizer.step()` 后再额外 forward 一次，避免遗漏更新后的最终位置。

默认保留当前偏好全部 `K` 个起点的历史最佳解，不只保留 scalar 最小的一个。不同起点可能收敛到不同局部最优，并在三个原始目标空间中形成不同的 Pareto 候选。

默认不输出每一步的完整轨迹，避免输出量随：

```text
n_weights × starts_per_weight × max_steps
```

快速增长。`runs.csv` 记录每个偏好轮次，`solutions.csv` 记录每个起点的历史最佳解。

## 8. 后验评价与 Pareto 调用

完成全部偏好后，候选总数为：

```text
n_candidates = n_weights × starts_per_weight
```

算法对所有历史最佳 raw pose 统一解码并计算：

- soft objectives。
- hard metrics。
- `is_feasible`。

然后把完整候选记录交给公共：

```python
extract_feasible_pareto_front(...)
```

hard feasible 和 Pareto 的目标与判定完全服从 `markdown/ALGORITHM_COMMON.md`。多起点 Adam 不在自己的模块中复制支配关系或改变可行性定义。

## 9. Adam 专属配置

多起点 Adam 只维护自己的搜索配置：

```text
algorithm_name = "multistart_adam"
seed
starts_per_weight
max_steps
learning_rate
init_eps
```

权重、normalization、切比雪夫、obstacle penalty 和 Weiszfeld 参数属于公共配置 `common`，见 `markdown/ALGORITHM_COMMON.md`，不在 Adam config 中重复定义。CMA-ES 也使用同一组公共参数。

第一版直接使用 `torch.optim.Adam` 的默认 `betas`、`eps` 和 `weight_decay`，不增加当前没有实验需求的：

- scheduler。
- early stopping。
- gradient clipping。
- 多 optimizer 选择。

后续如果需要改变这些口径，先补充本文档和配置。

## 10. 输出

推荐输出目录：

```text
outputs/multistart_adam_region/
```

输出文件：

```text
resolved_config.json
normalization.json
runs.csv
solutions.csv
pareto_solutions.csv
run_summary.json
all_candidates_points_map.png
all_candidates_footprints_map.png
pareto_points_map.png
pareto_footprints_map.png
pareto_3d_interactive.html
```

公共候选字段含义服从 `markdown/ALGORITHM_COMMON.md`。

`runs.csv` 每个偏好权重一行，Adam 专属字段至少包括：

```text
preference_id
weight_index
seed
starts_per_weight
max_steps
learning_rate
```

同时记录公共权重字段：

```text
weight_dem
weight_road
weight_demand
```

`solutions.csv` 每个起点的历史最佳解一行，在公共候选字段之外增加：

```text
preference_id
start_id
best_step
```

`pareto_solutions.csv` 字段与 `solutions.csv` 一致，只包含公共 Pareto 模块返回的候选。

`run_summary.json` 至少记录：

```text
n_preferences
n_starts_per_preference
n_solutions
n_feasible
n_pareto
no_feasible_solution
```

当前不输出 `best_solution.json`，也不按均衡权重额外选择最终推荐点。

四张空间图的坐标系、底图和候选含义与 CMA-ES 保持可比较，但绘图逻辑不放进 `multistart_adam.py` 搜索核心。

Pareto 3D HTML 使用 `pareto_solutions.csv` 对应记录，三轴固定为：

```text
dem_soft
road_distance
demand_distance
```

HTML 只展示已经提取好的 Pareto records，不重新计算 Pareto、不重新计算目标函数、不重新计算 scalar。具体 HTML 生成逻辑服从 `markdown/FIGURES_MODULE_SUMMARY.md`。

## 11. Adam 专属测试重点

后续实现至少覆盖：

- 相同 seed 生成相同起点。
- 不同偏好使用确定性派生 seed。
- 初始化后的有界 pose 近似覆盖合法范围，而不是集中在中心。
- 一个偏好 batch 中每个起点有独立、有限的梯度。
- `loss.backward()` 后 `raw_pose_batch.grad.shape == [K, 3]`。
- 每个偏好重新创建 Adam，不继承其他偏好的 optimizer state。
- 一个优化 step 能更新 raw pose 并保持有限数值。
- 历史最佳记录不劣于对应起点最后一步。
- 最后一次 optimizer update 后的候选不会被漏记。
- 输出 pose 来自 `decode_raw_pose`，且位于合法范围。
- 小型合成数据 smoke test 能完成多权重、多起点运行。
- 候选数量等于 `n_weights × starts_per_weight`。
- CSV 的 Adam 专属字段、四张空间图和 Pareto 3D HTML 完整。

公共权重、normalization、切比雪夫、hard feasible 和 Pareto 测试统一放在公共组件测试中，不在 Adam 测试中重复维护。

## 12. 实现顺序

1. 先按 `markdown/ALGORITHM_COMMON.md` 完成公共组件迁移，并确认 CMA-ES 行为不变。当前已完成。
2. 增加多起点 Adam config。当前已完成。
3. 实现可复现的均匀有界空间起点初始化。当前已完成。
4. 实现逐偏好、批量起点 Adam 更新。当前已完成。
5. 实现每个起点的历史最佳记录。当前已完成。
6. 实现独立实验入口和输出编排。当前已完成。
7. 调用 `figures/` 生成四张 candidate map 和 `pareto_3d_interactive.html`。当前已完成。
8. 增加多起点 Adam deterministic、gradient 和 smoke tests。当前已完成基础 deterministic 和 smoke tests。
9. 最后运行真实区域实验。当前未运行正式真实区域实验。

## 13. 已确认决定

- 优化器使用 `torch.optim.Adam`，不使用普通 SGD。
- 不调用 CMA-ES；只调用算法公共组件。
- 每个偏好权重是一轮独立优化。
- 每轮用一个 `[K, 3]` batch 同时维护多个起点。
- 每个偏好重新初始化起点并重新创建 Adam。
- 每一步对当前位置的新目标值调用公共 PyTorch 切比雪夫入口。
- ideal 和 scale 由公共模块在实验开始时计算一次，后续固定不动。
- 保存每个起点的历史最佳解。
- 所有偏好和所有起点给出的候选统一进行 hard 后验评价。
- 所有 hard feasible 候选统一交给公共 Pareto 模块。
- 空间图和 Pareto 3D HTML 统一交给 `figures/` 模块生成。
