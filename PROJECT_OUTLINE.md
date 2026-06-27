# 卡通人脸生成后端项目大纲

## 1. 项目定位

本项目可以定位为一个面向 Unity 前端的 AI 卡通人脸生成服务。用户上传一张人脸图片后，后端异步执行人脸检测、裁剪对齐、人脸解析、3DMM 重建、卡通模型拟合、五官和头发等部件匹配，最终生成 Unity 可消费的 `HumanInfo.json`，用于驱动卡通角色的脸型、五官、发型、肤色、发色和配饰等配置。

它不只是一个算法脚本项目，更适合包装为一个完整的工程化后端项目：

- 用 FastAPI 提供上传、任务查询、结果获取和历史记录接口
- 用 PostgreSQL 保存用户、任务状态、结果 JSON 和历史记录
- 用 Redis + Celery/RQ/Dramatiq 承接耗时推理任务
- 用对象存储保存原图、裁剪图、中间文件、预览图和调试产物
- 用 Worker 常驻加载模型，避免每次请求重复加载大模型
- 用限流、任务队列、超时控制和缓存提高高并发下的稳定性

## 2. 从残留 inference.py 复原出的旧流程

当前 `inference.py` 只能作为历史运行流程参考，不应作为最终版本。旧版本更接近 Flask 同步接口：

```text
POST /upload
  -> 接收上传文件
  -> 生成 Timestamp 作为本次任务目录
  -> save_as_jpg 保存为 image.jpg
  -> process_image 执行人脸检测、裁剪、对齐，输出 imagecut.jpg
  -> face parsing inference，输出解析图、头发 mask、眼镜 mask、肤色、发色、是否戴眼镜
  -> FaceVerse fit 执行 3DMM/人脸重建，输出 imagecut_base.ply 等结果
  -> getpoints 从 ply 中提取 FaceVerse 点位
  -> 调用 run_commands_5003.sh 执行后续外部处理
  -> process_vertices 结合原图、头发/眼镜解析结果、肤色/发色等生成最终结果
  -> 返回 imagesinput/{Timestamp}/HumanInfo.json
```

旧流程暴露出的主要问题：

- 请求线程同步执行完整算法，单张图耗时 10 秒以上时容易导致 HTTP 超时
- API 服务和算法推理强耦合，高并发下请求会互相阻塞
- 没有任务状态表，前端无法可靠查询排队、处理中、失败和完成状态
- 没有数据库，结果不可追踪，历史记录不可管理
- 使用时间戳作为任务目录，缺少统一的 job_id、result_id 和幂等机制
- 中间文件和模型路径硬编码，环境迁移成本高
- 外部 shell 脚本调用缺少超时、错误捕获和结构化日志
- 没有统一错误码，前端无法根据失败原因给用户明确提示
- 缺少模型版本、资源版本和 JSON schema 版本，历史结果难以复现

## 3. 新版本核心目标

第一阶段不追求把算法重新写完，而是把项目补成一个可信的后端工程作品：

1. 把旧算法链路封装成一个纯 Python pipeline：输入图片路径，输出结构化 JSON
2. FastAPI 只负责接收请求、创建任务、查询状态、返回结果
3. Worker 异步执行耗时算法，并在启动时预加载模型
4. PostgreSQL 持久化任务、结果、用户归属和版本信息
5. Redis 负责任务队列、限流、幂等缓存和临时状态
6. 文件存储与数据库分离，图片和中间产物存文件系统或 MinIO/S3
7. 支持错误码、任务超时、重试、日志追踪和基础监控

## 4. 推荐整体架构

```text
Unity Client
  |
  | 上传图片 / 查询任务 / 获取结果
  v
Nginx
  |
  v
FastAPI API Service  x N
  |
  |-- PostgreSQL: 用户、任务、结果 JSON、历史记录、版本信息
  |-- Redis: 任务队列、限流、幂等缓存、临时进度
  |-- Object Storage: 原图、裁剪图、中间文件、预览图、调试产物
  |
  v
Algorithm Worker x M
  |
  |-- 人脸检测与对齐
  |-- 人脸解析
  |-- 3DMM / FaceVerse 重建
  |-- 卡通 blend shape 拟合
  |-- 头发、五官、眼镜等部件匹配
  |-- HumanInfo.json 生成
```

关键原则：

- API 服务不直接跑算法
- 上传接口立即返回 `job_id`
- 前端通过轮询或 WebSocket 查询进度
- Worker 执行算法并更新任务状态
- 结果 JSON 持久化，图片和中间文件存对象存储

## 5. 标准业务流程

```text
1. Unity 上传图片
2. FastAPI 校验图片格式、大小和分辨率
3. 计算 image_hash
4. 查询 user_id + image_hash + algorithm_version 是否已有成功结果
5. 如果命中缓存，直接返回已有 result_id 或已完成 job
6. 如果未命中，保存原图
7. 创建 avatar_job，状态为 queued
8. 投递 Celery/RQ 任务
9. Worker 获取任务，状态改为 processing
10. Worker 执行算法 pipeline
11. 保存 HumanInfo.json 和预览图
12. 写入 avatar_results
13. avatar_job 状态改为 succeeded
14. Unity 查询到完成状态
15. Unity 拉取结果 JSON 并驱动卡通角色生成
```

失败流程也必须完整：

```text
图片非法 / 无人脸 / 多人脸 / 推理失败 / 超时
  -> Worker 或 API 捕获异常
  -> 写入 error_code 和 error_message
  -> avatar_job 状态改为 failed
  -> 前端按错误码提示用户
```

## 6. 算法 Pipeline 建议封装

旧脚本中的每个处理段应该从 Web 接口中拆出来，形成清晰的算法模块。

```text
algorithms/
  pipeline.py
  image_prepare.py
  face_detect.py
  face_parse.py
  faceverse_fit.py
  mesh_points.py
  cartoon_fit.py
  part_match.py
  human_info_builder.py
```

推荐抽象：

```python
def generate_cartoon_avatar(input_image_path: str, work_dir: str) -> dict:
    prepared = prepare_image(input_image_path, work_dir)
    aligned_face = detect_crop_align(prepared.image_path, work_dir)
    parse_result = parse_face(aligned_face.path, work_dir)
    reconstruction = reconstruct_faceverse(aligned_face.path, work_dir)
    mesh_points = extract_mesh_points(reconstruction.ply_path, work_dir)
    cartoon = fit_cartoon_model(mesh_points, parse_result, work_dir)
    result = build_human_info(cartoon, parse_result, reconstruction)
    return result
```

最终 pipeline 的输入输出要稳定：

- 输入：原图路径、任务工作目录、算法配置、模型版本
- 输出：`HumanInfo.json` 内容、预览图路径、中间调试产物路径、耗时统计
- 异常：抛出带错误码的业务异常，例如 `NO_FACE_DETECTED`

## 7. API 设计

### 创建生成任务

```http
POST /api/v1/avatar/jobs
Content-Type: multipart/form-data
Authorization: Bearer <token>
```

请求字段：

| 字段 | 说明 |
| --- | --- |
| image | 用户上传的人脸图片 |
| client_request_id | 可选，客户端幂等 ID |

返回：

```json
{
  "job_id": "job_01HX...",
  "status": "queued",
  "estimated_wait_seconds": 8
}
```

### 查询任务状态

```http
GET /api/v1/avatar/jobs/{job_id}
```

处理中：

```json
{
  "job_id": "job_01HX...",
  "status": "processing",
  "progress": 45,
  "stage": "faceverse_reconstruction"
}
```

完成：

```json
{
  "job_id": "job_01HX...",
  "status": "succeeded",
  "result_id": "result_01HX..."
}
```

失败：

```json
{
  "job_id": "job_01HX...",
  "status": "failed",
  "error_code": "NO_FACE_DETECTED",
  "message": "No valid face detected in uploaded image."
}
```

### 获取结果 JSON

```http
GET /api/v1/avatar/results/{result_id}
```

返回内容应直接适配 Unity：

```json
{
  "schema_version": "1.0",
  "algorithm_version": "avatar-algo-1.0.0",
  "asset_library_version": "avatar-assets-2026-05",
  "blend_shape": {
    "face_width": 0.23,
    "jaw_height": -0.14,
    "eye_size": 0.31
  },
  "parts": {
    "hair": 12,
    "eyebrow": 4,
    "eye": 8,
    "mouth": 3,
    "glasses": 0
  },
  "appearance": {
    "skin_color": [238, 198, 172],
    "hair_color": [36, 28, 22],
    "has_glasses": false
  }
}
```

### 历史记录

```http
GET /api/v1/avatar/results
```

用于用户查看历史生成结果。

### 删除结果

```http
DELETE /api/v1/avatar/results/{result_id}
```

删除结果记录，并按策略删除或软删除关联图片。

## 8. 数据库设计

### users

如果项目第一版不做完整登录，也可以用 `device_id` 或匿名用户表替代。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 主键 |
| username | varchar | 用户名 |
| email | varchar | 邮箱 |
| password_hash | varchar | 密码哈希 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

### avatar_jobs

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 任务 ID |
| user_id | UUID | 用户 ID |
| status | enum | queued / processing / succeeded / failed / cancelled |
| image_hash | varchar | 原图哈希，用于去重 |
| original_image_key | varchar | 原图对象存储 key |
| aligned_image_key | varchar | 裁剪对齐图 key |
| result_id | UUID | 成功后的结果 ID |
| progress | int | 0 到 100 |
| current_stage | varchar | 当前算法阶段 |
| error_code | varchar | 失败错误码 |
| error_message | text | 失败说明 |
| algorithm_version | varchar | 算法版本 |
| asset_library_version | varchar | 资源库版本 |
| created_at | timestamp | 创建时间 |
| started_at | timestamp | 开始时间 |
| finished_at | timestamp | 结束时间 |

### avatar_results

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 结果 ID |
| user_id | UUID | 用户 ID |
| job_id | UUID | 关联任务 |
| result_json | JSONB | 完整 HumanInfo JSON |
| blendshape_json | JSONB | 脸型参数 |
| parts_json | JSONB | 部件匹配结果 |
| preview_image_key | varchar | 预览图 key |
| schema_version | varchar | JSON schema 版本 |
| algorithm_version | varchar | 算法版本 |
| asset_library_version | varchar | Unity 资源版本 |
| created_at | timestamp | 创建时间 |

### avatar_assets

可选，用于管理 Unity 侧卡通部件资源。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 主键 |
| type | varchar | hair / eye / eyebrow / mouth / glasses |
| asset_index | int | Unity 使用的资源编号 |
| asset_name | varchar | 资源名称 |
| asset_version | varchar | 资源版本 |
| feature_vector_key | varchar | 部件特征文件 key |
| metadata_json | JSONB | 元数据 |
| is_active | bool | 是否启用 |

## 9. 状态与错误码

任务状态：

| 状态 | 说明 |
| --- | --- |
| queued | 已入队，等待 Worker |
| processing | Worker 正在处理 |
| succeeded | 处理成功 |
| failed | 处理失败 |
| cancelled | 用户或系统取消 |

算法阶段：

| stage | 说明 |
| --- | --- |
| image_preparing | 图片解码、格式转换、缩放 |
| face_detecting | 人脸检测 |
| face_aligning | 裁剪对齐 |
| face_parsing | 人脸解析，识别头发、眼镜、肤色等 |
| faceverse_reconstruction | 3DMM / FaceVerse 重建 |
| mesh_extracting | 点位和 mesh 信息提取 |
| cartoon_fitting | 卡通脸型拟合 |
| part_matching | 头发、五官、配饰匹配 |
| result_building | 生成 HumanInfo.json |

错误码：

| 错误码 | 说明 |
| --- | --- |
| INVALID_IMAGE_FORMAT | 图片格式不支持 |
| IMAGE_TOO_LARGE | 图片文件过大 |
| IMAGE_RESOLUTION_TOO_HIGH | 图片分辨率过高 |
| NO_FACE_DETECTED | 未检测到人脸 |
| MULTIPLE_FACES_DETECTED | 检测到多张人脸 |
| FACE_TOO_SMALL | 人脸区域过小 |
| FACE_OCCLUDED | 人脸遮挡严重 |
| LOW_CONFIDENCE | 算法置信度过低 |
| MODEL_INFERENCE_FAILED | 模型推理失败 |
| EXTERNAL_COMMAND_FAILED | 外部脚本执行失败 |
| PROCESSING_TIMEOUT | 处理超时 |
| INTERNAL_ERROR | 未分类内部错误 |

## 10. 并发与性能设计

旧版本的问题不是单张图不能跑，而是无法稳定承接多个用户同时上传。新版本需要体现这些工程能力：

### API 与 Worker 解耦

FastAPI 只做轻量工作：

- 鉴权
- 图片校验
- 保存文件
- 创建任务
- 入队
- 查询任务和结果

耗时算法全部放到 Worker。

### 模型预加载

Worker 启动时加载模型：

```text
face_detector
face_parser
faceverse_model
rigid_optimizer
nonrigid_optimizer
cartoon_fitter
part_matcher
```

每个任务只复用已加载模型，避免把 10 秒任务变成 10 秒算法 + 多秒模型加载。

### 队列削峰

Redis + Celery/RQ 承接任务队列：

- 单用户同时排队任务数限制
- 单 IP 上传频率限制
- Worker 数量按 CPU/GPU 资源扩展
- GPU Worker 可单独队列化，避免显存争用

### 幂等与缓存

对上传图片计算 `sha256`：

```text
cache_key = user_id + image_hash + algorithm_version + asset_library_version
```

如果已有成功结果，直接返回历史结果，避免重复计算。

### 超时和重试

建议每个任务设置最大处理时间，例如 30 秒或 60 秒。可重试的错误只重试有限次数，不可重试错误直接失败：

- 图片质量问题：不重试
- 模型偶发错误：可重试 1 次
- 外部命令异常：可重试 1 次并保留日志
- 超时：标记失败并释放 Worker

### 部件匹配优化

如果旧版本中头发、眼睛、眉毛、嘴巴等部件是遍历模板匹配，可以升级为离线特征索引：

```text
离线阶段:
  预计算 hair / eye / mouth / glasses 等资源特征
  保存到 FAISS index

在线阶段:
  提取用户特征
  FAISS 查询 top-k
  规则或轻量模型重排
  输出 Unity 部件编号
```

## 11. 文件存储设计

数据库不保存图片二进制，只保存 object key。

```text
users/{user_id}/jobs/{job_id}/original.jpg
users/{user_id}/jobs/{job_id}/aligned.jpg
users/{user_id}/jobs/{job_id}/face_parse.png
users/{user_id}/jobs/{job_id}/hair_mask.png
users/{user_id}/jobs/{job_id}/glasses_mask.png
users/{user_id}/jobs/{job_id}/faceverse/imagecut_base.ply
users/{user_id}/jobs/{job_id}/preview.png
users/{user_id}/jobs/{job_id}/HumanInfo.json
users/{user_id}/jobs/{job_id}/debug/
```

本地开发可以先用本地文件系统，第二阶段替换成 MinIO，生产环境再替换成 S3/OSS/COS。

## 12. 推荐项目目录

```text
avatar-backend/
  app/
    main.py
    api/
      v1/
        avatar_jobs.py
        avatar_results.py
        users.py
    core/
      config.py
      logging.py
      security.py
      errors.py
    db/
      session.py
      base.py
    models/
      user.py
      avatar_job.py
      avatar_result.py
      avatar_asset.py
    schemas/
      avatar_job.py
      avatar_result.py
      user.py
    repositories/
      avatar_job_repository.py
      avatar_result_repository.py
    services/
      storage_service.py
      avatar_job_service.py
      avatar_result_service.py
      rate_limit_service.py
    workers/
      celery_app.py
      avatar_tasks.py
    algorithms/
      pipeline.py
      image_prepare.py
      face_detect.py
      face_parse.py
      faceverse_fit.py
      mesh_points.py
      cartoon_fit.py
      part_match.py
      human_info_builder.py
    utils/
      hash_utils.py
      image_utils.py
      time_utils.py
  migrations/
  tests/
  docker-compose.yml
  Dockerfile
  requirements.txt
  alembic.ini
  README.md
```

## 13. MVP 落地范围

作为简历项目，第一版要避免范围失控。推荐 MVP 做到：

- FastAPI 上传接口
- PostgreSQL 任务表和结果表
- Redis + Celery 异步任务
- Worker 启动时预加载模型
- pipeline 可先接入旧算法，也可以用 mock 算法占位
- 任务状态查询
- 结果 JSON 查询
- 图片 hash 去重
- 基础错误码
- Docker Compose 一键启动 API、PostgreSQL、Redis、Worker
- 单元测试覆盖任务创建、状态流转、结果保存、重复图片命中缓存

暂时不必第一版完成：

- 完整用户注册登录
- WebSocket 推送
- GPU Worker 集群调度
- ONNX/TensorRT 加速
- 完整后台管理系统
- 复杂付费优先级队列

## 14. 第二阶段增强点

当 MVP 跑通后，可以继续补充更有含金量的工程点：

- MinIO 对象存储替换本地文件
- Prometheus + Grafana 监控任务耗时、成功率、队列长度
- OpenTelemetry 或 request_id 串联 API 和 Worker 日志
- GPU Worker 独立队列
- ONNX Runtime 推理加速
- FAISS 部件匹配索引
- WebSocket/SSE 推送任务进度
- 原图定期清理和用户删除数据
- Nginx 上传大小限制和 HTTPS 部署

## 15. 测试设计

建议最少覆盖这些测试：

| 测试 | 目的 |
| --- | --- |
| 上传非法格式图片 | 验证 `INVALID_IMAGE_FORMAT` |
| 上传超大图片 | 验证 `IMAGE_TOO_LARGE` |
| 创建任务成功 | 验证 job 状态为 queued |
| Worker 成功处理 | 验证状态从 queued 到 processing 到 succeeded |
| Worker 抛业务异常 | 验证状态为 failed 且有错误码 |
| 重复图片上传 | 验证 image_hash 缓存命中 |
| 查询不存在任务 | 验证 404 |
| 查询非本人结果 | 验证权限控制 |

## 16. 简历描述建议

可以把项目写成下面这种表达：

```text
AI 卡通人脸生成后端系统

- 基于 FastAPI 设计图片上传、任务状态查询、结果获取和历史记录接口，将原同步推理链路重构为异步任务架构。
- 使用 Redis + Celery 将单次 10s+ 的人脸生成流程从 API 请求线程中解耦，支持任务排队、状态追踪、失败重试和超时控制。
- 设计 PostgreSQL 数据模型保存用户任务、生成结果 JSON、算法版本和 Unity 资源版本，保证历史结果可追踪、可复现。
- 将人脸检测、裁剪对齐、人脸解析、FaceVerse/3DMM 重建、卡通 blend shape 拟合和部件匹配封装为可插拔 pipeline。
- 通过模型预加载、图片 hash 去重、上传限流和结构化错误码优化服务稳定性，降低重复请求和高并发场景下的推理压力。
- 使用 Docker Compose 编排 FastAPI、PostgreSQL、Redis 和 Worker，提升本地开发与部署的一致性。
```

如果需要更强调算法：

```text
项目支持从单张人脸图像中提取肤色、发色、眼镜、FaceVerse 3D 点位和卡通脸型参数，并生成 Unity 可消费的 HumanInfo.json，用于驱动三维卡通角色自动生成。
```

如果需要更强调后端工程：

```text
项目重点解决长耗时 AI 推理任务在 Web 服务中的并发处理问题，通过异步队列、任务状态机、结果持久化、幂等缓存和模型常驻内存机制，将原同步脚本改造为可扩展的后端服务。
```

## 17. 推荐开发顺序

```text
阶段 1: 梳理旧算法流程
  -> 将旧 inference.py 拆成 pipeline 函数
  -> 明确输入、输出、异常和中间文件目录

阶段 2: 搭建 Web 服务骨架
  -> FastAPI
  -> 配置管理
  -> 统一错误处理
  -> 上传接口

阶段 3: 加入数据库
  -> avatar_jobs
  -> avatar_results
  -> Alembic migration

阶段 4: 加入异步任务
  -> Redis
  -> Celery/RQ
  -> Worker 预加载模型
  -> 状态流转

阶段 5: 补充工程能力
  -> 限流
  -> hash 去重
  -> 超时控制
  -> 结构化日志
  -> Docker Compose

阶段 6: 优化与展示
  -> 性能统计
  -> API 文档截图
  -> Demo 视频
  -> README 和简历描述
```

## 18. 项目展示重点

这个项目用于投简历时，建议展示的不是“我写了一个上传接口”，而是：

- 我识别出了长耗时 AI 推理不能放在请求线程里
- 我把同步脚本拆成了异步任务系统
- 我设计了任务状态机和错误码
- 我做了数据库持久化和结果版本管理
- 我考虑了高并发下的排队、限流、去重和超时
- 我能把算法流程包装成工程上可维护、可部署、可观测的服务

这比单纯展示一个 `inference.py` 更能体现后端工程能力。
