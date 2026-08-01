# VAE-like 条件多头随机站址生成算法实施方案

## 1. 算法边界

本算法是条件多头对角高斯生成器，不是标准 VAE。它没有 encoder、reconstruction loss 和 KL loss。

输入是不同的多目标偏好权重：

```text
preferences.shape = [B, 3]
preferences[b] = [weight_dem, weight_road, weight_demand]
```

同一个 batch 的不同 `b` 应使用不同或独立采样的权重。网络学习从 preference 到候选站址分布的映射。

本算法只新增：

- shared backbone 和 independent Gaussian heads；
- `mu/sigma` 参数化与重参数化采样；
- candidate softmin、`mu_loss`、entropy 和 diversity；
- 训练调度、checkpoint、中心推理和随机推理。

以下内容直接调用现有模块，不在 VAE-like 中重写：

```text
modeling/evaluator.py                # soft objectives、hard metrics
algorithms/common/scalarization.py  # normalization、Tchebycheff
algorithms/common/weiszfeld.py      # demand ideal
algorithms/common/pareto.py         # feasible Pareto
figures/candidate_maps.py           # 候选点和 footprint 地图
figures/pareto_3d.py                # Pareto 3D HTML
config/project_config.py            # config 加载、保存和 CUDA 校验
```

## 2. 目录

参考 CMA-ES 和 multi-start Adam，只保留算法核心和 main：

```text
algorithms/
  vae_like_multihead/
    __init__.py
    vae_like_multihead.py        # 网络、算法专属 loss、训练和推理
    vae_like_multihead_main.py   # 实验组装、公共后处理和输出

experiments/
  run_vae_like_multihead_region.py
```

- `vae_like_multihead.py` 调用 modeling evaluator 和 common scalarization，不写实验文件。
- `vae_like_multihead_main.py` 参考现有两个 main，负责调用数据模块、算法核心、公共 Pareto 和 figures。
- 实验入口只导入并调用 main。

## 3. 网络与张量

符号：

```text
B：每批 preference 数量
H：Gaussian head 数量
K：每个 head 的训练采样数
D：解维度，固定为 3
```

网络结构：

```text
preferences [B,3]
       |
 shared MLP backbone
       |
       +-- head 1: mu_layer + raw_std_layer
       +-- head 2: mu_layer + raw_std_layer
       `-- head H: mu_layer + raw_std_layer
```

输出：

```python
mu_raw.shape == [B, H, 3]
raw_std.shape == [B, H, 3]
```

每个 head 的 `mu_layer` 和 `raw_std_layer` 参数独立，backbone 共享。第一版使用 MLP 和对角高斯，不增加 encoder、完整协方差或 flow。

## 4. Raw 空间 Logistic-Normal 重参数化

每个 head 在无界 raw/logit 空间输出对角高斯分布参数：

```python
sigma_raw = F.softplus(raw_std) + sigma_eps

epsilon = torch.randn(B, H, K, 3, device=device)
sample_raw = mu_raw[:, :, None, :] + sigma_raw[:, :, None, :] * epsilon
```

其中 `sigma_eps` 是很小的正数，只用于数值稳定。第一版不设置标准差上下界，不使用 `torch.clamp`，也不使用随训练 step 变化的 `std_scale`；标准差由网络直接学习。

输出 shape：

```text
mu_raw       [B,H,3]
sigma_raw    [B,H,3]
sample_raw   [B,H,K,3]
```

随机候选和中心候选都直接调用现有建模入口：

```python
sample_pose = decode_raw_pose(sample_raw.reshape(B * H * K, 3), ...)
center_pose = decode_raw_pose(mu_raw.reshape(B * H, 3), ...)
```

`decode_raw_pose` 内部通过 sigmoid 将 raw/logit 变量压到 `(0,1)`，再映射到合法 pose：

```text
x = xmin + (xmax - xmin) * u_x
y = ymin + (ymax - ymin) * u_y
theta = -pi + 2*pi*u_theta
```

因此 sigmoid 后的单位变量服从 Logistic-Normal 分布，最终 pose 不会越界。该方案不使用 sample clamp，不记录 `boundary_hit_ratio`，也不新增 `decode_unit_pose`。VAE-like 与 multi-start Adam 复用完全相同的 `decode_raw_pose` 和 pose bounds。

## 5. 公共标量化的 batch 接口

现有 `scalarize_tchebycheff_torch` 支持一批候选共享一条权重 `[3]`。VAE-like 的一个 batch 包含不同 preference，因此公共模块需要增加：

```python
scalarize_tchebycheff_torch_batched(
    objectives: dict[str, torch.Tensor],  # 每项 [N]
    weights: torch.Tensor,                # [N,3]
    normalization: dict[str, float | int],
    obstacle_penalty_scale: float,
    eps: float = 0.0,
) -> torch.Tensor                         # [N]
```

该函数放在 `algorithms/common/scalarization.py`，与现有 Torch 入口共享同一内部公式和校验。VAE-like 只调用它，不在算法文件里实现 Tchebycheff。

兼容要求：

- 现有 Adam 继续调用 `scalarize_tchebycheff_torch(..., weights=[3])`。
- VAE-like 调用 batched 入口，允许每个候选对应不同权重。
- 当 `[N,3]` 的每行权重相同时，batched 入口必须与现有入口数值一致。
- batched 入口不能 detach、转 NumPy或使用 `torch.no_grad()`。

## 6. 候选评分

随机候选先展平：

```python
flat_pose = pose_samples.reshape(B * H * K, 3)
```

调用 `evaluate_site_objectives` 得到每项 `[B*H*K]`。对应权重展开为：

```python
flat_weights = (
    preferences[:, None, None, :]
    .expand(B, H, K, 3)
    .reshape(B * H * K, 3)
)
```

再调用公共接口：

```python
flat_scores = scalarize_tchebycheff_torch_batched(
    objectives=sample_objectives,
    weights=flat_weights,
    normalization=normalization,
    obstacle_penalty_scale=common_config.obstacle_penalty_scale,
    eps=common_config.scalarization_eps,
)
candidate_scores = flat_scores.reshape(B, H, K)
```

normalization 与 Adam/CMA-ES 相同：实验开始时调用公共 Weiszfeld 和 normalization 入口计算一次，训练期间固定。

## 7. 训练损失

### 7.1 Candidate softmin

每个 preference 在自己的 `H*K` 个候选中竞争：

```text
L_candidate[b]
  = -tau(step) * logsumexp(-candidate_scores[b,:,:] / tau(step))

L_candidate = mean_b(L_candidate[b])
```

`tau` 从大到小，使训练从多候选共同获得梯度逐渐接近 winner-takes-all。

### 7.2 均值解损失

将 `mu_raw [B,H,3]` 通过 `decode_raw_pose` 解码为中心候选并评价，使用同一 batched Tchebycheff 得到 `mu_scores [B,H]`：

```text
L_mu[b] = -mu_tau(step) * logsumexp(-mu_scores[b,:] / mu_tau(step))
L_mu = mean_b(L_mu[b])
```

`mu_weight` 前期较小、后期增大，防止模型仅靠大标准差偶然采到好解。

### 7.3 Entropy 与 diversity

```text
L_entropy = -mean(log(sigma_raw))

L_div = mean_(b,h!=h') exp(
    -||sigmoid(mu_raw[b,h]) - sigmoid(mu_raw[b,h'])||^2
      / diversity_bandwidth
)
```

entropy 权重训练早期为小正值，后期降为 0。diversity 使用 sigmoid 后的无量纲单位中心，避免直接比较无界 raw 值；使用小的固定权重。

### 7.4 总损失

```text
L_total
  = L_candidate
  + mu_weight(step) * L_mu
  + entropy_weight(step) * L_entropy
  + diversity_weight * L_div
```

`obstacle_soft` 已经由公共 Tchebycheff 的独立 penalty 加入随机候选和均值候选 score，不再重复添加 constraint loss。

## 8. 训练流程

1. 完整实验只计算一次公共 normalization。
2. 每个 step 从公共 weight grid 抽取 `B` 条 preference；batch 内允许不同权重。
3. 网络输出 `[B,H,3]` 的 `mu/sigma`。
4. 每个 head 重参数化采样 `K` 次。
5. evaluator 批量计算 `[B*H*K]` 个随机候选。
6. 公共 batched Tchebycheff 按候选对应权重计算 score。
7. 单独评价 `[B*H]` 个均值候选并计算 `L_mu`。
8. 组合总损失，执行 `loss.backward()` 和 Adam update。

调度方向固定为：

```text
softmin tau:     large -> small
entropy weight:  positive -> zero
mu loss weight:  small -> large
```

第一版使用从 start 到 end 的连续线性调度，并使用 `clip_grad_norm_`。不加入 prototype gate、balance loss 或 KL loss。

## 9. 推理与统一后处理

对公共 weight grid 的全部 preference 同时执行：

- 中心推理：每个 preference 将 `H` 个 `mu_raw` 通过 `decode_raw_pose` 输出中心候选。
- 随机推理：每个 preference、每个 head 输出 `K_eval` 个采样候选。

推理结束后不按 preference 或 head 分别提取 Pareto。处理方式与 Adam、CMA-ES 一致：

```text
汇总所有 preference/head/sample 候选
                |
                v
统一计算 soft objectives 和 hard metrics
                |
                v
is_feasible = obstacle_hard_count == 0
                |
                v
从全部 hard feasible 候选整体提取一次 Pareto front
                |
                v
调用公共 figures 画可行候选图和 Pareto 图
```

这与现有算法的后处理口径一致。不可行候选保留在 `solutions.csv`，不进入 `pareto_solutions.csv`。

公共输出图：

```text
all_candidates_points_map.png
all_candidates_footprints_map.png
pareto_points_map.png
pareto_footprints_map.png
pareto_3d_interactive.html
```

VAE-like main 只筛选记录、传入数据和指定输出路径；Pareto 与绘图实现分别调用 `algorithms/common/pareto.py` 和 `figures/`。

## 10. 配置与记录

算法专属配置：

```text
training_seed
sampling_seed
hidden_dim
backbone_depth
n_heads
samples_per_head
preference_batch_size
total_steps
learning_rate
sigma_eps
tau_start/end
mu_tau_start/end
mu_weight_start/end
entropy_weight_start/end
diversity_weight
diversity_bandwidth
max_grad_norm
eval_samples_per_head
checkpoint_interval
validation_preferences_path
validation_interval
```

CUDA device 继续使用公共 `modeling.device`，不在 VAE-like 专属配置中重复定义。

训练历史至少记录：

```text
total_loss, candidate_loss, mu_loss, entropy_loss, diversity_loss
tau, mu_weight, entropy_weight
sigma_mean, sigma_min, sigma_max
head_usage_ratio, mean_pairwise_mu_distance
```

候选记录在公共字段外增加：

```text
inference_mode, weight_index, head_id, sample_id, sampling_seed
mu_raw_x/y/theta, sigma_raw_x/y/theta
```

## 11. TensorBoard 收敛曲线

第一版 TensorBoard 只记录三条曲线：

```text
loss/train
loss/validation
sigma/mean
```

定义：

- `loss/train`：当前训练 step 实际用于 `backward()` 的 `L_total`。
- `loss/validation`：读取 `validation_preferences_path` 指向的公共偏好 CSV，使用各 head 的 `mu_raw` 中心候选做确定性前向；每条偏好直接取所有 head 中最小的 Tchebycheff scalar，再对全部验证偏好求平均。该指标不使用 `mu_tau` 或 softmin，所有训练 step 的评价口径固定。
- `sigma/mean`：当前训练 step 所有 preference、head 和三个 raw pose 维度的 `sigma_raw.mean()`，用于观察 entropy loss 下标准差是否持续放大、坍缩或趋稳。

训练 loss 每个 step 记录；validation loss 每 `validation_interval` 计算并记录。验证时使用 `model.eval()` 和 `torch.no_grad()`，不执行 backward 或 optimizer step。

两条曲线含义不同：训练曲线是包含随机 candidate、entropy 和 diversity 的总损失，验证曲线是固定偏好上各 head 中心最小 scalar 的平均值。因此只比较各自是否下降和趋稳，不直接比较二者绝对数值。

日志目录固定为：

```text
outputs/vae_like_multihead_region/tensorboard/
```

第一版不向 TensorBoard 写其他 scalar、histogram、图片或模型结构。entropy loss 保留，并按配置的 `entropy_weight` 参与 `L_total`。

## 12. 输出与执行

```text
outputs/vae_like_multihead_region/
  resolved_config.json
  normalization.json
  training_history.csv
  tensorboard/
  model_final.pt
  checkpoints/
  solutions.csv
  pareto_solutions.csv
  run_summary.json
  all_candidates_points_map.png
  all_candidates_footprints_map.png
  pareto_points_map.png
  pareto_footprints_map.png
  pareto_3d_interactive.html
```

目标入口：

```powershell
conda run -n torch311 python experiments/run_vae_like_multihead_region.py `
  --config config/default_config.json
```

当前只定义实施方案，入口尚未实现。

## 13. 实现与验证顺序

1. 在 common scalarization 增加 batched Torch 入口，验证与现有单权重入口数值一致并能反传。
2. 实现 Gaussian multi-head、raw 空间重参数化和 shape 测试。
3. 验证随机候选与中心候选都通过现有 `decode_raw_pose` 获得合法 pose。
4. 实现四项算法专属损失与调度测试。
5. 完成小型 CUDA forward/backward smoke test。
6. 接入公共偏好 CSV验证，并记录训练 loss、验证 loss 和平均标准差三条 TensorBoard 曲线。
7. 接入现有 normalization、hard evaluator、全局 Pareto 和 figures。
8. 真实数据先小步运行，检查显存、sigma 和 head usage，再运行正式实验。
