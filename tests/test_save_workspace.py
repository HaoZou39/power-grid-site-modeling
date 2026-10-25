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
