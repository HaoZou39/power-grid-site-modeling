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
