# Testing Strategy

本文档记录当前新仓库的测试边界。pytest 只作为轻量、确定性、无实验输出的口径保护；真实数据、大矩阵、CUDA 显存记录和完整流程验收放在 `experiments/validate_*.py`。

## pytest 的职责

pytest 只测试小数据上容易悄悄出错的核心口径：

1. landuse 到 obstacle mask 的业务映射。
2. 1 m 连续 pose、safe margin 和 footprint 掩膜。
3. PyTorch soft objective 的 CUDA forward/backward。
4. hard 后验指标的手算一致性。
5. 非法输入明确报错。
6. 进货原点道路连通性：全连通、部分 Gate 不连通、全部 Gate 不连通、同一线段内部投影，以及 `cangnan` 已准备场景回归。
7. 道路拓扑简化：共享节点、T 型和多分支路口保持，普通形状点仍可简化；分离道路、近距离平行道路和不同层的几何交叉不得被错误连接；道路专用场景发布必须备份、保持非道路产物并可在失败时恢复。
8. OSM 建筑避障和道路退距：中心线栅格化必须复用 HaulField 道路格规则；遥感类别 3 与 OSM 中心线取并集后按可配置的 `road_setback_m`（默认 5 m，0 只禁道路格）做 1 m 距离变换。轴对齐或旋转足迹覆盖退距格即不可行，并与土地策略、手绘范围叠加。同一候选的 Gate、进站长度和累计高差不得因建筑专用掩膜改变。
8. 单方案报告与搜索约束一致：农田和山体策略、建筑/水体硬禁止、禁区、可行域、进货原点、显式掩膜兼容，以及完整或部分 API 约束字段的处理。
9. Haul-field route reconstruction: compact predecessor and gate-owner dtypes, exact metric agreement, Gate/contact/road-segment identity, the existing 5 cm terminal rule, bounded report-cache reuse and invalidation, and reachable/infeasible handling for a 40-pose cangnan reference fixture.

pytest 不读取原始 DEM tif，不生成真实 road Voronoi，不写 `outputs/`，不记录显存，也不跑完整实验流程。道路连通性另有场景回归：本机存在已准备的 `scenes/cangnan` 时，直接读取其中的标准 `.npy` 产物，按场景元数据把固定 WGS84 原点转换到局部米坐标，并验证真实 Gate 的可达过滤；`tests/fixtures/cangnan_p2b_reference.csv` 固定保存已核验实验的 40 个 pose，用来确认新路径场能区分可达与不可达位置；可达位置的精确查表与路线回溯三项运输指标一致，不可达位置明确报告不可行。算法更新后不再把历史方案指标当作当前选路算法的基准值。场景缺失时跳过。测试不重建或修改场景，也不读取可变的 `outputs/` 实验目录。

## 具体测试项

### 1. Landuse 映射

使用小型 fixture：

```text
0,1,2
3,4,5
```

期望 obstacle mask：

```text
0,1,1
1,0,1
```

固定语义：

- `0 other / 其他区域 -> 可建设 -> obstacle_mask 0`
- `4 mountain_natural / 山体/自然区域 -> 可建设 -> obstacle_mask 0`
- `1 field / 农田区域 -> 不可建设 -> obstacle_mask 1`
- `2 building / 建筑区域 -> 不可建设 -> obstacle_mask 1`
- `3 road / 道路区域 -> 不可建设 -> obstacle_mask 1`
- `5 water / 水体区域 -> 不可建设 -> obstacle_mask 1`

同时检查 metadata 中写入真实类别含义、可建设类别、不可建设类别和 mask 映射。出现未定义类别编号时必须 `ValueError`。

### 2. Pose 与 Footprint

使用小型矩阵 shape，例如 `64 x 80`：

- `decode_raw_pose(raw_pose)` 返回 shape `[B, 3]`。
- `x/y` 位于 safe margin 约束后的合法范围。
- `theta` 位于 `[-pi, pi]`。
- `compute_soft_footprint` 返回 CUDA 上的 `grid` 和 `weights`。
- `compute_hard_footprint_indices` 返回非空整数 `[row, col]`，且不越界。

### 3. CUDA Soft Objectives

使用合成 DEM、obstacle、road、demand：

- DEM soft variance 输出 shape `[B]`。
- obstacle soft overlap 输出 shape `[B]`。
- road distance 输出 shape `[B]`。
- demand distance 输出 shape `[B]`。
- 所有 PyTorch 输出必须在 CUDA 上，且数值有限。
- `sum(loss).backward()` 后，`raw_pose.grad` 必须存在、位于 CUDA、且数值有限。

### 4. Hard Metrics

直接用小型 NumPy 矩阵和显式 hard indices 做手算校验：

- DEM hard variance。
- DEM hard range。
- obstacle hard count。
- obstacle hard ratio。

这类指标只用于后验评价，不参与反向传播。

### 5. 非法输入

必须明确报错，不做静默兜底：

- 非 CUDA tensor 传入 CUDA 建模函数。
- shape 错误。
- NaN / Inf。
- landuse 出现未知类别，例如 `6`。
- demand weights 为负数或总和为 0。
- road Voronoi 中 seg_id 越界。

## 真实数据验证

真实数据验收使用实验脚本，而不是 pytest：

```bash
conda run -n torch311 python experiments/validate_modeling.py
```

该脚本可以写入 `outputs/validate_modeling/`，并记录配置、shape、CUDA 设备、显存、soft backward 和 hard 指标。

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

Run the prepared-scene comparison without opening a browser:

```bash
python -m experiments.compare_initialization --output-dir outputs/initialization_comparison_20261022
```

The comparison uses paired seeds and unchanged search/scene settings. It records input and source hashes, configuration, initial/guided/final CSVs and timing. The 100-member methods share an evaluation budget; the legacy 40-member arm has a smaller budget. HV and IGD+ use one common empirical reference and normalization across all runs. Spatial-cell counts are occupancy measures, not certified feasible-region coverage. This experiment stays outside pytest.
