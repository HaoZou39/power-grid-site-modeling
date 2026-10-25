"""Independent sampled Voronoi/setback checks and real-scene access-gate acceptance."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.spatial import cKDTree

from config.project_config import load_default_config
from data_tools.io_utils import write_json
from modeling.context import highway_building_buffer, rasterize_osm_centerlines
from modeling.haul_field import build_haul_field


def verify(scene: Path, output: Path, *, seed: int, samples: int, check_gates: bool) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    segments = np.load(scene / 'road_segments_local.npy')
    kinds = np.load(scene / 'road_segment_kind.npy')
    labels = np.load(scene / 'road_voronoi_1m.npy', mmap_mode='r')
    shape = labels.shape
    rng = np.random.default_rng(seed)
    rows = rng.integers(0, shape[0], samples)
    cols = rng.integers(0, shape[1], samples)
    points = np.column_stack((cols + .5, rows + .5))
    eligible = segments[kinds == 0].astype(np.float64)
    start, span = eligible[:, :2], eligible[:, 2:] - eligible[:, :2]
    ratio = np.clip(np.sum((points[:, None] - start) * span, axis=-1) / np.sum(span * span, axis=-1), 0, 1)
    distances = np.linalg.norm(points[:, None] - (start + ratio[..., None] * span), axis=-1)
    ids = labels[rows, cols]
    chosen = segments[ids].astype(np.float64)
    vector = chosen[:, 2:] - chosen[:, :2]
    t = np.clip(np.sum((points - chosen[:, :2]) * vector, axis=1) / np.sum(vector * vector, axis=1), 0, 1)
    selected = np.linalg.norm(points - (chosen[:, :2] + t[:, None] * vector), axis=1)
    errors = np.abs(selected - distances.min(axis=1))
    assert np.all(kinds[ids] == 0)
    assert errors.max() < 1e-3
    config = load_default_config()
    buffer = highway_building_buffer(segments, kinds, shape, config.modeling.highway_setback_m)
    padding = int(np.ceil(config.modeling.highway_setback_m))
    surface = rasterize_osm_centerlines(segments[kinds == 2] + padding, (shape[0] + 2 * padding, shape[1] + 2 * padding))
    if surface.any():
        tree = cKDTree(np.argwhere(surface) - padding)
        probes = rng.integers([0, 0], shape, size=(samples, 2))
        cells = np.argwhere(surface) - padding
        near = cells[rng.integers(0, len(cells), samples)] + rng.integers(-40, 41, (samples, 2))
        near = np.clip(near, [0, 0], np.asarray(shape) - 1)
        probes = np.concatenate((probes, near))
        expected = tree.query(probes)[0] <= config.modeling.highway_setback_m
        np.testing.assert_array_equal(buffer[probes[:, 0], probes[:, 1]], expected)
    report = {'scene': scene.name, 'seed': seed, 'samples': samples,
              'voronoi_access_only': True, 'max_independent_distance_error_m': float(errors.max()),
              'segment_kind_counts': {str(k): int(np.count_nonzero(kinds == k)) for k in range(4)},
              'highway_buffer_cells': int(np.count_nonzero(buffer)), 'setback_sample_matches': True}
    if check_gates:
        from experiments.constraint_mask import compose_hard_mask, policy_from_form
        from experiments.protected_farmland import access_inputs
        landuse = np.load(scene / 'landuse_1m.npy')
        hard = compose_hard_mask(landuse, [], policy_from_form({}), [])
        walkable, blocked = access_inputs(scene, hard)
        started = perf_counter()
        field = build_haul_field(np.load(scene / 'dem_1m.npy'), walkable, segments,
                                 diagonal=config.guided_search.diagonal_access,
                                 access_elevation_weight=config.guided_search.access_elevation_weight,
                                 connector_blocked=blocked, segment_kinds=kinds)
        assert np.all(kinds[field.gate_contact_edges] == 0)
        surface_barrier = rasterize_osm_centerlines(segments[np.isin(kinds, [1, 2])], shape)
        cells = field.gate_cells
        assert not surface_barrier[cells[:, 0], cells[:, 1]].any()
        report.update(gate_count=field.gate_count, reachable_gates=field.reachable_gate_count,
                      inaccessible_contact_count=0, surface_barrier_gate_count=0,
                      field_build_seconds=perf_counter() - started)
        del field
    if check_gates:
        write_json(output / 'gate_verification.json', report)
    _figure(segments, kinds, buffer, output / 'road_kinds_and_setback.png', config.modeling.highway_setback_m)
    write_json(output / 'verification.json', report)
    return report


def _figure(segments, kinds, buffer, path, setback):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    h, w = buffer.shape
    colors = ['#3d8f9f', '#e09a33', '#e74868', '#8063be']
    names = ['Access', 'Link: no access', 'Highway: no access', 'Tunnel: no access']
    for axis in axes:
        for kind in range(4):
            selected = segments[kinds == kind].reshape(-1, 2, 2)
            axis.add_collection(LineCollection(selected, colors=colors[kind], linewidths=1 if kind == 0 else 1.8,
                                                linestyles='dashed' if kind in (1, 3) else 'solid', label=names[kind]))
        axis.set_xlim(0, w); axis.set_ylim(h, 0); axis.set_aspect('equal')
        axis.set_xlabel('Local x (m)'); axis.set_ylabel('Local y (m)')
    axes[0].legend(loc='upper left', fontsize=8)
    axes[0].set_title('Published road kinds')
    axes[1].imshow(np.ma.masked_where(~buffer[::4, ::4], buffer[::4, ::4]), extent=(0, w, h, 0),
                   cmap='Reds', alpha=.4, interpolation='nearest', vmin=0, vmax=1)
    highway = segments[kinds == 2]
    if len(highway):
        mids = (highway[:, :2] + highway[:, 2:]) / 2
        inside = mids[(mids[:, 0] > 100) & (mids[:, 0] < w - 100) & (mids[:, 1] > 100) & (mids[:, 1] < h - 100)]
        if len(inside):
            x, y = inside[len(inside)//2]
            radius = min(600, w / 3)
            axes[1].set_xlim(max(0, x-radius), min(w, x+radius))
            axes[1].set_ylim(min(h, y+radius), max(0, y-radius))
    axes[1].set_title(f'{setback:g} m highway buffer; display sampled every 4 m')
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seed', required=True, type=int)
    parser.add_argument('--samples', required=True, type=int)
    parser.add_argument('--check-gates', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(args.scene, args.output, seed=args.seed, samples=args.samples, check_gates=args.check_gates), ensure_ascii=False))


if __name__ == '__main__': main()
