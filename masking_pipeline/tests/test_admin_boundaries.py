#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行政边界提取：无序 outer/inner ways 的环组装。"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extract_admin_boundaries import assemble_rings, build_features, relation_geometry

# 正方形外环拆成两条反向相接的 way，内环一条闭合 way
NODES = {
    1: (120.0, 27.0),
    2: (120.1, 27.0),
    3: (120.1, 27.1),
    4: (120.0, 27.1),
    5: (120.03, 27.03),
    6: (120.06, 27.03),
    7: (120.06, 27.06),
    8: (120.03, 27.06),
}
WAY_REFS = {
    10: [1, 2, 3],
    11: [1, 4, 3],  # 与 10 反方向相接
    12: [5, 6, 7, 8, 5],
    13: [1, 9],  # 断头链，节点 9 不存在于其他 way
}


class AssembleRingsTests(unittest.TestCase):
    def test_reversed_ways_close_ring(self):
        rings, open_chains = assemble_rings([10, 11], WAY_REFS)
        self.assertEqual(open_chains, 0)
        self.assertEqual(len(rings), 1)
        self.assertEqual(rings[0][0], rings[0][-1])
        self.assertEqual(sorted(set(rings[0])), [1, 2, 3, 4])

    def test_open_chain_is_counted_not_returned(self):
        rings, open_chains = assemble_rings([13], WAY_REFS)
        self.assertEqual(rings, [])
        self.assertEqual(open_chains, 1)

    def test_inner_ring_becomes_hole(self):
        relation = (100, {"name": "测试镇", "admin_level": "8"}, [10, 11], [12])
        geom, open_chains = relation_geometry(relation, WAY_REFS, NODES)
        self.assertEqual(open_chains, 0)
        self.assertIsNotNone(geom)
        self.assertEqual(len(geom.geoms), 1)
        poly = geom.geoms[0]
        self.assertEqual(len(poly.interiors), 1)
        self.assertAlmostEqual(poly.area, 0.01 - 0.0009, places=6)

    def test_only_open_chains_returns_none(self):
        relation = (101, {"name": "断头", "admin_level": "8"}, [13], [])
        geom, open_chains = relation_geometry(relation, WAY_REFS, NODES)
        self.assertIsNone(geom)
        self.assertEqual(open_chains, 1)

    def test_partial_relation_is_not_published(self):
        for outer, inner in (([10, 11, 13], []), ([10, 11], [13]), ([10, 11, 99], [])):
            with self.subTest(outer=outer, inner=inner):
                relation = (102, {"name": "残缺", "admin_level": "8"}, outer, inner)
                geom, failures = relation_geometry(relation, WAY_REFS, NODES)
                self.assertIsNone(geom)
                self.assertGreater(failures, 0)

    def test_missing_node_does_not_create_shortcut_edge(self):
        relation = (103, {"admin_level": "8"}, [10, 11], [])
        geom, failures = relation_geometry(relation, WAY_REFS, {k: v for k, v in NODES.items() if k != 2})
        self.assertIsNone(geom)
        self.assertGreater(failures, 0)

    def test_build_features_places_label_inside_polygon_and_outside_hole(self):
        relation = (104, {"name": "带孔镇", "admin_level": "8"}, [10, 11], [12])
        features, stats = build_features([relation], WAY_REFS, NODES, 20)
        from shapely.geometry import shape
        self.assertEqual(stats["built"], 1)
        self.assertTrue(shape(features[0]["geometry"]).contains(shape(features[1]["geometry"])))

    def test_nonpositive_or_nonfinite_tolerance_is_rejected(self):
        for tolerance in (0, -1, float("nan"), float("inf")):
            with self.subTest(tolerance=tolerance), self.assertRaises(ValueError):
                build_features([], {}, {}, tolerance)


if __name__ == "__main__":
    unittest.main()
