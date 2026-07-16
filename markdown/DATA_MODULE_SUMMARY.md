# Data Module Summary

这个文档保存新仓库数据模块所需的全部信息。新仓库实现数据处理层时只服从本文档，不直接参考旧代码。

为避免原始数据和代码混放，新仓库中：

- `data/` 只存放原始输入数据文件，例如 DEM tif、landuse csv、OSM GeoJSON。
- `data_tools/` 存放数据处理 tool 的 Python 代码。
- 四个数据 tool 的中间结果和标准产物写入显式配置的输出目录，例如 `outputs/`，不要写回原始 `data/`。

如果本文档信息不足，先补充本文档，再继续实现。

## 数据模块职责

数据模块负责把原始输入整理成四个独立 tool 的标准输出。它只处理数据读取、数据转换、数据生成和数据记录，不负责建模目标函数，也不负责 Pareto Set Learning。

当前数据模块需要包含四类核心数据：

1. DEM 数据
2. 不可建设区域掩膜
3. OSM 道路数据及道路 Voronoi 图
4. 随机生成的需求点

这四类数据应理解为四个独立的数据处理 tool：

```text
data/                 # 原始输入数据，不放 Python 代码
data_tools/
  dem_tool.py        # 读取/处理 DEM，生成 1 m 对齐 DEM 矩阵
  landuse_tool.py    # 读取 landuse/obstacle，生成不可建设区域矩阵
  traffic_tool.py    # 读取 OSM 道路，简化道路并生成道路 Voronoi 交通图矩阵
  demand_tool.py     # 随机生成连续需求点
```

这里的 tool 指的是四个相对独立的数据处理软件/模块。每个 tool 负责一种数据产物，后续实验脚本或建模模块按需读取这些产物，数据模块不强制汇总成统一数据结构。

## 坐标系总约定

数据模块必须使用统一的局部栅格坐标系。当前真实区域实验以图像识别得到的 landuse / obstacle 大矩阵作为唯一主栅格；当前 shape 为 `1800 x 1800`，但实现不能把 1800 写死，必须从矩阵 shape 读取。

卫星 GeoTIFF 只作为带地理参考的空间底座，用它的 CRS、bounds 和 transform 把外部空间数据对齐到主栅格。数据模块输出给建模和算法模块后，所有空间数据都必须是同一个局部矩阵坐标，不再混用经纬度或 EPSG 坐标。

局部坐标系约定：

```text
原点：左上角
x：向右为正
y：向下为正
单位：米
矩阵分辨率：1 m
```

如果最终矩阵 shape 为：

```python
H, W = matrix.shape
```

则局部连续坐标范围为：

```python
x in [0, W]
y in [0, H]
```

矩阵索引和局部坐标的关系为：

```text
matrix[row, col] 对应局部 1 m 栅格单元：
x in [col, col + 1]
y in [row, row + 1]

该单元中心点：
x = col + 0.5
y = row + 0.5
```

- landuse csv / obstacle mask 是主栅格，直接定义局部坐标系。
- 卫星 GeoTIFF 提供主栅格对应的真实地理范围，即 CRS、bounds、transform。
- DEM GeoTIFF 必须对齐到主栅格。
- OSM 道路 GeoJSON 必须对齐到主栅格。
- 需求点、候选点和 footprint 不做经纬度转换，直接在主栅格局部坐标中计算。

## 空间对齐入口

正式数据对齐入口由以下参数定义：

```python
reference_geotiff_path: Path       # satellite GeoTIFF with CRS/bounds/transform
primary_grid_shape: tuple[int, int] # from landuse / obstacle mask, [H, W]
target_resolution_m: float = 1.0
```

其中：

- `reference_geotiff_path` 指向与图像识别 landuse / obstacle 来源一致的卫星 GeoTIFF。
- `primary_grid_shape` 必须从 landuse / obstacle mask 的 shape 得到，不允许由 `center_lon`、`center_lat` 或 `half_side_m` 反推。
- 当前数据的 `primary_grid_shape` 为 `[1800, 1800]`。
- 当前卫星 GeoTIFF 使用 EPSG:3857，但实现必须读取 GeoTIFF 自身 CRS，不要硬编码 CRS。

根据参考 GeoTIFF 的 bounds 和主栅格 shape 定义目标 transform：

```python
H, W = primary_grid_shape
target_transform = from_bounds(
    bounds.left,
    bounds.bottom,
    bounds.right,
    bounds.top,
    W,
    H,
)
```

所有外部空间数据都必须进入这个目标 transform 对应的主栅格：

- 卫星影像：从原始 GeoTIFF 重采样到 `primary_grid_shape`，用于绘图检查。
- DEM：从 DEM GeoTIFF 重投影 / 重采样到 `reference_geotiff_path` 的 CRS、bounds 和 `primary_grid_shape`。
- OSM 道路：从 WGS84 经纬度投影到参考 GeoTIFF CRS，再按参考 GeoTIFF bounds 映射到主栅格局部坐标。

OSM 道路映射到局部坐标的公式为：

```python
x_local = (x_ref - bounds.left) / (bounds.right - bounds.left) * W
y_local = (bounds.top - y_ref) / (bounds.top - bounds.bottom) * H
```

其中 `x_ref, y_ref` 是道路投影到参考 GeoTIFF CRS 后的米制坐标。`y_local` 使用 `bounds.top - y_ref`，因为局部栅格 y 轴向下为正，而 GeoTIFF CRS 中 y 轴向上为正。

旧的 `center_lon / center_lat / half_side_m` 局部投影口径废弃，不作为正式数据模块接口，也不作为真实区域实验 fallback。

## 核心栅格约定

数据模块最终输出给后续模块的所有矩阵都必须对齐到同一个 1 m 分辨率主栅格。

当前默认输入分辨率：

- DEM GeoTIFF：外部高程栅格，可能不是主栅格分辨率，必须重投影 / 重采样到主栅格。
- landuse csv / obstacle：图像识别主栅格，当前为 1 m 局部矩阵。
- road GeoJSON：WGS84 经纬度矢量数据，不是栅格分辨率输入。
- demand：随机生成的连续点，不是栅格矩阵。

也就是说，除需求点以外，最终输出都应是空间范围一致、shape 一致、分辨率一致的 `np.ndarray`：

- landuse / obstacle mask 定义主栅格 shape 和局部坐标范围。
- DEM 最终必须重投影 / 重采样到主栅格矩阵。
- 道路 Voronoi 图必须生成到主栅格矩阵。
- 三者都使用左上角原点、x 向右、y 向下的局部坐标系。

需求点是唯一例外：需求点不是矩阵，也不要求落在离散 1 m 像素点上；它是与 1 m 输出矩阵使用同一空间范围和坐标原点的连续二维坐标数组。

## 1. DEM 数据

数据模块负责读取 DEM 数据。

输入：

```python
dem_path: Path                 # tif
reference_geotiff_path: Path   # satellite GeoTIFF spatial reference
primary_grid_shape: tuple[int, int]
target_resolution_m: float = 1.0
```

输出：

```python
dem: np.ndarray                # shape: [H, W], 1 m aligned
dem_metadata: dict             # source path, shape, resolution, local coord convention
```

要求：

- 支持从 tif 栅格文件读取 DEM。
- DEM 作为后续地形/平整度建模的基础输入。
- DEM GeoTIFF 是外部空间数据，不能直接假定已经与 landuse 主栅格对齐。
- DEM GeoTIFF 必须读取自身 CRS 和 transform，并重投影 / 重采样到 `reference_geotiff_path` 的 CRS、bounds 和 `primary_grid_shape`。
- 如果 DEM GeoTIFF 缺少 CRS 或 transform，应直接报错，不做静默猜测。
- `dem` 必须是二维矩阵。
- `dem[row, col]` 必须服从左上角原点、x 向右、y 向下的局部坐标约定。
- 输出 `dem.shape` 必须等于 `primary_grid_shape`，并与 obstacle mask、road Voronoi 的 shape 一致。
- DEM 是连续高程值，重投影 / 重采样时使用 bilinear interpolation。
- `dem_metadata` 必须记录 DEM 原始路径、DEM CRS、DEM transform、参考 GeoTIFF 路径、参考 CRS、参考 bounds、目标 transform、目标 shape 和重采样方法。
- DEM 文件路径必须由配置显式提供，不做隐式搜索。

## 2. Landuse 主栅格与不可建设区域掩膜

不可建设区域掩膜来自 landuse csv。landuse csv 是当前真实区域实验的主栅格入口，后续 DEM、道路 Voronoi、需求点和候选点都必须服从它的 shape 和局部坐标范围。

landuse csv 的数值类别、真实含义和不可建设映射如下，数据模块必须把这套映射写入输出 metadata：

| 数值 | 英文代码 | 中文含义 | 典型颜色 | 可建设性 | obstacle mask |
|---:|---|---|---|---|---:|
| 0 | `other` | 其他区域 | 灰色 | 可建设 | 0 |
| 1 | `field` | 农田区域 | 黄色 | 不可建设 | 1 |
| 2 | `building` | 建筑区域 | 品红/粉红 | 不可建设 | 1 |
| 3 | `road` | 道路区域 | 红色 | 不可建设 | 1 |
| 4 | `mountain_natural` | 山体/自然区域（裸地、草地、林地等合并） | 绿色 | 可建设 | 0 |
| 5 | `water` | 水体区域 | 蓝色 | 不可建设 | 1 |

因此默认可建设类别为：

```python
buildable_classes = (0, 4)
```

默认不可建设类别为：

```python
obstacle_classes = (1, 2, 3, 5)
```

`obstacle_mask` 的二值语义固定为：

```text
0 = 可建设
1 = 不可建设
```

输入：

```python
landuse_path: Path             # csv
obstacle_classes: tuple[int, ...] = (1, 2, 3, 5)
landuse_input_resolution_m: float = 1.0
target_resolution_m: float = 1.0
```

输出：

```python
landuse: np.ndarray            # shape: [H, W], 1 m aligned
obstacle_mask: np.ndarray      # shape: [H, W], 1 m aligned, 1=不可建设, 0=可建设
landuse_metadata: dict
```

要求：

- 数据模块负责读取 landuse csv。
- landuse csv 直接视为图像识别输出的局部主栅格数据。
- `primary_grid_shape = landuse.shape = obstacle_mask.shape`。
- 当前默认 landuse 输入分辨率是 1 m。
- 输出统一的 obstacle mask。
- `landuse` 和 `obstacle_mask` 必须是二维矩阵。
- mask 中必须按上表明确区分可建设区域和不可建设区域。
- `obstacle_mask` 使用二值语义：`1` 表示不可建设区域，`0` 表示可建设区域。
- `0=other` 和 `4=mountain_natural` 映射到 `obstacle_mask=0`。
- `1=field`、`2=building`、`3=road`、`5=water` 映射到 `obstacle_mask=1`。
- 如果 landuse 中出现上表未定义的类别编号，应直接 `ValueError`，不要静默猜测其可建设性。
- obstacle mask 的最终输出分辨率为 1 m。
- landuse / obstacle 是类别或二值数据，不能使用 bilinear interpolation。
- 如果未来 landuse / obstacle 需要重采样或对齐，只能使用 nearest neighbor interpolation，保证类别值和二值 mask 不被插成小数。
- 后续 `dem` 和 `road_voronoi` 的 shape 必须与 `landuse` 和 `obstacle_mask` 一致。
- 不可建设区域掩膜作为后续约束建模输入。
- landuse / obstacle 文件路径必须由配置显式提供。

## 3. OSM 道路数据与道路 Voronoi 图

数据模块负责读取从 OSM 下载下来的道路数据，并对道路数据做处理，生成针对道路的 Voronoi 图。

输入：

```python
osm_roads_path: Path           # GeoJSON, WGS84 lon/lat
road_voronoi_output_path: Path
reference_geotiff_path: Path
target_shape: tuple[int, int]
road_dp_tolerance_m: float
road_resolution_m: float = 1.0
```

输出：

```python
road_segments_local: np.ndarray    # shape: [N_seg, 4], each row = [x1, y1, x2, y2]
road_voronoi: np.ndarray           # shape: [H, W], 1 m aligned, value=nearest seg_id
road_metadata: dict            # projection params, shape, resolution, simplification params
```

要求：

- 输入为 OSM 道路 GeoJSON，坐标为 WGS84 经纬度。
- 必须根据参考 GeoTIFF 的 CRS 和 bounds，把道路转换到局部栅格坐标系。
- `reference_geotiff_path` 应指向与 landuse / obstacle 来源一致的带地理参考卫星 GeoTIFF；当前数据中该图为 EPSG:3857。
- `target_shape` 必须取 landuse / obstacle 的 shape，保证道路 Voronoi 与 DEM、obstacle mask 处于同一主栅格范围。
- 转换后所有道路几何都必须是局部坐标，不能在后续 Voronoi 或建模模块里继续混用经纬度。
- `road_segments_local` 记录所有道路线段的局部坐标，每一行是一条线段 `[x1, y1, x2, y2]`。
- 数据模块需要把 OSM 道路几何处理成后续可计算道路距离的数据结构。
- 在生成道路 Voronoi 图之前，先对 OSM 道路线做 Douglas-Peucker 简化，使道路折线适度直化、减少过密节点。
- 道路 Voronoi 切分只以道路线段为 site，不单独维护道路端点 site。
- 需要生成道路 Voronoi 图，用于后续计算候选点到道路的距离或最近道路归属。
- `road_voronoi` 必须是二维矩阵。
- `road_voronoi[row, col]` 存该像素最近道路线段的 `seg_id`。
- 道路 Voronoi 图的最终输出分辨率为 1 m，范围、shape 和坐标系应与 DEM 1 m 矩阵、obstacle mask 一致。
- `road_metadata` 必须记录参考 GeoTIFF 路径、参考 CRS、bounds、transform、原始 GeoTIFF shape、目标 shape、分辨率、Douglas-Peucker 简化参数、线段数量等说明性信息。
- OSM 输入路径、输出路径、参考 GeoTIFF 路径、目标 shape、Voronoi 分辨率和 Douglas-Peucker 简化容差必须参数化。
- 旧的 `center_lon / center_lat / half_side_m` 局部投影口径已废弃，不再出现在正式道路接口中。

道路 Voronoi 的线段编号约定：

- 每条道路线段都有一个 `seg_id`。
- `seg_id in [0, N_seg)`。
- `road_segments_local[seg_id]` 保存该线段的局部坐标，格式是 `[x1, y1, x2, y2]`。
- `road_voronoi` 矩阵中每个像素存该位置最近线段的 `seg_id`。

因此，Voronoi 切分不是对道路端点和线段共同切分，而是只对道路线段切分。候选点到道路的距离统一使用点到线段距离计算；当最近位置落在线段端点时，点到线段距离会自然退化为点到端点距离，不需要单独维护 endpoint site。

## 4. 随机需求点

需求点目前不从外部真实数据读取，改为随机生成。

输入：

```python
n_demand_points: int
demand_seed: int
primary_grid_shape: tuple[int, int]
demand_on_buildable_only: bool
obstacle_mask: np.ndarray | None
```

输出：

```python
demand_points: np.ndarray      # shape: [N, 2], continuous coordinates
demand_weights: np.ndarray | None
demand_metadata: dict
```

要求：

- 需求点由数据模块随机生成。
- 生成数量必须可配置。
- 随机生成必须支持 seed，保证实验可复现。
- 需求点应落在主栅格范围内，并使用与 1 m 输出矩阵一致的连续二维坐标系。
- 需求点不是矩阵输出，而是点坐标数组。
- `demand_points[:, 0]` 是连续 `x` 坐标。
- `demand_points[:, 1]` 是连续 `y` 坐标。
- 坐标不要求为整数像素。
- 坐标必须落在与 1 m 输出矩阵一致的局部空间范围内，即 `x in [0, W]`、`y in [0, H]`。
- `H, W` 必须来自 `primary_grid_shape`，不允许由 `half_side_m` 反推。
- 是否限制需求点只能落在可建设区域内，作为显式参数控制。
- 如果 `demand_on_buildable_only=True`，必须使用 `obstacle_mask` 从可建设像素内抽样。

## 参数化要求

以下内容必须参数化：

- DEM 文件路径
- DEM 分辨率
- landuse / obstacle 文件路径
- obstacle classes
- 参考卫星 GeoTIFF 路径
- 主栅格 shape，由 landuse / obstacle mask 读取
- OSM 道路文件路径
- 道路 Voronoi 输出路径
- 道路目标栅格 shape
- 道路 Voronoi 分辨率
- 需求点数量
- 需求点随机 seed
- 需求点是否限制在可建设区域

## 不做的事情

数据模块不负责：

- 计算平整度目标
- 计算道路距离目标
- 计算 Pareto front
- 训练 PSL 模型
- 运行实验对比

这些职责分别属于建模模块和算法模块。
