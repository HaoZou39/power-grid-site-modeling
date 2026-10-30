#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""majority_smooth 分块实现的回归测试：与原整图算法逐位一致，大图显存有界。"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch  # noqa: E402
from segment import _SMOOTH_BLOCK_ROWS, majority_smooth  # noqa: E402

NUM_CLASSES = 6


def _reference_smooth(mask: np.ndarray, num_classes: int, kernel: int, device: str) -> np.ndarray:
    """分块前的整图实现，作为逐位对照。"""
    x = torch.from_numpy(mask.astype(np.int64))
    x = torch.nn.functional.one_hot(x, num_classes=num_classes).permute(2, 0, 1).unsqueeze(0).float()
    x = x.to(device)
    pooled = torch.nn.functional.avg_pool2d(x, kernel_size=kernel, stride=1, padding=kernel // 2)
    return pooled.argmax(dim=1)[0].detach().cpu().numpy().astype(np.uint8)


def _cases():
    rng = np.random.default_rng(7)
    sizes = [
        (1, 1), (1, 5), (3, 3), (70, 50),
        (_SMOOTH_BLOCK_ROWS, 10),
        (_SMOOTH_BLOCK_ROWS + 1, 10),
        (2 * _SMOOTH_BLOCK_ROWS + 3, 8),
    ]
    for shape in sizes:
        yield f"random-{shape[0]}x{shape[1]}", rng.integers(0, NUM_CLASSES, size=shape, dtype=np.uint8)
    # 全同值与两类交替：覆盖平局与一致区域。
    yield "uniform", np.full((37, 41), 2, dtype=np.uint8)
    checker = np.indices((64, 64)).sum(axis=0) % 2
    yield "checker", checker.astype(np.uint8)


class MajoritySmoothTests(unittest.TestCase):
    def test_matches_reference_on_cpu(self):
        for name, mask in _cases():
            with self.subTest(case=name):
                expected = _reference_smooth(mask, NUM_CLASSES, 3, "cpu")
                actual = majority_smooth(mask, NUM_CLASSES, kernel=3, device="cpu")
                np.testing.assert_array_equal(actual, expected)

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA not available")
    def test_matches_reference_on_cuda(self):
        for name, mask in _cases():
            with self.subTest(case=name):
                expected = _reference_smooth(mask, NUM_CLASSES, 3, "cuda:0")
                actual = majority_smooth(mask, NUM_CLASSES, kernel=3, device="cuda:0")
                np.testing.assert_array_equal(actual, expected)

    def test_kernel_passthrough_and_validation(self):
        mask = np.arange(12, dtype=np.uint8).reshape(3, 4) % NUM_CLASSES
        self.assertIs(majority_smooth(mask, NUM_CLASSES, kernel=1), mask)
        self.assertIs(majority_smooth(mask, NUM_CLASSES, kernel=0), mask)
        with self.assertRaises(ValueError):
            majority_smooth(mask, NUM_CLASSES, kernel=2)

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA not available")
    def test_large_mask_peak_memory_is_bounded(self):
        # 20 km 场景的尺寸：原整图实现在此必然 OOM（约 54 GiB），分块必须有界。
        mask = np.zeros((34906, 34906), dtype=np.uint8)
        mask[::7, ::5] = 3
        torch.zeros(1, device="cuda:0")
        torch.cuda.reset_peak_memory_stats(0)
        result = majority_smooth(mask, NUM_CLASSES, kernel=3, device="cuda:0")
        peak = torch.cuda.max_memory_allocated(0) / 2**20
        self.assertEqual(result.shape, mask.shape)
        self.assertLess(peak, 2048, f"peak {peak:.0f} MiB exceeds the 2 GiB budget")
        print(f"\n[INFO] 34906x34906 majority_smooth peak: {peak:.0f} MiB")


if __name__ == "__main__":
    unittest.main()
