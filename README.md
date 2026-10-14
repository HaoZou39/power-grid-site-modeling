# Research Site Modeling Prototype

This repository contains the documented Python 3.11 research modules and the
v0.1 software shell. It keeps raw input files in `data/` and separates
data-tool code, PyTorch modeling, algorithms, experiments, configuration,
tests, frontend, backend, and worker services.

The repository now contains a small v0.1 software shell in addition to the
research modules. The shell has a React frontend, FastAPI API, background
worker, explicit plugin registry, and a deterministic demo plugin. Its
architecture is documented in `markdown/V0_ARCHITECTURE.md`.

For a file-by-file orientation, start with `markdown/CODE_MAP.md`. It explains
the purpose of every top-level directory and the public role of each module
without replacing the detailed domain documents.

The frontend implementation plan is specified in
`markdown/FRONTEND_IMPLEMENTATION_SPEC.md`. It covers the decision-maker flow,
configuration screens, run monitoring, result visualization, and acceptance
criteria for the next implementation agent.

Environment setup and the decision-map ports are in `markdown/LOCAL_RUN_GUIDE.md`. After creating or updating the Conda environment, run the research checks:

```bash
conda env update -n torch311 -f environment.yml
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

Without `REDIS_URL`, the development API uses in-memory SQLite and starts an
embedded daemon worker. Set `DATABASE_URL=sqlite:///outputs/v0/jobs.db` when
file-backed local persistence is needed. Production-shaped deployments use the
separate `worker` container and Redis from the Compose file.

The frontend can be started with Node.js:

```bash
cd frontend
npm install
npm run dev
```

From the repository root, `./restart.sh` fast-forwards the current branch, then stops this checkout's API and decision map and starts them again. If the pull fails, the running processes stay up. It uses the `torch311` interpreter and writes logs under `outputs/dev-servers/`. The decision map's Settings tab runs the same script after `UPDATE_PASSWORD` from the repo-root `.env`. A dirty worktree is rejected. If the new processes do not become healthy, the script resets to the pre-pull commit and starts again.

For the production-shaped local stack, use Docker Compose:

```bash
docker compose -f deploy/compose.yaml up --build
```

In development mode, the API listens on port `8010` and the decision map on
port `5176`. With Docker Compose, the API is exposed at `http://localhost:8000`.
The decision map calls the `site.guided_search` plugin. Its objective list is in
`markdown/GUIDED_SEARCH.md`. The demo plugin remains only to exercise the job shell.

The map can also open an assistant. It proposes edits and does not apply them
until the user confirms. The contract is `markdown/AGENT_MODULE.md`. Set these
before starting the API; leave them unset to keep the assistant unavailable:

```text
AGENT_BASE_URL   OpenAI-compatible base URL, including the /v1 prefix
AGENT_MODEL      model name
AGENT_API_KEY    secret, read only by the API process
```

Copy `.env.example` to `.env` for local values. The API reads that file at
startup when the variables are unset. `.env` is gitignored. Do not put the key
in the frontend or in a commit.

The assistant keeps confirmed preferences, shortcuts, and scene notes in
`memory/MEMORY.md` (override with `AGENT_MEMORY_PATH`). The file is created on
first use, can be edited by hand, and is gitignored. Clicking 「记为我的选择」 on a
scheme card appends one line to `memory/PREFERENCE_CHOICES.jsonl` (override with
`AGENT_PREFERENCE_HISTORY_PATH`). The assistant's 「偏好」 page saves a default
importance per objective to `memory/PREFERENCE_DEFAULTS.json` (override with
`AGENT_PREFERENCE_DEFAULTS_PATH`); recommendations start from these weights and
learn from the choices.

The frontend also has an experiment-results view. It reads completed output
directories under `EXPERIMENT_OUTPUT_ROOT` (default `outputs/`) through the
read-only experiment catalog API and previews PNG maps and self-contained Pareto
HTML files. Run an experiment that writes `run_summary.json`, then open the
“实验结果” view in the frontend.

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
`markdown/EXPERIMENT_LOG.md`. The Chinese file-by-file reading notes live in
`markdown/CODE_MAP.md`. This section is the English index of the same source
tree. It omits `outputs/`, `scenes/`, `data/` rasters, and dependency folders.

## Repository map

### `data_tools/`

Reads raw inputs and writes aligned 1 m products. It does not train or score sites.

- `__init__.py`: package marker.
- `dem_tool.py`: read the DEM and resample it to the 1 m grid.
- `landuse_tool.py`: map land-use classes to the obstacle mask.
- `landuse_prompt.py`: replaceable click-segmentation hook; the placeholder raises.
- `traffic_tool.py`: read OSM roads, convert them to local meters, and build the Voronoi grid.
- `demand_tool.py`: generate demand points from a count and seed.
- `io_utils.py`: write JSON, arrays, and paths.

### `modeling/`

Turns the 1 m products into PyTorch objectives and hard metrics.

- `__init__.py`: package marker.
- `context.py`: `SiteProblemContext`, the shared numpy and tensor bundle.
- `pose.py`: decode an unbounded raw pose into local meters and heading.
- `masks.py`: soft and hard building footprints.
- `dem_model.py`: soft and hard terrain flatness.
- `obstacle_model.py`: soft overlap and hard obstacle counts.
- `road_model.py`: differentiable straight-line distance to the road, using the Voronoi grid.
- `demand_model.py`: weighted distance to the demand points.
- `site_model.py`: objective and constraint classes assembled into one site model.
- `evaluator.py`: function entry that calls the default site model.
- `slope.py`: footprint slope used only in reports.
- `logistics_cost.py`: on-road length from an origin to a road contact.
- `construction_cost.py`: one site's approach polyline, plus the public road-gate grid.
- `haul_field.py`: one distance field per search. Cell centers match the polyline lengths.
- `haul_model.py`: bilinear sample of that field for the short gradient guide.
- `access_path.py`: straight-line approach kept for comparison tests.

### `algorithms/`

Replaceable searches. They do not read raw rasters.

- `__init__.py`: package marker.
- `common/__init__.py`: package marker.
- `common/search.py`: `SiteSearch` parent. Subclasses implement `search`.
- `common/scalarization.py`: three-objective order and Tchebycheff used by CMA-ES and Adam.
- `common/pareto.py`: feasible non-dominated records.
- `common/weiszfeld.py`: demand ideal point.
- `guided_search/__init__.py`: package marker.
- `guided_search/search.py`: decision guided search. Dominance uses the exact haul lookup.
- `guided_search/guide.py`: short Adam guide before that evolution. The sum is not the dominance rule.
- `cma_es/__init__.py`: package marker.
- `cma_es/cma_es.py`: research CMA-ES search.
- `cma_es/cma_es_main.py`: load config, run CMA-ES, write outputs.
- `cma_es/pareto.py`: compatibility re-export of `common/pareto.py`.
- `cma_es/weiszfeld.py`: compatibility re-export of `common/weiszfeld.py`.
- `multistart_adam/__init__.py`: package marker.
- `multistart_adam/multistart_adam.py`: multi-start Adam on one weight vector at a time.
- `multistart_adam/multistart_adam_main.py`: load config, run Adam, write outputs.
- `vae_like_multihead/__init__.py`: package marker.
- `vae_like_multihead/vae_like_multihead.py`: VAE-like candidate generator.
- `vae_like_multihead/vae_like_multihead_main.py`: load config, train, write outputs.

### `experiments/`

Assemble data, modeling, and a search, then write one result directory.

- `__init__.py`: package marker.
- `problem_context.py`: build the shared problem context from the four data tools.
- `scene_store.py`: save and load a prepared scene under `scenes/`; `rebuild_scene_roads` safely rebuilds only the road segments, Voronoi grid, and matching metadata while preserving all non-road products.
- `constraint_mask.py`: compose one run's hard and soft masks from land use and drawn zones.
- `landuse_patch.py`: turn one click into the ring of a connected land-use patch.
- `site_report.py`: slope, haul lengths, and the yellow path for one site. It does not search.
- `launch_site_run.py`: decision-job entry for guided search, CMA-ES, and Adam. `evaluate_form_poses` rescores poses placed outside a search with the same columns.
- `output_writer.py`: CSV, summary, maps, and Pareto HTML.
- `run_cma_es_region.py`: command line for the CMA-ES region experiment.
- `run_multistart_adam_region.py`: command line for the Adam region experiment.
- `run_vae_like_multihead_region.py`: command line for the VAE-like experiment.
- `validate_modeling.py`: small CUDA modeling check.
- `diagnose_road_alignment.py`: road-alignment diagnostic, outside the search path.

### `figures/`

Shared drawings. They do not load raw data or compute objectives.

- `__init__.py`: package marker.
- `candidate_maps.py`: footprint and point maps.
- `pareto_3d.py`: interactive Pareto HTML.

### `config/`

- `__init__.py`: package marker.
- `project_config.py`: dataclasses, JSON load, validation, and save.
- `default_config.json`: default experiment parameters. The 110 kV footprint default is 77 m by 51.5 m.

### `validation_data/`

- `build_preferences.py`: write the fixed preference table.
- `preferences_step_0.1.csv`: deterministic validation weights.

### `backend/`

FastAPI shell. Routes do not implement the search.

- `__init__.py`: package marker.
- `requirements.txt`: API dependencies.
- `Dockerfile`: API image.
- `app/__init__.py`: package marker.
- `app/main.py`: application factory.
- `app/api/__init__.py`: package marker.
- `app/api/routes.py`: HTTP models and routes.
- `app/api/agent_routes.py`: assistant chat and the edit-operation schema.
- `app/application/agent_gateway.py`: read-only adapters the assistant tools call.
- `app/domain/__init__.py`: package marker.
- `app/domain/plugins.py`: plugin protocol.
- `app/domain/jobs.py`: job records and statuses.
- `app/domain/experiments.py`: experiment catalog records.
- `app/application/__init__.py`: package marker.
- `app/application/registry.py`: built-in plugin registration.
- `app/application/service.py`: create, run, cancel, and read jobs.
- `app/infrastructure/__init__.py`: package marker.
- `app/infrastructure/repository.py`: SQLite job store.
- `app/infrastructure/postgres_repository.py`: PostgreSQL job store.
- `app/infrastructure/queue.py`: in-memory and Redis queues.
- `app/infrastructure/experiment_catalog.py`: read-only scan of `outputs/`.

### `frontend/`

React decision map. It calls the API and does not run the optimizer.

- `package.json`: scripts and dependencies.
- `package-lock.json`: locked npm versions.
- `index.html`: page shell.
- `vite.config.ts`: dev server and API proxy.
- `tsconfig.json`: TypeScript project.
- `nginx.conf`: static hosting for the production image.
- `Dockerfile`: frontend image.
- `src/main.tsx`: React mount.
- `src/App.tsx`: shell. It mounts the decision map and the health line.
- `src/styles.css`: visual styles.
- `src/vite-env.d.ts`: Vite client types.
- `src/api.ts`: request functions and response types.
- `src/agent/`: assistant snapshot, edit reducer, chat request, and confirm panel.
- `src/generated/api.ts`: generated OpenAPI types. Do not edit by hand.
- `src/map/basemap.ts`: satellite tile URL.
- `src/map/site_frame.ts`: local meter frame for the 1800 m site.
- `src/map/site_frame.test.mjs`: frame conversion checks.
- `src/map/world_map.tsx`: pan, zoom, and pointer tools.
- `src/map/site_overlay.tsx`: draw the frame, zones, footprints, and haul line.
- `src/map/building_footprint.ts`: oriented rectangle corners.
- `src/map/decision_run.ts`: guided-search request, Pareto rows, status lines, and footprint moves.
- `src/map/decision_map.test.mjs`: decision-map logic checks.
- `src/map/exclusion_sketch.ts`: freehand exclusion zones.
- `src/map/map_shortcuts.ts`: keyboard shortcuts.
- `src/map/toolbar_commands.ts`: ribbon commands and which ones stay beside the map.
- `src/map/map_toolbar.tsx`: File, Home, View, and Edit tabs, plus the map-side tools.
- `src/map/map_workspace.tsx`: assemble the map, ribbon, and sidebar.
- `src/problem_overview.tsx`: problem overview page. It is not mounted.
- `src/problem_snapshot.ts`: adapt an experiment manifest into a problem snapshot.
- `src/problem_snapshot.test.mjs`: snapshot checks.
- `src/job_workspace.tsx`: plugin form. It is not mounted.
- `src/config_form.tsx`: schema-driven form.
- `src/config_check.ts`: client-side form checks.
- `src/config_check.test.mjs`: form-check tests.
- `src/run_monitor.tsx`: job polling for the unmounted form.
- `src/run_status.ts`: status and failure text.
- `src/run_status.test.mjs`: status text checks.
- `src/experiment_browser.tsx`: experiment list. It is not mounted.
- `src/result_explorer.tsx`: one experiment's maps and tables. It is not mounted.
- `src/solution_record.ts`: read solution CSV columns.
- `src/solution_record.test.mjs`: CSV reader checks.

### `agent/`

Read-only assistant. It proposes edit operations and does not change the map.
The confirm step lives in the frontend. See `markdown/AGENT_MODULE.md`.

- `__init__.py`: package marker.
- `config.py`: model settings from the environment.
- `workspace.py`: snapshot, edit operations, and validation.
- `tools.py`: read-only tool registry.
- `llm.py`: OpenAI-compatible chat client.
- `loop.py`: one conversation turn.
- `prompts.py`: system prompt.

### `plugins/`

- `__init__.py`: package marker.
- `site_plugin.py`: schemas and runners for scene preparation, guided search, CMA-ES, and Adam.
- `demo/__init__.py`: package marker.
- `demo/plugin.py`: deterministic demo plugin for the job shell.

### `worker/`

- `__init__.py`: package marker.
- `main.py`: separate worker process. It reuses the API service.
- `Dockerfile`: worker image.

### `deploy/`

- `compose.yaml`: API, worker, Redis, PostgreSQL, and frontend.

### `tests/`

Small deterministic checks. They do not run a full Cangnan search.

- `conftest.py`: CUDA fixture.
- `fixtures/landuse_classes_0_to_5.csv`: known land-use classes.
- `fixtures/landuse_unknown_class.csv`: a class id the mapper must reject.
- `test_landuse_mapping.py`: class-to-mask mapping.
- `test_landuse_prompt.py`: segmentation placeholder.
- `test_landuse_patch.py`: connected land-use click.
- `test_pose_and_masks_cuda.py`: CUDA pose and footprints.
- `test_objectives_cuda.py`: CUDA soft objectives.
- `test_hard_metrics.py`: hard metrics and feasibility.
- `test_site_model.py`: objective and constraint objects.
- `test_construction_cost.py`: unpriced haul lengths.
- `test_construction_report.py`: one-site report.
- `test_haul_field.py`: distance-field lookup against the polyline.
- `test_haul_model.py`: bilinear sampling and the unreachable sentinel.
- `test_guided_search.py`: dominance, objective names, one field build per search, and rescoring that reproduces the search rows.
- `test_search_guide.py`: gradient guide and exact lookup after it.
- `test_cma_es_utils.py`: CMA-ES helpers.
- `test_multistart_adam.py`: Adam search pieces.
- `test_vae_like_multihead.py`: VAE-like pieces.
- `test_constraint_mask.py`: land-use and drawn-zone masks.
- `test_scene_store.py`: scene directory read and write.
- `test_launch_site_run.py`: form overlay and output-directory guards.
- `test_site_plugin_schema.py`: siting plugin validation.
- `test_figures.py`: shared figure writer.
- `test_experiment_output_writer.py`: experiment output contract.
- `test_v0_plugins.py`: plugin registry and cancel.
- `test_v0_api.py`: HTTP job API.
- `test_v0_experiments.py`: experiment catalog API.
- `test_invalid_inputs.py`: illegal inputs raise.

### `markdown/`

Authority notes. Change a rule here before changing the code that follows it.

- `CODE_MAP.md`: Chinese directory and file guide.
- `DATA_MODULE_SUMMARY.md`: data tools and coordinates.
- `MODELING_MODULE_SUMMARY.md`: objectives, constraints, and the haul field.
- `ALGORITHMS_MODULE_SUMMARY.md`: algorithm index.
- `ALGORITHM_COMMON.md`: shared objective order, weights, and Pareto rules.
- `GUIDED_SEARCH.md`: decision guided search.
- `CMA_ES.md`: research CMA-ES.
- `MULTISTART_ADAM.md`: multi-start Adam.
- `VAE_LIKE_MULTIHEAD_ALGORITHM.md`: VAE-like generator.
- `VALIDATION.md`: evenly spaced preference checks.
- `FIGURES_MODULE_SUMMARY.md`: shared figures.
- `TESTING_STRATEGY.md`: pytest versus acceptance scripts.
- `LOCAL_RUN_GUIDE.md`: local end-to-end commands.
- `EXPERIMENT_LOG.md`: finished experiments.
- `V0_ARCHITECTURE.md`: API, plugins, jobs, and deployment.
- `FRONTEND_IMPLEMENTATION_SPEC.md`: decision-map screens and acceptance.
- `DECISION_REQUIREMENTS.md`: requirements not yet in the search.
