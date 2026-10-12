# Agent 模块

Agent 是决策地图上的只读助手。它能查看当前编辑、场景、历史实验和插件，并提议一组编辑操作。操作在用户点确认之前不写入 `SiteEdit`，也不提交搜索。

坐标沿用地图口径：1 m 局部坐标，原点在选址范围左上角，x 向东，y 向南。`theta` 用弧度，0 表示建筑宽边朝东。

## 目录和依赖

```text
agent/                              不依赖 FastAPI，不读 tif/csv/GeoJSON
  config.py                         AgentConfig.from_env()
  workspace.py                      WorkspaceSnapshot、EditOp、Proposal、validate_ops
  tools.py                          工具注册表。只调用 ToolContext 上的函数
  llm.py                            ChatModel 与 OpenAI 兼容实现
  loop.py                           run_turn 和循环护栏
  prompts.py                        系统提示和每种操作的说明卡
  memory.py                         记忆条目、记忆文件读写、MemoryOp 校验与执行
memory/MEMORY.md                    本机记忆文件，不入 git
experiments/agent_eval.py           对真实模型跑评测集
experiments/agent_eval_cases.json   评测用例
backend/app/application/agent_gateway.py
                                    把场景、实验目录、插件和 site report 装进 ToolContext
backend/app/api/agent_routes.py     POST /api/v1/agent/chat，GET /api/v1/agent/ops
frontend/src/agent/                 快照、reducer、对话面板
```

`agent/` 不保存会话，也不保存编辑。每一轮请求都带上最新的 `WorkspaceSnapshot`。写入地图的唯一入口是前端 `applyOps`。跨会话保留的只有记忆文件，写入它的唯一入口是 `POST /api/v1/agent/memory`，见「记忆」一节。

新增只读工具时只改 `agent/tools.py` 的注册表，以及网关里对应的取值函数。`loop.py` 和路由不用改。

新增一种写操作要同时改四处：`agent/workspace.py` 的模型、`agent/prompts.py` 的说明卡、`frontend/src/agent/edit_ops.ts` 的分支、两边测试里的 op 清单。再往 `experiments/agent_eval_cases.json` 加至少一条用例。

## 读：WorkspaceSnapshot

前端 `toSnapshot` 把当前 `SiteEdit` 收成下面的 JSON。未完成的笔迹留在 `draft`，不进入快照。

```text
scene_name
site            { width_m, height_m }
building        { width_m, height_m }
policies        { mountain_policy, field_policy, field_cost }
origin          { x, y } 或 null
regions[]       { id, kind, ring }。kind 为 exclusion 或 feasible
poses[]         { id, x, y, theta, objectives? }
selected_pose_id
experiment_id   当前导入的实验目录；没有则为 null
```

`objectives` 只转写方案上已经有的数字，键为 `dem_soft`、`road_distance`、`demand_distance`、`road_haul_m`、`offroad_haul_m`、`haul_rise_m`。没有的键不补。

## 写：EditOp

`Proposal` 是 `{ rationale, ops, memory }`。`ops` 是地图编辑，`memory` 是记忆改动（见「记忆」一节），两者至少一个非空。`ops` 里的每一项都带 `kind`：

| kind | 字段 | 确认后 |
| --- | --- | --- |
| `set_building` | `width_m`, `height_m` | 改建筑宽高。两者都必须大于 0 |
| `set_policies` | `mountain_policy?`, `field_policy?`, `field_cost?` | 至少改一项。代价系数在 0 到 1 之间，不含 0 |
| `set_origin` | `x`, `y` | 替换进货原点。点必须在选址范围内 |
| `clear_origin` | 无 | 去掉进货原点 |
| `add_region` | `region_kind`, `ring` | 追加禁区或可行域。`ring` 至少三个 `{x, y}`，都在范围内。方框也写成 ring |
| `remove_region` | `region_id` | 按 id 删除已有范围 |
| `update_pose` | `pose_id`, `x?`, `y?`, `theta?` | 修改已有方案。至少改一项，中心仍在范围内。确认后沿现有 site report 刷新该方案 |
| `select_pose` | `pose_id` | 切换当前方案 |
| `run_search` | `plugin_id` | 只接受 `site.nsga2`。先应用同一提案里的其他操作，再用得到的 `searchConfig()` 提交任务 |

`validate_ops` 按顺序检查。id 不存在、坐标出界、ring 太短或数值不合法时直接 `ValueError`。`run_turn` 把这个错误交回模型重试一次；再失败就返回不带提案的说明。

`GET /api/v1/agent/ops` 返回这组操作的 JSON Schema，给后续客户端对照。前端 reducer 不靠这份 schema 执行。

## 工具

| 工具 | 作用 |
| --- | --- |
| `get_workspace` | 返回本轮快照 |
| `list_scenes` | 复用 `experiments.scene_store.list_scenes` |
| `list_experiments` | 复用实验目录的已完成记录 |
| `get_experiment` | 读取一个实验的摘要和产物清单 |
| `list_plugins` | 复用插件 `describe()` |
| `evaluate_pose` | 复用 `build_site_report`。返回数字，不返回进场折线 |
| `analyze_pose` | 分析一个已有方案，见「方案附件与分析」 |
| `propose_changes` | 唯一会结束本轮的工具。只校验并携带提案，不改数据 |

决策搜索的目标顺序以 `markdown/NSGA2.md` 为准，全部最小化。默认是 `dem_soft`、`offroad_haul_m`、`haul_rise_m`；有进货原点才比较 `road_haul_m`；侧栏打开需求点距离才比较 `demand_distance`。`road_distance` 写入方案表，不参加支配比较。快照里没有的目标键不要当成正在比较的目标。

## 说明卡

光有 JSON Schema，模型知道字段名，却不一定知道一句话该落到哪个操作、数值怎么算。`agent/prompts.py` 给每个 `EditOp` 写一张说明卡：什么时候用、数值从快照里怎么算、一个例子。系统提示由通用规则加全部说明卡拼成。测试保证说明卡和操作种类一一对应。

通用规则里写死这几条：

- 相对说法（往东挪 50 米、转 90 度、加宽 3 米）从快照当前值算出绝对值，直接提案。`evaluate_pose` 只在用户要数字时调用，不是提案前的必经步骤。
- 能改的只有说明卡里的操作。其余改动都算「目前不支持」：回复里必须写出「目前不支持」这几个字，原因和替代做法由模型用自己的话说。不许调用工具去试，不许用相近的操作凑，也不许拿默认参数的 `run_search` 顶替。
- 一句话里既有能做的又有不支持的，能做的部分照常提案，并在 `rationale` 里写明哪部分目前不支持。

`prompts.py` 的 `UNSUPPORTED` 列出已知不支持的事，每条写一句事实，拼进系统提示。它只是例子，帮模型把口径说准；不在清单里、但说明卡做不到的请求，同样按上面的规则处理，由模型自己判断。当前清单：算法参数（种群、代数、`sigma0`、种子、设备、目标权重）、水体/建筑/道路这三类用地、目标函数、选址范围和场景重建、换算法、新增方案或单个方案的尺寸、历史结果和导出文件、点选同类用地。某一项有了对应 `EditOp` 后，从清单里删掉。

## 循环护栏

`run_turn` 里，一个只读工具连续两轮都报错时，本轮后面不再把它交给模型，并在对话里加一条系统说明：直接提案，或说明做不到。`propose_changes` 不受这条限制，它仍按上面的规则只重试一次。

## 方案附件与分析

方案小窗的「问 AI」按钮打开助手，把当前方案附到输入框上，并预填「分析一下这个方案」；助手里没有附件时，输入框上方的「＋ 附上方案 N/M」也能附上当前选中方案。附件只跟着一条用户消息走：`POST /api/v1/agent/chat` 的 `messages[i].pose_id` 可选，发送后输入框上的附件标签清掉，用户气泡上留一个方案小标签。`pose_id` 不在快照的 `poses` 里时返回 422（`attached_pose_unknown`）。`run_turn` 把附件转写成该条用户消息后面的一句「（本句附上方案 pose-3，即 poses 第 3 个）」。

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

排名只用快照里已有的 `objectives`，目标顺序和全部最小化同上；没有进货原点时不排 `road_haul_m`。名次 1 为最好，同值同名次。只有方案自己带有、且至少两个方案都有值的目标才排名。`site_report` 出错（例如中心格不可建）时，排名和 `footprint` 照常返回，模型在回答里说明这一项缺失。

分析规则写在系统提示里：附上方案并要求分析时，先调用 `analyze_pose`；回答按一句结论、占优项、短板及和最好方案的差距、占地用地与地形、进场情况、可以试的改动来组织，数字带单位。方案按界面序号称「方案 N」，不说 id；目标名用 `label`，不写英文字段名。附件方案是本句里「这个方案」「它」所指，改动时 `pose_id` 用附件方案，不用 `selected_pose_id`。改动仍走 `propose_changes`。

## 记忆

记忆让助手跨会话记住决策者的偏好、常用说法和场景备注。设计取自三类做法：Mem0 对照已有条目决定新增、改写还是删除（[arXiv 2504.19413](https://arxiv.org/abs/2504.19413)）；Claude Code 用一份可读的 `MEMORY.md` 整份放进上下文；持久记忆综述指出偏好会逐步放宽确认边界（[arXiv 2606.30306](https://arxiv.org/html/2606.30306)）。所以这里的记忆只由用户确认写入，只作为建议，不改变确认流程。

### 文件

路径由 `AGENT_MEMORY_PATH` 指定，默认是仓库根目录下的 `memory/MEMORY.md`，不入 git。文件不存在时，第一次读取（打开「记忆」页或发出一轮对话）就创建一份只有标题和三个空节的文件。文件可以手改，后端每一轮重新读取。

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

拼进提示的条目超过 80 条（`MEMORY_PROMPT_LIMIT`）时，不截断，仍全部放入，同时在提示里告诉模型条数超限，在用户提出相关请求时建议整理；「记忆」页也显示超限提醒。

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

## 评测

```bash
conda run -n torch311 python experiments/agent_eval.py --name <实验名> [--model <模型名>] [--repeats N]
```

`experiments/agent_eval_cases.json` 里有一份基础快照和一组用例。每条用例是 `{id, ask, expect, unsupported?}`：`expect` 为操作列表时，要求提案的操作个数、顺序和种类一致；用例里写了的字段要相等，没写的字段必须为空。数值容差 0.01，`ring` 按点集合比较，不管起点和方向。`expect` 为 `null` 时，要求不出提案。`unsupported` 为真时，回复或提案理由里还要出现「目前不支持」。不支持类用例既有清单里的，也有清单外的，用来检查模型的泛化。

方案附件类用例可写 `attach`（这条用户消息的 `pose_id`）和 `expect_tools`（本轮必须成功调用过的工具名列表）。

记忆类用例另有两个可选字段。`memory` 是预置的条目列表（`MemoryEntry` 的 JSON），没有则为空记忆；`snapshot_scene` 覆盖快照的 `scene_name`，用来检查别的场景的条目不生效。`expect_memory` 是记忆改动列表：种类和顺序要一致，写了的 `section`、`scene`、`source`、`memory_id` 要相等，`text_has` 里的每个片段都要出现在正文里。没写 `expect_memory` 时，要求提案不带记忆改动。

脚本复用 `.env` 里的地址和密钥，`--model` 只替换模型名。工具上下文走 `live_tool_context`，和线上对话是同一套工具。输出写到 `outputs/agent_eval/<实验名>/`：

```text
results.tsv         每次调用一行：case_id, repeat, passed, reason, ops, memory, tools, message, seconds
eval_summary.json   模型名、用例文件、总通过数和每条用例的通过次数
```

文件名不用 `run_summary.json`，所以评测不会出现在「导入案例」里。评测要调用外部模型，不放进 pytest。打分函数本身有 pytest。

## 配置

`AgentConfig.from_env()` 读取：

```text
AGENT_BASE_URL    OpenAI 兼容地址，含 /v1 前缀，例如 https://api.openai.com/v1
AGENT_MODEL       模型名
AGENT_API_KEY     密钥
```

缺任何一项时，`POST /api/v1/agent/chat` 返回 503，`code` 为 `agent_not_configured`。不猜测地址，也不改用别的模型。进程启动时，若这些变量还没设置，会读仓库根目录的 `.env`；已经在环境里的值优先。

可选：`AGENT_MAX_TOOL_ROUNDS`（默认 6）、`AGENT_TIMEOUT_S`（默认 60）。不是数字时直接报错。`AGENT_MEMORY_PATH`（默认 `memory/MEMORY.md`）指定记忆文件；记忆接口不需要模型配置。

密钥只留在后端环境变量里。不进前端，不写日志，不提交 `.env`。仓库里的 `.env.example` 只有键名。

模型调用是 `POST {AGENT_BASE_URL}/chat/completions`，`stream` 为真，密钥放在 `Authorization` 头。`POST /api/v1/agent/chat` 把正文增量按一行一个 JSON 转给页面：`{"type":"delta","text"}`，结束时 `{"type":"done","reply"}`。`reply` 仍是原来的 `AgentReply`。思考过程不往外传。上游中途失败时同一条流里返回 `{"type":"error","message"}`，响应里不带回密钥。配置缺失仍是请求开始前的 503。

## 前端确认

对话记录只留在浏览器里。面板展示提案理由和 `describeOps` 的差异。地图用虚线画出提案里新增或改动的范围、位姿和进货原点。

确认时先把 `memory` 发给 `POST /api/v1/agent/memory`，成功后再调用 `applyOps`。记忆写入失败时报错，地图也不改。含 `run_search` 时接着走现有的优化提交。拒绝则丢弃提案。提案生成后如果地图快照变了，提案标为过期，不能确认。提案卡片在地图差异之后列出记忆改动，例如「将记下：…」「将忘掉 [m2]」。

助手窗口顶部分「对话」和「记忆」两页。「记忆」页按三节列出全部条目，标出范围和来源，每条有删除按钮。每次打开这一页都重新读取，手改文件后不用刷新页面；读取失败的提示只显示在这一页。当前场景可见条数超过 `prompt_limit` 时显示提醒，建议在对话里说「整理一下记忆」。

## 这次不实现的扩展

- 新的写操作，例如改用地分类或算法参数：按上面的四处一起加。
- 多个角色：换 `prompts.py`，并按角色挑选工具子集。快照和 `EditOp` 不变。
- 记忆检索：条目到几百条时，把 `select_for_prompt` 换成关键词或语义取前若干条。文件格式不变。
- 多个决策者：按人拆记忆文件，前端选择当前是谁。
- 一次附多个方案做对比：`pose_id` 改成列表，`analyze_pose` 不变，逐个调用。
