# Modeling Module Summary

这个文档保存新仓库建模模块所需的全部信息。新仓库实现 `modeling/` 层时只服从本文档，不直接参考旧代码。

如果本文档信息不足，先补充本文档，再继续实现。

## 建模模块定位

数据层已经输出统一的 1 m 对齐矩阵。建模模块负责把这些数据转成 PyTorch 可微计算所需的张量和 evaluator。

建模模块不负责读取原始数据，不负责训练 Pareto Set Learning，也不负责实验脚本编排。

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

DEM loss 用来衡量站址矩形区域内的地形平整程度。

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

不可建设区域来自数据层输出的 `obstacle_mask`，该矩阵已经与 DEM、道路 Voronoi 对齐到同一个 1 m 分辨率栅格。

不可建设区域 loss 分为训练用 soft loss 和评估用 hard loss。两个 loss 必须是两个独立函数，不要写成一个函数靠参数切换模式。

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

1. 根据 soft footprint 的 `grid`，从 `obstacle_mask` 中用双线性采样得到站址附近的 obstacle patch。
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

其中 `obstacle_values_inside_hard_indices` 是 hard rectangle 覆盖到的原始 obstacle mask 值。

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
is_feasible = obstacle_hard_count == 0
```

## 道路 Voronoi 距离 loss

道路 Voronoi 距离 loss 用来衡量候选站址中心点到最近道路的距离。它不使用站址矩形 footprint，而是只基于 pose 的中心坐标 `[x, y]` 计算。

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

道路距离目前不单独设置 hard mask，也不区分 soft/hard 两个函数。原因是道路距离不是矩形区域覆盖评价，而是候选中心点到道路几何的距离评价。

最终报告中可以直接使用：

```python
road_distance_loss: torch.Tensor  # shape: [B]
```

作为道路距离指标。若后续需要完全 NumPy 的后验版本，可以另设 `compute_road_distance_numpy(...)`，但不要和训练用 PyTorch 函数混在一个函数里用参数切换。

## 需求点距离 loss

需求点距离 loss 用来衡量候选站址中心点到需求点集合的加权距离。它不使用站址矩形 footprint，而是只基于 pose 的中心坐标 `[x, y]` 计算。

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
