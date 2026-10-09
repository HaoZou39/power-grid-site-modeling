# v0 软件框架

## 目标

v0.1 只验证软件骨架和插件边界。浏览器通过 FastAPI 提交一个任务，Worker 从队列领取任务，插件执行后将状态和结果写回数据库，前端查询并展示结果。

本版本使用 deterministic demo plugin，不接入真实 DEM、landuse、道路、需求点和正式算法。

## 目录边界

```text
frontend/       React + TypeScript 页面和 API client
backend/app/    FastAPI、领域协议、用例和基础设施适配器
worker/         后台任务执行入口
plugins/        显式注册的内置插件
data_tools/     后续数据插件的实现位置
modeling/       后续目标、约束和指标实现位置
algorithms/     后续算法实现位置
deploy/         Docker Compose 部署文件
```

API 层不读取算法代码，Worker 不处理 HTTP，插件不读取数据库。跨层数据通过明确的 Python 类型和 JSON schema 传输。

## 任务流

1. `POST /api/v1/jobs` 校验插件 ID 和配置。
2. API 创建 `queued` 任务并将 `job_id` 放入任务队列。
3. Worker 领取任务，更新为 `running`。
4. 插件通过 reporter 写入进度、阶段和消息。
5. 插件返回结构化结果，Worker 将任务更新为 `succeeded`；异常则更新为 `failed`。
6. 前端通过 `GET /api/v1/jobs/{job_id}` 查询状态，通过 `/result` 查询结果。

开发测试默认使用 SQLite 和内存队列，API 在同一进程启动内置 Worker。Docker Compose 使用 PostgreSQL、Redis 和独立 Worker，具体适配由 Repository 和 TaskQueue 接口隔离。

## 插件协议

每个插件提供：

- 稳定的 `id` 和 `version`
- `describe()` 返回名称、类型、说明和配置 schema
- `validate_config()` 校验配置
- `run()` 执行任务并返回 `PluginResult`

插件通过显式注册表发现。新增插件只需实现协议并在组合根注册，不修改任务服务、API 路由或前端任务页面。

后续插件类型包括：

- `DataTool`：生成统一 1 m 局部栅格和数据 manifest
- `AlgorithmPlugin`：执行优化算法
- `ObjectivePlugin`：计算 soft objective
- `ConstraintPlugin`：计算 hard feasibility 和约束
- `MetricPlugin`：生成后验指标

## v0.1 API

- `GET /api/v1/health`
- `GET /api/v1/plugins`
- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/result`

任务状态为 `queued`、`running`、`succeeded`、`failed`。正式身份认证、数据集版本管理、任务取消、图件存储和真实算法接入在后续增量中实现。
