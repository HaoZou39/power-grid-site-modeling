# Modeling Module Summary

这个文档保存新仓库建模模块所需的全部信息。新仓库实现 `modeling/` 层时只服从本文档，不直接参考旧代码。

如果本文档信息不足，先补充本文档，再继续实现。

## 建模模块定位

数据层已经输出统一的 1 m 对齐矩阵。建模模块负责把这些数据转成 PyTorch 可微计算所需的张量和 evaluator。

目标公式和硬约束分别是 `modeling/site_model.py` 里的 `SiteObjective`、`SiteConstraint` 子类。`SiteModel` 把它们装在一起。`evaluate_site_objectives` 和 `compute_hard_constraints` 调用默认的 `SiteModel`，调用方不用改。`SiteProblemContext` 仍然只装数据，不是这些类的父类。

人工改建模时，类负责选择，公式文件负责计算：

- `SiteObjective`：一个目标的父类。`DemSoft`、`RoadDistance`、`DemandDistance` 是三个帕累托目标。`ObstacleSoft` 是软重叠惩罚，不参与帕累托比较。
- `SiteConstraint`：一条硬约束的父类。`ObstacleCountConstraint` 用足迹压到的禁止格数量作为 `constraint_violation`。
- `SiteModel`：把一组目标和一条硬约束装在一起。`default_site_model` 是当前搜索使用的那一组。
- `ObjectiveBatch`：一批站址和允许读取的张量。目标子类只从这里取输入。
- `dem_model.py`、`road_model.py`、`demand_model.py`、`obstacle_model.py`：对应公式。改数值定义时改这些文件，类只负责调用。
- `pose.py`：无界 raw pose 到场地内坐标的转换。
- `masks.py`：建筑矩形的软足迹和硬足迹。
- `context.py`：场景数据包，不含计算公式。
- `evaluator.py`：原来的两个函数入口，内部转发给 `SiteModel`。
- `construction_cost.py`：运输量接口。只返回沿路长度、进站长度和进站累计高差，不乘单价，也不把路径选择惩罚合并进指标。它不在 `OBJECTIVE_NAMES` 里。

建模模块不负责读取原始数据，不负责训练 Pareto Set Learning，也不负责实验脚本编排。

## 计算设备

pose 解码、软足迹和四个 soft 目标支持 CPU 与 CUDA，公式、目标顺序、dtype 和梯度含义保持一致；同一次评价的输入必须在同一设备上。设备不一致、NaN/Inf、shape 错误仍明确报错。CPU 上继续用 PyTorch 执行 soft forward/backward 和前期 Adam；“NumPy 后端”指演化算子，不代表把模型改写成 NumPy 或取消梯度引导。

设备解析在实验组装层创建场景张量之前完成。引导搜索默认有 CUDA 时使用张量演化，无 CUDA 时使用 NumPy 演化和 CPU 模型；具体配置以 `markdown/GUIDED_SEARCH.md` 为准。完整报告、精确进站路径与硬指标继续共用当前入口。`modeling/numpy_evaluator.py` 仅组装旧评价流程，不重复实现目标公式。

## 变量设置

数据层输入已经是 1 m 对齐矩阵。建模层不再使用 10 m 坐标，也不负责 10 m 到 1 m 的映射。

建模层的站址 pose 使用连续 1 m 坐标：

```python
pose = [x, y, theta]
```

其中：

- `x` 和 `y` 是连续坐标，不要求是整数像素。
- `x` 和 `y` 的空间范围由数据层输出矩阵的 shape 决定。
- `theta` 是矩形站址的朝向角。
- `theta` 的默认范围是 `[-pi, pi]`。

优化变量本身是无界变量：

```python
raw_pose = [raw_x, raw_y, raw_theta]
```

建模层使用 sigmoid reparameterization 将无界变量压到合法范围：

```python
u = sigmoid(raw_pose)
x = xmin + (xmax - xmin) * u_x
y = ymin + (ymax - ymin) * u_y
theta = -pi + 2 * pi * u_theta
```

`x/y` 的合法范围由矩阵大小和矩形安全边距决定：

```python
xmin = safe_margin
xmax = W - 1 - safe_margin
ymin = safe_margin
ymax = H - 1 - safe_margin
```

矩形安全边距用于保证站址矩形旋转后仍在区域内，默认按矩形对角线半长计算：

```python
safe_margin = 0.5 * sqrt(rect_w_m**2 + rect_h_m**2)
```

后续所有可微采样、约束计算和目标函数计算都基于解码后的有界 pose。

## 掩膜函数

建模模块需要单独设置一个掩膜函数文件，用来计算站址矩形 footprint 的 mask。这个文件只负责根据 pose 和矩形尺寸生成掩膜，不负责具体 DEM loss、道路 loss 或需求点 loss。

建议文件：

```text
modeling/
  masks.py
```

掩膜函数输入：

```python
pose = [x, y, theta]
rect_w_m: float
rect_h_m: float
matrix_shape: tuple[int, int]
```

其中 `x` 和 `y` 是连续 1 m 坐标，`theta` 是矩形朝向角。

掩膜函数需要支持两种输出：

1. soft mask
2. hard mask

soft 和 hard 必须是两个独立函数，只是放在同一个 `masks.py` 文件中。不要写成一个函数靠参数切换模式。

建议函数：

```python
compute_soft_footprint(...)
compute_hard_footprint_indices(...)
```

二者职责不同：

- `compute_soft_footprint` 服务 PyTorch 可微训练，返回采样 grid 和 soft weights。
- `compute_hard_footprint_indices` 服务最终评估，返回原始矩阵中的整数像素坐标列表。

### soft mask

soft mask 使用 PyTorch 计算，可微，用于训练 loss。

soft footprint 函数按批量并行设计。输入：

```python
pose_batch.shape == [B, 3]
```

其中 `B` 是候选站址数量。

soft footprint 函数返回：

```python
{
    "grid": torch.Tensor,       # shape: [B, Hwin, Wwin, 2]
    "weights": torch.Tensor,    # shape: [B, Hwin, Wwin]
}
```

各维度含义：

- `B`：候选站址数量。
- `Hwin`：每个候选站址局部采样窗口的高度。
- `Wwin`：每个候选站址局部采样窗口的宽度。
- `grid[..., 2]` 的最后一维表示采样坐标 `(x, y)`。

`grid` 用于 `torch.nn.functional.grid_sample`，坐标应归一化到 `[-1, 1]`。例如：

```python
patch = grid_sample(matrix.expand(B, -1, -1, -1), grid)
```

其中：

```python
matrix.shape == [1, 1, H, W]
patch.shape == [B, 1, Hwin, Wwin]
```

`weights` 是 soft rectangle 权重：

- `weights[b, i, j]` 表示第 `b` 个候选站址的局部窗口中，第 `(i, j)` 个采样点属于矩形 footprint 的程度。
- 矩形内部权重接近 `1`。
- 矩形外部权重接近 `0`。
- 边界附近连续过渡。

计算方式：

1. 以 `(x, y)` 为中心建立局部窗口。
2. 对窗口内坐标计算相对偏移 `dx, dy`。
3. 根据 `theta` 将坐标旋转到矩形局部坐标：

```python
x_rot = cos(theta) * dx + sin(theta) * dy
y_rot = -sin(theta) * dx + cos(theta) * dy
```

4. 用 sigmoid 生成软矩形权重：

```python
weight_x = sigmoid(sharpness * (rect_w_m / 2 - abs(x_rot)))
weight_y = sigmoid(sharpness * (rect_h_m / 2 - abs(y_rot)))
soft_mask = weight_x * weight_y
```

soft mask 的特点：

- 矩形内部权重接近 1。
- 矩形外部权重接近 0。
- 边界附近连续过渡，因此对 `x, y, theta` 可微。
- DEM loss 和 soft obstacle loss 都使用这个 mask。

### hard mask

hard mask 使用 NumPy 计算，不用于反向传播，只用于最终评估。

计算方式：

```python
hard_mask = (abs(x_rot) <= rect_w_m / 2) & (abs(y_rot) <= rect_h_m / 2)
```

hard mask 的用途：

- 计算 hard obstacle count。
- 计算 DEM hard range。
- 生成最终报告和可行性判断。

## DEM loss

DEM loss 用来衡量站址矩形区域内的地形平整程度。足迹内相邻 1 m 格子的最大坡度由 `modeling/slope.py` 单独报告，单位为度，不进入三个目标，也不改变可行性。

`modeling/footprint_terrain.py` 的 `footprint_terrain(dem, landuse, pose, rect_w_m, rect_h_m)` 也是报告：用 hard mask 取出足迹格子，返回格子数、各 landuse 类别占比（键为 `other`、`field`、`building`、`road`、`mountain`、`water`，对应类别 0 到 5，和为 1）、高程最小值、最大值和落差（米），以及同上口径的最大坡度。它只给助手的方案分析用，不进入目标，也不改变可行性。

数据层已经输出 1 m 对齐的 DEM 矩阵，因此 DEM loss 直接在 1 m DEM 矩阵上计算，不再做 10 m 到 1 m 的坐标转换。

DEM loss 分为训练用 soft loss 和评估用 hard loss。DEM loss 函数必须按批量并行设计，而不是只处理单个站址。

DEM soft loss 和 DEM hard loss 必须是两个独立函数，不要写成一个函数靠参数切换模式。

建议函数：

```python
compute_dem_soft_loss(...)
compute_dem_hard_loss(...)
```

二者职责不同：

- `compute_dem_soft_loss` 使用 PyTorch，根据 soft footprint 的 `grid` 和 `weights` 计算可微的 soft 方差。
- `compute_dem_hard_loss` 使用 hard footprint 的整数像素坐标列表，从原始 DEM 矩阵中取值，计算 hard 方差和 hard 极差。

输入 pose 是一批候选站址：

```python
pose_batch.shape == [B, 3]
```

DEM soft loss 和 DEM hard loss 分别返回自己的结果，不合并到同一个返回字典里。

`compute_dem_soft_loss(...)` 返回：

```python
dem_soft_loss: torch.Tensor  # shape: [B]
```

`compute_dem_hard_loss(...)` 返回：

```python
{
    "dem_hard_var": torch.Tensor,    # shape: [B]
    "dem_hard_range": torch.Tensor,  # shape: [B]
}
```

hard loss 返回字典，是因为 `dem_hard_var` 和 `dem_hard_range` 都属于同一个 hard 评估函数的输出，但语义不同。soft loss 是训练项，单独返回一个 `[B]` 张量。

### DEM soft loss

DEM soft loss 使用 PyTorch 计算，可微，用于训练。

输入：

```python
dem: torch.Tensor          # shape: [1, 1, H, W]
pose_batch: torch.Tensor   # shape: [B, 3], [x, y, theta]
rect_w_m: float
rect_h_m: float
soft_mask: torch.Tensor
```

计算方式：

1. 根据 pose 和局部窗口，从 DEM 矩阵中用双线性采样得到站址附近的 DEM patch。
2. 使用 `masks.py` 生成的 soft rectangle mask 作为权重。
3. 计算 soft mask 内 DEM 值的加权平均。
4. 计算 soft mask 内 DEM 值的加权方差。

公式：

```python
z_mean = sum(soft_mask * z) / sum(soft_mask)
dem_soft_loss = sum(soft_mask * (z - z_mean) ** 2) / sum(soft_mask)
```

其中：

- `z` 是 DEM patch 中采样得到的高程值。
- `soft_mask` 是矩形 footprint 的可微软掩膜。
- `dem_soft_loss` 越小，说明矩形区域内地形越平整。

这个 loss 对 `x, y, theta` 可微，因为：

- DEM patch 通过 PyTorch 双线性采样得到。
- soft mask 对 `x, y, theta` 连续可微。
- 加权方差本身可微。

### DEM hard loss

DEM hard loss 不参与反向传播，只用于最终评估和报告。实现上可以用 hard mask 取出矩形内 DEM 值，再计算 hard 方差和 hard 极差。

输入：

```python
dem: np.ndarray
pose_batch: torch.Tensor | np.ndarray
hard_mask: np.ndarray
```

必须计算两个 hard 指标：

```python
dem_hard_range = max(z_inside_hard_mask) - min(z_inside_hard_mask)
dem_hard_var = var(z_inside_hard_mask)
```

其中 `z_inside_hard_mask` 是 hard rectangle 内的 DEM 值。

用途：

- `dem_hard_range` 用来报告真实高差。
- `dem_hard_var` 用来和训练时的 soft variance 对照。
- hard loss 不用于训练，只用于后验评价。

批量情况下：

```python
dem_hard_var.shape == [B]
dem_hard_range.shape == [B]
```

## 不可建设区域 loss

不可建设区域 loss 用来衡量站址矩形是否覆盖不可建设区域。

不可建设区域来自数据层输出的 `landuse` 和默认 `obstacle_mask`。优化开始前合成两张与 DEM、道路 Voronoi 对齐的 1 m 掩膜，不新增第四个帕累托目标。地形平整度、道路距离、需求点距离的顺序不变。

土地约束硬掩膜只包含本次按土地类别、手绘禁区和可行域禁止建设的格子，取值为 `0` 或 `1`。建筑足迹硬评价在此之上再并入道路退距：遥感土地利用类别 `3` 与 OSM 道路中心线栅格取并集，用 1 m 栅格距离变换向外扩展 `road_setback_m`（默认 5 m，可配置，必须是有限非负数）。距离小于等于该值的格子禁止建筑 footprint 覆盖。`road_setback_m` 为 0 时没有额外缓冲，道路格子本身仍然禁止建设。这是格子中心距离变换的近似退距，不是连续几何净距，也不估计道路宽度。缓冲在准备一次优化或评价时计算一次，不在每个个体或每次 hard 计数时重算。足迹碰到合并后硬格子或越出图幅则不可行，图内禁止格数仍是 `obstacle_hard_count`，图外违例另计入 `outside_count`。道路退距只进入这份建筑专用硬掩膜，不写回 `problem.obstacle_mask`，因此不改变 Gate、进站可通行格、运输距离场或软目标。车辆仍可按原有规则经过退距格。软代价掩膜的格子取值在 `0` 到 `1`：禁止类、手绘禁区和可行域以外的格子为 `1`，可建设为 `0`，允许建设但计成本的类别取配置里的代价系数。`obstacle_soft` 仍用下面的重叠公式，采样的是软代价掩膜，不是建筑专用硬掩膜。

默认策略下，农田、建筑、遥感道路、水体都是硬禁止。决策界面默认不按类别禁止山体和农田，能不能建设看坡度和进站条件。侧栏可以把它们改成一律不可建设。建筑、遥感道路、水体保持硬禁止。农田也可以改成允许建设并计入成本，默认代价系数是 `0.5`。手绘禁区始终并入土地约束硬掩膜，并把软代价掩膜的对应格子设为 `1`。可行域是另一组局部米坐标多边形：没有可行域时，整个选址范围都可搜索；有一个或多个时，这些圈取并集，圈外格子并入土地约束硬掩膜和软代价 `1`，站址落在任一圈内即可。禁区仍然盖住圈内。道路退距始终追加到建筑专用硬掩膜，不受山体或农田策略关闭。一次优化不改写场景里的 `landuse`、原始 `obstacle_mask` 或道路产物。

不可建设区域 loss 分为训练用 soft loss 和评估用 hard loss。两个 loss 必须是两个独立函数，不要写成一个函数靠参数切换模式。

`SiteProblemContext.initialization_feasible_zones` 和 `initialization_exclusion_zones` 保存任务装配传入的原始局部米坐标多边形，仅用于初始化及前期引导的中心点边界检查，补充栅格 `all_touched` 的边缘口径；不改变本节已有硬掩膜、足迹和路径评价。采样流程见 `markdown/GUIDED_SEARCH.md`。

建议函数：

```python
compute_obstacle_soft_loss(...)
compute_obstacle_hard_loss(...)
```

二者职责不同：

- `compute_obstacle_soft_loss` 使用 PyTorch，根据 soft footprint 的 `grid` 和 `weights` 计算可微的 soft overlap。
- `compute_obstacle_hard_loss` 使用 hard footprint 的整数像素坐标列表，从原始 obstacle mask 中取值，统计 hard obstacle count 和 hard obstacle ratio。

不可建设区域 loss 函数必须按批量并行设计。输入 pose 是一批候选站址：

```python
pose_batch.shape == [B, 3]
```

不可建设区域 soft loss 和 hard loss 分别返回自己的结果，不合并到同一个返回字典里。

`compute_obstacle_soft_loss(...)` 返回：

```python
obstacle_soft_loss: torch.Tensor  # shape: [B]
```

`compute_obstacle_hard_loss(...)` 返回：

```python
{
    "obstacle_hard_count": torch.Tensor,   # shape: [B]
    "obstacle_hard_ratio": torch.Tensor,   # shape: [B]
}
```

hard loss 返回字典，是因为 `obstacle_hard_count` 和 `obstacle_hard_ratio` 都属于同一个 hard 评估函数的输出，但语义不同。soft loss 是训练项，单独返回一个 `[B]` 张量。

### obstacle soft loss

obstacle soft loss 使用 PyTorch 计算，可微，用于训练。

输入：

```python
obstacle_mask: torch.Tensor   # shape: [1, 1, H, W]
pose_batch: torch.Tensor      # shape: [B, 3], [x, y, theta]
rect_w_m: float
rect_h_m: float
soft_mask: torch.Tensor       # shape: [B, Hwin, Wwin]
grid: torch.Tensor            # shape: [B, Hwin, Wwin, 2]
```

计算方式：

1. 根据 soft footprint 的 `grid`，从软代价掩膜中用双线性采样得到站址附近的 obstacle patch。
2. 使用 `masks.py` 生成的 soft rectangle mask 作为权重。
3. 计算 soft mask 内不可建设区域的加权覆盖量。

公式：

```python
obstacle_soft_loss = sum(soft_mask * obstacle_values) / sum(soft_mask)
```

其中：

- `obstacle_values` 是 obstacle patch 中采样得到的不可建设区域值。
- `soft_mask` 是矩形 footprint 的可微软掩膜。
- `obstacle_soft_loss` 越小，说明矩形区域覆盖不可建设区域越少。

这个 loss 对 `x, y, theta` 可微，因为：

- obstacle patch 通过 PyTorch 双线性采样得到。
- soft mask 对 `x, y, theta` 连续可微。
- 加权覆盖量本身可微。

### obstacle hard loss

obstacle hard loss 不参与反向传播，只用于最终评估、报告和可行性判断。

输入：

```python
obstacle_mask: np.ndarray
pose_batch: torch.Tensor | np.ndarray
hard_indices: list[np.ndarray]
```

其中 `hard_indices` 来自：

```python
compute_hard_footprint_indices(...)
```

`hard_indices[b]` 是第 `b` 个候选站址矩形覆盖到的整数像素坐标列表：

```python
hard_indices[b].shape == [N_b, 2]  # each row: [row, col]
```

必须计算两个 hard 指标：

```python
obstacle_hard_count = count(obstacle_values_inside_hard_indices > 0)
obstacle_hard_ratio = mean(obstacle_values_inside_hard_indices > 0)
```

其中 `obstacle_values_inside_hard_indices` 是 hard rectangle 覆盖到的硬掩膜值。软代价掩膜不参与可行性判断。

用途：

- `obstacle_hard_count` 用来判断候选站址是否碰到不可建设区域。
- `obstacle_hard_ratio` 用来报告不可建设区域覆盖比例。
- hard loss 不用于训练，只用于后验评价。

批量情况下：

```python
obstacle_hard_count.shape == [B]
obstacle_hard_ratio.shape == [B]
```

可行性判断：

```python
is_feasible = obstacle_hard_count + outside_count == 0
```

`outside_count` 是旋转矩形盖到、但行列超出栅格的 1 m 格子数。四个角点只要有一个越出图幅 `[0, width] × [0, height]`，即使没有格子中心落在图外，也至少计 1。角点比较使用 `2 × float32 epsilon × max(width, height, rect_w_m, rect_h_m)` 米的数值容差，兼容前端贴边坐标转成 float32 后的位置和角度舍入，不把这项容差当成建设退距。`obstacle_hard_count` 仍只数图内禁止格。整栋建筑都落在图外时，足迹函数直接报错，不把它当成零违例。搜索解码会把矩形中心留在安全边距内，所以搜索过程中这项通常是 0；拖动或单点重算的已解码坐标仍走同一条硬约束。

`masks.compute_tensor_hard_footprint` 返回 `TensorHardFootprint`（批量行列、图内覆盖布尔掩膜、图外格数），只计算几何；`obstacle_model.compute_obstacle_tensor_violation` 负责禁止格计数。

`ObstacleCountConstraint.violation` 为演化阶段提供张量化的违例计数，使用 `modeling/masks.py` 的批量硬足迹几何，采用 float64 判断格子中心与角点，计数结果与下述完整硬报告相同，不额外计算 DEM hard 指标。

`ObstacleCountConstraint.metrics` 同时返回 `constraint_violation`，它等于上面的和。算法只读取这个违例。以后增加坡度等硬约束时，继承 `SiteConstraint`，不改搜索父类。演化用的 `violation` 与完整报告的 `metrics` 必须同步维护并验证数值一致。

## 道路 Voronoi 距离 loss

进站路径只走硬掩膜上可建设的格子，默认四连通，`diagonal_access` 打开时为八连通且斜步不能穿过障碍角。路径选择使用多源 Dijkstra；每一步的代价为 `水平距离 + access_elevation_weight × 相邻格高程差绝对值`。`access_elevation_weight` 在 `config/default_config.json` 的 `guided_search` 配置中显式设置，只影响选路。选中路径后的 `offroad_haul_m`（水平长度）、`haul_rise_m`（沿途高程变化绝对值之和）和最大局部坡度分别计算、分别报告，不合并为单一目标。权重为 `0` 时只按水平长度选路；提高权重会让搜索更偏好累计高差较小的路线。道路接入点通过投影到实际道路折线段获得连续坐标，不依赖固定间隔插入的道路节点。DEM 按格子高程取值，报告的最大坡度是路径相邻采样点间的局部坡度。

道路 Voronoi 距离 loss 用来衡量候选站址中心点到最近道路的距离。它不使用站址矩形 footprint，而是只基于 pose 的中心坐标 `[x, y]` 计算。`modeling/logistics_cost.py` 计算从指定原点沿道路到站址的路径。`RoadHaulCost` 用直线计算离开道路的长度。`TerrainHaulCost` 保留为单点对照和兼容入口；优化结果、方案报告和地图黄线的权威来源统一为 `HaulField`。这些量分开返回进站长度和进站累计高差，不把高差乘进长度，也不使用单价。没有通路时直接报错。道路线段没有路宽，不读路宽或遥感。方案报告的进站坡度沿 `HaulField` 记录的同一条格子路径计算，不再独立寻路。当前界面和助手的单方案报告把完整山体/农田策略、农田代价、禁区与可行域交给 `experiments/constraint_mask.py`，所得 hard mask 必须与同表单搜索时逐格相同。完全不带这些约束字段的旧 `site-report` 客户端继续读取场景静态 `obstacle_mask_1m.npy`；只传一部分字段直接返回 422；内部显式 `obstacle_mask` 调用保持可用，且不得与动态约束同时传入。`modeling/access_path.py` 只留作直线对照测试。坡度警告不改变可行性。决策界面的引导式多目标搜索默认比较脚印平整度、进站长度和进站累计高差，有进货原点时加上沿路长度。需求点距离仍由 `DemandDistance` 计算并写入方案表，默认不参加比较。到道路的直线距离 `road_distance` 仍由 `RoadDistance` 计算并写入方案表，不参加这次支配比较。CMA-ES 仍使用 `dem_soft`、`road_distance`、`demand_distance`。

`modeling/haul_field.py` 在一次优化开始时扩展当前硬掩膜，得到每个格子中心对应的加权最优路径及其长度、高差。默认四连通，`diagonal_access` 打开时为八连通；正交一步是两格中心距离 1 m，斜向一步是 √2 m，斜步要求两个侧邻都可走且目标格不在道路上，避免从障碍角切过。指定进货原点时同时记录沿路长度。道路网络在建场时只构图一次，并从进货原点只做一次单源最短路预计算；每个 Gate 从这份结果查询沿路长度。只有与原点道路分量连通的 Gate 才能作为多源扩展的种子，不连通的 Gate 不写入零距离，也不标记为 reachable。若所有 Gate 都不可达，直接报告 Gate 总数、可达数和不可达数；若只有部分不可达，则继续建场，无法从可达 Gate 走到的候选由既有 blocked/infeasible 机制处理。道路接触点投影到其连续道路段上。`modeling/construction_cost.py` 的单点对照仍只走四连通，不随这个开关变成八连通。

距离场同时保存每格 `int8` 前驱方向、`int32` Gate 归属、Gate 格子、道路接触点、接触路段和 Gate 初始化指标。`query_route()` 按 `query_exact()` 的同一 `floor(x/y)` 映射回溯这些数据；站址离格子中心不超过 `0.05 m` 时沿用现有规则，不增加最后一小段，超过时同时把该段计入长度、高差和折线。走不通的格子只标记为不可行，不把哨兵距离写成可行目标。`modeling/haul_model.py` 把格子中心值做双线性插值供前期梯度引导；细粒度比较、方案表、单方案报告和地图黄色折线都以精确查表及其前驱链为准。Voronoi 直线距离不拿来代替进站长度或进站累计高差。

多源 Dijkstra 按 Gate 到道路接触点的初始长度和加权高差，以及后续栅格边的长度和加权高差选路；原点到道路的公共离路间隙只计入报告长度，不参与优先队列排序。累计高差仍按所选路径逐段记录，不是独立最小爬升目标。改变 `access_elevation_weight` 会改变所选路径，必须与距离场缓存键一同变化。

`modeling/tensor_evaluator.py` 为演化阶段准备设备常驻的建筑掩膜与 HaulField 数组，并按显式 `evaluation_batch_size` 分批计算。soft 目标复用 `SiteModel` 的目标对象，只评价当前参与 Pareto 比较的目标；约束调用 `ObstacleCountConstraint.violation`。非道路格的进站目标按 floor 索引、可达标记和 5 cm 末段规则批量查表；同格站址与格子中心的高程都按现有格子 DEM 取值，因此末段高差为零。道路格候选仍调用原 `query_exact` 计算连续接触点与道路最短路，保留精确口径。最终完整方案报告仍经 `pose_records`，不会把插值引导值或不可达哨兵值当作精确目标。

`experiments/haul_field_cache.py` 把优化阶段生成的 `HaulField` 数值数组以 `.npy` 和 JSON 清单写入场景目录下的共享缓存，使 Worker 与 API 可以跨进程复用；不使用 pickle。缓存键包含场景绝对路径、DEM/道路/掩膜源文件的 `mtime_ns` 与大小、三个实际输入数组的内容摘要、完整硬约束相关字段、可达道路分量、连通方式、高程惩罚系数和缓存格式版本。同一可达 Gate 集复用前驱、Gate 归属和累计高差；距离场另存 `int32` 的 Dijkstra 出堆顺序，换原点时更新道路最短路和 Gate 指标，再按该顺序逐边重放长度加法，保持四连通及八连通的浮点运算次序。原点离路间隙计入 `offroad_haul_m`，不参与 Gate 之间的选路比较；所有 Gate 的这段间隙相同，因此改变间隙不改变所选路径。道路只有一个分量时，无原点与有原点可复用；多个分量时，无原点和各个分量分别缓存。不能用旧 FIFO 层次重放替代当前 Dijkstra，也不能恢复旧选路规则。

缓存清单记录参考原点和连通方式。加载时验证出堆顺序覆盖全部可达格且没有重复、每个非根格的前驱位于它之前并属于同一 Gate，再绑定当前原点。约束、人工土地修正、道路分量、路径配置、源数组或场景重建变化都会产生新键；损坏或不兼容的条目回退到正常构建。缓存按最近使用保留至多 4 份，通常总量控制在 1 GiB；当前正在使用的条目受保护，单条超过 1 GiB 时仍保留，因此该值不是硬磁盘配额。写入采用同目录临时目录后原子发布，不写实验目录，也不改历史 CSV。

`experiments/site_report.py` 仍在 API 进程内保留容量为 1 的 `HaulField` LRU；内存未命中时先读取上述共享缓存，只有共享缓存也未命中才调用 `build_haul_field()`。显式传入内存掩膜的内部调用继续绕过持久缓存。报告日志分别记录总耗时、内存/磁盘/构建状态、距离场阶段、足迹坡度和 `query_route()` 耗时。

### 大场景的后续瓶颈

道路 Voronoi 的分块 GPU 构建见 `markdown/DATA_MODULE_SUMMARY.md`。它的 9000×9000 验收只代表最近线段标签构建，不代表以下整个选址链路已在该尺寸验收。以下容量按现有数组 dtype 静态计算，未测量 9 km 全流程耗时。

1. **优先处理 Gate 到线段的全量广播。** `haul_field._nearest_on_segments` 目前对全部 Gate 和全部道路生成 `[G,S,2]` float64 中间量。仅一个这样的数组就是 `16*G*S` 字节，且函数会同时保留多个中间量。G=300000、S=21475 时单数组约 103 GB，早于 Dijkstra 就可能耗尽主机内存。应先对两个轴分块，保留原 float64 距离、sqrt 舍入及等距最小编号；再评估 GPU 或有精确下界的空间索引，不能直接用 float32 Voronoi 标签替代连续 Gate 的 float64 最近接触点。
2. **Dijkstra 的 CPU 时间和完整图幅数组。** `build_haul_field` 的三张 float64 代价/指标图、道路/可达/前驱、Gate 归属，以及内核中的 int64 heap/heap_position、int32 出堆顺序，合计约 51 字节/格；有原点时约 59 字节/格。8100 万格约 4.13/4.78 GB，尚未加 DEM、buildable、几何对象、输入数组和加载/校验临时量。带高程权重的最短路不是普通距离变换，后续加速须保留选路、平局和前驱次序；不能直接换成并行 BFS 或近似传播。
3. **设备距离场重复与峰值。** `TensorHaulLookup` 的两个/三个 float64 指标约 1.30/1.94 GB，构造时各输入张量与 `torch.stack` 输出会短暂共存；梯度引导另存对应 float32 场，约 0.65/0.97 GB。DEM/硬软掩膜每个 float32 全图约 324 MB，int64 Voronoi 另约 648 MB。优先复用设备数据、避免 stack 临时副本和重复掩膜，再考虑按需瓦片；只降低 `evaluation_batch_size` 不能减少这些常驻场。
4. **缓存、加载和校验。** 不含 DEM/可建设图的距离场全图输出约 27 字节/格（有原点再加 8），9000×9000 约 2.19/2.84 GB，且 Gate 数组另计。共享缓存目前全量 `np.load`，出堆次序验证也产生完整 rank 和高级索引临时数组。单个大场景会超过通常的 1 GiB 缓存预算；应明确可配置容量，并评估 mmap、分块哈希/校验和多进程共享，仍须保留损坏检测与输入寻址。
5. **种群与场景是两种规模。** NSGA-II 的支配矩阵仍为 `O(popsize²)`，与场景像素数无关；足迹评价已经分批。扩大种群时继续关注这两项，不应通过降低场景分辨率、截断道路或减少代数来冒充等价加速。
6. **道路退距的距离变换。** `context.road_building_buffer` 使用 CPU SciPy 欧氏距离变换，9000×9000 的 float64 距离输出本身约 648 MB，另有特征索引和内部临时量；只在场景装配或退距变化时构建，当前相同 context/退距会复用布尔 buffer。后续评估 GPU 精确距离变换或更充分的跨请求缓存时，须保留欧氏距离与 `distance <= road_setback_m` 的判定口径，并测量构建时的主机峰值。

数据层已经输出道路 tool 的标准产物：

```python
road_segments_local: np.ndarray    # shape: [N_seg, 4], each row = [x1, y1, x2, y2]
road_voronoi: np.ndarray           # shape: [H, W], value = nearest seg_id
```

这些输出都已经是左上角原点、x 向右、y 向下、单位为米的局部坐标。建模模块不再做道路经纬度转换，也不再做 EPSG/bbox 坐标变换。

道路距离 loss 按批量并行设计。输入 pose 是一批候选站址：

```python
pose_batch.shape == [B, 3]
```

道路距离只使用：

```python
xy_batch = pose_batch[:, :2]  # shape: [B, 2]
```

`theta` 不参与道路距离计算。

建议函数：

```python
compute_road_distance_loss(...)
```

返回：

```python
road_distance_loss: torch.Tensor  # shape: [B]
```

### 输入

```python
road_segments_local: torch.Tensor   # shape: [N_seg, 4], [x1, y1, x2, y2]
road_voronoi: torch.Tensor          # shape: [H, W], dtype long, nearest seg_id
pose_batch: torch.Tensor            # shape: [B, 3], [x, y, theta]
```

其中：

- `road_voronoi[row, col]` 存该 1 m 像素最近道路线段的 `seg_id`。
- `seg_id in [0, N_seg)`。
- 真实线段几何为 `road_segments_local[seg_id]`。

### 计算方式

对每个候选点 `(x, y)`：

1. 找到它所在的栅格单元：

```python
col = floor(x)
row = floor(y)
```

2. 取这个单元四个角对应的最近道路线段：

```python
seg00 = road_voronoi[row,     col    ]
seg10 = road_voronoi[row,     col + 1]
seg01 = road_voronoi[row + 1, col    ]
seg11 = road_voronoi[row + 1, col + 1]
```

3. 对四个 `seg_id` 分别计算候选点到对应道路线段的真实几何距离。

```python
A = [x1, y1]
B = [x2, y2]
AB = B - A
t = dot(P - A, AB) / dot(AB, AB)
t = clamp(t, 0, 1)
proj = A + t * AB
d = ||P - proj||
```

当最近位置落在线段端点时，点到线段距离会自然退化为点到端点距离，因此道路距离建模不单独维护 endpoint 分支。

4. 根据候选点在当前 1 m 栅格单元内的小数位置做双线性加权：

```python
a = x - floor(x)
b = y - floor(y)

w00 = (1 - a) * (1 - b)
w10 = a * (1 - b)
w01 = (1 - a) * b
w11 = a * b

road_distance_loss = w00 * d00 + w10 * d10 + w01 * d01 + w11 * d11
```

批量情况下：

```python
road_distance_loss.shape == [B]
```

### 可微性说明

道路 Voronoi 距离 loss 是分段可微的：

- `floor(x) / floor(y)` 和 `road_voronoi` 查表本身不可微。
- 在同一个 1 m 栅格单元内部，四个 `seg_id` 固定。
- 点到线段投影距离和双线性权重都对 `(x, y)` 可微。

因此这个 loss 可以用于训练，但它在跨越 Voronoi label 或栅格边界时会出现分段变化。这一点是道路 Voronoi 方法本身的建模口径，不需要在数据层额外保存距离矩阵。

### hard 评估

道路距离目标本身不设置 hard mask，也不区分 soft/hard 两个函数，因为它是候选中心点到道路几何的距离评价。道路退距只作为建筑足迹硬约束，不改变 `road_distance` 的公式、进站通行规则或目标顺序。

最终报告中可以直接使用：

```python
road_distance_loss: torch.Tensor  # shape: [B]
```

作为道路距离指标。若后续需要完全 NumPy 的后验版本，可以另设 `compute_road_distance_numpy(...)`，但不要和训练用 PyTorch 函数混在一个函数里用参数切换。

## 需求点距离 loss

需求点距离 loss 用来衡量候选站址中心点到需求点集合的加权距离。它不使用站址矩形 footprint，而是只基于 pose 的中心坐标 `[x, y]` 计算。当前需求点由数据模块按数量和 seed 随机生成。以后要换成新能源负荷预测时，只替换这组点和权重，目标名 `demand_distance` 不变。

数据层已经输出需求点 tool 的标准产物：

```python
demand_points: np.ndarray          # shape: [N, 2], each row = [x, y]
demand_weights: np.ndarray | None  # shape: [N] or None
```

需求点坐标已经是左上角原点、x 向右、y 向下、单位为米的局部连续坐标。建模模块不生成需求点，也不做坐标转换。

需求点距离 loss 按批量并行设计。输入 pose 是一批候选站址：

```python
pose_batch.shape == [B, 3]
```

需求点距离只使用：

```python
xy_batch = pose_batch[:, :2]  # shape: [B, 2]
```

`theta` 不参与需求点距离计算。

建议函数：

```python
compute_demand_distance_loss(...)
```

返回：

```python
demand_distance_loss: torch.Tensor  # shape: [B]
```

### 输入

```python
demand_points: torch.Tensor          # shape: [N, 2]
demand_weights: torch.Tensor | None  # shape: [N] or None
pose_batch: torch.Tensor             # shape: [B, 3], [x, y, theta]
```

其中：

- `demand_points[n]` 是第 `n` 个需求点的局部连续坐标 `[x_n, y_n]`。
- 如果 `demand_weights is None`，则默认所有需求点权重相同。
- 如果提供 `demand_weights`，则必须是一维张量，长度为需求点数量 `N`。

### 计算方式

对每个候选点 `P_b = [x_b, y_b]` 和每个需求点 `D_n = [x_n, y_n]`，计算欧氏距离：

```python
d_bn = sqrt((x_b - x_n) ** 2 + (y_b - y_n) ** 2)
```

如果没有显式权重，使用普通平均距离：

```python
demand_distance_loss[b] = mean_n(d_bn)
```

如果有显式权重，使用加权平均距离：

```python
w = demand_weights / sum(demand_weights)
demand_distance_loss[b] = sum_n(w_n * d_bn)
```

批量向量化形式：

```python
diff = xy_batch[:, None, :] - demand_points[None, :, :]  # shape: [B, N, 2]
dist = sqrt(sum(diff ** 2, dim=-1) + eps)                # shape: [B, N]

if demand_weights is None:
    demand_distance_loss = mean(dist, dim=1)              # shape: [B]
else:
    w = demand_weights / sum(demand_weights)              # shape: [N]
    demand_distance_loss = sum(dist * w[None, :], dim=1)  # shape: [B]
```

### 可微性说明

需求点距离 loss 对 `(x, y)` 可微：

- 候选点坐标来自 sigmoid reparameterization 后的连续 pose。
- 欧氏距离对 `(x, y)` 可微。
- 平均或加权平均本身可微。

实现时距离公式应加入很小的 `eps`，避免候选点和需求点完全重合时 `sqrt(0)` 的梯度问题：

```python
dist = sqrt(sum(diff ** 2, dim=-1) + eps)
```

### hard 评估

需求点距离目前不单独设置 hard mask，也不区分 soft/hard 两个函数。原因是需求点距离不是矩形区域覆盖评价，而是候选中心点到需求点集合的距离评价。

最终报告中可以直接使用：

```python
demand_distance_loss: torch.Tensor  # shape: [B]
```

作为需求点距离指标。若后续需要完全 NumPy 的后验版本，可以另设 `compute_demand_distance_numpy(...)`，但不要和训练用 PyTorch 函数混在一个函数里用参数切换。
