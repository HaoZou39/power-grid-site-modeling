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
11. Landuse revisions: saved and deleted building patches change pose feasibility;
    unchanged road/farmland products must not suppress frontend reevaluation.
    Late responses from an older landuse revision cannot replace current metrics,
    and pending assistant snapshots omit stale objectives and feasibility.
12. Access barriers: ordinary-road cells shared with surface highways or ramps
    must use the same connector blocking check as gates. Cover origins present
    and absent, protected farmland, and passable surface above tunnels. Cache
    reuse preserves intrinsic gate validity separately from network reachability,
    including after disk reload and origin changes; values and routes must match
    a fresh field exactly. Missing or incompatible gate-validity arrays rebuild.

Tests do not rebuild real scenes or read raw DEM files. Prepared Cangnan regression tests may read existing standard arrays and the fixed 40-pose CSV fixture; they skip when that scene is absent. Historical pose metrics are not treated as the current path-selection optimum. Job-output tests write only to pytest temporary directories. Formal experiment outputs remain outside pytest.

The autouse scene-root fixture isolates the scene registry, experiment output and
favorite database from the running application, including its worker lock.
Tests needing the historical Cangnan fixture use its explicit
path. Metric-migration tests cover original-vector requirements, source-version
changes, preservation of legacy bytes, geographic favorite copying, and cleanup
after a failed publication. Real migrations and Chromium acceptance remain
separate validations recorded in `markdown/EXPERIMENT_LOG.md`.

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

Scene adoption must copy mutable products independently. Hardlink regressions
publish and roll back a road bundle while verifying historical experiment bytes
remain unchanged. The link audit verifies independent, hashed snapshots before
detaching scene files. Kernel-lock tests use a separate process, kill the owner,
and verify exclusion and automatic release without PID-based stale detection.
Scene reconstruction and landuse edits share the publication lock; snapshot
reads release it before objective evaluation.

`tests/test_save_workspace.py` covers named manual saves with fresh objective
evaluation, retained hidden/manual/infeasible poses, independent same-name copies,
source preservation, display-name/path separation, validation, busy scenes,
scene changes during evaluation and cleanup after write/publication failures.
Frontend save tests check merged current edits and retained hidden poses, complete
reload and saved baselines. Browser acceptance must delete poses, save under a
custom name, reload the case and verify deleted IDs never return, including when
the last visible pose was deleted but hidden poses remain.

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

Job lifecycle regressions cover cancellation acknowledgement, busy scenes while
cancelling, atomic claims under duplicate delivery, and restart recovery from a
persistent SQLite database. The local and Compose executors share an exclusive
worker lock. Public job serialization excludes historical traceback fields.
Redis/PostgreSQL fault acceptance requires real temporary services; unavailable
services must be reported as unverified rather than silently counted as passed.

The web shell has a separate small deterministic pytest set in
`tests/test_v0_plugins.py` and `tests/test_v0_api.py`. It verifies the explicit
plugin registry, configuration rejection, job state and result persistence,
API transport, the local embedded worker, explicit registry injection, plugin
failure status persistence, schema defaults, and adding a second plugin without
changing the job service. These tests use SQLite and an in-memory queue; they do
not read real GIS inputs or require Docker.

Run the web-shell tests in the same `torch311` environment used by the
repository-wide command. The web dependencies are declared in
`requirements.txt`, included by `environment.yml`:

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
Mask2Former.

`tests/test_scene_store.py` also verifies that source paths inside the repository
are saved relative to its root, survive moving the repository together with the
raw bundle, and rebuild correctly from a different working directory. External
absolute source paths retain their meaning. Missing raw inputs must fail before
publishing or modifying an existing scene; prepared arrays do not replace them.

Run these checks with:

```bash
conda run -n torch311 pytest -q tests/test_coordinate_scene.py tests/test_scene_store.py tests/test_v0_plugins.py tests/test_site_plugin_schema.py
```

`tests/test_road_import.py` covers external line sources on a synthetic prepared
grid without a reference GeoTIFF, explicit class exclusion, junction-preserving
simplification, ZIP extraction, preview isolation, non-road data preservation,
complete rollback after an interrupted road publication, and rejection of
stale grid/road versions. Failure injection covers both road publication entry
points: a second failure during rollback must preserve the read-blocking marker
and report a complete backup, including failures after some files were restored.
Successful rollback restores originally absent sidecars to absence. Incomplete
candidate bundles fail before backing up or modifying the published scene.
SHP and ZIP inputs with exclusions must reject a missing `class` field before
building candidates; the same schema remains valid without exclusions.
Road-building defaults are read from the project
configuration. Run it with the existing traffic and Voronoi checks:

```bash
conda run -n torch311 pytest -q tests/test_road_import.py tests/test_traffic_topology.py tests/test_road_voronoi.py tests/test_scene_store.py
```

Real imported-road comparisons belong in `outputs/` and the experiment log;
they report source CRS, class policy, topology, nearest-road checks and map
alignment separately. Agreement with OSM is not ground-truth accuracy.

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

The map gesture checks cover erasing an optimization footprint above underlying
landuse or regions while preserving favorite priority. Decision-map checks cover
single-solution removal from the diversity cache, selection and reference cleanup,
stale report rejection, and refusal during optimization or objective evaluation.
These checks run in `npm run test:problem-snapshot`.

Coordinate checks use independent pyproj controls for northern and southern UTM
scenes, a zone boundary, and the legacy Web Mercator frame. Browser acceptance
verifies north-up cameras after loading, switching scenes, locating and exporting;
right-drag, two-finger twist and Shift+arrow keys must not rotate the map, while
normal panning and pinch zoom remain available. Export cleanup must preserve
the rotation restrictions. Isolated camera checks reuse captured scene and plugin
responses and fixed tiles; they make no writes to saved favorites or scene data.

### Favorite sites

Both map-picked sites and optimization results use the same favorite store and
CRUD API. `npm run test:favorites` covers creation without a search, duplicate
suppression, persistence reload, movement and rotation, rejected writes,
initial-load/write ordering, and stale responses after scene changes. Evaluation
checks require the full current constraints and the favorite's own dimensions,
objectives before the transport report, and rejection of obsolete responses.
The map gesture check covers selecting and dragging a different favorite in one
gesture. These checks also run in `npm run test:problem-snapshot`.

`tests/test_favorites_api.py` verifies SQLite reopening, scene isolation, both
creation payloads, pose evaluation through the search scorer, and a stable
default database path across working directories. Run it with
`pytest -q tests/test_favorites_api.py`. Use a temporary database and small
synthetic scene for evaluation; never modify a user's saved favorites. Browser
acceptance checks both entry points, movement, rotation, page reload, and an API
restart. A saved site outside an optimization feasible region remains a favorite
and is evaluated as infeasible under those constraints.

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

`tests/test_initialization.py` protects seed reproducibility, legacy Gaussian draws, the decoded uniform domain, and every pair of Taguchi factor levels, including the 10000-member design. The orthogonal design uses exactly `s*s` rows; non-square populations are rejected instead of truncating an array. CUDA guidance/search checks run all three methods on a tiny scene. Plugin and configuration tests protect initialization selection and its saved metadata. `tests/test_project_config.py` and `tests/test_site_plugin_schema.py` require every plugin form default and the assistant's stated population to equal `config/default_config.json`, and reject a JSON section with a missing or unknown parameter. Tests build small configurations with `replace(load_default_config().<section>, ...)` instead of literal defaults.

The CUDA search checks also compare every returned raw pose with the selected evolutionary endpoint, with and without partition bounds. Search output must not apply any post-evolution local refinement. The initial gradient guide remains covered separately.

Fast initialization checks use synthetic concave/disconnected feasible polygons, interior exclusions, an exclusion-only domain, small allowed regions, fractional partition bounds and an empty domain. Decode all initial centers and require zero forbidden cells, including after Adam guidance. Protect population size, seed reproducibility, area-weighted uniform sampling, explicit failure on an empty domain, and effective uniform selection for constrained Taguchi requests. These checks do not run evolution or benchmark final search quality; full-footprint and road reachability remain separate hard constraints. Historical three-method comparisons must reject domains that would replace the requested method with uniform sampling.

Run the prepared-scene comparison without opening a browser:

```bash
python -m experiments.compare_initialization --output-dir outputs/initialization_comparison_20261022
```

The comparison uses paired seeds and unchanged search/scene settings. It records input and source hashes, configuration, initial/guided/final CSVs and timing. The 100-member methods share an evaluation budget; the legacy 40-member arm has a smaller budget. HV and IGD+ use one common empirical reference and normalization across all runs. Spatial-cell counts are occupancy measures, not certified feasible-region coverage. This experiment stays outside pytest.

## Tensor NSGA-II checks

`tests/test_tensor_nsga2.py` compares constrained dominance, ranks, crowding and survivor selection against an independent scalar reference on CPU and CUDA. Fixtures include equal objectives, zero spans, complete chains, tradeoffs, feasible candidates and tied positive violations. Fixed random inputs check that batched tournaments, arithmetic crossover and Gaussian mutation preserve the operator definitions; repeated runs check the local torch generator. Ranking runs with both a tiny `TILE_PAIRS` and the default value, so the tiled dominance counts must give the same ranks as one full block.

`tests/test_search_guide.py::test_chunked_guidance_matches_one_batch` runs the Adam guide once with `guide_batch_size` equal to the population and once with a small block, and requires the same final raw poses.

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

### Road kinds and unified data imports

`tests/test_road_kinds.py` checks classification priority, segment alignment,
access-only Voronoi labels with full-array IDs, explicit ordinary-road contacts,
highway transport, surface barriers, tunnels and building setbacks.
`tests/test_scene_data_import.py` covers all three upload combinations, stale
previews, joint rollback, failed rollback protection, retained provenance,
scene-specific OSM restoration, full rebuild retention and the multipart API.
The overlap check changes road kinds after an import to catch stale statistics.
Frontend tests cover evaluation keys and data versions, 200-pose batches,
manual baselines, deletion selection, diversity/PNG behavior and upload fields.
The card and eraser share one deletion handler. Its behavior checks cover busy
states, hidden-pose retention, selected/non-selected deletion, stale report
invalidation and clearing the final retained pose; gesture checks preserve
solution/favorite/landuse hit priority without requiring WebGL.
Real-scene migrations must back up the bundle and assert byte-identical segment
files before publishing. Sample Voronoi distances and gate contacts independently;
record screenshots and acceptance results in the experiment log. External model
evaluation is separate and requires authorization to send its cases and prompts.

## Worker fault acceptance

`python -m experiments.validate_job_recovery --output-dir <new-directory>` starts
isolated PostgreSQL and Redis containers on random localhost ports, checks both
repository adapters, kills a worker during a paused plugin, rejects a concurrent
worker, and verifies queued-job recovery. Containers and child processes are
removed even on failure. It never uses the deployment database. Docker images
must be available; the Docker Official Images public ECR mirror is used by this
entry. Logs and summary remain in the requested output directory.

## Building masks and validation entries

Setback tests cover ramps and surface highways with the same configured radius,
independent haul walkability, and a boundary-pose soft gradient that points away
from the road. Data and context parameters must come from the loaded JSON;
custom partition and overlay tests use a deliberately different highway radius.
DEM tests distinguish uncovered/missing data from valid zero elevation. Small
GeoTIFF/CSV/GeoJSON inputs exercise all three road validation entry points,
including CUDA gradients. CMA-ES rejects seed zero before starting a search.


The repair acceptance artifacts under `outputs/validation/` distinguish deterministic tests from actual service checks. `experiments/benchmark_pareto.py` compares 40,000 identical three-objective records against a chosen Git baseline in isolated processes on the same CPU. It verifies ordered front hashes, timing medians and peak RSS; performance thresholds do not belong in pytest. `experiments/validate_job_recovery.py --output-dir <new-directory>` runs the database contract on actual PostgreSQL and Redis and kills/restarts the actual Worker. Use an isolated directory and never point fault validation at a deployed database.

Browser acceptance uses a temporary pinned Playwright installation outside the repository, real Chromium, an isolated API/database and synthetic scene. Fixed background tiles remove external imagery latency while map geometry and API evaluation run normally. Recorded checks include multi-digit angle input, setback commits, retry after an injected request failure, Esc during dragging, stable report request keys and changed footprint pixels in downloaded PNGs. Nginx acceptance sends two valid 80 MiB ZIPs through the actual container and separately checks proxy and per-file limits.

## Routing contracts

`test_pilot_integration.py` checks empty-strategy NumPy replay, strict nested configuration, shared total and per-call phase budgets, private random streams, continuous path conversion and incremental geometry against complete route feasibility. The optional CPU strategy must preserve every coordinate/objective hash when all migrated mechanisms are disabled. Real three-problem replay, repeated seeds, published Jobs and browser checks remain separate experiments.

`test_pilot_rrt.py` compares extension/backtracking and rejected nearest-branch traces with the frozen original function under controlled random inputs. It also checks cancellation, exhausted target sampling, fixed endpoints on blocked land, legal water crossings, bounded real seed injection and saved parameter migration. RRT's actual tree successes and unique feasible seeds are reported independently from the existing A* fallback. Formal benefits use the preregistered initial-shape-diversity gate and shared-reference quality nonregression checks.

`test_pilot_initialization.py` covers opt-in processed seeds, a filled initial population with bounded RRT provenance, budget exhaustion with explicit evaluated-state reuse, expansion anchors that preserve existing long seeds, historical mode defaults, and rejection of deletions that increase crossing. Real comparisons separate preprocessing, filling, and anchored expansion; calibration trials do not count as the five-seed confirmation gate. Keep coordinate/objective prefix replay against frozen legacy results when changing the initialization interface.

`test_pilot_source.py` executes selected functions from hash-verified PILOT source snapshots with deterministic dependency and RNG bindings. It covers source identity, hand-calculated adaptive radii, constrained candidate acceptance, RRT goal-biased extension/backtracking and spatial crossover traces without importing the old application. Migration scope and per-round gates are defined in `markdown/PILOT_ROUTING_MIGRATION.md`.

`test_pilot_migration_metrics.py` checks independent geometric-diversity values, paired-seed gates, no-gain and regression rejection, and comparison of saved candidate artifacts. `experiments.compare_pilot_migration` validates engineering inputs, data hashes and evaluation budgets before constructing a joint reference front. Explicit protocols select the primary metric and all thresholds before candidate trials.

`test_routing_config.py`, `test_routing_context.py`, `test_routing_evaluator.py`, `test_routing_initialization.py` and `test_routing_search.py` use synthetic metric grids, analytic lengths and independent polygon intersections. They cover fixed endpoints, full circular footprints, landuse/farmland rules, road-control unions, local turns, tower-range expansion, deterministic seeds and evaluation budgets.

`test_routing_navigation.py` checks a legal-tower graph whose edges may cross non-buildable land, including water crossings, detours around barriers wider than a span, forbidden-crossing polygons, fixed endpoints, cancellation and bounded scene traversal. Search tests cover initialization consuming the entire budget and partial final generations in both evolution backends. Real failure replays must preserve the saved connection points, engineering inputs and original evaluation budget before testing larger defaults; increasing the budget alone is not evidence that initialization was fixed.

`test_routing_plugin.py` and `test_routing_output.py` exercise the existing job service, strict schemas, scene-busy rejection, independent input snapshots, history roundtrips, cancellation and publication. Shared site schema and publication regressions run alongside them. Real routing runs and memory measurements belong to the later explicit validation entry, not pytest.

Routing frontend contracts run with `npm --prefix frontend run test:routing`. They check coordinate entry, distinct region serialization, resolved task roundtrips, budget-to-generation bounds, explicit algorithm-default restoration, scene/grid identity and map geometry without calling an optimizer. Existing gesture tests additionally verify routing clicks cannot erase site objects. Browser acceptance uses an isolated real API/Worker with a synthetic 400 m UTM scene and actual MapLibre rendering, then submits, verifies actual generation counts, reloads, reopens history and cancels another run.

Browser recovery acceptance also restores an expired saved job ID: a temporary 503 must retry, then a real 404 must stop polling, clear only the matching saved job, unlock inputs/history and retain any displayed result. Compare two saved routes on the same map and verify the selected route's per-span table.

`test_routing_agent.py` checks routing-mode isolation with a scripted model: no site evaluation, ranking or proposal tools are available, and server validation rejects site edits. `test_routing_output.py` also rejects a registered farmland layer whose mask is missing.

Run real-scene acceptance explicitly with `python -m experiments.validate_routing --config /path/to/task.json --output-root outputs/validation/routing --repeat`. It rechecks all feasible saved routes, verifies source hashes and independent snapshots, optionally compares repeated route artifacts byte for byte, and reports peak RSS and timings. It requires explicit connection points and engineering inputs; it never invents production endpoints.

### Routing acceleration

Validate each acceleration independently against the NumPy/CPU reference before combining changes. Frozen objectives test dominance, ranks, crowding and stable selection; controlled operator inputs test variable tower counts and fixed endpoints. Compare every constraint and objective on exact grid boundaries, thin features, DEM nodata, polygons and masked padding. Feasibility must match; objective tolerance is atol=1e-8, rtol=1e-10. Recheck all published feasible routes on CPU.

Explicit benchmarks separate cold context preparation, warm execution, evolution, exact evaluation, archive, final validation and output. Synchronize CUDA timings and record per-device peak allocated/reserved memory. Performance thresholds belong to benchmark reports, not pytest. Large-budget quality uses fixed seeds, evaluation budgets and a frozen common reference; it never labels the best-known real-scene front globally optimal. Run single-device correctness before synchronous two-device evaluation.

`test_routing_metrics.py` checks hand-calculated IGD+/epsilon, an enumerated discrete routing front, and a repeated manifest run with frozen normalization and preserved source snapshots. `experiments.benchmark_routing` stores completed cases individually before assembling the final report; incomplete matrices are not logged as completed experiments. Candidate completion times support search-only time comparisons; publication and cold preparation are reported separately.

Benchmark tasks may be existing configuration-path strings or objects with `id` and `config`. Explicit task IDs must be unique directory components; use them to compare different engineering inputs in the same scene without overwriting artifacts.

`test_routing_multi_device.py` requires two real CUDA devices and checks ordered candidate parity, repeated search budgets and cooperative cancellation. The evaluation session must join device threads and release scene tensors on every exit path. Two-device speed is measured independently from correctness and is not assumed to beat compiled CPU evaluation.

`test_routing_tower_cache.py` checks bitwise equality with uncached reference results, complete slope reports, bounded eviction and unchanged fixed-seed trajectories. Large-budget reference validation and streamed output both expose batch checkpoints for cooperative cancellation; a cancelled overwrite must retain the previous complete experiment.

The first measured repeat has `reproduced: null` because no comparison exists yet; later measured repeats must match the first coordinate/objective hash. Five different seeds are independent quality trials, not five same-seed reproduction checks. Earlier benchmark artifacts used a true first-pass placeholder; interpret them using the saved repeat index and manifest.


## Behavior-preserving routing refactors

`tests/test_routing_refactor.py` tests Python-only initializer/operator/selection/range replacement, independent seed-fill and evolution dependencies, multi-trial evaluation reuse, global/phase limits, and core import boundaries. Existing search, PILOT, CPU/CUDA and two-device tests remain authoritative for their semantics.

Before editing, freeze a Git source archive and independent prepared-scene inputs. Run the same external capture tool against both source roots:

```bash
python experiments/validate_routing_refactor.py --source-root /path/to/frozen-source --output /path/to/before.json
python experiments/validate_routing_refactor.py --source-root "$PWD" --output /path/to/after.json
python -m experiments.validate_routing_refactor --before /path/to/before.json --after /path/to/after.json --output /path/to/comparison.json
```

The capture compares actual complete evaluation requests, selection identities, final NumPy/Python/Torch stream states, ordered archives, bounds, budget, generations and plugin schema. Compare the same backend and device; cross-backend numerical similarity is a different test. Timings and GPU peaks are recorded separately. The capture itself warms compilation before tracing and restores all instrumentation after each run.

Use matching `experiments.benchmark_routing` manifests for real-scene matrices, then compare their completed job directories with `--benchmark --before <old-matrix> --after <new-matrix>`. Coordinates, counts, scores, feasibility, Pareto order, evaluation indices and semantic JSON fields must match exactly. Candidate completion times, runtime/resource fields, code identity and isolated output paths may differ. Benchmark NPZ archives contain unique candidates and their first evaluation indices; the synthetic capture additionally retains repeated evaluation requests.

Measure runtime and peak memory separately with three alternating paired runs after warmup, without a concurrent experiment matrix. Investigate repeatable regressions above 10%; do not put timing gates in pytest. Run frontend routing assertions, TypeScript/build and an isolated real API/Worker browser test for inputs, defaults, history, reload, selection and cancellation. Keep missing archived-fixture failures explicit; do not manufacture a production experiment to make a test pass. Record final evidence only in `markdown/EXPERIMENT_LOG.md`.


## CPU PILOT component migration

`tests/test_pilot_components.py` compares frozen original neutral acceptance, metric radius scaling and private per-run streams. `experiments.validate_pilot_components` runs explicit frozen tasks with `report_quality: false`; no IGD/epsilon is calculated until all components pass correctness. The optional isolated real Jobs probe uses its own database/output. Existing routing benchmarks retain quality reporting unless explicitly disabled.

The completed CPU component suite additionally covers frozen elite/global phase ordering, both private random streams, encoding acceptance loss, same-cell A* result/cache counters, exact duplicate rollback and continuous survival identities. The final software probe restores a full-component task through actual routing history, submits it through the UI, reloads it and cancels another run on an isolated API/Worker. Full default configurations are never enabled by the presence of these tests.

Full PILOT acceleration keeps the original CPU implementation as an oracle. `tests/test_pilot_tensor_runtime.py` checks native tensor evaluation, exact feasibility, individual violations, manual-region/boundary rechecks, poisoned padding, empty batches and shared-budget truncation. CPU and CUDA evaluation microbatch sizes must preserve results. Native device results are distinct from complete algorithm integration; the staged contract is in `markdown/PILOT_ROUTING_MIGRATION.md`.

`tests/test_pilot_tensor_driver.py` exercises complete PILOT tensor evolution on CPU, one CUDA device and two CUDA devices, including all enabled phases, repeated microbatch settings, initialization exhaustion, partial final budgets, dynamic elite quota recycling and rejection after encoding loss. It also checks CPU/CUDA cancellation cleanup and an isolated real Jobs/API publication with saved execution metadata. Boundary regressions preserve temporary endpoint resampling and apply injected repairs to expansion probes exactly once. Formal equal-budget quality and timing comparisons remain explicit experiments; their frozen protocol and results are recorded separately from pytest.

`tests/test_routing_population_screen.py` protects the optional run-wide phase caps, the Python-only fresh-candidate replacement, unchanged common seed coordinates, unique random fill, shared evaluation billing and the exclusion of final evolved routes from cached initialization priors. `experiments.screen_routing_population` is a small cached-prior quality screen, with its full protocol in `markdown/PILOT_ROUTING_MIGRATION.md`; its timings do not include historical planning work. These research controls do not change Jobs defaults or enable a new assistant capability.
