"""Test worker process. The production optimizer is replaced only at the search call."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from algorithms.routing.types import RoutingResult


def _gate() -> Path:
    return Path(os.environ["P2H2_GATE_DIR"])


def _write(event: str, **fields: object) -> None:
    path = _gate() / "events.jsonl"
    row = {"event": event, "pid": os.getpid(), "t": time.time(), **fields}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _hold(reporter, marker: str) -> None:
    gate = _gate()
    _write("enter", marker=marker)
    try:
        while (gate / "hold").is_file() and not (gate / "release").is_file():
            if reporter is not None:
                reporter(0.5, "search", "p2h2-hold")
            time.sleep(0.05)
    finally:
        _write("exit", marker=marker)


def _site_result():
    return type("Result", (), {
        "solutions": [], "normalization": {}, "objective_names": ("dem_soft", "road_distance", "demand_distance"),
    })()


def install_standin() -> None:
    def site_search(_problem, *args, **_kwargs):
        reporter = next((arg for arg in args if callable(arg)), None)
        _hold(reporter, "site")
        return _site_result()

    def route_search(_problem, _config, reporter):
        _hold(reporter, "routing")
        return RoutingResult([], [], [], 0, 0, 0, 0, [], "stub", 0, 0, {"devices": ["cpu"]})

    import algorithms.guided_search.search as site_search_module
    import algorithms.routing.search as routing_search_module

    site_search_module.run_guided_search = site_search
    routing_search_module.routing_search = route_search


def main() -> None:
    gate = _gate()
    gate.mkdir(parents=True, exist_ok=True)
    (gate / "worker.pid").write_text(str(os.getpid()), encoding="utf-8")
    install_standin()
    from worker.main import run_forever

    run_forever()


if __name__ == "__main__":
    main()
