"""Bound map textures without changing their geographic extent or model inputs."""

from io import BytesIO
from typing import Any


def bounded_png(content: bytes, max_size_px: int) -> bytes:
    from PIL import Image

    # 图层 PNG 是本项目自己生成的。18 km 场景约 3.4 亿像素，超过 Pillow 默认的防护上限（约 1.8 亿）会直接报错。
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(BytesIO(content)) as image:
        if max(image.size) <= max_size_px:
            return content
        image.thumbnail((max_size_px, max_size_px), Image.Resampling.NEAREST)
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def study_domain_png(content: bytes, frame: dict[str, Any] | None) -> bytes:
    """Crop a full display-grid PNG to the study domain window. ``None`` frames are not cropped."""

    from PIL import Image

    from data_tools.display_grid import display_grid

    if frame is None:
        return content
    full = display_grid(frame)
    col, row, width, height = frame["study_domain"]["window"]
    with Image.open(BytesIO(content)) as image:
        if image.size != (full["width"], full["height"]):
            raise ValueError(f"map image {image.size} does not match the scene display grid {(full['width'], full['height'])}")
        if (col, row, width, height) == (0, 0, *image.size):
            return content
        output = BytesIO()
        image.crop((col, row, col + width, row + height)).save(output, format="PNG")
        return output.getvalue()
