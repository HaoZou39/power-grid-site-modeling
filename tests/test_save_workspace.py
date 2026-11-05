import json
from dataclasses import replace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from config.project_config import load_default_config
import experiments.launch_site_run as launch
import experiments.save_workspace as saved


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    scene = tmp_path / "scenes" / "demo"
    scene.mkdir(parents=True)
    landuse = np.zeros((32, 32), np.uint8)
    landuse[20:25, 20:25] = 2
    arrays = {
        "landuse_1m": landuse, "obstacle_mask_1m": landuse != 0,
        "dem_1m": np.zeros((32, 32), np.float64),
        "road_segments_local": np.array([[.5, .5, 31.5, .5]]),
        "road_segment_kind": np.zeros(1, np.int8),
        "road_voronoi_1m": np.zeros((32, 32), np.int64),
        "demand_points": np.array([[8., 16.]], np.float32),
    }
    for name, value in arrays.items():
        np.save(scene / f"{name}.npy", value)
    (scene / "data_metadata.json").write_text('{"scene": "demo"}')
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    config = load_default_config()
    monkeypatch.setattr(launch, "load_project_config", lambda _: replace(config, modeling=replace(config.modeling, device="cpu")))
    launch._scored_scene.cache_clear()
    root = tmp_path / "outputs"
    app = create_app("sqlite://:memory:", "", experiment_root=root, favorite_db_path=tmp_path / "favorites.sqlite3")
    body = {
        "name": "  楠溪江 筛选结果  ", "scene_name": "demo", "source_experiment_id": "original-run",
        "rect_w_m": 4, "rect_h_m": 3, "mountain_policy": "allowed", "field_policy": "allowed", "field_cost": .5,
        "road_setback_m": 0, "water_setback_m": 0, "exclusion_zones": [], "feasible_zones": [], "include_demand": False,
        "poses": [
            {"id": "kept", "x": 12, "y": 12, "theta": .2, "pareto_layer": 1},
            {"id": "hidden", "x": 22, "y": 22, "theta": 0, "pareto_layer": 3},
            {"id": "manual-1", "x": 8, "y": 12, "theta": 0, "manual": True, "derived_from": "kept"},
        ],
    }
    with TestClient(app) as client:
        yield client, root, scene, body
    launch._scored_scene.cache_clear()


def test_save_recalculates_and_round_trips_all_retained_poses(workspace):
    client, root, scene, body = workspace
    original = root / "original-run"
    original.mkdir(parents=True)
    (original / "run_summary.json").write_text('{"algorithm":"guided_search"}')
    before = (original / "run_summary.json").read_bytes()
    response = client.post('/api/v1/experiments', json=body)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['name'] == '楠溪江 筛选结果' and result['solution_count'] == 3
    experiment = client.get(f"/api/v1/experiments/{result['id']}").json()
    assert experiment['name'] == result['name'] and experiment['algorithm'] == 'workspace_snapshot'
    artifact = next(a for a in experiment['artifacts'] if a['name'] == 'workspace_solutions.json')
    rows = client.get(artifact['url']).json()['solutions']
    assert [row['id'] for row in rows] == ['kept', 'hidden', 'manual-1']
    assert [row['is_feasible'] for row in rows] == [True, False, True]
    assert rows[0]['theta'] == .2 and rows[1]['pareto_layer'] == 3
    assert rows[2]['manual'] and rows[2]['derived_from'] == 'kept'
    assert all(isinstance(row['dem_soft'], float) for row in rows)
    assert (original / 'run_summary.json').read_bytes() == before
    assert json.loads((root / result['id'] / 'site_form_snapshot.json').read_text())['road_setback_m'] == 0
    again = client.post('/api/v1/experiments', json=body).json()
    assert again['id'] != result['id']
    assert client.delete(f"/api/v1/experiments/{result['id']}").status_code == 200
    assert original.is_dir() and (root / again['id']).is_dir()


@pytest.mark.parametrize('damage', ['empty', 'duplicate', 'nan', 'blank', 'control'])
def test_invalid_workspace_is_rejected_without_outputs(workspace, damage):
    client, root, _, body = workspace
    if damage == 'empty':
        body['poses'] = []
    elif damage == 'duplicate':
        body['poses'][1]['id'] = body['poses'][0]['id']
    elif damage == 'nan':
        body['poses'][0]['x'] = 'NaN'
    else:
        body['name'] = '   ' if damage == 'blank' else 'name\nother'
    assert client.post('/api/v1/experiments', json=body).status_code == 422
    assert not any(p.name != "user-state" for p in root.iterdir())


def test_display_name_cannot_control_the_saved_path(workspace):
    client, root, _, body = workspace
    body['name'] = '../自定义名称'
    response = client.post('/api/v1/experiments', json=body)
    assert response.status_code == 201
    result = response.json()
    assert result['id'].startswith('saved-') and (root / result['id']).parent == root
    assert client.get('/api/v1/experiments').json()[0]['name'] == body['name']


@pytest.mark.parametrize('failure', ['write', 'publish'])
def test_failed_save_leaves_no_partial_case(workspace, monkeypatch, failure):
    client, root, _, body = workspace
    def reject(*args, **kwargs):
        raise OSError('injected publication error')
    if failure == 'write':
        monkeypatch.setattr(saved, 'write_csv', reject)
    else:
        monkeypatch.setattr(saved.Path, 'rename', reject)
    assert client.post('/api/v1/experiments', json=body).status_code == 500
    assert not any(p.name != "user-state" for p in root.iterdir())
    assert client.get('/api/v1/experiments').json() == []


def test_changing_scene_during_evaluation_rejects_save(workspace, monkeypatch):
    client, root, scene, body = workspace
    evaluate = saved.evaluate_form_poses
    def change_scene(*args):
        rows = evaluate(*args)
        path = scene / 'landuse_1m.npy'
        np.save(path, np.load(path))
        return rows
    monkeypatch.setattr(saved, 'evaluate_form_poses', change_scene)
    response = client.post('/api/v1/experiments', json=body)
    assert response.status_code == 422 and '场景数据已变化' in response.text
    assert not any(p.name != "user-state" for p in root.iterdir())


def test_busy_scene_rejects_save(workspace, monkeypatch):
    client, root, _, body = workspace
    monkeypatch.setattr(client.app.state.job_service.repository, 'active_scene_names', lambda: {'demo'})
    assert client.post('/api/v1/experiments', json=body).status_code == 409
    assert not any(p.name != "user-state" for p in root.iterdir())


def test_save_recomputes_current_front_but_preserves_historical_layers(workspace, monkeypatch):
    client, root, _, body = workspace
    values = [(8,8,8), (1,1,1), (0,0,0)]
    def measured(*args):
        return [{"dem_soft":a, "offroad_haul_m":b, "haul_rise_m":c, "is_feasible":True}
                for a,b,c in values]
    monkeypatch.setattr(saved, "evaluate_form_poses", measured)
    result = client.post('/api/v1/experiments', json=body)
    assert result.status_code == 201, result.text
    directory = root/result.json()["id"]
    rows = json.loads((directory/"workspace_solutions.json").read_text())["solutions"]
    assert [row["pareto_layer"] for row in rows] == [1,3,1]
    assert [row["is_pareto"] for row in rows] == [False,True,False]
    assert json.loads((directory/"run_summary.json").read_text())["n_pareto"] == 1


def _scene_version(scene):
    from experiments.scene_version import scene_data_version

    metadata = {
        "scene": "demo", "scene_revision": "rev-fast-1",
        "dem": {"shape": [32, 32], "target_transform": [1.0, 0.0, 0.0, 0.0, -1.0, 32.0], "reference_crs": "EPSG:32651"},
    }
    (scene / "data_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return scene_data_version(scene)


def _auto_source(root, scene, body, experiment_id="original-run", **summary_extra):
    version = _scene_version(scene)
    directory = root / experiment_id
    directory.mkdir()
    precise = "1.2345678901234567"
    header = ["run_id", "x", "y", "theta", "dem_soft", "obstacle_soft", "road_distance", "demand_distance",
              "offroad_haul_m", "haul_rise_m", "obstacle_hard_count", "is_feasible"]
    population = [
        ["a", "12.5", "12.25", "0.2", precise, "0.1", "4", "5", "10", "1", "0", "True"],
        ["b", "14", "15", "0.3", "2.5", "0.1", "4", "5", "11", "2", "0", "True"],
        ["c", "16", "17", "0.4", "3.5", "0.1", "4", "5", "12", "3", "0", "True"],
        ["d", "18", "19", "0.5", "4.5", "0.1", "4", "5", "13", "4", "0", "True"],
    ]
    _write_table(directory / "solutions.csv", header, population)
    _write_table(directory / "pareto_solutions.csv", header, population[:1])
    snapshot = {
        "experiment_name": "demo_变电站_4×3m_20261105-120000",
        "scene_name": body["scene_name"], "rect_w_m": body["rect_w_m"], "rect_h_m": body["rect_h_m"],
        "mountain_policy": body["mountain_policy"], "field_policy": body["field_policy"], "field_cost": body["field_cost"],
        "exclusion_zones": body["exclusion_zones"], "feasible_zones": body["feasible_zones"],
        "include_demand": body["include_demand"], "diagonal_access": True,
        "road_setback_m": body["road_setback_m"], "water_setback_m": body["water_setback_m"], "highway_setback_m": 30,
        "max_elevation_m": None,
    }
    (directory / "site_form_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (directory / "resolved_config.json").write_text(json.dumps({"modeling": {
        "rect_w_m": body["rect_w_m"], "rect_h_m": body["rect_h_m"],
        "road_setback_m": body["road_setback_m"], "water_setback_m": body["water_setback_m"], "highway_setback_m": 30,
    }}), encoding="utf-8")
    (directory / "data_metadata.json").write_text(json.dumps({"data_version": version}), encoding="utf-8")
    summary = {
        "algorithm": "guided_search", "result_origin": "auto", "problem_type": "site",
        "scene_name": "demo", "display_name": experiment_id, "is_case": False,
    }
    summary.update(summary_extra)
    (directory / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return directory, precise


def _write_table(path, header, rows):
    import csv
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def _fast_body(body):
    poses = [
        {"id": "a", "x": 12.5, "y": 12.25, "theta": 0.2, "manual": False, "pareto_layer": 1},
        {"id": "b", "x": 14, "y": 15, "theta": 0.3, "manual": False, "pareto_layer": 2},
        {"id": "c", "x": 16, "y": 17, "theta": 0.4, "manual": False, "pareto_layer": 3},
    ]
    return {**body, "highway_setback_m": 30, "diagonal_access": True, "source_experiment_id": "original-run",
            "fast_save_source_experiment_id": "original-run", "poses": poses}


def _watch_evaluation(monkeypatch, block_scene=False):
    import algorithms.common.pareto as pareto_module

    calls = {"evaluate": 0, "pareto": 0, "scene": 0, "field": 0}
    real_evaluate = saved.evaluate_form_poses
    real_pareto = pareto_module.extract_feasible_pareto_front
    real_scene = launch.constrained_problem
    real_field = launch._shared_haul_field

    def evaluate(*args, **kwargs):
        calls["evaluate"] += 1
        return real_evaluate(*args, **kwargs)

    def pareto(*args, **kwargs):
        calls["pareto"] += 1
        return real_pareto(*args, **kwargs)

    def scene(*args, **kwargs):
        calls["scene"] += 1
        if block_scene:
            raise AssertionError("scene load")
        return real_scene(*args, **kwargs)

    def field(*args, **kwargs):
        calls["field"] += 1
        if block_scene:
            raise AssertionError("haul field")
        return real_field(*args, **kwargs)

    monkeypatch.setattr(saved, "evaluate_form_poses", evaluate)
    monkeypatch.setattr(pareto_module, "extract_feasible_pareto_front", pareto)
    monkeypatch.setattr(launch, "constrained_problem", scene)
    monkeypatch.setattr(launch, "_shared_haul_field", field)
    return calls


def test_unmodified_auto_result_fast_saves_full_precision_layers(workspace, monkeypatch, caplog):
    import logging
    client, root, scene, body = workspace
    directory, precise = _auto_source(root, scene, body)
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    calls = _watch_evaluation(monkeypatch, block_scene=True)
    caplog.set_level(logging.INFO, logger="site-modeling.fast-save")
    response = client.post("/api/v1/experiments", json=_fast_body(body))
    assert response.status_code == 201, response.text
    saved_id = response.json()["id"]
    assert saved_id.startswith("saved-") and saved_id != "original-run"
    assert calls == {"evaluate": 0, "pareto": 0, "scene": 0, "field": 0}
    case = root / saved_id
    rows = json.loads((case / "workspace_solutions.json").read_text())["solutions"]
    assert [row["id"] for row in rows] == ["a", "b", "c"]
    assert [row["pareto_layer"] for row in rows] == [1, 2, 3]
    assert [row["is_pareto"] for row in rows] == [True, False, False]
    assert rows[0]["dem_soft"] == float(precise) and rows[0]["dem_soft"] != round(float(precise), 3)
    assert [row["is_feasible"] for row in rows] == [True, True, True]
    assert (rows[0]["x"], rows[0]["y"], rows[0]["theta"]) == (12.5, 12.25, 0.2)
    assert json.loads((case / "workspace_solutions.json").read_text())["format"] == "workspace-solutions-v1"
    pareto = (case / "pareto_solutions.csv").read_text()
    assert "\na," in f"\n{pareto}" and "\nb," not in f"\n{pareto}" and "\nc," not in f"\n{pareto}"
    assert "\nd," not in (case / "solutions.csv").read_text()
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before
    record = " ".join(caplog.messages)
    assert "fast_save=hit" in record and "evaluate_s=0.000000" in record and "pareto_s=0.000000" in record
    experiment = client.get(f"/api/v1/experiments/{saved_id}").json()
    artifact = next(item for item in experiment["artifacts"] if item["name"] == "workspace_solutions.json")
    reloaded = client.get(artifact["url"]).json()["solutions"]
    assert [(row["id"], row["pareto_layer"], row["is_feasible"], row["dem_soft"]) for row in reloaded] == [
        ("a", 1, True, float(precise)), ("b", 2, True, 2.5), ("c", 3, True, 3.5),
    ]


@pytest.mark.parametrize("change", ["move", "resize", "delete", "add", "rotate", "derived", "refine", "manual", "missing", "revision", "forged"])
def test_fast_save_falls_back_unless_the_source_still_matches(workspace, monkeypatch, change):
    client, root, scene, body = workspace
    directory, _ = _auto_source(root, scene, body)
    calls = _watch_evaluation(monkeypatch)
    payload = _fast_body(body)
    if change == "move":
        payload["poses"][0]["x"] = 13.5
    elif change == "resize":
        payload["rect_w_m"] = 8
    elif change == "delete":
        payload["poses"] = payload["poses"][:2]
    elif change == "add":
        payload["poses"].append({"id": "extra", "x": 6, "y": 6, "theta": 0, "manual": False, "pareto_layer": 1})
    elif change == "rotate":
        payload["poses"][0]["theta"] = 1.2
    elif change == "derived":
        payload["poses"][0]["derived_from"] = "b"
    elif change == "refine":
        summary = json.loads((directory / "run_summary.json").read_text())
        summary["display_name"] = "demo_局部优化_20261105"
        (directory / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    elif change == "manual":
        summary = json.loads((directory / "run_summary.json").read_text())
        summary.update({"algorithm": "workspace_snapshot", "is_case": True, "result_origin": "manual"})
        (directory / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    elif change == "missing":
        (directory / "pareto_solutions.csv").unlink()
    elif change == "revision":
        metadata = json.loads((scene / "data_metadata.json").read_text())
        metadata["scene_revision"] = "rev-changed"
        (scene / "data_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    elif change == "forged":
        payload["source_experiment_id"] = "other-run"
        payload["fast_save_source_experiment_id"] = "original-run"
    response = client.post("/api/v1/experiments", json=payload)
    assert response.status_code == 201, response.text
    assert calls["evaluate"] == 1 and calls["pareto"] == 1
    assert response.json()["id"] != "original-run"
    assert not any(path.name.startswith(".saving-") for path in root.iterdir())


def test_fast_save_write_failure_leaves_no_case(workspace, monkeypatch):
    client, root, scene, body = workspace
    directory, _ = _auto_source(root, scene, body)
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    calls = _watch_evaluation(monkeypatch)

    def reject(*args, **kwargs):
        raise OSError("injected publication error")

    monkeypatch.setattr("experiments.output_writer.write_csv", reject)
    assert client.post("/api/v1/experiments", json=_fast_body(body)).status_code == 500
    assert calls["evaluate"] == 0 and calls["pareto"] == 0
    visible = [path.name for path in root.iterdir() if path.name != "user-state" and not path.name.startswith(".")]
    assert visible == ["original-run"]
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before
