from __future__ import annotations

import pytest
import torch

from config.project_config import validate_cuda_device


@pytest.fixture(autouse=True)
def isolated_scene_root(tmp_path, monkeypatch):
    """Keep unit/API state separate from a running application and its worker lock."""
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    monkeypatch.setenv("EXPERIMENT_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("FAVORITES_DB_PATH", str(tmp_path / "favorites.sqlite3"))


@pytest.fixture(scope="session")
def cuda_device() -> torch.device:
    return validate_cuda_device("cuda")



@pytest.fixture(params=["cpu", "cuda"])
def model_device(request) -> torch.device:
    if request.param == "cpu":
        return torch.device("cpu")
    request.getfixturevalue("cuda_device")
    return torch.device("cuda", torch.cuda.current_device())
