"""一次运行的三个 Guided Search 批次。

JSON 里的 `guide_batch_size`、`evaluation_batch_size` 和这里的 `REPORT_BATCH_LIMIT`
只做上限。CUDA 上按足迹窗口和当时剩余显存定一次，之后不再改。
CPU 不查询 CUDA，批次保持上限与候选数的较小值。
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

# 与 modeling/masks.py 的软足迹相同：half_diag = 0.5 * hypot，窗口 = ceil(2 * half_diag) + 4。
# 下面按这个窗口的整幅浮点图计数，不另做矩形面积近似。

# compute_soft_footprint 里每个候选会形成的 float32 图：旋转坐标、绝对值、
# 两个 sigmoid 的输入和输出、权重、采样坐标、两通道 grid，以及 DEM 和障碍的采样结果。
# 这些图不会同时全部活着；按全部计入是故意偏大的包络，不是 profiler 读数。
SOFT_FORWARD_F32_MAPS = 17
# 反向传播保留前向激活，并再写一份同形状梯度。三份一起算，所以引导系数最大。
GUIDE_AUTOGRAD_COPIES = 3
# compute_tensor_hard_footprint：int64 行列、float64 位移和旋转坐标、三张布尔覆盖图。
EVAL_HARD_I64_MAPS = 2
EVAL_HARD_F64_MAPS = 4
EVAL_HARD_BOOL_MAPS = 3
# compute_hard_footprints 逐个候选做 meshgrid。工作区只留一份；每个候选留下的是足迹索引。
REPORT_CPU_F64_MAPS = 6
REPORT_CPU_I64_MAPS = 2
REPORT_CPU_BOOL_MAPS = 2
REPORT_CPU_RETAINED_I64 = 2
# 坐标、原始位姿梯度和目标向量相对足迹图很小，但仍计入，避免只按一个像元估价。
GUIDE_OVERHEAD_BYTES = 64
EVAL_OVERHEAD_BYTES = 128
REPORT_GPU_OVERHEAD_BYTES = 64
REPORT_CPU_OVERHEAD_BYTES = 256

# 剩余显存先扣掉总容量的 25% 和 4 GiB 中的较大者，留给已加载场景之外的距离场和分配器。
GPU_RESERVE_FRACTION = 0.25
GPU_RESERVE_FLOOR_BYTES = 4 * 1024**3
# 报告还要占主机内存。距离场和 DEM 已经在 RAM 里，同样先留 25% 或 8 GiB。
HOST_RESERVE_FRACTION = 0.25
HOST_RESERVE_FLOOR_BYTES = 8 * 1024**3

# 最终报告的历史上限。不是运行中改写的全局批次。
REPORT_BATCH_LIMIT = 8192


@dataclass(frozen=True)
class MemorySnapshot:
    free_bytes: int
    total_bytes: int
    name: str | None = None


@dataclass(frozen=True)
class BatchPlan:
    rect_w_m: float
    rect_h_m: float
    footprint_window: int
    footprint_pixels: int
    device: str
    gpu_name: str | None
    free_gpu_bytes: int | None
    total_gpu_bytes: int | None
    usable_gpu_bytes: int | None
    free_host_bytes: int | None
    usable_host_bytes: int | None
    population: int
    guide_batch_size: int
    evaluation_batch_size: int
    report_batch_size: int
    guide_batch_limit: int
    evaluation_batch_limit: int
    report_batch_limit: int
    bytes_per_candidate: dict[str, int]
    memory_query: str

    def as_record(self) -> dict[str, Any]:
        return {
            "rect_w_m": self.rect_w_m,
            "rect_h_m": self.rect_h_m,
            "footprint_window": self.footprint_window,
            "footprint_pixels": self.footprint_pixels,
            "device": self.device,
            "gpu_name": self.gpu_name,
            "free_gpu_bytes": self.free_gpu_bytes,
            "total_gpu_bytes": self.total_gpu_bytes,
            "usable_gpu_bytes": self.usable_gpu_bytes,
            "free_host_bytes": self.free_host_bytes,
            "usable_host_bytes": self.usable_host_bytes,
            "population": self.population,
            "guide_batch_size": self.guide_batch_size,
            "evaluation_batch_size": self.evaluation_batch_size,
            "report_batch_size": self.report_batch_size,
            "guide_batch_limit": self.guide_batch_limit,
            "evaluation_batch_limit": self.evaluation_batch_limit,
            "report_batch_limit": self.report_batch_limit,
            "bytes_per_candidate": dict(self.bytes_per_candidate),
            "memory_query": self.memory_query,
        }


def footprint_window(rect_w_m: float, rect_h_m: float) -> int:
    """软足迹采样窗口，和 `compute_soft_footprint` 用同一表达式。"""

    if rect_w_m <= 0 or rect_h_m <= 0 or not math.isfinite(rect_w_m) or not math.isfinite(rect_h_m):
        raise ValueError("rectangle dimensions must be positive and finite")
    half_diag = 0.5 * math.sqrt(rect_w_m**2 + rect_h_m**2)
    window = int(math.ceil(2.0 * half_diag)) + 4
    if window < 3:
        raise ValueError("soft footprint window is invalid")
    return window


def stage_bytes(window: int) -> dict[str, int]:
    """每个候选的保守字节数。`report_cpu_workspace` 是逐候选 meshgrid 的一份工作区，不乘批次。"""

    if window < 3:
        raise ValueError("soft footprint window is invalid")
    pixels = window * window
    soft = SOFT_FORWARD_F32_MAPS * 4 * pixels
    return {
        "guide": soft * GUIDE_AUTOGRAD_COPIES + GUIDE_OVERHEAD_BYTES,
        "evaluation": soft + (EVAL_HARD_I64_MAPS * 8 + EVAL_HARD_F64_MAPS * 8 + EVAL_HARD_BOOL_MAPS) * pixels + EVAL_OVERHEAD_BYTES,
        "report_gpu": soft + REPORT_GPU_OVERHEAD_BYTES,
        "report_cpu": REPORT_CPU_RETAINED_I64 * 8 * pixels + REPORT_CPU_OVERHEAD_BYTES,
        "report_cpu_workspace": (REPORT_CPU_F64_MAPS * 8 + REPORT_CPU_I64_MAPS * 8 + REPORT_CPU_BOOL_MAPS) * pixels,
    }


def usable_bytes(snapshot: MemorySnapshot, fraction: float, floor_bytes: int) -> int:
    if snapshot.free_bytes < 0 or snapshot.total_bytes < 1:
        raise ValueError("memory snapshot must have non-negative free bytes and a positive total")
    reserve = max(int(snapshot.total_bytes * fraction), floor_bytes)
    return max(0, snapshot.free_bytes - reserve)


def batch_limits(config: Any) -> tuple[int, int, int]:
    """表单或脚本里的批次只许把 JSON 上限再压低，不能抬过默认值。"""

    from config.project_config import load_default_config

    defaults = load_default_config().guided_search
    guide = min(int(config.guide_batch_size), int(defaults.guide_batch_size))
    evaluation = min(int(config.evaluation_batch_size), int(defaults.evaluation_batch_size))
    return guide, evaluation, REPORT_BATCH_LIMIT


def plan_guided_batches(
    rect_w_m: float,
    rect_h_m: float,
    *,
    population: int,
    guide_limit: int,
    evaluation_limit: int,
    report_limit: int,
    device: Any,
    gpu_memory: Callable[[Any], MemorySnapshot] | None = None,
    host_memory: Callable[[], MemorySnapshot] | None = None,
) -> BatchPlan:
    """定一次三个批次。CUDA 预算放不下一个候选就报错，不用 Batch=1 硬撑。"""

    window = footprint_window(float(rect_w_m), float(rect_h_m))
    costs = stage_bytes(window)
    limits = (int(guide_limit), int(evaluation_limit), int(report_limit))
    if population < 1 or min(limits) < 1:
        raise ValueError("population and batch limits must be positive")
    device_name = str(device)
    common = dict(
        rect_w_m=float(rect_w_m), rect_h_m=float(rect_h_m), footprint_window=window,
        footprint_pixels=window * window, device=device_name, population=int(population),
        guide_batch_limit=limits[0], evaluation_batch_limit=limits[1], report_batch_limit=limits[2],
        bytes_per_candidate=costs,
    )
    kind = getattr(device, "type", device_name)
    if kind == "cpu":
        clipped = tuple(min(limit, population) for limit in limits)
        return BatchPlan(
            gpu_name=None, free_gpu_bytes=None, total_gpu_bytes=None, usable_gpu_bytes=None,
            free_host_bytes=None, usable_host_bytes=None, memory_query="cpu",
            guide_batch_size=clipped[0], evaluation_batch_size=clipped[1], report_batch_size=clipped[2],
            **common,
        )
    if kind != "cuda":
        raise ValueError(f"guided search batch planning supports cpu and cuda, got {device_name}")
    gpu = (gpu_memory or read_cuda_memory)(device)
    host = (host_memory or read_host_memory)()
    gpu_budget = usable_bytes(gpu, GPU_RESERVE_FRACTION, GPU_RESERVE_FLOOR_BYTES)
    host_budget = usable_bytes(host, HOST_RESERVE_FRACTION, HOST_RESERVE_FLOOR_BYTES)
    guide = _fit("guide", limits[0], population, gpu_budget, costs["guide"], window, device_name)
    evaluation = _fit("evaluation", limits[1], population, gpu_budget, costs["evaluation"], window, device_name)
    report_gpu = _fit("report-gpu", limits[2], population, gpu_budget, costs["report_gpu"], window, device_name)
    report_cpu = _fit_report_cpu(limits[2], population, host_budget, costs, window, device_name)
    plan = BatchPlan(
        gpu_name=gpu.name, free_gpu_bytes=int(gpu.free_bytes), total_gpu_bytes=int(gpu.total_bytes),
        usable_gpu_bytes=gpu_budget, free_host_bytes=int(host.free_bytes), usable_host_bytes=host_budget,
        memory_query="cuda", guide_batch_size=guide, evaluation_batch_size=evaluation,
        report_batch_size=min(report_gpu, report_cpu), **common,
    )
    import logging

    logging.getLogger("uvicorn.error").info(
        "guided_search.batch device=%s gpu=%s window=%s free_gpu=%s guide=%s evaluation=%s report=%s",
        plan.device, plan.gpu_name, plan.footprint_window, plan.free_gpu_bytes,
        plan.guide_batch_size, plan.evaluation_batch_size, plan.report_batch_size,
    )
    return plan


def plan_for_problem(problem: Any, modeling: Any, config: Any) -> BatchPlan:
    """场景张量已经在任务设备上之后调用，按那张卡的剩余显存规划。"""

    guide_limit, evaluation_limit, report_limit = batch_limits(config)
    return plan_guided_batches(
        float(modeling.rect_w_m), float(modeling.rect_h_m), population=int(config.popsize),
        guide_limit=guide_limit, evaluation_limit=evaluation_limit, report_limit=report_limit,
        device=problem.dem_tensor.device,
    )


def write_resolved_batch_plan(path: str | Path, record: Mapping[str, Any]) -> None:
    """把本次实际批次写回已经提前保存的 resolved_config。两个配置字段改成实际值。"""

    target = Path(path)
    raw = json.loads(target.read_text(encoding="utf-8"))
    guided = raw["guided_search"]
    guided["guide_batch_size"] = int(record["guide_batch_size"])
    guided["evaluation_batch_size"] = int(record["evaluation_batch_size"])
    raw["batch_plan"] = dict(record)
    target.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_cuda_memory(device: Any) -> MemorySnapshot:
    import torch

    free_bytes, total_bytes = torch.cuda.mem_get_info(device)
    return MemorySnapshot(int(free_bytes), int(total_bytes), torch.cuda.get_device_name(device))


def read_host_memory() -> MemorySnapshot:
    if sys.platform == "win32":
        return _read_windows_host_memory()
    total = available = None
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            total = int(line.split()[1]) * 1024
        elif line.startswith("MemAvailable:"):
            available = int(line.split()[1]) * 1024
    if total is None or available is None:
        raise RuntimeError("MemTotal and MemAvailable are required in /proc/meminfo")
    return MemorySnapshot(available, total)


def _read_windows_host_memory() -> MemorySnapshot:
    import ctypes

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_uint32),
            ("dwMemoryLoad", ctypes.c_uint32),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    query = ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
    query.argtypes = [ctypes.POINTER(MemoryStatusEx)]
    query.restype = ctypes.c_int
    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not query(ctypes.byref(status)):
        raise ctypes.WinError(ctypes.get_last_error())
    # Physical bytes match Linux MemTotal/MemAvailable; pagefile capacity is not a RAM budget.
    return MemorySnapshot(int(status.ullAvailPhys), int(status.ullTotalPhys))


def _fit(stage: str, limit: int, population: int, usable: int, each: int, window: int, device: str) -> int:
    if usable < each:
        raise RuntimeError(
            f"guided search {stage} batch cannot fit one candidate: "
            f"need {each} bytes, usable {usable} bytes, window {window}, device {device}"
        )
    return min(limit, population, usable // each)


def _fit_report_cpu(limit: int, population: int, usable: int, costs: Mapping[str, int], window: int, device: str) -> int:
    each = int(costs["report_cpu"])
    workspace = int(costs["report_cpu_workspace"])
    if usable < workspace + each:
        raise RuntimeError(
            f"guided search report-cpu batch cannot fit one candidate: "
            f"need {workspace + each} bytes, usable {usable} bytes, window {window}, device {device}"
        )
    return min(limit, population, (usable - workspace) // each)
