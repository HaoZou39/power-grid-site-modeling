"""Schema and validation for the siting plugins. Does not start an optimizer."""

from backend.app.application.registry import build_registry
from backend.app.application.service import JobService
from backend.app.infrastructure.queue import InMemoryTaskQueue
from backend.app.infrastructure.repository import SQLiteJobRepository


def _valid_cma_config() -> dict:
    return {
        "experiment_name": "cmaes-ui",
        "seed": 123,
        "rect_w_m": 80,
        "rect_h_m": 50,
        "demand_on_buildable_only": False,
        "target_resolution_m": 1,
        "objective_weights": {"dem_soft": 0.2, "road_distance": 0.3, "demand_distance": 0.5},
        "popsize": 8,
        "sigma0": 1,
        "max_iters": 40,
        "restarts_per_weight": 1,
        "device": "cuda",
        "overwrite_existing": False,
    }


def test_registry_includes_siting_plugins_beside_demo() -> None:
    ids = [spec.id for spec in build_registry().list_specs()]
    assert ids == [
        "demo.algorithm",
        "site.cma_es",
        "site.guided_search",
        "site.multistart_adam",
        "site.prepare_scene",
    ]


def test_cma_schema_exposes_decision_fields_for_the_form() -> None:
    spec = next(item for item in build_registry().list_specs() if item.id == "site.cma_es")
    properties = spec.config_schema["properties"]
    assert properties["rect_w_m"]["x-unit"] == "m"
    assert properties["rect_w_m"]["x-group"] == "site"
    assert properties["rect_w_m"]["default"] == 77
    assert properties["rect_h_m"]["default"] == 51.5
    assert properties["target_resolution_m"]["x-readonly"] is True
    weights = properties["objective_weights"]
    assert weights["x-group"] == "preference"
    assert set(weights["properties"]) == {"dem_soft", "road_distance", "demand_distance"}
    assert "experiment_name" in spec.config_schema["required"]
    assert "预计产物" in spec.description


def test_decision_search_uses_ninety_generations_by_default() -> None:
    from config.project_config import GuidedSearchConfig

    spec = next(item for item in build_registry().list_specs() if item.id == "site.guided_search")
    assert spec.config_schema["properties"]["generations"]["default"] == 90
    assert GuidedSearchConfig().generations == 90
    assert GuidedSearchConfig().popsize == 40
    assert spec.config_schema["properties"]["include_demand"]["default"] is False
    assert spec.config_schema["properties"]["diagonal_access"]["default"] is False


def test_weight_sum_and_rectangle_are_rejected() -> None:
    service = JobService(SQLiteJobRepository(":memory:"), InMemoryTaskQueue(), build_registry())
    config = _valid_cma_config()
    config["objective_weights"] = {"dem_soft": 0.5, "road_distance": 0.5, "demand_distance": 0.5}
    try:
        service.create_job("site.cma_es", config)
    except ValueError as exc:
        assert "sum to 1" in str(exc)
    else:
        raise AssertionError("invalid weights were accepted")

    config = _valid_cma_config()
    config["rect_w_m"] = 0
    try:
        service.create_job("site.cma_es", config)
    except ValueError as exc:
        assert "rect_w_m" in str(exc)
    else:
        raise AssertionError("zero rectangle width was accepted")


def test_valid_siting_config_is_queued_without_running_the_search() -> None:
    service = JobService(SQLiteJobRepository(":memory:"), InMemoryTaskQueue(), build_registry())
    record = service.create_job("site.cma_es", _valid_cma_config())
    assert record.status.value == "queued"
    assert record.result is None
