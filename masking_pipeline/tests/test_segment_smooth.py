#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

import numpy as np
import torch

from segment import majority_smooth


def _whole_image_smooth(mask, num_classes, kernel):
    """The previous one-shot implementation, kept as the reference result."""
    x = torch.from_numpy(mask.astype(np.int64))
    x = torch.nn.functional.one_hot(x, num_classes=num_classes).permute(2, 0, 1).unsqueeze(0).float()
    pooled = torch.nn.functional.avg_pool2d(x, kernel_size=kernel, stride=1, padding=kernel // 2)
    return pooled.argmax(dim=1)[0].numpy().astype(np.uint8)


class MajoritySmoothTest(unittest.TestCase):
    def test_row_chunks_match_whole_image(self):
        rng = np.random.default_rng(0)
        for h, w, kernel, chunk_rows in [(1, 1, 3, 512), (37, 53, 3, 5), (100, 80, 5, 7), (64, 64, 3, 1)]:
            blocks = rng.integers(0, 6, size=(h // 8 + 1, w // 8 + 1)).repeat(8, 0).repeat(8, 1)[:h, :w]
            noise = rng.random((h, w)) < 0.2
            mask = np.where(noise, rng.integers(0, 6, size=(h, w)), blocks).astype(np.uint8)
            expected = _whole_image_smooth(mask, 6, kernel)
            actual = majority_smooth(mask, 6, kernel, chunk_rows=chunk_rows)
            np.testing.assert_array_equal(actual, expected, err_msg=f"{h}x{w} k={kernel} chunk={chunk_rows}")

    def test_rejects_class_outside_range(self):
        with self.assertRaises(ValueError):
            majority_smooth(np.array([[0, 6]], dtype=np.uint8), 6)


if __name__ == "__main__":
    unittest.main()
