"""One real worker. It does not replace the site or routing search."""

from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> None:
    visible = os.environ["CUDA_VISIBLE_DEVICES"]
    probe_dir = Path(os.environ["P2I_PROBE_DIR"])
    probe_dir.mkdir(parents=True, exist_ok=True)
    (probe_dir / "worker.pid").write_text(str(os.getpid()), encoding="utf-8")
    import torch

    available = bool(torch.cuda.is_available())
    count = int(torch.cuda.device_count()) if available else 0
    properties = torch.cuda.get_device_properties(0) if count == 1 else None
    probe = {
        "cuda_visible_devices": visible,
        "available": available,
        "device_count": count,
        "name": None if properties is None else torch.cuda.get_device_name(0),
        "uuid": None if properties is None else str(getattr(properties, "uuid", "")),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
    }
    (probe_dir / "gpu_probe.json").write_text(json.dumps(probe), encoding="utf-8")
    if not available or count != 1:
        raise SystemExit("这次 Worker 没有恰好一张可见的 CUDA 设备")
    from worker.main import run_forever

    run_forever()


if __name__ == "__main__":
    main()
