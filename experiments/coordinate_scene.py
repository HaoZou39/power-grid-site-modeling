"""Build one scene from a center coordinate by running the masking pipeline, then the existing reconstruction."""

from __future__ import annotations

import json
import math
import os
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from experiments.scene_store import prepare_scene_from_sources, scenes_root
from masking_pipeline.naming import (
    NamingError,
    build_site_id,
    build_site_paths,
    bundle_filenames,
    canonical_parameters,
)

Progress = Any
MIN_GRID = 1
MAX_GRID = 4096
_LOCK_GUARD = threading.Lock()
_HELD_IDS: set[str] = set()


class CoordinateSceneError(ValueError):
    """The coordinate build request or its published bundle cannot be accepted."""


@dataclass(frozen=True)
class BuildRequest:
    lat: float
    lon: float
    side_length_m: float
    radius_km: float
    zoom: int
    target_height: int
    target_width: int
    road_buffer_m: int
    site_name: str
    site_id: str

    @property
    def title(self) -> str:
        if self.site_name != "site":
            return self.site_name
        return f"{self.lat:.6f}, {self.lon:.6f}"


@dataclass(frozen=True)
class MaskingPaths:
    osm_pbf: Path
    dem_source: Path
    output_root: Path
    model: str
    hf_endpoint: str | None
    model_cache: Path | None


def _ensure_env() -> None:
    import agent.config  # noqa: F401  fills unset keys from the repo-root .env


def _finite(value: object, label: str) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise CoordinateSceneError(f"{label} 必须是有限数字") from exc
    if not math.isfinite(number):
        raise CoordinateSceneError(f"{label} 必须是有限数字")
    return number


def _whole(value: object, label: str) -> int:
    number = _finite(value, label)
    if abs(number - round(number)) > 1e-9:
        raise CoordinateSceneError(f"{label} 必须是整数")
    return int(round(number))


def radius_km_from_side_length(side_length_m: float) -> float:
    """Convert a square side length in metres to the pipeline's Web Mercator half-side in kilometres."""

    return float(side_length_m) / 2000.0


def _regional_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "masking_pipeline" / "data" / "regional"


def masking_paths() -> MaskingPaths:
    _ensure_env()
    regional = _regional_dir()
    osm = os.environ.get("MASKING_OSM_PBF", "").strip() or str(regional / "zhejiang-261020.osm.pbf")
    dem = os.environ.get("MASKING_DEM_SOURCE", "").strip() or str(regional / "wenzhou.tif")
    output = os.environ.get("MASKING_OUTPUT_ROOT", "outputs/masking-sites").strip() or "outputs/masking-sites"
    model = os.environ.get("MASKING_MODEL", "mfaytin/mask2former-satellite").strip() or "mfaytin/mask2former-satellite"
    endpoint = os.environ.get("MASKING_HF_ENDPOINT", os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")).strip()
    cache = os.environ.get("HF_HOME", os.environ.get("MASKING_MODEL_CACHE", "")).strip()
    if cache:
        os.environ["HF_HOME"] = cache
    return MaskingPaths(
        osm_pbf=Path(osm) if osm else Path(),
        dem_source=Path(dem) if dem else Path(),
        output_root=Path(output),
        model=model,
        hf_endpoint=endpoint or None,
        model_cache=Path(cache) if cache else None,
    )


def validate_build_config(config: dict[str, Any]) -> BuildRequest:
    """Reject a coordinate build before a job is queued."""

    lat = _finite(config.get("lat"), "lat")
    lon = _finite(config.get("lon"), "lon")
    if lat < -90 or lat > 90:
        raise CoordinateSceneError("lat 必须在 -90 到 90 之间")
    if lon < -180 or lon > 180:
        raise CoordinateSceneError("lon 必须在 -180 到 180 之间")
    side = _finite(config.get("side_length_m", 1800), "side_length_m")
    if side <= 0:
        raise CoordinateSceneError("side_length_m 必须大于 0")
    side_m = _whole(side, "side_length_m")
    if side_m < 2 or side_m > MAX_GRID or side_m % 2 != 0:
        raise CoordinateSceneError("边长必须是 2 到 4096 之间的偶数米。一格是 1 m，网格等于边长乘边长。")
    for key in ("target_height", "target_width"):
        if key not in config or config[key] is None:
            continue
        if _whole(config[key], key) != side_m:
            raise CoordinateSceneError("网格由边长决定，一格 1 m，不能单独指定高度或宽度")
    height = side_m
    width = side_m
    zoom = _whole(config.get("zoom", 18), "zoom")
    road_buffer = _whole(config.get("road_buffer_m", 500), "road_buffer_m")
    site_name = config.get("site_name")
    if site_name is not None and not str(site_name).strip():
        site_name = None
    radius_km = radius_km_from_side_length(side)
    try:
        params = canonical_parameters(
            lat, lon, radius_km, zoom, height, width, road_buffer, site_name
        )
    except NamingError as exc:
        raise CoordinateSceneError(str(exc)) from exc
    site_id = build_site_id(lat, lon, radius_km, zoom, height, width, road_buffer, site_name)
    return BuildRequest(
        lat=params["lat"],
        lon=params["lon"],
        side_length_m=side,
        radius_km=params["radius_km"],
        zoom=params["zoom"],
        target_height=params["target_height"],
        target_width=params["target_width"],
        road_buffer_m=params["road_buffer_m"],
        site_name=params["site_name"],
        site_id=site_id,
    )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _lock_is_stale(lock_dir: Path) -> bool:
    pid_path = lock_dir / "pid"
    if not pid_path.is_file():
        return time.time() - lock_dir.stat().st_mtime > 30
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        return True
    return not _pid_alive(pid)


@contextmanager
def scene_write_lock(site_id: str, root: Path) -> Iterator[None]:
    """Stop two builds from writing one scene directory."""

    lock_dir = root / ".locks" / site_id
    lock_dir.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK_GUARD:
        if site_id in _HELD_IDS:
            raise CoordinateSceneError(f"场景 {site_id} 已有构建任务正在写入同一目录")
        _HELD_IDS.add(site_id)
    acquired = False
    try:
        try:
            lock_dir.mkdir()
            acquired = True
        except FileExistsError as exc:
            if _lock_is_stale(lock_dir):
                shutil.rmtree(lock_dir)
                lock_dir.mkdir()
                acquired = True
            else:
                raise CoordinateSceneError(f"场景 {site_id} 已有构建任务正在写入同一目录") from exc
        (lock_dir / "pid").write_text(str(os.getpid()), encoding="utf-8")
        yield
    finally:
        if acquired:
            shutil.rmtree(lock_dir, ignore_errors=True)
        with _LOCK_GUARD:
            _HELD_IDS.discard(site_id)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CoordinateSceneError(f"{path.name} 必须是 JSON 对象")
    return value


def inspect_published_bundle(site_dir: Path, request: BuildRequest) -> dict[str, Path]:
    """Require the upstream QA report and the four readable bundle files before scene publication."""

    import numpy as np
    import rasterio

    from masking_pipeline.geo_utils import bounds_contain, transform_bounds

    site_dir = Path(site_dir)
    qa_path = site_dir / "qa_report.json"
    if not qa_path.is_file():
        raise CoordinateSceneError(f"缺少 QA 报告：{qa_path}")
    qa = _read_json(qa_path)
    if qa.get("overall_status") != "passed":
        errors = qa.get("errors") or ["QA 未通过"]
        detail = "；".join(str(item) for item in errors)
        raise CoordinateSceneError(f"数据包校验未通过：{detail}")
    names = bundle_filenames(request.site_id)
    bundle = site_dir / "bundle"
    paths = {key: bundle / name for key, name in names.items()}
    missing = [path.name for path in paths.values() if not path.is_file() or path.stat().st_size <= 0]
    if missing:
        raise CoordinateSceneError("数据包缺少可读文件：" + ", ".join(missing))
    expected = {name for name in names.values()}
    present = {path.name for path in bundle.iterdir() if path.is_file() and not path.name.startswith(".")}
    if present != expected:
        raise CoordinateSceneError(f"数据包必须恰好包含四份文件，实际为 {sorted(present)}")

    with rasterio.open(paths["satellite"]) as source:
        crs = None if source.crs is None else str(source.crs)
        if crs != "EPSG:3857":
            raise CoordinateSceneError(f"卫星影像 CRS 必须是 EPSG:3857，实际为 {crs}")
        reference_bounds = (source.bounds.left, source.bounds.bottom, source.bounds.right, source.bounds.top)

    landuse = np.loadtxt(paths["landuse"], delimiter=",")
    if landuse.ndim != 2 or tuple(int(v) for v in landuse.shape) != (request.target_height, request.target_width):
        raise CoordinateSceneError(
            f"用地网格 shape 必须是 {(request.target_height, request.target_width)}，实际为 {getattr(landuse, 'shape', None)}"
        )
    rounded = np.rint(landuse)
    if not np.isfinite(landuse).all() or not np.allclose(landuse, rounded, rtol=0.0, atol=1e-3):
        raise CoordinateSceneError("用地类别必须是整数")
    classes = {int(value) for value in np.unique(rounded)}
    if not classes.issubset(set(range(6))):
        raise CoordinateSceneError(f"用地类别必须在 0 到 5 之间，实际包含 {sorted(classes - set(range(6)))}")

    roads = _read_json(paths["osm_roads"])
    features = roads.get("features") if roads.get("type") == "FeatureCollection" else None
    if not isinstance(features, list) or not features:
        raise CoordinateSceneError("OSM 道路必须是非空的 FeatureCollection")
    bad = [
        (feature.get("geometry") or {}).get("type")
        for feature in features
        if not isinstance(feature, dict)
        or (feature.get("geometry") or {}).get("type") not in {"LineString", "MultiLineString"}
    ]
    if bad:
        raise CoordinateSceneError(f"OSM 道路包含非线几何：{bad[:5]}")

    with rasterio.open(paths["dem"]) as source:
        if source.crs is None:
            raise CoordinateSceneError("DEM 缺少 CRS")
        dem_bounds = (source.bounds.left, source.bounds.bottom, source.bounds.right, source.bounds.top)
        reference_in_dem = transform_bounds("EPSG:3857", str(source.crs), reference_bounds)
        tolerance = max(abs(float(source.res[0])), abs(float(source.res[1]))) * 2
        if not bounds_contain(dem_bounds, reference_in_dem, tol=tolerance):
            raise CoordinateSceneError("DEM 没有覆盖卫星影像范围")
    return paths


def _require_regional_files(paths: MaskingPaths) -> None:
    if not paths.osm_pbf.is_file():
        raise CoordinateSceneError(
            "缺少区域 OSM PBF：masking_pipeline/data/regional/zhejiang-261020.osm.pbf。"
            f"当前路径：{paths.osm_pbf}"
        )
    if not paths.dem_source.is_file():
        raise CoordinateSceneError(
            "缺少区域 DEM：masking_pipeline/data/regional/wenzhou.tif。"
            f"当前路径：{paths.dem_source}"
        )


def build_scene_from_coordinates(
    config: dict[str, Any],
    reporter: Progress,
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Run generation, QA, and the existing scene reconstruction for one coordinate request."""

    request = validate_build_config(config)
    paths = masking_paths()
    _require_regional_files(paths)
    scene_root = scenes_root(root).expanduser().resolve()
    scene_root.mkdir(parents=True, exist_ok=True)
    output_root = paths.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    def elapsed() -> float:
        return round(time.perf_counter() - started, 3)

    with scene_write_lock(request.site_id, scene_root):
        reporter(0.05, "generating_data", f"正在生成 {request.site_id} 的卫星、道路、DEM 和用地")
        from masking_pipeline.run import run_pipeline

        site_paths = build_site_paths(request.site_id, output_root=str(output_root))
        for step, progress, message in (
            ("download", 0.15, "正在下载卫星影像"),
            ("osm", 0.28, "正在提取 OSM 道路"),
            ("dem", 0.4, "正在裁剪 DEM"),
            ("segment", 0.55, "正在分割用地"),
            ("downsample", 0.68, "正在把用地下采样到目标网格"),
        ):
            reporter(progress, "generating_data", f"{message}（已用时 {elapsed():.0f} 秒）")
            run_pipeline(
                lat=request.lat,
                lon=request.lon,
                radius_km=request.radius_km,
                zoom=request.zoom,
                target_height=request.target_height,
                target_width=request.target_width,
                output_root=str(output_root),
                site_name=request.site_name,
                model=paths.model,
                hf_endpoint=paths.hf_endpoint,
                step=step,
                osm_pbf=str(paths.osm_pbf),
                dem_source=str(paths.dem_source),
                road_buffer_m=request.road_buffer_m,
                resume=True,
                render_fullres=True,
            )

        reporter(0.74, "validating_data", f"正在校验四份数据（已用时 {elapsed():.0f} 秒）")
        run_pipeline(
            lat=request.lat,
            lon=request.lon,
            radius_km=request.radius_km,
            zoom=request.zoom,
            target_height=request.target_height,
            target_width=request.target_width,
            output_root=str(output_root),
            site_name=request.site_name,
            model=paths.model,
            hf_endpoint=paths.hf_endpoint,
            step="export",
            osm_pbf=str(paths.osm_pbf),
            dem_source=str(paths.dem_source),
            road_buffer_m=request.road_buffer_m,
            resume=True,
            render_fullres=False,
        )
        bundle_paths = inspect_published_bundle(Path(site_paths["site_dir"]), request)

        reporter(0.82, "rebuilding_scene", f"正在重建场景 {request.site_id}（已用时 {elapsed():.0f} 秒）")

        def relay(progress: float, _stage: str, message: str) -> None:
            reporter(min(0.96, 0.82 + 0.14 * progress), "rebuilding_scene", message)

        scene_dir = prepare_scene_from_sources(
            request.site_id,
            {
                "dem_path": bundle_paths["dem"],
                "landuse_path": bundle_paths["landuse"],
                "osm_roads_path": bundle_paths["osm_roads"],
                "reference_geotiff_path": bundle_paths["satellite"],
            },
            relay,
            title=request.title,
            source_site_id=request.site_id,
            root=scene_root,
            progress_stage="rebuilding_scene",
        )
        message = f"场景已就绪（用时 {elapsed():.0f} 秒）"
        reporter(1.0, "ready", message)
        return {
            "scene_id": scene_dir.name,
            "site_id": request.site_id,
            "title": request.title,
            "bundle_dir": str(Path(site_paths["bundle_dir"])),
            "scene_dir": str(scene_dir),
            "elapsed_s": elapsed(),
            "message": message,
            "radius_km": request.radius_km,
            "side_length_m": request.side_length_m,
        }
