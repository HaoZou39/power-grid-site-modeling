"""Validate synthetic DXF classification and optionally inspect an original DWG."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import ezdxf
import numpy as np
from fastapi.testclient import TestClient

from backend.app.main import create_app
from data_tools.cad_tool import read_cad_drawing, rasterize_cad_landuse
from data_tools.scene_coordinates import local_to_projected
from experiments.constraint_mask import DEFAULT_FIELD_COST, compose_hard_mask, policy_from_form


def validate(output: Path, converter: Path, reference: Path | None) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    os.environ["CAD_DWG_CONVERTER"] = str(converter.resolve())
    os.environ["SCENE_ROOT"] = str((output / "scenes").resolve())
    os.environ["EXPERIMENT_OUTPUT_ROOT"] = str((output / "experiments").resolve())
    frame = {"crs": "EPSG:32651", "transform": [1, 0, 222000, 0, -1, 3046000], "width": 20, "height": 20}
    document = ezdxf.new("R2000")
    names = ["building", "field", "road", "water"]
    for name, (x, y) in zip(names, [(2, 2), (8, 2), (2, 8), (8, 8)]):
        document.layers.new(name)
        points = [local_to_projected(frame, a, b) for a, b in [(x, y), (x + 4, y), (x + 4, y + 4), (x, y + 4)]]
        document.modelspace().add_lwpolyline(points, close=True, dxfattribs={"layer": name})
    dxf = output / "synthetic-full.dxf"
    document.saveas(dxf)
    drawing = read_cad_drawing(dxf)
    kinds = {layer["name"]: layer["suggested_kind"] for layer in drawing["layers"]}
    layer, statistics = rasterize_cad_landuse(drawing, frame["crs"], kinds, frame)
    assert [int(layer[y, x]) for x, y in [(4, 4), (10, 4), (4, 10), (10, 10)]] == [2, 1, 3, 5]
    scene = output / "scenes" / "cad-demo"
    scene.mkdir(parents=True)
    arrays = {"dem_1m.npy": np.zeros((20, 20), np.float32), "landuse_1m.npy": np.zeros((20, 20), np.uint8),
              "obstacle_mask_1m.npy": np.zeros((20, 20), np.uint8),
              "road_segments_local.npy": np.array([[0, 0, 20, 0]], np.float32),
              "road_segment_kind.npy": np.zeros(1, np.int8), "road_voronoi_1m.npy": np.zeros((20, 20), np.int64),
              "demand_points.npy": np.array([[15, 15]], np.float32)}
    for name, value in arrays.items():
        np.save(scene / name, value)
    (scene / "data_metadata.json").write_text(json.dumps({"dem": {"reference_crs": frame["crs"],
        "target_transform": frame["transform"], "shape": [20, 20]}, "road": {"n_segments": 1}}))
    client = TestClient(create_app("sqlite://:memory:", "", favorite_db_path=output / "favorites.sqlite3"))
    url = "/api/v1/scenes/cad-demo"
    def successful(response, status=200):
        if response.status_code != status:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text}")
        return response.json()
    cad_id = successful(client.post(url + "/cad-files", files={"file": (dxf.name, dxf.read_bytes())}), 201)["id"]
    successful(client.post(url + f"/cad-files/{cad_id}/inspect"))
    preview = successful(client.post(url + f"/cad-files/{cad_id}/preview", json={"source_crs": frame["crs"], "layer_kinds": kinds}))
    image = client.get(url + f"/cad-files/preview/{preview['token']}.png")
    assert image.status_code == 200
    (output / "cad-preview.png").write_bytes(image.content)
    applied = successful(client.post(url + "/cad-files/confirm", json={"token": preview["token"]}))
    landuse = np.load(scene / "landuse_1m.npy")
    assert landuse[4, 4] == 2 and landuse[4, 10] == 1
    assert compose_hard_mask(landuse, [], policy_from_form({"field_policy": "blocked"}))[4, 10]
    assert not compose_hard_mask(landuse, [], policy_from_form({"field_policy": "allowed"}))[4, 10]
    feasible = client.post(url + "/construction-feasibility-overlay", json={"field_policy": "blocked", "mountain_policy": "allowed",
        "field_cost": DEFAULT_FIELD_COST, "exclusion_zones": [], "feasible_zones": [], "road_setback_m": 0, "water_setback_m": 0})
    assert feasible.status_code == 200, feasible.text
    (output / "construction-feasibility.png").write_bytes(feasible.content)
    successful(client.delete(url + "/cad-landuse"))
    assert not np.load(scene / "landuse_1m.npy").any()
    reference_summary = None
    if reference:
        raw = read_cad_drawing(reference, converter=str(converter.resolve()))
        reference_summary = {"path": str(reference), "sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
                             "layers": raw["layers"], "warnings": raw["warnings"]}
    result = {"status": "passed", "synthetic": True, "synthetic_format": "DXF", "frame": frame, "statistics": statistics,
              "apply_revision": applied["scene_revision"],
              "field_policy_preserved": True, "clear_restored_base": True, "reference_inspection": reference_summary}
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--converter", type=Path, required=True)
    parser.add_argument("--reference-cad", type=Path)
    args = parser.parse_args()
    result = validate(args.output_dir, args.converter, args.reference_cad)
    print(json.dumps({key: result[key] for key in ("status", "synthetic_format", "field_policy_preserved", "clear_restored_base")}))
