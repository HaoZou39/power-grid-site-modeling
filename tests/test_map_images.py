from io import BytesIO

from PIL import Image

from backend.app.api.map_images import bounded_png


def _png(size):
    image = Image.new("RGBA", size, (170, 50, 145, 192))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_large_map_image_fits_texture_limit_and_keeps_extent_and_alpha():
    image = Image.open(BytesIO(bounded_png(_png((90, 45)), 40)))
    assert image.size == (40, 20)
    assert image.getpixel((0, 0)) == (170, 50, 145, 192)
    assert image.getpixel((39, 19)) == (170, 50, 145, 192)


def test_small_map_png_keeps_original_bytes():
    content = _png((8, 4))
    assert bounded_png(content, 40) is content
