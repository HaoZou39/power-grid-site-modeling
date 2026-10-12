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
experiments/agent_eval.py           对真实模型跑评测集
experiments/agent_eval_cases.json   评测用例
backend/app/application/agent_gateway.py
                                    把场景、实验目录、插件和 site report 装进 ToolContext
backend/app/api/agent_routes.py     POST /api/v1/agent/chat，GET /api/v1/agent/ops
frontend/src/agent/                 快照、reducer、对话面板
```

`agent/` 不保存会话，也不保存编辑。每一轮请求都带上最新的 `WorkspaceSnapshot`。写入地图的唯一入口是前端 `applyOps`。

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

`Proposal` 是 `{ rationale, ops }`。`ops` 里的每一项都带 `kind`：

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
| `propose_changes` | 唯一会结束本轮的工具。只校验并携带提案，不改数据 |

决策搜索的目标顺序以 `markdown/NSGA2.md` 为准，全部最小化：`dem_soft`、`demand_distance`、`road_haul_m`（有进货原点才比较）、`offroad_haul_m`、`haul_rise_m`。`road_distance` 写入方案表，不参加支配比较。

## 说明卡

光有 JSON Schema，模型知道字段名，却不一定知道一句话该落到哪个操作、数值怎么算。`agent/prompts.py` 给每个 `EditOp` 写一张说明卡：什么时候用、数值从快照里怎么算、一个例子。系统提示由通用规则加全部说明卡拼成。测试保证说明卡和操作种类一一对应。

通用规则里写死这几条：

- 相对说法（往东挪 50 米、转 90 度、加宽 3 米）从快照当前值算出绝对值，直接提案。`evaluate_pose` 只在用户要数字时调用，不是提案前的必经步骤。
- 能改的只有说明卡里的操作。其余改动都算「目前不支持」：回复里必须写出「目前不支持」这几个字，原因和替代做法由模型用自己的话说。不许调用工具去试，不许用相近的操作凑，也不许拿默认参数的 `run_search` 顶替。
- 一句话里既有能做的又有不支持的，能做的部分照常提案，并在 `rationale` 里写明哪部分目前不支持。

`prompts.py` 的 `UNSUPPORTED` 列出已知不支持的事，每条写一句事实，拼进系统提示。它只是例子，帮模型把口径说准；不在清单里、但说明卡做不到的请求，同样按上面的规则处理，由模型自己判断。当前清单：算法参数（种群、代数、`sigma0`、种子、设备、目标权重）、水体/建筑/道路这三类用地、目标函数、选址范围和场景重建、换算法、新增方案或单个方案的尺寸、历史结果和导出文件、点选同类用地。某一项有了对应 `EditOp` 后，从清单里删掉。

## 循环护栏

`run_turn` 里，一个只读工具连续两轮都报错时，本轮后面不再把它交给模型，并在对话里加一条系统说明：直接提案，或说明做不到。`propose_changes` 不受这条限制，它仍按上面的规则只重试一次。

## 评测

```bash
conda run -n torch311 python experiments/agent_eval.py --name <实验名> [--model <模型名>] [--repeats N]
```

`experiments/agent_eval_cases.json` 里有一份基础快照和一组用例。每条用例是 `{id, ask, expect, unsupported?}`：`expect` 为操作列表时，要求提案的操作个数、顺序和种类一致；用例里写了的字段要相等，没写的字段必须为空。数值容差 0.01，`ring` 按点集合比较，不管起点和方向。`expect` 为 `null` 时，要求不出提案。`unsupported` 为真时，回复或提案理由里还要出现「目前不支持」。不支持类用例既有清单里的，也有清单外的，用来检查模型的泛化。

脚本复用 `.env` 里的地址和密钥，`--model` 只替换模型名。工具上下文走 `live_tool_context`，和线上对话是同一套工具。输出写到 `outputs/agent_eval/<实验名>/`：

```text
results.tsv         每次调用一行：case_id, repeat, passed, reason, ops, tools, seconds
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

可选：`AGENT_MAX_TOOL_ROUNDS`（默认 6）、`AGENT_TIMEOUT_S`（默认 60）。不是数字时直接报错。

密钥只留在后端环境变量里。不进前端，不写日志，不提交 `.env`。仓库里的 `.env.example` 只有键名。

模型调用是 `POST {AGENT_BASE_URL}/chat/completions`，`stream` 为真，密钥放在 `Authorization` 头。`POST /api/v1/agent/chat` 把正文增量按一行一个 JSON 转给页面：`{"type":"delta","text"}`，结束时 `{"type":"done","reply"}`。`reply` 仍是原来的 `AgentReply`。思考过程不往外传。上游中途失败时同一条流里返回 `{"type":"error","message"}`，响应里不带回密钥。配置缺失仍是请求开始前的 503。

## 前端确认

对话记录只留在浏览器里。面板展示提案理由和 `describeOps` 的差异。地图用虚线画出提案里新增或改动的范围、位姿和进货原点。

确认调用 `applyOps`。含 `run_search` 时接着走现有的优化提交。拒绝则丢弃提案。提案生成后如果地图快照变了，提案标为过期，不能确认。

## 这次不实现的扩展

- 新的写操作，例如改用地分类或算法参数：按上面的四处一起加。
- 多个角色：换 `prompts.py`，并按角色挑选工具子集。快照和 `EditOp` 不变。
