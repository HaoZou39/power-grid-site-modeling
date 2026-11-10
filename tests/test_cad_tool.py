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
    with pytest.raises(ValueError, match="未配置 DWG 转换工具"):
        read_cad_drawing(path)


@pytest.mark.parametrize("diagnostics,expected", [
    ("", None),
    ("Warning: Unstable Class object 502 MATERIAL (0x481) 63/0\nWarning: Unstable Class object 505 MLEADERSTYLE (0xfff) 103/0", "样式未完整转换"),
    ("Warning: page_type: 0x7155102a\nERROR: Some section size or address out of bounds", "区域边界可能不完整"),
    ("Warning: unknown conversion issue", "兼容性提示"),
])
def test_dwg_warnings_are_chinese_and_raw_diagnostics_stay_in_logs(tmp_path, monkeypatch, caplog, diagnostics, expected):
    import subprocess
    from data_tools.cad_tool import _dxf_path
    def convert(command, **kwargs):
        Path(command[2]).write_bytes(b"DXF")
        return subprocess.CompletedProcess(command, 0, b"", diagnostics.encode("utf-8"))
    monkeypatch.setattr("data_tools.cad_tool.subprocess.run", convert)
    _, warnings = _dxf_path(tmp_path / "drawing.dwg", tmp_path, "converter")
    if expected is None:
        assert warnings == []
    else:
        assert len(warnings) == 1 and expected in warnings[0]
        assert "Warning:" not in warnings[0] and "0x" not in warnings[0]
        assert diagnostics in caplog.text


@pytest.mark.parametrize("failure", ["exit", "missing_output", "timeout", "unavailable", "parse"])
def test_cad_failures_give_chinese_next_steps_without_raw_exception(tmp_path, monkeypatch, caplog, failure):
    import subprocess
    raw = "English internal converter error"
    def convert(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 120, stderr=raw)
        if failure == "unavailable":
            raise OSError(raw)
        if failure == "parse":
            Path(command[2]).write_bytes(b"DXF")
        return subprocess.CompletedProcess(command, 1 if failure == "exit" else 0, b"", raw.encode("utf-8"))
    def parse(_path):
        raise ValueError(raw)
    monkeypatch.setattr("data_tools.cad_tool.subprocess.run", convert)
    monkeypatch.setattr(ezdxf, "readfile", parse)
    with pytest.raises(ValueError) as error:
        read_cad_drawing(tmp_path / "drawing.dwg", converter="converter")
    assert "DXF" in str(error.value)
    assert raw not in str(error.value)
    assert raw in caplog.text


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


def test_single_layer_feasible_zones_keep_concavity_and_clip(tmp_path):
    from data_tools.cad_tool import cad_feasible_zones
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    def populate(doc):
        doc.layers.new("范围")
        doc.modelspace().add_lwpolyline([(99, 201), (106, 201), (106, 198), (102, 198), (102, 194), (99, 194)],
                                       close=True, dxfattribs={"layer": "范围"})
        doc.modelspace().add_text("说明", dxfattribs={"layer": "0"})
    frame = {**FRAME, "study_domain": {"ring": [[0, 0], [5, 0], [5, 5], [0, 5]]}}
    result = cad_feasible_zones(read_cad_drawing(drawing_file(tmp_path, populate)), "EPSG:3857", frame)
    region = unary_union([Polygon(zone["points"]) for zone in result["feasible_zones"]])
    expected = Polygon([(0, 0), (5, 0), (5, 2), (2, 2), (2, 5), (0, 5)])
    assert region.symmetric_difference(expected).area < 1e-9
    assert result["covered_area_m2"] == pytest.approx(16)


def test_feasible_zones_preserve_holes_and_disconnected_faces():
    from data_tools.cad_tool import cad_feasible_zones
    from shapely.geometry import Polygon, box, mapping
    from shapely.ops import unary_union
    donut = Polygon([(101, 199), (109, 199), (109, 191), (101, 191)],
                    [[(103, 197), (107, 197), (107, 193), (103, 193)]])
    extra = box(111, 191, 113, 193)
    drawing = {"layers": [{"name": "范围", "polygon_count": 2, "open_line_count": 0,
                          "invalid_count": 0, "unsupported_count": 0}],
               "features": [{"layer": "范围", "geometry": mapping(item)} for item in (donut, extra)]}
    frame = {**FRAME, "study_domain": {"ring": [[0, 0], [20, 0], [20, 20], [0, 20]]}}
    result = cad_feasible_zones(drawing, "EPSG:3857", frame)
    region = unary_union([Polygon(zone["points"]) for zone in result["feasible_zones"]])
    assert region.area == pytest.approx(52)
    assert not region.covers(box(4, 4, 6, 6))
    assert region.covers(box(11, 7, 13, 9))
    assert all(not Polygon(zone["points"]).interiors for zone in result["feasible_zones"])


def test_feasible_zones_reject_multiple_geometry_layers(tmp_path):
    from data_tools.cad_tool import cad_feasible_zones
    def populate(doc):
        for name in ("A", "B"):
            doc.layers.new(name)
            doc.modelspace().add_circle((105, 195), 1, dxfattribs={"layer": name})
    with pytest.raises(ValueError, match="一个有效几何图层"):
        cad_feasible_zones(read_cad_drawing(drawing_file(tmp_path, populate)), "EPSG:3857", FRAME)
