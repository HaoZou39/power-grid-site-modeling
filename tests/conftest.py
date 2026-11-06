from __future__ import annotations

import os

import pytest
import torch
from fastapi.testclient import TestClient

from config.project_config import validate_cuda_device
from tests.auth_flags import skip_auto_login

os.environ.setdefault("BOOTSTRAP_ADMIN_USERNAME", "pytest-admin")
os.environ.setdefault("BOOTSTRAP_ADMIN_PASSWORD", "pytest-admin-pass-9f3c")
_original_request = TestClient.request


def _request(self, method, url, **kwargs):
    path = str(url).split("?", 1)[0]
    if (
        not skip_auto_login.get()
        and path.startswith("/api/")
        and (method.upper(), path) not in {("POST", "/api/v1/auth/login"), ("GET", "/api/v1/health")}
    ):
        if "site_session" not in self.cookies:
            token = skip_auto_login.set(True)
            try:
                response = _original_request(
                    self, "POST", "/api/v1/auth/login",
                    json={"username": os.environ["BOOTSTRAP_ADMIN_USERNAME"], "password": os.environ["BOOTSTRAP_ADMIN_PASSWORD"]},
                )
            finally:
                skip_auto_login.reset(token)
            if response.status_code == 200:
                self.csrf_token = response.json()["csrf_token"]
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers = kwargs.get("headers")
            if headers is None:
                headers = {}
                kwargs["headers"] = headers
            if isinstance(headers, dict) and "x-csrf-token" not in {str(key).lower() for key in headers}:
                headers["X-CSRF-Token"] = getattr(self, "csrf_token", "")
    return _original_request(self, method, url, **kwargs)


TestClient.request = _request


@pytest.fixture(autouse=True)
def isolated_scene_root(tmp_path, monkeypatch):
    """Keep unit/API state separate from a running application and its worker lock."""
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))
    monkeypatch.setenv("EXPERIMENT_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("FAVORITES_DB_PATH", str(tmp_path / "favorites.sqlite3"))
    monkeypatch.setenv("AGENT_MEMORY_ROOT", str(tmp_path / "memory"))


@pytest.fixture(scope="session")
def cuda_device() -> torch.device:
    return validate_cuda_device("cuda")



@pytest.fixture(params=["cpu", "cuda"])
def model_device(request) -> torch.device:
    if request.param == "cpu":
        return torch.device("cpu")
    request.getfixturevalue("cuda_device")
    return torch.device("cuda", torch.cuda.current_device())
