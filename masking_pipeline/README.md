# Masking Pipeline

从给定 GPS 坐标生成 routing land-cover masking 图的完整流水线。

本目录是从 `image_process/` 复制整理而来的**独立可运行包**，不依赖仓库其它代码。原有 `image_process/` 脚本保持不动。

## 流程

```
坐标 (lat, lon) + 浙江 OSM / 温州 DEM
    │
    ▼
[1] download.py     下载 ESRI World Imagery → EPSG:3857 GeoTIFF
    │               任一瓦片失败则中止，不把灰色占位像元送去分割
    ▼
[2] osm.py          osmium complete_ways 提取道路，再按研究区外缓冲裁剪
[3] dem.py          按卫星范围裁剪区域 DEM，保留原始高程
    │
    ▼
[4] segment.py      Mask2Former 分割 → fine/coarse .npy
    │
    ▼
[5] downsample.py   最近邻下采样到目标网格 (默认 1800×1800)
    │
    ▼
[6] bundle.py       写出四份标准数据、metadata.json、qa_report.json
```

`radius-km` 是 Web Mercator 下正方形的半边长（乘 1000 为投影米），不是大地测量半径。道路缓冲 `--road-buffer-m` 也是卫星 CRS 里的投影距离，不是精确地表距离。

区域底库在 `data/regional/`。流水线默认读下面两份，并随仓库提供：

```text
data/regional/zhejiang-261020.osm.pbf
data/regional/wenzhou.tif
```

`wenzhou.tif` 是温州附近高程（约东经 119.45°–121.50°、北纬 27.14°–28.80°）。南边界停在全省 DEM 的覆盖尽头，大约 27.14°N。全省 `zhejiang.tif` 约 500MB，不入库。

路由粗类别 (`ROUTE_CLASSES`):

| id | name              | color   |
|----|-------------------|---------|
| 0  | other             | #666666 |
| 1  | field             | #f2d16b |
| 2  | building          | #d81b60 |
| 3  | road              | #ff4d4d |
| 4  | mountain_natural  | #2ecc71 |
| 5  | water             | #1f5fd1 |

## 安装

```bash
cd masking_pipeline
# 推荐：本仓库已有 conda 环境
conda activate route_plan

# 或新建环境
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

- 道路提取需要系统命令 `osmium`（`osmium-tool`）。当前环境可用：

```bash
conda install -n route_plan -c conda-forge osmium-tool
```

没有 `osmium` 时会退回内置 PBF 读取器，并打印警告。
- 坐标转换使用 `pyproj`。
- 分割步骤有 GPU（CUDA）会更快；无 GPU 时自动用 CPU（较慢）。
- 国内默认使用 HuggingFace 镜像 `https://hf-mirror.com` 拉取模型 `mfaytin/mask2former-satellite`。
- 本包已在 `route_plan` 环境下跑通 download → segment → downsample。

## 一键运行

```bash
cd masking_pipeline

python run.py \
  --site-name cangnan \
  --lat 27.501662 \
  --lon 120.194639 \
  --radius-km 0.9 \
  --zoom 18 \
  --target-height 1800 \
  --target-width 1800 \
  --osm-pbf data/regional/zhejiang-261020.osm.pbf \
  --dem-source data/regional/wenzhou.tif \
  --road-buffer-m 500 \
  --output-root outputs \
  --step all

# 分阶段。osm / dem 只读已有卫星 GeoTIFF，不会启动 Mask2Former
python run.py --lat 27.501662 --lon 120.194639 --output-dir outputs/cangnan_test --step download
python run.py --lat 27.501662 --lon 120.194639 --output-dir outputs/cangnan_test --step osm
python run.py --lat 27.501662 --lon 120.194639 --output-dir outputs/cangnan_test --step dem
python run.py --lat 27.501662 --lon 120.194639 --output-dir outputs/cangnan_test --step segment
python run.py --lat 27.501662 --lon 120.194639 --output-dir outputs/cangnan_test --step downsample
python run.py --lat 27.501662 --lon 120.194639 --output-dir outputs/cangnan_test --step export

# 参数一致且产物还在时才复用；换了中心点或缓冲会拒绝缓存
python run.py --lat 27.501662 --lon 120.194639 --output-dir outputs/cangnan_test --step all --resume

# 直连 huggingface.co（不用镜像）
python run.py --lat 27.55 --lon 120.38 --hf-endpoint ""
```

## 标准输出

`site_id` 由 `naming.py` 统一生成。苍南示例：

`lat27.501662_lon120.194639_r0.900km_z18_g1800x1800_rb500m`

场景简称仍写入 `metadata.json` 的 `site_name`，不放进目录名或文件名。

```text
outputs/<site_id>/
├── bundle/
│   ├── <site_id>_satellite_epsg3857.tif
│   ├── <site_id>_landuse.csv
│   ├── <site_id>_dem.tif
│   └── <site_id>_osm_roads_wgs84.geojson
├── previews/
│   ├── <site_id>_satellite_preview.png
│   ├── <site_id>_landuse_preview.png
│   ├── <site_id>_dem_preview.png
│   ├── <site_id>_osm_roads_preview.png
│   └── <site_id>_alignment_check.png
├── metadata.json
├── qa_report.json
├── downstream_config.json
└── .cache/                  # 断点续跑，不进入 bundle
```

`--output-dir` 仍表示“就写到这个目录”，不会再套一层 site_id。新运行请用 `--output-root`。真实地理范围以 GeoTIFF bounds 为准，不要只用文件名里的 radius 反推。

下游 `power-grid-site-modeling` 直接读这四份 `bundle` 文件。`landuse.csv` 用 `numpy.loadtxt`，道路 GeoJSON 用 `@id`、`layer`、`bridge`、`tunnel`，DEM 必须带 CRS。外围道路只说明缓冲内的拓扑还在，不表示研究区外的每条绕行都可被下游使用。

## 旧版中间产品

在 `intermediates/`（默认输出目录名仍是 `outputs_lat{lat}_lon{lon}_{YYYYMMDD}/`）下：

| 文件 | 说明 |
|------|------|
| `*_epsg3857.tif` | 卫星 GeoTIFF |
| `*_preview.png` | 卫星预览图 |
| `*_openearthmap_fine.png` | 细类叠加可视化 |
| `*_routing_coarse.png` | 粗类叠加可视化（masking 图） |
| `*_routing_coarse_mask.npy` | 全分辨率粗类 mask |
| `*_routing_coarse_mask_class_map.png` | 全分辨率纯色类别图 |
| `*_routing_coarse_downsampled.png` | 下采样后 masking 图 |
| `*_routing_coarse_mask_downsampled.npy` | 下采样 mask（可直接用于路径规划） |

## 作为库调用

```python
from run import run_pipeline

results = run_pipeline(lat=27.501662, lon=120.194639)
print(results["coarse_vis"])
print(results["downsampled_npy"])
```

## 文件说明

| 文件 | 来源 | 作用 |
|------|------|------|
| `run.py` | 统一入口，支持分阶段和 `--resume` |
| `download.py` | 瓦片下载；失败瓦片会中止 |
| `segment.py` | Mask2Former 地物分割 |
| `downsample.py` | 最近邻下采样 |
| `render.py` | 纯色类别图 |
| `osm.py` / `osm_pbf.py` | OSM 道路、拓扑和预览 |
| `dem.py` | DEM 裁剪和覆盖检查 |
| `bundle.py` | 四文件数据包、metadata、QA |
| `visualize.py` | 四宫格对齐图 |
