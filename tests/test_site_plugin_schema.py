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
        "site.build_scene",
        "site.cma_es",
        "site.guided_search",
        "site.multistart_adam",
        "site.partitioned_guided_search",
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
    assert GuidedSearchConfig().popsize == 100
    assert spec.config_schema["properties"]["popsize"]["default"] == 100
    assert GuidedSearchConfig().initialization == "uniform"
    assert spec.config_schema["properties"]["initialization"]["default"] == "uniform"
    assert spec.config_schema["properties"]["include_demand"]["default"] is False
    assert spec.config_schema["properties"]["diagonal_access"]["default"] is False
    assert spec.config_schema["properties"]["road_setback_m"]["default"] == 5.0
    assert GuidedSearchConfig().access_elevation_weight == 1.0


def test_partitioned_search_schema_and_limits() -> None:
    from plugins.site_plugin import PartitionedGuidedSitePlugin

    plugin = PartitionedGuidedSitePlugin()
    schema = plugin.describe().config_schema
    properties = schema["properties"]
    assert properties["partition_count"]["default"] == 4
    assert properties["max_parallel_tiles"]["default"] == 2
    assert properties["search_bounds_m"]["description"].startswith("可选的站址中心搜索范围")

    config = _valid_cma_config()
    config.pop("max_iters")
    config.pop("restarts_per_weight")
    config.update({"partition_count": 6, "max_parallel_tiles": 2})
    config["experiment_name"] = "parallel-search"
    plugin.validate_config(config)

    config["max_parallel_tiles"] = 7
    try:
        plugin.validate_config(config)
    except ValueError as exc:
        assert "max_parallel_tiles" in str(exc)
    else:
        raise AssertionError("parallelism above the configured maximum was accepted")


def test_partitioned_search_rejects_more_workers_than_tiles() -> None:
    from plugins.site_plugin import PartitionedGuidedSitePlugin

    config = _valid_cma_config()
    config.pop("max_iters")
    config.pop("restarts_per_weight")
    config.update({"partition_count": 4, "max_parallel_tiles": 5})
    try:
        PartitionedGuidedSitePlugin().validate_config(config)
    except ValueError as exc:
        assert "partition_count" in str(exc)
    else:
        raise AssertionError("parallelism above the tile count was accepted")


def test_partitioned_search_uses_existing_job_service() -> None:
    service = JobService(SQLiteJobRepository(":memory:"), InMemoryTaskQueue(), build_registry())
    config = _valid_cma_config()
    config.pop("max_iters")
    config.pop("restarts_per_weight")
    config.update(
        {
            "experiment_name": "parallel-queued",
            "partition_count": 4,
            "max_parallel_tiles": 2,
        }
    )

    record = service.create_job("site.partitioned_guided_search", config)
    assert record.status.value == "queued"
    assert record.plugin_id == "site.partitioned_guided_search"


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


def test_prepare_scene_accepts_only_the_two_registered_scenes() -> None:
    service = JobService(SQLiteJobRepository(":memory:"), InMemoryTaskQueue(), build_registry())
    record = service.create_job("site.prepare_scene", {"scene_name": "yongjia"})
    assert record.config["scene_name"] == "yongjia"
    try:
        service.create_job("site.prepare_scene", {"scene_name": "other"})
    except ValueError as exc:
        assert "scene_name" in str(exc)
    else:
        raise AssertionError("an unregistered scene was accepted")
