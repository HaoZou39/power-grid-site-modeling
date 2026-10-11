"""Site-model inheritance. These tests do not run a search."""

import numpy as np
import torch

from algorithms.common.scalarization import OBJECTIVE_NAMES
from algorithms.common.search import SiteSearch
from algorithms.cma_es.cma_es import CmaEsSearch
from modeling.site_model import (
    DemandDistance,
    DemSoft,
    ObstacleCountConstraint,
    ObstacleSoft,
    RoadDistance,
    SiteConstraint,
    SiteModel,
    SiteObjective,
    default_site_model,
)


def test_default_model_keeps_the_pareto_objective_names() -> None:
    model = default_site_model()
    names = [item.name for item in model.objectives]
    assert list(OBJECTIVE_NAMES) == [name for name in names if name in OBJECTIVE_NAMES]
    assert "obstacle_soft" in names
    assert all(isinstance(item, SiteObjective) for item in model.objectives)
    assert isinstance(model.constraint, SiteConstraint)
    assert [type(item) for item in model.objectives] == [DemSoft, ObstacleSoft, RoadDistance, DemandDistance]


def test_constraint_subclass_is_what_the_model_reports() -> None:
    class Marked(ObstacleCountConstraint):
        def metrics(self, dem, obstacle_mask, pose_batch, rect_w_m, rect_h_m, device="cuda"):
            reported = super().metrics(dem, obstacle_mask, pose_batch, rect_w_m, rect_h_m, device)
            return {**reported, "constraint_violation": reported["obstacle_hard_count"] + 7}

    dem = np.zeros((6, 6), dtype=np.float32)
    mask = np.zeros((6, 6), dtype=np.float32)
    pose = torch.tensor([[2.5, 2.5, 0.0]])
    reported = SiteModel((), Marked()).hard_metrics(dem, mask, pose, 2.0, 2.0, device="cpu")
    assert float(reported["constraint_violation"][0]) == 7.0
    assert float(reported["obstacle_hard_count"][0]) == 0.0


def test_cma_es_uses_the_same_search_parent() -> None:
    assert issubclass(CmaEsSearch, SiteSearch)
    assert CmaEsSearch(object(), object()).algorithm_name == "cma_es"
