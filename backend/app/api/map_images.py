"""Bound map textures without changing their geographic extent or model inputs."""

from io import BytesIO


def bounded_png(content: bytes, max_size_px: int) -> bytes:
    from PIL import Image

    with Image.open(BytesIO(content)) as image:
        if max(image.size) <= max_size_px:
            return content
        image.thumbnail((max_size_px, max_size_px), Image.Resampling.NEAREST)
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
