from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.app.infrastructure.experiment_catalog import ExperimentCatalog
from backend.app.main import create_app


def _write_experiment(root, name: str = "cmaes_demo"):
    output = root / name
    output.mkdir()
    (output / "run_summary.json").write_text(
        json.dumps({"n_runs": 2, "n_feasible": 1, "n_pareto": 1}),
        encoding="utf-8",
    )
    (output / "resolved_config.json").write_text(
        json.dumps({"cma_es": {"algorithm_name": "cma_es"}}),
        encoding="utf-8",
    )
    (output / "pareto_points_map.png").write_bytes(b"png-bytes")
    (output / "pareto_3d_interactive.html").write_text("<html>pareto</html>", encoding="utf-8")
    (output / "solutions.csv").write_text("run_id\n1\n", encoding="utf-8")
    (output / "internal.npy").write_bytes(b"should-not-be-served")
    return output


def test_catalog_lists_only_completed_experiment_directories(tmp_path) -> None:
    _write_experiment(tmp_path)
    (tmp_path / "incomplete").mkdir()
    _write_experiment(tmp_path, ".saving-private")

    experiments = ExperimentCatalog(tmp_path).list_experiments()

    assert [item.id for item in experiments] == ["cmaes_demo"]
    assert experiments[0].algorithm == "cma_es"
    import pytest
    with pytest.raises(FileNotFoundError):
        ExperimentCatalog(tmp_path).get_experiment('.saving-private')
    assert [item.id for item in experiments[0].artifacts] == [
        "pareto_3d_interactive.html",
        "pareto_points_map.png",
        "resolved_config.json",
        "run_summary.json",
        "solutions.csv",
    ]


def test_catalog_rejects_paths_outside_root(tmp_path) -> None:
    _write_experiment(tmp_path)
    catalog = ExperimentCatalog(tmp_path)

    try:
        catalog.get_experiment("../cmaes_demo")
    except FileNotFoundError:
        pass
    else:  # pragma: no cover
        raise AssertionError("path traversal was accepted")


def test_api_exposes_experiment_artifact_urls(tmp_path) -> None:
    output = _write_experiment(tmp_path)

    with TestClient(create_app("sqlite://:memory:", "", experiment_root=tmp_path)) as client:
        response = client.get("/api/v1/experiments")
        assert response.status_code == 200
        item = response.json()[0]
        assert item["id"] == output.name
        assert item["summary"]["n_pareto"] == 1
        assert isinstance(item["modified_at"], str) and item["modified_at"]
        artifact = next(value for value in item["artifacts"] if value["id"] == "pareto_points_map.png")

        image = client.get(artifact["url"])
        assert image.status_code == 200
        assert image.headers["content-type"].startswith("image/png")
        assert image.headers["x-artifact-kind"] == "image"
        assert image.content == b"png-bytes"

        html = client.get(f"/api/v1/experiments/{output.name}/artifacts/pareto_3d_interactive.html")
        assert html.status_code == 200
        assert html.headers["content-type"].startswith("text/html")
        assert "pareto" in html.text

        assert client.get(f"/api/v1/experiments/{output.name}/artifacts/internal.npy").status_code == 404
        assert client.get("/api/v1/experiments/../artifacts/run_summary.json").status_code in {404, 422}


def test_catalog_deletes_only_the_completed_directory(tmp_path) -> None:
    kept = _write_experiment(tmp_path, "keep-me")
    gone = _write_experiment(tmp_path, "remove-me")
    stray = tmp_path / "notes.txt"
    stray.write_text("keep", encoding="utf-8")
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    (incomplete / "solutions.csv").write_text("x\n", encoding="utf-8")

    catalog = ExperimentCatalog(tmp_path)
    catalog.delete_experiment("remove-me")

    assert not gone.exists()
    assert (kept / "run_summary.json").is_file()
    assert stray.read_text(encoding="utf-8") == "keep"
    assert incomplete.is_dir()
    try:
        catalog.delete_experiment("incomplete")
    except FileNotFoundError:
        pass
    else:  # pragma: no cover
        raise AssertionError("incomplete directory was deleted")
    try:
        catalog.delete_experiment("../keep-me")
    except FileNotFoundError:
        pass
    else:  # pragma: no cover
        raise AssertionError("path traversal was accepted")
    assert (kept / "run_summary.json").is_file()


def test_api_deletes_one_experiment_directory(tmp_path) -> None:
    output = _write_experiment(tmp_path)
    kept = _write_experiment(tmp_path, "kept-run")

    with TestClient(create_app("sqlite://:memory:", "", experiment_root=tmp_path)) as client:
        deleted = client.delete(f"/api/v1/experiments/{output.name}")
        assert deleted.status_code == 200
        assert deleted.json() == {"id": output.name, "deleted": True}
        assert not output.exists()
        remaining = client.get("/api/v1/experiments")
        assert remaining.status_code == 200
        assert [item["id"] for item in remaining.json()] == ["kept-run"]
        missing = client.delete(f"/api/v1/experiments/{output.name}")
        assert missing.status_code == 404
        assert (kept / "run_summary.json").is_file()
