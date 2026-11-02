"""Independent CAD geometry, layer semantics and known-grid checks."""
from pathlib import Path

import ezdxf
import numpy as np
import pytest
from shapely.geometry import shape

from data_tools.cad_tool import read_cad_drawing, rasterize_cad_landuse, suggest_layer_kind

FRAME = {"crs": "EPSG:3857", "transform": [1, 0, 100, 0, -1, 200], "width": 20, "height": 20}


def drawing_file(tmp_path, populate):
    document = ezdxf.new()
    populate(document)
    path = tmp_path / "drawing.dxf"
    document.saveas(path)
    return path


@pytest.mark.parametrize("name,expected", [("现状建筑轮廓", "building"), ("A-BLDG", "building"), ("农田", "field"),
    ("ROAD_EDGE", "road"), ("water-area", "water"), ("建筑和道路", None), ("苍南分乡镇", None), ("broad-area", None)])
def test_layer_name_suggestions_are_explicit(name, expected):
    assert suggest_layer_kind(name) == expected


def test_blocks_use_transformed_geometry_and_inherit_layer_zero(tmp_path):
    def populate(document):
        document.layers.new("建筑")
        block = document.blocks.new("house")
        block.add_lwpolyline([(0, 0), (2, 0), (2, 2), (0, 2)], close=True)
        document.modelspace().add_blockref("house", (105, 190), dxfattribs={"layer": "建筑", "xscale": 2})
    drawing = read_cad_drawing(drawing_file(tmp_path, populate))
    assert drawing["layers"][0]["suggested_kind"] == "building"
    assert shape(drawing["features"][0]["geometry"]).bounds == (105, 190, 109, 192)
    layer, counts = rasterize_cad_landuse(drawing, "EPSG:3857", {"建筑": "building"}, FRAME)
    assert layer[9, 6] == 2 and layer[1, 1] == -1
    assert counts["cell_counts"]["building"] > 0


def test_linework_only_forms_closed_faces_and_does_not_fill_gaps(tmp_path):
    def populate(document):
        for name in ("buildings", "open-road"):
            document.layers.new(name)
        for a, b in [((102, 192), (104, 192)), ((104, 192), (104, 194)),
                     ((104, 194), (102, 194)), ((102, 194), (102, 192))]:
            document.modelspace().add_line(a, b, dxfattribs={"layer": "buildings"})
        document.modelspace().add_line((110, 190), (112, 190), dxfattribs={"layer": "open-road"})
    drawing = read_cad_drawing(drawing_file(tmp_path, populate))
    layers = {layer["name"]: layer for layer in drawing["layers"]}
    assert layers["buildings"]["polygon_count"] == 1
    assert layers["open-road"]["polygon_count"] == 0
    assert layers["open-road"]["open_line_count"] == 1


def test_hatch_holes_remain_unclassified(tmp_path):
    def populate(document):
        document.layers.new("水体")
        hatch = document.modelspace().add_hatch(dxfattribs={"layer": "水体"})
        hatch.paths.add_polyline_path([(101, 181), (119, 181), (119, 199), (101, 199)], is_closed=True, flags=1)
        hatch.paths.add_polyline_path([(106, 186), (114, 186), (114, 194), (106, 194)], is_closed=True, flags=0)
    drawing = read_cad_drawing(drawing_file(tmp_path, populate))
    layer, _ = rasterize_cad_landuse(drawing, "EPSG:3857", {"水体": "water"}, FRAME)
    assert layer[3, 3] == 5
    assert layer[10, 10] == -1


def test_unknown_layer_and_crs_require_user_mapping(tmp_path):
    path = drawing_file(tmp_path, lambda doc: doc.modelspace().add_lwpolyline([(101, 190), (104, 190), (104, 194)], close=True))
    drawing = read_cad_drawing(path)
    with pytest.raises(ValueError, match="指定用地类别"):
        rasterize_cad_landuse(drawing, "EPSG:3857", {}, FRAME)
    with pytest.raises(ValueError, match="坐标系"):
        rasterize_cad_landuse(drawing, "", {"0": "building"}, FRAME)
    with pytest.raises(ValueError, match="坐标系无效"):
        rasterize_cad_landuse(drawing, "bad-crs", {"0": "building"}, FRAME)
    with pytest.raises(ValueError, match="没有.*可用地物面"):
        rasterize_cad_landuse(drawing, "EPSG:3857", {"0": "ignore"}, FRAME)


def test_wrong_crs_extent_and_invalid_geometry_are_rejected(tmp_path):
    path = drawing_file(tmp_path, lambda doc: doc.modelspace().add_lwpolyline([(1000, 1000), (1001, 1000), (1001, 1001)], close=True))
    with pytest.raises(ValueError, match="相交"):
        rasterize_cad_landuse(read_cad_drawing(path), "EPSG:3857", {"0": "building"}, FRAME)
    path = drawing_file(tmp_path, lambda doc: doc.modelspace().add_lwpolyline([(101, 190), (104, 194), (101, 194), (104, 190)], close=True))
    with pytest.raises(ValueError, match="无效"):
        rasterize_cad_landuse(read_cad_drawing(path), "EPSG:3857", {"0": "building"}, FRAME)


def test_missing_dwg_converter_is_explicit(tmp_path, monkeypatch):
    monkeypatch.delenv("CAD_DWG_CONVERTER", raising=False)
    monkeypatch.setattr("data_tools.cad_tool.shutil.which", lambda _: None)
    path = tmp_path / "drawing.dwg"
    path.write_bytes(b"not parsed")
    with pytest.raises(ValueError, match="CAD_DWG_CONVERTER"):
        read_cad_drawing(path)


def test_clipped_blocks_are_not_imported_as_unclipped_geometry(tmp_path):
    from ezdxf.xclip import XClip
    def populate(document):
        document.layers.new("建筑")
        block = document.blocks.new("house")
        block.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
        insert = document.modelspace().add_blockref("house", (100, 180), dxfattribs={"layer": "建筑"})
        XClip(insert).set_block_clipping_path([(0, 0), (2, 2)])
    drawing = read_cad_drawing(drawing_file(tmp_path, populate))
    assert drawing["layers"][0]["unsupported_count"] == 1
    assert not drawing["features"]
    with pytest.raises(ValueError, match="不支持"):
        rasterize_cad_landuse(drawing, "EPSG:3857", {"建筑": "building"}, FRAME)
