# Research Site Modeling Prototype

This is a fresh Python 3.11 implementation based only on `AGENTS.md` and the
three `markdown/*_SUMMARY.md` files. It keeps raw input files in `data/` and
separates data-tool code, PyTorch modeling, algorithm placeholder code,
experiments, configuration, and tests.

Run everything in the requested Conda environment:

```bash
conda run -n torch311 pytest -q
conda run -n torch311 python experiments/validate_modeling.py
```

The default config is `config/default_config.json`. CUDA is required and is
validated at startup; the code does not fall back to CPU.

Public entry points:

- `data_tools.dem_tool.build_dem_product`
- `data_tools.landuse_tool.build_landuse_product`
- `data_tools.traffic_tool.build_road_product`
- `data_tools.demand_tool.generate_demand_points`
- `modeling.pose.decode_raw_pose`
- `modeling.masks.compute_soft_footprint`
- `modeling.masks.compute_hard_footprint_indices`
- `modeling.dem_model.compute_dem_soft_loss`
- `modeling.dem_model.compute_dem_hard_loss`
- `modeling.obstacle_model.compute_obstacle_soft_loss`
- `modeling.obstacle_model.compute_obstacle_hard_loss`
- `modeling.road_model.compute_road_distance_loss`
- `modeling.demand_model.compute_demand_distance_loss`
- `modeling.evaluator.evaluate_site_objectives`
- `modeling.evaluator.compute_hard_constraints`

The algorithms package is intentionally a placeholder because
`ALGORITHMS_MODULE_SUMMARY.md` does not define any concrete algorithm yet.
