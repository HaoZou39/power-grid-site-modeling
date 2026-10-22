"""Backend equivalence, boundary ties and chunked road-label construction."""

import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
import torch

from config.project_config import load_project_config
from data_tools import road_voronoi as module
from data_tools.road_voronoi import compute_segment_voronoi, resolve_voronoi_backend
from data_tools.traffic_tool import build_road_product


def _roads(seed=19, count=271):
    return np.random.default_rng(seed).uniform(-10, 80, (count, 4)).astype(np.float32)


def test_numpy_fallback_is_exact_across_both_chunk_axes(monkeypatch):
    roads = _roads()
    expected = compute_segment_voronoi(roads, 31, 47, 0.7, backend="cpu")
    monkeypatch.setattr(module, "_segment_voronoi_numba", None)
    for chunk in (1, 113, 10000):
        actual = compute_segment_voronoi(roads, 31, 47, 0.7, chunk, backend="cpu")
        np.testing.assert_array_equal(actual, expected)


def test_auto_uses_cpu_without_cuda_and_explicit_cuda_rejects(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert resolve_voronoi_backend() == "cpu"
    with pytest.raises(RuntimeError, match="unavailable"):
        resolve_voronoi_backend("cuda")
    np.testing.assert_array_equal(compute_segment_voronoi(_roads(), 9, 13),
                                  compute_segment_voronoi(_roads(), 9, 13, backend="cpu"))


def test_auto_uses_cpu_without_triton(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(module, "find_spec", lambda name: None)
    assert resolve_voronoi_backend() == "cpu"
    with pytest.raises(ImportError, match="Triton"):
        resolve_voronoi_backend("cuda")


@pytest.mark.parametrize("kwargs", [
    {"height": 0}, {"width": 1.5}, {"resolution_m": float("nan")},
    {"resolution_m": 0}, {"chunk_points": 0}, {"gpu_chunk_points": 0},
    {"segment_tile": 63}, {"backend": "unknown"},
])
def test_invalid_grid_and_backend_parameters(kwargs):
    inputs = dict(height=3, width=7, backend="cpu")
    inputs.update(kwargs)
    with pytest.raises(ValueError):
        compute_segment_voronoi(_roads(), **inputs)


@pytest.mark.parametrize("roads", [np.empty((0, 4)), np.zeros((2, 3)),
                                    np.array([[0, 0, np.nan, 2]]), np.array([[1, 1, 1, 1]])])
def test_invalid_segments(roads):
    with pytest.raises(ValueError):
        compute_segment_voronoi(roads, 3, 7, backend="cpu")


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
@pytest.mark.parametrize("tile", [32, 64, 128, 256])
@pytest.mark.parametrize("resolution", [1.0, 0.7])
def test_cuda_matches_original_cpu_across_tail_chunks(tile, resolution):
    pytest.importorskip("triton")
    roads = _roads()
    expected = compute_segment_voronoi(roads, 31, 47, resolution, backend="cpu")
    actual = compute_segment_voronoi(roads, 31, 47, resolution, backend="cuda",
                                     gpu_chunk_points=157, segment_tile=tile)
    assert actual.dtype == np.int64
    np.testing.assert_array_equal(actual, expected)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
def test_cuda_keeps_earliest_id_for_shared_endpoints_and_cross_tile_ties():
    pytest.importorskip("triton")
    roads = np.tile([0, 0, 0, 40], (260, 1)).astype(np.float32)
    roads[5] = [0, 0, 40, 0]
    roads[150] = roads[5]
    roads[210] = [40, 0, 0, 0]
    for backend in ("cpu", "cuda"):
        labels = compute_segment_voronoi(roads, 20, 20, backend=backend,
                                         gpu_chunk_points=71, segment_tile=32)
        assert labels[3, 3] == 0
        assert labels[0, 10] == 5
        expected = np.where(np.arange(20)[:, None] < np.arange(20)[None, :], 5, 0)
        np.testing.assert_array_equal(labels, expected)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
def test_cuda_chunk_bounds_tensor_memory_independently_of_grid_size():
    pytest.importorskip("triton")
    roads = _roads(count=31)
    compute_segment_voronoi(roads, 1, 1, backend="cuda")
    for size in (37, 239):
        baseline = torch.cuda.memory_allocated()
        torch.cuda.reset_peak_memory_stats()
        compute_segment_voronoi(roads, size, size + 3, backend="cuda", gpu_chunk_points=1001)
        extra = torch.cuda.max_memory_allocated() - baseline
        assert extra < roads.nbytes + 1001 * 8 + 65536


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
def test_cuda_preserves_near_ties_at_nine_kilometre_coordinates():
    pytest.importorskip("triton")
    roads = np.array([
        [8999.0, -1, 8999.0, 3], [8999.001, -1, 8999.001, 3],
        [8998.998, -1, 8998.998, 3], [0, 0, 8999, 1], [0, 0, 8999, 1.00001],
    ], dtype=np.float32)
    cpu = compute_segment_voronoi(roads, 2, 9001, backend="cpu")
    cuda = compute_segment_voronoi(roads, 2, 9001, backend="cuda", gpu_chunk_points=1001)
    np.testing.assert_array_equal(cuda, cpu)


def test_build_product_passes_config_and_saves_exact_labels(tmp_path):
    reference = tmp_path / "reference.tif"
    with rasterio.open(reference, "w", driver="GTiff", height=12, width=14, count=1,
                       dtype="uint8", crs="EPSG:4326", transform=from_origin(120, 28, 0.001, 0.001)) as dst:
        dst.write(np.zeros((1, 12, 14), np.uint8))
    source = tmp_path / "roads.geojson"
    source.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "LineString",
         "coordinates": [[120.001, 27.999], [120.011, 27.990]]}},
    ]}))
    target = tmp_path / "labels.npy"
    segments, labels, metadata = build_road_product(source, None, target, reference, (12, 14), 0,
                                                   voronoi_backend="cpu", voronoi_chunk_points=113)
    np.testing.assert_array_equal(labels, compute_segment_voronoi(segments, 12, 14, backend="cpu"))
    np.testing.assert_array_equal(np.load(target), labels)
    assert metadata["voronoi_backend"] == metadata["voronoi_device"] == "cpu"
    assert json.loads(target.with_suffix(".json").read_text())["voronoi_backend_requested"] == "cpu"
    config = load_project_config("config/default_config.json")
    assert config.data.road_voronoi_backend == "auto"
    assert config.data.road_voronoi_segment_tile == 128
