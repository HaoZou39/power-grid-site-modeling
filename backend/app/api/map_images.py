"""Bound map textures without changing their geographic extent or model inputs."""

from io import BytesIO
from typing import Any


def bounded_png(content: bytes, max_size_px: int) -> bytes:
    from PIL import Image
    from PIL.PngImagePlugin import PngImageFile

    # Internal scene PNGs may exceed Image.open's limit; keep its global policy unchanged.
    with PngImageFile(BytesIO(content)) as image:
        if max(image.size) <= max_size_px:
            return content
        image.thumbnail((max_size_px, max_size_px), Image.Resampling.NEAREST)
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def study_domain_png(content: bytes, frame: dict[str, Any] | None) -> bytes:
    """Crop a full display-grid PNG to the study domain window. ``None`` frames are not cropped."""

    from PIL import Image
    from PIL.PngImagePlugin import PngImageFile

    from data_tools.display_grid import display_grid

    if frame is None:
        return content
    full = display_grid(frame)
    col, row, width, height = frame["study_domain"]["window"]
    with PngImageFile(BytesIO(content)) as image:
        if image.size != (full["width"], full["height"]):
            raise ValueError(f"map image {image.size} does not match the scene display grid {(full['width'], full['height'])}")
        if (col, row, width, height) == (0, 0, *image.size):
            return content
        output = BytesIO()
        # A same-resolution box resize is an exact crop, without crop's global pixel guard.
        image.resize((width, height), Image.Resampling.NEAREST,
                     box=(col, row, col + width, row + height)).save(output, format="PNG")
        return output.getvalue()
