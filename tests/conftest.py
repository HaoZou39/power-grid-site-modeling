from __future__ import annotations

import pytest
import torch

from config.project_config import validate_cuda_device


@pytest.fixture(scope="session")
def cuda_device() -> torch.device:
    return validate_cuda_device("cuda")

