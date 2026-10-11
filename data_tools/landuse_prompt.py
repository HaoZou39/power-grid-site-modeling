"""Click-prompt segmentation is a replaceable boundary. No model is bundled."""

from __future__ import annotations

from pathlib import Path

import numpy as np


class LandusePrompt:
    """Image click to a local mask. A future model replaces only this class."""

    def mask_at_click(self, image_path: Path, x: float, y: float) -> np.ndarray:
        raise RuntimeError("尚未提供点击分割模型。点选连通区域仍使用 landuse_patch。")


def unavailable_landuse_prompt() -> LandusePrompt:
    return LandusePrompt()
