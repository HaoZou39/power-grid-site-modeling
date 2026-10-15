"""Compare origin-cache reuse with a repository revision on a prepared scene."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import types
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

import numpy as np

from experiments.constraint_mask import compose_constraint_masks, policy_from_form
from experiments.haul_field_cache import _ARRAY_DTYPES, get_or_build_haul_field
from modeling.haul_field import query_exact, query_route


@dataclass(frozen=True)
class OriginCacheValidationConfig:
    scene_dir: Path
    output_dir: Path
    reference_commit: str
    origins: tuple[tuple[float, float], ...] = ((827.541, 987.102), (1200.125, 600.25))
    diagonal: bool = False
    access_elevation_weight: float = 1.0
    sample_sites: int = 200
    seed: int = 123
    field_policy: str = "allowed"
    mountain_policy: str = "allowed"


def _reference_module(commit: str) -> types.ModuleType:
    source = subprocess.run(
        ["rtk", "proxy", "git", "show", f"{commit}:modeling/haul_field.py"],
        cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True,
    ).stdout
    module = types.ModuleType("haul_field_validation_reference")
    sys.modules[module.__name__] = module
    exec(compile(source, f"{commit}:modeling/haul_field.py", "exec"), module.__dict__)
    return module


def _compare(reference, actual, expected, sites: np.ndarray) -> dict:
    arrays = {}
    for name in (*_ARRAY_DTYPES, "road_m"):
        left, right = getattr(actual, name), getattr(expected, name)
        if left is None or right is None:
            assert left is right, name
            continue
        np.testing.assert_array_equal(left, right, err_msg=name)
        arrays[name] = {
            "sha256": hashlib.sha256(memoryview(np.ascontiguousarray(left)).cast("B")).hexdigest(),
            "max_absolute_difference": float(np.max(np.abs(left.astype(float) - right.astype(float)))) if left.size else 0.,
        }
    assert actual.reachable_gate_count == expected.reachable_gate_count
    assert actual.unreachable_gate_count == expected.unreachable_gate_count
    values, blocked = query_exact(actual, sites)
    expected_values, expected_blocked = reference.query_exact(expected, sites)
    np.testing.assert_array_equal(values, expected_values)
    np.testing.assert_array_equal(blocked, expected_blocked)
    routes = 0
    for site in sites[blocked == 0]:
        assert query_route(actual, tuple(site)) == reference.query_route(expected, tuple(site))
        routes += 1
    return {"arrays": arrays, "queried_sites": len(sites), "identical_routes": routes}


def validate(config: OriginCacheValidationConfig) -> dict:
    if config.sample_sites < 1:
        raise ValueError("sample_sites must be positive")
    directory = config.scene_dir.resolve()
    dem = np.load(directory / "dem_1m.npy")
    segments = np.load(directory / "road_segments_local.npy")
    form = {"field_policy": config.field_policy, "mountain_policy": config.mountain_policy}
    hard, _ = compose_constraint_masks(np.load(directory / "landuse_1m.npy"), [], policy_from_form(form))
    walkable = hard == 0
    reference = _reference_module(config.reference_commit)
    rng = np.random.default_rng(config.seed)
    indices = rng.choice(dem.size, min(config.sample_sites, dem.size), replace=False)
    centers = np.column_stack((indices % dem.shape[1] + .5, indices // dem.shape[1] + .5))
    sites = np.concatenate((centers, centers + [.071, .127]))
    # Compile both origin modes and the replay kernel before measuring runtime.
    from modeling.haul_field import build_haul_field, bind_haul_origin
    from modeling.logistics_cost import RoadNetwork
    warm_dem = np.zeros((5, 6), dtype=np.float32)
    warm_walkable = np.ones_like(warm_dem, dtype=bool)
    warm_segments = np.array([[.5, .5, 5.5, .5]])
    for origin in (None, (1.5, 1.5)):
        reference.build_haul_field(warm_dem, warm_walkable, warm_segments, origin, diagonal=config.diagonal,
                                   access_elevation_weight=config.access_elevation_weight)
    warm = build_haul_field(warm_dem, warm_walkable, warm_segments, diagonal=config.diagonal,
                            access_elevation_weight=config.access_elevation_weight)
    bind_haul_origin(warm, RoadNetwork(warm_segments).routes_from((1.5, 1.5)))
    rows = []
    with tempfile.TemporaryDirectory(prefix="haul-origin-validation-") as temporary:
        cache_scene = Path(temporary)
        for name in ("dem_1m.npy", "landuse_1m.npy", "road_segments_local.npy"):
            (cache_scene / name).symlink_to(directory / name)
        for origin in (None, *config.origins, None):
            started = perf_counter()
            expected = reference.build_haul_field(dem, walkable, segments, origin, diagonal=config.diagonal,
                                                   access_elevation_weight=config.access_elevation_weight)
            old_seconds = perf_counter() - started
            started = perf_counter()
            result = get_or_build_haul_field(
                cache_scene, dem, walkable, segments, origin, form,
                uses_landuse=True, diagonal=config.diagonal, access_elevation_weight=config.access_elevation_weight,
            )
            new_seconds = perf_counter() - started
            comparison = _compare(reference, result.field, expected, sites)
            row = {
                "origin": origin, "cache_status": result.status,
                "reference_seconds": old_seconds, "current_seconds": new_seconds,
                "speedup": old_seconds / new_seconds, "comparison": comparison,
            }
            rows.append(row)
            print(json.dumps({key: value for key, value in row.items() if key != "comparison"}), flush=True)
            del expected, result
    summary = {"config": asdict(config), "shape": list(dem.shape), "results": rows}
    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, default=Path("scenes/cangnan"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference-commit", required=True)
    parser.add_argument("--origin", type=float, nargs=2, action="append")
    parser.add_argument("--diagonal", action="store_true")
    parser.add_argument("--access-elevation-weight", type=float, default=1.0)
    parser.add_argument("--sample-sites", type=int, default=200)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--field-policy", choices=("allowed", "blocked", "costly"), default="allowed")
    parser.add_argument("--mountain-policy", choices=("allowed", "blocked"), default="allowed")
    args = parser.parse_args()
    config = OriginCacheValidationConfig(
        scene_dir=args.scene_dir, output_dir=args.output_dir, reference_commit=args.reference_commit,
        origins=tuple(tuple(point) for point in args.origin) if args.origin else OriginCacheValidationConfig.origins,
        diagonal=args.diagonal, access_elevation_weight=args.access_elevation_weight, sample_sites=args.sample_sites, seed=args.seed,
        field_policy=args.field_policy, mountain_policy=args.mountain_policy,
    )
    validate(config)


if __name__ == "__main__":
    main()
