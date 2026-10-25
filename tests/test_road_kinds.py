"""Access contacts use ordinary edges while transport retains the complete network."""
import json
import numpy as np
import pytest
from config.project_config import load_default_config
from data_tools.traffic_tool import RoadLine, road_segment_kind, _topology_simplified_segments, build_road_product
from modeling.haul_field import build_haul_field, query_exact, query_route
from modeling.context import highway_building_buffer


def test_classification_precedence_and_alignment():
    rules = load_default_config().data.road_kind_rules
    assert road_segment_kind({'class': '高速', 'road_detai': '其他路', 'tunnel': 'yes'}, rules) == 3
    assert road_segment_kind({'class': '高速', 'road_detai': '其他路'}, rules) == 2
    assert road_segment_kind({'road_detai': '其他路'}, rules) == 1
    assert road_segment_kind({'highway': 'motorway_link'}, rules) == 1
    assert road_segment_kind({'highway': 'motorway'}, rules) == 2
    assert road_segment_kind({'highway': 'residential', 'tunnel': 'no'}, rules) == 0
    lines = [RoadLine(str(k), 0, np.array([[0, k], [1, k], [2, k]], float), 0, k) for k in range(4)]
    segments, kinds, _ = _topology_simplified_segments(lines, .1)
    np.testing.assert_array_equal(kinds, [0, 1, 2, 3])
    np.testing.assert_array_equal(segments[:, 1], kinds)


def test_contacts_are_access_only_and_transport_uses_highway():
    # Ordinary horizontal road joins a ramp then a highway; origin intentionally on highway.
    segments = np.array([[1.5, 10.5, 15.5, 10.5], [1.5, 10.5, 1.5, 2.5], [1.5, 2.5, 15.5, 2.5]])
    kinds = np.array([0, 1, 2], np.int8)
    field = build_haul_field(np.zeros((18, 18)), np.ones((18, 18), bool), segments,
                             (15.5, 2.5), diagonal=True, segment_kinds=kinds)
    assert np.all(kinds[field.gate_contact_edges] == 0)
    route = query_route(field, (14.5, 8.5))
    assert kinds[route['road_segment_id']] == 0
    assert route['road_haul_m'] > 20
    assert route['offroad_haul_m'] >= 2
    assert not field.reachable[2, 10]
    # Adjacent highway must never steal projection from the explicit ordinary edge.
    close = np.array([[.2, 1.2, 9.2, 1.2], [1.2, 1.8, 8.2, 1.8], [.2, 1.2, 1.2, 1.8]])
    close_field = build_haul_field(np.zeros((10, 10)), np.ones((10, 10), bool), close,
                                  (8.2, 1.8), segment_kinds=np.array([0, 2, 1], np.int8))
    assert query_route(close_field, (7.5, 1.75))['road_segment_id'] == 0


def test_surface_blocks_access_but_tunnel_does_not():
    segments = np.array([[.5, .5, 14.5, .5], [.5, 6.5, 14.5, 6.5]])
    dem = np.zeros((15, 15)); walkable = np.ones_like(dem, bool)
    surface = build_haul_field(dem, walkable, segments, segment_kinds=np.array([0, 2], np.int8))
    tunnel = build_haul_field(dem, walkable, segments, segment_kinds=np.array([0, 3], np.int8))
    assert query_exact(surface, np.array([[7.5, 12.5]]))[1][0] == 1
    assert query_exact(tunnel, np.array([[7.5, 12.5]]))[1][0] == 0
    assert not tunnel.road_cells[6, 7]


def test_highway_setback_only_surface_segments():
    segments = np.array([[40.5, .5, 40.5, 89.5], [80.5, .5, 80.5, 89.5]])
    buffer = highway_building_buffer(segments, np.array([2, 3], np.int8), (90, 90), 30)
    assert buffer[45, 10] and buffer[45, 70]
    assert not buffer[45, 9] and not buffer[45, 80]


def test_voronoi_labels_are_full_array_indices_of_access_only(tmp_path):
    from pyproj import Transformer
    inverse = Transformer.from_crs(3857, 4326, always_xy=True)
    features = []
    for y, properties in [(199, {'highway': 'motorway'}), (191, {'highway': 'residential'})]:
        points = [inverse.transform(x, y) for x in [100, 114]]
        features.append({'type': 'Feature', 'properties': properties, 'geometry': {'type': 'LineString', 'coordinates': points}})
    source = tmp_path / 'roads.geojson'
    source.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}))
    segments, labels, kinds, metadata = build_road_product(source, tmp_path / 'road_segments_local.npy', tmp_path / 'road_voronoi_1m.npy',
        None, (12, 14), 0, reference_frame={'height': 12, 'width': 14, 'crs': 'EPSG:3857', 'transform': [1, 0, 100, 0, -1, 200]},
        voronoi_backend='cpu')
    np.testing.assert_array_equal(kinds, [2, 0])
    assert labels.dtype == np.int64
    assert np.all(labels == 1)
    assert np.all(kinds[labels] == 0)
    np.testing.assert_array_equal(np.load(tmp_path / 'road_segment_kind.npy'), kinds)
    from experiments.scene_store import _validate_road_arrays
    _validate_road_arrays(segments, labels, (12, 14), kinds)
    with pytest.raises(ValueError, match='access roads'):
        _validate_road_arrays(segments, np.zeros_like(labels), (12, 14), kinds)


def test_non_access_roads_in_outer_buffer_do_not_require_grid_crossing():
    segments = np.array([[.5, .5, 9.5, .5], [50, .5, 50, 9.5], [51, .5, 51, 9.5]])
    kinds = np.array([0, 2, 1], np.int8)
    assert not highway_building_buffer(segments, kinds, (10, 10), 30).any()
    field = build_haul_field(np.zeros((10, 10)), np.ones((10, 10), bool), segments, segment_kinds=kinds)
    assert field.reachable_gate_count > 0
    assert np.all(kinds[field.gate_contact_edges] == 0)


def test_highway_outside_scene_still_imposes_setback_at_boundary():
    segments = np.array([[11.5, .5, 11.5, 9.5]])
    buffer = highway_building_buffer(segments, np.array([2], np.int8), (10, 10), 3)
    assert buffer[5, 9] and buffer[5, 8]
    assert not buffer[5, 7]
