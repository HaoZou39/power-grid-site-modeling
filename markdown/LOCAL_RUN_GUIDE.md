# Local End-to-End Run Guide

This is the environment guide for people working on this repository. The recorded Windows verification later in this file is one successful machine, not a second setup procedure.

## Environment for collaborators

### Tools

- Git, to clone `https://github.com/HaoZou39/power-grid-site-modeling.git`
- Conda
- An NVIDIA GPU and a driver that can run the CUDA build in `environment.yml`
- Node.js 22 or newer, and npm, for the decision map
- The raw files listed below, under `data/`

The search and modeling checks require CUDA. The default configuration does not fall back to CPU.

### Python

From the repository root, create the environment named in `environment.yml`:

```bash
conda env create -f environment.yml
```

If `torch311` already exists, update it instead of creating a second environment:

```bash
conda env update -n torch311 -f environment.yml --prune
```

That file installs Python 3.11 and PyTorch 2.11.0 with CUDA 12.8, plus NumPy, SciPy, Matplotlib, Rasterio, PyProj, Shapely, pytest, pycma, TensorBoard, FastAPI, and Uvicorn. Check that this interpreter can see a GPU:

```bash
conda run -n torch311 python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

Stop if `cuda_available` is `False`. Use this same `torch311` interpreter for pytest, modeling checks, and the API. A different system Python will not have the project dependencies.

### Data files

These four inputs must be present in `data/`:

```text
苍南10m84_clip_1800m_10m_180x180_3857.tif
satellite_27.501662_120.194639_r0.90km_z18_crop_epsg3857.tif
satellite_27.501662_120.194639_r0.90km_z18_crop_epsg3857_routing_coarse_mask_downsampled.csv
osm_roads_27.501662_120.194639_r0.90km_wgs84.geojson
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

`frontend/package.json` asks for Node.js 22 or newer. The dev server listens on port 5176 and forwards `/api` to `http://127.0.0.1:8010`, so colleagues open only the page. On this machine that address is `http://10.28.0.176:5176`. On another machine, use that machine's LAN address with port 5176. The same page on the server itself is `http://127.0.0.1:5176`.

Without `REDIS_URL`, the API keeps jobs in memory and runs them in a background thread. Set `DATABASE_URL=sqlite:///outputs/v0/jobs.db` when a local file-backed job store is needed.

The map assistant reads `AGENT_BASE_URL`, `AGENT_MODEL`, and `AGENT_API_KEY` from the API process. Names and the confirm flow are in `markdown/AGENT_MODULE.md`. A missing value makes the assistant return 503. Do not commit `.env`.

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

The code validates CUDA at startup and does not fall back to CPU. A CUDA-capable NVIDIA GPU is therefore required by the current default configuration.

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

Stop here if `cuda_available` is `False`. The current project deliberately raises an error instead of silently running on CPU.

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
| `all_candidates_points_map.png`         | Centers of all hard-feasible candidates.                                                                               |
| `all_candidates_footprints_map.png`     | Footprints of all hard-feasible candidates.                                                                            |
| `pareto_points_map.png`                 | Centers of the Pareto solutions.                                                                                       |
| `pareto_footprints_map.png`             | Footprints of the Pareto solutions.                                                                                    |
| `pareto_3d_interactive.html`            | Interactive plot of `dem_soft`, `road_distance`, and `demand_distance`.                                           |
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

Open the generated PNG files with any image viewer. Open the self-contained interactive Pareto plot in a browser:

```text
outputs/local_run_guide_cma_es/pareto_3d_interactive.html
```

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
conda run -n torch311 python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
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

Start the API and the decision map with the commands in "Environment for collaborators" above. Use the `torch311` interpreter. Do not start the API with a different system Python.

Open `http://127.0.0.1:5176`. The page is the decision map. It prepares a scene, then runs `site.nsga2`. The objective list is in `markdown/NSGA2.md`. Set `EXPERIMENT_OUTPUT_ROOT` when the API should read a directory other than `outputs/`.

For the production-shaped local stack, use Docker Compose:

```powershell
docker compose -f deploy/compose.yaml up --build
```

This stack uses PostgreSQL and Redis and runs the API and Worker as separate
services. Docker Desktop is required for this command.
