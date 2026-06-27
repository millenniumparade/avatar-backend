# Avatar Backend

这是一个面向 Unity 客户端的头像生成后端。当前真实算法仍是模拟实现：worker 会等待
`MOCK_ALGORITHM_DELAY_SECONDS`，然后返回 `examples/HumanInfo(102).json` 作为示例
结果。

## 系统组成

- FastAPI 接收图片上传请求，并返回 `job_id`。
- PostgreSQL 保存用户、上传图片、任务、生成结果和 outbox 事件。
- Redis 同时承担两类职责：
  - 作为业务准入控制层，用于单用户 active job 锁和全局任务容量计数。
  - 作为 Celery broker，用于 API、system worker 和 GPU worker 之间传递异步任务。
- GPU Celery worker 消费 `avatar_gpu` 队列，执行头像生成任务。
- system Celery worker 消费 `avatar_default` 队列，负责 outbox 派发、stale job 检查和 queued job 重新派发。
- Celery beat 定时调度系统任务，包括派发 outbox、处理超时的 `processing` job、重新派发长期停留在 `queued` 的 job。
- Alembic 根据迁移文件创建和升级 PostgreSQL 表结构。
- MinIO/S3 兼容对象存储用于保存上传图片、`HumanInfo.json` 和生成产物。

## 当前架构

```text
Unity / Client
    -> FastAPI API
        -> PostgreSQL: 用户、图片、任务、结果、outbox
        -> Redis: active job 锁、全局容量计数、Celery broker
        -> MinIO/S3: 上传图片和结果文件
    -> system-worker: outbox 派发、超时恢复、queued job 重新派发
    -> GPU worker: 头像生成任务
    -> watchdog / Celery beat: 定时调度系统任务
```

PostgreSQL 是业务事实来源。任务状态、结果、worker 抢占状态、outbox 派发状态都以
PostgreSQL 为准。Redis 是短期协调层和消息传输层，不作为最终结果存储。

## 是否需要手动创建 PostgreSQL 表

不需要。

Docker Compose 会启动一个 PostgreSQL 容器：

```text
POSTGRES_DB=avatar
POSTGRES_USER=avatar
POSTGRES_PASSWORD=avatar
```

随后 Alembic 会根据 `migrations/` 下的迁移文件创建项目表。除非正在调试数据库问题，
否则不应该手写 SQL 去注册业务表。

## 本地 Docker 运行

```powershell
docker compose up --build
```

当前 `api` 容器配置了：

```text
RUN_MIGRATIONS=1
```

因此容器启动前会执行：

```bash
alembic upgrade head
```

API 文档地址：

```text
http://localhost:8000/docs
```

## 手动执行数据库迁移

如果只想先启动数据库和 Redis，再从宿主机手动执行迁移：

```powershell
docker compose up -d postgres redis
.\.venv\Scripts\alembic.exe upgrade head
```

在 Docker 容器内部，数据库地址使用 Compose 服务名 `postgres`：

```text
DATABASE_URL=postgresql+psycopg://avatar:avatar@postgres:5432/avatar
```

如果从宿主机执行 Alembic，需要改成宿主机可访问的地址：

```powershell
$env:DATABASE_URL="postgresql+psycopg://avatar:avatar@localhost:5432/avatar"
.\.venv\Scripts\alembic.exe upgrade head
```

## 主要 API

```http
POST   /api/v1/avatar/jobs
GET    /api/v1/avatar/jobs/{job_id}
GET    /api/v1/avatar/results/{result_id}
GET    /api/v1/avatar/results
DELETE /api/v1/avatar/results/{result_id}
GET    /api/v1/users/me
```

## 并发策略

- 同一个用户或设备同一时间只能有一个 active job。active 状态包括 `queued`、`processing` 和 `retrying`。
- 单用户 active job 规则先通过 Redis `SET NX EX` 实现，key 形如 `avatar:active_job:{user_id}`。
- 全局容量会在保存图片和写数据库前检查。若 `avatar:global_active_jobs` 超过 `MAX_GLOBAL_ACTIVE_JOBS`，API 会拒绝新任务并返回稍后重试的提示。
- MVP 阶段的用户身份来自请求头 `X-Device-Id`。如果请求头缺失，则使用 `DEFAULT_USER_DEVICE_ID`。
- 不同用户可以并发提交任务，但 GPU 处理能力由 Celery worker 进程数和显存容量控制。
- worker 进程启动时通过 `preload_models()` 加载模型，后续 job 复用已加载的模型句柄。
- 不要在每个 job 内重复加载 3DMM、性别分类或人像解析模型。
- 扩容 worker 前必须确认 GPU/CPU 内存足够容纳每个 worker 进程的一份模型副本。
- 同一用户重复上传同一张图片且算法版本一致时，会复用已有 active result，避免重复重建。
- 历史结果列表依赖 PostgreSQL 的用户和结果表索引。当前产品路径是用户查询自己的历史结果，不需要 Bloom filter。

同一用户第二次上传应在第一个任务 active 时被拒绝：

```powershell
curl.exe -X POST -H "X-Device-Id: user-a" -F "image=@examples/00997A17.jpg" http://localhost:8000/api/v1/avatar/jobs
curl.exe -X POST -H "X-Device-Id: user-a" -F "image=@examples/00997A17.jpg" http://localhost:8000/api/v1/avatar/jobs
```

不同用户可以分别进入队列：

```powershell
curl.exe -X POST -H "X-Device-Id: user-a" -F "image=@examples/00997A17.jpg" http://localhost:8000/api/v1/avatar/jobs
curl.exe -X POST -H "X-Device-Id: user-b" -F "image=@examples/00997A17.jpg" http://localhost:8000/api/v1/avatar/jobs
```

## PowerShell 开发命令

```powershell
.\scripts\run_api.ps1
.\scripts\run_worker.ps1
.\scripts\run_system_worker.ps1
.\scripts\run_watchdog.ps1
```

## 云服务器部署提示

当前 `docker-compose.yml` 更偏本地开发：API 使用 `--reload`，并把项目目录挂载进容器。
云服务器部署时建议新增生产 Compose 配置：

- 去掉 `--reload`。
- 去掉 `.:/app` 代码挂载，使用镜像内代码。
- 使用 `.env.production` 或云平台 secret，而不是 `.env.example`。
- PostgreSQL、Redis、MinIO 不暴露公网端口，只允许内网访问。
- API 通过 Nginx 或云负载均衡暴露 HTTPS。
- 生产环境迁移建议作为单独部署步骤执行，不建议多个 API 副本同时自动执行 Alembic。
- PostgreSQL、对象存储必须配置备份。

更接近生产的部署方式是：

```text
Nginx / Load Balancer
    -> api 容器
    -> api 容器

api / worker 内网访问：
    -> 云 PostgreSQL
    -> 云 Redis
    -> S3/COS/OSS/MinIO 对象存储
    -> GPU worker
    -> system-worker
    -> Celery beat
```
