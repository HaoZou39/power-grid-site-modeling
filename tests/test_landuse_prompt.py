"""The prompt segmentation boundary stays explicit until a model is supplied."""

from pathlib import Path

import pytest

from data_tools.landuse_prompt import unavailable_landuse_prompt
from experiments.landuse_patch import connected_class_ring
import numpy as np


def test_prompt_model_is_refused_until_one_is_supplied() -> None:
    prompt = unavailable_landuse_prompt()
    with pytest.raises(RuntimeError, match="尚未提供点击分割模型"):
        prompt.mask_at_click(Path("image.tif"), 1.0, 1.0)


def test_connected_patch_still_works_without_a_prompt_model() -> None:
    landuse = np.array([[1, 1, 2]], dtype=np.int32)
    patch = connected_class_ring(landuse, 0.2, 0.2)
    assert patch["cell_count"] == 2
    assert patch["class_id"] == 1
