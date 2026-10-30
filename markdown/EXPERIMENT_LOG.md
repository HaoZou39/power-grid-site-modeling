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
| 状态 | 作废 |

2026-10-26 核验：该目录的 DEM、需求点、道路线段、Voronoi 和 metadata 曾与 `scenes/cangnan` 共用 inode，metadata 已被后续道路发布改写。现已独立备份并隔离场景侧共享文件；没有原始输入哈希可证明所提备份属于本实验，因此保留全部产物，不能作为可复现的有效实验。证据见 `outputs/scene-link-audits/20261026-before-isolation/audit.json`。

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

## 引导式多目标搜索与无引导版本的超体积

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-11 |
| 实验名 | Guided search versus the 2026-10-11 unguided four-objective front |
| 目的 | 看距离场引导之后，同样种群和代数下的墙钟时间，以及四项目标超体积是否低于无引导的旧版本 |
| 入口 | `experiments/launch_site_run.py` |
| 关键配置 | 苍南场景，无进货原点，无手绘禁区，山体和农田按坡度与进场判断，矩形 80 m × 50 m，种群 40，30 代，seed 123。对照是 `outputs/site-20261011-154222` |
| 输出目录 | `outputs/site-guided-20261011-compare`（细阶段步长 0.1），`outputs/site-guided-wide-sigma`（细阶段步长 1） |
| 主要结果 | 两次新搜索都约 23 秒，40 个解全部可行。同一参考盒上的归一化超体积：旧前沿 0.815，步长 0.1 为 0.791，步长 1 为 0.815。步长 0.1 丢掉了约 4 m 的短进场极端。默认细阶段步长因此保持 1 |
| 相关提交 | 尚未提交 |
| 状态 | 有效 |

## 加长引导式多目标搜索的代数

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-11 |
| 实验名 | Guided search generations 90 versus population 100 |
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

## 选址助手：方案附件与分析

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-12 |
| 实验名 | Attached pose analysis, deepseek-flash |
| 目的 | 看用户消息附上一个方案后，模型能否把「这个方案」「它」落到附件方案上：要分析时先调用 `analyze_pose`，要改动时 `pose_id` 用附件方案而不是当前选中方案 |
| 入口 | `experiments/agent_eval.py` |
| 关键配置 | 用例扩到 40 条：原来 36 条，加 4 条附件用例（分析、往东挪 20 米、占了多少农田、和最好的比差在哪），都附 `pose-2`，快照里选中的是 `pose-1`。分析类用例要求本轮成功调用过 `analyze_pose`。模型 `deepseek-flash`，每条重复 2 次，工具轮数 6 |
| 输出目录 | `outputs/agent_eval/attach_v1` |
| 主要结果 | 80/80，共 282 秒；附件用例 8/8，原有 36 条无回退。浏览器里点「问 AI」实测：第一版回答把方案叫成内部 id「方案 0」、写英文字段名，并把 `dem_soft` 说成「需求满足度」；给 `ranks` 加上与方案小窗同名的 `label` 和从 1 开始的 `best_index`，并在提示里要求按「方案 N」和 `label` 称呼后，回答用词与界面一致 |
| 相关提交 | `c8e935e` |
| 状态 | 有效 |

## 选址助手：按以往选择推荐方案

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-13 |
| 实验名 | Preference recommendation, deepseek-flash |
| 目的 | 偏好推荐改成只读工具 `recommend_poses`、选择只由用户在方案小窗点「记为我的选择」记下之后，看模型能否在要推荐时调用工具，在被要求代记选择时拒绝，原有用例不回退 |
| 入口 | `experiments/agent_eval.py` |
| 关键配置 | 用例扩到 43 条：原来 40 条，加 2 条推荐用例（要求调用过 `recommend_poses`）和 1 条代记选择（按不支持判）。模型 `deepseek-flash`，每条重复 2 次，工具轮数 6 |
| 输出目录 | `outputs/agent_eval/preference_recommend_v1` |
| 主要结果 | 84/86；推荐用例 4/4。失败的两次：「按我习惯的种群跑一遍」有 1 次没写出「目前不支持」，代记选择有 1 次出了提案。规则 12 写长时，全量跑出 81/86。只拿 14 条拒绝类用例对照，新旧提示词各跑 3 遍：原有 13 条新版 36/39、旧版 35/39，没有回退；代记选择新版 2/3，旧版 0/3（每次都出提案）。pytest 里有一个只看平整度的用户：训练改回原始数值，或退化成等权，都会让它失败 |
| 相关提交 | `ca31620` |
| 状态 | 有效 |

## 选址助手：偏好默认值与推荐理由

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-13 |
| 实验名 | Preference defaults, deepseek-flash |
| 目的 | 加了「偏好」页默认重要程度作为推荐起点、每个推荐带 `strengths` 理由之后，看推荐用例和原有用例是否仍通过，以及模型会不会代设偏好 |
| 入口 | `experiments/agent_eval.py` |
| 关键配置 | 用例扩到 44 条：原来 43 条，加 1 条代设偏好（按不支持判）。模型 `deepseek-flash`，每条重复 2 次，工具轮数 6 |
| 输出目录 | `outputs/agent_eval/preference_defaults_v1` |
| 主要结果 | 86/88；推荐用例 4/4，代设偏好 2/2。失败的两次与上一条相同：「按我习惯的种群跑一遍」有 1 次没写出「目前不支持」，代记选择有 1 次出了提案。浏览器实测：回答第一版写了 `dem_soft`、`offroad_haul` 这类字段名，工具返回的 `objectives` 改用中文目标名为键后，用词与方案小窗一致。另一个问题：只记了 1 次选择时，学到的东西几乎全在非线性项里，线性权重不动，回答便说「权重和原来一样」，排序却已经变了。把 `weight` 改成整个效用在当前方案上的平均斜率之后，解释与排序一致 |
| 相关提交 | `2706178` |
| 状态 | 有效 |

## 选址助手：局部优化与调整后重算

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-13 |
| 实验名 | Refine pose, deepseek-flash |
| 目的 | 「调整/优化这个方案」改成 `refine_pose`（方案周围方框内再跑引导式搜索），挪动或改约束后的方案按搜索口径重算。看模型会不会用对操作，原有用例是否仍通过，以及浏览器里调整后的方案能否再分析 |
| 入口 | `experiments/agent_eval.py`；浏览器走 `http://localhost:5176` |
| 关键配置 | 用例扩到 47 条：加 2 条局部优化（默认半宽 150 m、附件方案 100 m）和 1 条「按卫星图设奖励」（按不支持判）。模型 `deepseek-flash`，每条重复 2 次，工具轮数 6。浏览器用 `site-20261013-015928`（农田计成本 0.3，无原点）的方案 9 |
| 输出目录 | `outputs/agent_eval/refine_pose_v1` |
| 主要结果 | 87/94；新用例 5/6，失败那次两次都漏了 `rationale` 字段。原有用例的 6 次失败里，4 次拒绝的意思对但写成「做不到」，没写出「目前不支持」；代记选择 2 次顺手提了 `select_pose`，与前两条记录是同一类。浏览器实测：方框 300 m 的局部搜索约 14 s；先按「各项都不差」再按「最好」挑时，附近没有各项都不差的点，加进来的是平整度 0.5、进场 165 m 这种和原方案差得很远的点，所以改成每个目标取「这项更好、其余项变差最少」：加入的方案 14 平整度 11.1（原 12.3）、进场 35.9 m（原 32.8），方案 15 高差 2.6 m（原 2.7）。分析方案 14 时能说出它由方案 9 局部优化而来并给出名次。往东挪 30 m 后约 5 s 重算出「不可行」（道路距离 5.6 m）。重算与方案表逐项一致（float32 末位差）。另查明分析时的 502 来自 Vite 代理复用了 uvicorn 已在 5 s 空闲后关闭的连接，代理改为每个请求新建连接 |
| 相关提交 | `dc9387b` |
| 状态 | 有效 |

## 选址助手：「再次优化某方案」只做局部优化

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-13 |
| 实验名 | Refine scope, deepseek-flash |
| 目的 | 用户反馈「再次优化」某个方案时地图上全部方案消失并被替换。查后端日志，这两次是改动前的整体重跑 `run_search`（`outputs/site-20261013-020815`、`outputs/site-20261013-021136`）。提示词第 13 条和 `run_search` 说明卡写明：指向某个方案的「再优化/重新优化」用 `refine_pose`，`run_search` 会替换全部方案，只用于整体重跑。看模型是否按此区分 |
| 入口 | `experiments/agent_eval.py --cases`（从 `experiments/agent_eval_cases.json` 取出局部优化与整体重跑的用例） |
| 关键配置 | 用例加 2 条：附件方案「再次优化一下这个方案」、「把方案 2 重新优化一下」，都应为 `refine_pose`。本次只跑 7 条：4 条局部优化、3 条应为 `run_search` 的整体重跑。模型 `deepseek-flash`，每条重复 3 次 |
| 输出目录 | `outputs/agent_eval/refine_scope_v1` |
| 主要结果 | 20/21；新用例 6/6，整体重跑 9/9。失败的那次是已有的 `refine_selected` 一次没给出提案 |
| 相关提交 | `11e6d5a` |
| 状态 | 有效 |

## 选址助手：推荐方案在地图上按名次上色

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-13 |
| 实验名 | Recommend colors, deepseek-flash |
| 目的 | 推荐结果原来只写在对话里。回复带出 `recommend_poses` 的名次，地图按名次上色并给出图例，方便讲解。提示词第 12 条补了一句「地图会上色」，看推荐用例是否仍通过 |
| 入口 | `experiments/agent_eval.py --cases`（取 2 条推荐用例）；浏览器走 `http://localhost:5176` |
| 关键配置 | 模型 `deepseek-flash`，每条重复 2 次。浏览器用 `site-20261013-015928`，问「按我的偏好推荐 5 个方案」 |
| 输出目录 | `outputs/agent_eval/recommend_colors_v1` |
| 主要结果 | 4/4。浏览器里图例列出第 1 到 5 名：方案 1、9、11、3、10，地图上对应方案依次为品红、橙、黄、绿、蓝，小窗标题带「推荐第 1」 |
| 相关提交 | `cc64b3c`（上色），`e681d7c`（名次徽标与淡化，只上色时缩放到全图几乎看不出） |
| 状态 | 有效 |

## 选址助手：推荐理由改成与第 1 名的差值

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-13 |
| 实验名 | Recommend explanation, deepseek-flash |
| 目的 | 用户读不懂推荐说明。原回答写「进场 0.333 → 1.0，地形平整度 0.333 → 0」，可名次里方案 11（进场 44.7 m）排在方案 3（37.7 m）前，方案 11 的理由还是「—」。`weight` 是整张图上的平均斜率，学过 10 次选择后效用是非线性的，和单个方案的名次对不上。改为：工具给每个推荐带 `better_than_first`、`worse_than_first`；提示词第 12 条要求用大白话，说明「综合分从好到差、太像的跳过」，其余名次写「比第 1 名 X 好 a、Y 差 b」，不写权重数字 |
| 入口 | `experiments/agent_eval.py --cases`（取 2 条推荐用例）；浏览器走 `http://localhost:5176` |
| 关键配置 | 模型 `deepseek-flash`，每条重复 2 次。浏览器用 `site-20261013-015928`，10 次选择记录，问「推荐 5 个方案」 |
| 输出目录 | `outputs/agent_eval/recommend_explain_v1` |
| 主要结果 | 4/4。浏览器里每个名次都有理由，例如方案 11「比第 1 名地形平整度好 6.6，进场差 7.8、进场高差差 1.4」，没有权重数字。另外用三种不带「偏好」的说法（「推荐 5 个方案」等）各问 2 次，6/6 都调用了 `recommend_poses`（`outputs/agent_eval/recommend_plain_before`） |
| 相关提交 | 本条所在提交 |
| 状态 | 有效 |

## HaulField 优化指标、Gate 与运输路线一致性

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-15 |
| 实验名 | P2b HaulField route consistency |
| 目的 | 让优化目标、Gate 选择、方案报告和地图黄色运输路线共同使用同一个 HaulField 结果，消除报告独立寻路导致的 Gate、进站长度和累计高差差异 |
| 入口 | `modeling/haul_field.py` 的 `build_haul_field()` / `query_route()`；`experiments/site_report.py`；`pytest` 与本地 Docker Compose API |
| 关键配置 | `cangnan` 1800 × 1800 场景；检查 `site-20261015-104522` 的界面方案 12，以及 `site-20261015-073941` 的 40 个方案（重点 run_id 8、5、35、36）；保持四连通 FIFO 传播和 5 cm 末段规则不变 |
| 输出目录 | 无新增正式输出；40 个历史方案的稳定回归输入保存为 `tests/fixtures/cangnan_p2b_reference.csv` |
| 主要结果 | 方案 12 的报告累计高差由独立寻路的 0.038 m 统一为优化值 0.258 m，进站长度保持 56.974 m；带进货原点的 40 个历史方案中，报告与 CSV 的沿路距离、进站长度、累计高差差值均为 0。真实场景 HaulField 构建约 40.6 s，新增核心路线数组后占用约 96.4 MiB，缓存命中后的单方案查询约 0.2 ms；API 冷请求约 15.5–20.8 s、同键热请求约 0.02 s。单元、接口、Agent 同步及 40 方案集成用例通过；前端生产构建通过。另用合成图确认 FIFO 在非等权初值下不保证加权最优，按边界留作 P2c，不在本次改为 Dijkstra |
| 相关提交 | 本条所在提交 |
| 状态 | 有效 |

## 进站斜向与横竖长度对照

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-15 |
| 实验名 | Diagonal access length comparison |
| 目的 | 在同一苍南硬掩膜上比较默认四连通进站长度和可选八连通斜向长度，看差别大不大。不替换默认走法，也不改已有方案 |
| 入口 | 直接调用 `modeling/haul_field.py` 的 `build_haul_field()`，`diagonal` 分别取假和真。不经过优化，不写实验目录 |
| 关键配置 | `scenes/cangnan`，1800 × 1800。硬掩膜用默认用地策略：建筑、道路、水体不可建设，山体和农田不按类别禁止；没有手绘禁区、可行域和进货原点。可建设格子 2,582,149 |
| 输出目录 | 无 |
| 主要结果 | 两种走法可达格子都是 2,510,405，没有只在一种走法下可达的格子。斜向长度除以横竖长度：最小 0.607，10 分位 0.755，中位数 0.855，90 分位 0.989，最大 1.000。斜向没有更长的格子。长度差超过 0.1 mm 的有 2,337,173 个，占可达格子的 93.1%；其中 2,006,120 个（79.9%）至少短 5%，2,268,908 个（90.4%）至少短 1%。最短之比出现在格子 (397, 387)：横竖 2.502 m、斜向 1.518 m，所选进站口也不同。横竖场约 14.2 秒，斜向场约 69.6 秒。差别明显，但靠近已对齐进站口的格子几乎不变。默认仍关闭斜向 |
| 相关提交 | 本条所在提交 |
| 状态 | 有效 |

## 本地加速与校验改进移植到远程 master

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-22 |
| 实验名 | Selective remote integration: validation and origin-cache reuse |
| 目的 | 将本地 `75da5f1` 的校验修复与 `03e02ac` 的换原点缓存复用移植到远程 `b54dcaf`，保护远程场景构建、地图 frame 和高程加权 Dijkstra |
| 入口 | `experiments/validate_haul_origin_cache.py`；`outputs/perf-validation-20261022/search_acceptance.py`；完整 pytest、前端 `test:problem-snapshot` 与生产构建；`experiments/agent_eval.py`。验收方法见 `markdown/TESTING_STRATEGY.md` |
| 关键配置 | 独立 checkout、私有场景缓存和实验目录；读取已有苍南 1800×1800 标准产物，不改正式场景。距离场对照 `b54dcaf`，高程权重 1、四/八连通、无原点→`(827.541, 987.102)`→`(1200.125, 600.25)`→无原点，每次 400 个连续查询。预热两份实现的 JIT 后计时。应用任务使用 CUDA、77×51.5 m、40 个体、90 代、seed 123；四连通无原点，八连通带第一个原点。Node 22.23.4；测试环境使用现有 torch311 加隔离安装的 Numba 0.68.0、requests |
| 输出目录 | `outputs/perf-validation-20261022/`；`outputs/merge-20261022-four-default/`；`outputs/merge-20261022-diagonal-origin/`；`outputs/agent_eval/perf-validation-20261022/`、`perf-validation-feasibility-20261022/`、`perf-validation-baseline-20261022/`、`perf-validation-baseline-refusals-20261022/`、`perf-validation-baseline-failures-20261022/`。这些本机产物未提交远程 |
| 主要结果 | 完整 pytest **337 passed**，新增评测用例后助手确定性回归 **59 passed**；前端断言、TypeScript 与生产构建通过。两种走法的全部原有距离场数组、可达性、前驱、Gate 及每次 346 条可达完整路线均与远程原版严格相等，最大绝对差 0。四连通换原点 4.165/4.239 s→1.050/1.117 s（3.97/3.80 倍）；八连通 4.021/4.141 s→1.050/1.111 s（3.83/3.73 倍）；去原点约 3.4–3.5 s→0.35 s。冷构建为四连通旧/新 3.549/3.676 s、八连通 3.387/3.456 s。完整 API 流程分别产出 40 个方案及 11/40 个 Pareto 方案，全部方案重算、全部 Pareto 报告指标与路线、产物下载通过，含图件约 17.77/20.07 s。Dijkstra 规则未替换为旧 FIFO；通过出堆顺序重放保留逐边加法。冲突保留场景失败阶段及任务终态保护；文件签名回归显式推进 mtime，避免同一文件系统时钟刻度造成不稳定。过期文件已核对，本轮未删除数据或有效产物 |
| 助手评测边界 | `deepseek-flash` 原有 71 用例通过 60，11 项未通过，不能称实模型评测全过。对远程原版复核这 11 项，仍有 7 项失败、4 项通过，另一次拒绝用例重跑也有波动；前三项为原点设置/清除和朝南旋转，均在原版复现。已有方案时改原点的旧期望与现行限制冲突，其他失败含拒绝措辞、记忆与提案行为；这些结果不证明模型行为无回归。本次新增“只推荐可行方案”实模型用例通过，相关过滤、排名与助手同步由确定性测试保护。本轮不更改原有助手交互规则来迎合旧用例 |
| 相关提交 | 本条所在提交；远程基线 `b54dcaf`，本地来源 `75da5f1`、`03e02ac` |
| 状态 | 有效 |

## 100 个体均匀与田口正交初始化对照

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-22 |
| 实验名 | Population initialization: Gaussian, uniform and Taguchi |
| 目的 | 实现普通均匀采样与田口式正交初始化；把默认种群从 40 增至 100，并区分种群规模与初始化方法的影响 |
| 入口 | `python -m experiments.compare_initialization --output-dir outputs/initialization_comparison_20261022`；`python -m experiments.plot_initialization_comparison outputs/initialization_comparison_20261022`；完整 pytest、前端测试与生产构建；`experiments/agent_eval.py` 的两个新增参数边界用例 |
| 关键配置 | 当前分支基线 `e10ac1f`；只读使用 `scenes/cangnan` 的 1800×1800 标准产物，77×51.5 m 足迹，山体和农田允许，无手绘约束、无进货原点、关闭需求点目标，四连通、高程权重 1。四组为高斯 40、高斯 100、均匀 100、田口 100；每组使用相同 seed：123、456、789、1011、1213、1415、1617、1819、2021、2223。全部 90 代、8 步 Adam 引导、学习率 0.05、变异步长 1，末 30 代收至 0.2，其余配置完全相同；seed 内轮换组别顺序。RTX 4090，PyTorch 2.11.0+cu126 |
| 评价口径 | 三种 100 个体方法演化评价预算相同，均为 9,100；40 个体为 3,640，不能将增加种群视为等预算收益。距离场只建一次，耗时 4.293 s，不计入搜索耗时；CUDA/优化器先预热。搜索计时包括初始化、引导、演化及最终复评，阶段导出和作图在计时外。合并全部最终可行前沿得到 27 个唯一经验非支配参考点，统一 ideal/nadir 归一化，每维参考点 1.1，计算 HV 与 IGD+；空间覆盖使用 100 m 格占据数，不是全局可行域覆盖率 |
| 输出目录 | 正式 `outputs/initialization_comparison_20261022/`，含输入与源码 SHA256、完整配置、每次引导前/后及最终 CSV、`reference_front.csv`、`runs.csv`、`paired_comparison.csv`、`summary.json`、`metrics.png`、`positions_seed123.png`。两代流程预检在 `outputs/initialization_comparison_smoke_20261022/`；测试 JUnit 在 `outputs/initialization_comparison_tests_20261022/full.xml`；助手评测在 `outputs/agent_eval/initialization-parameters-20261022/`。这些本机输出不加入提交 |
| 主要结果 | 40/40 次搜索完成，最终种群全部可行。田口相对均匀平均 HV 高 0.58%，均匀相对田口平均 IGD+ 低 6.31%；按同 seed 配对，两项指标均各胜 5 次，未见稳定赢家。田口的初始位置覆盖更均衡，但不保证演化后的质量优势。默认采用 100 个体、均匀初始化，保留田口及旧高斯的显式配置。单独比较高斯 40→100：平均 HV 提升 2.39%，IGD+ 降低 11.89%，搜索耗时增至 4.33 倍。结论只覆盖本场景和本轮配置，不证明全局最优 |
| 初始化与引导 | 100 个体高斯、均匀、田口的初始 100 m 格占据数分别为 76.5、87.2、100.0；引导后为 68.4、79.6、92.5。初始可行率均值分别为 33.5%、43.7%、47.5%，引导后为 60.8%、65.2%、70.6%；最终前沿占据格数均值为 8.5、8.2、7.9，说明初始化分散程度不等于最终前沿空间覆盖 |
| 验证 | 完整 pytest **358 passed**，无失败或跳过，含三种初始化的真实 CUDA 小场景搜索；前端 `test:problem-snapshot` 与生产构建通过；新增助手参数边界实模型评测 **2/2** 通过。正式运行的全部配置逐项核对，仅 seed、种群和初始化变化；每次引导前、引导后和最终数量均与配置一致，输入与算法源码哈希保持不变。静态图已生成并检查，全程未打开浏览器。已核对过期文件，本轮未删除原始数据或有效产物 |
| 相关提交 | 本条所在提交；实验基线 `e10ac1f`，运行时未提交的算法源码以 manifest 中 SHA256 标识 |
| 状态 | 有效 |

以下为 10 个 seed 的均值 ± 样本标准差，搜索时间单位为秒。HV 越大越好，IGD+ 越小越好。

| 初始化 | 种群 | HV | IGD+ | 搜索耗时 |
| --- | --- | --- | --- | --- |
| 高斯（旧方法） | 40 | 1.185897 ± 0.032439 | 0.071663 ± 0.025050 | 3.310 ± 0.046 |
| 高斯（旧方法） | 100 | 1.214268 ± 0.024833 | 0.063141 ± 0.019207 | 14.328 ± 0.181 |
| 普通均匀 | 100 | 1.219342 ± 0.035597 | 0.055819 ± 0.025691 | 14.300 ± 0.293 |
| 田口正交 | 100 | 1.226363 ± 0.036609 | 0.059580 ± 0.023143 | 14.183 ± 0.154 |

## 初始化改进合入 GitHub master 前验收

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-22 |
| 实验名 | Initialization and remote partitioned-search integration acceptance |
| 目的 | 推送初始化改进 `1928965` 前合并远程 `ed9b331` 的矩形分区并行搜索，验证参数选择、种群默认值和有界 pose 流程共同工作 |
| 入口 | 完整 `pytest -q`；前端 `test:problem-snapshot` 与 `build`；`python -m experiments.compare_initialization --seeds 123 --output-dir outputs/initialization_push_validation_20261022/scene_comparison` |
| 关键配置 | 保留远程 `site.partitioned_guided_search` 插件和 pose bounds 传递；每个分区继承初始化方式与种群大小。新增三种初始化在有界和无界搜索范围下的 CUDA 组合回归。真实苍南场景复跑高斯 40、高斯 100、均匀 100、田口 100，全部 seed 123、90 代、8 步引导，其余配置与上一条正式对照实验一致；不重跑 10 seed 研究，也不修改其原始产物 |
| 输出目录 | `outputs/initialization_push_validation_20261022/`：完整测试 `full.xml`，四组真实场景结果 `scene_comparison/`，逐组等价性核对 `equivalence.json`；本机验收输出不加入提交 |
| 主要结果 | 完整 pytest **373 passed**，无失败或跳过；前端测试与生产构建通过。四组真实搜索全部完成，共 340 个最终个体全部可行。每组的 `initial.csv`、`guided.csv`、`solutions.csv`、`pareto_solutions.csv` 共 16 个文件与合并前 seed 123 的产物逐字节相等；场景输入哈希保持不变。三种初始化均通过分区边界内的实际 CUDA 引导与演化回归。助手文档保留初始化参数限制及远程分区调用边界，无冲突标记；已核对过期产物，本轮未删除原始数据或有效输出 |
| 相关提交 | 本条所在合并提交；本地初始化 `1928965`，远程基线 `ed9b331` |
| 状态 | 有效 |

## 移除演化结束后的局部微调验收

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-22 |
| 实验名 | Remove post-evolution local polish |
| 目的 | 按用户要求终止学习率研究，移除演化结束后的梯度、邻居与混合方向微调，最终种群直接输出；保留前期梯度引导和演化中的变异步长递减 |
| 入口 | 完整 `pytest -q`；`python -m experiments.compare_initialization --seeds 123 --output-dir outputs/remove_local_polish_acceptance_20261022` |
| 关键配置 | 基线 `e6e0d87`；删除 `local_polish` 及其专用辅助函数、搜索调用，以及 `local_steps`、`local_lr`、`local_lr_end`、`local_beta`、`local_mode` 五个配置字段。苍南 1800×1800，77×51.5 m，无原点、关闭需求点目标、四连通，seed 123；复跑高斯 40、高斯 100、均匀 100、田口 100，均为 90 代、前期 8 步 Adam 引导，末 30 代变异步长收至 0.2 |
| 输出目录 | `outputs/remove_local_polish_tests_20261022/full.xml`；`outputs/remove_local_polish_acceptance_20261022/`，含 `removal_equivalence.json`。本机验收产物不加入提交 |
| 主要结果 | 完整 pytest **370 passed**，无失败或跳过。删除 3 个仅针对已移除算子的测试；在三种初始化 × 有/无分区边界的 6 组实际 CUDA 搜索中追加断言，返回的全部 raw pose 与演化选择终点逐位相等。真实场景四组均完成，共 340 个最终个体全部可行；16 个初始化、引导后、最终种群与 Pareto CSV 文件均与此前 seed 123 结果逐字节相等，输入哈希不变。初始化模块、前期引导及分区搜索保持通过 |
| 取消处理 | 未完成的学习率研究已停止，原始诊断和源码快照以 `CANCELLED.json` 标记保留，列于下方存疑产物，不形成正式研究结论；撤销了本轮尚未提交的研究脚本、测试和文档入口。已核对过期文件，未删除原始数据或已有有效实验产物 |
| 相关提交 | 本条所在提交；验收基线 `e6e0d87` |
| 状态 | 有效 |

## 张量 NSGA-II 定稿前验证（由最终对照替代）

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-22 |
| 实验名 | Tensor NSGA-II preliminary implementation checks |
| 目的 | 定位旧版逐对排序瓶颈，核对第一版张量算子与精确建模口径；此阶段的性能数字由下方最终源码对照替代 |
| 入口 | `experiments/compare_tensor_nsga2.py`；`outputs/tensor_nsga2_comparison_20261022/validate_reports.py` |
| 关键配置 | 基线 `6740ce9`，苍南 1800×1800，77×51.5 m，uniform，90 代、8 步 Adam、末 30 代变异步长收至 0.2，四连通、高程权重 1、无原点、关闭需求目标。预检用 seed 123，对照旧版 100 与张量版 100/400/1000；随后 10 seed 比较旧版 100 和张量版 100/400/1000/1600，共 50 次搜索 |
| 输出目录 | `outputs/tensor_nsga2_pilot_20261022/`（含旧版 cProfile）；`outputs/tensor_nsga2_comparison_20261022/`（含 50 次 CSV 与精确复核摘要）；起始源码和配置备份为 `outputs/tensorization_20261022/` |
| 主要结果 | 旧版带 cProfile 的 23.681 s 中，181 次非支配排序累计 20.099 s，说明逐对支配比较是主要瓶颈。第一轮单 seed 的旧版 100 为 13.528 s，张量版 100/400/1000 为 0.926/2.229/5.166 s。中间 50 次搜索均完成，32000 个最终个体全部可行；32000 个最终位姿与另一批 1000 个未经引导的随机位姿，目标值、随机位姿违例和可行性与原评价严格相等，最大绝对差为 0；随机位姿有 465 个可行、133 个进站不可达 |
| 替代原因 | 定稿时把批量足迹几何与禁止格计数按模块职责分开，并补充静态掩膜校验。最终源码重新跑完整对照，以最终条目作为性能与质量结论；本条产物保留为布局整理前后的逐行回归输入，不删除原始数据或已有有效产物 |
| 相关提交 | 本条所在提交；旧版对照 `6740ce9` |
| 状态 | 作废 |

## 张量化 NSGA-II 与大种群正式对照

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-22 |
| 实验名 | Tensor NSGA-II final runtime and front-quality comparison |
| 目的 | 将选择、算术交叉、高斯变异、约束非支配分层、拥挤距离和环境选择改为 PyTorch 批量运算，验证更大种群能否在旧版搜索时间内改善搜索质量 |
| 入口 | `python -m experiments.compare_tensor_nsga2 --output-dir outputs/tensor_nsga2_final_20261022 --baseline-ref 6740ce9 --seeds 123 456 789 1011 1213 1415 1617 1819 2021 2223 --populations 100 400 1000 1600`；`outputs/tensor_nsga2_final_20261022/validate_reports.py`；完整 `pytest -q` |
| 关键配置 | 基线 `6740ce9`，苍南 1800×1800，足迹 77×51.5 m，uniform，90 代、8 步 Adam、学习率 0.05，变异步长 1、末 30 代降至 0.2；四连通、高程权重 1、无原点、关闭需求目标、无手绘范围、山体和农田允许。旧版 100；张量版 100/400/1000/1600；10 个共同 seed，seed 内轮换组别运行顺序，评价批大小 256。RTX 4090，PyTorch 2.11.0+cu126。前期引导和初始化沿用原实现，无演化后局部微调 |
| 评价口径 | 只建一次共同距离场，建场耗时 4.311 s，单独记录。各组第一次完整调用单独保存在 manifest，正式均值取预热后的完整搜索（初始化、引导、演化、最终报告）；CSV 写入和质量汇总不计时。张量版采用独立 torch Generator，旧版采用 NumPy 随机流，不承诺同 seed 与旧版逐代轨迹相等。合并全部最终可行前沿得到 46 个唯一经验参考点，统一 ideal/nadir 归一化、每维参考点 1.1，计算 HV/IGD+；大种群有更多评价预算，不称等评价次数收益 |
| 输出目录 | `outputs/tensor_nsga2_final_20261022/`，含输入/源码 SHA256、旧版源码快照、完整配置、50 份最终 CSV、共同参考前沿、`runs.csv`、`summary.json`、`paired_summary.json`、`evaluation_validation.json` 和 `layout_equivalence.json`。本机输出不加入 Git |
| 主要结果 | 50/50 次搜索完成，32000 个最终个体全部可行。相同 100 个体平均从 13.873 s 降至 0.979 s，约 14.17 倍加速。1000 个体平均 5.411 s，HV 比旧版 100 高 8.35%，IGD+ 低 71.68%；1600 个体平均 8.501 s，HV 高 9.33%，IGD+ 低 78.04%，种群扩大 16 倍而平均用时减少 38.72%。1600 最慢 8.873 s 仍低于旧版 100 最快 13.422 s。1600 的两项质量指标按同 seed 各胜 9/10；1000 的 HV 胜 10/10、IGD+ 胜 9/10。100 个体两项各胜 5/10，不把随机流切换解释为质量提升 |
| 验证 | 完整 CUDA pytest **390 passed**，无失败或跳过。独立标量参考覆盖支配、rank、拥挤距离与选择，固定随机输入核对交叉/变异，检查 seed 复现。合成图覆盖旋转足迹、越界、零跨度、相同违例、四/八连通、道路分量与 5 cm 末段。另以最终源码复核 32000 个最终位姿与 1000 个未经引导的随机位姿，目标最大绝对差均为 0，可行性与随机位姿违例不一致数均为 0；随机样本中 465 个可行、133 个进站不可达。50 份最终方案 CSV 与模块职责整理前逐字节相等；输入哈希和最终运行源码哈希不变 |
| 实现边界 | 种群、演化算子和普通格精确评价驻留设备；足迹评价按批处理。连续道路接触点保留小批 CPU 精确查询，默认关闭的自适应 HV 监测仍用 CPU，前沿推进有控制同步；不宣称全程序没有 CPU。支配矩阵仍为 O(N²)，结论限定本场景、硬件和配置，不保证任意种群恒定耗时或全局最优。默认种群保持 100，较大规模通过显式 `popsize` 选择；田口仍要求完全平方数。已核对助手知识、文档索引与过期产物，本轮未删除原始输入或有效实验输出 |
| 相关提交 | 本条所在提交；旧版基线 `6740ce9`，运行时未提交的最终源码由 manifest SHA256 标识 |
| 状态 | 有效 |

以下为 10 个 seed 的均值 ± 样本标准差。时间为完整搜索秒数，显存为 `torch.cuda.max_memory_allocated` 的 MiB，不是整卡占用。

| 实现 | 种群 | 搜索耗时 | HV（越大越好） | IGD+（越小越好） | 峰值张量显存 MiB |
| --- | --- | --- | --- | --- | --- |
| 旧版 | 100 | 13.873 ± 0.292 | 1.153258 ± 0.055478 | 0.090504 ± 0.040106 | 152.8 |
| 张量版 | 100 | 0.979 ± 0.074 | 1.156914 ± 0.042620 | 0.090124 ± 0.028677 | 172.5 |
| 张量版 | 400 | 2.436 ± 0.097 | 1.225261 ± 0.020629 | 0.037499 ± 0.015813 | 324.4 |
| 张量版 | 1000 | 5.411 ± 0.206 | 1.249502 ± 0.011067 | 0.025635 ± 0.005908 | 670.4 |
| 张量版 | 1600 | 8.501 ± 0.211 | 1.260801 ± 0.011410 | 0.019873 ± 0.005195 | 1017.1 |

## 可选择演化后端与无 CUDA 自动回退验收

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-22 |
| 实验名 | Selectable tensor/NumPy evolution and complete CPU fallback |
| 目的 | 将张量化与原版演化分别模块化，默认选择张量版，允许显式选择原版；没有可用 CUDA 时完整使用 NumPy 演化和 CPU 评价/Adam，不改变算法参数 |
| 入口 | 完整 `pytest -q`；`tests/test_evolution_backends.py` 和模型测试在 `CUDA_VISIBLE_DEVICES=` 的独立进程；`python -m experiments.validate_evolution_backends --output-dir outputs/evolution_backend_validation_20261022/gpu --reference-dir outputs/tensor_nsga2_final_20261022`；`CUDA_VISIBLE_DEVICES= OMP_NUM_THREADS=4 python -m experiments.validate_evolution_backends --output-dir outputs/evolution_backend_validation_20261022/no_gpu` |
| 关键配置 | 基线 `64404f2`，原版 NumPy 算子来自 `6740ce9`。苍南 1800×1800，足迹 77×51.5 m、uniform、种群 100、90 代、前期 8 步 Adam、学习率 0.05，变异步长 1、末 30 代收到 0.2，seed 123；四连通、高程权重 1、无原点、关闭需求目标。GPU 与完全隐藏 CUDA 两种环境分别请求 `tensor` 与 `numpy`；请求设备仍为默认 `cuda`。PyTorch 2.11.0+cu126，GPU 为 RTX 4090；验收进程 `OMP_NUM_THREADS=4`。本轮记录冷启动完整调用，不据此重算此前预热性能结论 |
| 输出目录 | `outputs/evolution_backend_validation_20261022/`：`full.xml`、`no_gpu_tests.xml`、`cpu_model_tests.xml`；`gpu/` 和 `no_gpu/` 下的输入/源码哈希、完整配置、两份最终 CSV、运行摘要与精确复评结果。本机产物不加入 Git |
| 主要结果 | GPU 环境正确分别运行 `tensor` 和 `numpy`，实际评价设备均为 `cuda:0`；两份 CSV 分别与模块化前对应的 seed 123、100 个体结果逐字节相等。隐藏 CUDA 环境真实检测为不可用，两种请求均完成 NumPy/CPU 搜索；保留完整 100 个体、90 代和 8 步引导，二者最终 CSV 逐字节相等。4 次真实搜索共 400 个最终个体，全部可行；同设备方案重算的全部目标最大绝对差均为 0，输入和运行源码哈希不变。GPU 两次完整调用约 1.965/13.520 s，CPU 自动/显式原版约 20.491/19.627 s，仅为本轮功能验收的观测时间。验收后仅清理 NumPy 模块末尾多余空行，AST 严格相同，原始源码快照与提交版哈希已追加到 manifest |
| 验证 | 完整 CUDA 环境 pytest **422 passed**，无失败或跳过。CUDA 隐藏的后端/完整任务回归 **23 passed**（显式排除 3 个 GPU 组合），另有 CPU soft 模型/解码/非法输入 **6 passed**（仅选择 CPU 组合）。原版固定 seed 17 的 8 个体、4 代结果与 `6740ce9` 严格相等。三种初始化 × 有/无分区边界的 CPU 搜索保留梯度引导、精确报告和 seed 复现；CPU/CUDA 评价在数值容差内一致。实际临时任务写出标准 CSV、图件和摘要；矩形分区继承实际后端及设备元数据 |
| 实现与边界 | `evolution_backend` 接受 `tensor`（默认）或 `numpy`；`evolution.py` 统一分派，`tensor_nsga2.py` 与 `numpy_nsga2.py` 分别维护算子，两个评价装配共用模型公式。引导任务和方案重算在创建场景张量前解析设备；CPU soft forward/backward 正常执行。显式 CPU 也选择 NumPy，GPU 上显式 NumPy仍可用 CUDA 评价。后期局部微调保持移除；没有静默降种群、代数或跳过引导，也不以 OOM/算法错误触发回退。其他研究算法的 CUDA 入口规则保持不变。已同步助手参数边界、权威文档和索引，并核对过期文件；本轮未删除原始输入或有效实验产物 |
| 相关提交 | 本条所在提交；模块化前基线 `64404f2`，原版算子 `6740ce9` |
| 状态 | 有效 |

## 道路 Voronoi 分块 CUDA 构建与 9 km 压力验收

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-22 |
| 实验名 | Exact CUDA segment Voronoi with bounded memory |
| 目的 | 加速道路 Voronoi 构建，保持原版逐格最近连续线段编号和等距规则，验证 9000×9000 的时间、显存及主机内存，并排查后续大场景瓶颈 |
| 入口 | `python -m experiments.compare_road_voronoi --output-dir outputs/road_voronoi_tensor_acceptance_20261022 --repeats 3 --threads 64 --product-config config/default_config.json`；完整 `pytest -q`；隐藏 CUDA 后运行 `tests/test_road_voronoi.py tests/test_traffic_topology.py`；输出目录中的 `measure_process_memory.py` |
| 关键配置 | CPU 原版来自 `a4e4f4a:data_tools/traffic_tool.py`，原函数体和装饰器 AST 与现 CPU 模块一致。Intel Xeon Platinum 8468，Numba 64 线程；RTX 4090，PyTorch 2.11.0+cu126，Triton 3.6.0。1 m 栅格，GPU 像素块 1048576，线段归约块 128。原始苍南为 1800×1800、859 段；9 km 稀疏压力场将坐标乘 5；密集压力场将原道路平移为 5×5 份，21475 段。两种 9 km 输入均为明确构造的压力场景，不是新增真实区域数据 |
| 评价口径 | 每场景 CPU/GPU 各 3 次，首次配对后轮换运行顺序；表中为后两次的中位数。计时包含完整标签分配、距离计算、归约和 GPU 到 CPU 拷贝；不含设备初始化、磁盘 I/O、逐格比较和哈希。首次调用另存，原场景 CPU/GPU 首次测得 1.427/0.466 s，包含各自尚未缓存的导入/JIT，但不声称都是清空编译缓存后的冷启动。所有标签按 int64 完整逐格比较，并核对 SHA256，不使用误差容差或抽样代替 |
| 输出目录 | `outputs/road_voronoi_tensor_acceptance_20261022/`：原 CPU 源码快照、运行时实验脚本快照、输入与源码哈希、18 次运行记录、`summary.json`、`product_validation.json`、`memory_validation.json`、完整/无 GPU pytest XML，及真实 GeoJSON 重建得到的 CPU/auto 两组道路文件。`portable-launcher-smoke/` 验证公开脚本去除本机 RTK 命令包装后直接调用系统 Git/NVIDIA 工具；AST 确认只改这两处包装，三个核心模块哈希与正式计时一致。本机产物不加入 Git |
| 主要结果 | 18/18 次完整构建完成，每场景所有 CPU/GPU 结果的 SHA256 相同，逐格编号不一致数全部为 0。9 km、859 段从 3.872 s 降至 0.422 s，约 9.17 倍；保持道路密度的 21475 段从 67.775 s 降至 4.139 s，约 16.38 倍。真实 GeoJSON 的投影、拓扑简化、保存和重读同样通过；`auto` 实际使用 CUDA，线段数组与已有苍南产物严格一致 |
| 内存 | 密集场景张量峰值 8,732,672 字节（8.33 MiB），PyTorch 保留峰值 22 MiB。独立进程运行期间 NVIDIA 采样 64 次，观察到的进程显存峰值 408 MiB，含 CUDA 上下文；采样间隔为 50 ms 加命令开销，不作为瞬时显存峰值的严格上界。单幅主机输出 648,000,000 字节（617.98 MiB）；独立 GPU 构建进程 RSS 高水位约 1.29 GiB，CPU/GPU 对照进程同时保留两幅标签，RSS 高水位约 2.05 GiB。独立显存验收输出哈希也与原 CPU 密集场景一致 |
| 验证 | 原基线完整 pytest **449 passed**；整合最新远程 `e190738` 的道路退距和 10 km 上限后，补齐演化后端合成测试场景显式 landuse，完整 pytest **466 passed**，无失败或跳过。原基线真实隐藏 CUDA 后 **25 passed, 11 skipped**；整合后连同演化回退再验收 **48 passed, 11 skipped, 3 deselected**，跳过和显式排除项均为 GPU 用例。小图回归覆盖 NumPy 双轴分块、所有线段块大小、像素尾块、非整数分辨率、共享端点、跨线段块等距、9 km 坐标近等距、显存随块而非全图大小增长、非法输入、无 CUDA/无 Triton 回退、落盘数组与 metadata |
| 后续瓶颈 | 按现代码 dtype 的静态核算见 `markdown/MODELING_MODULE_SUMMARY.md`「大场景的后续瓶颈」。优先处理 Gate×全部道路的 float64 全量广播，再评估加权 Dijkstra、全图张量重复、缓存容量与全量加载/校验，以及新加入的道路退距 CPU 距离变换；NSGA-II 另受种群平方支配矩阵影响。本次未运行完整 9 km 选址流程，不把 Voronoi 通过解释为全链路可用 |
| 实现与同步 | CPU/CUDA 分模块，默认 `auto`，无 CUDA/Triton 回 CPU，显式 CUDA 缺失时报错；分块上限、设备及后端均可配置，三个数据入口一致传参。使用 float32 原运算顺序、正确舍入除法并关闭乘加融合，保留最小编号平局规则，不降分辨率、不删道路、不改简化。已同步数据、建模、测试和代码地图文档，并按 `AGENT_MODULE.md` 核对内部助手边界；本次不新增地图操作。已核对过期产物，本轮未删除原始输入或有效实验输出 |
| 相关提交 | 本条所在提交；CPU 基线 `a4e4f4a`，最终整合基线 `e190738`；三个计时核心模块在整合前后哈希一致，正式运行源码与最终源码哈希及等价性核对保存在 manifest |
| 状态 | 有效 |

以下均为完整 Voronoi 标签构建的预热时间，不包含输入读取、道路简化或文件写入。

| 场景 | 栅格 | 线段数 | CPU 秒 | CUDA 秒 | 加速比 | 逐格编号不一致数 |
| --- | --- | --- | --- | --- | --- | --- |
| 原始苍南 | 1800×1800 | 859 | 0.2023 | 0.0205 | 9.87 | 0 |
| 坐标放大压力场 | 9000×9000 | 859 | 3.8725 | 0.4225 | 9.17 | 0 |
| 5×5 平铺压力场 | 9000×9000 | 21475 | 67.7751 | 4.1388 | 16.38 | 0 |

## 引导搜索实际 GPU/CPU 执行核验与阶段显示

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-22 |
| 实验名 | Actual NSGA-II execution visibility |
| 目的 | 核验用户最近一轮 10000 个体是否实际使用 CUDA，并在运行消息中区分实际演化/评价设备和 CPU 建场、初始化、演化、最终报告与文件输出 |
| 入口 | 只读 `GET /api/v1/jobs/d06a87d7-7f74-4e8d-8e0b-72b13591443c`；读取 `outputs/site-20261022-215208/normalization.json` 与 `run_summary.json`；完整 `pytest -q`；后端聚焦回归与隐藏 CUDA 回归；`frontend/` 下 `npm run test:problem-snapshot`、`npm run build` |
| 关键配置 | 用户已完成任务 `site-20261022-215208`，实际种群 10000、90 代、uniform、seed 123、请求和实际演化后端均为 tensor、评价设备 cuda:0、无回退。GPU 进程为本仓库 8010 端口的 Uvicorn/内置 Worker，显卡为 RTX 4090。新增设备描述按已解析的实际设备生成，不依据请求默认值或 CUDA 可用性猜测 |
| 输出目录 | `outputs/execution_visibility_20261022/`：`observed_job.json` 保留任务身份、实际配置、结果摘要及原 normalization 文件哈希；`full.xml`、`focused.xml`、`no_gpu.xml` 保留回归结果。本机产物不加入 Git |
| 主要结果 | 真实任务已成功完成，10000 个方案全部可行，最终 Pareto 方案 7 个；元数据确认 tensor/cuda:0，确实采用 GPU 张量演化。任务创建至完成约 199.58 s，包含全部前后处理，不当作纯演化计时。核验时该任务已结束，API 进程仍保留约 8564 MiB 显存，而瞬时 GPU 利用率为 0%，因此这两个读数不能单独证明或否定当时的 GPU 计算 |
| 实现 | `evolution.describe_evolution_runtime` 区分 GPU 张量演化、CPU NumPy 演化配 GPU 评价、完整 CPU。`GuidedSearch` 在初始化前、每代完成后和最终报告前发送含设备描述的消息，并将 `execution_description` 保存到 normalization。任务装配在读场景和 CPU 距离场阶段即显示设备配置；分区汇总保留该字段；输出阶段明确为 CPU 图件/文件处理。现有地图工作栏与运行页直接展示消息，阶段名称为中文；后端日志同时记录实际设备、种群和代数 |
| 验证 | 完整 CUDA 环境 pytest **468 passed**；并行功能合并到 `b26fcfe` 后最终完整回归 **471 passed**，均无失败或跳过。最终文案与阶段调整后聚焦回归 **49 passed**。真实隐藏 CUDA 的演化回退回归 **25 passed, 3 deselected**，显式排除三项 GPU 专用组合。覆盖有 GPU 时显式 CPU 不误报、真实 CUDA tensor/NumPy 区分、三种初始化、进度单调、报告阶段、消息与保存元数据一致、带/不带 reporter 的 CPU 搜索结果严格相同。前端原生断言及完整构建均通过 |
| 边界 | 本次不改变种群、随机流、交叉变异、梯度引导或停止条件，不加入早停，也未据此判断 10000 个体主要慢在何处。现有 API 没有自动重载，新的消息在后端下次重启后加载；已完成任务保留原消息。早停策略需另行做质量/总耗时对照，不能把已有 CPU 递归 HV 步长控制直接当作早停 |
| 同步 | 已同步运行显示权威文档、算法元数据口径、测试策略与内部助手知识边界；不新增 Agent 操作。保留工作区原有种群默认值等并行修改，提交仅包含本次设备显示。已核对过期产物，未删除原始数据或有效实验输出 |
| 相关提交 | 本条所在提交；核验时本地已提交基线 `eec1ad6`，最终验证基线 `b26fcfe`；实际已完成任务的配置和证据以保存的原文件哈希为准 |
| 状态 | 有效 |

## 最新修改发布前回归验收

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-22 |
| 实验名 | GitHub publication regression for current changes |
| 目的 | 在推送前核对未同步的 Voronoi CUDA 加速、实际设备/阶段显示，以及工作区已有的 10000 个体默认值和依赖文件拆分，修正遗漏的测试文档 |
| 入口 | 完整 `pytest -q`；`CUDA_VISIBLE_DEVICES= OMP_NUM_THREADS=4 pytest -q tests/test_evolution_backends.py -k 'not test_cuda'`；`frontend/` 下 `npm run test:problem-snapshot`、`npm run build`；`python -m pip check`；Conda 环境解析与依赖声明比对 |
| 关键配置 | 发布前基线 `d279bd8`，远程 `972c017`；默认种群 10000、uniform、90 代、tensor 优先，评价批次 256。测试环境为 PyTorch 2.11.0+cu126、RTX 4090；完整测试显式使用 CUDA，另一个独立进程完全隐藏 CUDA。测试使用各自的小型显式配置，不把 pytest 计时当作 10000 个体性能实验 |
| 输出目录 | `outputs/github_publish_validation_20261022/`：`full.xml`、最终 `final.xml`、`no_gpu.xml`、`dependency_validation.json`、`manifest.json`，以及未发送给外部模型的六条聚焦助手评测输入。本机产物不加入 Git |
| 主要结果 | 最终完整回归 **472 passed**，无失败或跳过；隐藏 CUDA 回退 **25 passed, 3 deselected**，排除项均为 GPU 专用测试。前端原生断言和生产构建通过。新增 10000 个体正交表两两组合全覆盖回归通过；项目 JSON、dataclass、插件和助手说明的默认种群一致。Conda 能解析根目录 `requirements.txt` 引用，拆分保留原有全部 20 项普通 pip 直接依赖，当前验证环境全部已安装且满足约束，`pip check` 无损坏依赖；未重新安装环境 |
| 助手同步与边界 | 更新默认种群事实并新增拒绝覆盖默认值的评测用例；完整测试中的本地脚本模型及助手同步回归通过。六条聚焦外部模型评测的执行请求被自动审批拒绝，原因是没有明确授权将评测数据发送至外部模型；没有发送数据，也未将本地回归解释为真实模型语义评测。既有性能与精确一致性结论仍以各自实验条目为准，本次不重复大场景计时、不加入早停、不重启现有服务 |
| 文档与产物 | 同步测试策略中的旧默认值和依赖入口，核对算法、运行指南、代码地图及助手知识；已核对过期文件，未删除原始数据或有效实验产物 |
| 相关提交 | 本条所在提交；待一同发布的功能提交 `25dbf1e`、`eec1ad6`、`d279bd8`，以及整合提交 `b26fcfe` |
| 状态 | 有效 |

## 约束域内初始化快速验收

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-22 |
| 实验名 | Initial centers inside feasible polygons and outside exclusions |
| 目的 | 修正全场景撒点后再判违例的初始化方式，直接在当前允许域内生成中心点，并验证前期引导不会把演化起始种群中心推到圈外 |
| 入口 | `pytest -q tests/test_constrained_initialization.py tests/test_initialization.py tests/test_site_plugin_schema.py tests/test_agent_sync.py` |
| 关键配置 | 基线 `4ee1b93`。合成 64×64、1 m 场景，矩形尺寸 4×4 m；每个大样本用例显式指定种群 10000、seed 123、引导 0 步，不依赖工作区默认种群。三种请求方式分别覆盖凹多边形加内禁区、两个分离三角形、仅禁区和半米见方的小可行域；另测非整数分区边界、空域、部分格子的面积权重、CPU/CUDA 实际解码和 8 步刻意朝圈外推动的 Adam 更新。CUDA 为 RTX 4090 |
| 输出目录 | `outputs/constrained_initialization_20261022/`：`quick.xml`、最终 `quick_final.xml` 和 `manifest.json`。本机验证产物不加入 Git |
| 主要结果 | 最终 **50 passed**，约 **2.96 s**，无失败或跳过；其中初始化与原始采样检查 **37 项**。12 组 CPU 大样本与一组 CUDA 大样本均生成完整 10000 个中心点，硬格违例和独立 Shapely 多边形圈外/禁区内检查均为零；相同 seed 严格复现。受约束的高斯/田口请求实际输出与同 seed 均匀采样相同；无约束矩形仍保留原田口正交序列。非整数分区不越界，空域明确报错，不用域外点补齐；强制大步长的 8 步引导逐步及结束后仍全部保持允许中心 |
| 装配与记录 | 表单原始多边形进入 context，避免只按 `all_touched` 栅格接纳画线外的边缘点；实际初始化方式、请求方式和切换原因写入结果元数据及进度。分区清单记录各分区实际方式；历史三方法比较在实际将改用均匀时于搜索前拒绝运行，防止错误标记田口结果 |
| 范围 | 仅验证中心点初始化与前期引导，不运行演化、不比较优化质量或完整任务耗时。旋转建筑完整足迹和进站可达性仍由既有硬约束评价，后续交叉变异仍可产生不可行个体。测试通过后只同步记录；没有重启服务，也未修改工作区并行调整的默认种群 |
| 文档与同步 | 已同步算法、建模、测试策略、README、代码地图及内部助手知识；不新增助手编辑操作。已核对过期产物，未删除原始数据或有效实验输出 |
| 相关提交 | 本条所在提交；初始化修正基线 `4ee1b93`；并行的种群默认值修改不纳入本次提交 |
| 状态 | 有效 |

## 种群与代数预算快速对照及显存分块

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-23 |
| 实验名 | Population/generation budget quick comparison |
| 目的 | 看扩大种群、减少代数能否缩短求解时间而不降低前沿质量；为 50000 以上种群去掉显存瓶颈 |
| 入口 | `outputs/population_budget_20261023/quick_arm.py`（单个配置）、`hv_igd.py`（共同参考前沿下的 HV/IGD+）、`profile_stages.py` 与 `profile_eval_batch.py`（分阶段计时） |
| 关键配置 | 苍南场景，seed 123，uniform 初始化，tensor 后端，RTX 4090。配置写作“种群×代数×末段退火代数”，其余参数取 `config/default_config.json` |
| 输出目录 | `outputs/population_budget_20261023/`，每个配置一个 `arm-*` 目录，含 `front.npy` 与 `summary.json`。本机产物不加入 Git |
| 主要结果 | 10000×90×30：55 s，HV 1.2665，IGD+ 0.0072；30000×40×15：91 s，1.2739，0.0054；20000×30×10：43 s，1.2458，0.0146；10000×50×17：33 s，1.2512，0.0112；10000×50×30：33 s，1.2541，0.0100。参考前沿由五组合并得到。少代数省时约 40%，但 HV/IGD+ 明显变差；用户决定保留 10000×90×30 |
| 显存 | 原实现在 50000 时 OOM（N×N 支配矩阵、整批引导 Adam、整批最终报告）。改为分块非支配计数、`guide_batch_size` 分块引导和 `REPORT_BATCH` 分块报告后，10000 峰值约 4.8 GB；100000 可以运行，但每代约 9 s（排序约 5 s，评价约 4 s），不适合交互演示 |
| 验证 | 完整 pytest **518 passed**；分块排序在极小块与默认块下名次一致，分块引导与整批引导结果一致（atol 1e-6）；前端断言和构建通过 |
| 边界 | 单 seed，只用于决定默认值，不作为算法质量结论；多 seed 预算研究另做 |
| 相关提交 | 本条所在提交 |
| 状态 | 有效 |

## 高德道路 Shapefile 试验替换楠溪江路网

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-25 |
| 实验名 | Gaode road-source replacement on the prepared Nanxijiang scene |
| 目的 | 检查用户提供的温州高德道路是否可替换当前 OSM 中心线，并利用已准备场景网格重建道路 Voronoi，避开对缺失原始影像的依赖 |
| 入口 | `python -m experiments.import_road_shapefile`；`PYTHONPATH=. python outputs/gaode_road_evaluation_20261025/validate_trial.py`；本机发布及 API 复核脚本 `outputs/gaode_road_evaluation_20261025/apply_trial.py` |
| 关键配置 | 原始 RAR 为用户提供的 `温州市_gaode_road.rar`，包含一套 UTF-8 PolyLine Shapefile，234712 条记录、1991853 个顶点，PRJ 声明 WGS84。目标为楠溪江 `lat28.246100_lon120.810600_r4.500km_z18_g9000x9000_rb500m` 的 EPSG:3857、9000×9000 已准备网格，显式保留图幅外 500 m 缓冲；排除在建道路、天桥、地道和其他线路。简化容差和 Voronoi 参数来自项目 JSON，本次实际采用 CPU 后端。独立距离抽查 seed 123、256 个格心；旧道路按场景内约 10 m 间距采样 |
| 输出目录 | `outputs/gaode_road_evaluation_20261025/`：源文件检查、两场景初步对齐与拓扑诊断、`nanxijiang_preview/` 完整候选道路 bundle、`trial_validation.json`、`road_comparison.png`、`regression.xml`、`publication_verification.json`。原始 RAR、解包数据和本机产物均不提交到 Git |
| 主要结果 | 500 m 缓冲内纳入 277 条折线部分，简化后 3419 条线段；原 OSM 为 994 条。新路网简化前后连通分量均为 12，实际 RoadNetwork 也为 12；旧路网为 6。新路网包含更多支路和独立路段，不按追求连通而强行合并。新路网简化后总长约 176831.4 m，含图幅外缓冲。旧路网在图幅内 5687 个采样点到高德路网的中位距离 3.0117 m、P90 为 13.2162 m，91.84% 在 15 m 内；这只验证两份数据的空间一致性，不代表测绘精度 |
| Voronoi 核验 | 生成完整 9000×9000、int64 最近线段标签。256 个格心用独立 float64 点到线段距离复算，0.0001 m 容差下无距离违例；2 个近似并列点的标签与独立最小索引不同，最大距离差约 0.00000537 m，不将浮点近似并列误报为米级误差 |
| 发布与保留 | 结束所有已知活动任务核对后暂停本仓库 API，备份并发布道路 bundle，再恢复 API。旧道路备份为 `outputs/scene-road-backups/lat28.246100_lon120.810600_r4.500km_z18_g9000x9000_rb500m/20261025T101417Z-78dc3f4a/`。逐文件 size/mtime 核对非道路文件全部未变，场景 metadata 除道路段外完全一致。网页代理的地图资源和道路线段接口均 HTTP 200，来源 gaode、线段数 3419、场景 ready |
| 验证 | 最终可访问 CUDA 的相关 Python 回归 139 passed，覆盖外部线导入、原道路简化/Voronoi、退距、HaulField、场景、Agent 与助手同步；其中导入新测 9 项。前端生产构建与全部 `test:problem-snapshot` 断言通过。验收同时修复远程可行性预取闭包的可选 scene id 类型错误，并将已固定八连通的报告测试从旧开关断言同步到当前口径 |
| 边界与同步 | 本次只切换楠溪江，其他场景保留原道路。试验入口为本机脚本，网页数据上传仍是永农导入；可借鉴其预览确认流程接入道路上传，但不能把折线直接当禁建面烧录。完整场景重建仍可能恢复登记的原始道路来源。新路网未提供路宽、通行方向或完整桥梁高程层，模型继续沿用已有中心线语义。旧优化结果不自动改写，新的搜索和评价读取新路网。同步数据、建模、前端、运行指南、测试策略、代码地图和助手知识；新增路网导入拒绝/通用道路显示用例，未新增 Agent 操作。核对本轮产物，无原始输入或有效实验目录删除 |
| 相关提交 | 本条所在提交；实施基线 `e5009a9` |
| 状态 | 有效 |

## 道路发布回滚保护与类别字段校验修复

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-25 |
| 实验名 | Road bundle rollback failure and class-schema regression |
| 目的 | 修复 `94fa288` 中发布失败后回滚再次失败却解除读保护，以及指定排除类别但源文件缺少 `class` 时静默纳入全部道路的问题 |
| 入口 | `python -m pytest -q tests/test_road_import.py tests/test_scene_store.py tests/test_coordinate_scene.py tests/test_traffic_topology.py tests/test_road_voronoi.py tests/test_road_setback.py tests/test_haul_field.py tests/test_v0_plugins.py tests/test_site_plugin_schema.py --disable-warnings --junitxml=outputs/road_publication_fix_20261025/regression.xml`；对正式楠溪江道路做只读 SHA-256 和 metadata 比对 |
| 关键配置 | 3×4 临时合成场景；第二次文件发布注入异常，随后在首次或中途回滚写入再次注入异常；新导入和旧重建入口分别覆盖。SHP/ZIP 将 `class` 改为 `fclass`，分别验证带和不带排除条件的行为。额外覆盖原本缺少 sidecar 的成功回滚，以及候选不完整时拒绝开始发布 |
| 输出目录 | `outputs/road_publication_fix_20261025/`：`regression.xml` 保存相关回归结果，`published_scene_verification.json` 保存正式道路哈希和 metadata 一致性证据。本机验收产物不提交到 Git |
| 主要结果 | 修复前新增聚焦用例为 6 failed、2 passed：两条发布路径的首次/中途回滚失败均删除了保护标记，SHP/ZIP 缺字段时均未报错；无排除条件的两项正常读取通过。修复后完整相关回归 136 passed，无失败或跳过，运行环境可访问 CUDA，已有 CUDA Voronoi/退距检查一并通过 |
| 实现 | 两条入口持有同一场景写锁并调用 `publish_road_bundle`。候选齐全后备份，保护标记记录产品 id、绝对备份路径和原先不存在的文件。只在完整发布或完整回滚后移除标记；二次回滚失败保留标记，并报告发布原因、回滚原因和备份位置。原先不存在的 sidecar 在成功回滚后恢复为不存在。请求类别排除时在遍历要素前检查准确的 `class` 字段，缺字段列出实际字段并报错，不扩展字段映射 |
| 正式数据核对 | 本轮未重建或发布正式场景。楠溪江仍为 gaode、3419 条线段；正式线段 SHA-256 为 `ad41f3f191bbb23dd4fb795b4d661942cdc5611d7b2dad9a330b9863fd4ee181`，正式 Voronoi SHA-256 为 `ec7d8f2797a680ff165415a4a7472e1c409044012d5ddc23ff15144f6068dfdb`，均与原已发布候选完全一致。两份道路 sidecar 与道路 metadata 相同，非道路 metadata 与原道路替换前备份相同，正式场景没有保护标记 |
| 同步与边界 | 更新数据权威文档、运行指南、测试策略和代码地图。仅修复内部发布事务和既有排除参数的输入校验，不新增助手工具或编辑操作；不修改优化算法、前端交互、数据默认参数或完整场景重建的来源选择。原高德试验数据保持有效。核对本轮产物，无原始数据、有效实验或权威文档删除 |
| 相关提交 | 本条所在提交；修复基线 `94fa288` |
| 状态 | 有效 |

## 道路类别、统一数据导入与方案重算修复验收

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-25 |
| 实验名 | Unified road/farmland import, access-only roads and declarative pose evaluation |
| 目的 | 实施统一导入与高速接入计划，连同其依赖的单方案删除、手动添加及重算修复；区分进站接入与沿路运输，防止约束或数据版本变化后指标过期 |
| 入口 | `python -m experiments.migrate_road_kinds`；`python -m experiments.verify_road_kinds --seed 88231 --samples 512`（楠溪江另做 `--check-gates`）；`python -m pytest tests -q --disable-warnings --junitxml=outputs/road_kinds_migration_20261025/regression.xml`；前端 `npm run test:problem-snapshot`、`npm run build`；浏览器脚本 `outputs/road_kinds_migration_20261025/ui_acceptance.cjs`、`ui_drag_rotate.cjs` |
| 关键配置 | 类别规则、导入缓冲和排除类别及高速建筑退距仅取项目默认 JSON。普通路可接入；匝道、高速地表段和隧道只通行，前两类地表线格阻断新建进站路，隧道不阻断地面。高速退距从中心线起量，网格外近邻也参与边界缓冲；不作为从公路用地外缘起量的法规合规证明。Voronoi 只使用普通路，保留全量线段 id 和 int64 存储 |
| 输出目录 | `outputs/road_kinds_migration_20261025/`：各场景 `int64-products/migration.json`、`acceptance/verification.json` 和 `road_kinds_and_setback.png`，楠溪江另有 `gate_verification.json`；`regression.xml`、`acceptance_summary.json`、`real_rar_preview.json`、`ui-acceptance.json`、`ui-drag-rotate.json` 及 UI 截图。原始购买数据、场景和本机验收产物不提交到 Git |
| 场景迁移 | 苍南：859 普通路；27.54 坐标场景：557 普通路、4 匝道、24 高速地表段；楠溪江：3232 普通路、93 匝道、54 高速地表段、40 隧道。三个场景正式线段文件与迁移前逐字节一致；非道路 metadata 不变，两份道路 sidecar 与场景道路 metadata 一致，发布保护标记均已解除。楠溪江高德来源已复制入场景 `road_source_wgs84.geojson`，不再依赖实验目录 |
| 备份 | 最终发布备份分别为 `outputs/scene-road-backups/cangnan/20261025T114343Z-8f9c1364/`、`outputs/scene-road-backups/lat27.543840_lon120.449097_r0.900km_z18_g1800x1800_rb500m/20261025T114344Z-15f06a04/`、`outputs/scene-road-backups/lat28.246100_lon120.810600_r4.500km_z18_g9000x9000_rb500m/20261025T114347Z-9c879aa1/`。最初生成类别前的旧 bundle 备份及完整路径保留在各场景第一轮 `migration.json` 中 |
| 独立检查 | 每个场景独立抽查 512 个格心，标签均指向普通路。苍南和 27.54 场景距离误差为 0；楠溪江最大约 0.0000002246 m。高速退距与独立 KDTree 栅格距离抽查一致。楠溪江实际距离场有 93579 个候选 Gate，其中 91840 个有效；所有接点道路类别均为普通路，高速或匝道地表格上的 Gate 为 0。最终高速建筑缓冲为 341737 格，包含场景外近邻中心线的影响 |
| 导入与回滚 | 三种上传组合、候选过期、来源保存、完整重建保留、按本场景登记来源恢复 OSM、实时重叠及新 multipart API 均有测试。道路/永农共用备份与发布保护；联合发布失败完整恢复，道路回滚再次失败保持不可读。真实 `温州市_gaode_road.rar` 通过本机 API 道路预览，约 4.66 s，类别数与正式楠溪江一致、线段逐字节一致；未确认发布这次预览 |
| 前端验收 | 真实后端验证手动方案、约束在途变化及改回原值、失败重试、删除后切换档位不复活、JSON 导出、鼠标拖动及旋转后重算和 baseline 对比。201 个合成历史方案用真实后端按 200+1 分批评价；改退距后再次 200+1。联合 ZIP 预览走真实 API；数据版本刷新使用浏览器内确认响应和版本桩，触发另一次 200+1，未用合成数据替换正式场景。高德图例、四个道路绘图层和恢复 OSM 按钮已检查，页面脚本异常为 0；控制台唯一 503 是重试测试主动注入的错误 |
| 回归 | 完整 Python 561 passed，无失败或跳过，包含宿主 CUDA 检查；前端全部测试、TypeScript 编译和生产构建通过。真实浏览器发现动态 `line-dasharray` 不受 MapLibre 支持，已改为四个按类别过滤的静态线型图层。另补场景外道路空栅格化、边界高速退距和重算后回到原 key 的回归 |
| 边界 | 楠溪江登记的原始 DEM、landuse、OSM 和卫星影像当前缺失；完整重建仍需要正式原始输入，改回 OSM 在该文件缺失时明确报错，不借用苍南数据。接口在合成场景已验证恢复与保留。Docker 依赖及 libarchive-tools 已配置，本轮没有构建容器镜像。助手固定用例与说明已更新，外部模型评测因自动审批拒绝发送评测内容而未执行；未绕过审批 |
| 同步与清理 | 同步数据、建模、前端、API 架构、运行、测试、代码地图和助手知识。旧永农专用对话框由统一导入组件替代；没有删除原始输入、有效实验目录或权威文档。API 已保留原环境并在无活动任务时重启，网页可直接使用新功能 |
| 相关提交 | 本条所在提交；实施基线 `1cffbd8` |
| 状态 | 有效 |

## 土地修订重算、接点缓存与直连阻断修复验收

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-25 |
| 实验名 | Landuse revision, intrinsic gate validity and direct connector barriers |
| 目的 | 复现并修复 `e937473` 审查中的三个问题：土地修正后沿用旧评价、原点变化重新启用非法接点而丢失缓存、普通路与高速/匝道共格时直连绕过阻断 |
| 入口 | `python -m pytest tests -q --disable-warnings --junitxml=outputs/road_review_fix_20261025/regression.xml`；前端 `npm run test:problem-snapshot`、`npm run build`；本机浏览器脚本 `outputs/road_review_fix_20261025/ui_landuse_revision.cjs` |
| 关键配置 | 临时合成 12×16 网格，普通路与匝道/高速共格，覆盖有无原点和原点移除；独立覆盖永农阻断和隧道地表可通行。土地 API 使用临时 8×9 场景、4×3 建筑。缓存新格式为 `haul-field-elevation-dijkstra-v5-connector-validity`，旧格式首次使用会重新构建 |
| 输出目录 | `outputs/road_review_fix_20261025/`：`regression.xml`、`agent-regression.xml`、`ui-landuse-revision.json`、页面截图、`runtime-jobs.json`、`runtime-restart.json`、`runtime-smoke.json`、`formal_scene_verification.json`。本机产物不提交到 Git |
| 复现与修复 | 修复前新增的 9 项 Python 用例全部失败，前端土地版本用例失败。土地修订计数进入评价 key、请求驱动依赖和过期响应核对；待评价时清除旧目标与可行性。新增 `gate_valid` 保存接点自身合法性，`gate_reachable` 单独表示原点可达子集；缓存保存并校验合法性，重绑原点只计算合法接点。构建与缓存加载共用地表/永农阻断掩膜，两种新建短连接共用阻断检测 |
| 回归 | 完整 Python **577 passed**，无失败或跳过，包含宿主 CUDA；新增 16 项 Python 回归。缓存复用测试禁止调用构建器，并逐数组、评价及路线与重新构建精确比较；另覆盖永农掩膜重新加载、缺失/损坏的合法性数组和旧格式缓存。助手说明同步后，本地助手契约回归另跑 **93 passed**。前端全部断言、TypeScript 与生产构建通过 |
| 土地与网页 | 真实 API 在临时场景上验证可行性随建筑图斑保存、删除依次为 true → false → true。浏览器使用实际 React 效果与地图绘制/橡皮擦手势，土地写入和评价响应用浏览器桩：保存和删除均自动重算，前一版本的延迟响应不覆盖新指标，等待时清除旧值；页面脚本异常为 0。前端断言同时验证待评价助手快照不含旧 objectives/feasible，新评价写入正确可行性 |
| 本机服务 | 当前 API 使用内存任务库；逐一核对本进程启动后创建的唯一任务已 succeeded，再保留原环境重启服务。网页代理健康检查及三个场景图层/道路接口均 200。真实苍南 1800×1800 网格两次评价，原点沿同一道路移动，日志为同 key 的 built → disk_hit；仅作为接口和缓存复用检查，不作为性能基准 |
| 同步与边界 | 同步建模、前端、测试策略、助手权威文档及现有土地微调说明，追加助手问答用例。本轮只验证本地助手契约，未运行外部模型评测；此前自动审批拒绝发送评测内容，本轮未重试。核对正式场景 55 个核心数组、JSON 与来源文件，size/mtime_ns 全部未变。未重新发布道路或修改正式土地数据，未删除原始输入、有效实验或权威文档 |
| 相关提交 | 本条所在提交；修复基线 `e937473` |
| 状态 | 有效 |

## 手动命名保存当前保留方案验收

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-25 |
| 实验名 | Named workspace saves with retained hidden poses and deletion exclusion |
| 目的 | 支持用户手动命名保存当前实验，包含全部未删除方案及被滑块隐藏的方案，重新打开时不恢复已删除方案 |
| 入口 | `POST /api/v1/experiments`；前端「文件 → 另存当前实验…」与「导入案例」；`python -m pytest tests -q --disable-warnings --junitxml=outputs/manual_experiment_save_20261025/regression.xml`；前端 `npm run test:problem-snapshot`、`npm run build`；浏览器脚本 `outputs/manual_experiment_save_20261025/ui_save.cjs` |
| 关键配置 | Python 使用临时 32×32 网格、4×3 建筑及显式 CPU 配置。浏览器使用已准备的苍南场景，合成 4 个输入方案，其中 1 个隐藏、1 个手动；实际保存请求由隔离 API 处理，评价复用真实场景与当前约束，不运行新优化 |
| 输出目录 | `outputs/manual_experiment_save_20261025/`：`regression.xml`、`browser-acceptance.json`、`reloaded-solutions.json`、弹窗及重新导入截图、`runtime-jobs.json`、`runtime-restart.json`、`formal-scene-verification.json`、隔离的 `cases/`。本机验收产物不提交到 Git，也不作为正式算法实验结果 |
| 保存口径 | 前端合并保留集合与当前位姿，后端重新评价全部提交方案，保存精确指标、手动标记、原层级、来源关系、建筑尺寸、约束和场景引用；隐藏、手动及不可行方案可回读。另存使用服务端生成的独立 id，名称只作显示，同名不覆盖原始实验；另存时位姿与指标成为新案例基线，不复制整套场景矩阵 |
| 删除与发布 | 删除最后一个可见方案时保留未删除的隐藏方案，保存和清空按钮按保留总量判断。原始算法结果不用于补回删除项。全部文件写完后原子发布，目录扫描不暴露私有临时目录；写入或发布失败不留下半成品。评价期间场景源版本变化时拒绝保存 |
| 回归 | 完整 Python **588 passed**，无失败或跳过，包含宿主 CUDA；其中手动保存新增 11 项 Python 回归，覆盖真实评价、同名另存、路径隔离、重复 id/空集合/非法值、原始实验保护、忙碌场景、数据变化和失败清理。前端全部断言、生成的实验 API 类型、TypeScript 与生产构建通过；新增前端断言覆盖隐藏集合、当前修改、全部回读及新基线 |
| 浏览器 | 修改角度后删除指定方案，按中文名称保存并重新导入，删除 id 始终不在保存集合中，隐藏方案和手动方案仍在。随后删除全部可见方案，只剩隐藏方案时仍能另存，再导入并展开滑块，JSON 导出仅含该隐藏 id。注入一次 503 后名称保留，重试走真实 API 成功；页面脚本异常为 0。浏览器输入案例通过桩提供，保存、列表、artifact 读取和回读均为真实隔离 API，不把输入桩当正式优化结果 |
| 本机服务 | 核对当前 API 启动后未创建任务，保留环境重启；网页代理健康检查通过，保存接口已注册，空保存返回 422。隔离验收服务已停止，正式场景 55 个核心文件的 size/mtime_ns 均未改变 |
| 同步与边界 | 同步前端、API 架构、代码地图、运行指南、README、测试策略与助手说明，新增助手另存请求拒绝用例并指向真实按钮；不增加助手写操作。本轮通过本地助手契约测试，未向外部模型发送评测内容。核对产物，无原始输入、有效实验或权威文档删除 |
| 相关提交 | 本条所在提交；实施基线 `8b57ce5` |
| 状态 | 有效 |

## GitHub 同步前的合并与回归验收

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-25 |
| 实验名 | Publication review of road kinds, retained workspaces and remote eraser deletion |
| 目的 | 复核土地评价版本、接点合法性缓存和直连阻断修复，并在发布前整合远程橡皮擦删除与本地命名保存功能 |
| 入口 | 完整 `python -m pytest tests -q --disable-warnings --junitxml=outputs/github_publication_review_20261025/regression.xml`；前端 `npm run test:problem-snapshot`、`npm run build`；助手说明同步后的 `tests/test_agent.py`、`tests/test_agent_sync.py`、`tests/test_agent_analysis.py` |
| 关键配置 | 本地基线 `f31c8ed`，远程 `origin/master` 为 `0224aff`。保留六个本地提交及远程删除功能，合并可行性预取函数、前端权威文档和代码地图；测试使用现有配置与临时夹具，完整 Python 检查在可访问 CUDA 的宿主环境执行 |
| 输出目录 | `outputs/github_publication_review_20261025/`：`regression.xml` 与 `verification.json`；本机验收产物不提交到 Git |
| 主要结果 | 完整 Python **588 passed**，无失败或跳过；前端全部断言、TypeScript 和生产构建通过。助手说明去重并补全两个删除入口后，相关本地回归 **45 passed**。静态审查确认前三项问题已修复，命名保存保留隐藏和手动方案并重新评价；未发现本次发布范围内仍阻塞同步的问题 |
| 合并实现 | 详情卡和橡皮擦调用同一单方案删除流程，统一维护保留集合、对比和推荐引用。删除选中项时使旧报告失效并清理卡片和附件；删除非选中项保留当前详情；整个保留集合为空才调用统一清空。橡皮擦保留重算期间拒绝删除的行为，不恢复旧的全局评价状态 setter。沿用现有地图悬停高亮和命中优先级 |
| 验证边界 | 新增前端行为断言覆盖运行、拖动和重算保护，删除后缓存不复活、仅剩隐藏方案、非选中项删除及最终清空；复用命名保存回读测试。地图手势在 MapLibre 桩中验证，本轮未重新执行浏览器视觉验收或 Docker 镜像构建，也未调用外部模型 |
| 同步与清理 | 同步前端、助手、代码地图和测试策略，合并重复的助手删除说明。本轮未重建或发布正式场景；原始道路 RAR、密钥、运行缓存和本机产物不纳入提交。核对过期文件，无原始输入、有效实验或权威文档删除 |
| 相关提交 | 本条所在合并提交；被复核本地提交 `e5009a9`、`94fa288`、`1cffbd8`、`e937473`、`8b57ce5`、`f31c8ed`；整合远程 `0224aff` |
| 状态 | 有效 |

## 存疑产物

以下文件本次未判定为过期，也未删除。

| 路径 | 原因 |
| --- | --- |
| `outputs/local_learning_rates_20261022/` | 用户要求移除后期微调，实验在 66/80 个局部分支、9 个基线后取消；`CANCELLED.json` 明确标记未完成，保留轨迹和 `cancelled_sources/` 诊断快照，不作为完整 10 seed 实验结论 |
| `outputs/local_learning_rates_smoke_20261022/` | 上述已取消研究的两代流程预检，仅供诊断，不代表 90 代正式比较结果 |
| `outputs/cmaes_region - 0.5` | 目录名含空格。对应 CMA-ES step 0.5 的结果仍有效，重命名前需同时改本文和 git 历史中的路径 |
| `outputs/cmaes_region.7z` | 与已展开的 CMA-ES 产物并存的压缩包，尚未确认是否为唯一副本 |
| `outputs/cmaes_region_0.05.7z` | 与 `outputs/cmaes_region_0.05` 并存的压缩包，尚未确认是否为唯一副本 |
| `outputs/road_alignment_diagnostic` | 已跟踪的道路对齐诊断图件，尚未补充为独立实验记录；确认用途和保留期限后再归档或清理 |

## 场景与历史实验文件隔离核验

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-26 |
| 实验名 | scene-link-isolation-20261026 |
| 目的 | 保全共享文件证据，解除场景发布对历史实验的写穿 |
| 入口 | `experiments/audit_scene_links.py` |
| 关键配置 | `--scenes scenes --outputs outputs --backup outputs/scene-link-audits/20261026-before-isolation --detach` |
| 输出目录 | `outputs/scene-link-audits/20261026-before-isolation` |
| 主要结果 | 发现并隔离 5 个共享文件，独立副本哈希和隔离前后一致；实验原始版本无法证实，未进行猜测恢复 |
| 相关提交 | 本条随硬链接隔离修复提交；原问题基线 `9d93677` |
| 状态 | 有效 |

## 单 Worker 崩溃恢复与真实数据库验收

| 字段 | 内容 |
| --- | --- |
| 记录日期 | 2026-10-26 |
| 实验名 | job-recovery-20261026 |
| 目的 | 验证 PostgreSQL 条件状态转换、Redis 重复消息和 Worker 崩溃后的恢复 |
| 入口 | `experiments/validate_job_recovery.py` |
| 关键配置 | 独立临时 PostgreSQL 16、Redis 7，localhost 随机端口；运行中杀死 Worker，随后重新启动 |
| 输出目录 | `outputs/validation/job-recovery-20261026` |
| 主要结果 | SQLite/PostgreSQL 共 4 项状态契约通过；第二 Worker 被拒绝；遗留运行任务标失败，排队任务恢复，重复投递不重复领取；测试容器已清理 |
| 相关提交 | 任务修复 `1dcb540`；本条随独立验收入口提交 |
| 状态 | 有效 |

## 2026-10-26 苍南独立 UTM 场景生成验证

- 实验名：cangnan-utm-v2 真实数据验证。
- 目的：验证标称 1800 m 范围不再使用 Web Mercator 投影米，且不覆盖旧场景及实验。
- 入口：`experiments.coordinate_scene.build_scene_from_coordinates`，指定独立场景根目录。
- 关键配置：WGS84 中心 `(27.501662, 120.194639)`，边长 1800 m，当地 EPSG:32651，原始下载半边长 1.042 km；其余数据参数读取默认配置。
- 输出：`outputs/validation/utm-migration-20261026/scenes/cangnan-utm-v2`，结果记录 `outputs/validation/utm-migration-20261026/cangnan-result.json`，原始 bundle 由结果记录定位。
- 结果：210 张卫星瓦片全部成功，四文件 QA 通过，四个数据 tool 完成，实际网格 1800×1800、1 m；生成约 91 秒。椭球距离、pyproj/proj4 控制点及显示像素对齐另由小型回归验证。当前生成过程的 transformers 加载报告提示 checkpoint 有缺失层，原始日志可追查；本次不将分割输出作为算法效果对照结论。
- Git：本次 UTM 与版本修复提交。
- 状态：有效。

## 2026-10-26 四万条三目标精确前沿性能验证

- 实验名：pareto-40000-20261026。
- 目的：替换最终前沿提取的二次比较，保持精确支配、重复点和输入顺序。
- 入口：`python -m experiments.benchmark_pareto outputs/validation/pareto-40000-20261026/summary.json`。
- 关键配置：40000 条三目标记录，seed=20261026，基线 `148b2e0`，单一固定 CPU，独立进程各三次；两边只加载 pareto 模块，避免无关包初始化影响 RSS。
- 输出：`outputs/validation/pareto-40000-20261026/summary.json`。
- 结果：53 个前沿点的有序 id 哈希逐次完全相同；中位数旧实现 100.098 s、新实现 0.330 s，约 302.9 倍。峰值 RSS 旧实现约 67.9 MiB、新实现约 71.6 MiB，额外数组换取 O(N log N) 精确扫描；通过至少四倍提速门槛。首轮未匹配包导入环境的结果另存为诊断文件，不采用其内存结论。
- Git：本次 Pareto 修复提交。
- 状态：有效。

## 2026-10-26 Nginx 联合导入边界验证

- 实验名：nginx-import-20261026。
- 目的：验证 Docker 代理的联合上传上限与 API 单文件限制一致。
- 入口：真实 `nginx:1.27-alpine` 容器转发到隔离 FastAPI，配置取 `frontend/nginx.conf`，仅替换本机测试端口和上游地址。
- 关键配置：两份各 83886080 字节的合法道路/永农 Shapefile ZIP（以 ZIP 前置填充达到边界大小）；独立 400 m UTM 场景及临时数据库。
- 输出：`outputs/validation/nginx-import-20261026/summary.json`。
- 结果：联合预览 200，耗时约 1.44 s，永农 3600 格、道路 1 段；171 MiB 被代理 413 拒绝；81 MiB 单文件被 API 413 拒绝，错误码 `data_import_too_large`；`nginx -t` 通过。容器已停止，正式场景未修改。镜像实际 id 记录在 summary。
- Git：本次代理配置修复提交。
- 状态：有效。

## 2026-10-26 PostgreSQL/Redis 任务状态最终故障验证

- 实验名：job-recovery-final-20261026。
- 目的：复核进度和成功终态改为条件更新后的实际数据库、队列和 Worker 行为。
- 入口：`python -m experiments.validate_job_recovery --output-dir outputs/validation/job-recovery-final-20261026`。
- 配置：本机临时 PostgreSQL 16、Redis 7 容器，随机端口、临时数据库及独立 Worker 输出目录。
- 输出：`outputs/validation/job-recovery-final-20261026/summary.json`，SQL 测试及 Worker 日志同目录。
- 结果：8 个 SQLite/PostgreSQL 状态契约用例通过；迟到进度不改取消或终态，自定义成功阶段与结果原子提交。第二 Worker 被拒绝；杀死运行中 Worker 后原任务明确失败，排队任务恢复，重复投递安全。验证结束已清理容器与进程。
- Git：本次任务终态修复提交。
- 状态：有效。

## 2026-10-26 默认原始实验入口 UTM/CUDA 验证

- 实验名：default-utm-modeling-20261026。
- 目的：验证默认命令行数据与建模入口不再按 Web Mercator 投影米计算。
- 入口：`python -m experiments.validate_modeling --output-dir outputs/validation/default-utm-modeling-20261026`。
- 关键配置：默认 JSON 的显式 UTM `data.target_grid`；新的苍南原始输入快照在 `data/sites/cangnan-utm-v2/`，文件来源和 SHA256 在该目录 `SOURCES.json`。区域 DEM 原始间距约 30 m，和旧约 10 m 裁剪输入属于不同场景版本，不作跨版本效果对照。
- 输出：`outputs/validation/default-utm-modeling-20261026`。
- 结果：1800×1800、1 m UTM 产物生成，目标、硬约束和 raw pose 梯度验证通过；实际使用 RTX 4090，CUDA 12.6。旧输入及旧场景数组未覆盖。
- Git：本次默认米制网格修复提交。
- 状态：有效。

## 2026-10-26 三处独立 UTM 场景发布验收

- 实验名：utm-publication-20261026。
- 目的：验证独立米制替代品发布、旧场景封存及收藏数据保护，不覆盖历史矩阵。
- 入口：`experiments.migrate_metric_scene.publish_metric_scene`；发布后逐文件 SHA256 核对。
- 关键配置：苍南、永嘉及中心 `(27.543840, 120.449097)` 的 1800 m 场景；当地 WGS84 UTM，保留相同标称边长。先在独立验证根生成，再复制到正式 `scenes/`；发布前保存旧记录与 SQLite 在线备份。
- 输出：`outputs/validation/utm-migration-20261026/scenes/` 和 `publication/`；验收汇总 `publication/verified.json`。正式替代品为相应旧 id 加 `-utm-v2`。
- 结果：三处正式新场景的核心数组与已验收副本一致；旧场景各八个核心产物哈希不变，只更新封存记录。三处原收藏记录均为 0；收藏复制另用包含宽小于高的确定性记录验证，保留经纬度、标称米制尺寸和长边真北角，重试不重复。默认场景切到苍南 UTM。
- 边界：楠溪江缺原始永农 `1.zip`，未生成或发布扩大范围的替代品，不计入本条已完成迁移；旧场景另行封存并保留迁移待办。新的默认 DEM 来源和采样质量见上一条，不作新旧算法效果比较。
- Git：本次迁移发布与默认输入修复提交。
- 状态：有效。

## 2026-10-26 审查修复浏览器与最终回归验收

- 实验名：review-fixes-browser-20261026。
- 目的：验证实际交互、批量评价、保存身份、设置鉴权及首次 UTM 准备，并汇总 28 项代码修复回归。
- 入口：前端断言与生产构建；完整 pytest；隔离 FastAPI/Vite 配合 Playwright Chromium 141，临时脚本位于 `/tmp/site-modeling-browser/`。
- 关键配置：Node 22.23.4，Playwright 1.56.1，独立数据库/输出/400 m UTM 夹具与虚构模型密钥；固定本地底图瓦片，实际 React、MapLibre WebGL 和 API。首次准备另外读取仓库新默认原始四文件，在临时场景根生成 1800 m UTM。
- 输出：`outputs/validation/browser-20261026/`；完整回归 `outputs/validation/review-fixes-20261026/regression.xml`。
- 交互结果：连续输入角度 123 成功；退距输入不逐键重测，Enter 提交、方向键立即步进；拖动中 Esc 释放调整状态；PNG 实际方案边框中心随当前拖动改变，同一请求键不重复取站址报告。手动方案失败可重试；501 条方案两批失败后请求批大小为 `[200,200,101,200,101]`，成功的前 200 条未重交；另存使用当前场景 id。设置要求管理员密码，保存成功清空密码。
- 场景结果：新页面选中尚未准备的苍南 UTM，实际准备任务成功，frame 为 EPSG:32651、1800×1800。切到封存夹具可查看，准备、优化、添加和编辑被阻止。各浏览器验收页面脚本异常为 0。首轮只读测试错误选了无已选方案的「调整方案」，随后改为可直接触发的画圈入口并重验通过，不将首轮超时当代码故障。
- 回归结果：完整 Python 671 passed、4 skipped，包含宿主 CUDA；四项 PostgreSQL 跳过项由此前真实临时服务最终验收覆盖。迁移故障注入、来源版本变化拒绝及收藏复制共 5 项通过。前端全部断言、OpenAPI 生成和 TypeScript/生产构建通过；大 bundle 提示仍存在。本轮只运行本地助手契约，未调用外部模型。
- Git：本次迁移发布与默认输入修复提交；逐项结论见 `markdown/CODE_REVIEW_FIX_REPORT.md`。
- 状态：有效。

## 2026-10-26 楠溪江完整 UTM 数据加载与发布验收

- 实验名：nanxi-utm-20261026。
- 目的：使用补齐的原始永农完成最后一处米制迁移，验证新范围的数据覆盖、原始向量导入和实际地图显示。
- 入口：`experiments.migrate_metric_scene.migrate_metric_scene`、`publish_metric_scene`；独立投影与全量栅格化、道路最近段抽查；真实 API 与 Chromium 页面验收。
- 关键配置：原始 `data/1.zip`，SHA256 `0131635d6440a92371252bf482985bb805908d9c3dc801e1ef21fef58c82eb58`，EPSG:4490、4360 个图斑；原始高德道路 RAR。旧网格中心经投影转换并保留六位小数后为 `(28.246101, 120.810599)`，目标 EPSG:32651、9000×9000、1 m，影像下载半边长 5.223 km、z18。
- 输出：`outputs/validation/nanxi-utm-20261026/`，包括 `preflight.json`、`legacy-farmland-check/verified.json`、`generation.log`、`generation.json`、`verified-staged.json`、`publication/`、`browser.json`、`browser-nanxi.png` 和回归 XML；正式替代品为 `scenes/lat28.246100_lon120.810600_r4.500km_z18_g9000x9000_rb500m-utm-v2`。
- 数据结果：4761 张影像瓦片全部成功，完整生成及原始道路/永农导入约 959 s。上传 ZIP 在旧网格重建后与原永农掩膜逐像素一致。新场景相交图斑 1529 个，永农 10415081 格；使用原始全部图斑独立转换并按 `all_touched=True` 栅格化，差异为 0。首轮校验错误使用中心点口径，边缘接触格出现差异；核对既有实现后改正校验口径，没有为迎合校验改动导入数据。
- 道路与空间结果：3839 条线段，普通路/匝道/高速地表/隧道分别为 3635/92/56/56；全量 Voronoi 标签均指向普通路，固定 seed 抽查 256 格的最近距离最大误差约 0.000113 m。四边椭球长度约 8998.3–8998.7 m，符合当地 UTM 尺度；建模栅格本身为精确 9000 m 投影边长。
- 发布与保全：正式产物与已验收副本逐文件哈希一致；旧核心数组和永农掩膜不变，原始 ZIP 随正式层保存。SQLite 在线备份后复制 2 个收藏点，原记录保留；成功后清除迁移待办标记。
- 页面与补修：真实页面可选择“楠溪江（UTM）”，读到 4360/1529 图斑说明。首次并发加载复现土地修订列表将占锁误报为 422，补充只读等待；大于浏览器纹理上限的原图曾导致 `texImage2D` 越界，通过统一 PNG 响应尺寸限制修复，完整图片和 1 m 数组不变。最终 Chromium 无脚本或纹理错误，截图中实际检出 89748 个永农显示像素；底图仍使用固定本地瓦片，数据读取、图层和 WebGL 实际运行。
- 回归：迁移与列表修复后、归档前完整 672 passed、4 skipped；归档与最终显示修复后完整 674 passed、6 skipped。四项 PostgreSQL 需要独立服务，已有此前最终验收覆盖；另外两项历史苍南夹具因用户要求归档而跳过。并发读取新增用例先失败后通过，地图 PNG 缩放与小图字节保留测试通过。
- 边界：沿用当前分割 checkpoint，缺失 LayerNorm 的加载提示仍记录在 generation.log；本次验证加载、空间一致和数据保全，不评估分割精度或新旧算法效果。原始上传 ZIP/RAR 及生成矩阵保留本机，不纳入源代码提交。
- Git：场景列表与迁移标记修复 `342b55b`；本条随后续验收记录提交。
- 状态：有效。

## 2026-10-26 移除重复旧场景并保留归档

- 实验名：legacy-scene-archive-20261026。
- 目的：执行用户清理旧场景的要求，使软件只提供当前有效的米制场景，不重复展示历史名字。
- 入口：持场景锁的目录归档和逐文件 SHA256 核对；场景列表 API、浏览器地区切换。
- 对象与原因：旧 `cangnan`、`yongjia`、`lat27.543840_lon120.449097_r0.900km_z18_g1800x1800_rb500m`、`lat28.246100_lon120.810600_r4.500km_z18_g9000x9000_rb500m` 均已有经过验证的 UTM 替代品。移动前先写明清理原因、原路径、替代品和哈希；只移出活动目录，保留历史数据快照。
- 输出：`outputs/scene-archives/legacy-3857-20261026/` 保存四个旧目录及 `manifest.json`；活动列表和运行检查见 `outputs/validation/nanxi-utm-20261026/active-scenes.json`、`runtime.json`。
- 结果：四个目录完整归档，移动后文件哈希不变；当前软件只列出苍南 UTM、另一处 1800 m UTM、楠溪江 UTM 和永嘉 UTM，均就绪、名称唯一。旧预置来源登记不再生成空占位入口。确认当前 API 无活动任务后保留环境重启，页面入口不变，默认仍为苍南 UTM。
- 保留范围：原始 `data/`、道路 RAR、收藏数据库及原记录、有效实验输出、迁移验证副本和历史恢复证据均保留。没有删除原始输入或有效实验；归档自身作为历史证据保留。
- Git：本条作为独立清理记录提交，不推送远程。
- 状态：有效。

## 2026-10-26 地图网格对齐与北向切换验收

- 实验名：grid-aligned-camera-20261026。
- 目的：使选址范围默认水平显示，验证相机旋转下的交互、真北角度及 PNG 导出恢复。
- 入口：前端断言、生产构建、`tests/test_agent.py`；Playwright Chromium 实际访问本机页面，临时验收脚本位于 `/tmp/site-modeling-browser/grid-camera.mjs`。
- 关键配置：Node 22.23.4、Playwright 1.56.1；四个正式 UTM 场景、真实 API 和 MapLibre WebGL；底图使用固定本地瓦片。只创建页面临时方案，不修改收藏或场景数据，不运行优化实验。
- 输出：`outputs/validation/grid-aligned-camera-20261026/`，含独立 pyproj 控制值、`browser.json`、`verified.json`、29 个数组的前后哈希、页面截图、五张导出 PNG 和助手测试 XML。
- 显示结果：四个场景初始化及定位的相机角度与 pyproj 一致，上边缘角度绝对值最大约 `7.91e-11°`；点击指南针归零，再定位恢复网格对齐，各次场景边界经纬度完全相同。苍南默认相机约 `-1.303592°`。导出图片像素另行验证完整范围上边缘水平、真北视角保留原倾角，北向箭头在自定义旋转图片中随之旋转。
- 交互与保全：独立投影控制点点选、拖动误差小于 3 m，符合当前缩放下的鼠标像素取整；输入 123° 后独立真北校验为 123°，平移后约 123.000743°，差异来自新位置的网格收敛角。完整范围导出切到网格对齐并恢复原相机，当前视角导出保留原朝向；另以 37° 旋转、25° 俯仰验证恢复。浏览器脚本异常为 0；29 个正式数组 SHA256 全部不变，请求审计无收藏或场景编辑写入。
- 回归：新增方向测试先失败后通过；前端全部断言及生产构建通过，助手契约 30 passed。截图采样时机及预览接口白名单在验收脚本中修正后完成最终检查；没有因此改动产品逻辑。构建仍有原有大 bundle 提示。本轮没有调用外部模型。
- Git：`4621b5e`。
- 后续：用户要求恢复固定真北朝上，本条显示策略已由下一条验收替代；原验收证据保留。
- 状态：作废。

## 2026-10-26 恢复固定北向并禁止误触旋转

- 实验名：north-up-camera-20261026。
- 目的：响应用户关于地图自行旋转的反馈，撤销自动网格对齐，固定北向并保留平移和缩放。
- 入口：Playwright Chromium，临时脚本 `/tmp/site-modeling-browser/rotation-check.mjs`；前端断言、生产构建及 `tests/test_agent.py`。
- 关键配置：Node 22.23.4、Playwright 1.56.1；真实 React 和 MapLibre WebGL，使用从当前 API 读取的四场景参考信息和插件响应作为隔离夹具，底图为固定本地瓦片。图层及报告接口不纳入坐标相机检查，不写正式场景或收藏。
- 输出：`outputs/validation/north-up-camera-20261026/`，包括 `baseline.json`、`fixed.json`、`verified.json`、页面及 PNG 截图、`frontend-tests.json` 和助手测试 XML。
- 复现：楠溪江定位后为约 `-1.043738°`；右键拖动、Shift+右方向键、双指扭转均可再次改变朝向。固定北向断言在修复前失败。
- 结果：四场景初始化及定位均为 bearing=0、pitch=0；右键、键盘旋转及双指扭转不能改变朝向，普通拖动和双指捏合仍改变中心与缩放。PNG 导出保持北向，导出后的交互恢复也没有重新开启旋转。前后场景边界经纬度一致，浏览器脚本异常为 0。
- 回归与边界：TypeScript 和生产构建通过；不依赖历史实验文件的 28 组前端断言通过，助手契约 30 passed。完整前端入口因本机 `outputs/cmaes_region_0.1/` 夹具缺失而中止，另两组读取该夹具的测试未运行，没有补造历史实验或更改这些测试。构建保留既有大 bundle 提示；没有运行算法实验或调用外部模型。
- Git：本条随恢复北向的修复一并提交。
- 状态：有效。

## 2026-10-26 选线地图与任务链路验收

- 实验名：routing-browser-20261026。
- 目的：验证 P7 地图交互与 P6 Jobs/Worker/历史产物连接，不使用正式场景作为写入对象。
- 入口：隔离 Uvicorn 8127、Vite 5197、Playwright Chromium；临时脚本 `/tmp/site-modeling-browser/routing-check.mjs`。
- 关键配置：400×400、1 m、EPSG:32651 合成坡面，独立建筑和道路；起点地图点选、终点由独立 pyproj 控制坐标输入；显式最大档距、塔基半径、转角与两类人工区域，固定 seed、评价预算。具体任务配置保存在 `browser.json` 的 submitted 中，不作为工程默认值。
- 输出：`outputs/validation/routing-browser-20261026/` 的 `browser.json`、`routing.png`、`frontend-regression.json`；任务与输入快照在 `/tmp/routing-acceptance-20261026/outputs/`。
- 结果：实际 Worker 成功执行，图上显示线路与塔基圆；两类多边形分别进入对应任务字段；实验目录可回读，刷新可恢复任务及结果；第二次运行取消后确认 cancelled，旧结果继续保留；相机 bearing/pitch 均为 0，右键拖动不旋转；浏览器脚本异常为 0。
- 验证边界：卫星瓦片固定为本地图片，API、投影、MapLibre 和任务执行真实运行；首轮验收脚本未等场景就绪、热更新重置及取消文案匹配已纠正后重跑，没有据此改变模型定义。完整旧前端入口仍受已删除的历史夹具影响，另行执行不依赖该夹具的 28 组回归。
- Git：本条随 P7 选线地图实现提交。
- 状态：有效。

## 2026-10-26 苍南选线开发预验

- 实验名：routing-cangnan-preflight-20261026。
- 目的：在 P8 开发阶段验证标准真实数据、完整硬检查与固定 seed 的线路产物复现；正式验收另用提交后的版本复验。
- 入口：`python -m experiments.validate_routing`，显式任务 `/tmp/routing-real-configs-20261026/cangnan.json`，启用 repeat。
- 关键配置：苍南 UTM 1800×1800；独立 pyproj 将局部验收起终点 `(200,900)`、`(1600,900)` 转为 WGS84；显式档距 500 m、塔基半径 3 m、转角 90°，种群 24、预算 384、固定 seed。上述值仅供验收，不作为工程默认值。
- 输出：`outputs/validation/routing-real-20261026/cangnan/`，含两份完整运行及 `verified.json`。
- 结果：102 条可行线路逐条复核通过，前沿 9 条；同 seed 重跑 `routes.json` 逐字节一致；输入哈希不变，快照独立。首轮快照约 0.042 s、上下文约 0.296 s、搜索与报告约 0.766 s；进程峰值约 765.8 MiB，含重复验收及框架。
- 边界：使用开发中的 P8 计时/来源记录代码；随后发现永农导入登记需按其独立 JSON 检查并已补充严格缺失校验，未改变四目标公式。不能将预验代码状态当作正式发布基线；正式版本将另行复验。
- Git：基础版本 `b694b89`，开发代码的逐文件哈希保存在摘要；P8 代码随本记录提交。
- 状态：有效。

## 2026-10-26 真实选线首轮验收与初始化诊断

- 实验名：routing-real-first-20261026。
- 目的：在已提交版本上正式复验苍南并扩展到楠溪江完整 1 m 数据，检查初始化与最大档距的一致性。
- 入口：`experiments.validate_routing`，显式任务配置 `/tmp/routing-real-configs-20261026/`。
- 关键配置：固定 seed、种群 24、预算 384；档距 500 m、半径 3 m、最大转角 90°。苍南端点同前条，楠溪江端点为独立 pyproj 转换的局部 `(500,4500)`、`(8500,4500)`；无新增工程默认值。
- 输出：`outputs/validation/routing-real-20261026/cangnan-final/` 与 `nanxi/`。
- 结果：苍南再次复核 102 条可行线路、前沿 9 条，重复产物逐字节相同，峰值约 765.9 MiB。楠溪江 9000×9000、384 次评价完成但无可行线路，验收明确失败并保留诊断；源数据哈希和快照独立检查通过。楠溪江上下文约 15.37 s、搜索与报告约 2.03 s；较好候选塔基/转角都通过，但仍有 39.87 m 总超档距。
- 诊断：塔位移出禁区后可能拉长相邻档，初始化未再次分档；另有 UTM 往返舍入在整除时使下界多一档。已补充回归并修复；本条记录保留首轮结果，不将「预算内未找到」当成数学不可行。
- Git：首轮执行 `3160b43`；修复随本记录提交。
- 状态：有效。

## 2026-10-26 选线模块最终验收

- 实验名：routing-final-20261026。
- 目的：关闭 P8，验证档距初始化修复后的真实小场景、大场景、固定 seed 复现、既有功能回归与软件入口。
- 入口：`python -m experiments.validate_routing`，显式任务 `/tmp/routing-real-configs-20261026/cangnan.json`（repeat）与 `nanxi.json`；全量 pytest；前端选线断言、既有无历史夹具回归、生产构建；隔离真实 API/Worker 的 Playwright 验收和正式页面只读检查。
- 关键配置：两场景均使用 seed 123、种群 24、评价预算 384；档距 500 m、塔基半径 3 m、单处转角 90°。道路退距按已保存配置；端点与前条一致。均为 CPU 执行，保持 1 m 最终评价，没有增加工程默认值或以粗网格代替硬检查。
- 输出：`outputs/validation/routing-real-20261026/` 下 `cangnan-fixed/`、`nanxi-fixed/`、`regression-final.xml`、`frontend-regression.json`、`runtime-final.json`、`runtime-browser.json`、`runtime-page.png` 和 `expired-job.json`；最终隔离浏览器完整任务链路证据为 `outputs/validation/routing-browser-20261026/browser.json` 与截图。
- 苍南：1800×1800，119 条可行线路逐条复核、硬违规 0，返回 24 条非支配方案；同 seed 的 `routes.json` 逐字节一致。首轮快照 0.042 s、上下文 0.344 s、搜索与报告 0.861 s，约 446 次搜索评价/s，任务约 1.248 s；验收进程峰值约 765.8 MiB。
- 楠溪江：9000×9000，120 条可行线路逐条复核、硬违规 0，返回 13 条非支配方案。直线松弛下界 15 塔、初始上界 25 塔，搜索扩展至 29 塔；预算耗尽正常停止。快照 1.026 s、上下文 14.170 s、搜索与报告 3.147 s，约 122 次搜索评价/s，任务约 18.345 s；验收进程峰值约 3636.4 MiB。本轮楠溪江执行一次，重复性由苍南 repeat 和确定性单元测试覆盖。
- 数据保全：两场景的源文件前后 SHA256 不变，历史输入与可变场景不是同一 inode。完整参数、输入与源码哈希、Git 来源、阶段计时和额外最终复核次数均保存在产物；不提交原始数据或生成矩阵。
- 最终回归：720 passed、6 skipped；四项 PostgreSQL 外部服务测试及两项已归档苍南夹具测试按原条件跳过。新增选线前端断言、28 组不依赖历史 fixture 的既有前端回归、TypeScript 与生产构建通过；另两组旧前端测试因已删除实验文件仍无法运行，未修改其答案或恢复历史数据。
- 软件链路：最终代码在隔离服务重新验证点选/经纬度输入、两类人工区域、实际 Worker 运行、线路与圆形塔基、两条线路的四目标比较与叠加、逐档详情、历史回读、刷新恢复、取消保留旧结果、固定北向，浏览器脚本异常 0。正式 API 当前生命周期 12 次成功提交均确认已完成后，保留原命令和环境平滑重启；`routing.nsga2` 注册、前端代理、楠溪江选线入口与工程必填输入只读检查通过，地址仍为 `http://10.28.0.176:5176/`。
- 恢复补修：额外构造一个已失效的保存任务 id，先返回临时 503、再由真实 API 返回 404。修复前 5 秒内仍请求 5 次且输入锁住；修复后共请求 2 次，503 重试、404 停止，清除该场景失效 id 并恢复历史读取，旧线路不被清空。验收脚本为 `/tmp/site-modeling-browser/routing-expired.mjs`；补修后再次通过生产构建、新选线断言、28 组前端回归与完整浏览器任务链路。
- 边界：非支配集合是本次预算内的搜索结果，不宣称全局完整前沿；仍未校核净空、弧垂或地形穿透。较大场景的主要时间和内存来自全幅上下文准备，没有声称 GPU 加速。浏览器底图瓦片固定为本地图片，真实投影、WebGL、API 和 Worker 均实际运行；助手模式测试使用脚本模型，没有调用外部 LLM。
- Git：真实数据执行基线 `7bc97d5`；失效任务恢复修复及本条随最终验收提交，不推送远程。
- 状态：有效。

## 2026-10-26 选线加速基线剖析

- 实验名：routing-acceleration-baseline-20261026。
- 目的：P0 固定加速前的正确性与耗时来源，不改变搜索规则。
- 入口：`python -m cProfile -o outputs/validation/routing-acceleration-20261026/baseline.prof -m experiments.validate_routing`，显式楠溪江任务。
- 关键配置：原验收端点与工程参数，seed 123、种群 24、预算 384，NumPy/CPU；全部输入只读，输出目录独立。
- 输出：`outputs/validation/routing-acceleration-20261026/baseline.prof`、`baseline-nanxi/verified.json`。
- 结果：120 条可行线路全部复核，输入哈希不变且快照独立。剖析包含验收时第二次建场，不能当作产品单次耗时：约 30.55 s 中两次上下文构建约 20.20 s；搜索约 4.78 s，评价累计约 3.97 s，塔基检查累计约 3.28 s，修复约 1.30 s，穿格约 1.23 s。主机峰值约 3649.8 MiB；后续无剖析重复计时另行报告。
- Git：执行基线 `89dca33`，本条随加速契约提交。
- 状态：有效。

## 2026-10-26 张量演化与共享排序验收

- 实验名：routing-tensor-evolution-p1-20261026。
- 目的：在不改精确评价的前提下验证张量排序、变长操作、固定端点与预算；测量排序组件收益。
- 入口：`tests/test_routing_tensor.py`、既有 `test_tensor_nsga2.py` 与配置/插件/助手回归；独立冻结数组计时。
- 关键配置：CPU 和 cuda:0；1024 个四目标冻结随机候选、全部可行，seed 11。预热后 CPU/CUDA 各三次，逐项核对 rank。
- 输出：`outputs/validation/routing-acceleration-20261026/p1-ranking.json`。
- 结果：综合 59 passed；新增前端断言和生产构建通过。排序 CPU 约 4.67 s、CUDA 约 0.005–0.006 s，中位加速约 886 倍，仅为该排序组件，不代表端到端收益。算子首轮暴露 bool 索引算术及混合 dtype 错误，修复后所有 CPU/CUDA 用例通过。
- 边界：张量平局按稳定候选序号，原 NumPy 的历史展开顺序保留；不同后端随机轨迹不要求逐位相同。评价与局部修复仍由参考 CPU 执行，后续单独加速。
- Git：基础 `28807e2`；本条随 P1 实现提交。
- 状态：有效。

## 2026-10-26 精确 CPU 几何编译验收

- 实验名：routing-compiled-evaluation-p2a-20261026。
- 目的：独立加速塔基、DEM 与穿格，保持精确参考语义。
- 入口：`tests/test_routing_compiled.py`，与原评价、张量搜索和 NumPy 搜索回归；固定真实候选三次计时。
- 关键配置：楠溪江基线中的前 128 条候选，完整 1 m 输入；Numba 不启用 fastmath，预热后对比 reference 与 compiled_cpu。
- 输出：`outputs/validation/routing-acceleration-20261026/p2-compiled.json`。
- 结果：逐项目标与可行性一致；三次原评价约 0.60–0.61 s、编译评价约 0.064–0.066 s，中位约 9.31 倍。随机地形/类别/多边形、相切、零档、共享边及 100 条随机穿格对照通过；搜索轨迹在固定 NumPy 输入案例一致。
- 边界：仅报告精确评价组件计时，完整任务和 GPU 批量后续单独测量。参考实现与最终 CPU 完整复核保留。
- Git：基础 `d77fd0e`；本条随 P2a 实现提交。
- 状态：有效。

## 2026-10-27 精确张量评价与显存验收

- 实验名：routing-tensor-evaluation-p2b-20261027。
- 目的：验证真正的批量 DEM/塔基/穿格/四目标计算，测量 GPU 相对编译 CPU 的真实收益。
- 入口：`tests/test_routing_tensor_evaluator.py`、张量演化/编译几何/历史输出/原站址算子回归；同一真实候选数组计时。
- 关键配置：楠溪江完整 1 m 输入的前 256 条冻结候选，float64，cuda:0；配置显存预算内分块，预热后重复三次，逐项目标和可行性对照。
- 输出：`outputs/validation/routing-acceleration-20261026/p2-tensor.json`。
- 结果：综合 47 passed。GPU 评价中位约 0.169 s，编译 CPU 中位约 0.123 s；该批量下 GPU 尚无收益，不设为推荐默认。GPU 峰值 allocated 约 528.3 MiB、reserved 552 MiB。CPU/CUDA 不同批次、NaN 补齐、相切/阈值回算、人工区和分配前显存拒绝均通过。
- 边界：该结果不抵消张量排序收益；后续端到端比较包含张量演化配编译 CPU 和全张量两条路径，按实测推荐。当前单设备评价，双设备同步分担在 P6 单独验收。
- Git：基础 `7c9635c`；本条随 P2b 实现提交。
- 状态：有效。

## 2026-10-27 大种群显存与精确归档验收

- 实验名：routing-memory-archive-p3-20261027。
- 目的：防止增大预算后显存、报告对象和四目标归档成为新的瓶颈。
- 入口：`test_routing_tensor.py` 的大种群用例、精确前沿/流式输出/已有输出回归；冻结四目标数组独立计时。
- 关键配置：合成网格上 1024 种群、3072 次评价，cuda:0 张量演化与评价，批次 64、显式预算 64 MiB；归档数组 40000 条四目标，seed 17，预热后三次。
- 输出：`outputs/validation/routing-acceleration-20261026/p3-archive.json`。
- 结果：大种群预算与最终可行前沿检查通过，工作分配未超过显式预算；搜索记录不保留逐档/高程对象，流式输出仍重建完整字段。40000 条候选得到 139 条前沿，三次约 0.0146–0.0158 s；小数组与独立两两枚举一致，包含重复与全非支配案例。
- 边界：不截断历史候选；原 CPU 可行性复核及最终按复核目标重算前沿保留。计时只代表归档组件，端到端仍需后续实验。
- Git：基础 `8cbf5e6`；本条随 P3 实现提交。
- 状态：有效。

## 2026-10-27 只读基础上下文复用验收

- 实验名：routing-context-cache-p4-20261027。
- 目的：减少同一场景反复优化时全图道路控制范围重建，同时保持任务约束独立。
- 入口：`test_routing_context_cache.py` 与输入/输出回归；楠溪江完整快照连续三次构建。
- 关键配置：既有真实验收快照与道路退距；缓存只保留一项，容量取默认 JSON，端点与人工区域每次装配。
- 输出：`outputs/validation/routing-acceleration-20261026/p4-context-cache.json`。
- 结果：冷构建约 15.36 s，后两次约 0.00386/0.00084 s；基础栅格共 891000000 字节。小网格验证命中只复用栅格、不复用端点/人工区域；退距和输入哈希变化失效，容量不足或零容量不保留，输入快照独立性继续通过。
- 边界：该收益只适用于同一进程的重复任务，不作为首次任务加速；不保留 CUDA 场景缓存，不改变正式快照与数据发布口径。
- Git：基础 `4a2f3f7`；本条随 P4 实现提交。
- 状态：有效。

## 2026-10-27 双卡同步评价验收

- 实验名：routing-dual-evaluation-p6-20261027。
- 目的：在单卡已验证后验证同步双卡分担评价，不改变全局选择。
- 入口：`tests/test_routing_multi_device.py` 与单卡/指标回归；同一 1024 条真实候选三次计时。
- 关键配置：楠溪江原 256 候选重复四次作为冻结批量；float64、批次 256，对比 compiled_cpu、cuda:0、cuda:0+cuda:1，预热后计时。
- 输出：`outputs/validation/routing-acceleration-20261026/p6-dual.json`。
- 结果：综合 21 passed，补充释放缓存后的双卡两项再次通过。编译 CPU 中位约 0.450 s、单卡约 0.639 s、双卡约 0.451 s；双卡相对单卡约 1.42 倍，但尚未优于编译 CPU，不设为默认。每卡峰值 allocated 约 528.3 MiB、reserved 约 552 MiB。
- 正确性：逐候选目标/违规及顺序一致，双卡搜索同 seed 重复与预算通过，取消后无线程遗留；评价会话结束释放各卡场景与空闲缓存。大预算质量矩阵仍单独执行，不能将此组件测试当作已完成质量实验。
- Git：基础 `f8a79b8`；本条随 P6 实现提交。
- 状态：有效。

## 2026-10-27 真实场景加速矩阵与完整发布验收

- 实验名：routing-performance-matrix-20261027。
- 目的：验证张量演化的端到端收益，区分精确评价、上下文与输出成本，按实测选择推荐路径。
- 入口：固定提交的独立代码副本运行 `experiments.benchmark_routing`；manifest 为 `/tmp/routing-acceleration-configs-20261027/performance.json`，内容随输出保存。
- 关键配置：苍南 1800×1800、楠溪江 9000×9000；沿用显式端点和工程约束，seed 123、种群 256、预算 4096。五种组合各预热一次、测量三次；原 reference 与 tensor+compiled_cpu 另外各重放三次完整冷任务，明确关闭上下文缓存并计入新快照、CPU 报告与流式写出。
- 输出：`outputs/validation/routing-acceleration-20261026/p5-performance/`，含 30 次测量、12 次独立完整发布、紧凑候选、冻结参考及 `report.json`。代码身份在 `/tmp/routing-acceleration-configs-20261027/final-source.json` 中记录。
- 苍南：搜索/归档/CPU 复核的中位耗时，numpy-reference 18.973 s、numpy-compiled 13.720 s、tensor-compiled 1.944 s、tensor-single 1.811 s、tensor-dual 1.808 s。完整冷任务从 23.506 s 降至 6.541 s，约 3.59 倍。
- 楠溪江：同口径中位耗时分别为 39.204/17.163/6.770/7.803/7.202 s。完整冷任务从 68.062 s 降至 36.158 s，约 1.88 倍，降幅约 46.9%，通过 20% 门槛。
- 显存：混合路径 PyTorch allocated 峰值苍南约 2.51 MiB、楠溪江约 3.00 MiB，整幅栅格保留 CPU；全张量路径楠溪江单卡约 528.6 MiB，双卡各约 526 MiB。allocated 不包含 CUDA 驱动上下文；reserved 峰值也在逐次报告中保存。
- 正确性：全部固定后端重复坐标/目标哈希一致；所有可行候选 CPU 复核通过，原场景输入 SHA256 不变，快照独立。不同后端的浮点运算及稳定平局顺序可能改变搜索轨迹，不将同 seed 的跨后端轨迹当作一致性依据。
- 软件回归：全量 758 passed、6 skipped；新增选线前端与 28 组无历史夹具前端回归、生产构建通过。隔离浏览器实际选择 tensor/compiled_cpu/cuda:0，真实 Worker 执行、四目标叠加、历史/刷新/取消和北向地图六项通过，无脚本异常；证据为同目录上级 `browser/`。两组旧前端夹具仍缺失，没有伪造。
- 边界：正式测量在测试结束后独立顺序执行，代码副本固定，不受工作区后续诊断字段和分批取消补修影响。尚不能据此宣称优化质量已收敛，五 seed 预算阶梯另行记录。
- Git：性能执行 `dc9242b`；本条随指标诊断与输出取消回归提交。
- 状态：有效。

## 2026-10-27 原 CPU 塔基复核的精确缓存

- 实验名：routing-reference-tower-cache-20261027。
- 目的：降低大预算最终复核中重复塔位的开销，保留原计算函数与全部硬检查。
- 入口：`tests/test_routing_tower_cache.py`、原评价与输出回归；冻结楠溪江 256 条候选三次交替对照；独立第二卡重放已完成真实任务。
- 关键配置：缓存按完整 float64 坐标键、评价器私有 LRU，按上下文预算扣除基础栅格后的剩余量限额；不量化坐标，不跨问题复用。真实重放为苍南 8192 次与楠溪江 32768 次评价，其他配置与质量矩阵对应记录一致。
- 输出：`outputs/validation/routing-acceleration-20261026/reference-tower-cache.json` 与 `tower-cache-replay.json`。
- 结果：相关 17 passed；固定候选原评价中位约 1.156 s、缓存约 0.614 s，约 1.88 倍。实际只使用 297 个缓存塔位，容量为 22671。两个真实重放的所有候选坐标和目标内容哈希与 `1bbb398` 完全相同；楠溪江重放约 36.8 s，但并行独立质量任务期间的重放耗时不作为速度门槛证据。
- 边界：正在运行的五 seed 质量矩阵继续使用不含该缓存的固定副本，因此不混合不同实现的组内计时。缓存失效/淘汰、完整坡度报告与固定 seed 搜索均逐位对照；零预算禁用。
- Git：固定对照 `1bbb398`；本条随原 CPU 缓存及分批最终复核取消检查提交。
- 状态：有效。

## 2026-10-27 原 CPU 精确穿格结果复用

- 实验名：routing-reference-geometry-cache-20261027。
- 目的：在塔基缓存后复用继承线路中反复出现的同一线段，不改变穿格算法。
- 入口：`tests/test_routing_tower_cache.py` 的方向/淘汰/逐位对照及原评价/输出回归；同一楠溪江 256 候选三次交替计时；第二卡完整任务等价重放。
- 关键配置：同一只读问题、完整有序端点坐标为键；塔基与跨越结果平分既有工作缓存额度，总上限不增加。只缓存原函数水平长度，三维换算和最终复核照常执行。
- 输出：`outputs/validation/routing-acceleration-20261026/reference-geometry-cache.json` 与 `geometry-cache-replay.json`。
- 结果：固定候选原 CPU 评价中位约 1.171 s、缓存约 0.222 s，约 5.27 倍；实际 297 个塔基、563 个线段条目。楠溪江 32768 次评价所有坐标/目标哈希再次与 `1bbb398` 完全相同。方向独立、淘汰和关闭缓存通过；无人工禁跨区域时还消除了无用 LineString 构造，保留非空区域回归。
- 边界：组件计时针对缓存本身；并行独立任务下完整重放约 25.1 s 只用于等价证据，不作为性能门槛。正式五 seed 矩阵仍使用原固定版本，不混用后续缓存的耗时。
- Git：基础 `de41a70`；本条随精确线段缓存提交。
- 状态：有效。

## 2026-10-27 五 seed 质量阶梯与最终交付验收

- 实验名：routing-quality-matrix-final-20261027。
- 目的：完成 P5，验证加速能支持更大的实际研究预算，并分开评估种群规模、评价次数和质量；关闭本轮升级。
- 入口：`experiments.benchmark_routing`，显式 `/tmp/routing-acceleration-configs-20261027/quality.json`；独立固定代码副本，先完成一次显式合成编译/CUDA 预热，再顺序执行真实任务。图表由 `/tmp/routing-render-final.py` 读取完成报告生成。
- 关键配置：苍南与楠溪江完整 1 m 输入，沿用验收端点、档距 500 m、半径 3 m、转角 90°与道路控制参数；tensor 演化、compiled_cpu 评价、cuda:0，seed 123–127。固定 32768 次评价比较种群 48/256/1024，固定种群 256 比较预算 8192/32768/131072；共 50 次独立质量试验，每个配置/seed 执行一次。不同 seed 不作为同 seed 的复现证据，复现由前述三次性能重复和逐位重放覆盖。
- 输出：`outputs/validation/routing-acceleration-20261026/p5-quality/` 保存独立快照、全部紧凑候选、完成时间、逐次配置与记录、冻结参考及 `report.json`；上级 `overview.json`、`acceleration-and-quality.png` 和 PDF 汇总性能与质量。源码身份保存于 `/tmp/routing-acceleration-configs-20261027/quality-source.json`。
- 完整性：50/50 全部完成，累计 2375680 次搜索评价，754709 条可行候选逐条通过原 CPU 硬检查；每次计数与配置预算一致，每次均找到可行候选。原始输入 SHA256 不变，快照独立，没有修改正式场景或既有实验。
- 质量参考：每场景所有已完成前沿并集取精确非支配集合后冻结，苍南 1352 个不同目标向量、楠溪江 555 个；统一 min/range 仅用于报告。该参考是本轮最佳已知集合，不是连续问题真实全局前沿。
- 固定种群 256 的 IGD+ 五 seed 中位数：苍南在预算 8192/32768/131072 下为 0.078791/0.020570/0.005387，楠溪江为 0.466849/0.208357/0.034432；8192 到 131072 分别降低约 93.2%/92.6%。加性 epsilon 中位数分别从 0.142857 降至 0.058602、从 0.498402 降至 0.104445。说明本轮大预算改善了相对最佳已知参考的质量，不等同于证明全局收敛。
- 固定预算 32768 的 IGD+：种群 48/256/1024，苍南分别为 0.019135/0.020570/0.048902，楠溪江为 0.135641/0.208357/0.363726。种群单独增大未改善该预算下的结果；对应最终塔数上界中位数，苍南为 175/37/13、楠溪江为 195/57/33。代数和按代触发的扩展次数存在耦合，不能把差异都解释为种群的固有优劣；应优先匹配评价预算和充分代数，再研究搜索策略。
- 下界与资源：苍南最少已知 2 塔达到直线松弛下界；楠溪江最少已知 17 塔，下界 15，仍有未闭合差距。质量矩阵进程峰值 RSS 约 4786 MiB，PyTorch GPU allocated 峰值约 103.45 MiB，远低于配置预算；CUDA 驱动上下文不在 allocated 数字中。
- 版本与时间：矩阵始终使用 `1bbb398` 固定副本，未混入后续精确坐标缓存；苍南大预算中位约 64.9 s、楠溪江约 191.9 s，均包含原 CPU 复核。性能门槛使用此前独立的 `dc9242b` 三次冷任务测量；后续缓存通过位级重放验证等价。最终全仓回归是在最后两次质量任务的 CPU 复核阶段运行，不将该阶段耗时作为独立速度门槛，等搜索时间指标按已保存的候选完成时间报告。
- 最终软件验证：763 passed、6 skipped；既有四项外部 PostgreSQL 与两项已归档历史夹具按原条件跳过。前端生产构建、新选线断言和 28 组不依赖历史夹具的回归通过。隔离真实浏览器六项任务链路通过；正式 API 空闲后保留环境平滑重启，新后端枚举、设备输入、JSON 显存默认值和楠溪江入口只读检查通过，地址 `http://10.28.0.176:5176/`。只读脚本首轮把可行域渲染 POST 误判为写入，修正白名单后通过，产品无需修改；未提交正式优化或数据修改请求。证据为 `regression-final.xml`、`frontend-regression.json`、`browser/`、`runtime.json`、`runtime-browser.json` 与截图。
- 交付边界：默认仍保留便于对照的原种群、预算和后端；本机推荐 tensor 演化＋compiled_cpu 评价＋cuda:0，双卡精确评价作为显式选项。保留「净空未校核」，不将已知参考质量等同于真实全局最优；原始数据与矩阵产物不纳入代码提交。
- Git：质量执行 `1bbb398`；缓存加速 `de41a70`、`a494bc4`；复现诊断 `2916ccb`。本条随最终文档提交，不推送远程。
- 状态：有效。

## 2026-10-27 楠溪江无可行解诊断与搜索预算修复

- 实验名：nanxi-routing-feasibility-20261027。
- 目的：复现用户真实接入点下的两次失败，区分预算不足、参考线被过滤和局部修复无法绕行，并验证修复及正式默认预算。
- 入口：`experiments.benchmark_routing`，配置为 `outputs/validation/nanxi-feasibility-20261027/configs/100m-manifest.json` 与 `200m-manifest.json`；完整发布复验使用 `experiments.launch_routing_run` 及同目录 `100m.json`。逐因素诊断脚本保存在该验收目录的 `diagnostics/`，不作为算法实现。
- 原任务：`outputs/routing-1793062752732`（水平档距 100 m）与 `outputs/routing-1793062828655`（200 m）。固定起点 WGS84 `(120.782730639, 28.218519189)`、终点 `(120.832309424, 28.258890993)`，塔基半径 10 m，最大单处水平转角 100°，道路控制距离 5/30 m，无人工区域。两次均为 NumPy/reference/CPU，seed 123，种群 48，评价预算 768。
- 复现：两组原代码重放的全部候选坐标均与已保存失败结果一致，均只有 16 代、零可行解。编译 CPU 对照的目标及违规在既有 float64 容差内一致，不能把后端变化误认为搜索修复。
- 逐因素结果：仅提高原预算到 8192 次，两组仍无可行解。原初始化在全部参考线失败时把初始上限退回理论下界，导致近可行参考线没有进入种群。仅修复参考线保留后，200 m 在原预算内找到 180 条可行候选；100 m 仍失败，甚至种群 64、32768 次评价、512 代也只将最大档距总超限降到约 42.77 m。这证明加预算不能替代绕行初始化。
- 修复：曲线均失败时追加合法塔位 A* 参考线，节点复用完整塔基检查，边允许跨越不可落塔地物，同时限制水平档距与人工禁跨区；生成后完整评价与删塔计入原预算。所有参考线仍失败时保留其塔数范围继续演化。四目标、工程输入和最终 CPU 复核保持原口径；未新增工程超参数。
- 原预算复验：NumPy/reference 在 100/200 m 下分别得到 172/139 条可行候选；NumPy/compiled_cpu 为 182/145，tensor/compiled_cpu/CPU 为 125/158。均保持 768 次评价、16 代，首次可行在线路评价序号 8 出现。完整 100 m CLI 发布成功，摘要、线路、逐档、坡度和快照均保存于 `published/routing-1793062752732`；没有覆盖原实验。
- 多 seed：两组均用 tensor/compiled_cpu/cuda:0、种群 48、768 次评价，seed 123–127。100 m 可行数为 101/177/197/156/134；200 m 为 187/198/204/212/223，10/10 均成功。所有可行候选由原 CPU 精确检查，原始输入哈希与失败任务完全一致，快照独立、源文件未改变。完整候选和报告在 `five-seeds-100m/` 与 `five-seeds-200m/`。
- 当前默认复验：默认 JSON 调整为 tensor/compiled_cpu/CPU，种群 64，32768 次评价。两组均实际完成 512 代，100/200 m 分别得到 9615/10371 条可行候选，最少可行新增塔为 99/43，直线松弛下界为 66/33；不能据此宣称全局最优。正确性诊断另做了一轮未缓存独立 CPU 逐条复查，因此其总耗时不作为性能门槛证据。
- 预算可见性：搜索与基准摘要记录 `generation_count` 和 `initialization_evaluations`；页面显示提交前代数上限和保存结果的实际代数。历史仍按保存参数回读，通过「恢复当前算法默认参数」显式应用新默认，不改接入点、工程参数或区域。
- 软件验收：775 passed、6 skipped；跳过项仍是四项外部 PostgreSQL 与两项已归档历史夹具。后续针对导航/初始化/指标/发布的 24 项回归通过。前端选线断言、生产构建和隔离浏览器七项链路通过，包含预算提示、默认恢复、CUDA worker、历史、刷新及取消。正式 API 在三个已接收任务全部结束后保留环境平滑重载，正式浏览器只读检查确认楠溪江已显示新默认，地址为 `http://10.28.0.176:5176/`。
- 输出：`outputs/validation/nanxi-feasibility-20261027/overview.json` 汇总配置、对照、源码哈希与运行检查；`full-regression.xml`、`routing-tests.xml`、`browser/`、`runtime.json`、`runtime-browser.json` 和截图提供验收证据。未上传原始数据或实验矩阵；本轮无确认过期且待删除的仓库产物。
- Git：复现基础 `a97d747`，工作区源码哈希记录在验收汇总；本条随可行性、预算、测试及权威文档一并提交，不推送远程。
- 状态：有效。

## 2026-10-27 PILOT 迁移准备轮：原函数与当前默认基线

- 实验名：pilot-migration-round0-20261027。
- 目的：冻结原始函数、确定受控行为与成对验收门槛，并保存当前默认策略的三工况基线。此轮不迁移搜索机制、不要求质量提升。
- 入口：`tests/test_pilot_source.py`、`tests/test_pilot_migration_metrics.py`、`tests/test_routing_metrics.py`；固定源码副本上的 `experiments.benchmark_routing`；`experiments.compare_pilot_migration` 自比较。
- 来源：PILOT_v2 `4e9d2c859ff9e1f4caed9a76ad14f08f66d4b3e0` 的六个原文件按字节冻结，来源及 SHA256 在测试参考目录；目录级 Git 属性禁止换行转换。原函数夹具验证手算半径、约束/Pareto 接受、RRT 目标偏置/回溯与失败回退、空间邻近双向拼接，不导入旧应用或新增依赖。
- 关键配置：当前算法源码固定 `aa3d9ce`，独立副本不受后续工作区改动影响；真实任务为苍南 220 m 与楠溪江 100/200 m，端点、半径、转角与道路参数全部沿用已保存任务。tensor/compiled_cpu/CPU，种群 64、32768 次、seed 123–127，单线程环境控制；合计 15 次、491520 次搜索评价。
- 输出：`outputs/validation/pilot-migration-20261027/round0/` 保存当前默认三工况完整紧凑候选、输入快照与报告；`configs/` 保存任务、manifest、固定源码哈希与预注册门槛；`round0-tests.xml` 和 `round0-self-comparison.json` 保存检查证据。
- 结果：15/15 找到可行解，152110 条可行候选均经原 CPU 检查。苍南五 seed 可行数 10136/10158/10100/10504/10177；楠溪江 100 m 为 9615/9766/9772/9669/9733；200 m 为 10371/10519/10344/10540/10706。自比较的 IGD+/epsilon 与形状指标一致，收益门槛拒绝无改进结果。准备相关 21 项测试通过，未改动当前优化逻辑或默认参数。
- 输入说明：运行期间实时楠溪江 landuse 被更新，原脚本末尾源文件检查阻止了部分完成报告。各已完成试验始终使用独立快照，快照实际 SHA256 与原保存任务一致，候选坐标/目标重算内容哈希与逐次记录一致；受影响组另生成 `resumed-report.json`，显式标注实时源变化，未伪称实时源保全。后续使用原保存快照建立只读隔离场景根，不回滚用户当前场景。
- 边界：这是原函数受控运行与默认算法基线，不代表 PILOT 机制已迁入。NumPy 基线另在独立副本完成，作为接入轮的成对对照。耗时受两条并行基线任务影响，本轮不作速度门槛结论。未发现本轮可确认删除的仓库产物。
- Git：算法基线 `aa3d9ce`，原始来源 `4e9d2c8`；本条随准备轮源码、指标工具、测试及权威文档提交，不推送。
- 状态：有效。

## 2026-10-27 PILOT 接入轮：CPU 参考策略与共享预算

- 实验名：pilot-migration-round1-20261027。
- 目的：先验证可选策略、路径适配与预算接入不改变现有 NumPy 搜索，再迁入增强机制；本轮不要求搜索收益。
- 入口：`tests/test_pilot_integration.py`、全仓 pytest、前端选线断言与生产构建；`experiments.benchmark_routing`、`experiments.compare_pilot_migration`；真实 JobService/Worker 发布及隔离浏览器。
- 关键配置：沿用准备轮三工况的独立只读输入，NumPy/compiled_cpu/CPU，种群 64、32768 次、seed 123–127。候选为 `pilot_reference` 且机制列表为空；对照为固定 `aa3d9ce` NumPy 版本。原默认仍为 standard/tensor/compiled_cpu/CPU。嵌套参数严格校验，未迁入机制明确拒绝。
- 输出：`outputs/validation/pilot-migration-20261027/round1/`、`round1-repeat/`、`round1-comparison.json`、`round1-repeat.json`、`round1-regression.xml`、`round1-jobs/`、`round1-jobs-report.json` 和 `round1-browser/`。
- 结果：15/15 完成，491520 次评价、152833 条可行候选；全部候选坐标/目标内容哈希逐 seed 与固定 NumPy 基线相同。三工况各重复 seed 123 一次，哈希再次相同。共同参考下所有质量与形状指标一致、无退化，收益门槛按预期拒绝零改进；该准备性质轮不据此宣称算法提升。
- 接入验证：共享账本与每次调用窗口均限制评价；原初始化与后代使用同一总预算，空策略不提前施加新增阶段限额。私有 Python/NumPy 随机流不污染全局，连续坐标/固定端点往返不量化；增量塔基/档段检查在 150 条随机线路及手算例上与完整可行性一致。最终 CPU 复核与输出重建另计。
- 软件验证：796 passed、6 skipped；跳过仍为四项外部 PostgreSQL 与两项历史归档夹具。前端断言与生产构建通过。三工况真实 Jobs 各 768 次、12 代，可行数 235/152/119；发布的全部坐标与目标分别与原 NumPy 对照的同预算前缀一致。真实浏览器八项链路通过，包括显式选择兼容 CPU 配置、地图输入、四目标比较、历史、刷新及取消，无页面异常。
- 边界：未迁入 RRT 或其他新搜索机制；仅提供经过验证的策略入口和当前模型适配。运行使用冻结场景，不修改实时场景。并行重复试验下的耗时不作为速度证据。没有确认应清理的仓库产物，原始数据不纳入提交。
- Git：准备轮 `7bc5b4b`，算法对照 `aa3d9ce`；本条随 CPU 策略、适配器、预算、界面及权威文档提交，不推送。
- 状态：有效。

## 2026-10-27 RRT 接入发现的编译零档段评价修复

- 实验名：routing-zero-span-parity-20261027。
- 目的：复现 RRT 浏览器发布失败，核对搜索与原 CPU 完整报告，修复继续正式对照前的评价一致性问题。
- 入口：`tests/test_routing_zero_spans.py`；隔离浏览器保存的 72 次任务逐候选重放；全仓 pytest 与实际浏览器发布。
- 关键配置：四个方向的直线路径各含相邻重复塔；零长度档段始终不可行。问题源于编译后端负零传入 `atan2`，两边同时向负方向时额外累加 pi，而原 CPU 为零。仅在相邻档长度为零时显式取零转角，保留无效几何计数与其他目标/约束。
- 输出：`outputs/validation/pilot-migration-20261027/round2-browser-diagnostic/`、`zero-span-regression.xml`、`round2-browser/`；早期 RRT 矩阵另保留在 `round2-precheck/`，不作为正式收益对照。
- 结果：新增测试先复现 1 failed/3 passed，修复后四个方向全部通过；相关 17 项与全仓 807 passed、6 skipped。失败任务在修正版下全部候选的目标、可行性和违规均与原 CPU 在规定容差内一致。隔离浏览器八项实际链路通过，包括报告写出、RRT 开关历史恢复与取消，无页面异常。
- 对照约束：该修复会影响部分不可行候选排序，已停止尚未完成的旧评价器 RRT 矩阵；旧准备/接入轮保留为当时版本的复现记录。后续 RRT 收益判断必须重新运行同一修正版评价器的基线与候选，不能把评价修复的收益归于 RRT。不调整报告一致性容差。
- Git：接入轮 `73f5304`；本条随零档段修复、独立回归及建模口径单独提交，不推送。其余 RRT 迁移实现保持未提交，等待正式验证。
- 状态：有效。

## 2026-10-27 PILOT RRT 轮：正确迁入，跨工况收益未通过

- 实验名：pilot-migration-round2-20261027。
- 目的：仅增加原 PILOT 单树 RRT 初始化，验证扩展/最近分支/回溯、当前工程模型适配和真实收益，不同时迁入多尺度 A*、填充或后续算子。
- 入口：`tests/test_pilot_rrt.py`、`tests/test_routing_zero_spans.py`、`experiments.benchmark_routing`、`experiments.compare_pilot_migration`；同目录保存 manifest 的真实 Jobs 与浏览器验收。
- 关键配置：两组都使用已修复零档段问题的 compiled_cpu/NumPy/CPU，相同冻结三工况与端点，种群 64、32768 次、seed 123–127。A 为关闭机制的 pilot_reference；B 只启用 `["rrt"]`。新树以当前最大档距定最大扩展，保持原最小/最大比例与目标偏置；自由目标、树尝试和每个松弛档迭代均有显式上限。完整评价共用总预算和初始化窗口，节点/边探查单独计数。
- 实现边界：原源码按字节留存并由受控函数测试对照。生产实现移除旧粗格量化、定长编码与 A* 回退统计，保留连续米坐标及固定端点；复用当前完整塔基/档段检查。所有具体数值来自默认 JSON；standard 与空参考策略默认不启用 RRT。页面提供实验复选框，切回 standard 清空机制，历史保留显式开关。
- 输出：`outputs/validation/pilot-migration-20261027/round2-baseline/`、`round2/`、`round2-repeat/`、`round2-comparison.json`、`round2-overview.json`、`round2-case-summary.json`、`round2-jobs/`、`round2-browser/`；`configs/round2-fixed-code-sha256.json` 保存整组固定代码身份，`round2-final-regression.xml` 与 `round2-focused.xml` 保存回归证据。
- 完整性：正式 A/B 共 30/30 完成、983040 次评价，全部找到可行解。A 有 152833 条、B 有 157684 条可行候选，均由原 CPU 逐条复核。B 每次均注入 16 条可行且不同的 RRT 种子，共 240 条；三个工况各重复 seed 123，全部候选内容哈希和 RRT 来源计数一致。快照独立、输入与整组源码哈希保持不变，不修改实时场景。
- 质量：以共同冻结最佳已知前沿和统一报告归一化，苍南 IGD+ 五 seed 中位数从 0.051727 降为 0.030947，改善 40.17%，5/5 配对改善；楠溪江 100 m 从 0.055798 降为 0.039294，改善 29.58%，4/5 改善；200 m 从 0.127115 升为 0.158373，退化 24.59%，只有 1/5 改善。200 m 的 epsilon 中位数虽从 0.321369 降为 0.285514，也不能抵消 IGD+ 的超限退化。
- 专项指标：初始形状多样性中位数，苍南从 0.134752 降为 0.101113，仅 1/5 改善；楠溪江 100/200 m 从零分别升为 0.098356/0.098801，5/5 与 4/5 改善。两个楠溪江工况通过专项改善条件，但 200 m 违反质量不退化要求，最终门槛为 false。可行发现率两组均为 15/15，不以种子调用次数替代收益证据。
- 观察与限制：200 m 的初始塔数上界中位数由 59 增为 95，RRT 注入较长且未修剪路径后，种群构成和搜索范围同时改变；它是后续诊断线索，尚不是退化原因的独立实验证明。没有为通过本次验收而调参，也没有将最佳已知前沿称为全局最优。
- 资源：A/B 最大单进程 RSS 约 3605/3604 MiB，本轮无 CUDA 显存占用。五 seed 完整运行耗时中位数，苍南约 46.8/47.8 s、楠溪江 100 m 约 91.8/117.1 s、200 m 约 72.5/79.0 s；各组并行执行，只作资源记录，不作为独立速度门槛。
- 软件验收：全仓 813 passed、6 skipped；专项 26 passed。跳过仍为四项外部 PostgreSQL 与两项历史归档夹具。前端断言、生产构建与隔离浏览器八项链路通过。三个真实 Jobs 各 768 次、12 代，可行数 275/222/280，完整发布成功。正式 API 在四个已接受用户任务全部成功后保留命令/环境重载；正式楠溪江浏览器只读三项检查通过，未提交任务或修改数据，地址 `http://10.28.0.176:5176/`。
- 决策：正确性通过，稳定收益未通过。按已确认规格保留默认关闭的实验实现及完整负结果，在本轮停止，不迁移下一项多尺度 A*，不切换默认策略；再次推进先讨论 200 m 的退化与实验方案。该有效负结果不是推广 RRT 的验收通过。没有确认应删除的仓库产物，诊断矩阵保留且已修正迁移后的候选路径引用。
- Git：准备轮 `7bc5b4b`、接入轮 `73f5304`、零档段修复 `f8b782a`；本条随已验证 RRT 实验实现、测试、界面、助手说明及权威文档提交，不推送。
- 状态：有效。

## 2026-10-27 初始化衔接累计消融与角色验收调整

- 实验名：pilot-initialization-ablation-20261027。
- 目的：检查冗余塔、初代未补齐、来源比例与塔数上界耦合，保留原始模式回放，不把初始化节点数量等同于合理工程塔数。
- 入口：`experiments.benchmark_routing`；验收目录 `configs/queue.json` 中的显式 manifest；`tests/test_pilot_initialization.py`。原有 `prune_reference` 的保存种子预检查确认 16 条路径可用 138 次完整评价减少塔位且其余目标不恶化。
- 配置：三份冻结历史工况与原输入，NumPy/compiled_cpu/CPU，种群 64、8192 次、校准 seed 131–133。比较原参考、原始 RRT、删塔、补齐、上界锚点与无 RRT 填充对照；三工况共 48 次完整试验。所有完整删塔和填充请求共享原总预算，初始化阶段倍数从 JSON 读取；内部试探不自动作为处理后种子，复用槽位单独记录。
- 输出：`outputs/validation/pilot-initialization-20261027/` 下 `screen/`、`quick/`、`quick-comparison.json`、`configs/source-sha256.json`、`legacy-prefix-replay.json`、`confirm/`、`confirmation.json`、`repeat/`、`jobs/` 与 `browser/`。
- 正确性：原始模式在楠溪江 200 m、seed 123 前 8192 次的全部坐标/目标与固定基线一致。新模式记录实际初代、唯一数量、RRT 槽位和处理前后塔数；目标预算内完成补齐，耗尽时仅复用已完整评价状态，不伪造新评价。初始受控例确认删除可能增加跨越时拒绝删除。
- 快速结果：楠溪江 100 m 的三 seed IGD+ 中位数，原参考 0.160884、原始 RRT 0.097539、补齐 0.056161、上界锚点 0.055821；苍南原参考 0.071690、原始 RRT 0.060978、补齐 0.061384、上界锚点 0.092275；200 m 原参考 0.171635、原始 RRT 0.350867、补齐 0.351619、上界锚点 0.334940。每工况使用自身共同参考，指标不跨工况直接比较。
- 复核：200 m 的上界锚点模式另跑 seed 123–127、32768 次，IGD+ 中位数 0.166732，原参考 0.127952，只有 1/5 配对改善，未消除退化。seed 123 完整重复内容哈希一致。真实 8192 次 Jobs 发布成功；模式及上限输入、历史、刷新和取消通过实际浏览器验证。单 seed 的积极结果没有被表述为稳定收益。
- 方法调整：用户随后明确指出 RRT 的主要作用是初始化多样性，要求与多尺度 A* 等配套机制组合后判断。迁移规格已改为逐组件检查正确性/角色、按完整候选与消融检查质量，不再以每个组件单独提高最终精度作为继续迁移的门槛；旧负结果保留为消融证据。多尺度 A* 尚未实现，本条不能代表完整原项目初始化已迁入。
- Git：基础 `c2f838a`，本条随可选初始化模式、测试、界面和权威文档提交；原始数据及矩阵不提交，不推送。
- 状态：有效。

## 2026-10-27 RRT 米制参数校准与独立五 seed 复验

- 实验名：pilot-initialization-calibration-20261027。
- 目的：区分初始化衔接和米制扩展参数的影响，在独立 seed 上检查校准是否泛化，不更改四目标或工程约束。
- 入口：`experiments.benchmark_routing`；验收目录 `configs/calibration-queue.json`、`step-queue.json`、`fresh-queue.json` 及其中每次运行的配置。分析使用公共 `reference_front`、`compare_front`、`migration_gate`。
- 配置：校准使用 seed 131–133、8192 次，先单独比较终点采样概率，再固定采样概率检查最小扩展与档距比例；共 18 次。选出的 compact 配置为 bounded 初始化、终点采样概率 0.95、最小比例 1.0，选择信息在 `selected-profile.json`；仍保留原 JSON 的 RRT 概率/比例和 standard 默认，不静默推广校准值。
- 独立验证：选择完成后冻结配置，200 m 工况使用未参与选择的 seed 141–145、32768 次，原参考、原始 RRT、compact 各五次，共 15 次；另用三个校准 seed 检查其他两工况。输入独立快照、工程参数一致，代码哈希保持不变，全部运行均找到可行候选。
- 输出：`outputs/validation/pilot-initialization-20261027/` 下 `calibration/`、`step-calibration/`、`all-calibration-comparison.json`、`fresh-confirm/`、`fresh-confirmation.json`、`compact-quick/`、`compact-quick-comparison.json`、`compact-repeat/`、`compact-jobs/` 与 `verification.json`。
- 独立结果：共同参考下，200 m IGD+ 中位数为原参考 0.140202、原始 RRT 0.245952、compact 0.211674。compact 相对原始 RRT 改善 13.94%，5/5 配对改善；相对原参考仅 3/5 改善，中位数仍退化 50.98%，不满足替换当前算法的质量门槛。epsilon 中位数分别为 0.352037、0.468750、0.385982。各次最少塔数中位数从原始 RRT 的 51 降为 compact 的 43，最好找到 36 塔可行路线，不能据此声称四目标整体优于原参考或达到全局最优。
- 其他工况：8192 次三 seed 检查中，苍南原始 RRT/compact IGD+ 为 0.053334/0.048514；楠溪江 100 m 为 0.059756/0.124871。100 m 的 compact 树尝试均达上限，只得到 0/0/2 条不同可行 RRT 种子，完整运行中位约 63.4 s；该参数不能直接作为通用默认。校准、单工况确认和最终算法验收范围分别保留。
- 软件验证：最终全仓 821 passed、6 skipped，专项 30 passed；跳过仍为四项外部 PostgreSQL 与两项历史归档夹具。前端断言、生产构建、实际模式/参数提交与历史/取消八项浏览器链路通过。compact seed 141 完整重复哈希一致；真实 8192 次 Jobs 发布成功，2309 条可行候选、123 代。各组仅 CPU，未占 CUDA 显存。
- 交付：界面显式提供初始化模式、阶段评价上限及 RRT 采样/步长参数；保持默认关闭且不推广 compact。正式 API 在已接受任务结束后保留命令/环境重载，正式只读浏览器检查另保存。后续按用户修订的方法补齐 A*+RRT 初始化流程，以完整组合评估，不继续用单项精度门槛阻断配套机制。
- Git：基础 `c2f838a`，本条与初始化实验实现、文档、助手知识一并本地提交，不推送。无确认应删除的历史产物；原始数据及矩阵不纳入提交。
- 状态：有效。

## 2026-10-27 选线模块化重构基线冻结

- 实验名：routing-modularity-baseline-20261027。
- 目的：重构前冻结同后端、同设备、同 seed 的逐候选行为，不以最终质量近似代替等价。
- 入口：`experiments/validate_routing_refactor.py`。固定源码为 `9ac409e14a0fedab0390f822eb177b99a14cc207`，独立源码快照和三工况输入位于验收目录的 `baseline.json`。
- 配置：小型确定性场景覆盖四种初始化模式、RRT 开关、NumPy/张量演化、reference/compiled_cpu/tensor 评价、CPU/CUDA/双 CUDA，以及初始化耗尽预算，共 28 组。
- 输出：`outputs/validation/routing-modularity-20261027/` 下 `synthetic-baseline.json`、`synthetic-p0.json`、`comparison-p0.json`。两个标为 incomplete-trace 的早期文件存在轨迹字段覆盖，不能作为验收证据。
- 结果：4731 次完整评价的坐标、目标、约束、来源顺序，父代/环境选择、各随机流最终状态、归档、塔数扩展、预算与插件 schema 全部相同。计时和显存峰值不参与语义相等判断。三真实工况 40 次基线运行已完成，后续重构另做配对验收。
- Git：本条随基线捕获工具和已批准的重构边界本地提交，不推送；原始数据、矩阵和验收输出不提交。
- 状态：有效。

## 2026-10-27 选线公共契约解耦验收

- 实验名：routing-modularity-p1-20261027。
- 目的：任务配置、结果类型、道路控制与输出目录工具抽取后保持行为等价。
- 入口：`experiments/validate_routing_refactor.py`；配置沿用已冻结的 28 组确定性矩阵。
- 输出：`outputs/validation/routing-modularity-20261027/synthetic-p1.json`、`comparison-p1.json`。
- 结果：4731 次完整评价及选择、随机流、结果、schema 与基线逐项一致；相关配置、上下文、PILOT、输出、插件、站址道路及目录工具测试 68 passed。测试的 EDT 监测点随实现移到公共道路模块，仍要求同一退距只计算一次。
- Git：基线 `edaecc8`；本条随公共契约抽取本地提交，不推送。无用户能力或参数变化，助手知识无新增内容。
- 状态：有效。

## 2026-10-27 选线初始化与预算边界验收

- 实验名：routing-modularity-p2-20261027。
- 目的：分开初始化编排、参考生成、塔数范围、几何修复与后处理，显式隔离填充变异依赖。
- 入口：`experiments/validate_routing_refactor.py`；配置沿用冻结的 28 组矩阵。
- 输出：`outputs/validation/routing-modularity-20261027/synthetic-p2.json`、`comparison-p2.json`。
- 结果：4731 次完整评价、选择、随机状态和结果与基线一致；初始化、PILOT、搜索、张量测试 40 passed。新增窗口测试验证阶段限制与总限制共用、历史只读、预算耗尽不产生评价。机械抽取的换行错误在收集期被发现并修正，未提交失败状态。
- Git：基础 `05637ec`；本条随初始化职责拆分本地提交，不推送。没有目标、参数或用户能力变化。
- 状态：有效。

## 2026-10-27 选线原生驱动与算子装配验收

- 实验名：routing-modularity-p3-20261027。
- 目的：分开 CPU/张量驱动、独立动作、选择 bundle 与最终归档，支持 Python 内部替换，不新增 HTTP 或配置参数。
- 入口：`experiments/validate_routing_refactor.py`；固定的 28 组同后端/设备/seed 轨迹。
- 输出：`outputs/validation/routing-modularity-20261027/synthetic-p3.json`、`comparison-p3.json`。
- 结果：4731 次评价、选择、随机状态、归档和 schema 全部与基线一致；专项 53 passed，包括八个 CPU/张量动作替换、两后端选择及范围替换、初始化与演化隔离、内部试探复用评价和分层导入约束。测试为填充初始化预留完整阶段预算后再检查演化替换，避免把没有进入演化误判为注入失败。
- 边界：原动作互斥概率、张量批量抽样与掩膜、CPU 末代额外未评价子代、张量独立初代选择均保留；张量仍使用原有显存检查。三真实工况的完整配对矩阵另行验收。
- Git：基础 `4d7eaef`；本条随原生驱动/算子和内部组合入口本地提交，不推送。无用户能力变化。
- 状态：有效。

## 2026-10-27 选线前端控制与展示拆分验收

- 实验名：routing-modularity-p4-20261027。
- 目的：将选线工作区的异步任务与历史控制、配置展示、结果展示分离，保持页面行为和请求一致。
- 入口：前端 `npm run test:routing`、`npm run build`；隔离 API/Worker 与浏览器验收脚本记录于验收目录。
- 输出：`outputs/validation/routing-modularity-20261027/browser/` 下 `browser.json`、`routing.png`、服务日志。
- 结果：选线前端断言、TypeScript 和生产构建通过；实际浏览器八项通过，包括参数恢复、PILOT CPU 锁定、地图点选/经纬度、两种禁区、真实任务、四目标对比/逐档指标、历史、刷新与取消；无页面错误，共享地图保持北向。临时服务使用独立场景和输出，代理明确指向临时 API。
- 限制：完整前端历史脚本在首项缺少 `outputs/cmaes_region_0.1/data_metadata.json` 时停止；这是历史夹具缺失，后续全局验收单独记录其余断言，不创建假正式实验填充该目录。
- Git：基础 `b0ba184`；本条随前端职责拆分本地提交，不推送。用户功能、HTTP 和默认值不变，助手说明无新增项。
- 状态：有效。

## 2026-10-27 选线模块化最终行为与资源验收

- 实验名：routing-modularity-final-20261027。
- 目的：确认外壳解耦与内部组件替换保留现有搜索行为，再恢复后续机制迁移的基础。
- 入口：`experiments/validate_routing_refactor.py`、`experiments.benchmark_routing`；配置与调度脚本保存于验收目录 `configs/`，资源/浏览器脚本随各组输出留存。
- 固定身份：原版源码 `9ac409e14a0fedab0390f822eb177b99a14cc207`；最终独立源码及 201 个文件 SHA256 见 `final-source.json`。三工况使用既有冻结历史输入；默认 JSON 的 SHA256 保持 `adcd50ecadae8b91351c6e12caec5ce0c944dbdccb8c9c3b82e9e86d7d87d0ad`。
- 配置：苍南 220 m、楠溪江 100/200 m；标准 NumPy/张量、PILOT 四初始化模式，种群 64，8192 次、seed 123/141；另有三个标准默认 32768 次及一个 bounded RRT 32768 次。共 40 次成对运行，每版 425984 次评价。张量初代改为显式交接已评价候选后，对受影响的六个配置再做 9 次配对、每版 147456 次评价；不重复无变化的 CPU 组。
- 输出：`outputs/validation/routing-modularity-20261027/` 下 `verification.json`、`real-comparison.json`、`final-tensor-comparison.json`、`synthetic-p5.json`、`comparison-p5.json`、`final-regression.xml`、`frontend-regression.json`、`resources-final/`、`browser/`、`runtime.json` 与 `runtime-browser.json`。旧 `resources/` 是中止的预检，不作为最终性能证据。
- 等价：40 次的 402467 条唯一候选和追加 9 次的 137461 条唯一候选，坐标、数量、目标、可行性、Pareto 次序、首次评价索引及全部语义 JSON 一致。小型 28 组另外覆盖重复评价请求与实际父代/环境选择，4731 次完整请求、所有随机流最终状态、归档、预算、扩展、代数及插件 schema 一致；包含 CPU、CUDA 与双设备。真实 NPZ 为去重档案，不把它表述为完整重复请求轨迹。
- 可替换性：独立替换八个 CPU/张量动作、初始化、选择、范围与多次试探生成均有测试；初始化填充与正式演化依赖隔离，已评价子代直接复用。张量初代显式接收初始化器选定的已评价集合，默认仍保留原范围内全部初期试探；有专项测试证明被排除的内部试探仍归档但不进入父代。
- 资源：固定源码、独立持久上下文、同一时刻一个搜索、暖启动后三次交替配对。NumPy 耗时中位 14.618→14.598 s，张量 CPU 8.834→8.887 s，PILOT bounded 17.965→17.863 s；峰值 RSS 3612.359→3614.113 MiB，约增加 0.049%，均未触发 10% 退化门槛。另在真实楠溪江 200 m、8192 次、CUDA 演化/compiled_cpu 评价测得 PyTorch 峰值分配 1.583→1.359 MiB，峰值保留同为 2 MiB；这不含 CUDA 驱动上下文，也不代表张量评价大场景的显存量。保留原有显存预算与批量原生操作。
- 软件验证：当前全工作区 845 passed、6 skipped。跳过为四个外部 PostgreSQL 和两个缺失历史场景/夹具。前端选线断言与生产构建通过；其余 28 个前端测试文件通过，两个旧实验夹具文件缺失的测试显式跳过。隔离真实浏览器八项主流程及两项 404/过期历史保护通过；正式只读三项通过，无页面错误或优化/数据写入。
- 运行：正式 API 在一个已接受任务终止后保留原命令/环境重载；PID、健康及默认策略核对见 `runtime.json`。正式地址 `http://10.28.0.176:5176/`。本轮只清理已经完成的前端测试临时编译目录；原始输入、有效历史产物与工作区其他改动保留。
- 文档与助手：算法边界、代码地图、测试策略、运行入口、前端规格均同步。没有新增用户操作、目标、参数或算子选择 UI，助手知识核对后无需增加说明。
- Git：分阶段基线 `edaecc8`、契约 `05637ec`、初始化 `4d7eaef`、原生驱动 `b0ba184`、前端 `e00449d`；本条随最终显式初代交接、对照工具、测试和文档本地提交，不推送。原始数据、矩阵和不属于本轮的坐标改动不纳入提交。
- 状态：有效。

## 2026-10-27 PILOT 全组件续迁基线冻结

- 实验名：pilot-components-p0-20261027。
- 目的：以模块化版本为起点，先完成 CPU 组件正确性，全部迁完后统一诊断求解质量。
- 入口：`experiments/validate_routing_refactor.py`；冻结原函数、迁移契约及模块化专项测试。
- 配置：既有 28 组 CPU/CUDA/双设备、旧初始化模式、RRT 开关与预算边界；源提交 `b2d04a4`，PILOT 来源保持固定提交。
- 输出：`outputs/validation/pilot-components-20261027/baseline.json`、`baseline-trace.json`。
- 结果：4731 次完整评价基线已冻结；原函数、接入与模块化专项回归通过。A* 三维代价、长度按最大档距换算和独立 CPU 驱动已获确认；不以迁移阶段质量收益阻断后续组件。
- Git：本条与续迁权威规格本地提交，不推送；工作区其他坐标改动与数据保留。
- 状态：有效。

## 2026-10-27 PILOT CPU 运行适配与独立入口

- 实验名：pilot-components-p1-20261027。
- 目的：建立私有运行状态、米制半径、原候选接受与评价身份，独立入口先委托现有 CPU 行为。
- 入口：`experiments.validate_pilot_components`、`experiments/validate_routing_refactor.py`、`tests/test_pilot_components.py`。
- 配置：三冻结工况，CPU/compiled_cpu，种群 64、8192 次、seed 123，机制 cpu_driver；独立 Jobs 在苍南同配置发布。
- 输出：`outputs/validation/pilot-components-20261027/p1/`、`p1-trace.json`、`p1-compatibility.json`。
- 结果：三次均完成精确 8192 次、全部可行候选经 CPU 复核，真实 Jobs 成功。28 组旧路径全部 4731 次完整评价、选择与随机状态保持；原参数值不变。原函数分支、长度换算、状态隔离、配置和基准默认行为专项测试通过。首轮 Job 因临时数据库提前建目录导致目录创建失败，修正后只补跑 Job，未重复三工况。未计算质量指标。
- Git：基础 `5da6ae0`；本条随运行适配、验证工具与文档本地提交，不推送。
- 状态：有效。

## 2026-10-27 PILOT 多尺度三维 A* 正确性迁移

- 实验名：pilot-components-p2-20261027。
- 目的：保留原 A* heap、松弛和回溯，适配 DEM 三维代价、当前塔基/档段几何及多尺度种子。
- 入口：`experiments.validate_pilot_components`，原 `_astar_on_binary_grid` 夹具与 `tests/test_pilot_components.py`。
- 配置：三冻结工况，CPU/compiled_cpu，种群 64、8192 次、seed 123，机制 cpu_driver/astar。
- 输出：`outputs/validation/pilot-components-20261027/p2/`；P1 的隔离重放在 `p1/job-isolated/`。
- 结果：三次均完成精确预算，A* 尝试、成功、唯一/重复/不可行种子按真实值记录，可行档案经 CPU 复核。受控内核路径与原函数一致，另覆盖三维绕开高程、跨水不落塔、人工禁跨和实际搜索接入。未计算 IGD+/epsilon 或调参。
- 隔离修正：P1 首次 Job 发布依赖环境变量，实际落到 `outputs/cpu-components-job/`；P2 同名保护拒绝覆盖。验证工具现显式临时设置发布根并恢复环境，P1/P2 分别在各自隔离根重放成功，有回归测试证明外部目录不写入。原首次产物保留，未删除或覆盖。
- 文档/助手：已记录邻接几何差异；助手只描述已实现的独立 CPU 与 A*，不声称完整迁移或质量提升。
- Git：基础 `f45d7de`，本轮本地提交，不推送。
- 状态：有效。

## 2026-10-27 PILOT 混合初始化与动态塔数采样

- 实验名：pilot-components-p3-20261027。
- 目的：迁移原 A*/RRT 构建、随机塔数/基线路径填充与有界重复回退，保留连续米坐标和动态范围。
- 入口：`experiments.validate_pilot_components`、`tests/test_pilot_components.py`、前端 routing 断言及构建。
- 配置：三冻结工况，CPU/compiled_cpu，种群 64、8192 次、seed 123，hybrid 模式和 cpu_driver/astar/rrt。
- 输出：`outputs/validation/pilot-components-20261027/p3/`。
- 结果：三工况实际初代均为 64 个唯一完整评价候选；来源分别为 A*/RRT/填充 3/16/45、1/16/47、3/16/45，全部运行完成精确预算并复核可行档案。真实隔离 Jobs 发布成功；固定小输入重复结果一致。原弧长采样对照、极小预算复用、旧模式与插件/助手回归 44 passed，相关混合/配置测试 50 passed；前端断言和生产构建通过。未计算质量收益。
- 兼容：旧模式不变；UI 新混合模式显式声明 A*，RRT 切换保留其余机制，避免只支持 RRT 时的覆盖写法丢掉新机制。助手同步说明，其他坐标说明仍保留未提交。
- Git：基础 `9cf88e6`，本轮本地提交，不推送。
- 状态：有效。

## 2026-10-27 PILOT 独立演化、邻近交叉与父代重选

- 实验名：pilot-components-p4-20261027。
- 目的：接入原中性交配选择、最近点双向交叉、有限索引重选和编码后复核，独立 CPU 循环共享当前排序与账本。
- 入口：`experiments.validate_pilot_components`、`tests/test_pilot_components.py`、关闭增强的完整轨迹捕获。
- 配置：三冻结工况、CPU/compiled_cpu、种群 64、8192 次、seed 123；hybrid 初始化，cpu_driver/astar/rrt/nearby_crossover/distinct_parents。
- 输出：`outputs/validation/pilot-components-20261027/p4-verified/`、`p4-trace.json`、`p4-compatibility.json`。旧 `p4/` 是中止诊断，不作为完成矩阵。
- 结果：三工况与真实 Jobs 完成精确预算，保存交叉调用/候选/接受及父代重选计数，可行档案经 CPU 复核。原交叉候选顺序和提前退出、父代私有 RNG 状态对照通过；专项累计 66 passed。28 组旧路径全部评价/选择/随机流与基线一致。未计算收益指标，耗时与原始可行计数仅作记录。
- 修正：受控回归发现本次算子已复评的父代仍携旧评价序号造成重复计费，按本次账本中该坐标的最新身份复用后重放矩阵；同时让参考初始化 RRT 与增强算子共享同一私有适配器，旧默认注入路径不变。
- Git：基础 `45db695`，本轮本地提交，不推送。
- 状态：有效。

## 2026-10-27 PILOT 独立自适应多试探变异

- 实验名：pilot-components-p5-20261027。
- 目的：迁移原独立概率触发和围绕同一原始塔位的多次极坐标试探，保留接受顺序与私有随机流。
- 入口：`experiments.validate_pilot_components`、`tests/test_pilot_components.py`。
- 配置：三冻结工况、CPU/compiled_cpu、种群 64、8192 次、seed 123；hybrid 加 P4 机制及 path_mutation。
- 输出：`outputs/validation/pilot-components-20261027/p5/`。
- 结果：三次完成精确预算，实际记录变异调用、抽样、完整评价和接受；所有可行档案经 CPU 复核，隔离真实 Jobs 成功。原提案逐坐标和两个 RNG 最终状态对照通过；交叉/变异可同一子代依次发生；一试探窗口与父代不变测试通过。相关累计 62 passed，配置/投影边界专项 55 passed。未调参或计算质量收益。
- Git：基础 `9d69023`，本轮本地提交，不推送。
- 状态：有效。

## 2026-10-27 PILOT 删塔、平滑与逐塔 VNS

- 实验名：pilot-components-p6-20261027。
- 目的：迁移删塔捷径、水平转角平滑和逐塔高斯 VNS，核对原控制流与目标语义。
- 入口：`experiments.validate_pilot_components`、原函数逐提案对照测试。
- 配置：三冻结工况、CPU/compiled_cpu、种群 64、8192 次、seed 123；hybrid 与 P5 机制增加 shorten/smooth，VNS 本轮只做函数级验证。
- 输出：`outputs/validation/pilot-components-20261027/p6/`，每工况独立子目录及日志。
- 结果：三工况和苍南隔离 Jobs 均完成，完整评价次数准确，所有可行档案经 CPU 复核；删塔和平滑均有实际完整评价与接受计数。源函数逐提案、返回路径与两个随机流一致；含零/单塔、耗尽窗口和半径单位试探数回归，累计专项 50 passed。三个独立进程并行运行，耗时不作串行速度比较。未计算质量收益。
- Git：基础 `99eb494`，本轮本地提交；助手同步已实现可选后处理，不宣称 VNS 已接主循环。
- 状态：有效。

## 2026-10-27 PILOT 周期精英局部搜索

- 实验名：pilot-components-p7-20261027。
- 目的：把已对照 VNS 接入环境选择后的可行极值/稀疏精英调度，验证周期与编码后再次接受。
- 入口：`experiments.validate_pilot_components`、`tests/test_pilot_local_search.py`。
- 配置：三冻结工况、CPU/compiled_cpu、种群 64、8192 次、seed 123；P6 全部机制增加 elite_local_search。
- 输出：`outputs/validation/pilot-components-20261027/p7/`，独立三进程与苍南 Jobs。
- 结果：三工况完成精确预算，VNS 在真实主循环产生抽样、完整评价和接受，编码后接纳及最终存活另记，全部可行档案经 CPU 复核，Jobs 成功。受控原精英顺序、1/4/7 代触发、分配额度及编码丢失改善拒绝验证通过，累计专项 53 passed。最初集成夹具允许零塔直达，无可扰动塔；改为必须落塔的工况后证实实际 VNS 接入。未计算质量收益。
- Git：基础 `151c35b`；本轮本地提交，同步助手已实现能力，不推送。
- 状态：有效。

## 2026-10-27 PILOT 全局注入、存活刷新与精确去重

- 实验名：pilot-components-p8-20261027。
- 目的：接入原每代全局探索、连续存活计数和环境选择前精确去重，保护非支配候选与实际初代来源。
- 入口：`experiments.validate_pilot_components`、`tests/test_pilot_global_search.py`。
- 配置：三冻结工况、CPU/compiled_cpu、种群 64、8192 次、seed 123；P7 全部机制增加 global_injection/population_dedup。
- 输出：`outputs/validation/pilot-components-20261027/p8/`，独立三进程及苍南隔离 Jobs。
- 结果：全部完成准确预算及可行档案 CPU 复核，真实全局窗口有评价和新身份存活，初始化来源未被覆盖。原全局阶段顺序、父代抽样/随机流、存活计数和重复代表选择对照通过；含阈值前注入、只删停滞受支配者、精确微小坐标差、消失重现与去重回退。累计专项 59 passed，补充原全局控制流后全局专项 7 passed。未计算质量收益。
- 修正：专项检查发现新增来源计数函数与目标塔数参数重名，已改为独立名称，并重跑原混合填充回归。
- Git：基础 `faacf36`；本轮本地提交，同步助手说明，不推送。
- 状态：有效。

## 2026-10-27 PILOT 全组件正确性与软件验收

- 实验名：pilot-components-p9-20261027。
- 目的：冻结全部适用 CPU 组件，核对标准路径保留、当前模型精确复核及真实软件流程。
- 入口：全仓 pytest、前端 test:routing/build、`experiments.validate_routing_refactor`、三工况验收与隔离 Playwright。
- 配置：三冻结工况、种群 64、8192 次、seed 123；完整机制和 hybrid。质量诊断协议另冻结 seed 1001–1005，未用于既有校准。
- 输出：`outputs/validation/pilot-components-20261027/p9/`、`p9-trace.json`、`p9-compatibility.json`、`p9-browser/`。
- 结果：三次准确完成 8192 次并通过可行档案 CPU 复核；同 P8 的全部候选/目标哈希一致，新增观测没有改变完整组轨迹。28 组旧路径全部 4731 次完整评价、选择与随机流一致。全仓 899 passed、6 skipped（原有外部服务/场景条件）；前端选线断言和构建通过。真实隔离浏览器完成完整机制历史加载、RRT 切换不丢算子、实际 UI 重提、北向地图、保存/刷新、取消保留旧结果，页面错误为零。
- 修正：同粗格 A* 成功/失败缓存补全；小初代池的精英上限按配置规模；旧测试把现已实现 A* 当未知机制，改用真正未知名称。来源摘要区分内部评价与最终新存活身份。
- 文档/助手：更新源码映射、模块地图、CLI、机制摘要与助手能力，旧模型和默认策略不变。本轮不计算质量或调参。
- 独立性/运行：只含选择性暂存内容的源码快照另通过 895 passed、6 skipped；正式 API 确认空闲后保留命令/环境重载，只读正式浏览器检查未发送写入请求，默认仍为 standard、RRT 关闭。
- Git：基础 `c931258`；完成后本地提交，不推送。
- 状态：有效。

## 2026-10-27 PILOT 全组件冻结质量诊断

- 实验名：pilot-components-p10-20261027。
- 目的：所有适用组件迁移验收后，统一检查完整组与四个功能组移除；不以单组件收益作为迁移门槛。
- 入口：`experiments.benchmark_routing`；输出目录中的 `coordinator.py`、`summarize.py`、`finite-probe.py` 保存调度与汇总代码。
- 配置：源码冻结为已提交版本 `9e2310c950914b530b12b600d5d3898ba1dc4cd7` 的独立副本，未混入工作区其他坐标修改。三冻结工况；种群 64、完整评价 32768 次；seed 1001–1005。standard-cpu、standard-tensor、full、without-initialization、without-crossover-mutation、without-local、without-global，共 105 次独立组合；full 的 seed 1001 每工况再复跑一次，共 108 次。
- 分组：full 显式启用所有迁入组件，包括原默认关闭的内嵌 shorten/smooth，不冒充原项目默认配置。初始化组移除 hybrid/astar/rrt；交叉变异组同时移除父代重选；局部组同时移除周期 VNS 与内嵌删塔/平滑；全局组只移除 global_injection。完整分组与解析参数见 protocol.json。
- 输出：`outputs/validation/pilot-components-20261027/p10/`。`report.json` 保存共同参考下的逐次指标、四目标范围、首次可行、代数、耗时和内存；`diagnosis-facts.json` 保存阶段与来源汇总；`validation-summary.json` 保存独立复现核对；每工况保留共同参考和 normalization JSON。
- 完整性：108 次共完成 3,538,944 次搜索评价，全部准确用满预算；105 个独立组合全部找到可行解，可行候选均经原 CPU 复核。三个复跑的坐标、塔数、目标、可行标记、Pareto 索引和评价序号逐数组一致（仅排除墙钟时间）；源码/输入哈希不变，快照不是原文件硬链接。
- 资源：最多 36 个独立 CPU 进程，数值库各 1 线程；没有使用 GPU。并发抽查合计约 69.13 GiB RSS，单次进程峰值约 4.04 GiB。表外耗时保留为并发墙钟记录，不能用来声称串行加速。

IGD+ 五 seed 中位数如下，越小越好；每列使用自己的共同经验前沿及 min/range，只能在同一工况内比较。经验前沿不是全局最优证明。

| 组 | 苍南 220 m | 楠溪江 100 m | 楠溪江 200 m |
| --- | ---: | ---: | ---: |
| standard-cpu | 0.043789 | 0.390591 | 0.202486 |
| standard-tensor | 0.041125 | 0.378088 | 0.208125 |
| full | 0.080933 | 0.123338 | 0.160397 |
| without-initialization | 0.098934 | 0.163932 | 0.185462 |
| without-crossover-mutation | 0.091343 | 0.144846 | 0.259096 |
| without-local | 0.094110 | 0.105775 | 0.119801 |
| without-global | 0.084999 | 0.127800 | 0.171349 |

结果解释：

- full 相比 standard-cpu 的 IGD+ 中位数在楠溪江两组较低、苍南较高。逐 seed 配对胜出为苍南 2/5、楠溪江 100 m 5/5、200 m 2/5；不能把中位数差异写成每个 seed 或每个工况都更好。full 的 epsilon 中位数分别为 0.193957、0.220130、0.303064；共同参考精确覆盖比例中位数约为 0.53%、0.75%、0.20%，也没有形成对标准组的全面优势。
- without-local 在楠溪江两组的 IGD+ 中位数更低，但逐 seed 仅 1/5 和 3/5 优于 full；尤其 100 m 的中位数与配对结果方向不同，不能据此直接判断 VNS 应关闭。该移除组还同时改变了内嵌后处理、评价分配和实际代数，并没有单独隔离 VNS。
- 编码保留是明确的诊断信号：五 seed 累计局部 raw 改善到 encoded 仍改善，苍南为 627→101（16.1%），楠溪江 100 m 为 1023→36（3.5%），200 m 为 748→100（13.4%）。对应局部阶段使用约 22.3%、41.8%、29.6% 的完整预算。源控制流已正确保留；当前模型下重采样和修复会损失不少局部改善，后续应单独检查，不能先把它当作迁移错误或唯一质量原因。
- 代数与上界调度也不同：标准组代数中位数均为 512，full 为 32/52/37；最终塔数上界中位数为 23/116/91，标准为 139/230/187。内部试探共用评价预算，但扩展仍按代数触发，这是已保留的调度事实，不能把较少代数直接解释为提前停止。
- 楠溪江 100 m 的候选生成与修复衔接值得继续诊断：五 seed 的初始化有 1215 次完整评价后塔数越出活动范围，全局阶段有 2899 次；全运行累计 RRT 迭代约 1309 万次。FE 相同不代表节点/边检查工作量相同。需要分别研究净有效种子率、编码及预算分配，不能仅靠继续增加所有搜索调用。现有计时未单独拆出局部/全局几何开销，本轮不作精确阶段耗时归因。
- 有限目录穷举：对 9 个固定候选点、0–3 塔的有序不重复目录共评价 586 条，19 条可行；两种连续搜索在独立 2048 次 sanity check 中都覆盖该目录前沿。目录是连续空间的有限子集，不能据此证明连续问题全局最优；完整定义与结果见 finite-catalogue.json。
- 结论：组件正确迁入与实际接入已验证；质量具有工况与 seed 差异。当前证据支持先诊断编码损失、有效种子和预算/上界调度，再另立质量优化实验。本轮未调参、未切默认、未推进张量化。
- 软件核对：移除界面已过期的“尚待统一诊断”描述；前端生产构建和正式页面只读检查通过，页面错误与写入请求均为零。现有助手功能说明仍准确，不新增调用能力。
- Git：算法来源 `9e2310c`；本条、必要的界面质量状态说明随诊断结果本地提交，不推送。
- 状态：有效。

## 2026-10-27 完整 PILOT 张量化基线与性能剖析

- 实验名：pilot-acceleration-t0-20261027。
- 目的：用户已授权完整 PILOT GPU 批处理；先冻结当前 CPU 版，定位新组件热点并验证剖析不改搜索结果。
- 入口：现有 `experiments.benchmark_routing`，输出中的 run-profiles.py/run-replays.py 分别使用 cProfile 与未插桩重放。
- 配置：源提交 `d477806` 的独立源码，三冻结工况，完整机制、CPU/compiled_cpu，种群 64、2048 次评价、seed 123；所有参数和工程输入保存到 manifest。
- 输出：`outputs/validation/pilot-acceleration-20261027/`，各工况 profile/replay、pstats、函数累计时间与 t0-replay-validation.json。
- 结果：三工况剖析前后候选/目标哈希与准确预算一致，可行档案经 CPU 复核。未插桩耗时约 3.90/119.79/37.06 秒；本轮三个独立 CPU 进程并行，不是无争用串行速度结论。cProfile 的楠溪江 100 m 样本中 RRT 累计约 102.89 秒，A* 约 44.28 秒；200 m 样本 A* 约 33.14 秒，投影约 6.90 秒。函数累计时间包括被调用者且相互嵌套，不能相加为阶段总时长；带 profiler 的时间不作加速基准。初始化/候选几何确为重要热点，只加速排序不足。
- 设计：用户确认单线路内部试探/接受顺序保留、跨线路固定批次并行记账；CPU/GPU 用固定提案对照，GPU 自身 seed 复现，不要求跨后端整轨迹相同。契约与 T0–T9 阶段已写入迁移权威文档。
- 资源：开始检查时两张 24 GiB RTX 4090 均有其他计算进程且高利用率；未终止外部进程，正式 GPU 基准须另核对占用。
- Git：基础 `d477806`；本条与已确认执行契约先行本地提交，不推送。
- 状态：有效。

## 2026-10-27 完整 PILOT 原生张量评价与批量账本

- 实验名：pilot-acceleration-t1-20261027。
- 目的：增加设备常驻评价结果入口和共享窗口张量请求，避免新驱动每条线路反复转换，保持现有 CPU/标准张量行为。
- 入口：`tests/test_pilot_tensor_runtime.py`、原路径回放、输出中的 validate-native.py；苍南隔离 Jobs。
- 配置：CPU/CUDA:0、float64；三冻结工况各抽取 96 条真实候选，对照当前原 CPU 的四目标、八项违规和可行性。Jobs 使用 T0 苍南完整组、2048 次、种群 64。
- 输出：`outputs/validation/pilot-acceleration-20261027/t1-native-validation.json`、t1-legacy-trace.json、t1-legacy-compatibility.json、t1-job/。
- 结果：三工况的 CPU/CUDA 原生结果均满足既有数值容差，可行性逐条一致；24 项原生/旧张量/窗口回归通过，补充 CUDA 分块后原生专项 9 passed。28 组全部旧候选轨迹与冻结基线一致；真实 Jobs 成功。覆盖人工区域、补齐位 NaN、零塔、空批、非法数量及总/阶段预算耗尽；改变 CPU/CUDA 评价微批次仍返回相同结果。
- 实现：`TensorEvaluationBatch` 返回设备数值，违例归一化表达式供标量与张量共用；`evaluate_tensors` 先按剩余额度截断，再计算并记录所有请求，档案在明确批次边界转 CPU。完整 PILOT GPU 驱动尚待后续阶段接入，不将本入口当成整链加速完成。
- Git：基础 `ba4d901`，本阶段验证后本地提交；没有用户功能/参数变化，助手能力说明仍准确，不推送。
- 状态：有效。

## 2026-10-27 完整 PILOT 批量几何预筛

- 实验名：pilot-acceleration-t2a-20261027。
- 目的：建立不调用四目标评价的张量塔基、档段与完整路径合法性查询，为投影/修复/生成提供设备预筛。
- 入口：`tests/test_pilot_tensor_geometry.py`、输出中的 validate-geometry.py。
- 配置：CPU/CUDA:0、float64；小型人工区/相切/重叠/转角/无效 padding 样例与两种工作空间；三冻结工况各 96 条真实候选。
- 输出：`outputs/validation/pilot-acceleration-20261027/t2a-geometry-validation.json`。
- 结果：三工况 CPU/CUDA 路径布尔值与原 CPU 完整可行性逐条一致；几何与 native 累计 15 项通过，补充精度/形状拒绝后几何专项 7 passed。实际验证路径分块并且预筛没有调用完整目标评价；有效塔位非有限值拒绝也已补测。点、路径和塔对轴均控制工作量，近阈值/人工几何回算单独计数，不计作完整目标请求。
- Git：基础 `e286cfc`；T2 拆成已可独立验证的几何查询与随后路径处理子步，本子步先提交。没有新增用户功能/参数，不推送。
- 状态：有效。

## 2026-10-27 完整 PILOT 张量投影与路径重采样

- 实验名：pilot-acceleration-t2b-20261027。
- 目的：按当前 CPU 净距与投影字典序、重复点和二维弧长插值实现设备路径处理，不混入编码质量优化。
- 入口：`tests/test_pilot_tensor_paths.py`、输出中的 validate-paths.py。
- 配置：CPU/CUDA:0、float64；受控阻塞/人工区域/无解投影/重复端点/不同塔数样例；三冻结工况各 20 个投影点及 12 条变长路径。
- 输出：`outputs/validation/pilot-acceleration-20261027/t2b-path-validation.json`。
- 结果：小型 CPU/CUDA 投影逐坐标与原版一致，保留首次成功方环和距离/净距平局；三工况 GPU 投影仍完全一致，重采样最大坐标误差约 4.55e-12 m，固定端点与父代未改变。相关累计 33 passed，统一 config/显存释放入口后路径专项 10 passed。Torch stable argsort 的参数形式在初始专项中发现并修正后复验。有效中心不构建多余净距场；点/候选轴分块和显存检查不改变投影结果。
- 实现：TowerBatch 增加复制、补齐与掩膜合并，处理过程中不转成逐条 NumPy 路径；净距场保留 CPU float32 EDT 数值，只在任务内延迟上传并可显式释放。有限档距修复另在 T2c 接入。
- Git：基础 `fc96301`；当前子步骤与权威规格/模块地图同步，本地提交，不推送。
- 状态：有效。

## 2026-10-27 完整 PILOT 张量有限修复与采样组合

- 实验名：pilot-acceleration-t2c-20261027。
- 目的：保留最长档插塔与每塔首次合法试探，将独立塔位/线路几何操作批量化，并组合既有重采样和投影。
- 入口：`tests/test_pilot_tensor_repair.py`、输出中的 validate-repair.py，原有完整路径回放。
- 配置：CPU/CUDA:0、float64、固定标准正态提案；有限次数不足/充分、阻塞中点、父代不变及未触发插塔的不可行线路；三冻结工况各 12 条真实路径重复采样。
- 输出：`outputs/validation/pilot-acceleration-20261027/t2c-repair-validation.json`、t2-legacy-trace.json、t2-legacy-compatibility.json。
- 结果：受控修复与原 CPU 逐坐标一致，最长档顺序和次数截断保留；实际三工况 GPU 固定 seed 输出完全复现，插塔未超过原次数，CPU 目标/几何核对一致。仍不可行的候选按真实值保留，没有假报可行。底层累计 35 passed，随后补充提案格式和分配前失败检查；28 组旧路径轨迹全部一致。
- 显存：修复、投影、压缩的预算检查前移至大数组复制/分配之前；正式执行只生成当前逻辑轮的随机平面，不堆积多轮提案。
- Git：基础 `bd7be0d`；T2 子步完成后本地提交，不推送。
- 状态：有效。

## 2026-10-27 完整 PILOT 设备候选与种群选择

- 实验名：pilot-acceleration-t3-20261027。
- 目的：在设备上保存已评价候选，实现中性锦标赛、精英顺序、精确去重及连续存活；保持未评价候选不能入选。
- 入口：`tests/test_pilot_tensor_population.py`、输出中的 validate-population.py。
- 配置：CPU/CUDA:0、float64；受控平局、不同父代有限重试、CV 容差阶梯、符号零、补齐位与消失后重现；三冻结工况各 96 条路径加 10 个重复槽位。
- 输出：`outputs/validation/pilot-acceleration-20261027/t3-population-validation.json`。
- 结果：累计底层 50 passed；三个工况的 rank、拥挤度、去重后 64 个评价序号和存活计数均与固定输入序号的 CPU 对照一致。精英极值/稀疏顺序一致；唯一数不足时原池回退。GPU 使用已确认的稳定输入序号平局规则。
- 实现：身份比较实际塔数与有效 float64 位型，补齐和容量不影响身份；仅保存上一代存活状态，没有设备历史栈。
- Git：基础 `b7e13f5`；对应规格和模块地图同步，本地提交，不推送。
- 状态：有效。

## 2026-10-27 完整 PILOT 张量变异与重组流水线

- 实验名：pilot-acceleration-t4-20261027。
- 目的：在设备候选之间执行原交叉、独立变异、删塔和平滑，保护内部试探、接受、重编码及预算行为。
- 入口：`tests/test_pilot_tensor_variation.py`、输出中的 validate-variation.py。
- 配置：CPU/CUDA:0、float64、相同确定性或显式极坐标提案；三工况各 12 个真实父代、6 个子代，两个评价微批次设置下重复。
- 输出：`outputs/validation/pilot-acceleration-20261027/t4-variation-validation.json`。
- 结果：14 passed；单线路 CPU 请求、接受结果及父代不变验证通过，多线路固定提案与单独执行一致。三个工况分别完成 81/51/73 个完整评价，所有目标和可行性经当前 CPU 全量复核；同 seed 在不同评价微批次下提案、评价序号和子代完全复现。零额度、部分额度和本次调用重查父代身份均通过。初次并行提案测试误用了 float32，显式修正为约定的 float64 后复验。
- Git：基础 `28160c4`；独立算子阶段完成，本地提交，不推送；尚未切换软件默认策略。
- 状态：有效。

## 2026-10-27 PILOT 交叉、独立变异与 VNS 批量调度受控验收

- 实验名：pilot-acceleration-vns-batch-20261027。
- 目的：按用户收紧后的范围补齐 VNS 批量接口，验证三算子逐次接受与 CPU 一致；不启动完整性能或质量实验。
- 入口：`tests/test_pilot_tensor_variation.py` 中既有确定性算子/固定变异测试、`tests/test_pilot_tensor_vns.py` 的一个受控测试。
- 配置：CPU/CUDA:0、float64；VNS 两条线路、固定正态提案与选点顺序，快速/完整邻域、充分/部分/零阶段额度。交叉与独立变异在既有测试内补充逐次接受和预算检查。
- 输出：pytest 终端结果，无新增冻结工况产物。
- 结果：仅直接相关的 10 项参数化测试全部通过；VNS 两条线路逐次接受/拒绝与 CPU 一致，包含实际接受和拒绝；父代坐标不变，所有返回候选均已完整评价，预算外状态不会被接受。交叉和独立变异的逐次接受、父代及额度检查也通过。
- 边界：未重放旧路径，未重复三冻结工况；未启动 T6/T8/T9，也不作速度判断。完整 GPU 主循环尚未接通，助手可见软件能力未变化，无需修改助手功能说明。
- Git：基础 `adecdc5`；本步有效改动与权威文档同步，本地提交，不推送。
- 状态：有效。

## 2026-10-27 张量化独立审查与瓶颈复测

- 实验名：tensor-audit-e27b156-20261027。
- 目的：按用户新的验证请求，独立核对当前张量化的正确性、实际接入范围与进一步加速机会；不实现新搜索机制或切换默认后端。
- 源码：真实候选与计时使用 `e27b15687804edcb79de58bbec6a9f5743db92c1` 的干净 Git 快照；全仓回归另在当前工作区运行。未提交的坐标改动不混入计时源码。PILOT CPU 的 driver、hybrid、RRT、A* 与冻结 CPU 基线 `d477806` 逐字节相同。
- 入口与输出：`outputs/validation/tensor-audit-e27b156-20261027/` 下 `audit.py`、`polygon_probe.py`、`summary.json`、`real-evaluators.json`、`current-cpu-replay.json`、`polygon-fallback.json`、回归 XML 和临时差分/错误复现脚本。
- 配置：只读使用三工况已有独立快照；每工况用 seed 7123 抽取 128 条候选，再加入 64 条扰动候选，共 576 条。float64、RTX 4090 cuda:0；原 CPU、compiled_cpu 与原生张量评价对照，张量微批次分别为 17/256。组件计时在完整回归结束后预热并顺序运行三次，数值库线程设为 1；期间另有秒级 CPU 边界复现，未与其他长时实验并行。未增加正式实验任务或修改场景。
- 正确性：576 条的可行性与原 CPU 全部一致，四目标、八项违规及总违规均通过既定容差；张量目标最大绝对误差约 `5.46e-12`。当前全仓 965 passed、6 skipped，跳过仍为四个外部服务和两个历史场景/夹具条件；CUDA/双卡用例实际运行。另有 210 组受控路径算子对照、200 个随机重复候选池和 19000 次接受判断对照通过。
- 尚存问题一：`tensor_repair.sample_routes` 首次投影后调用严格保留终点的通用去重；末塔与终点近重复时，会在 CPU 允许重采样并恢复终点之前抛错。32×32 合成场景、建筑条带第 26 列、终点 `(28-1e-9, 8)`、25 塔，CPU 正常返回，张量 CPU/CUDA 均报 `PILOT path deduplication changed fixed endpoints`。末塔距终点约 `3.85e-11 m`。这属于采样流程边界，不能通过全局去掉终点保护草率解决。
- 尚存问题二：前次审查的标准张量驱动自定义修复漏掉扩展代首个子代仍可复现；4 个子代只调用注入修复 3 次。默认策略不受该注入问题影响。本轮仅确认并记录两项 P2，没有修改产品代码。
- 固定候选评价：每次 192 条，统一列表入口、预热后三次中位数，compiled_cpu→CUDA 分别为苍南 `16.303→7.794 ms`、楠溪江 100 m `166.938→33.781 ms`、200 m `125.491→27.089 ms`，约 2.09/4.94/4.63 倍。该口径包含候选转换/回传，但不含场景上传、初始化与发布，不能当作完整 PILOT 的加速倍数。
- 当前完整 CPU 热点：楠溪江 100 m、完整 PILOT、种群 64、2048 次、seed 123，单次串行搜索及归档/CPU 复核共 `122.717 s`，结果哈希与冻结回放一致。轻量函数计时为 RRT 157 次 `75.233 s`、A* 三次 `23.815 s`，两者无相互嵌套，合计约 80.7%；完整评价 `1.904 s`、排序 `0.0247 s`。初始化 `70.357 s` 与规划器/评价存在包含关系，不能再次相加。本轮只跑一次真实完整搜索，不据此给出稳定端到端速度倍率。
- 人工区域回退：对同一批 192 条苍南线路，增加与其无关的角落禁跨多边形，目标/可行性不变，但 CPU 全量复核从 0 条变为 192 条；原生 GPU 评价三次中位数由 `7.054 ms` 变为 `310.433 ms`。现有实现遇任意人工区域就复核全批，具备采用保守包围盒预筛再精确检查的明确优化机会；不能删去精确边界检查。
- 结论与边界：标准张量后端已接入；完整 PILOT GPU 主循环仍未接通，配置仍明确拒绝 PILOT 的 tensor/CUDA 组合。组件通过不代表完整 GPU 算法验收完成。进一步实现应先处理上述边界，再接通批量驱动；主要时间机会在 RRT/A* 的重复容器构造与节点/边检查、人工区全批回退，以及设备诊断同步和无效批次成员。未启动完整 GPU 容量/质量实验，不承诺尚未测量的收益。
- 文档/助手：本次无用户能力、参数或默认值变化，助手功能说明无需新增；验收与限制仅追加于本记录，未建立重复结论文档。没有发现需删除的过期产物，原始输入及既有有效输出保留。
- Git：审查基线 `e27b156`；本条作为独立审查记录本地提交，不推送。
- 状态：有效。

## 2026-10-27 PILOT 采样终点与替换修复边界修正

- 实验名：pilot-batch-boundaries-20261027。
- 目的：按已核实问题修复临时终点去重及扩展代修复替换接口，不改变默认搜索规则。
- 入口：`test_sampling_resamples_a_temporarily_deduplicated_endpoint`、`test_expansion_probe_uses_the_same_injected_repair_as_other_children`，受影响路径处理测试。
- 配置：32×32 合成场景、25 塔、末塔近终点、CPU/CUDA；标准张量驱动 4 个子代的扩展代，显式替换修复。
- 结果：修改前 3 个参数化回归全部失败，修复后及路径相关共 13 passed。采样只在自己的临时路径允许去掉近重复终点，随后按 CPU 口径重采样恢复接入点；通用去重仍会拒绝改变终点。扩展代 4 个子代均恰好使用指定修复，默认边界探查不重复修复。
- 输出：pytest 终端结果。未跑三冻结工况或性能实验。
- Git：基础 `90ef0b4`；权威规格同时记录本轮完整驱动和固定对照协议，本地提交，不推送。
- 状态：有效。

## 2026-10-27 完整 PILOT 张量主循环与软件入口接通

- 实验名：pilot-batch-driver-integration-20261027。
- 目的：连接已验证设备候选、交叉/独立变异、环境选择、精英 VNS、全局注入与连续存活，不改四目标、试探数、阶段顺序或规划器。
- 入口：`tests/test_pilot_tensor_driver.py`，既有集成/算子/双卡/替换接口测试，前端 routing 与 build，以及一次完整旧路径 capture。
- 输出：`outputs/validation/pilot-batch-20261027/regression.xml`、legacy-trace.json、legacy-compatibility.json；隔离 Jobs 产物在 pytest 临时目录。
- 结果：全仓 978 passed、6 skipped，CUDA 和双 CUDA 实际执行；原有 28 组完整评价、选择、随机状态、范围与归档逐项一致。单/双卡完整搜索、不同评价微批次自身复现、全部启用阶段、初始化耗尽、末批截断、精英未用额度再分配与编码退化拒绝、CPU/CUDA 取消释放均通过。真实 Jobs 成功发布完整 CUDA 任务与实际分工。前端 routing 与生产构建通过；构建保留既有 bundle 体积提示。
- 修正：集成检查发现临时交叉/修复容量会逐代继承，现于环境选择后按真实塔数收紧，不截有效塔。全局父代 stable argsort 调用形式已修正。首次 Jobs 断言误把 execution 描述字符串当作详情字典，改读既有 execution_details 后全仓复验通过。
- 助手：同步 tensor/tensor 配置、CPU 规划边界与不能代用户启动选线的限制，新增评测用例；外部模型评测被自动审批以潜在上下文外发为由拒绝，未调用模型。本地提示与工具边界 3 passed；不冒充实模型评测。
- Git：基础 `4c03a38`；本步实现、权威文档、助手知识与测试同步提交，不推送。三工况质量与计时尚待冻结后执行，不在本条声称加速。
- 状态：有效。

## 2026-10-27 完整 PILOT GPU 接通前后固定预算对照

- 实验名：pilot-batch-paired-20261027。
- 目的：验证完整 GPU 路径接通后的求解质量变化和实际搜索时间，不预设张量化一定加速，不调整规划器或扩大预算。
- 入口：输出中的 `run-paired.py`，复用 `experiments.benchmark_routing`；后处理复用 `experiments.routing_metrics`。
- 源码：接通前 CPU 为 `e27b156`，接通后 GPU 为 `c5e3f54`，均使用独立干净 Git 快照。11 个 CPU PILOT 模块逐字节相同。RRT/A* 未加速，手绘禁区回退未优化，默认策略/参数未改变。
- 配置：苍南 220 m、楠溪江 100/200 m；全部迁入机制显式开启、hybrid、种群 64、2048 次评价；五个 seed 1001–1005，各后端第一 seed 另重复两次，共 42 次串行搜索、30 次独立 seed 运行。CPU/GPU 交替，数值线程固定为 1，库预热在计时外，无 profiler。RTX 4090 cuda:0。
- 输出：`outputs/validation/pilot-batch-20261027/` 下 protocol.json、paired-report.json、completed-rows.json、各次 manifest/log、matrix 独立快照与候选 NPZ，以及三工况共同经验参考。没有覆盖既有有效输出。
- 正确性：42/42 找到可行解，全部准确消耗 2048 次评价，共 86,016 次；阶段合计一致，保存的可行线路全部经过原 CPU 复核。15 组配对的输入哈希、除执行后端/设备外的算法参数、初始化候选坐标/目标/评价序号前缀均完全一致。6 组首 seed 的 12 次复跑哈希全部一致。正式实验期间不改代码、参数或输入。
- 计时：下表取首 seed 三次独立搜索的中位数，包含设备场景建立、CPU 初始化、演化、归档和 CPU 复核；磁盘快照、CPU 问题构建与软件发布不在此时间内，逐次另有记录。所有采样边界的显存均为 2 MiB；四个利用率滚动样本为 4%，其余为 0%，未进行持续独占监控，也不宣称硬件全程独占。

| 工况 | 接通前 CPU（秒） | 接通后 GPU（秒） | GPU 增加时间（秒） | GPU 耗时增加 |
| --- | ---: | ---: | ---: | ---: |
| 苍南 220 m | 4.007 | 9.306 | 5.299 | 132.24% |
| 楠溪江 100 m | 118.597 | 129.500 | 10.903 | 9.19% |
| 楠溪江 200 m | 32.453 | 43.766 | 11.313 | 34.86% |

- 质量：各工况只使用本轮两后端完成前沿构成共同经验参考和固定 min/range，重复结果不增加新参考点；不将它作为连续全局最优。下表为五个独立 seed 的中位数，IGD+ 与 epsilon 均越小越好；胜数是相同 seed 下 GPU 的 IGD+ 更小次数。

| 工况 | CPU IGD+ | GPU IGD+ | GPU IGD+ 变化 | GPU 胜数 | CPU epsilon | GPU epsilon |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 苍南 220 m | 0.094225 | 0.114605 | 变差 21.63% | 2/5 | 0.219691 | 0.230375 |
| 楠溪江 100 m | 0.167989 | 0.155190 | 改善 7.62% | 4/5 | 0.259219 | 0.256899 |
| 楠溪江 200 m | 0.113191 | 0.086404 | 改善 23.66% | 3/5 | 0.364108 | 0.387009 |

- 显存：三工况最大 allocated 分别约 62.8/836.1/839.1 MiB，均在显式预算内；没有静默缩小种群、预算、精度或分辨率。
- 解释：本轮完整 GPU 驱动已可运行，但在此规模没有端到端时间节省，也没有普遍质量不回退的证据。每条线路的接受规则保持，CPU/GPU 随机流及跨线路预算顺序不同，完整搜索轨迹和局部/全局工作量可不同。例：楠溪江 100 m seed1003 的 GPU/CPU 全局调用为 3/2 次，RRT 迭代为 479283/352464，不能把全部时间差归因于 GPU 算术。原 CPU 规划器仍是主要成本，小批次评价、局部串行依赖与设备同步还增加开销；固定候选评价的局部收益不等于完整算法收益。保留可选 GPU 路径和原 CPU 参考，不自动切换默认或继续 T6/T9。
- 软件：正式 API 已知 25 个任务均过期且进程空闲后温和重载，命令/环境保留，健康检查通过。只读真实 Chromium 检查 GPU/双卡参数、CPU 切换与默认机制均通过，零页面错误、零任务/数据写入；证据为 runtime-idle-check.json、runtime-reload.json、runtime-browser.json/png。真实 CUDA Jobs 发布和取消另由前一条集成验证覆盖。
- 助手：已同步执行边界；外部模型评测被自动审批以潜在工作区上下文外发为由拒绝，未绕过。仅报告本地提示/工具边界验证，不声称实模型评测通过。
- Git：边界修复 `4c03a38`，完整驱动 `c5e3f54`；本条与算法总览索引同步本地提交，不推送。原始数据与用户已有坐标修改未纳入提交；本轮有效产物保留，未发现需要删除的过期产物。
- 状态：有效。

## 2026-10-27 固定先验种群筛查组件验收

- 实验名：population-screen-components-20261027。
- 目的：为用户授权的快速扩种群筛查建立受控研究组装，不把规划和局部预算随种群一起放大。
- 入口：`tests/test_routing_population_screen.py`，既有完整驱动 CPU 受控用例。
- 配置：合成路径、CPU/CUDA；两个嵌套种群、独立初始/全局随机流；相同阶段总上限与完整评价预算。
- 结果：新增 4 项参数化测试通过，既有默认驱动用例另通过；阶段上限由多个窗口共享并在评分前截断，默认未设置上限的路径仍可执行。共同种子坐标不变，新增槽位均唯一，初始化和全局候选实际重新评价计费。固定先验只来自旧初始化，最终演化坐标不得进入先验。增加耗尽阶段早退后，直接相关 CPU/CUDA 两项复验通过。
- 实现：账本可选 phase_limits 与完整驱动 Python-only fresh_builder，默认调用保持；固定种子/单塔扰动组装在独立研究模块，不进 API/前端配置，无助手新增能力。
- 输出：pytest 终端。真实六次质量筛查尚未运行，不在本条写结论，也未重跑全仓或旧矩阵。
- Git：基础 `99e2827`；组件、权威规格和索引同步后本地提交，不推送。
- 状态：有效。

## 2026-10-27 固定规划先验的 P64/P256 快速质量筛查

- 实验名：population-screen-nanxi100-20261027。
- 目的：快速验证不增加规划工作、只补充随机个体时，较大种群在相同评价预算下是否提高前沿质量。不修改正式默认，不做大矩阵或参数搜索。
- 源码/入口：干净提交 `54875d6`，`python -m experiments.screen_routing_population --protocol <protocol.json> --output <runs>`。冻结源码目录与完整路径保存在协议中。
- 配置：楠溪江 100 m、cuda:0、float64；P64/P256、每次 E4096、seed1001–1003，共六次串行运行。使用前轮 GPU 运行的初始化坐标构建每个 seed 的共同 64 条种子，不使用最终演化坐标；P256 包含相同前缀及 192 个单塔随机扰动/有限修复个体。每个候选重新评价计费。局部/全局整次额度上限分别 768/64，精英上限不按 P 放大，全局新候选目标固定 10；正式演化算子、试探数、四目标和约束保持。
- 输出：`outputs/validation/population-screen-20261027/` 下 protocol.json、runs/report.json、completed.json、逐次配置/候选 NPZ 和 reference.npy；原初始化文件哈希及历史初始化耗时单列在 bank_provenance。先验生成来自已有实验，本轮不新运行 A*/RRT，时间不代表重新规划的完整任务。
- 正确性：六次均准确完成 4096 次评价，共 24,576 次；全部找到可行解并按既有归档流程 CPU 复核全部可行输出。三个配对的输入哈希、共同 64 个种子坐标前缀一致；初始唯一数确为 64/256，没有靠复制槽位扩容。局部实际用量均为 768，全局未超过 64，新 A*/RRT 调用均为零。过程中不改代码/参数，也未重跑全仓、28 组轨迹或三工况矩阵。
- 质量口径：六次完成前沿构成同一经验参考和 min/range，IGD+、epsilon 均越小越好，不是全局最优。报告三个独立 seed 的中位数。

| 种群 | 实际代数（三个 seed） | IGD+ 中位数 | epsilon 中位数 | 缓存先验后耗时中位数（秒） | 最大本进程 GPU allocated（MiB） |
| --- | --- | ---: | ---: | ---: | ---: |
| 64 | 9 / 9 / 9 | 0.091006 | 0.269274 | 44.927 | 839.1 |
| 256 | 3 / 3 / 3 | 0.104853 | 0.439082 | 49.162 | 858.4 |

- 逐 seed IGD+：1001 为 0.139758→0.152516，1002 为 0.048336→0.059995，1003 为 0.091006→0.104853，P256 为 0/3 胜；epsilon 也为 0/3 胜。中位 IGD+ 变差 15.21%，epsilon 变差 63.06%。新增初始可行个体数从 2/14/6 增至 8/29/19，仍未转化为此预算下的前沿质量收益。
- 时间解释：本轮耗时包含设备建立、随机补齐、演化、归档与 CPU 复核，排除历史规划和当前 CPU 问题构建。P256 中位耗时增加 4.235 秒、9.43%，但两组总评价量相同，不能推断保持相同代数、增加四倍工作量也只需多 9.43%。开始/结束 GPU0 都有约 574 MiB 其他常驻显存、利用率 0%；本进程峰值另计，不宣称全程独占或完整软件提速。
- 结论：在此共同先验、固定总评价量和固定辅助阶段上限下，增大种群未提高质量；实际代数从 9 降至 3。结果只覆盖一个工况/三个 seed，不能否定增大种群并同步增加评价预算的设想，也不能归因于种群规模的普遍效果。保持相近代数的大预算对照尚未做，不在负结果后自动调参或追加组别寻找正收益。
- Git/维护：研究组件 `54875d6`；本记录本地提交，不推送，不改助手/前端能力或生产参数。原始数据和用户已有未提交修改保持，既有有效产物不覆盖；未发现本轮应删除的过期产物。
- 状态：有效。

## 2026-10-27 等代数研究停止逻辑验收

- 实验名：population-generation-stop-components-20261027。
- 目的：纠正将用户「迭代次数不变」误设为「评价预算不变」的实验口径。原 E4096 数据保留为等预算对照，不能替代等代数回答。
- 入口：`tests/test_routing_population_screen.py`、`tests/test_routing_search.py`。
- 配置：CPU/CUDA、两个种群规模，显式完整两代与宽松评价保护上限；原评价预算模式也保留验证。
- 结果：14 passed。新研究参数 max_generations 精确停止在完整目标代数，返回 generation_limit，并且实际评价量低于保护上限；未设置时仍按 evaluation_budget 停止。元数据不再把提前按代数停止写成评价预算用满。
- 实现边界：只增加 Python 研究停止口，不新增 Jobs/前端参数或修改生产默认。两组正式等代数筛查将各自重跑完整九代，不复用原可能部分截断的第九代结果。
- 输出：pytest 终端；正式六次对照尚未运行。
- Git：基础 `6580511`；实现、测试和权威协议同步后本地提交，不推送。
- 状态：有效。

## 2026-10-27 固定完整九代的 P64/P256 质量对照

- 实验名：population-equal-generations-nanxi100-20261027。
- 目的：按用户明确更正的「迭代次数不变、种群正常变大」重新验证。上一轮 E4096 是等评价预算对照，不能用于回答本问题；旧记录作为不同口径的对照保留。
- 源码/入口：干净提交 `082ab2b`，`experiments.screen_routing_population`，协议启用 generations=9；两组都重新运行，不复用旧的可能部分截断的九代结果。
- 配置：楠溪江 100 m、GPU cuda:0、float64，P64/P256、seed1001–1003，共六次串行搜索。每次完整执行九代，评价上限 65536 只作保护；辅助阶段上限、共同初始化坐标、随机填充方式及其独立随机流与上一轮保持，规划工作不增加。
- 输出：`outputs/validation/population-generations-20261027/` 下 protocol.json、runs/report.json、逐次 JSON/NPZ、completed.json 和 reference.npy。数据、先验来源及其历史耗时由协议和逐次 bank_provenance 记录，不覆盖上一轮产物。
- 正确性：六次都完整九代，停止原因均为 generation_limit，全部未触及评价保护上限；实际完整评价总计 51,577 次。三个配对输入与共同种子前缀一致，初始唯一数均为请求的 64/256；全部找到可行解，保存的可行线路逐条经 CPU 精确复核。局部/全局实际评价上限保持 768/64，无新 A*/RRT。未改四目标、约束、算子、试探数或生产默认。
- 质量口径：本轮六次完成前沿构成共同经验参考及统一 min/range；不是全局最优。不跨实验直接比较不同参考下的 IGD+ 数值。下表是三个独立 seed 的中位数，指标越小越好。

| 种群 | 完整代数 | 实际评价次数中位数 | IGD+ 中位数 | epsilon 中位数 | 缓存先验后的耗时中位数（秒） | 最大 GPU allocated（MiB） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 64 | 9 | 4144 | 0.100179 | 0.262388 | 46.965 | 839.1 |
| 256 | 9 | 12425 | 0.054319 | 0.230848 | 105.077 | 859.1 |

- 逐 seed 评价次数：P64 为 4144/4096/4402，P256 为 12425/11884/14626；均按真实请求计费，不人为配平预算。
- 逐 seed IGD+：1001 为 0.188932→0.182836，1002 为 0.074581→0.037416，1003 为 0.100179→0.054319；P256 为 3/3 胜。epsilon 也为 3/3 胜。IGD+ 中位数改善 45.78%，epsilon 改善 12.02%。
- 时间/资源：评价量中位数约 3.00 倍，缓存后求解耗时约 2.24 倍，增加约 58.11 秒；种群四倍没有造成显存四倍，峰值由约 839.1 增至 859.1 MiB。时间包含设备建立、补齐、演化、归档及 CPU 复核，排除历史规划和 CPU 问题构建；不能当作新完整工程任务的冷启动耗时，也未测大种群 CPU 对照，不声称 CPU/GPU 加速倍率。
- 结论：本工况、三个 seed 下，保持相同完整代数并扩大种群取得一致质量收益，同时自然使用了更多评价和时间，支持用户本次提出的方案。小样本不代表其他工况或全局最优，不自动扩展实验、调整默认或把先前等预算负结果推广到本问题。
- Git/维护：停止逻辑 `082ab2b`；本记录与测试策略同步本地提交，不推送。助手/前端能力未新增；用户已有未提交修改和所有原始数据保持，既有有效产物保留，无应删除的过期产物。
- 状态：有效。

## 2026-10-28 初始化可立塔走廊对照

- 实验名：init-corridor-nanxi100-20261028。
- 目的：检查初始化只要求塔位可立、相邻档长不超过最大档距时，完整搜索是否更快，以及九代后的前沿是否明显变差。演化、全局注入和最终评价仍用严格延伸判断。
- 入口：`experiments.compare_init_corridor`。严格臂 `corridor=False`，走廊臂为初始化默认。
- 配置：楠溪江 100 m、hybrid、cuda:0、float64、种群 256、完整 9 代、评价上限 65536 只作保护。seed 1001–1003，两臂共六次，每次从当前场景重新做 A* 和 RRT，不用上一轮缓存种子。
- 输出：`outputs/validation/init-corridor-20261028/` 下逐次 JSON、帕累托 `npy` 和 `summary.json`。
- 正确性：六次都停在 `generation_limit`，都有非空可行帕累托前沿。IGD+ 与 epsilon 只用这六次前沿合成的经验参考，越小越好，不是全局最优。

| 种子 | 严格初始化秒 | 走廊初始化秒 | 严格 IGD+ | 走廊 IGD+ | 严格 epsilon | 走廊 epsilon | 严格总秒 | 走廊总秒 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1001 | 90.736 | 75.175 | 0.180178 | 0.112984 | 0.298441 | 0.236448 | 866.524 | 896.002 |
| 1002 | 82.131 | 66.700 | 0.051922 | 0.044302 | 0.181996 | 0.210882 | 413.698 | 421.499 |
| 1003 | 76.215 | 73.644 | 0.163248 | 0.148574 | 0.279085 | 0.287391 | 486.584 | 515.112 |

- 初始化时间中位数从 82.131 秒降到 73.644 秒，约快 10.3%，三对都更快。IGD+ 中位数从 0.163248 降到 0.112984，约好 30.8%，三对都更好。epsilon 为 1/3 更好。总搜索时间中位数从 486.584 秒增到 515.112 秒；局部搜索和全局注入仍占大头，走廊没有缩短整次搜索。
- 结论：初始化变快且 IGD+ 没有差过 10% 的门槛，可立塔走廊保留为初始化行为。总耗时没有下降，不把这次结果说成整次算法加速。不改默认种群、代数和机制开关。
- 状态：有效。

## 2026-10-28 隔代可立塔走廊全局注入对照

- 实验名：global-period-nanxi100-20261028。
- 目的：看把全局注入改成与局部搜索相同的 3 代间隔，并且全局 RRT 改用可立塔走廊后，九代总时间是否下降、前沿是否明显变差。
- 入口：`experiments.compare_init_corridor`。对照是同一天已经跑完的每代严格全局注入、初始化走廊臂，输出在 `outputs/validation/init-corridor-20261028/`。本轮输出在 `outputs/validation/global-period-20261028/`。
- 配置：楠溪江 100 m、hybrid、cuda:0、float64、种群 256、完整 9 代、seed 1001–1003。演化交叉和局部搜索仍严格。
- 正确性：三次都停在 `generation_limit`，都有非空可行帕累托前沿。IGD+ 用六次走廊相关前沿合成的经验参考，越小越好，不是全局最优。

| 种子 | 每代严格全局秒 | 隔代走廊全局秒 | 每代总秒 | 隔代总秒 | 每代 IGD+ | 隔代 IGD+ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1001 | 252.211 | 82.153 | 896.002 | 352.048 | 0.088336 | 0.110007 |
| 1002 | 177.703 | 58.124 | 421.499 | 271.999 | 0.018656 | 0.021614 |
| 1003 | 241.556 | 85.995 | 515.112 | 657.228 | 0.119492 | 0.128382 |

- 全局阶段三对都更快，中位数从 241.556 秒降到 82.153 秒。总时间中位数从 515.112 秒降到 352.048 秒；seed 1003 的局部搜索单次涨到 412 秒，总时间反而更长。IGD+ 三对都变差，中位数从 0.088336 升到 0.110007，约差 24.5%，超过 10% 的保留线。
- 结论：隔代注入能减少全局 RRT 时间，但前沿变差。该改动没有留在默认行为里，全局注入仍是每代严格种线。
- 状态：有效。

## 2026-10-29 标准搜索与 PILOT 的等时间多场景对照

- 实验名：routing-mode-equal-time-20261029。
- 目的：在相近墙钟时间下比较 `standard` 与默认 `pilot_reference`，覆盖直线可通、短距挡障和长距紧档距。
- 入口：当次临时脚本，直接调用 `routing_search`。场景为已准备的苍南、永嘉和楠溪江 1 m 网格。
- 关键配置：种群 48，搜索种子 11，张量演化与张量评价，设备 CPU。塔基半径 3 m，转角 90°。每组先让 PILOT 接近 40 秒，再把标准模式的代数调到相近时间。档距和端点按场景设定，直线障碍比例按建筑与水体采样。
- 输出：`/tmp/routing_scenarios.json`。
- 主要结果：苍南 500 m 档距、直线无建筑水体时，两边都到 2 塔；标准模式多压过 27 对 7。苍南 160 m 档距、直线 55% 穿过建筑或水体，时间同为约 94 秒，标准模式的最少塔数、长度、转角和跨越都更好，压过 125 对 24。永嘉 180 m 档距、直线 94% 穿过建筑或水体，标准模式时间更长（131 秒对 78 秒），四个目标的最小值仍更好，压过 292 对 23。楠溪江 200 m 档距、两端相距 4213 m、下界 21 塔，PILOT 约 49 秒只完成 1 代，最少 23 塔、跨越约 40 m；标准模式约 28 秒、114 代，最少 27 塔、跨越约 344 m，PILOT 压过 40 对 1。
- 结论：短距场景里参考线已经够用，PILOT 每代的全局规划减少了外层代数，等时间下标准模式更好。长距紧档距时，A*/RRT 初始化给出标准变异在同样时间内碰不到的低跨越走廊。一次端点和一个搜索种子，不是全局最优。
- 注意：计时取 `routing_search` 全程，包含当时逐条复核后重算前沿的最终复核，未按 `markdown/ALGORITHMS_MODULE_SUMMARY.md` 只计搜索时间。复核耗时随评价次数增长，对评价更多的一方不利。
- 状态：有效。

## 2026-10-29 选线默认参数第一次校准

- 实验名：routing-tuning-20261029。
- 目的：按 `markdown/ALGORITHMS_MODULE_SUMMARY.md`「选线默认参数校准」，找一套在六类场景都还不错的默认参数。
- 入口：`experiments/tune_routing.py`，manifest 为 `experiments/manifests/routing_tuning.json`。
- 关键配置：每次运行 60 秒搜索时间，CPU，张量演化与张量评价。24 个进程并行，每个进程 1 个数值线程。调参集每类 2 组端点 × 种子 11、12；复验集每类 2 组新端点 × 种子 21、22、23。
- 输出：`outputs/routing_tuning/stage1-tuning`、`stage2-tuning`、`stage1-holdout`，各含 `plan.json`、`runs.jsonl` 与 `summary.json`。
- 主要结果：第一轮调参集上，当前完整 PILOT 的最差倍数最小，为 1.83；去掉局部或全局搜索的三套在 2.36–2.56，PILOT 初始化接标准演化为 3.54，标准模式为 7.18。第二轮以完整 PILOT 为基准逐个改参数，基准仍最好，为 1.43；扩展间隔 8 代为 1.62，变异步长 0.4 为 1.72，扩展间隔 16 代为 1.91，种群 96 为 2.06，变异步长 0.1 为 2.11，种群 24 为 7.55。调参集上的胜者就是现行默认，按落地规则不改 `config/default_config.json`。复验集上排名反过来：标准模式最差倍数 2.28，PILOT 初始化接标准演化 2.70，完整 PILOT 4.19。完整 PILOT 的最差项在短距直线可通场景，平均 IGD+ 0.031，而标准模式只有 0.008。长距紧档距场景则相反，完整 PILOT 为 0.083，标准模式为 0.166。
- 结论：每类只有 2 组端点，最差倍数在调参集与复验集之间不稳定。短距直线可通场景的 IGD+ 本身只有 0.01–0.03，倍数会把很小的绝对差距放大成 4 倍，这一项主导了排序，下限 1e-3 偏小。长场景的单代成本是另一个限制：楠溪江 4–6 km 上，单进程初始化 13–28 秒，加上评价器准备约 5.5 秒，第一代又要 20–45 秒，60 秒内常常一代都跑不完。默认参数保持不变。之后的第二次校准改了口径，见下一条。
- 相关提交：未提交。
- 状态：有效。

## 2026-10-29 选线默认参数第二次校准

- 实验名：routing-tuning-v2-20261029。
- 目的：用户在第一次校准后改了口径：倍数下限从 1e-3 提到 0.02，每类端点从 2 组加到 4 组。按新口径重做两轮调参和复验。
- 入口：`experiments/tune_routing.py`，manifest 为 `experiments/manifests/routing_tuning.json`（`ratio_floor` 为 0.02）。
- 关键配置：每次运行 60 秒搜索时间，CPU，张量演化与张量评价。48 个进程并行，每个进程 1 个数值线程。调参集每类 4 组端点 × 种子 11、12；复验集每类 4 组新端点 × 种子 21、22、23。
- 输出：`outputs/routing_tuning/v2-stage1-tuning`、`v2-stage2-tuning`、`v2-holdout-final`。
- 主要结果：第一轮完整 PILOT 最差倍数 1.58，局部搜索每 9 代一次的那套 1.59，PILOT 初始化接标准演化 1.75，去掉局部与全局搜索 2.03，去掉全局搜索 2.16，标准模式 2.31。第二轮以完整 PILOT 为基准：变异步长 0.4 为 1.30，扩展间隔 8 代 1.35，基准 1.37，扩展间隔 16 代 1.44，种群 96 为 1.47，变异步长 0.1 为 1.79，种群 24 为 1.98。复验集只比胜者与现行默认：变异步长 0.4 为 1.44，现行默认为 2.05。差距主要在中距离，平均 IGD+ 0.186 对 0.402；长距紧档距上现行默认更好，0.079 对 0.122。60 秒内完成代数的中位数：短距直线可通 70–95 代，短距绕障与水体 36–42 代，中距离 3–7 代，长距 0–3 代；复验集的长距端点几乎都在 60 秒内一代未完成。
- 收敛补测：用调参集端点（每类 4 组 × 种子 11、12），以新默认参数一次跑到短距 200 代、中距离 120 代，按逐代评价条数截出前沿，与同端点所有截点的并集前沿比 IGD+。参考前沿主要来自最后几代，数值对后期截点有利。入口为临时脚本，未入库。平均 IGD+ 依次为第 10、20、40、80、120、200 代：短距直线可通 0.019、0.014、0.009、0.007、0.005、0.004；短距水体 0.029、0.022、0.016、0.012、0.010、0.009；短距绕障 0.121、0.098、0.085、0.067、0.055、0.042；中距离 0.306、0.234、0.189、0.123、0.106（只跑到 120 代）。32 个进程并行时，第 40 代的中位耗时是短距直线可通 30 秒、绕障 69 秒、中距离 113 秒，比按 60 秒代数推算的短。
- 结论：过了替换门槛，`mutation_scale` 从 0.2 改为 0.4。`max_generations` 先按短距绕障场景 60 秒的中位数从 683 改为 40；收敛补测显示短距直线可通和水体在 40 代已基本收敛，绕障和中距离在 40 代后仍明显改进，用户定为 80 代。实测 80 代时短场景约 1–2 分钟，中距离约 3 分钟，长距更久，长场景的单代成本需要另行加速。选线、PILOT 与配置测试 359 项通过。端点每类 4 组，结论仍有采样噪声，不是全局最优。
- 相关提交：未提交。
- 状态：有效。

## 2026-10-29 最终复核整批化

- 实验名：routing-archive-batch-validation-20261029。
- 目的：最终 CPU 复核原先每复核一条前沿线路就对全部候选重新提取一次前沿，剖析显示它占总耗时 40%–50%。改为整批复核后重新提取一次，检查发布结果是否不变、耗时降多少。
- 入口：当次临时脚本，在同一进程里分别用旧、新复核函数跑同一组搜索，直接调用 `routing_search`。
- 关键配置：苍南 160 m 档距、直线约 55% 穿过建筑或水体的端点对。种群 48，种子 11，张量演化与张量评价，设备 CPU。PILOT 10 代，标准模式 400 代。
- 输出：只有终端输出，不保存文件。
- 主要结果：两种模式的前沿索引、塔位和目标值逐位一致（PILOT 243 条，标准模式 142 条）。复核耗时 PILOT 从 8.21 秒降到 0.35 秒，标准模式从 7.52 秒降到 0.26 秒。总耗时 PILOT 从 23.8 秒降到 15.5 秒，标准模式从 19.2 秒降到 10.6 秒。选线与 PILOT 测试 322 项通过。
- 相关提交：未提交。
- 状态：有效。

## 2026-10-29 选线只发布合并相似线路后的前沿

- 实验名：routing-front-merge-20261029。
- 目的：网页任务 `routing-1793276773227` 把 254,525 条已评价候选连同逐塔高程全部写进 `routes.json`（723 MB，写出 350 秒），而精确前沿只有 306 条，其中很多几乎相同。按 `markdown/ALGORITHMS_MODULE_SUMMARY.md`「发布前沿」改为只发布前沿，并合并塔数相同、每座塔位都在 10 m 以内的相似线路，检查发布数量、目标覆盖和写出耗时。
- 入口：离线合并检查直接对上述任务的前沿调用 `algorithms.routing.archive.merge_similar_front`；端到端用 `experiments.launch_routing_run` 跑同一任务配置。
- 关键配置：苍南场景、该网页任务的端点与工程参数，PILOT 默认机制，种群 48，种子 123，张量演化与张量评价，CPU 单数值线程；端到端为 40 代。`front_merge_distance_m` 为 10。
- 输出：`/tmp/rprof/out/g40-t1/`，临时目录，不作为正式产物保留。
- 主要结果：上述网页任务的 306 条前沿合并后剩 85 条，塔数 6–12 每档都有保留；新增塔数、总转角和跨越长度的最小值不变，三维长度最小值从 1265.38 m 变为 1265.55 m。端到端 40 代：去重候选 15,464 条，精确前沿 148 条，发布 52 条；写出从约 18.2 秒降到 0.09 秒，`routes.json` 为 135 KB。同一配置下 PyTorch 96 线程与 1 线程的搜索时间分别为 37.9 秒和 39.0 秒，线程数不影响速度。选线输出、提示词与记忆相关测试 159 项通过；全仓仅 `tests/test_base_constraint_cache.py` 中依赖文件时间戳的缓存测试偶发失败，在未改动的 `origin/master` 上同样失败。
- 相关提交：见本条所在提交。
- 状态：有效。

## 2026-10-29 选线净距表每个问题只算一次

- 实验名：routing-clearance-once-20261029。
- 目的：Codex 在小场景上看到 PILOT 混合初始化有大量重复候选，建议优先消除。按调参用的六类场景（种群 48）实测，重复候选每次最多花 0.3 秒，不是瓶颈。真正固定的开销是整幅净距表：一次中距离搜索里，张量评价器、CPU 编译评价器、PILOT 初始化的塔位投影、张量演化的投影打分和邻域半径各对同一掩膜做一次 9000×9000 距离变换，每次约 4.7 秒。用户决定把两张净距表放进 `RoutingProblem` 只算一次，并随基础栅格一起缓存，`context_cache_mib` 从 1024 提到 1536。
- 入口：临时脚本，未入库。分时统计包装 `hybrid.py` 中的 A*、RRT、重采样与 `distance_transform_edt`；前后对照用 `git stash` 在同一提交上分别运行。
- 关键配置：调参集 mid 与 long-tight 各两组端点（楠溪江 9000×9000，无缺高程），默认参数，种子 11，3 代，CPU，张量演化与张量评价，单数值线程，4 个进程并行。
- 输出：`/tmp/before.json`、`/tmp/after.json`，临时文件，不作为正式产物保留。
- 主要结果：四组的帕累托塔位、目标值和评价次数改动前后逐项相同。构建选线问题从约 9.9 秒变为约 14.8 秒（多算一次净距表），搜索从 39.9–49.1 秒降到 14.7–24.0 秒，合计每次省约 20 秒（例如 51.2 → 31.5 秒，59.0 → 38.6 秒）。改前的初始化分时：中长距离进入混合初始化前约 11 秒，混合初始化 7–28 秒，其中净距表 4.8 秒、A* 1.5–15 秒、RRT 多数不到 1 秒、重采样与修复合计不到 0.5 秒。选线、PILOT、配置、助手与发布相关测试 469 项通过，新增净距表与直接并集距离变换逐位相同的测试。
- 相关提交：见本条所在提交。
- 状态：有效。

## 2026-10-29 PILOT A* 改为 numba 编译搜索

- 实验名：routing-astar-numba-20261029。
- 目的：上一条之后，中长距离初始化里 A* 是最大的可变开销。用户决定用 numba 重写搜索循环，算法与排序不变、要求逐位一致，有人工多边形时保留 Python 搜索。
- 入口：临时脚本，未入库。cProfile 拆分 A* 内部耗时；前后对照用 `git stash` 在同一提交上分别运行。
- 关键配置：调参集 mid 第 0、1 组，long-tight 第 0、1、3 组，long-wide 第 1 组；默认参数，种子 11，3 代，CPU，张量演化与张量评价，单数值线程，6 个进程并行。
- 输出：`/tmp/astar_before.json`、`/tmp/astar_after.json`，临时文件，不作为正式产物保留。
- 主要结果：cProfile 下 long-tight 第 3 组的走廊 A*（20、40、60 m 三个尺度）约 30 秒，第一代全局注入的非走廊 20 m A* 约 50 秒；展开约 2.2 万节点、检查约 200 万条边，时间几乎都花在逐边的 `np.linalg.norm`、格心坐标与档距回调上。逐位核对发现 `np.linalg.norm` 经 OpenBLAS 按 FMA 链舍入：普通平方和在 20 万对三维距离里有 49 处末位不同，FMA 链全部一致，numba 的 `contract` 选项复现了它。六组端点改前后帕累托塔位、目标值和评价次数逐项相同；3 代搜索时间：mid 16.4 → 12.5 秒、14.5 → 11.0 秒，long-tight 23.8 → 10.0 秒、19.5 → 10.1 秒、76.1 → 36.1 秒，long-wide 47.3 → 10.5 秒。long-tight 第 3 组剩余耗时主要在 RRT 等其他环节。选线相关测试 471 项通过，新增编译与 Python 两条 A* 路径的逐位对照测试。
- 限制：逐位一致在本机 OpenBLAS（Haswell 内核，带 FMA）上验证；换到 numpy 不用 FMA 的机器，旧 Python 搜索本身的末位舍入就会不同。
- 相关提交：见本条所在提交。
- 状态：有效。

## 2026-10-30 PILOT 种群规模与耗时瓶颈

- 实验名：routing-popsize-scaling-20261030。
- 目的：用户计划增大种群，并希望靠 GPU 并行让耗时不随种群明显增长。测量各阶段耗时随种群的变化，找出不能并行的部分。
- 入口：临时脚本，未入库。读取 `execution["timings"]`，并包装 `EvaluationBudget.evaluate_tensors/evaluate_many` 统计各来源的调用次数与批量。
- 关键配置：调参集 mid 第 0 组与 long-tight 第 0 组；默认参数（PILOT 全机制），种子 11，6 代，种群 48、96、192、384；CPU（单数值线程、8 进程并行）与 `cuda:0`（RTX 4090，串行）各一遍，张量演化与张量评价。
- 输出：`/tmp/popscale_cpu.jsonl`、`/tmp/popscale_gpu.jsonl`，临时文件，不作为正式产物保留。
- 主要结果：总耗时在 CPU 与 GPU 上都约与种群成正比，GPU 不比 CPU 快。long-tight 种群 48 到 384：CPU 16.5 → 112.2 秒，GPU 19.8 → 110.6 秒。GPU 上精英局部搜索从 11.7 秒增至 89.9 秒，占总时长约 80%，比 CPU（5.2 → 38.4 秒）还慢一倍；子代变异修复在 GPU 上基本不随种群变（2.1 → 2.9 秒），CPU 上从 1.9 增至 19.2 秒；排序选择不到 0.2 秒；全局注入 3 到 12 秒；初始化 0.6 到 5.5 秒。种群 384 的 GPU 运行中，局部搜索评价 8656 次全部是单条一批，耗时 58.5 秒；子代评价 29574 条分 493 批，耗时 4.9 秒；全局注入新种子在 CPU 上生成，张量评价平均每批 5.7 条。原因是 `tensor_local_search.refine_population` 逐个精英调用 `vns`，每次只有一条车道，而 `vns` 本身支持多条路线并行。
- 结论：增大种群时首要瓶颈是逐精英串行的局部搜索，其次是全局注入的 CPU 新种子生成。子代生成、评价与排序已经能随 GPU 批量扩展。
- 补注：其他用户的训练任务自 2026-10-29 23:58 起占用两张 GPU（利用率约 90%），本条 GPU 数字是在该负载下测得的，只能作定性参考；CPU 数字不受影响。
- 相关提交：见本条所在提交。
- 状态：有效。

## 2026-10-30 精英局部搜索改为平分额度并行

- 实验名：routing-local-batch-20261030。
- 目的：按上一条结论，用户决定把张量驱动的精英局部搜索改为全部精英并行一次跑 VNS、事先平分额度（口径见 `markdown/PILOT_ROUTING_MIGRATION.md`「张量驱动的精英局部搜索」）。结果不再与旧实现逐位相同，按 60 秒复验门槛确认质量后才保留。
- 入口：`experiments/tune_routing.py`，临时 manifest 只含一个不覆盖任何字段的候选（当前默认），在复验集上分别用旧提交 `f3e49d6`（临时 git 工作树）与新代码运行，合并后用同一参考前沿打分；速度用上一条的临时脚本重跑。
- 关键配置：复验集 6 类 × 端点 100–103 × 种子 21–23，每次 60 秒，CPU，倍数下限 0.02；两边各 40 进程同时运行。速度对照同上一条（mid 第 0 组、long-tight 第 0 组，6 代，种群 48–384）。
- 输出：`/tmp/lb_sequential/`、`/tmp/lb_batched/`、`/tmp/popscale_cpu_batched.jsonl`，临时文件，不作为正式产物保留。
- 主要结果：复验集最差倍数新实现 1.074、旧实现 1.107；平均 IGD+ 新/旧为 mid 0.627/0.696，long-tight 0.051/0.054，long-wide 0.075/0.069，short-detour 0.051/0.053，short-water 0.016/0.019，short-clear 0.009/0.009。60 秒内完成代数的中位数新/旧：short-clear 112.5/72.5，short-detour 68/34.5，short-water 79.5/39，mid 50/30，long-tight 23/18，long-wide 33/24。CPU 种群 384 的 6 代运行：long-tight 局部搜索 38.4 → 11.8 秒、总计 112.2 → 75.6 秒；mid 局部搜索 36.3 → 9.9 秒、总计 105.4 → 81.1 秒。GPU 对照受其他用户任务干扰，未作结论。选线相关测试 473 项通过，替换旧的逐精英额度测试，新增 VNS 车道额度不互借的测试。
- 结论：通过复验门槛，作为默认实现保留。默认 80 代的耗时随之缩短；是否按新速度重定代数另议。
- 相关提交：见本条所在提交。
- 状态：有效。

## 2026-10-30 全局注入的耗时拆分与新种子来源

- 实验名：routing-global-split-20261030。
- 目的：判断全局注入的 CPU 新种子生成是否随种群增长，以及新种子有多少进入种群，作为是否张量化的依据。
- 入口：临时脚本 `/tmp/global_split.py`（包装 `rrt_seed`、`metric_astar`、`sample_route` 与评价计时）和 `/tmp/global_sources.py`（读取 `new_survivor_sources`、`global_sources`），未入库。
- 关键配置：当前默认参数，CPU 张量演化与张量评价，单线程，seed 11。耗时拆分用调参集 short-detour、mid、long-tight 各第 0、1 组端点，6 代，种群 48 与 384。来源统计用调参集六类各 4 组端点，种群 96，短距 40 代、中距离 20 代、长距 10 代。
- 输出：`/tmp/global_split.jsonl`、`/tmp/global_sources.jsonl`，临时文件。
- 主要结果：每次全局注入的新种子数为 `max(global_min_new, ceil(popsize × global_fraction)) // 2`，其中 RRT 条数为 `min(新种子数, max(rrt_seed_min, min(rrt_seed_max, 新种子数 // rrt_population_divisor)))`，其余由重采样填充。默认参数下种群 48、96 每代全部 4、7 条都是 RRT，没有填充；种群 384 每代 10 条 RRT、19 条填充；种群超过约 570 后 RRT 才从 10 条增长，封顶 18 条。6 代合计，种群 48 → 384：新种子生成 0.2–4.7 → 0.7–9.1 秒，其中 RRT 0.15–4.6 → 0.4–8.5 秒，重采样修复 0.03–0.09 → 0.25–0.54 秒，CPU 评价不超过 0.17 秒，A* 锚线约 0.05 秒（缓存后只算一次）。全局阶段其余时间是前沿父代的张量子代，1.0–2.0 → 2.6–4.9 秒。来源统计中，进入种群的新个体里 RRT 种子占 1–9%（每组 4–43 个），RRT 种子存活率约 7–19%；其余主要是普通子代（offspring_encoding），全局阶段的前沿子代也记在这一来源里，未与普通子代分开。
- 结论（续见下一条）：RRT 条数有上下限，种群 96 到约 570 每代固定 10 条，所以 CPU 新种子生成是每代的固定开销，不随种群线性增长；随种群增长的只有填充（每代约 0.1 秒）和已经张量化的前沿子代。全局注入的整体效果有既有证据：第二次校准第一轮去掉全局搜索最差倍数 2.16 对完整 PILOT 1.58，P10 等评价消融三工况中位数都略差，隔代注入 IGD+ 差 24.5%；但这些都是整体移除，没有分开 RRT 种子和前沿子代两部分，也都在本轮加速之前测得。
- 相关提交：见本条所在提交。
- 状态：有效。

## 2026-10-30 PILOT RRT 改为 numba 编译

- 实验名：routing-rrt-numba-20261030。
- 目的：上一条之后，用户决定先用 numba 编译 `rrt_seed` 的 RRT，要求结果逐位相同，只提速（口径见 `markdown/PILOT_ROUTING_MIGRATION.md` A* 与 RRT 两段）。
- 入口：临时脚本 `/tmp/rrt_same.py`（整次搜索对照）、`/tmp/global_split.py`（全局阶段拆分），未入库。旧代码用提交 `5dabcc3` 的临时 git 工作树运行。
- 关键配置：调参集六类各 4 组端点，seed 11，6 代，种群 48 与 384，CPU 张量演化与张量评价，单线程；新旧各 48 次同时运行，numba 缓存预热后的第二次计时。拆分对照沿用上一条的 12 次运行。
- 输出：`/tmp/rrt_old.json`、`/tmp/rrt_new.json`、`/tmp/global_split_new.jsonl`，临时文件。
- 主要结果：48 次整次搜索的帕累托塔位、目标值和评价次数与旧代码逐项相同。RRT 本身快 30–40 倍：mid 第 0 组种群 384 由 8.48 秒降到 0.21 秒，种群 48 由 4.55 秒降到 0.11 秒；新种子生成合计由 0.2–9.1 秒降到 0.05–0.74 秒，剩余主要是重采样填充。全局阶段中位数（种群 384）：long-tight 8.82 → 5.70 秒，mid 6.03 → 4.41 秒，short-detour 3.90 → 3.20 秒；剩余时间主要是前沿父代的张量子代。初始化中位数下降 0.1–0.8 秒。整次 6 代总时间的变化在并行运行噪声内（例如 long-tight 种群 384 为 102.7 → 95.4 秒），因为 CPU 上评价本身占大头。
- 发现：二维 `np.linalg.norm` 与一维 `@` 的舍入是 `fma(y, y, x * x)`，A* 一条里用的 `fastmath={"contract"}` 在二维时让 LLVM 选了另一种融合顺序，20 万组随机向量中约 11% 末位不同；三维恰好一致。改为显式调用 LLVM `fma` 后二维、三维与点积在 20 万组中全部一致。A* 走廊模式只把二维长度与最大档距比较，上述 48 次整次搜索在改前后结果相同。
- 测试：全量 1062 项通过、6 项跳过；唯一失败的 `test_base_constraint_cache.py::test_farmland_buffer_follows_the_file_and_not_the_exclusion` 在改动前的提交上同样失败，与本次无关。新增编译与 Python 两条 RRT 路径在走廊与严格模式下的逐位对照，比较路径、两条随机流的最终状态、节点与延伸检查次数和迭代计数。
- 限制：与 A* 相同，逐位一致在本机 OpenBLAS（带 FMA）上验证。
- 相关提交：见本条所在提交。
- 状态：有效。

## 2026-10-30 PILOT 种群规模的 GPU 耗时复测

- 实验名：routing-popscale-gpu-20261030。
- 目的：GPU 空闲后，复测精英局部搜索并行化与 RRT 编译之后，种群增大时 GPU 上的总耗时，判断能否用大种群换质量而不显著加时。
- 入口：临时脚本 `/tmp/popscale_gpu.py`（逐个种群顺序运行）和 `/tmp/prof_archive.py`（cProfile），未入库。
- 关键配置：调参集 mid 第 0 组用 `cuda:0`、long-tight 第 0 组用 `cuda:1`，两路各一个进程同时运行，其他用户无 GPU 负载；当前默认参数，6 代，seed 11，CPU 部分单线程；种群 48、96、192、384、768、1536、3072，先跑一次种群 48 预热编译缓存。
- 输出：`/tmp/pg_mid.jsonl`、`/tmp/pg_long.jsonl`、`/tmp/prof_archive.out`，临时文件。
- 主要结果：种群 48 → 3072（64 倍），总时间 mid 10.1 → 105.7 秒、long-tight 9.8 → 105.8 秒，评价次数 5261 → 274343。拆开看：演化主循环（排序、子代、局部搜索、全局注入合计）mid 6.9 → 25.0 秒、long-tight 7.3 → 30.7 秒，只涨 3.5–4.2 倍；初始化 0.3–0.4 → 27.6–38.8 秒，近似线性；未计入阶段计时的最终归档 2.0–2.7 → 36.1–52.9 秒，近似线性。显存峰值 1.1 → 1.3 GiB。cProfile（mid 种群 1536）：初始化 23.4 秒中 22.2 秒在 CPU 混合填充的 `sample_route`，主要是 Python 逐格 `project`（19.4 万次、约 213 万次立塔判断）；归档 22.1 秒中 20.2 秒是 `_pareto_indices`，CPU 复核每轮都对全部约 14 万条记录用纯 Python 重求一次前沿，共 23 轮。
- 结论：GPU 上演化主循环已经接近「种群大、时间涨得少」的预期；限制大种群的是两段 CPU 串行代码：初始化填充的逐格投影，以及最终归档反复的全记录前沿提取。两者都与种群成正比，不改变它们，种群 3072 的总时间有约 70% 在这两段。本条只测时间，未比较大种群的求解质量。
- 相关提交：见本条所在提交。
- 状态：有效。

## 2026-10-30 初始化投影编译与归档前沿数组化

- 实验名：routing-projection-archive-20261030。
- 目的：按上一条结论，用户决定先把初始化填充的 CPU 投影和最终归档的前沿提取改成结果逐位相同的快速实现，再做等时间质量对照（口径见 `markdown/PILOT_ROUTING_MIGRATION.md` 投影一段与 `markdown/ALGORITHM_COMMON.md` 的 `feasible_front_indices`）。
- 入口：临时脚本 `/tmp/rrt_same.py`（新旧整次搜索对照，增加节点与延伸检查数比较）与 `/tmp/popscale_gpu.py`，未入库。旧代码用提交 `95ecbbb` 的临时 git 工作树运行。
- 关键配置：逐位对照同 RRT 一条（调参集六类各 4 组端点，种群 48 与 384，CPU，6 代）。GPU 复测同上一条（mid 第 0 组 `cuda:0`、long-tight 第 0 组 `cuda:1`，6 代）。复测中 mid 种群 192、384 与 long-tight 种群 768 的演化时间是其他点的 3 倍左右，当时其他用户占着两张卡的进程在间歇运行；这三个点各重跑两次，两次一致，表中取重跑值。
- 输出：`/tmp/rrt_old.json`、`/tmp/rrt_new.json`、`/tmp/pg2_*.jsonl`、`/tmp/pg3_*.jsonl`，临时文件。
- 主要结果：48 次整次搜索的帕累托塔位、目标值、评价次数、节点检查数和延伸检查数与旧代码逐项相同。GPU 总时间（种群 48、96、192、384、768、1536、3072）：mid 10.0、14.0、17.1、21.2、29.3、35.5、55.2 秒；long-tight 9.5、11.5、14.8、22.4、34.5、44.1、67.4 秒。种群 3072 由 105.7、105.8 秒降到 55.2、67.4 秒，1536 由 54.2、61.5 秒降到 35.5、44.1 秒。种群 3072 时初始化由 27.6、38.8 秒降到 12.2、17.1 秒，归档等未计入阶段的时间由 52.9、36.1 秒降到 20.0、21.5 秒，演化主循环仍为 22.9、28.6 秒。种群放大 64 倍，总时间约增 5.5–7 倍。全量测试 1064 项通过、6 项跳过，唯一失败项与 RRT 一条所记相同，与本次无关；新增编译与 Python 两条投影路径的逐位与计数对照。
- 结论：初始化和归档仍随种群线性增长，但在种群 3072 时合计已降到总时间的一半左右。本条只测时间，下一步按用户决定做 GPU 等时间质量对照。
- 相关提交：见本条所在提交。
- 状态：有效。

## 2026-10-30 大种群 GPU 等时间对照

- 实验名：routing-popsize-gpu-20261030。
- 目的：按 `markdown/ALGORITHMS_MODULE_SUMMARY.md`「大种群 GPU 等时间对照」，判断 GPU 上增大种群能否在相同时间内提高质量。
- 入口：`experiments/tune_routing.py --devices cuda:0,cuda:1 --workers 2`，manifest 为 `experiments/manifests/routing_popsize_gpu.json`，阶段 `popsize`，复验集；干扰拆分用临时脚本 `/tmp/popsize_analyze.py`。
- 关键配置：每次 120 秒搜索时间，张量演化与张量评价，每张卡同一时刻一个进程；复验集六类 × 4 组端点 × 3 个种子，种群 48、384、1536、3072，共 288 次，2026-10-30 03:37 到 08:29。
- 输出：`outputs/routing_tuning/popsize-gpu-holdout/`（`plan.json`、`runs.jsonl`、`summary.json`）。
- 干扰：其他用户的两个 GPU 进程自 05:28 起占满两张卡（各约 3.3 GiB、利用率约 99%）。按每个进程累计墙钟推算，前 110 次在此之前完成，覆盖 short-clear、short-detour 全部 4 组端点与 short-water 第 100 组；其余 178 次（short-water 其余端点、mid、long-tight、long-wide）都在争用下运行。争用对单代 GPU 计算多的大种群更不利。
- 主要结果：全部运行无一缺可行解。全部 288 次的最差倍数：种群 3072 为 1.235，1536 为 1.262，384 为 1.332，48 为 4.823。平均 IGD+（48 / 384 / 1536 / 3072）：mid 0.410 / 0.069 / 0.070 / 0.086，long-tight 0.209 / 0.081 / 0.107 / 0.089，long-wide 0.087 / 0.053 / 0.035 / 0.048，short-detour 0.078 / 0.035 / 0.024 / 0.030，short-water 0.024 / 0.006 / 0.004 / 0.005，short-clear 0.010 / 0.004 / 0.003 / 0.003。只用干扰前完成的 9 组端点重新打分：1536 为 1.078，3072 为 1.133，384 为 1.246，48 为 2.226。120 秒内完成代数中位数（48 / 384 / 1536 / 3072）：long-tight 25.5 / 10.5 / 4.5 / 3.5，mid 39 / 24.5 / 21 / 10，short-detour 97.5 / 62.5 / 31.5 / 15，short-clear 60 / 55.5 / 47.5 / 19。
- 结论：GPU 上种群 48 明显吃亏，最差倍数约为其余三档的 4 倍，mid 与 long-tight 的平均 IGD+ 是 384 档的 2.5–6 倍。384、1536、3072 三档之间差距在 1.08–1.33 倍以内；干扰前的短距场景里 1536 最好，3072 次之。长距场景下大种群 120 秒只跑 3–5 代，且结果受争用影响，1536 与 3072 是否优于 384 尚不能下结论，需在 GPU 空闲时重跑 mid 与两类长距。按协议本条不改 `config/default_config.json`。
- 相关提交：见本条所在提交。
- 状态：有效。

## 2026-10-30 未推送提交审查与远程融合验收

- 实验名：pre-push-review-20261030-a2fba2f。
- 目的：审查 `a2fba2f` 及之前尚未推送的 110 个提交，融合远程更新，修复可复现缺陷后验证整体代码。
- 版本：审查前备份分支 `backup/pre-review-20261030-a2fba2f`；远程新增 `4e072e4`、`ccf65e0`，合并提交 `1dae228` 保留双方历史，不重写已有提交。
- 入口：`conda run -n torch311 pytest -q --durations=10 --junitxml=/tmp/pre-push-review-final.xml`；`PYTHONPATH=.:masking_pipeline conda run -n torch311 pytest -q masking_pipeline/tests`；`npm --prefix frontend run test:problem-snapshot`、`test:routing`、`build`。
- 配置：Python 仅用 torch311；数值线程为 1，MKL 使用 SEQUENTIAL；宿主机两张 RTX 4090，实际执行单 CUDA 和同步双卡测试。前端 Node.js 20.20.2；本次构建通过，但不替代文档要求的 Node.js 22 环境验收。
- 输出：`outputs/validation/pre-push-review-20261030-a2fba2f/pytest-final.xml`、`summary.json`，包含审查版本、代码内容摘要、测试结果与未覆盖范围；本机产物不入 Git。
- 修复：hybrid CPU 种子完整评分保持在 compiled CPU 上下文内，初始化窗口按 seed 目标计；第 0 代扩群只作用于完整 PILOT hybrid，保留旧初始化模式；区分 CPU seed 与扩群后重复槽位，补记扩群耗时。基础退距与永农缓冲缓存加入已加载数组的内容摘要，修复同尺寸同 mtime 改写后误用旧掩膜。两份前端适配器测试改用独立合成数据，不依赖被忽略的历史实验目录。
- 合并：两个文本冲突均人工处理。保留远程 20 km 上限、收藏只读交互、动态地图留白，同时保留本地选线图层、点选隔离和固定真北朝上；同步修正收藏说明中的旧入口和缓存、初始化文档。
- 主要结果：首次完整回归 1068 passed、6 skipped、1 failed，唯一失败为上述缓存失效，已在沙箱内外复现。最终完整回归 1071 passed、6 skipped、0 failed，用时 93.76 秒；分割流水线 18 passed；前端通用测试、选线测试和生产构建全部通过。新增回归先失败后通过，覆盖 CPU 评分边界、旧模式不扩群、CPU/CUDA 扩群及重复槽位一致性、保持原 mtime 的缓存更新。文档代码路径核对无断链，未推送增量中未发现常见私钥或访问令牌格式。
- 验证边界：6 个跳过项为 2 份缺失的历史场景/参考产物，以及 4 个要求隔离 PostgreSQL 的用例。本次未重做浏览器验收、PostgreSQL 故障演练或多 seed 质量/耗时矩阵；测试通过不证明初始化策略在所有场景的质量不退化。沙箱内 TestClient 停住及 NVIDIA 不可用均通过沙箱外复跑排除，不作为代码失败。
- 维护：同步建模、算法迁移、测试策略、前端规格和代码地图；助手能力未新增，远程收藏/场景能力提示随合并保留。未发现应删除的过期项目产物；两个未跟踪原始压缩文件保持，不加入提交。
- 相关提交：合并 `1dae228`；修复、对应权威文档和本记录在本条所在提交中一并保存。
- 状态：有效。

## 2026-10-30 PILOT 张量初始化 48 条 CPU seed 与第 0 代设备扩群对照

- 实验名：routing-init-seed-cap-compare-20261030。
- 目的：验证 tensor/hybrid 初始化改动（CPU 只做 `min(popsize, 48)` 条 A*/RRT/fill seed，第 0 代入口用张量变异批量扩到 `popsize`）在真实场景 CUDA 下的正确性、初始化提速和等代数前沿质量变化；同时审查实现并修正诊断口径。
- 入口：临时脚本 `/tmp/pilot-compare/compare.py`（逐档种群顺序运行并记录诊断与前沿），未入库；旧代码用提交 `ad73a75` 的临时 git 工作树 `/tmp/pilot-before` 运行。
- 关键配置：场景 `cangnan-utm-v2`，起终点与任务 `routing-1793330618079` 相同，两版共用同一份独立场景快照；seed 123，6 代，`cuda:0`，张量演化与张量评价，当前默认参数；种群 384、1536、3072，先跑一次种群 384 预热。质量比较以两版合并前沿为参考前沿。
- 输出：`outputs/pilot-init-cap-compare/`（`task.json`、`rows-before.json`、`rows-after.json`、`fronts-before.npz`、`fronts-after.npz`）。
- 主要结果：初始化时间 0.67 / 6.90 / 18.03 → 0.32 / 0.32 / 0.32 秒（种群 3072 约 56 倍）；fill 尝试 2155 / 25534 / 58630 → 36；初始化评价 398 / 1635 / 3241 → 55。6 代总时间 10.9 / 22.9 / 41.2 → 10.9 / 19.0 / 26.4 秒；6 代总评价数 34734 / 132908 / 247155 → 40004 / 165341 / 342719（+15%～38%，扩群候选含各变异操作中间评价）。扩群后初代唯一条数 151 / 376 / 679（名义 384 / 1536 / 3072），由 `initial_unique_population` 记录。6 代 IGD+（种群 384 / 1536 / 3072）：0.0082 → 0.0451、0.0104 → 0.0077、0.0072 → 0.0044；epsilon 同向（种群 384 0.088 → 0.165，1536 持平，3072 0.111 → 0.054）。同 seed 两次改后运行（含诊断修复后）全部算法数字逐项相同。审查中发现 `initial_gpu_expansion_reuses` 原实现可为负，已修正为与 `evaluated_offspring_reuses` 同口径；修复前后算法结果逐项相同。
- 结论：实现正确，初始化不再随种群增长；本样本下种群 1536、3072 的 6 代质量不差且略好，种群 384 略差。单 seed 单 case、6 代样本，质量结论只作参考，不作统计证明；如需定论按 `routing_popsize_gpu.json` 的完整矩阵重跑。
- 相关提交：见本条所在提交。
- 状态：有效。

## 2026-10-30 选线默认配置改为种群 1536、24 代

- 实验名：routing-default-popsize-1536-gen24-20261030。
- 目的：把「一分钟左右出结果」口径下质量最优的种群与代数定为 `config/default_config.json` 的 `routing` 段默认值，替换原种群 48、80 代。
- 入口：临时脚本（候选配置对比与设备复测，未入库）；分阶段剖析脚本 `/tmp/pilot-compare/profile_stages.py`。
- 关键配置：场景 `cangnan-utm-v2`，起终点与任务 `routing-1793330618079` 相同，同一份独立场景快照；seed 123，张量演化与张量评价；候选 A 为种群 1536 × 24 代，候选 B 为种群 3072 × 12 代；两版合并前沿作参考。
- 主要结果：候选 A 总时间 58.8 秒、IGD+ 0.0016、帕累托 1097 条；候选 B 总时间 46.7 秒、IGD+ 0.0044、帕累托 852 条、epsilon 更小（0.048 对 0.142）。按覆盖口径选 A。设备复测：同一配置 `devices=["cpu"]` 60.1 秒、`cuda:0` 58.8 秒，均满足一分钟口径，故 `devices` 默认值不改。分阶段剖析（种群 384→12288）：初始化恒定 0.03 秒，时间增长来自评价（占约一半）、全局注入填充（新种子数 = `ceil(popsize × global_fraction)`，随种群线性）和子代生成修复三个模块；排序与精英局部搜索不是瓶颈。
- 依据补充：「大种群 GPU 等时间对照」（120 秒）中种群 1536 综合最优（干扰前重打分 1.078，优于 3072 的 1.133）。
- 变更：`routing.popsize` 48 → 1536，`routing.max_generations` 80 → 24；`max_evaluations` 保留，仍是旧任务换算代数的兼容字段，不决定停止。助手提示与插件表单默认值经 `load_default_config()` 动态读取，无需另改。
- 边界：一分钟口径对短距场景成立；长距 mid 约 2–3 分钟、long-tight 约 10 分钟（每代成本随塔数与障碍上升）。质量结论基于单 seed 单 case 候选对比加既有 120 秒对照，非全矩阵证明。
- 相关提交：见本条所在提交。
- 状态：有效。

## 2026-10-30 大场景分割 OOM 修复与批量推理

- 实验名：masking-segment-smooth-tiling-batch-20261030。
- 目的：20 km 场景（卫星图 34906×34906）在 segment 阶段 GPU OOM；定位根因并修复，保证结果不变，同时压低显存与分割时间。
- 根因：`masking_pipeline/segment.py` 的 `majority_smooth()` 把整幅粗掩膜 one-hot 成 (1, 6, 34906, 34906) float32 一次性上 GPU 做 3×3 平均池化，输入加输出约 54 GiB，远超 24 GiB。滑窗推理（每窗口恒定）与 logit 融合（磁盘 memmap）均不是瓶颈。
- 改动：`majority_smooth()` 改为按 512 行分块加 halo 执行同一 one-hot + avg_pool2d + argmax，结果与原实现逐位一致（avg_pool2d 每像素独立，halo 保证窗口完整）；滑窗推理改为批量（默认 batch=4，`--infer-batch-size` 可调），数值与逐窗口路径仅有浮点末位差异。
- 入口：单元测试 `masking_pipeline/tests/test_segment_smooth.py`；端到端 `python masking_pipeline/run.py --lat 27.524 --lon 120.149 --radius-km 10.422 --target-height 18000 --target-width 18000 --output-root outputs/masking-sites --step segment --resume`。
- 主要结果：分块平滑与原实现在 CPU/CUDA 上 7 种尺寸逐位一致；34906×34906 合成掩膜平滑峰值显存 **1232 MiB**（原实现约 54 GiB，必 OOM）。批量一致性（3488×3488 实图，batch=8 对 batch=1）：94/12,166,144 像素类别不同（0.0008%）。推理 batch=4 峰值 1671 MiB；速度 48 → 38 ms/窗口（1.3×），batch≥4 后 GPU 前向（约 19 ms/窗口）饱和，再大增益小。20 km 场景端到端：**1882.5 秒（31.4 分钟）通过**，segment 阶段记录 passed；产物 fine/coarse mask 各 1162 MB，粗分类分布（1/50 抽样）山区 94.9%、field 1.7%、road 1.1%、other 1.0%、water 0.8%、building 0.5%，符合该山区场景。时间构成：滑窗推理约 13 分钟，融合取类、平滑、保存与全尺寸可视化约 18 分钟。
- 边界：批量推理的末位差异在百万分之一像素量级，不改变分类语义；未做双卡并行与可视化降采样（另一张 4090 闲置时可将推理再减半，可视化目前是收尾大头）；`masking_pipeline` 测试 22 项、主仓全量 1075 项通过。
- 相关提交：见本条所在提交。
- 状态：有效。

## 2026-10-30 行政边界只读显示图层与助手评测

- 实验名：admin-boundaries-display-v1。
- 目的：决策地图原本没有任何行政信息。从随仓库的浙江 OSM PBF 提取区县级（admin_level=6）和乡镇/街道级（admin_level=8）边界与名称，作为只读显示图层接入地图、GIS 面板和 PNG 导出；不进建模、优化或报告。永嘉等场景乡镇级缺失如实缺画，不补第三方数据。
- 入口：`masking_pipeline/extract_admin_boundaries.py`（产物 `masking_pipeline/data/regional/admin_boundaries.geojson`）；`GET /api/v1/scenes/{scene_id}/admin-boundaries`；助手评测 `experiments/agent_eval.py --cases`（图层操作 12 条子集）；浏览器走 `http://10.28.0.176:5176`。
- 关键配置：来源 `zhejiang-261020.osm.pbf`，与道路同源；外环由无序 outer ways 链接组装，内环挂洞；EPSG:3857 下按 20 m 简化；标注点用 polylabel 极点。评测模型 `deepseek-flash`，每条重复 2 次。
- 主要结果：提取 924 个 relation，建成 844 个边界（80 个省界边缘断头 relation 跳过并计数）。pytest 全量 1081 passed、6 skipped（既有前端 proj4 守卫失败已由 `759b20a` 修复）；masking 测试 26 项通过；前端构建与 mjs 单测通过。浏览器实测：苍南场景接口返回 7 个要素（区县级 4、乡镇级 2、标注点 1），「莒溪镇」标注显示，GIS 面板开关、两级图例和「非官方界线，仅供空间参考」注记齐全，显隐切换生效。助手评测 24/24：新增「关掉行政边界」「显示区县和乡镇界线」均通过；评测框架本次新增 `snapshot_layers` 用例级图层覆盖（首跑「显示」用例因快照默认开启被判为无需提案，加覆盖后通过）。
- 边界：行政界线是 OSM 社区数据，非官方勘界成果，图例与助手知识均注明仅供空间参考。PNG 导出的名称标注用 canvas 补画（底图无字体），本次未逐张核对导出图。
- 备注：本次改动的 4 个前端/后端文件（`backend/app/api/routes.py`、`frontend/src/api.ts`、`frontend/src/map/map_workspace.tsx`、`frontend/src/styles.css`）在工作区中被一并卷入 `1fcd0e1`，本条所在提交保存其余全部文件。
- 相关提交：见本条所在提交及 `1fcd0e1`。
- 状态：有效。

## 2026-10-30 行政边界与场景删除提交前复核

- 实验名：integration-review-admin-and-delete-20261030。
- 目的：复核本地新增图层与删除功能，纠正残缺行政区域和隐藏图层 PNG 导出，验证同场景并发删除互斥。
- 入口：`masking_pipeline/extract_admin_boundaries.py --output outputs/integration-review-20261030/admin_boundaries.geojson`；`masking_pipeline/tests/test_admin_boundaries.py`；`tests/test_admin_boundaries.py`、`tests/test_scene_delete.py` 和助手回归；Chromium 验收脚本 `outputs/integration-review-20261030/validate_admin_boundary_export.mjs`。
- 关键配置：同一浙江 PBF、原有 20 m 简化容差；不完整外环、内环或缺失 way/node 时整条 relation 跳过。浏览器用独立端口 15189 和合成区域，不访问真实场景或数据库。
- 输出目录：`outputs/integration-review-20261030/`，含重新生成的 GeoJSON、`admin-export.png` 和 `browser-summary.json`；通过核验的 GeoJSON 同步到 `masking_pipeline/data/regional/admin_boundaries.geojson`。
- 主要结果：924 个 relation 保留 841 个，剔除旧产物中残缺的婺源县、山阳镇和江湾镇；所有区域有效，全部标注落在对应区域内部。苍南县、永嘉县、龙港市仍在。新增测试先复现缺节点连成假边、残缺 relation 部分发布和并发删除 500，修复后 8 项边界提取单测与 42 项后端/助手定向测试通过。前端完整快照回归和生产构建通过。真实 Chromium 验证无已加载地图边界时，导出请求自己的 GeoJSON 能绘制边界及名称，图像中有 2871 个亮色像素；导出恢复隐藏状态，显隐切换正常，无地图错误或页面异常。
- 边界：本条不替代后续远程合并后的完整回归；没有运行新的模型在线评测。
- 相关提交：本条所在提交；审查基线 `1e2e1e1`。
- 状态：有效。

## 2026-10-30 远程更新合并与完整回归

- 实验名：integration-review-remote-master-20261030。
- 目的：审查并合并远程 4 个新提交，验证本地场景删除、框选建场与行政边界功能和远程的大图处理、历史案例加载、界面指标及道路通行规则。
- 入口：主仓 `conda run -n torch311 python -m pytest -q`；在 `masking_pipeline/` 运行 `conda run -n torch311 python -m unittest discover -s tests -v`；前端 `npm run test:problem-snapshot`、`npm run test:routing`、`npm run build`；浏览器脚本 `outputs/integration-review-20261030/validate_admin_boundary_export.mjs`；`experiments/agent_eval.py`。
- 关键配置：本地审查基线 `1e2e1e1`，本地修复 `ab2b8e8`，远程 `origin/master=582d8e6`；实际可见两张 RTX 4090，主仓与流水线 GPU 检查均在沙箱外执行；测试使用临时场景和数据库。保留远程的行分块实现并合并本地 CPU/CUDA、显存和不同块高回归。
- 输出目录：`outputs/integration-review-20261030/`；助手首轮 `outputs/agent_eval/integration-review-20261030/`，修正后复测 `outputs/agent_eval/integration-review-20261030-confirmed/`。
- 修复：内部 PNG 裁剪和缩图不再触发通用像素限制，也不修改 Pillow 全局状态；负分类、非整数分类和非法块高明确报错；历史案例加载一次生成已恢复表单、评价键和完整候选池，不在 React 状态更新函数里改外部引用。补齐历史导入与道路距离隐藏的前端文档，并验证类别 3 对建站和进站的不同规则，永农约束仍保持。
- 主要结果：主仓 **1087 passed、6 skipped**（93.83 s），覆盖 CPU、CUDA 与双卡；独立流水线 **33 项全部通过**，34906×34906 掩膜平滑峰值 **976 MiB**；前端快照回归、选线回归和生产构建通过；合并后再次运行 Chromium 导出检查通过，无页面和地图异常。新增 PNG、道路掩膜和删除定向回归 38 项通过。助手首轮 12/13，失败为模型连续漏填 `rationale`，后端正确拒绝提案；明确必填理由并补充道路类别与行政边界入口说明后，59 项助手回归通过，在线 13 个用例各重复两次 **26/26**，历史保存值说明正确，不可用行政图层没有提案。
- 未验证边界：2 个旧版苍南场景回归因 `scenes/cangnan` 缺失跳过；4 个 PostgreSQL 分支因未设置隔离 `TEST_JOB_DATABASE_URL` 跳过。没有把这些项目计为通过。没有重跑完整遥感模型推理、真实 Redis/PostgreSQL 故障恢复或所有历史大场景；在线模型重复通过不代表今后每次输出都确定正确，提案校验与确认流程继续保留。
- 相关提交：本条所在合并提交，父提交 `ab2b8e8` 与 `582d8e6`。
- 状态：有效。
