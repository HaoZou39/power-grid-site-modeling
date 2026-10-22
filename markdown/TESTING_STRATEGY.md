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
8. OSM 建筑避障：中心线栅格化必须复用 HaulField 道路格规则；轴对齐或旋转足迹只要覆盖道路格即不可行，并与土地策略、手绘范围叠加；同一候选的 Gate、进站长度和累计高差不得因建筑专用掩膜改变。
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
