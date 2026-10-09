# 实验记录

已完成实验只记在本文。记录规则见 `AGENTS.md` 的「实验记录」和「Git 联动」。

每条记录使用下面的字段：

| 字段 | 含义 |
| --- | --- |
| 记录日期 | 写入本文的日期 |
| 实验名 | 稳定名称，不使用临时目录名代替 |
| 目的 | 这次实验要回答的问题 |
| 入口 | 仓库相对路径的脚本 |
| 关键配置 | 决定结果可否复现的参数 |
| 输出目录 | 产物位置 |
| 主要结果 | 来自该目录 `run_summary.json` 或验收摘要的数字 |
| 相关提交 | 引入对应代码的 git 提交；不表示产物一定产生于该日 |
| 状态 | `有效` 或 `作废` |

下面各条于 2026-10-09 根据仓库中已有产物补录。偏好步长由输出目录名，以及运行条数与 `markdown/VALIDATION.md` 的单纯形计数对齐得到：`0.5` 为 6，`0.1` 为 66，`0.05` 为 231，`0.01` 为 5151。这些目录里的 `resolved_config.json` 仍把 `experiment_name` 写成 `validate_modeling`，该字段不能当作实验身份。

## CMA-ES，偏好步长 0.5

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-09 |
| 实验名 | CMA-ES region，preference step 0.5 |
| 目的 | 用最粗偏好网格跑通 CMA-ES 区域搜索 |
| 入口 | `experiments/run_cma_es_region.py` |
| 关键配置 | 偏好步长 0.5，对应 6 个偏好 |
| 输出目录 | `outputs/cmaes_region - 0.5` |
| 主要结果 | 6 次运行，6 个解，6 个可行，4 个 Pareto |
| 相关提交 | `cae923f`（2026-07-16，CMA-ES） |
| 状态 | 有效 |

目录名含空格，见文末「存疑产物」。结果本身仍有效。

## CMA-ES，偏好步长 0.1

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-09 |
| 实验名 | CMA-ES region，preference step 0.1 |
| 目的 | 在默认偏好验证集上运行 CMA-ES |
| 入口 | `experiments/run_cma_es_region.py` |
| 关键配置 | 偏好步长 0.1，对应 66 个偏好 |
| 输出目录 | `outputs/cmaes_region_0.1` |
| 主要结果 | 66 次运行，66 个解，66 个可行，17 个 Pareto |
| 相关提交 | `cae923f`（2026-07-16，CMA-ES） |
| 状态 | 有效 |

## CMA-ES，偏好步长 0.05

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-09 |
| 实验名 | CMA-ES region，preference step 0.05 |
| 目的 | 加密偏好网格后的 CMA-ES 搜索 |
| 入口 | `experiments/run_cma_es_region.py` |
| 关键配置 | 偏好步长 0.05，对应 231 个偏好 |
| 输出目录 | `outputs/cmaes_region_0.05` |
| 主要结果 | 231 次运行，231 个解，230 个可行，28 个 Pareto |
| 相关提交 | `cae923f`（2026-07-16，CMA-ES） |
| 状态 | 有效 |

## CMA-ES，偏好步长 0.01

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-09 |
| 实验名 | CMA-ES region，preference step 0.01 |
| 目的 | 更密偏好网格上的 CMA-ES 搜索 |
| 入口 | `experiments/run_cma_es_region.py` |
| 关键配置 | 偏好步长 0.01，对应 5151 个偏好 |
| 输出目录 | `outputs/cmaes_region_0.01` |
| 主要结果 | 5151 次运行，5151 个解，5116 个可行，195 个 Pareto |
| 相关提交 | `cae923f`（2026-07-16，CMA-ES） |
| 状态 | 有效 |

## 多起点 Adam，偏好步长 0.1

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-09 |
| 实验名 | Multistart Adam region，preference step 0.1 |
| 目的 | 在默认偏好验证集上做多起点 Adam 搜索 |
| 入口 | `experiments/run_multistart_adam_region.py` |
| 关键配置 | 66 个偏好，每个偏好 100 个起点 |
| 输出目录 | `outputs/multistart_adam_region` |
| 主要结果 | 6600 个解，5371 个可行，91 个 Pareto |
| 相关提交 | `d729211`（2026-07-30，multistart Adam） |
| 状态 | 有效 |

## VAE-like multi-head，偏好步长 0.1

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-09 |
| 实验名 | VAE-like multi-head region，preference step 0.1 |
| 目的 | 用条件多头生成器在默认偏好验证集上产生候选站址 |
| 入口 | `experiments/run_vae_like_multihead_region.py` |
| 关键配置 | 66 个偏好，4 个 head，264 个中心候选，2112 个随机候选 |
| 输出目录 | `outputs/vae_like_multihead_region` |
| 主要结果 | 2376 个解，1082 个可行，117 个 Pareto |
| 相关提交 | `b5debfd`、`629979d`（2026-08-02，VAE-like） |
| 状态 | 有效 |

## 建模验收

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-09 |
| 实验名 | Modeling validation |
| 目的 | 在 CUDA 上验收数据模块和建模模块 |
| 入口 | `experiments/validate_modeling.py` |
| 关键配置 | `config/default_config.json`，seed 123 |
| 输出目录 | `outputs/validate_modeling` |
| 主要结果 | 验收摘要在 `validation_summary.json`。补录时可见 CUDA 可用，设备为 NVIDIA GeForce RTX 3060 Laptop GPU |
| 相关提交 | `f24bae9`（2026-10-08，validation CLI） |
| 状态 | 有效 |

完整环境记录见 `markdown/LOCAL_RUN_GUIDE.md`。该指南记录的 GPU 与上面摘要中的 GPU 名称不一致，复现时以当次 `validation_summary.json` 为准。

## 存疑产物

以下文件本次未判定为过期，也未删除。

| 路径 | 原因 |
| --- | --- |
| `outputs/cmaes_region - 0.5` | 目录名含空格。对应 CMA-ES step 0.5 的结果仍有效，重命名前需同时改本文和 git 历史中的路径 |
| `outputs/cmaes_region.7z` | 与已展开的 CMA-ES 产物并存的压缩包，尚未确认是否为唯一副本 |
| `outputs/cmaes_region_0.05.7z` | 与 `outputs/cmaes_region_0.05` 并存的压缩包，尚未确认是否为唯一副本 |
