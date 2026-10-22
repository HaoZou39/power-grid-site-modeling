# Testing Strategy

Pytest protects small deterministic domain contracts. Real-data studies, large matrices, GPU memory measurements and full research experiments belong in `experiments/validate_*.py` or the documented comparison scripts.

## Pytest responsibilities

1. Landuse class mapping to obstacles and metadata.
2. Continuous 1 m poses, safe margins, partition bounds and footprints.
3. CPU and CUDA soft-objective forward/backward with finite gradients.
4. Hand-calculated hard terrain and obstacle metrics.
5. Explicit rejection of invalid shapes, devices, values and class IDs.
6. Road connectivity: connected, partially reachable and wholly unreachable gates, projection within a road segment, and prepared-scene regressions.
7. Road simplification: preserve shared nodes and junctions while keeping separate roads, nearby parallel lines and different-level crossings disconnected. Road-only publication must preserve other products and restore failures.
8. Building avoidance and road setback: reuse the haul-field road-cell definition. Union remote-sensing class 3 with OSM centerlines and expand by configurable `road_setback_m` (default 5 m; 0 forbids only the road cells) with a 1 m distance transform. A rotated footprint that covers any buffer cell is infeasible, together with landuse and drawn constraints. The candidate's gate and transport metrics stay unchanged.
9. Reports and searches must share field/mountain policies, building/water constraints, exclusions, feasible zones and origins. Cover explicit masks and complete/partial API constraint fields.
10. Haul-field route reconstruction: predecessor and gate-owner dtypes, exact metric agreement, contact/segment identity, the 5 cm terminal rule, report-cache invalidation and reachable/infeasible handling.

Tests do not rebuild real scenes or read raw DEM files. Prepared Cangnan regression tests may read existing standard arrays and the fixed 40-pose CSV fixture; they skip when that scene is absent. Historical pose metrics are not treated as the current path-selection optimum. Job-output tests write only to pytest temporary directories. Formal experiment outputs remain outside pytest.

`tests/test_road_voronoi.py` checks CPU/NumPy/CUDA label equality on small
grids, pixel/segment chunk tails, fractional resolutions, shared endpoints,
cross-tile ties, invalid inputs, dependency/device fallback, and saved product
metadata. CUDA cases require CUDA and Triton; CPU cases always run.
Evolution-backend synthetic scenes provide explicit landuse classes consistent
with their obstacle masks, so the current road-setback context is exercised on
both CPU and CUDA.
They also verify actual CPU/GPU execution messages, distinguish NumPy evolution
with CUDA evaluation, check monotonic progress and the final-report phase, and
require the saved execution description to agree with the running messages.
`python -m experiments.compare_road_voronoi --output-dir outputs/road-voronoi-check --threads 64`
separately measures the original scene and complete 9000×9000 scaled/tiled
stress grids against the original CPU source. It reports first and warm calls,
full-grid mismatches and hashes, CUDA allocated/reserved peaks, cumulative
process RSS, and explicit synthetic-input provenance. Timing excludes disk I/O
and comparison but includes output allocation and device-to-host copies.

## Core checks

### 1. Landuse mapping

For classes `[[0,1,2],[3,4,5]]`, expect obstacle mask `[[0,1,1],[1,0,1]]`. Classes 0 (other) and 4 (mountain/natural) are buildable; classes 1 (field), 2 (building), 3 (road) and 5 (water) are obstacles. Require these meanings in metadata and reject unknown class IDs.

### 2. Pose and footprints

On a small grid, require `[B,3]` poses inside the safe center bounds and angles within `[-pi,pi]`. Soft grids and weights remain on the input device; hard indices are nonempty integer row/column pairs. Cover optional partition bounds, boundary contact and overhangs.

### 3. Soft objectives on CPU and CUDA

Use synthetic terrain, obstacles, roads and demand points. Every loss has shape `[B]`, is finite and stays on its input device. Backpropagation must produce finite raw-pose gradients on the same device. Mixed input devices must raise a clear error. Test CPU explicitly even when a GPU is available.

### 4. Hard metrics

Check DEM variance/range and obstacle count/ratio against small NumPy examples. These report metrics do not participate in backpropagation.

### 5. Invalid inputs

Reject inconsistent devices, wrong shapes, NaN/Inf, unknown landuse classes, negative or zero-total demand weights, and road Voronoi IDs outside the segment table. CPU tensors are supported and are not invalid inputs.

## Real-data validation

The CUDA modeling acceptance script remains explicit:

```bash
conda run -n torch311 python experiments/validate_modeling.py
```

It writes configuration, matrix shapes, CUDA memory, soft gradients and hard metrics to its output directory. Guided-search CPU fallback has a separate acceptance entry below.

## v0.1 software shell checks

The web shell has a separate small deterministic pytest set in
`tests/test_v0_plugins.py` and `tests/test_v0_api.py`. It verifies the explicit
plugin registry, configuration rejection, job state and result persistence,
API transport, the local embedded worker, explicit registry injection, plugin
failure status persistence, schema defaults, and adding a second plugin without
changing the job service. These tests use SQLite and an in-memory queue; they do
not read real GIS inputs or require Docker.

Run the web-shell tests in the same `torch311` environment used by the
repository-wide command. The web dependencies are declared in
`environment.yml`:

```bash
conda env update -n torch311 -f environment.yml
conda run -n torch311 pytest -q tests/test_v0_plugins.py tests/test_v0_api.py
```

The web shell also tests experiment catalog discovery, artifact URL serving,
path traversal rejection, and the shared experiment output writer. These tests
use temporary directories and synthetic arrays; they do not depend on the
tracked experiment outputs.

`tests/test_coordinate_scene.py` covers the coordinate-to-scene job with a
mocked pipeline and synthetic GeoTIFFs. It does not download imagery or run
Mask2Former. The command is:

```bash
conda run -n torch311 pytest -q tests/test_coordinate_scene.py tests/test_scene_store.py tests/test_v0_plugins.py tests/test_site_plugin_schema.py
```

`tests/test_partitioned_search.py` verifies deterministic 4/6-way rectangle
planning, safe bounds, bounded worker concurrency, shared-field global
rescoring, and merged partition provenance without loading a real scene or
starting CUDA searches. `tests/test_pose_and_masks_cuda.py` checks that the
optional pose bounds stay inside the scene-safe interval. Run the focused
checks with:

```bash
conda run -n torch311 pytest -q tests/test_partitioned_search.py tests/test_pose_and_masks_cuda.py tests/test_site_plugin_schema.py tests/test_v0_plugins.py
```

The frontend compile check is `npm run build` from `frontend/`. Docker Compose
checks require Docker Desktop and are separate from pytest.

## Assistant checks

`tests/test_agent.py` uses a scripted model. It checks the edit-op contract,
the instruction cards, the loop guard, and the scoring rules of the
assistant evaluation. It never calls a real model. `tests/test_agent_memory.py`
checks the memory file format, memory changes, scene filtering, and the memory
routes. It points `AGENT_MEMORY_PATH` at a temporary file, so it never touches
`memory/MEMORY.md`. `tests/test_agent_analysis.py` checks the footprint
terrain summary on a synthetic grid, solution ranking with ties, the
`analyze_pose` result when the access report fails, the attached-solution
note and its 422 route, and the pose-objectives route with a stubbed scorer.
`tests/test_guided_search.py` checks on CUDA that rescoring the search's own
poses reproduces their rows, so moved schemes use the search's numbers. `tests/test_agent_preference.py` checks the shared
normalization (a flatness-first user must get the flattest scheme), skipping
history with other objectives, diversity, and the choice route against a
temporary file. `tests/test_agent_sync.py` fails when the assistant falls
behind the software: the tool table in `markdown/AGENT_MODULE.md` must match
the registry, the frontend objective keys must match `RANKED_OBJECTIVES`, and
evaluation cases may only expect registered tools.

`experiments/agent_eval.py` scores the configured model against
`experiments/agent_eval_cases.json` and writes to `outputs/agent_eval/`. It
needs network access and model credentials, so it stays out of pytest. Run it
after changing `agent/prompts.py`, `agent/loop.py`, or the model, and record
the result in `markdown/EXPERIMENT_LOG.md`. Case format and scoring are in
`markdown/AGENT_MODULE.md`.

## Origin-change cache checks

Compare reused fields with uncached builds for every grid cell and reconstructed route. Require exact equality for lengths, rise, gate ownership, reachability and predecessors. Cover both movement modes, multiple elevation weights, off-road origins, origin removal and disconnected road components. Cache hits must skip grid expansion; changes to scene inputs, constraints, movement mode or elevation weight must invalidate the cache. Corrupt settlement orders must be rejected and rebuilt.

```bash
python -m experiments.validate_haul_origin_cache --reference-commit b54dcaf --output-dir outputs/validate-haul-origin-cache
python -m experiments.validate_haul_origin_cache --reference-commit b54dcaf --diagonal --output-dir outputs/validate-haul-origin-cache-diagonal
```

The reference revision supplies the remote weighted-Dijkstra builder. The validator compares every original field array, sampled continuous queries and complete routes, and records cold-build and cache-rebind times in `summary.json`. It uses a temporary cache and leaves the prepared scene unchanged. Its warm-up excludes one-time JIT compilation from timings. The former FIFO benchmark remains a historical experiment and does not establish the current speedup.

## Remote integration acceptance

Before publishing a selective integration, run the repository-wide pytest suite with CUDA, the frontend `test:problem-snapshot` script and `npm run build`. Compare prepared-scene fields against the current remote revision in both movement modes using the validator above. For the application check, submit a default guided-search job through the API on the prepared Cangnan scene, then an eight-neighbor job with an origin. Require complete artifact downloads, rescore every returned pose through `pose-objectives`, and compare every Pareto report with its CSV transport metrics. Use a separate checkout, scene cache and experiment output directory. Record completed results in `markdown/EXPERIMENT_LOG.md`.

## Population initialization

`tests/test_initialization.py` protects seed reproducibility, legacy Gaussian draws, the decoded uniform domain, and every pair of Taguchi factor levels. The orthogonal design uses exactly `s*s` rows; non-square populations are rejected instead of truncating an array. CUDA guidance/search checks run all three methods on a tiny scene. Plugin and configuration tests protect the population default of 100, initialization selection and its saved metadata.

The CUDA search checks also compare every returned raw pose with the selected evolutionary endpoint, with and without partition bounds. Search output must not apply any post-evolution local refinement. The initial gradient guide remains covered separately.

Run the prepared-scene comparison without opening a browser:

```bash
python -m experiments.compare_initialization --output-dir outputs/initialization_comparison_20261022
```

The comparison uses paired seeds and unchanged search/scene settings. It records input and source hashes, configuration, initial/guided/final CSVs and timing. The 100-member methods share an evaluation budget; the legacy 40-member arm has a smaller budget. HV and IGD+ use one common empirical reference and normalization across all runs. Spatial-cell counts are occupancy measures, not certified feasible-region coverage. This experiment stays outside pytest.

## Tensor NSGA-II checks

`tests/test_tensor_nsga2.py` compares constrained dominance, ranks, crowding and survivor selection against an independent scalar reference on CPU and CUDA. Fixtures include equal objectives, zero spans, complete chains, tradeoffs, feasible candidates and tied positive violations. Fixed random inputs check that batched tournaments, arithmetic crossover and Gaussian mutation preserve the operator definitions; repeated runs check the local torch generator.

`tests/test_tensor_hard_metrics.py` compares device footprint violations with the report geometry for random rotations, obstacles, border contact, overhangs and completely outside poses. `tests/test_guided_search.py` compares batched objectives and violations with the full existing evaluator for both origin modes, demand settings and multiple batch sizes. `tests/test_tensor_haul.py` checks all cells and continuous offsets on a synthetic disconnected road network in both movement modes, including the 5 cm endpoint rule and origin restrictions. Existing guidance and partition tests continue to cover bounded searches.

Run the full CUDA pytest suite before accepting the change. Performance is a separate headless experiment:

```bash
python -m experiments.compare_tensor_nsga2 --baseline-ref 6740ce9 --output-dir outputs/tensor-nsga2-comparison --populations 100 400 1000 --seeds 123 456 789 1011 1213
```

The Git revision supplies only the previous search implementation; initialization, guidance, scene inputs, constraints and field are shared. Warm full-search timings include initialization, guidance, evolution and final reports. Record field construction, first calls and peak CUDA allocation separately. Compare feasible fronts using a shared empirical reference and record completed experiments in `markdown/EXPERIMENT_LOG.md`. A larger population is accepted as fitting the former time budget only when measured full-search timings support that claim.

## Selectable evolution backends and CPU fallback

`tests/test_evolution_backends.py` checks the `tensor` default, explicit `numpy`, unavailable CUDA, forced CPU, invalid selectors and device indices. The NumPy operator regression uses a fixed population from revision `6740ce9`. CPU searches cover all initializers, partition bounds, initial Adam guidance, exact rescoring, partition inheritance and a complete temporary job with normal CSV/figure artifacts. CPU/CUDA model checks share formulas and compare objective values.

Run the full suite on CUDA and a separate process with CUDA hidden:

```bash
pytest -q
CUDA_VISIBLE_DEVICES="" OMP_NUM_THREADS=4 pytest -q tests/test_evolution_backends.py -k 'not test_cuda'
```

Use the prepared scene for full default-size acceptance:

```bash
python -m experiments.validate_evolution_backends --output-dir outputs/backend-validation-gpu
CUDA_VISIBLE_DEVICES="" OMP_NUM_THREADS=4 python -m experiments.validate_evolution_backends --output-dir outputs/backend-validation-cpu
```

Both requests must complete on a CPU-only process using the NumPy backend, with identical outputs and exact report rescoring. On CUDA, both selected backends must run; `--reference-dir` may point to the earlier 100-population tensorization comparison for byte-level CSV regression. Runtime metadata records requested/effective backend and actual model device. Record completed acceptance runs in `markdown/EXPERIMENT_LOG.md`.
