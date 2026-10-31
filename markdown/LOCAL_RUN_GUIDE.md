# Local End-to-End Run Guide

This is the environment guide for people working on this repository. The recorded Windows verification later in this file is one successful machine, not a second setup procedure.

## Default Python environment

The only project interpreter is the Conda environment named `torch311`. `environment.yml` creates it with Python 3.11 and the research dependencies, including Shapely and PyProj. Pytest, experiment scripts, and the local API all use this environment:

```bash
conda run -n torch311 python -m pytest -q
```

Do not run those commands with the base Conda interpreter (`python` or `python3` while the base environment is active). That interpreter does not have this repository's packages. `ModuleNotFoundError: No module named 'shapely'` means the command used the base interpreter. Activate `torch311`, or keep the `conda run -n torch311` prefix. Node.js commands for the decision map stay outside this environment.

## Environment for collaborators

### CAD classification

Install the current data dependencies, including `ezdxf==1.4.3`. DXF files can
then be classified directly. DWG files additionally require the official
[LibreDWG converter](https://github.com/LibreDWG/libredwg/releases).
Set `CAD_DWG_CONVERTER` to the absolute `dwg2dxf` executable path in the process
environment or repository `.env`, or put `dwg2dxf` on PATH. The API and worker
Dockerfiles build pinned LibreDWG 0.14 from a SHA256-checked source archive.
Uploading an attachment remains available when this optional converter is absent;
attempting DWG classification reports the missing dependency explicitly.

Open **File → Import data**, add the drawing, and choose its layer-classification
action. Confirm suggested building, field, road-area and water classes, explicitly
classify or ignore unknown layers, and enter the source CRS supplied with the CAD.
Generate the preview and apply it to the current scene. This preserves the current
field/mountain policies and manual land-use edits. The construction-feasibility
overlay and subsequent evaluations use the normal scene rules. Existing poses
need reevaluation. The active CAD layer can be removed independently of the stored
attachment. CAD coordinates are interpreted in the supplied CRS; units, datum or
position are never inferred from a file name or a nearby scene.

### Tools

- Git, to clone `https://github.com/HaoZou39/power-grid-site-modeling.git`
- Conda
- An NVIDIA GPU and compatible driver for CUDA research checks; guided search also supports CPU
- Node.js 22 or newer, and npm, for the decision map
- The raw files listed below, under `data/`

Guided search defaults to tensor evolution on CUDA and automatically uses the original NumPy evolution with CPU evaluation when CUDA is unavailable. The CUDA-specific modeling acceptance and other research entry points still require a GPU.

### Python

Use the `torch311` environment from the section above. From the repository root, create it when it does not exist:

```bash
conda env create -f environment.yml
```

If `torch311` already exists, update it instead of creating a second environment:

```bash
conda env update -n torch311 -f environment.yml --prune
```

That file installs Python 3.11 and PyTorch 2.11.0 with CUDA 12.8. The other pip packages are listed in `requirements.txt`, including NumPy, SciPy, Numba, Matplotlib, Rasterio, PyProj, Shapely, Requests, Mercantile, Transformers, pytest, pycma, TensorBoard, FastAPI, and Uvicorn. Check that this interpreter can see a GPU:

```bash
conda run -n torch311 python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"
```

If `cuda_available` is `False`, guided search and CPU tests can continue; skip the CUDA-specific acceptance commands. Use the same interpreter for the API and tests so the project dependencies are available.

### Data files

These four inputs must be present in `data/`:

```text
苍南10m84_clip_1800m_10m_180x180_3857.tif
satellite_27.501662_120.194639_r0.90km_z18_crop_epsg3857.tif
satellite_27.501662_120.194639_r0.90km_z18_crop_epsg3857_routing_coarse_mask_downsampled.csv
osm_roads_27.501662_120.194639_r0.90km_wgs84.geojson
```

Those files are the prepared Cangnan inputs. To enable the preset Yongjia scene,
copy exactly four raw files into the following controlled paths. Long source
bundle names may be renamed while copying; no pipeline metadata or QA report is
required.

```text
data/sites/yongjia/satellite_ref.tif
data/sites/yongjia/landuse.csv
data/sites/yongjia/dem.tif
data/sites/yongjia/osm_roads.geojson
```

### Decision map

Start the API from the repository root:

```bash
conda run -n torch311 python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8010
```

In a second terminal, start the page:

```bash
cd frontend
npm install
npm run dev
```

Each optimization result's "收藏站址" button saves to the favorite collection.
The edit toolbar does not add or drag favorites. Favorites use
`outputs/user-state/favorites.sqlite3` by default. `FAVORITES_DB_PATH` overrides
the file; the default and relative environment paths resolve from the repository
root. Keep this file when restarting or updating the service. Page reloads and
API restarts retain favorites; separate machines have separate databases.
After pulling code or configuration changes, update the declared dependencies
and restart the API and frontend so the running code matches the configuration.

This also applies after a manual Git merge. Python keeps imported modules in
each running process; an API or Worker started before the merge can combine an
old cached module with newly imported code. For example, `cannot import name
'access_policy' from 'experiments.constraint_mask'` can occur even when the
function exists on disk and imports successfully in a new `torch311` process.
Check the service start time against the update, finish active jobs, and restart
the API and any separate Worker. Verify an actual pose evaluation or job after
the restart; the health endpoint only confirms that the server responds.

To pull the current branch and restart both processes on that code:

```bash
./restart.sh
```

The script fast-forwards from the branch upstream first. If the pull fails, the listeners keep running. It then stops listeners on ports 8010 and 5176 only when their working directory is this repository, and starts the API with the `torch311` interpreter and the decision map again. A frontend dependency change in that pull runs `npm install` before the restart. Logs are `outputs/dev-servers/api.log` and `outputs/dev-servers/web.log`. In-memory jobs are cleared. Set `PYTHON` when the `torch311` interpreter is not the one Conda would select. Python environment changes in `environment.yml` are not applied by this script. The Settings tab button "软件更新" calls this same script. Set `UPDATE_PASSWORD` in the repo-root `.env`; the value stays on the server. A dirty worktree, a missing upstream, or an update already in progress is rejected and the current processes stay up. The started servers do not inherit the update lock, so the page sees the run as finished once the script exits. Stopping sends SIGTERM, waits up to 10 s for both ports to free, and only then sends SIGKILL. If the new processes do not pass the health checks, the script runs `git reset --hard` back to the pre-pull commit, reruns `npm install` when that pull had changed the frontend dependencies, and starts that code. After success or rollback the dialog offers a page reload. If no status for this run appears within 60 s and no update holds the lock, the dialog reports that the update never started; the reason is in `outputs/dev-servers/update.log`. The assistant cannot start an update.

`frontend/package.json` asks for Node.js 22 or newer. The dev server listens on port 5176 and forwards `/api` to `http://127.0.0.1:8010`, so colleagues open only the page. The proxy opens a new connection per request; reusing idle connections raced uvicorn's 5 s keep-alive close and returned an occasional 502. On this machine that address is `http://10.28.0.176:5176`. On another machine, use that machine's LAN address with port 5176. The same page on the server itself is `http://127.0.0.1:5176`.

Without `REDIS_URL`, the API keeps jobs in memory and runs them in a background thread. Set `DATABASE_URL=sqlite:///outputs/v0/jobs.db` when a local file-backed job store is needed.

The API and Worker select sequential Intel MKL threading before importing the
numerical stack. This avoids loading a second Intel OpenMP runtime when a
PyTorch build and a Conda MKL-backed NumPy/SciPy environment are used together.
Candidate-map artifacts use Matplotlib's non-interactive `Agg` backend so they
can be rendered safely by a background job.

#### Submit a partitioned search without the frontend

The backend registers `site.partitioned_guided_search` on the existing Jobs API.
Submit one job with 4 or 6 partitions and a worker cap. The optional
`search_bounds_m` value is `[x_min, y_min, x_max, y_max]` in scene-local meters;
omit it to search the full safe scene range.

```bash
curl -X POST http://127.0.0.1:8010/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"plugin_id":"site.partitioned_guided_search","config":{"experiment_name":"partitioned-demo","scene_name":"cangnan-utm-v2","partition_count":4,"max_parallel_tiles":2,"seed":123}}'
```

Poll `GET /api/v1/jobs/{job_id}` until the job is terminal, then read
`GET /api/v1/jobs/{job_id}/result`. The returned `data.experiment_id` identifies
the combined result under `GET /api/v1/experiments/{experiment_id}`. The result
uses the standard full-scene maps and solution CSVs, with additional
`partition_manifest.json` and `partitions.csv` provenance. The assistant does
not submit this batch plugin.

The map assistant reads `AGENT_BASE_URL`, `AGENT_MODEL`, and `AGENT_API_KEY` from the repo-root `.env` on every new chat. A process environment value that differs from `.env` wins for that key, and the settings page refuses to pretend a save changed it. Names and the confirm flow are in `markdown/AGENT_MODULE.md`. A missing value makes the assistant return 503. Do not commit `.env`. The assistant memory is `memory/MEMORY.md` under the repo root, or `AGENT_MEMORY_PATH`. The API creates it on first use; it stays on this machine and out of git.

The in-app fast-forward update uses the POSIX `restart.sh` workflow and is not available when the API runs as a native Windows process. On Windows, fetch/pull the desired branch in Git and restart the API and frontend manually.

### Checks before changing search code

```bash
conda run -n torch311 python -m pytest -q
cd frontend && npm run test:problem-snapshot
```

`experiments/validate_modeling.py` is the small CUDA modeling check. It reads `config/default_config.json`.

### Docker

The Compose stack in `deploy/compose.yaml` is a separate production-shaped layout. It uses PostgreSQL, Redis, and its own API port `8000`. Day-to-day work on the decision map uses the two commands above, not Compose.

## Recorded Windows verification

The notes below record one complete run on October 8, 2026. They are not required to start the decision map.

## 1. Verified machine and software

The successful run used:

- Windows 11 and PowerShell
- NVIDIA GeForce RTX 5060 Ti with 8 GB VRAM
- NVIDIA driver 610.47
- Conda 25.5.1
- Python 3.11.17
- PyTorch 2.11.0+cu128
- CUDA runtime reported by PyTorch: 12.8
- Rasterio 1.4.4
- PyProj 3.7.2
- Shapely 2.2.0
- SciPy 1.17.1
- pycma 4.5.0
- TensorBoard 2.21.0

Guided-search tasks resolve the device before loading scene tensors. Without CUDA they use NumPy evolution and CPU soft objectives/Adam; the requested population and iteration counts stay unchanged. Other CUDA research entry points keep their explicit device checks.

## 2. Run commands from the repository root

Open PowerShell and change to the cloned repository directory. All later paths are relative to this directory.

```powershell
Set-Location 'C:\path\to\the\repository'
```

Confirm that the four raw input files are present:

```powershell
Get-ChildItem .\data
```

Expected inputs:

```text
osm_roads_27.501662_120.194639_r0.90km_wgs84.geojson
satellite_27.501662_120.194639_r0.90km_z18_crop_epsg3857.tif
satellite_27.501662_120.194639_r0.90km_z18_crop_epsg3857_routing_coarse_mask_downsampled.csv
苍南10m84_clip_1800m_10m_180x180_3857.tif
```

## 3. Check Conda and the GPU

```powershell
conda --version
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
```

The verified machine printed:

```text
conda 25.5.1
NVIDIA GeForce RTX 5060 Ti, 610.47, 8151 MiB
```

## 4. Create the Conda environment

Create the environment declared by the repository:

```powershell
conda env create -f environment.yml
```

This creates the `torch311` environment and installs PyTorch 2.11.0 with CUDA 12.8, NumPy, SciPy, Matplotlib, Rasterio, PyProj, Shapely, pytest, pycma, and TensorBoard.

The PyTorch wheel is large. In the verified run it downloaded approximately 2.8 GB and took about 13 minutes at the available network speed.

If `torch311` already exists, do not recreate it. Update it from the environment file:

```powershell
conda env update -n torch311 -f environment.yml --prune
```

## 5. Verify Python, CUDA, and the core dependencies

Run:

```powershell
conda run -n torch311 python -c "import sys, torch, rasterio, pyproj, shapely, scipy, cma, tensorboard; print('python', sys.version.split()[0]); print('torch', torch.__version__); print('cuda_build', torch.version.cuda); print('cuda_available', torch.cuda.is_available()); print('gpu', torch.cuda.get_device_name(0) if torch.cuda.is_available() else None); print('rasterio', rasterio.__version__); print('pyproj', pyproj.__version__); print('shapely', shapely.__version__); print('scipy', scipy.__version__); print('cma', cma.__version__); print('tensorboard', tensorboard.__version__)"
```

The verified output was:

```text
python 3.11.17
torch 2.11.0+cu128
cuda_build 12.8
cuda_available True
gpu NVIDIA GeForce RTX 5060 Ti
rasterio 1.4.4
pyproj 3.7.2
shapely 2.2.0
scipy 1.17.1
cma 4.5.0
tensorboard 2.21.0
```

Without CUDA, continue with guided search and CPU tests. The CUDA-only modeling and research commands still raise an explicit error.

## 6. Run the complete test suite

```powershell
conda run -n torch311 pytest -q
```

Verified result:

```text
The exact count depends on the checked-out test set. The command above is the
authoritative verification command; it includes both the modeling tests and
the v0 web-shell tests.
```

The tests cover data mapping, pose bounds, masks, soft objectives, hard metrics,
CMA-ES utilities, multi-start Adam components, VAE-like multi-head components,
figures, invalid inputs, CUDA behavior, plugin configuration schemas, API
transport, and the embedded worker flow. The CUDA-dependent tests require the
environment check above to report `cuda_available True`.

## 7. Run the end-to-end data and modeling validation

```powershell
conda run -n torch311 python experiments/validate_modeling.py
```

The default command reads `config/default_config.json` and uses the output directory stored in that configuration. To select the configuration and output directory explicitly, run:

```powershell
conda run -n torch311 python experiments/validate_modeling.py --config config/default_config.json --output-dir outputs/validate_modeling_custom
```

This command performs the following operations in order:

1. Loads `config/default_config.json`.
2. Validates the CUDA device.
3. Reads the 1 m land-use CSV and creates the obstacle mask.
4. Reprojects and bilinearly resamples the 10 m DEM to the 1 m primary grid.
5. Projects the WGS84 OSM roads into local grid coordinates, simplifies them, and builds the road Voronoi matrix.
6. Generates 64 deterministic demand points with seed 42.
7. Evaluates three sample poses with all four soft objectives.
8. Runs backpropagation and checks that the raw-pose gradients are finite CUDA tensors.
9. Computes hard DEM and obstacle metrics.
10. Writes the validation summary and all aligned data products.

The verified run took approximately 109 seconds and printed:

```text
{
  "torch": "2.11.0+cu128",
  "cuda_available": true,
  "cuda_version": "12.8",
  "device_count": 1,
  "device_name": "NVIDIA GeForce RTX 5060 Ti",
  "memory_allocated": 51856384,
  "max_memory_allocated": 75713536
}
validation outputs: outputs\validate_modeling
```

### Files produced by the modeling validation

The command writes to `outputs/validate_modeling`, as configured by `data.output_dir` in `config/default_config.json`.

| File                         | Meaning                                                                            |
| ---------------------------- | ---------------------------------------------------------------------------------- |
| `resolved_config.json`     | Fully resolved configuration used by the run.                                      |
| `landuse_1m.npy`           | `1800 x 1800` integer land-use grid.                                             |
| `landuse_1m.json`          | Land-use source, class mapping, resolution, and coordinate metadata.               |
| `obstacle_mask_1m.npy`     | `1800 x 1800` binary obstacle grid.                                              |
| `obstacle_mask_1m.json`    | Obstacle mapping and grid metadata.                                                |
| `dem_1m.npy`               | `1800 x 1800` aligned float32 DEM.                                               |
| `dem_1m.json`              | DEM source CRS, transforms, bounds, resampling method, and target shape.           |
| `road_segments_local.npy`  | 523 local road segments with shape `[523, 4]`.                                    |
| `road_segments_local.json` | Road projection and simplification metadata.                                       |
| `road_voronoi_1m.npy`      | `1800 x 1800` nearest-road-segment ID grid.                                      |
| `road_voronoi_1m.json`     | Road Voronoi metadata.                                                             |
| `demand_points.npy`        | 64 continuous local demand points with shape `[64, 2]`.                           |
| `demand_points.json`       | Demand seed, count, primary-grid shape, and coordinate convention.                 |
| `validation_summary.json`  | CUDA information, metadata, soft objectives, hard metrics, and raw-pose gradients. |

All six generated NPY products were loaded after the run. Their shapes were correct and every numeric value was finite.

### Validation CLI options

The validation entry point supports:

```text
--config CONFIG_PATH
--output-dir OUTPUT_DIRECTORY
```

Run `conda run -n torch311 python experiments/validate_modeling.py --help` to display the CLI help without starting validation. If `--output-dir` is omitted, the script uses `data.output_dir` from the selected config. Reusing an output directory overwrites files with matching names.

## 8. Run one complete CMA-ES experiment

The current `experiments/run_cma_es_region.py` wrapper always uses its default output directory and does not expose command-line arguments. To preserve existing CMA-ES outputs, the verified run called the already-parameterized Python `main` function directly and supplied a fresh output directory:

```powershell
conda run -n torch311 python -c "from algorithms.cma_es.cma_es_main import main; main('config/default_config.json', 'outputs/local_run_guide_cma_es')"
```

This was a complete default experiment, not a reduced smoke run. The default configuration used:

- 66 deterministic weight vectors from a three-objective simplex grid with step 0.1
- population size 8
- up to 40 CMA-ES iterations per weight vector
- one restart per weight vector
- 512 fixed normalization samples
- a `95`th-percentile normalization scale
- seed 123 for both normalization and CMA-ES

The command repeats the data preparation, computes one fixed normalization, runs CMA-ES for all 66 preferences, evaluates hard constraints, extracts the feasible Pareto front, and generates the figures.

The verified run took approximately 180 seconds and printed:

```text
CMA-ES outputs: outputs\local_run_guide_cma_es
```

### Verified CMA-ES result counts

`outputs/local_run_guide_cma_es/run_summary.json` contained:

```json
{
  "n_runs": 66,
  "n_solutions": 66,
  "n_feasible": 64,
  "n_pareto": 25,
  "no_feasible_solution": false
}
```

The CSV files were read back after the run:

- `runs.csv`: 66 data rows
- `solutions.csv`: 66 data rows
- `pareto_solutions.csv`: 25 data rows

### Files produced by the CMA-ES experiment

| File                                      | Meaning                                                                                                                |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `resolved_config.json`                  | Configuration used by this experiment.                                                                                 |
| `data_metadata.json`                    | Combined DEM, land-use, road, and demand metadata.                                                                     |
| `normalization.json`                    | Fixed ideal values, scales, percentile, sample count, and seed.                                                        |
| `runs.csv`                              | One summary row for each of the 66 preference runs.                                                                    |
| `solutions.csv`                         | One final candidate from each preference, including raw pose, decoded pose, objectives, hard metrics, and feasibility. |
| `pareto_solutions.csv`                  | The 25 hard-feasible nondominated solutions.                                                                           |
| `run_summary.json`                      | Run, solution, feasible, and Pareto counts.                                                                            |
| `dem_1m.npy` and `.json`              | Aligned DEM and metadata used by the experiment.                                                                       |
| `landuse_1m.npy` and `.json`          | Land-use grid and metadata.                                                                                            |
| `obstacle_mask_1m.npy` and `.json`    | Obstacle grid and metadata.                                                                                            |
| `road_segments_local.npy` and `.json` | Local road geometry and metadata.                                                                                      |
| `road_voronoi_1m.npy` and `.json`     | Road Voronoi grid and metadata.                                                                                        |
| `demand_points.npy` and `.json`       | Deterministic demand points and metadata.                                                                              |

Use a new directory name for each experiment if previous results must be preserved:

```powershell
conda run -n torch311 python -c "from algorithms.cma_es.cma_es_main import main; main('config/default_config.json', 'outputs/cmaes_experiment_002')"
```

## 9. Inspect the results

Print the CMA-ES run summary:

```powershell
Get-Content .\outputs\local_run_guide_cma_es\run_summary.json
```

Count CSV records:

```powershell
(Import-Csv .\outputs\local_run_guide_cma_es\runs.csv).Count
(Import-Csv .\outputs\local_run_guide_cma_es\solutions.csv).Count
(Import-Csv .\outputs\local_run_guide_cma_es\pareto_solutions.csv).Count
```

The run writes the CSV and JSON files above. It does not write candidate-map PNG files or `pareto_3d_interactive.html`.

## 10. Reproducibility and overwrite behavior

- Data and experiment parameters come from `config/default_config.json`.
- Demand generation uses seed 42.
- Normalization and CMA-ES use seed 123.
- The fixed objective order is `dem_soft`, `road_distance`, `demand_distance`.
- `obstacle_soft` is a search penalty, not a Pareto objective.
- Hard feasibility is defined only by `obstacle_hard_count == 0`.
- Reusing an output directory overwrites files with matching names. Use a new directory for a new experiment.
- `outputs/`, `.codegraph/`, and `.history/` are ignored. Running tests or experiments writes local files and does not by itself change `git status`.

## 11. Short verified command sequence

For a new machine, the complete verified sequence is:

```powershell
conda env create -f environment.yml
conda env update -n torch311 -f environment.yml
conda run -n torch311 python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"
conda run -n torch311 pytest -q
conda run -n torch311 python experiments/validate_modeling.py --config config/default_config.json --output-dir outputs/validate_modeling
conda run -n torch311 python -c "from algorithms.cma_es.cma_es_main import main; main('config/default_config.json', 'outputs/local_run_guide_cma_es')"
```

Successful completion means:

- all tests in the current checkout pass;
- `outputs/validate_modeling/validation_summary.json` exists;
- `outputs/local_run_guide_cma_es/run_summary.json` exists;
- the summary reports 66 runs and at least one feasible solution;
- the CSV, PNG, and HTML result files are present.

## 12. Run the v0.1 software shell

The v0.1 shell is a separate application surface around the research modules.
It exposes a FastAPI API, a React frontend, an explicit plugin registry, and a
background job boundary. The default local mode uses in-memory SQLite and an embedded
worker when `REDIS_URL` is not set.

Start the API and the decision map with the commands in "Environment for collaborators" above, or run `./restart.sh` from the repository root to fast-forward the current branch and start this checkout's listeners again. The Settings tab button runs that same script after `UPDATE_PASSWORD` is set. Use the `torch311` interpreter. Do not start the API with a different system Python.

Open `http://127.0.0.1:5176`. The page is the decision map. Use the Cangnan and
Yongjia buttons in the top toolbar to select a preset region. A prepared scene
can optimize immediately. For an unprepared preset scene, open the Home tab and click
`准备当前场景数据`. That button rebuilds the scene that is currently open and fuses `masking_pipeline/data/regional/water_polygons.shp` and `water_lines.shp`, each with its `.shx`, `.dbf`, `.prj` and `.cpg` sidecars. Only polygon records with `fclass=water` are written; other polygon classes are skipped. Line widths are estimated during that rebuild. Original road and building cells stay unchanged. Opening a ready scene does not rebuild it. A new coordinate scene uses File → `新建场景…`. A prepared scene can also use File → `导出优化场景 PNG…` to download the current map view or the full site extent; that export does not change the workspace. The existing Job API reports progress and errors. A successful
build writes the standard products under `scenes/<scene_id>/`, after which the
same `site.guided_search` flow is enabled. The objective list is in
`markdown/GUIDED_SEARCH.md`. Set `EXPERIMENT_OUTPUT_ROOT` when the API should read
a directory other than `outputs/`.

In the decision map's File tab, use `另存当前实验…` to name and save every
retained pose, including hidden poses. Deleted poses are excluded. The API
reevaluates the captured poses using the current scene and constraints, then
publishes a separate case under `EXPERIMENT_OUTPUT_ROOT`; the original experiment
is retained. Reopen it through `导入案例`. Repeated names create separate cases.
Saving is available after optimization and pose adjustment finish.

For the production-shaped local stack, use Docker Compose:

```powershell
docker compose -f deploy/compose.yaml up --build
```

This stack uses PostgreSQL and Redis and runs the API and Worker as separate
services. Both services mount the repository `data/` directory read-only at
`/app/data` and share the writable `scenes/` directory at `/app/scenes`, so a
scene rebuild and its road arrays are immediately visible to both containers.
The relative bind-mount paths are resolved from `deploy/` on Windows and Linux.
Docker Desktop is required for this command on Windows.

To rebuild only the prepared `cangnan-utm-v2` road bundle after changing the road
preprocessor, stop new readers, run the guarded road-only rebuild, and restart
the local services:

```powershell
docker compose -f deploy/compose.yaml -f deploy/compose.local.yaml stop api worker
D:\conda_envs\torch311\python.exe -c "from experiments.scene_store import rebuild_scene_roads; print(rebuild_scene_roads('cangnan-utm-v2'))"
docker compose -f deploy/compose.yaml -f deploy/compose.local.yaml up -d --build api worker
```

The rebuild builds and validates both arrays in a temporary directory, then
backs up the current road bundle under `outputs/scene-road-backups/` before
publishing them together with matching metadata. It does not
rewrite DEM, land-use, demand, or user land-use edits. Publication overwrites
the existing road files in place so Windows Docker bind mounts retain their
readable ACLs.

## 13. Build a scene from coordinates

The decision map can submit a center latitude, longitude, and square side
length. The job id is `site.build_scene`. The worker calls the vendored
pipeline in `masking_pipeline/` and then the existing scene reconstruction.
The contract, QA checks, and failure behavior are in
`markdown/DATA_MODULE_SUMMARY.md`.

Put these keys in the gitignored repo-root `.env`. Do not commit the files
they point at:

```text
MASKING_OUTPUT_ROOT=outputs/masking-sites
MASKING_HF_ENDPOINT=https://hf-mirror.com
MASKING_DEVICE=auto
HF_HOME=/absolute/path/huggingface
SCENE_ROOT=scenes
```

The regional OSM extract and DEM are in the repository:

- `masking_pipeline/data/regional/zhejiang-261020.osm.pbf`
- `masking_pipeline/data/regional/wenzhou.tif`
- `masking_pipeline/data/regional/water_polygons.shp` and its `.shx`, `.dbf`, `.prj`, `.cpg` sidecars
- `masking_pipeline/data/regional/water_lines.shp` and its `.shx`, `.dbf`, `.prj`, `.cpg` sidecars

The DEM must cover the requested site. The provincial `zhejiang.tif` is not the default and is not required. `osmium-tool` is optional;
without it the pipeline uses its built-in PBF reader. The first segmentation
job downloads `mfaytin/mask2former-satellite` into `HF_HOME`. Later jobs reuse
that cache. `MASKING_DEVICE=auto` uses CUDA when the installed PyTorch can see
a GPU, and CPU otherwise. `MASKING_DEVICE=cpu` forces CPU. `MASKING_DEVICE=cuda`
fails when CUDA is absent.

Start the API with the research environment (`torch311` or another env that
has the `environment.yml` packages, including `rasterio`, `transformers`, and
`torch`). The slim `backend/requirements.txt` install can serve the API but
cannot run this job. Generated bundles go to `outputs/masking-sites/<site_id>/bundle/`.
The model-ready scene goes to `scenes/<site_id>/`. The four published names are
`{site_id}_satellite_epsg3857.tif`, `{site_id}_landuse.csv`, `{site_id}_dem.tif`,
and `{site_id}_osm_roads_wgs84.geojson`.

When moving a coordinate scene to another machine, copy both its prepared
`scenes/<site_id>/` directory and its four raw bundle files. The `source_files`
entries in `scene.json` use repository-root-relative paths for files inside the
repository; preserve that layout on the destination. External files keep their
absolute paths. Update old machine-specific entries explicitly to the copied
files, following `markdown/DATA_MODULE_SUMMARY.md`. Both `scenes/` and `outputs/`
are gitignored, so pulling GitHub updates does not transfer these generated
bundles. Prepared scene arrays alone support optimization, but rebuilding still
requires the four raw files.

For Compose, keep the API image on `backend/requirements.txt`. The worker image
installs `worker/requirements.txt`, including a CPU PyTorch wheel and
`osmium-tool` plus `libarchive-tools`. The image includes `masking_pipeline/data/regional/`.

```bash
docker compose -f deploy/compose.yaml up --build
```

The API and worker both mount `scenes/` and `outputs/`. A CUDA worker is a
separate image: replace the CPU torch wheel and set `MASKING_DEVICE=cuda` or
`auto`. This guide does not claim that a GPU end-to-end build has been run.

## External road-source trial

Use an existing prepared scene to try a purchased road Shapefile without its
original satellite GeoTIFF. The road import contract is in
`markdown/DATA_MODULE_SUMMARY.md`. Run from the repository root:

```bash
python -m experiments.import_road_shapefile \
  --scene cangnan-utm-v2 --source '温州市_gaode_road.rar' \
  --output-dir outputs/gaode-road-trial-cangnan \
  --provider gaode --buffer-m 500 \
  --exclude-class 在建道路 --exclude-class 天桥 \
  --exclude-class 地道 --exclude-class 其他线路
```

The output directory must be new. Inspect its `import_summary.json`,
`roads_wgs84.geojson`, road arrays, class counts and connectivity before applying.
The buffer and excluded classes are explicit trial choices, not hidden defaults.
When exclusions are requested, the Shapefile must contain the exact `class`
field. Other names such as `fclass` are rejected rather than silently ignored.
RAR inputs need `bsdtar` (libarchive); extracted SHP and ZIP inputs use the same
projection and road-building path. The source's `.prj` determines its CRS.

To publish an inspected trial while the scene has no active jobs:

```bash
python -c "from pathlib import Path; from experiments.import_road_shapefile import apply_road_preview; print(apply_road_preview(Path('scenes/cangnan-utm-v2'), Path('outputs/gaode-road-trial-cangnan'), Path('outputs/scene-road-backups')))"
```

Alternatively, add `--apply` to a fresh trial command to build and publish in one
run. Publication backs up the previous road bundle, rejects a changed scene or
road version, and attempts rollback if writing fails. DEM, land use,
demand and protected farmland stay in place. Reload the page afterward; the GIS
panel shows the road provider. Saved optimization results retain their original
metrics, so run a new search or reevaluate them to use the new road source.
The File → Import Data dialog accepts optional farmland ZIP and road ZIP/RAR
uploads, separately or together. Preview shows access-road overlap, kind counts
and candidate roads on the map. Confirmation updates only the uploaded items.
Imported road GeoJSON is retained inside the scene across full rebuilds. The
Restore OSM button uses that scene's registered original road file; a missing
original file is an explicit error.

If publication and rollback both fail, the scene stays blocked by
`.roads-rebuilding`. The error and marker identify the backup directory; restore
the complete bundle and its originally absent-file state before removing the
marker. Both road publication entry points share this behavior. The authoritative
recovery contract is in `markdown/DATA_MODULE_SUMMARY.md`.

## Guided-search backend selection

`guided_search.evolution_backend` in `config/default_config.json` defaults to `tensor`; set it to `numpy` to use the original evolution implementation. The same parameter is accepted by both guided-search plugins. With CUDA available, the original evolution can still use CUDA model evaluation. Without CUDA, both requests use NumPy evolution and CPU evaluation automatically. Explicit `device: cpu` reproduces this mode on a GPU machine; `device: auto` prefers CUDA.

The CPU path retains initial Adam guidance and all configured population/generation counts. Actual device/backend and any fallback are written to `normalization.json`. Full prepared-scene checks are documented in `markdown/TESTING_STRATEGY.md`; performance experiments that explicitly measure CUDA remain GPU-only.


The default scene id comes from `default_scene` in the project JSON. Its source files are the verified snapshot under `data/sites/cangnan-utm-v2/`; `SOURCES.json` records input hashes. `data.target_grid` explicitly supplies the WGS84 UTM CRS, affine transform and dimensions to both scene preparation and standalone algorithm/modeling entry points. Replacing raw input paths also requires an explicit matching target grid. The original DEM sampling interval is recorded independently of the 1 m working grid.

Legacy scenes can be archived outside the active scene root after their independent metric replacements pass validation. The selector lists the configured default and directories that actually exist, so removing a legacy directory does not recreate an empty preset entry. `experiments.migrate_metric_scene` requires the original imported farmland and road vectors for the expanded extent. Publication evidence and SQLite backups are stored under the chosen migration evidence directory. See `markdown/DATA_MODULE_SUMMARY.md` for the authoritative coordinate and retention rules.

## Transmission routing CLI

The map's top-level "选线" mode exposes the same task: choose a prepared metric scene, pick each fixed connection point on the map or enter its longitude/latitude, fill the required engineering inputs, and submit. It also supports separate no-tower and no-crossing regions, cancellation, four-objective comparison and saved routing history. The first version reports "净空未校核"; it does not check conductor clearance.

The `routing.nsga2` plugin uses the existing Jobs API. A routing task JSON must include `scene_name`, `experiment_name`, WGS84 `start` and `end` objects with `lng`/`lat`, `max_span_m`, `tower_radius_m`, and `max_turn_deg`. Road-control defaults and the optional nested `algorithm` configuration come from the default project configuration. `no_tower_zones` and `no_cross_zones` are arrays of polygon rings in local metric coordinates.

```bash
rtk proxy conda run -n torch311 python -m experiments.launch_routing_run --config /path/to/routing-task.json --output-root outputs
```

The runner reads a prepared scene, copies independent input snapshots, evaluates on CPU and atomically publishes CSV/JSON results. It never rebuilds a scene. The output includes all resolved parameters, input hashes, tower coordinates, per-span reports, and search-range expansion history. Clearance is not checked. For container builds without `.git`, set `SOURCE_REVISION` to record the source revision; a missing revision remains explicitly null.

Real-data acceptance is separate from unit tests:

```bash
rtk proxy conda run -n torch311 python -m experiments.validate_routing --config /path/to/routing-task.json --output-root outputs/validation/routing --repeat
```

Each acceptance directory contains `verified.json` and independent run folders. Search counts exclude the additional final validation/report pass; both are recorded. Snapshot, context, search/report times and evaluations per search second are written to the run summary. Source file hashes accompany the Git revision so local changes can be identified.

Routing execution options are declared in the project's routing JSON: evolution/evaluation backends, device list, evaluation batch size, per-device GPU memory budget and the single-entry CPU context-cache budget (zero disables it). The first device hosts tensor evolution. Current defaults use the complete PILOT tensor evolution and tensor evaluation path on CPU, with a research budget from the single default JSON. Reference evaluation, compiled CPU evaluation and standard NumPy evolution remain explicit options. Existing task JSONs receive defaults only for missing fields; saved values remain unchanged.

`algorithm.search_strategy` selects `standard` or `pilot_reference`. The project default is `pilot_reference` with the hybrid A*/RRT initialization, path variation, elite local search and conditional global injection enabled. PILOT supports NumPy evolution with `devices: ["cpu"]` and reference/compiled CPU evaluation, or tensor evolution together with tensor evaluation on an explicit CPU/CUDA device list. Selecting the strategy from the UI initially keeps the CPU reference settings; selecting tensor evolution also selects tensor evaluation, then enter `cuda:0` or `cuda:0,cuda:1` explicitly. Initialization and fresh global seeds still use the existing CPU planners and compiled CPU evaluation; the evolution operators, geometry and selection use the first device and tensor evaluation can span both cards. CPU final validation remains mandatory. Saved task settings are preserved; the API rejects mixed PILOT NumPy/GPU or tensor/compiled-CPU configurations. Its nested `pilot` configuration comes from the same default JSON and is preserved in saved tasks. An empty enabled-mechanism list in legacy mode reproduces standard NumPy search. The RRT checkbox starts enabled with the project default and can remove only `rrt`, preserving other mechanisms. Switching back to standard clears the mechanism list. Saved tasks resolve newly added PILOT parameter defaults at the plugin boundary; the project default JSON must still contain every field. The implemented CPU components and their verification contract are defined in `markdown/PILOT_ROUTING_MIGRATION.md`.

Within the CPU reference strategy, `pilot.initialization_mode` selects legacy, seed pruning, a balanced initial population, or balanced initialization with reference-anchored tower-range probes (`legacy`, `pruned`, `balanced`, `bounded`), or the migrated multi-scale A*/RRT hybrid (`hybrid`). The UI also exposes the initialization evaluation cap as a population multiplier. Every full pruning/filling evaluation counts toward the unchanged total budget. Saved tasks retain the mode and explicit cap; missing historical modes resolve to legacy. Returning to standard clears the experimental mode. An empty mechanism list with a non-legacy mode is an explicit initialization control experiment, not a replay of standard search. No mode is a claim of improved quality; consult the experiment log for measured scope.

Routing stops after `max_generations` complete iterations. Initialization is outside that count. One iteration evaluates `popsize` offspring and then runs any local search or global injection scheduled for that generation. Evaluation count is recorded and does not stop the run. Saved tasks that predate `max_generations` use `ceil(max_evaluations / popsize)` generations. The summary records `generation_count` and `initialization_evaluations`. Use "恢复当前算法默认参数" to adopt current algorithm defaults while preserving connection points, engineering constraints and regions.

Run repeatable performance and quality matrices with `python -m experiments.benchmark_routing --manifest /path/to/manifest.json --output-root /path/to/new-directory`. The manifest provides task paths, named cases with routing overrides, seeds, warmup/repeat counts and search-time checkpoints. The benchmark saves full compact candidate coordinates and scores, source hashes, runtime/memory records and a frozen best-known reference front. It is separate from published software artifacts; no conductor-clearance check or global-optimality claim is implied.

For several problems in the same scene, specify tasks as `{"id": "nanxi-100m", "config": "/path/to/task.json"}`. Each ID owns an independent result directory and reference front. Existing task-path strings continue to use the scene ID as the result directory.

A case may set `publish: true` to replay a complete task in its own publication directory after each search benchmark. The additional timing includes a new independent snapshot, context, full CPU report and streamed CSV/JSON output. Set that case's `context_cache_mib` override to zero when comparing cold end-to-end runs. The extra replay has its own recorded evaluation count and is not part of the measured search pass.

On this workstation, the validated low-memory CUDA choice is `evolution_backend: tensor`, `evaluation_backend: compiled_cpu`, and `devices: ["cuda:0"]`. Select the device under the routing workspace's advanced parameters, or override the same fields in the task JSON. Population and evaluation counts remain explicit research choices. Tensor evaluation can use one or both CUDA devices; its measured benefit depends on scene and batch size. The default device remains CPU for portability.


## Routing research composition

`routing_search(problem, config, reporter=None)` remains the public search entry. Internal experiments can use `algorithms.routing.search.run_with_components` with an explicit `SearchComponents(initializer, driver)`. The native driver must match `config.evolution_backend`; NumPy and tensor variation remain separate implementations. Operator injection does not add Jobs fields or UI options, and changing evolution does not implicitly change seed filling.

See `markdown/ALGORITHMS_MODULE_SUMMARY.md` for the authoritative composition example and `markdown/TESTING_STRATEGY.md` for source-snapshot and real-matrix equivalence commands. Algorithm parameters still come from `config/default_config.json`; this refactor does not introduce new defaults.

## Full PILOT CPU experiment

The project default already uses the full PILOT component set. To prepare an explicit CPU reference task while preserving its engineering inputs, replace only its algorithm block using the sole default configuration:

```python
from dataclasses import asdict, replace
import json
from pathlib import Path
from config.project_config import load_default_config

task_path = Path("/path/to/routing-task.json")
task = json.loads(task_path.read_text())
base = load_default_config().routing
mechanisms = ["astar", "rrt", "nearby_crossover",
              "distinct_parents", "path_mutation", "shorten", "smooth",
              "elite_local_search", "global_injection", "population_dedup"]
config = replace(base, search_strategy="pilot_reference", evolution_backend="numpy",
                 evaluation_backend="compiled_cpu", devices=["cpu"],
                 pilot=replace(base.pilot, initialization_mode="hybrid",
                               enabled_mechanisms=mechanisms))
task["algorithm"] = asdict(config)
Path("/path/to/new-pilot-task.json").write_text(json.dumps(task, indent=2))
```

Run this new task with the routing CLI or Jobs API. This example selects the CPU reference execution explicitly; the same mechanism list is enabled by the project default tensor path. The UI supports hybrid initialization and displays all mechanisms retained from task history. Local/global internal trials share the total budget, so the actual number of generations is smaller than the simple budget/population upper bound. Production code never imports the frozen original source.

Correctness probes use `python -m experiments.validate_pilot_components --tasks ... --mechanisms ... --mode hybrid --seed ... --evaluations ... --output /path/to/new-directory --job`. They suppress quality computation and isolate Job publication. Completed experiments and final diagnosis artifacts are indexed only in `markdown/EXPERIMENT_LOG.md`.
