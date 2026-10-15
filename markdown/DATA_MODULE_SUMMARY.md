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

场景数据和优化分成两个阶段。数据构建把四个 tool 的产物写入 `scenes/<场景名>/`，这一步可以很慢，并且只在选定或更新场景时运行。优化阶段只读取该目录里已经写好的 `dem_1m.npy`、`landuse_1m.npy`、`obstacle_mask_1m.npy`、`road_segments_local.npy`、`road_voronoi_1m.npy`、`demand_points.npy` 和 `data_metadata.json`，不重新读取原始 tif、csv 或 GeoJSON。`landuse_1m.npy` 用来按类别合成当次约束，不触发 DEM、道路或需求点重建。研究脚本 `experiments/problem_context.py` 里的 `build_site_problem_context` 仍可供命令行实验一次完成构建和搜索；决策界面的优化入口不调用它。

决策网站只登记两个固定场景：`cangnan`（苍南）和 `yongjia`（永嘉）。`experiments/scene_store.py` 保存受控的 `scene_id -> 四文件` 映射；`yongjia` 只读取 `data/sites/yongjia/dem.tif`、`landuse.csv`、`osm_roads.geojson` 和 `satellite_ref.tif`，不得回退到 `config/default_config.json` 的苍南路径。用户只需复制这四个标准名文件，不要求 `metadata.json` 或 `qa_report.json`。苍南继续使用现有四个输入路径和已发布的 `scenes/cangnan/`。

网页构建使用 `site.prepare_scene` 任务。已就绪场景直接复用，不默认重建；未就绪场景先在 `scenes/` 下的私有临时目录生成并校验全部标准产物，再发布为 `scenes/<scene_id>/`。缺文件、GeoTIFF 无 CRS 或 OSM 没有有效 LineString/线段时任务失败，临时目录被清除，场景仍为未就绪，不能使用其他场景的数据补齐。场景列表即使在输出目录不存在时也返回两个登记项；就绪场景的地图 frame 取 `data_metadata.json`，未就绪场景若四份原始文件齐全则从真实 reference GeoTIFF 边界和 landuse shape 计算预览 frame。

地图显示使用的 `dem_elevation.png` 和 `dem_elevation.json` 是从 `dem_1m.npy` 派生的可选缓存，不属于场景就绪条件，也不参与建模或优化。新场景在准备阶段生成；旧场景缺少缓存时，由只读图层接口在独立可写缓存目录按需生成。色带上下限取该场景 DEM 的真实有限值范围，原始空间分辨率从 DEM metadata 的 `source_transform` 读取；当前苍南输入约为 10 m，1 m 矩阵是双线性重采样工作网格，不表示 1 m 实测精度。OSM 地图线直接读取 `road_segments_local.npy`，不重新下载或生成第二份道路模型数据。

## 坐标系总约定

数据模块必须使用统一的局部栅格坐标系。当前真实区域实验以图像识别得到的 landuse / obstacle 大矩阵作为唯一主栅格；当前 shape 为 `1800 x 1800`，但实现不能把 1800 写死，必须从矩阵 shape 读取。本仓库不包含分割模型本身。模型身份、点选标注和施工成本的待办写在 `markdown/DECISION_REQUIREMENTS.md`。

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
- DEM 是连续高程值，重投影 / 重采样时使用 bilinear interpolation。源栅格标了 NoData 时，缺测格子写成非有限值，再由有限值检查拒绝，不能把 `-9999` 这类哨兵留成高程。源文件没有 NoData 标记时不另猜哨兵。
- `dem_metadata` 必须记录 DEM 原始路径、DEM CRS、DEM transform、参考 GeoTIFF 路径、参考 CRS、参考 bounds、目标 transform、目标 shape 和重采样方法。
- DEM 文件路径必须由配置显式提供，不做隐式搜索。

## 2. Landuse 主栅格与不可建设区域掩膜

不可建设区域掩膜来自 landuse csv。landuse csv 是当前真实区域实验的主栅格入口，后续 DEM、道路 Voronoi、需求点和候选点都必须服从它的 shape 和局部坐标范围。

landuse csv 的数值必须是下面的整数类别。`1.0` 可以，`1.9` 这类小数在重采样之前就报错，不能等降采样丢掉那个像素，也不能截断后当成合法类别。类别含义和不可建设映射如下，数据模块必须把这套映射写入输出 metadata：

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

这张二值掩膜是默认策略下的产物：`1` 农田、`2` 建筑、`3` 道路、`5` 水体为不可建设，`0` 其他和 `4` 山体自然为可建设。地图按类别着色时使用 `landuse`，不把这四类画成同一种红色。`0` 和 `4` 不着色。

优化可以在读取场景之后，按本次类别策略和手绘禁区另合成约束，不改写场景目录里的 `landuse_1m.npy` 和 `obstacle_mask_1m.npy`。手绘禁区的顶点使用与主栅格相同的局部米坐标。点击某一格时，`experiments/landuse_patch.py` 用四连通取出同类区域的外环，再当作一块禁区参与同一次合成。区域格子数超过上限时直接报错。类别策略和合成规则写在 `markdown/MODELING_MODULE_SUMMARY.md`。

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
- 在生成道路 Voronoi 图之前，先对 OSM 道路线做拓扑感知的 Douglas-Peucker 简化，使道路折线适度直化、减少过密节点，同时不改变有证据支持的道路连接关系。不得对整条独立 LineString 直接简化，也不得依靠统一距离 Snap 半径把邻近道路强行连接。
- 连接证据以原始 GeoJSON 为准：道路端点始终保护；两条或多条道路共享的原始坐标节点、T 型路口中共享的原始节点、多分支节点作为真实连接节点。先在这些节点处分段，再只简化两个保护节点之间的内部形状点；所有相连 section 必须复用同一个保护节点坐标。
- `bridge`、`tunnel`、`layer` 表示不同高程层时，只有平面几何相交不建立连接。原始道路共享同一个坐标节点时将其视为有证据的连接或层级过渡，例如桥梁端点接回地面道路。当前 GeoJSON 没有 OSM node ID，因而无共享原始坐标、只有平面相交的道路缺少足够拓扑证据，不因追求单一连通分量而自动连接；这一限制必须写入道路 metadata。现有 `[N,4]` 产物不能表达坐标完全重合但拓扑上独立的两个分层节点，若未来输入包含这种情况，需要先补充节点身份或分层图结构，不能靠坐标猜测。
- 简化后必须验证：所有保护节点仍为线段端点；原始有证据连接的节点没有丢失；原本分开的道路分量没有被合并；所有线段非零且有限。metadata 记录原始/简化线段数、保护节点数、连接节点数、连通分量数和拓扑判断规则。
- `experiments/scene_store.py` 的 `rebuild_scene_roads` 是道路专用重建入口。它先备份旧的 segments、Voronoi、两份道路 sidecar 和 `data_metadata.json`，在场景同级临时目录生成并校验完整 bundle，再用发布标记阻止新读取并覆盖整组已有道路文件；覆盖而不是换 inode，可保留 Windows Docker bind mount 所需的原文件 ACL。失败时从备份恢复。它不调用完整 `prepare_scene()`，不改 DEM、landuse、demand 或土地类型编辑。优化器和地图均继续读取同一场景目录中的正式道路数组。
- 2026-10-14 使用当前 `cangnan` 输入验证：56 个 feature / LineString 产生 1093 条原始线段、1085 个节点、1 个连通分量，总长 33503.644 m。旧的逐 LineString 简化产生 843 条线段、846 个节点、6 个分量，总长 33464.523 m，丢失 11 个路口上的 22 条连接关系。拓扑感知简化保护 82 个节点，其中真实分支节点 42 个，产生 859 条线段、851 个节点、1 个分量，总长 33466.015 m；丢失连接和意外分量合并均为 0。固定进货原点 `(120.193987, 27.500968)` 对应局部坐标约 `(827.541, 987.102)`，新版场景中 13095 个 Gate 全部可达。
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

## 按坐标生成新场景

新场景不从文件名反推地理范围。用户给出中心纬度和经度，以及正方形边长（米）。流水线里的 `radius_km` 是 Web Mercator 投影米下的半边长，换算是：

`radius_km = side_length_m / 2000.0`

因此 1800 m × 1800 m 对应 `radius_km = 0.9`。一格是 1 m，网格高度和宽度都等于边长，不能单独指定。边长必须是 2 到 4096 之间的偶数米，这样半边长能用 site id 里的三位小数表示。`zoom` 默认 18，`road_buffer_m` 默认 500。场景名称可以是中文，只作为显示名，不进入 site id。这些值在创建任务前用 `masking_pipeline/naming.py` 的精度规则收成 site id。空的场景名称记为 `site`，并且不进入 site id。site id 形如 `lat{6}_lon{6}_r{3}km_z{zoom}_g{H}x{W}_rb{buffer}m`。多出来的小数会被拒绝，避免两个不同范围写成同一个目录。

入口是现有任务系统里的插件 `site.build_scene`。HTTP 处理函数只校验并入队。Worker 调用 `experiments.coordinate_scene.build_scene_from_coordinates`，后者直接调用 `masking_pipeline.run.run_pipeline(...)`，不拼接 shell 命令。阶段写在任务的 `stage` 字段上，任务状态仍是 `queued`、`running`、`succeeded`、`failed` 或 `cancelled`：

`queued` → `generating_data` → `validating_data` → `rebuilding_scene` → `ready`

成功时状态是 `succeeded`，阶段是 `ready`。任一步失败时状态是 `failed`，阶段停在失败的那一步，消息是可读摘要；完整 traceback 只留在任务错误和 worker 日志里。已有的 `POST /api/v1/jobs/{job_id}/cancel` 可以在两个流水线步骤之间终止任务。页面上的重试会用上一次提交的同一份配置再创建一个任务。

四份正式文件由上游 `export_bundle` 在暂存目录里做 QA，只有 `overall_status == passed` 才调用 `release_staged_bundle`。发布位置是：

`{MASKING_OUTPUT_ROOT}/{site_id}/bundle/`

文件名固定为：

- `{site_id}_satellite_epsg3857.tif`
- `{site_id}_landuse.csv`
- `{site_id}_dem.tif`
- `{site_id}_osm_roads_wgs84.geojson`

同目录的上一级还保留 `metadata.json`、`qa_report.json`、`downstream_config.json`、`previews/` 和 `.cache/`。发布前再检查 QA 为通过、卫星 CRS 为 EPSG:3857、用地 shape 等于目标网格且类别是 0 到 5 的整数、道路是非空的线要素、DEM 有 CRS 并且覆盖卫星影像的 GeoTIFF bounds。失败的 QA 不会改成警告，也不会替换已经发布过的 bundle。

通过之后调用 `experiments.scene_store.prepare_scene_from_sources`。它仍使用现有的 `write_scene_products`，生成 1 m 局部网格、用地、障碍、DEM、道路、Voronoi、需求点和 `data_metadata.json`。局部原点、轴向、用地到障碍的映射、需求点数量 64 和种子 42 都沿用 `config/default_config.json`。新目录先写在临时目录，校验通过后才替换 `{SCENE_ROOT}/{site_id}/`。旧目录先移到 `{SCENE_ROOT}/.previous/{site_id}`，新目录就位后才删除。重建失败时旧场景保持不可被这次失败覆盖，任务停在 `rebuilding_scene`，场景不能拿去优化。

同一个 site id 同时只能有一个写入。锁是 `{SCENE_ROOT}/.locks/{site_id}`，进程内还有一份集合，避免本机单进程 worker 里的并发线程互相覆盖。`.locks` 和 `.previous` 不是场景。

生成结果默认不进 Git。需要的环境变量：

| 变量 | 作用 |
| --- | --- |
| 区域 OSM | `masking_pipeline/data/regional/zhejiang-261020.osm.pbf`，随仓库提供。 |
| 区域 DEM | `masking_pipeline/data/regional/wenzhou.tif`，随仓库提供。必须覆盖请求范围。 |
| `MASKING_OUTPUT_ROOT` | 流水线站点目录。默认 `outputs/masking-sites`。 |
| `SCENE_ROOT` | 模型就绪场景目录。默认 `scenes`。API 和 worker 必须指向同一份持久目录。 |
| `MASKING_MODEL` | Hugging Face 模型 id。默认 `mfaytin/mask2former-satellite`。 |
| `MASKING_HF_ENDPOINT` | 模型下载端点。默认 `https://hf-mirror.com`。留空则不改现有 `HF_ENDPOINT`。 |
| `HF_HOME` 或 `MASKING_MODEL_CACHE` | 模型缓存。同一路径上的后续任务复用已下载权重。 |
| `MASKING_DEVICE` | `auto`、`cpu` 或 `cuda`。`auto` 在有 CUDA 时用 GPU，否则用 CPU。`cuda` 在没有 GPU 时直接失败。 |

系统依赖是 `osmium-tool`。找不到时流水线会改用内置 PBF 读取器，并在元数据里记录这一点。分割权重不放进仓库。Docker worker 默认安装 CPU 版 PyTorch；要用 GPU，换成 CUDA wheel 并把 `MASKING_DEVICE` 设为 `cuda` 或 `auto`。区域数据用 `deploy/compose.masking.yaml` 只读挂载，不复制进镜像。

预置的苍南和永嘉仍走 `site.prepare_scene`，不经过这条流水线。优化插件的目标顺序、约束和结果字段不变。

## 不做的事情

数据模块不负责：

- 计算平整度目标
- 计算道路距离目标
- 计算 Pareto front
- 训练 PSL 模型
- 运行实验对比

这些职责分别属于建模模块和算法模块。
