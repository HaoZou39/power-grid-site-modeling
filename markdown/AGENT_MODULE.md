# Agent 模块

Agent 是决策地图上的只读助手。它能查看当前编辑、场景、历史实验和插件，并提议一组编辑操作。操作在用户点确认之前不写入 `SiteEdit`，也不提交搜索。

助手默认使用简体中文回答，结论、解释、分析、建议、提案理由、确认信息、错误和反馈都以中文为主。用户用英文提问时仍默认用中文，只有明确要求英文、翻译或指定输出语言时才切换。代码、API 字段、文件路径、单位、专有名词等必要技术标识可以保留英文，但不能因此输出整段纯英文；面向用户的目标名要把内部英文字段映射为中文。该规则只约束自然语言，不改变工具调用和结构化输出。

坐标沿用地图口径：1 m 局部坐标，原点在选址范围左上角，x 向东，y 向南。`theta` 用弧度，0 表示建筑宽边朝东。

## 目录和依赖

```text
agent/                              不依赖 FastAPI
  config.py                         AgentConfig.from_env()
  workspace.py                      WorkspaceSnapshot、EditOp、Proposal、validate_ops
  tools.py                          工具注册表。只调用 ToolContext 上的函数
  llm.py                            ChatModel 与 OpenAI 兼容实现
  loop.py                           run_turn 和循环护栏
  prompts.py                        系统提示和每种操作的说明卡
  memory.py                         记忆条目、记忆文件读写、MemoryOp 校验与执行
  settings.py                       助手设置、.env 中的模型 API 配置与记忆开关锁
  analysis.py                       用快照里的目标值给方案排名，定出本次比较的目标
  preference/                       选择记录、SLFN 效用和推荐，见「偏好推荐」
memory/MEMORY.md                    本机记忆文件，不入 git
memory/AGENT_SETTINGS.json          长期记忆开关，不入 git
memory/PREFERENCE_CHOICES.jsonl     本机选择记录，不入 git
memory/PREFERENCE_DEFAULTS.json     本机默认重要程度，不入 git
experiments/agent_eval.py           对真实模型跑评测集
experiments/agent_eval_cases.json   评测用例
backend/app/application/agent_gateway.py
                                    把场景、实验目录、插件和 site report 装进 ToolContext
backend/app/api/agent_routes.py     对话、操作 schema、记忆和选择记录的路由
frontend/src/agent/                 快照、reducer、对话面板
```

`agent/` 不保存会话，也不保存编辑。每一轮请求都带上最新的 `WorkspaceSnapshot`。写入地图的唯一入口是前端 `applyOps`。跨会话保留的只有记忆文件和选择记录。记忆的唯一写入口是 `POST /api/v1/agent/memory`，见「记忆」一节；选择记录的唯一写入口是 `POST /api/v1/agent/preferences/choices`，见「偏好推荐」一节。

## 让助手跟上新功能

助手只知道三样东西：系统提示（`agent/prompts.py` 的规则、说明卡和 `UNSUPPORTED`）、工具（`agent/tools.py`），以及快照里的字段。软件新增或改动了功能，而这三样没跟着改，助手就会答错、乱拒绝，或者去凑相近的操作。所以每次改动都对照下表；已有的知识就地改，不另加一条重复的规则；没有的才新增。

| 这次改了什么 | 助手侧要同步 |
| --- | --- |
| 用户在界面上多了一种编辑（新按钮、新参数、新用地策略） | 要让助手也能做：加 `EditOp`，同时改四处——`agent/workspace.py` 的模型、`agent/prompts.py` 的说明卡、`frontend/src/agent/edit_ops.ts` 的分支、两边测试里的 op 清单。暂不让助手做：在 `UNSUPPORTED` 加一句事实，说明用户该去哪里点 |
| 原来不支持的事现在支持了 | 从 `UNSUPPORTED` 删掉对应的那句，把评测里对应的拒绝用例改成期望提案 |
| 新的只读数据或分析 | 在 `agent/tools.py` 注册，在网关加取值函数，补本文「工具」表；何时调用、怎么称呼结果写进 `prompts.py` 的通用规则。`loop.py` 和路由不用改 |
| 新增目标、改目标名或改比较口径 | `frontend/src/agent/workspace_snapshot.ts` 的 `OBJECTIVE_FIELDS`、`agent/analysis.py` 的 `RANKED_OBJECTIVES`（`label` 与方案小窗一致）和 `compared_keys`，以及本文「读：WorkspaceSnapshot」 |
| 新插件或换决策算法 | `run_search` 允许的 `plugin_id`、`UNSUPPORTED` 里的算法一句、`prompts.py` 里提到的插件名 |
| 用户可见的名称或单位改了 | 说明卡和规则里的叫法，`RANKED_OBJECTIVES` 的 `label` |
| 只改了内部实现，用户能做的事和看到的字段没变 | 不用改助手 |

改完再往 `experiments/agent_eval_cases.json` 加至少一条用例：能做的事用 `expect`，要调用工具的用 `expect_tools`，不支持的标 `unsupported`。然后跑一次评测，结果写进 `markdown/EXPERIMENT_LOG.md`。

能自动对上的部分由 `tests/test_agent_sync.py` 检查：工具表与注册表一致，前端目标键与 `RANKED_OBJECTIVES` 一致，评测用例里的工具名都存在。`tests/test_agent.py` 检查说明卡与操作种类一一对应、前后端 op 清单一致。语义上是否跟上了（新按钮有没有对应的操作或不支持说明），测试查不出，由 `.githooks/pre-commit` 在提交时提醒：改了界面、插件、建模或配置，却没碰助手相关文件时，打印本节路径，不拦截提交。启用方法：`git config core.hooksPath .githooks`。

## 读：WorkspaceSnapshot

前端 `toSnapshot` 把当前 `SiteEdit` 收成下面的 JSON。未完成的笔迹留在 `draft`，不进入快照。

```text
scene_name
site            { width_m, height_m }
building        { width_m, height_m }
policies        { mountain_policy, field_policy, field_cost }
origin          { x, y } 或 null
regions[]       { id, kind, ring }。kind 为 exclusion 或 feasible
poses[]         { id, x, y, theta, objectives?, feasible?, derived_from? }
selected_pose_id
experiment_id   当前导入的实验目录；没有则为 null
layers          当前 GIS 显示状态和资源可用性，见下文
```

`objectives` 只转写方案上已经有的数字，键为 `dem_soft`、`road_distance`、`demand_distance`、`road_haul_m`、`offroad_haul_m`、`haul_rise_m`。没有的键不补。方案被挪动或约束改了之后、重算结果回来之前，这个方案没有 `objectives` 和 `feasible`。`feasible` 来自方案表的 `is_feasible`。`derived_from` 是局部优化时原方案的 id，优化器原本给出的方案没有这一项。

`layers` 的结构为：

```text
panel_open
scene_ready
dem             { visible, opacity, available }
landuse         { field, building, road, water }，每项为 { visible, available }
osm_roads       { visible, available }
regions         { exclusion, feasible }
```

这里的状态只描述前端显示。`available` 表示当前已准备场景里是否有相应数据资源；旧客户端没传 `layers` 时后端使用“场景未准备、数据图层不可用、禁区和可行域显示”的兼容默认值。

变电站尺寸口径：
- width_m 对应用户界面的“长度”，默认 77 m。
- height_m 对应用户界面的“宽度”，默认 51.5 m。
- 该命名为内部兼容字段，不因 UI 术语变化而修改数据结构。
- Agent 必须按照上述映射理解用户的长宽指令，不能直接将 width_m 翻译为“宽度”。

## 写：EditOp

`Proposal` 是 `{ rationale, ops, memory }`。`ops` 是地图编辑，`memory` 是记忆改动（见「记忆」一节），两者至少一个非空。`ops` 里的每一项都带 `kind`：

| kind | 字段 | 确认后 |
| --- | --- | --- |
| `set_building` | `width_m`, `height_m` | 改建筑宽高。两者都必须大于 0 |
| `set_policies` | `mountain_policy?`, `field_policy?`, `field_cost?` | 至少改一项。代价系数在 0 到 1 之间，不含 0 |
| `set_origin` | `x`, `y` | 替换进货原点。点必须在选址范围内 |
| `clear_origin` | 无 | 去掉进货原点 |
| `clear_poses` | 无 | 清空当前地图上的全部方案，保留历史实验、GIS 数据和用户约束。必须是提案中唯一的地图操作，当前没有方案时无效 |
| `add_region` | `region_kind`, `ring` | 追加禁区或可行域。`ring` 至少三个 `{x, y}`，都在范围内。方框也写成 ring |
| `remove_region` | `region_id` | 按 id 删除已有范围 |
| `update_pose` | `pose_id`, `x?`, `y?`, `theta?` | 修改已有方案。至少改一项，中心仍在范围内。确认后按搜索口径重算该方案（见下文「调整方案」） |
| `select_pose` | `pose_id` | 切换当前方案 |
| `run_search` | `plugin_id` | 只接受 `site.guided_search`。先应用同一提案里的其他操作，再用得到的 `searchConfig()` 提交任务 |
| `refine_pose` | `pose_id`, `half_width_m`（30 到 400，默认 150） | 在方案周围方框里局部优化，新方案加到地图上，原方案保留。一个提案最多一个，不能和 `run_search` 同时出现 |
| `set_layer_visibility` | `layer`, `visible` | 设置 GIS 图层显隐。layer 取 `dem`、`field`、`building`、`road`、`water`、`osm_roads`、`exclusion`、`feasible` |
| `set_dem_opacity` | `opacity` | 设置 DEM 渲染透明度，范围 0 到 1，含两端 |
| `set_layer_panel_open` | `open` | 打开或关闭右侧 GIS 图层控制面板，不改变任何图层显隐状态 |

`validate_ops` 按顺序检查。id 不存在、坐标出界、ring 太短或数值不合法时直接 `ValueError`。启用 DEM、土地利用或 OSM 道路，以及设置 DEM 透明度时，场景必须准备完成且相应资源可用；隐藏数据图层和切换禁区、可行域显示不依赖资源。`half_width_m` 的界限同时写在 `agent/workspace.py` 的 `RefinePose` 和前端 `REFINE_HALF_WIDTH_M`，`tests/test_agent.py` 检查两边一致。

图层操作只影响显示：隐藏禁区不删除几何，隐藏农田不改建设策略，显示 DEM 不增加优化目标，透明度不修改 DEM 数据。`road` 是土地利用道路区域，`osm_roads` 是 OSM 道路网络。`set_layer_panel_open` 只改 `layers.panel_open`；关闭面板不等于隐藏图层，“隐藏所有图层”也不能用关闭面板代替。

### 调整方案

用户只说「调整」「优化」「再优化」「重新优化」某个方案时，模型用 `refine_pose`，不自己挑坐标，也不用 `run_search`；给了具体位移或朝向时才用 `update_pose`。`run_search` 会替换地图上的全部方案，只用于没指向某个方案的整体重跑。助手看不到卫星影像，不能据此设目标奖励，这一条写在 `UNSUPPORTED` 里。

`refine_pose` 确认后，前端用当前编辑的 `searchConfig()` 提交一次 `site.guided_search`，实验名为 `refine-<时间>`，只把 `feasible_zones` 换成方案中心周围、裁到选址范围内的方框，禁区和策略不变。挑选规则和并入方式见 `markdown/FRONTEND_IMPLEMENTATION_SPEC.md`「局部优化」。

`update_pose` 确认、拖动结束，或提案改了建筑尺寸、策略、范围、原点（且不含 `run_search`）时，受影响方案先显示「重算中」，再由 `POST /api/v1/scenes/{id}/pose-objectives` 按方案表同一口径重算目标和可行性。所以调整后的方案和优化器给的方案放在同一个快照里，排名、分析和推荐都直接可用。`run_turn` 把这个错误交回模型重试一次；再失败就返回不带提案的说明。

用户要求清空当前全部方案或地图上的全部候选站址时，模型只提出一个 `clear_poses`，不使用 `run_search`、`clear_origin` 或多条逐项删除操作。指定删除某一个方案目前不支持，不能扩大解释为清空全部方案。确认卡中的数量由前端对提案快照里的 `poses` 计数，模型不填写数量。确认前不改地图；确认后 `MapWorkspace` 调用与顶部和工作栏按钮相同的 `clearDisplayedSolutions()`，并直接结束本次应用，不触发 `markMoved()`、目标重算或搜索。优化任务正在启动、排队或运行时，确认会明确报错且不清空。

清空后，`SiteEdit.poses` 和 `selected_pose_id` 为空，同时清理方案卡、连接线、对比、推荐、报告、运输路径、预览和编辑临时状态；工作区的场景、图层、禁区、可行域、土地修正、进货原点、建筑尺寸、策略参数、助手对话和长期记忆保留。方案导入、任务结果、局部优化、重算和报告响应都受方案代次号保护，代次不匹配的旧结果不得回填。快照包含 `poses`，所以清空后依赖旧方案的待确认提案会按 `snapshotStamp` 自动过期。

工作栏「清除」和地图橡皮擦是前端对同一 `SiteEdit.clearOrigin()` 的直接入口，不增加新的 `EditOp`。助手仍使用现有 `set_origin`、`clear_origin` 及确认流程；确认 `set_origin` 后，前端会使用户此前删除原点留下的单步撤销快照失效，避免后续 `Ctrl+Z` 覆盖助手刚设置的新原点。

`GET /api/v1/agent/ops` 返回这组操作的 JSON Schema，给后续客户端对照。前端 reducer 不靠这份 schema 执行。

## 工具

| 工具 | 作用 |
| --- | --- |
| `get_workspace` | 返回本轮快照 |
| `list_scenes` | 复用 `experiments.scene_store.list_scenes` |
| `list_experiments` | 复用实验目录的已完成记录 |
| `get_experiment` | 读取一个实验的摘要和产物清单 |
| `list_plugins` | 复用插件 `describe()` |
| `evaluate_pose` | 复用 `build_site_report`。返回数字，不返回进站路径折线 |
| `analyze_pose` | 分析一个已有方案，见「方案附件与分析」 |
| `propose_changes` | 唯一会结束本轮的工具。只校验并携带提案，不改数据 |
| `recommend_poses` | 按以往的选择给当前方案排序，见「偏好推荐」 |

## 偏好推荐

推荐有两个来源，都只由用户在界面上写入，助手只读：

- 默认重要程度：助手「偏好」页给每个目标设 0 到 5，0 表示不看。第一次使用、还没有选择记录时，推荐就按它排序；有记录后，它是学习的起点。
- 选择记录：用户在方案小窗点「记为我的选择」，就记下一次选择——选中的方案，加上当时地图上所有带目标值的方案作为候选。用户在对话里说「就选它」时，助手请用户去点按钮。

两者都不分场景，所有场景共用一份，因为学的是同一位决策者的取舍。

```text
agent/preference/
  store.py       ChoiceInput、PreferenceChoice、PreferenceDefaults，两个文件的读写
  slfn.py        SlfnUtility：从选择对学效用
  recommend.py   PreferenceConfig、recommend_poses
```

一条记录是一行 JSON：

```text
scene_name      记下时的场景
experiment_id   记下时导入的实验目录，没有则为 null
chosen_id       选中的方案 id，必须在 candidates 里
candidates[]    { id, objectives }，至少两个，id 不重复。objectives 与快照同键
recorded_at     服务端写入的 ISO 8601 时间
```

选择记录文件由 `AGENT_PREFERENCE_HISTORY_PATH` 指定，默认 `memory/PREFERENCE_CHOICES.jsonl`。默认重要程度文件由 `AGENT_PREFERENCE_DEFAULTS_PATH` 指定，默认 `memory/PREFERENCE_DEFAULTS.json`，内容为 `{"weights": {目标键: 0 到 5}}`；键只能是 `RANKED_OBJECTIVES` 里的，没写的键按 1 算。`GET /api/v1/agent/preferences` 返回 `{ defaults, choice_count }`，`defaults` 没设过时为 null；`PUT /api/v1/agent/preferences/defaults` 收 `{ weights }`，校验后整份覆盖，返回同样的结构。`POST /api/v1/agent/preferences/choices` 收 `ChoiceInput`（上表去掉 `recorded_at`），校验后追加一行，返回 `{ count }`。任一文件损坏时返回 422 `preference_file_invalid`，并指出原因，不写入。没有删除接口；要删记录时手动编辑这个文件。

`recommend_poses` 工具的口径：

1. 比较的目标由 `agent.analysis.compared_keys` 给出：顺序为 `dem_soft`、`demand_distance`、`road_haul_m`、`offroad_haul_m`、`haul_rise_m`，没有进货原点时去掉 `road_haul_m`。只保留每个带目标值的方案都有的键，所以需求点距离没打开时，快照里没有这个键，也就不比较。全部最小化。地图上带目标值的方案少于两个时报错。
2. 某条记录只有在每个候选都带齐这些目标时才用上，否则跳过，并计入 `choices_skipped`。目标比本次多的记录照样能用，多出的键不看。
3. 归一化：把本次方案和用上的记录里的候选拼在一起，每个目标取最小值和极差，线性缩放到 [0, 1]，极差下限 1e-9。训练和打分用同一套缩放。
4. 效用：分数越低越好，由线性项、平方项、两两交叉项和随机 ReLU 项（单隐层网络，SLFN）组成。每次选择拆成「选中的胜过同一组里其他每个」这样的成对比较，用 logistic 损失加 L2 正则，配合 L-BFGS-B 求解。线性权重从先验 `prior` 出发，正则把它拉回先验。`prior` 是默认重要程度在本次比较的目标上的取值，再缩放到和为 1；没设默认值时为等权；全为 0 时报错。只有一次选择时，平方项的惩罚放大 16 倍。没有可用的记录时不训练，分数就是先验加权和，此时设过默认值则 `basis` 为 `defaults`，否则为 `equal_weights`；用上了记录则为 `past_choices`。
5. 多样性：按分数从低到高挑，跳过与已挑方案在归一化空间里欧氏距离小于 `min_distance` 的；不够 `top_k` 个时，再按分数补齐。

参数在 `PreferenceConfig` 和 `SlfnConfig` 里，默认值如下：

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `top_k` | 5 | 推荐个数，工具参数可覆盖，1 到 10 |
| `min_distance` | 0.08 | 多样性门槛，归一化空间的欧氏距离 |
| `n_hidden` | 16 | 随机 ReLU 特征数 |
| `lambda_delta` | 0.5 | 线性权重偏离先验的惩罚 |
| `lambda_quad` | 0.1 | 平方项和 ReLU 项的惩罚；交叉项不罚 |
| `single_choice_quad_multiplier` | 16 | 只有一次选择时平方项惩罚的倍数 |
| `delta_cap` | 2.0 | 线性权重相对先验的增量上界 |
| `max_iter` | 200 | L-BFGS-B 迭代上限 |
| `seed` | 42 | 随机 ReLU 特征的种子 |

工具返回 `basis`、`choices_used`、`choices_skipped`、`weights[]`（`{key, label, prior, weight}`：`prior` 是起点；`weight` 是学完后整个效用在当前方案上对各目标的平均斜率（数值求导，截掉负值后归一化），平方项和 ReLU 项也算在内，因为一两次选择学到的主要在这些项里。两者对比，说明选择记录改变了什么），以及 `recommendations[]`（`{rank, pose_id, index, score, objectives, strengths}`）。`index` 从 1 开始，与界面上的「方案 N」一致；`objectives` 以方案小窗上的中文目标名为键；`strengths` 是该方案在地图上排进前 25% 的目标名，按 `weight` 从大到小排，作为第 1 名的推荐理由；`better_than_first` 与 `worse_than_first` 以中文目标名为键，给出该方案比第 1 名好多少、差多少（正数，一位小数），作为其余名次的推荐理由。

回答里不写 `prior`、`weight`、`score` 的数字。`weight` 是整张图上的平均斜率，学过选择以后效用是非线性的，单个方案的名次可能和它对不上，直接给用户看反而读不懂。用户追问为什么这样排时，才用 `weights` 说哪些目标更受看重，并说明这是平均影响。

一轮对话里调用过 `recommend_poses` 时，回复 `AgentReply.recommended` 带上最后一次调用的 `pose_id`，按名次排列；没调用时为空。前端据此按名次给这些方案上色，见 `markdown/FRONTEND_IMPLEMENTATION_SPEC.md` 7.5「AI 助手」。上色只改显示，不改编辑，不需要确认。后端每轮在日志里记一行 `agent turn tools=[…] recommended=[…] proposal=…`，只有工具名、成败和 id，不记对话内容，用来排查「助手说了但地图没变」。

决策搜索的目标顺序以 `markdown/GUIDED_SEARCH.md` 为准，全部最小化。默认是 `dem_soft`、`offroad_haul_m`、`haul_rise_m`；有进货原点才比较 `road_haul_m`；侧栏打开需求点距离才比较 `demand_distance`。`road_distance` 写入方案表，不参加支配比较。快照里没有的目标键不要当成正在比较的目标。

## 说明卡

光有 JSON Schema，模型知道字段名，却不一定知道一句话该落到哪个操作、数值怎么算。`agent/prompts.py` 给每个 `EditOp` 写一张说明卡：什么时候用、数值从快照里怎么算、一个例子。系统提示由通用规则加全部说明卡拼成。测试保证说明卡和操作种类一一对应。

通用规则里写死这几条：

- 相对说法（往东挪 50 米、转 90 度、加宽 3 米）从快照当前值算出绝对值，直接提案。`evaluate_pose` 只在用户要数字时调用，不是提案前的必经步骤。
- 能改的只有说明卡里的操作。其余改动都算「目前不支持」：回复里必须写出「目前不支持」这几个字，原因和替代做法由模型用自己的话说。不许调用工具去试，不许用相近的操作凑，也不许拿默认参数的 `run_search` 顶替。
- 一句话里既有能做的又有不支持的，能做的部分照常提案，并在 `rationale` 里写明哪部分目前不支持。

`prompts.py` 的 `UNSUPPORTED` 列出已知不支持的事，每条写一句事实，拼进系统提示。它只是例子，帮模型把口径说准；不在清单里、但说明卡做不到的请求，同样按上面的规则处理，由模型自己判断。当前清单：算法参数（种群、代数、`sigma0`、种子、设备、目标权重）、水体/建筑/道路这三类用地、目标函数、选址范围和场景重建、换算法、凭空新增方案、删除单个指定方案或设置单个方案尺寸、历史结果导入和删除、由助手代为导出文件、代记选择、代设偏好、软件更新、点选同类用地。清空地图上当前显示的全部方案由 `clear_poses` 支持，但不会删除历史实验。用户可在决策地图「文件」里选择「导出全部方案 CSV/JSON」，导出当前地图工作区中的全部方案。某一项有了对应 `EditOp` 后，从清单里删掉。软件更新只能在决策地图「设置」输入 `UPDATE_PASSWORD`，助手不能代做。

## 循环护栏

`run_turn` 里，一个只读工具连续两轮都报错时，本轮后面不再把它交给模型，并在对话里加一条系统说明：直接提案，或说明做不到。`propose_changes` 不受这条限制，它仍按上面的规则只重试一次。

## 方案附件与分析

方案小窗的「问 AI」按钮打开助手，把当前方案附到输入框上，并预填「分析一下这个方案」；助手里没有附件时，输入框上方的「＋ 附上方案 N/M」也能附上当前选中方案。附件只跟着一条用户消息走：`POST /api/v1/agent/chat` 的 `messages[i].pose_id` 可选，发送后输入框上的附件标签清掉，用户气泡上留一个方案小标签。`pose_id` 不在快照的 `poses` 里时返回 422（`attached_pose_unknown`）。`run_turn` 把附件转写成该条用户消息后面的一句「（本句附上方案 3，pose_id 为 pose-3）」。方案 N 是界面序号。

`analyze_pose(pose_id)` 返回：

```text
pose          { id, index, x, y, theta, objectives }   index 从 1 开始
ranks[]       { key, label, value, rank, of, best_value, best_pose_id, best_index }
              label 与前端方案小窗同名；best_index 从 1 开始
strengths[]   名次在前 25% 的目标键
weaknesses[]  名次在后 25% 的目标键
road_distance 该方案的 road_distance，只报值，不排名；没有则为 null
footprint     footprint_terrain 的结果（见 markdown/MODELING_MODULE_SUMMARY.md）
site_report   evaluate_pose 的结果；报 ValueError 时为 { error }
```

排名只用快照里已有的 `objectives`，目标顺序和全部最小化同上；没有进货原点时不排 `road_haul_m`。名次 1 为最好，同值同名次。只有方案自己带有、且至少两个方案都有值的目标才排名。`site_report` 使用快照中的山体/农田策略、农田代价、禁区、可行域和可选进货原点，和当前地图单方案报告使用同一约束口径。它出错（例如中心格不可建）时，排名和 `footprint` 照常返回，模型在回答里说明这一项缺失。

分析规则写在系统提示里：附上方案并要求分析时，先调用 `analyze_pose`；回答按一句结论、占优项、短板及和最好方案的差距、占地用地与地形、进站情况、可以试的改动来组织，数字带单位。方案按界面序号称「方案 N」，不说 id；目标名用 `label`，不写英文字段名。附件方案是本句里「这个方案」「它」所指，改动时 `pose_id` 用附件方案，不用 `selected_pose_id`。改动仍走 `propose_changes`。

## 记忆

记忆让助手跨会话记住决策者的偏好、常用说法和场景备注。设计取自三类做法：Mem0 对照已有条目决定新增、改写还是删除（[arXiv 2504.19413](https://arxiv.org/abs/2504.19413)）；Claude Code 用一份可读的 `MEMORY.md` 整份放进上下文；持久记忆综述指出偏好会逐步放宽确认边界（[arXiv 2606.30306](https://arxiv.org/html/2606.30306)）。所以这里的记忆只由用户确认写入，只作为建议，不改变确认流程。

### 文件

路径由 `AGENT_MEMORY_PATH` 指定，默认是仓库根目录下的 `memory/MEMORY.md`，不入 git。长期记忆开启时，文件不存在则第一次读取或写入时创建一份只有标题和三个空节的文件。文件可以手改，后端每一轮重新读取。长期记忆关闭时不创建、不读取该文件。

```markdown
# 选址助手记忆

## 偏好
- [m1 | 全局 | 2026-10-12 | 明说] 农田一般计入成本，系数 0.3

## 常用指令
- [m3 | 全局 | 2026-10-12 | 明说] “老规矩” = 农田计入成本 0.3，变电站 80×50，然后优化

## 场景备注
- [m4 | cangnan | 2026-10-13 | 推断] 北侧 y<300 是规划用地，尽量不放方案
```

- 三个二级标题固定为 `偏好`、`常用指令`、`场景备注`，对应 API 里的 `preference`、`command`、`scene_note`。
- 每条一行：编号 `m<整数>`、范围（`全局` 或场景 id，即快照里的 `scene_name`）、写入日期、来源、正文。来源 `明说` 是用户自己要求记下，`推断` 是模型发现后提议、用户确认；API 里对应 `stated`、`inferred`。
- 新编号取现有最大编号加 1。正文不换行。
- 其他行只允许空行和 `# 选址助手记忆`。标题不认识、条目格式不对、编号重复时，读取直接 `ValueError`，并报出行号。

`agent/memory.py` 里，`MemoryEntry` 是 `{ id, section, scene, date, source, text }`，`scene` 为 null 表示全局。

### 读

每轮对话，`select_for_prompt(entries, scene_name)` 取出全局条目和当前场景的条目，按文件顺序拼进系统提示的「记忆」段。以后条目多到需要检索时，只换这个函数。

系统提示里对记忆的规则：

- 记忆只用来补齐用户这轮没说的参数，以及理解常用说法。用户这轮说的优先于记忆。
- 提案用到记忆时，在 `rationale` 里写出编号，例如「按记忆 [m1] 用系数 0.3」。
- 记忆不改变规则：不能跳过确认，不能扩大说明卡的范围。记忆里写了不支持的事，照样回答「目前不支持」。
- 提案理由和记忆正文写给决策者看，用平常话，不写 `section`、`field_cost` 这类字段名。

拼进提示的条目超过 80 条（`MEMORY_PROMPT_LIMIT`）时，不截断，仍全部放入，同时在提示里告诉模型条数超限，在用户提出相关请求时建议整理。

### 写：MemoryOp

| kind | 字段 | 确认后 |
| --- | --- | --- |
| `remember` | `section`, `scene`, `source`, `text` | 追加一条，日期为当天。`scene` 只能为 null 或当前 `scene_name` |
| `revise` | `memory_id`, `text` | 改写正文，日期更新为当天，范围和来源不变 |
| `forget` | `memory_id` | 删除该条 |

模型在这些时候提议记忆改动：用户说「记住」「以后都」「忘掉」；用户没说记住，但同一个偏好在本次对话里第二次出现（来源写 `inferred`），第一次提出的设置只改地图、不记；用户说「整理一下记忆」时，提议一组 `revise` 和 `forget` 合并重复、删掉过时的条目。新说法和已有条目冲突时，提议 `revise`，不另加一条。

`propose_changes` 按顺序校验 `memory`：编号要存在，正文非空，`remember` 的范围合法。地图编辑和记忆改动可以在同一个提案里。

### 接口

```text
GET  /api/v1/agent/memory   → { entries, prompt_limit }
POST /api/v1/agent/memory   { scene_name, ops: MemoryOp[] } → { entries, prompt_limit }
```

POST 读当前文件，按顺序执行，整体成功才写回（先写临时文件再替换）。`scene_name` 用来检查 `remember` 的范围。编号已不存在等错误返回 422（`memory_op_invalid`），文件不变。记忆文件格式不对时，两个接口和对话都返回 422（`memory_file_invalid`），并带出行号。确认提案和「记忆」页的删除按钮都走这个接口。

长期记忆开关默认开启，状态写在 `memory/AGENT_SETTINGS.json`。关闭操作在同一把跨线程、跨进程文件锁内先持久化 `memory_enabled=false`，再删除 `MEMORY.md`；只清文字记忆，不清 `PREFERENCE_CHOICES.jsonl` 和 `PREFERENCE_DEFAULTS.json`。关闭后四层同时生效：系统提示不带记忆段和记忆规则，`propose_changes` 的模型 schema 不含 `memory`，记忆接口不读文件且 POST 返回 409 `memory_disabled`，前端中止正在流式返回的旧请求并在确认前再次检查开关。已经在途的后端回复也会在返回前再次检查，关闭后移除混合提案里的记忆改动，纯记忆提案直接丢弃。纯记忆请求固定回复「长期记忆未开启」；同一句还有地图编辑时仍可生成地图提案，但不保存记忆。

设置接口为：

```text
GET /api/v1/agent/settings
  → { memory_enabled, base_url, model, api_key_configured }
PUT /api/v1/agent/settings
  action=update_model | enable_memory | disable_memory_and_clear
```

GET 返回当前生效的 `base_url`、`model`、`api_key_configured`、`config_source`，以及这三个字段能否由界面修改；永不返回 API Key。PUT 的三种操作不需要管理员密码。`update_model` 只改模型配置，`enable_memory` 和 `disable_memory_and_clear` 只改长期记忆。关闭记忆必须由前端二次确认。记忆开关和锁位于 `AGENT_SETTINGS_DIR`（默认 `memory/`），可用 `AGENT_SETTINGS_PATH` 覆盖。模型 API 只写仓库根目录 `.env`（可用 `AGENT_ENV_FILE` 覆盖）里的 `AGENT_BASE_URL`、`AGENT_MODEL`、`AGENT_API_KEY`，保留其余行、注释和权限；写入使用文件锁和临时文件替换。若仍存在旧的 `memory/AGENT_MODEL_CONFIG.json`，首次读取时把其中未被进程环境锁住的字段迁入 `.env`，核对写入成功后再删除该文件；被锁住的字段留在原文件里。Docker 给 API 挂载 `../memory:/app/memory`，本地 Compose 再把仓库 `.env` 挂进 API，frontend 和 worker 不接触这些文件。

## 评测

```bash
conda run -n torch311 python experiments/agent_eval.py --name <实验名> [--model <模型名>] [--repeats N]
```

`experiments/agent_eval_cases.json` 里有一份基础快照和一组用例。每条用例是 `{id, ask, expect, unsupported?}`：`expect` 为操作列表时，要求提案的操作个数、顺序和种类一致；用例里写了的字段要相等，没写的字段必须为空。数值容差 0.01，`ring` 按点集合比较，不管起点和方向。`expect` 为 `null` 时，要求不出提案。`unsupported` 为真时，回复或提案理由里还要出现「目前不支持」。不支持类用例既有清单里的，也有清单外的，用来检查模型的泛化。

方案附件类用例可写 `attach`（这条用户消息的 `pose_id`）和 `expect_tools`（本轮必须成功调用过的工具名列表）。

记忆类用例另有三个可选字段。`memory` 是预置的条目列表（`MemoryEntry` 的 JSON），没有则为空记忆；`memory_enabled` 默认 true，false 用于检查关闭状态；`snapshot_scene` 覆盖快照的 `scene_name`，用来检查别的场景的条目不生效。`expect_memory` 是记忆改动列表：种类和顺序要一致，写了的 `section`、`scene`、`source`、`memory_id` 要相等，`text_has` 里的每个片段都要出现在正文里。没写 `expect_memory` 时，要求提案不带记忆改动。

脚本复用 `.env` 里的地址和密钥，`--model` 只替换模型名。工具上下文走 `live_tool_context`，和线上对话是同一套工具。输出写到 `outputs/agent_eval/<实验名>/`：

```text
results.tsv         每次调用一行：case_id, repeat, passed, reason, ops, memory, tools, message, seconds
eval_summary.json   模型名、用例文件、总通过数和每条用例的通过次数
```

文件名不用 `run_summary.json`，所以评测不会出现在「导入案例」里。评测要调用外部模型，不放进 pytest。打分函数本身有 pytest。

## 配置

模型配置的初始来源是环境变量：

```text
AGENT_BASE_URL    OpenAI 兼容地址，含 /v1 前缀，例如 https://api.openai.com/v1
AGENT_MODEL       模型名
AGENT_API_KEY     密钥
```

「设置 → AI 助手设置」保存的模型配置写回 `.env` 的上述三项。每一轮新的 `POST /api/v1/agent/chat` 都重新读取这份文件，已经开始的请求继续使用开始时的 `AgentConfig`。设置页显示并保存 `.env` 里的 `AGENT_BASE_URL`。本地 Docker 的对话仍发到本机中继 `http://host.docker.internal:18080/v1`，中继每次转发前重新读取 `.env`，所以保存后的上游地址在下一次请求生效。其它和 `.env` 不一致的进程环境变量仍以进程环境为准，界面标成外部环境变量并拒绝修改。两边一致，或该项只写在 `.env` 时，以文件为准。API Key 不回显，输入新值即替换，留空则保留文件中的原值，不会回退到进程里旧的副本。缺任何有效项时返回 503，`code` 为 `agent_not_configured`。不猜测地址，也不改用别的模型。进程启动时，若环境变量还没设置，仍会把 `.env` 里其余未设置的变量读进环境，供 `UPDATE_PASSWORD` 等使用；模型三项不靠这次启动注入冒充后续更新。

可选：`AGENT_MAX_TOOL_ROUNDS`（默认 6）、`AGENT_TIMEOUT_S`（默认 60）。不是数字时直接报错。`AGENT_MEMORY_PATH`（默认 `memory/MEMORY.md`）指定记忆文件；记忆和设置接口不需要模型配置。

密钥只留在 `.env` 或确实注入的进程环境里。不回传前端、不写日志、不提交 `.env` 或 `memory/`。API Base URL 必须是 HTTPS；HTTP 只允许 loopback 和既有的 `host.docker.internal`。地址不得包含凭据、查询或 fragment，也不得解析到非 loopback 的私网、链路本地、保留或组播地址。本地 Docker 经中继转发时，上游地址只检查是否为 HTTPS，由宿主机解析，因此可以保存只在校园网 DNS 中的地址。模型名为 1 到 128 个非空白、非控制字符。模型 HTTP 客户端不跟随重定向，降低服务端请求伪造和密钥转发风险。

模型调用是 `POST {AGENT_BASE_URL}/chat/completions`，`stream` 为真，密钥放在 `Authorization` 头。`POST /api/v1/agent/chat` 把正文增量按一行一个 JSON 转给页面：`{"type":"delta","text"}`，结束时 `{"type":"done","reply"}`。`reply` 仍是原来的 `AgentReply`。思考过程不往外传。上游中途失败时同一条流里返回 `{"type":"error","message"}`，响应里不带回密钥。配置缺失仍是请求开始前的 503。

## 前端确认

对话记录只留在浏览器里。面板展示提案理由和 `describeOps` 的差异。地图用虚线画出提案里新增或改动的范围、位姿和进货原点。

确认时先把 `memory` 发给 `POST /api/v1/agent/memory`，成功后再调用 `applyOps`。记忆写入失败时报错，地图也不改。含 `run_search` 时接着走现有的优化提交，含 `refine_pose` 时提交局部优化。`clear_poses` 的无副作用预览只生成确认说明；确认后由 `MapWorkspace` 调用统一清空流程并立即结束，不另建 Agent 执行 API。图层操作在 `applyOps` 预览阶段只生成无副作用的 `layerChanges`，确认后才由 `MapWorkspace` 用绝对值更新现有 React 图层状态。普通图层显隐或透明度操作沿用原行为，自动展开图层面板；提案含 `set_layer_panel_open` 时按其最终绝对值打开或关闭面板。纯图层或面板操作不重算候选方案、不搜索也不局部优化。拒绝则丢弃提案，面板和图层状态都不变。地图上的方框预览也画出 `refine_pose` 的搜索范围。提案生成后如果地图或图层快照变了，提案标为过期，不能确认。提案卡片在地图差异之后列出记忆改动，例如「将记下：…」「将忘掉 [m2]」。

助手窗口保留「对话」和「偏好」两页，不再直接展示或删除文字记忆。长期记忆与模型 API 配置统一在顶部「设置 → AI 助手设置」管理。助手回复使用 GitHub Flavored Markdown 渲染，用户输入仍按纯文本显示；链接只允许 HTTP、HTTPS、mailto 和相对地址，新窗口打开并带 `noopener noreferrer`，代码块和表格在气泡内横向滚动。

## 这次不实现的扩展

- 新的写操作，例如改用地分类或算法参数：按上面的四处一起加。
- 多个角色：换 `prompts.py`，并按角色挑选工具子集。快照和 `EditOp` 不变。
- 记忆检索：条目到几百条时，把 `select_for_prompt` 换成关键词或语义取前若干条。文件格式不变。
- 多个决策者：按人拆记忆文件，前端选择当前是谁。
- 一次附多个方案做对比：`pose_id` 改成列表，`analyze_pose` 不变，逐个调用。
