from io import BytesIO

from PIL import Image

from backend.app.api.map_images import bounded_png, study_domain_png


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


def test_map_image_above_pillow_bomb_limit_is_still_downscaled(monkeypatch):
    # 18 km 场景图层约 3.4 亿像素，超过 Pillow 默认上限。这里把上限调小来模拟。
    with monkeypatch.context() as settings:
        settings.setattr(Image, "MAX_IMAGE_PIXELS", 100)
        content = bounded_png(_png((90, 45)), 40)
        assert Image.MAX_IMAGE_PIXELS == 100
    image = Image.open(BytesIO(content))
    assert image.size == (40, 20)


def test_small_map_png_keeps_original_bytes():
    content = _png((8, 4))
    assert bounded_png(content, 40) is content


def test_study_domain_crop_supports_large_png_without_changing_global_limit(monkeypatch):
    monkeypatch.setattr("data_tools.display_grid.display_grid", lambda frame: {"width": 90, "height": 45})
    image = Image.new("RGBA", (90, 45), (170, 50, 145, 192))
    image.putpixel((10, 5), (255, 0, 0, 255))
    source = BytesIO()
    image.save(source, format="PNG")
    with monkeypatch.context() as settings:
        settings.setattr(Image, "MAX_IMAGE_PIXELS", 100)
        content = study_domain_png(source.getvalue(), {"study_domain": {"window": [10, 5, 50, 20]}})
        assert Image.MAX_IMAGE_PIXELS == 100
    with Image.open(BytesIO(content)) as image:
        assert image.size == (50, 20)
        assert image.getpixel((0, 0)) == (255, 0, 0, 255)
        assert image.getpixel((49, 19)) == (170, 50, 145, 192)
