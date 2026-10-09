# Research Site Modeling Prototype

This is a fresh Python 3.11 implementation based only on `AGENTS.md` and the
three `markdown/*_SUMMARY.md` files. It keeps raw input files in `data/` and
separates data-tool code, PyTorch modeling, algorithm placeholder code,
experiments, configuration, and tests.

The repository now contains a small v0.1 software shell in addition to the
research modules. The shell has a React frontend, FastAPI API, background
worker, explicit plugin registry, and a deterministic demo plugin. Its
architecture is documented in `markdown/V0_ARCHITECTURE.md`.

Run the existing research checks in the requested Conda environment:

```bash
conda run -n torch311 pytest -q
conda run -n torch311 python experiments/validate_modeling.py
```

The default config is `config/default_config.json`. CUDA is required and is
validated at startup; the code does not fall back to CPU.

## v0.1 software shell

Install the backend dependencies and start the development API:

```bash
python -m pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8010
```

Without `REDIS_URL`, the development API uses a local SQLite database and
starts an embedded daemon worker. Production-shaped deployments use the
separate `worker` container and Redis from the Compose file.

The frontend can be started with Node.js:

```bash
cd frontend
npm install
npm run dev
```

For the production-shaped local stack, use Docker Compose:

```bash
docker compose -f deploy/compose.yaml up --build
```

The development API is available at `http://localhost:8010`, and the frontend at
`http://localhost:5173`. The first version intentionally exposes only the
demo plugin; real data and algorithms will be added through the same plugin
boundary.

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

Algorithm scope is defined in `markdown/ALGORITHMS_MODULE_SUMMARY.md` and the
algorithm documents it links. Finished experiments are recorded only in
`markdown/EXPERIMENT_LOG.md`.
