# Figures Module Summary

本文档记录新仓库中的 figure / visualization 公共模块约定。Figure 模块独立于具体算法，用来沉淀多个算法都会复用的实验展示图逻辑。

## 1. 模块目标

`figures/` 是独立的实验展示图模块，不属于 `algorithms/`，也不属于某一个 `experiments/` 脚本。

Figure 模块只负责把已经算好的实验结果画出来：

- 接收数据模块产物，例如 DEM、obstacle mask、road segments、demand points。
- 接收算法已经生成并评价好的 candidate records 或 pareto records。
- 根据调用方给定的输出路径保存图像或 HTML。
- 多个算法共享同一套展示图逻辑。

实验输出由 `experiments/output_writer.py` 统一编排，平台通过后端的实验
catalog 将已完成输出目录转换成只读 artifact manifest。manifest 只暴露
PNG、HTML、JSON 和 CSV，不暴露原始 NPY、checkpoint 或任意路径。

Figure 模块不负责：

- 不读取原始 tif/csv/GeoJSON。
- 不调用优化器。
- 不计算 objective、normalization 或 scalar。
- 不筛选 Pareto。
- 不判断 hard feasible。
- 不改变 `solutions.csv`、`runs.csv` 或 `pareto_solutions.csv` 的字段语义。
- 不决定最终推荐解。

## 2. 建议目录

```text
figures/
  __init__.py
  candidate_maps.py   # 候选点、可行点、Pareto 点和 footprint 地图
  pareto_3d.py        # 三目标 Pareto interactive HTML
```

当前公共入口：

```python
from figures import plot_candidate_map, rectangle_corners, write_pareto_3d_html
```

如果某张图只服务一个临时实验脚本，可以先留在对应 `experiments/` 中。只要第二个算法或第二个实验也需要它，就迁入 `figures/`。

## 3. 当前必须支持的图

当前 figure 模块优先沉淀两类公共图：

```text
candidate map PNG
Pareto 3D interactive HTML
```

### 3.1 Candidate Map PNG

Candidate map 用于在同一张局部 1 m 栅格地图上叠加展示：

- DEM 背景。
- obstacle mask 半透明覆盖。
- road segments。
- demand points。
- candidate site 点位，或 candidate footprint。

`figures/` 仍能画出下面四张图。默认优化写入不再调用它们；旧实验目录里已经生成的文件保持原样：

```text
all_candidates_points_map.png
all_candidates_footprints_map.png
pareto_points_map.png
pareto_footprints_map.png
```

语义：

- `all_candidates_points_map.png`：展示 hard feasible candidates 的点位。
- `all_candidates_footprints_map.png`：展示 hard feasible candidates 的建筑 footprint。
- `pareto_points_map.png`：展示 Pareto optimal candidates 的点位。
- `pareto_footprints_map.png`：展示 Pareto optimal candidates 的建筑 footprint。

绘图模式固定为：

```text
points
footprints
```

`points` 模式只使用候选记录中的：

```text
x
y
```

`footprints` 模式使用候选记录中的：

```text
x
y
theta
```

并使用配置中的：

```text
rect_w_m
rect_h_m
```

计算矩形四角。

Candidate map 的调用方负责先筛选 records。Figure 模块不根据 `is_feasible` 或 Pareto 状态重新筛选。

### 3.2 Pareto 3D Interactive HTML

Pareto 3D 图用于展示三目标 Pareto front。输出格式固定为 HTML：

```text
pareto_3d_interactive.html
```

三轴由调用方传入，取这次搜索目标名单的前三项。CMA-ES、多起点 Adam 和 VAE-like 仍是 `dem_soft`、`road_distance`、`demand_distance`。默认引导式搜索是 `dem_soft`、`offroad_haul_m`、`haul_rise_m`。名单里第 4 项及以后不占轴，记录里有有限值时只出现在悬停里。

要求：

- 输入应是已经完成 Pareto 提取的 pareto records。
- 不在 figure 模块中重新计算 Pareto；Pareto 提取由 `algorithms/common/pareto.py` 完成。
- 不重新计算 objective、normalization 或 scalar。
- 三个目标均按最小化解释。
- 坐标轴标题使用调用方传入的 objective name，不在图里另写一套默认目标。
- hover 信息至少包含 `run_id`、`x`、`y`、`theta` 和三个轴。记录里有有限的 `scalar` 时一并显示；引导式多目标搜索不产生标量，该字段留空时跳过。
- HTML 文件应自包含或尽量减少外部依赖，方便实验结果目录直接打开查看。

## 4. 公共输入约定

Candidate map 需要调用方传入：

```text
dem
obstacle_mask
road_segments
demand_points
records
rect_w_m
rect_h_m
output_path
title
mode
```

Pareto 3D HTML 需要调用方传入：

```text
pareto_records
output_path
title
```

records 应该来自算法输出或公共 Pareto 提取结果。Figure 模块假设字段已经存在，字段缺失时应直接报错，不做猜测或静默兜底。

## 5. 与算法模块的关系

算法模块负责产生候选、评价目标和 hard metrics。Figure 模块负责展示这些结果。

以 CMA-ES 为例：

- `algorithms/cma_es/cma_es.py` 负责搜索并生成 candidate records。
- `algorithms/cma_es/cma_es_main.py` 负责写出 CSV/JSON，并调用 `figures/` 生成图。
- `figures/` 不依赖 CMA-ES 的内部搜索状态，只依赖公共候选字段。

`experiments/problem_context.py` 负责一次性准备所有算法共享的站点数据上下文，
`experiments/output_writer.py` 负责统一写出 CSV、摘要和图件。multi-start Adam
或其他算法只负责搜索/训练，不应在算法目录里复制数据准备和地图绘制编排。

## 6. 与 Algorithm Common 的关系

Figure 模块和 `algorithms/common/` 是两个不同层次：

- `algorithms/common/`：多目标算法公共逻辑，例如 objective order、weight grid、normalization、Tchebycheff scalarization、Weiszfeld ideal、Pareto 提取。
- `figures/`：实验展示图公共逻辑，例如 candidate map、footprint map、Pareto 3D HTML。

Figure 模块不应导入 `algorithms/common` 来重新计算 scalar 或 Pareto。调用方应先完成计算，再把结果传给 figure 模块。

## 7. 后续可扩展图

后续如果多个算法共享同类图，优先放入 `figures/`：

- Pareto 2D 静态图。
- scalar convergence curve。
- objective convergence curve。
- feasible candidate distribution。
- all candidates vs hard feasible vs Pareto 对比图。

## 8. 平台展示边界

结果读取接口。删除已完成实验目录的接口写在 `markdown/V0_ARCHITECTURE.md`。

```text
GET /api/v1/experiments
GET /api/v1/experiments/{experiment_id}
GET /api/v1/experiments/{experiment_id}/artifacts/{artifact_id}
```

前端按 artifact 类型选择展示方式：PNG 使用图片预览，HTML 使用 sandbox iframe，
JSON 和 CSV 提供查看/下载链接。缺少某个可选图件时只隐藏该图件，不影响整个实验结果页。
