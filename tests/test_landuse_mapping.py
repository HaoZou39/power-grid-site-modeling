from __future__ import annotations

import numpy as np
import pytest

from data_tools.landuse_tool import (
    DEFAULT_BUILDABLE_CLASSES,
    DEFAULT_OBSTACLE_CLASSES,
    LANDUSE_CLASS_MAPPING,
    build_landuse_product,
)


def test_landuse_class_mapping_to_obstacle_mask() -> None:
    landuse, obstacle_mask, metadata = build_landuse_product(
        "tests/fixtures/landuse_classes_0_to_5.csv",
        DEFAULT_OBSTACLE_CLASSES,
        expected_shape=(2, 3),
    )

    np.testing.assert_array_equal(landuse, np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int32))
    np.testing.assert_array_equal(obstacle_mask, np.array([[0, 1, 1], [1, 0, 1]], dtype=np.float32))

    assert tuple(metadata["buildable_classes"]) == DEFAULT_BUILDABLE_CLASSES
    assert tuple(metadata["obstacle_classes"]) == DEFAULT_OBSTACLE_CLASSES
    assert metadata["obstacle_mapping"]["mask_value_0"] == "buildable"
    assert metadata["obstacle_mapping"]["mask_value_1"] == "non_buildable"
    assert metadata["landuse_class_mapping"][0]["code"] == "other"
    assert metadata["landuse_class_mapping"][0]["zh"] == "其他区域"
    assert metadata["landuse_class_mapping"][4]["code"] == "mountain_natural"
    assert metadata["landuse_class_mapping"][4]["buildability"] == "buildable"
    assert metadata["landuse_class_mapping"][5]["code"] == "water"
    assert LANDUSE_CLASS_MAPPING[1]["obstacle_mask_value"] == 1


def test_landuse_unknown_class_raises() -> None:
    with pytest.raises(ValueError, match="undefined class"):
        build_landuse_product(
            "tests/fixtures/landuse_unknown_class.csv",
            DEFAULT_OBSTACLE_CLASSES,
            expected_shape=(2, 2),
        )


def test_unknown_obstacle_class_raises() -> None:
    with pytest.raises(ValueError, match="unknown obstacle class"):
        build_landuse_product(
            "tests/fixtures/landuse_classes_0_to_5.csv",
            (1, 2, 6),
            expected_shape=(2, 3),
        )

