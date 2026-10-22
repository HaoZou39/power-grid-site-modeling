from __future__ import annotations

import pytest
import torch

from config.project_config import validate_cuda_device


@pytest.fixture(scope="session")
def cuda_device() -> torch.device:
    return validate_cuda_device("cuda")



@pytest.fixture(params=["cpu", "cuda"])
def model_device(request) -> torch.device:
    if request.param == "cpu":
        return torch.device("cpu")
    request.getfixturevalue("cuda_device")
    return torch.device("cuda", torch.cuda.current_device())
