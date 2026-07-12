# Testing Strategy

本文档记录当前新仓库的测试边界。pytest 只作为轻量、确定性、无实验输出的口径保护；真实数据、大矩阵、CUDA 显存记录和完整流程验收放在 `experiments/validate_*.py`。

## pytest 的职责

pytest 只测试小数据上容易悄悄出错的核心口径：

1. landuse 到 obstacle mask 的业务映射。
2. 1 m 连续 pose、safe margin 和 footprint 掩膜。
3. PyTorch soft objective 的 CUDA forward/backward。
4. hard 后验指标的手算一致性。
5. 非法输入明确报错。

pytest 不读取真实 DEM tif，不生成真实 road Voronoi，不写 `outputs/`，不记录显存，也不跑完整实验流程。

## 具体测试项

### 1. Landuse 映射

使用小型 fixture：

```text
0,1,2
3,4,5
```

期望 obstacle mask：

```text
0,1,1
1,0,1
```

固定语义：

- `0 other / 其他区域 -> 可建设 -> obstacle_mask 0`
- `4 mountain_natural / 山体/自然区域 -> 可建设 -> obstacle_mask 0`
- `1 field / 农田区域 -> 不可建设 -> obstacle_mask 1`
- `2 building / 建筑区域 -> 不可建设 -> obstacle_mask 1`
- `3 road / 道路区域 -> 不可建设 -> obstacle_mask 1`
- `5 water / 水体区域 -> 不可建设 -> obstacle_mask 1`

同时检查 metadata 中写入真实类别含义、可建设类别、不可建设类别和 mask 映射。出现未定义类别编号时必须 `ValueError`。

### 2. Pose 与 Footprint

使用小型矩阵 shape，例如 `64 x 80`：

- `decode_raw_pose(raw_pose)` 返回 shape `[B, 3]`。
- `x/y` 位于 safe margin 约束后的合法范围。
- `theta` 位于 `[-pi, pi]`。
- `compute_soft_footprint` 返回 CUDA 上的 `grid` 和 `weights`。
- `compute_hard_footprint_indices` 返回非空整数 `[row, col]`，且不越界。

### 3. CUDA Soft Objectives

使用合成 DEM、obstacle、road、demand：

- DEM soft variance 输出 shape `[B]`。
- obstacle soft overlap 输出 shape `[B]`。
- road distance 输出 shape `[B]`。
- demand distance 输出 shape `[B]`。
- 所有 PyTorch 输出必须在 CUDA 上，且数值有限。
- `sum(loss).backward()` 后，`raw_pose.grad` 必须存在、位于 CUDA、且数值有限。

### 4. Hard Metrics

直接用小型 NumPy 矩阵和显式 hard indices 做手算校验：

- DEM hard variance。
- DEM hard range。
- obstacle hard count。
- obstacle hard ratio。

这类指标只用于后验评价，不参与反向传播。

### 5. 非法输入

必须明确报错，不做静默兜底：

- 非 CUDA tensor 传入 CUDA 建模函数。
- shape 错误。
- NaN / Inf。
- landuse 出现未知类别，例如 `6`。
- demand weights 为负数或总和为 0。
- road Voronoi 中 seg_id 越界。

## 真实数据验证

真实数据验收使用实验脚本，而不是 pytest：

```bash
conda run -n torch311 python experiments/validate_modeling.py
```

该脚本可以写入 `outputs/validate_modeling/`，并记录配置、shape、CUDA 设备、显存、soft backward 和 hard 指标。

