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
| 关键配置 | `config/default_config.json`，demand_seed 42；normalization 和算法 seed 不参与本次建模验收 |
| 输出目录 | `outputs/validate_modeling` |
| 主要结果 | 验收摘要在 `validation_summary.json`。补录时可见 CUDA 可用，设备为 NVIDIA GeForce RTX 3060 Laptop GPU |
| 相关提交 | `f24bae9`（2026-10-08，validation CLI） |
| 状态 | 有效 |

完整环境记录见 `markdown/LOCAL_RUN_GUIDE.md`。该指南记录的 GPU 与上面摘要中的 GPU 名称不一致，复现时以当次 `validation_summary.json` 为准。

## 引导式 NSGA-II 与旧 NSGA-II 的超体积

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-11 |
| 实验名 | Guided NSGA-II versus the 2026-10-11 four-objective front |
| 目的 | 看距离场引导之后，同样种群和代数下的墙钟时间，以及四项目标超体积是否低于旧 NSGA-II |
| 入口 | `experiments/launch_site_run.py` |
| 关键配置 | 苍南场景，无进货原点，无手绘禁区，山体和农田按坡度与进场判断，矩形 80 m × 50 m，种群 40，30 代，seed 123。对照是 `outputs/site-20261011-154222` |
| 输出目录 | `outputs/site-guided-20261011-compare`（细阶段步长 0.1），`outputs/site-guided-wide-sigma`（细阶段步长 1） |
| 主要结果 | 两次新搜索都约 23 秒，40 个解全部可行。同一参考盒上的归一化超体积：旧前沿 0.815，步长 0.1 为 0.791，步长 1 为 0.815。步长 0.1 丢掉了约 4 m 的短进场极端。默认细阶段步长因此保持 1 |
| 相关提交 | 尚未提交 |
| 状态 | 有效 |

## 加长 NSGA-II 代数

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-11 |
| 实验名 | NSGA-II generations 90 versus population 100 |
| 目的 | 看四项目标前沿没有铺开时，加长代数和加大种群哪一个更抬超体积，且不明显增加总时间 |
| 入口 | `experiments/launch_site_run.py` |
| 关键配置 | 与上一条相同的苍南设置。对照为种群 40、30 代。另跑种群 100、30 代，以及种群 40、90 代。细阶段步长 1 |
| 输出目录 | `outputs/site-pop100-gen30`，`outputs/site-pop40-gen90` |
| 主要结果 | 种群 100、30 代用时 26.7 秒，超体积 0.842。种群 40、90 代用时 23.5 秒，超体积 0.872。同一参考盒上，30 代约为 0.816，25 m 网格约为 0.861。默认代数因此改为 90，种群保持 40 |
| 相关提交 | 尚未提交 |
| 状态 | 有效 |

## 后期局部方向与步长递减

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-11 |
| 实验名 | Late local direction versus sigma anneal |
| 目的 | 比较 90 代之后的自身梯度、朝该项最好的人走、两者融合、走向更不拥挤的邻居，以及最后 30 代缩小变异步长 |
| 入口 | `experiments/launch_site_run.py` |
| 关键配置 | 与 `outputs/site-gen90-look` 相同。局部搜索 8 步。基线超体积 0.872，最短进场约 22 m，约 25 秒。胜出要超体积不低于 0.872、最短进场不差于约 22 m、总时间不超过约 35 秒 |
| 输出目录 | `outputs/site-local-grad`，`outputs/site-local-grad-decay`，`outputs/site-local-neighbor`，`outputs/site-local-blend-05`，`outputs/site-local-blend-1`，`outputs/site-local-crowding`，`outputs/site-anneal-sigma` |
| 主要结果 | 自身梯度恒定学习率：25.2 秒，超体积 0.766，最短进场 38.6 m。自身梯度并递减：23.7 秒，0.766，38.3 m。只追他人：23.5 秒，0.791，40.5 m。融合 beta 0.5：23.7 秒，0.748，42.3 m。融合 beta 1：23.5 秒，0.775，37.4 m。走向更不拥挤的邻居：23.6 秒，0.861，21.6 m。最后 30 代步长收到 0.2：23.2 秒，0.884，21.6 m。只有最后一臂同时满足三条。默认因此采用最后 30 代步长递减，`local_steps` 保持 0 |
| 相关提交 | 尚未提交 |
| 状态 | 有效 |

## 按前沿是否还在变好来缩小步长

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-11 |
| 实验名 | Adaptive sigma from hypervolume stall |
| 目的 | 看步长不按代数、而在超体积连续停住后再乘 0.8，能否保住最后 30 代收到 0.2 的提升 |
| 入口 | `experiments/launch_site_run.py` |
| 关键配置 | 与 `outputs/site-anneal-sigma` 相同的苍南设置，但关掉按代数递减。`sigma_shrink = 0.8`，连续 5 代超体积无明显增加才缩小，下限 0.05 |
| 输出目录 | `outputs/site-adaptive-sigma` |
| 主要结果 | 用时 47.9 秒，超体积 0.850，最短进场 30.9 m。对照的按代数收到 0.2 是 23.2 秒、超体积 0.884、最短进场 21.6 m。这一版更慢，前沿也更差，因此不作为默认，`adaptive_sigma` 保持关闭 |
| 相关提交 | 尚未提交 |
| 状态 | 有效 |

## 选址助手：说明卡与循环护栏

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-12 |
| 实验名 | Assistant instruction cards and loop guard, deepseek-flash |
| 目的 | 看给每种编辑操作配说明卡、并撤下连续出错的只读工具后，模型能否把一句话准确落成提案 |
| 入口 | `experiments/agent_eval.py` |
| 关键配置 | 用例 `experiments/agent_eval_cases.json`，共 18 条：14 条应出提案，4 条不应出提案。模型 `deepseek-flash`，经 `.env` 中的 OpenAI 兼容网关调用。每条重复 2 次。工具轮数 6，单次超时 60 秒。基线是提交 `dd7793a` 的提示词和循环，在临时 worktree 里用同一份用例运行 |
| 输出目录 | `outputs/agent_eval/deepseek-flash-baseline`，`outputs/agent_eval/deepseek-flash-cards` |
| 主要结果 | 基线 31/36，共 485 秒。失败集中在相对移动：模型反复调用 `evaluate_pose`，遇到不可建格子就换点试，最后用完轮数，或者把往南 30 米悄悄改成 `y=906`。另有 1 次把“种群调到 80”顶替成默认参数的 `run_search`。另有 1 次上游超时。加说明卡和护栏后 34/36，共 222 秒。所有移动、转向、拒绝类用例都通过，2 次失败都是上游 60 秒超时，不是答错 |
| 相关提交 | `f711a61` |
| 状态 | 有效 |

## 选址助手：明确写出「目前不支持」

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-12 |
| 实验名 | Assistant explicit unsupported rules, deepseek-flash |
| 目的 | 看把“说明卡以外一律目前不支持”写成硬规则、再给一份已知例子清单后，模型能否不乱试、明确说做不到，同时对清单外的请求也能自己判断 |
| 入口 | `experiments/agent_eval.py` |
| 关键配置 | 用例扩到 27 条：原来 18 条，加上清单内 7 类、清单外 2 条（圆形变电站、土方单价）和 1 条混合请求。不支持类用例要求不出提案（混合请求只提能做的部分），且回复或理由里写出「目前不支持」。模型 `deepseek-flash`，每条重复 2 次，工具轮数 6，单次超时 120 秒 |
| 输出目录 | `outputs/agent_eval/deepseek-flash-unsupported` |
| 主要结果 | 第一次跑 53/54：“换个随机种子再跑一次”有 1 次被顶替成默认参数的 `run_search`。在清单里写明“种子固定，重跑结果相同”后，同一目录重跑 54/54，共 224 秒。所有不支持类用例都没有调用任何工具；两条清单外用例也都写明「目前不支持」，并由模型自己给出替代做法 |
| 相关提交 | `f711a61` |
| 状态 | 有效 |

## 选址助手：决策者记忆

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-12 |
| 实验名 | Assistant memory file, deepseek-flash |
| 目的 | 看把确认过的偏好、常用说法和场景备注拼进系统提示后，模型能否用记忆补参数、让当场说的覆盖记忆、按场景筛选、正确提议记下/改写/忘掉，同时不因记忆跳过确认或扩大能做的范围 |
| 入口 | `experiments/agent_eval.py` |
| 关键配置 | 用例扩到 36 条：原来 27 条，加 9 条记忆用例（补系数、当场覆盖、展开「老规矩」、别的场景不生效、记下、改写、忘掉、记忆说不用确认、记忆里写了不支持的参数）。模型 `deepseek-flash`，每条重复 2 次，工具轮数 6，单次超时 60 秒 |
| 输出目录 | `outputs/agent_eval/deepseek-flash-memory` |
| 主要结果 | 第一版提示 68/72：原有的“农田计入成本，系数 0.3”两次都被顺手提议记成推断偏好；另有 2 次拒绝时没写出「目前不支持」。把“推断偏好只在本次对话第二次出现时才提议，第一次只改地图”写进说明卡后，同一目录重跑 71/72，共 250 秒；记忆用例 17/18。唯一失败是“按我习惯的种群跑一遍”有 1 次说明种群不支持后仍提议默认参数的 `run_search`，这句话本身含可执行的“跑一遍”，暂不再加规则 |
| 相关提交 | `5ff68b4` |
| 状态 | 有效 |

## 存疑产物

以下文件本次未判定为过期，也未删除。

| 路径 | 原因 |
| --- | --- |
| `outputs/cmaes_region - 0.5` | 目录名含空格。对应 CMA-ES step 0.5 的结果仍有效，重命名前需同时改本文和 git 历史中的路径 |
| `outputs/cmaes_region.7z` | 与已展开的 CMA-ES 产物并存的压缩包，尚未确认是否为唯一副本 |
| `outputs/cmaes_region_0.05.7z` | 与 `outputs/cmaes_region_0.05` 并存的压缩包，尚未确认是否为唯一副本 |
| `outputs/road_alignment_diagnostic` | 已跟踪的道路对齐诊断图件，尚未补充为独立实验记录；确认用途和保留期限后再归档或清理 |
