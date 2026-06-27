# 推荐整体架构

```
Unity 前端
|
| 1. 上传图片 / 查询任务状态 / 获取结果
v
FastAPI API 服务
|
|-- PostgreSQL：用户、任务、结果 JSON、状态
|-- Redis：缓存、任务队列、限流、临时状态
|-- Object Storage：原图、裁剪图、中间文件、生成结果
|
v
算法 Worker 集群
|
|-- 人脸检测/对齐
|-- 3DMM 重建
|-- 卡通 blend shape 拟合
|-- 五官/头发等部件匹配
|-- 结果 JSON 生成
```

---

## 你需要学习的技术栈

建议优先级如下：

1. **FastAPI**
   - 接收 Unity 上传图片
   - 提供 REST API
   - 用户鉴权、任务查询、历史记录查询
2. **PostgreSQL**
   - 存用户信息、任务状态、生成结果 JSON、历史记录
3. **Redis**
   - 缓存
   - 限流
   - 分布式锁
   - 任务队列中间件
4. **Celery / RQ / Dramatiq**
   - 后台异步任务队列
   - 把耗时算法从 API 请求中拆出去
5. **对象存储**
   - 本地开发可以用 MinIO
   - 生产可以用 AWS S3、阿里云 OSS、腾讯云 COS
   - 不建议把图片直接存在数据库里
6. **Docker / Docker Compose**
   - 本地快速搭建 FastAPI、PostgreSQL、Redis、Worker
7. **Nginx**
   - 反向代理
   - 上传大小限制
   - HTTPS
   - 静态文件转发
8. **模型推理优化**
   - ONNX Runtime
   - TensorRT
   - PyTorch JIT / TorchScript
   - GPU Worker 管理
   - batch inference

---

## 核心设计原则

你的算法可能耗时比较长，所以不要让 Unity 上传图片后一直卡着等 HTTP 返回。

生产中更推荐：

```
前端上传图片
后端立即返回 task_id
前端轮询 task_id 状态
算法完成后前端获取 JSON
```

而不是：

```
前端上传图片
HTTP 一直等待算法完成
直接返回 JSON
```

原因是：

- 算法可能 1 秒、5 秒、20 秒甚至更久
- HTTP 长连接容易超时
- 高并发时 API 服务会被拖垮
- 任务队列可以削峰填谷
- 后端更容易做失败重试、状态管理、排队

---

## 推荐接口设计

### 1. 用户上传图片

```
POST /api/v1/avatar/jobs
Content-Type: multipart/form-data
Authorization: Bearer <token>
```

请求字段：

- `image`: 用户上传的人脸图片
- `client_request_id`: 可选，用于防止重复提交

返回：

```json
{
  "job_id": "job_123456",
  "status": "queued",
  "estimated_wait_seconds": 3
}
```

后端做的事情：

1. 校验用户身份
2. 校验图片格式、大小、分辨率
3. 保存原图到对象存储
4. 在数据库创建任务记录
5. 把任务丢进 Redis/Celery 队列
6. 返回 job_id

---

### 2. 查询任务状态

```
GET /api/v1/avatar/jobs/{job_id}
```

返回处理中：

```json
{
  "job_id": "job_123456",
  "status": "processing",
  "progress": 60,
  "stage": "cartoon_blendshape_fitting"
}
```

返回完成：

```json
{
  "job_id": "job_123456",
  "status": "succeeded",
  "result_id": "result_987654"
}
```

返回失败：

```json
{
  "job_id": "job_123456",
  "status": "failed",
  "error_code": "NO_FACE_DETECTED",
  "message": "No valid face detected in uploaded image."
}
```

---

### 3. 获取生成结果 JSON

```
GET /api/v1/avatar/results/{result_id}
```

返回：

```json
{
  "result_id": "result_987654",
  "blend_shape": {
    "face_width": 0.23,
    "jaw_height": -0.14,
    "eye_size": 0.31,
    "nose_width": -0.05
  },
  "parts": {
    "hair": 12,
    "eyebrow": 4,
    "eye": 8,
    "mouth": 3,
    "lip": 6
  },
  "metadata": {
    "model_version": "cartoon-v1.3.2",
    "created_at": "2026-05-03T10:30:00Z"
  }
}
```

Unity 前端拿到这个 JSON 后，就可以根据 blend_shape 和 parts 编号加载对应卡通模型资源。

---

### 4. 查询用户历史记录

```
GET /api/v1/avatar/results
```

返回：

```json
{
  "items": [
    {
      "result_id": "result_987654",
      "job_id": "job_123456",
      "preview_url": "https://cdn.xxx.com/avatar/job_123456/preview.png",
      "created_at": "2026-05-03T10:30:00Z"
    }
  ],
  "total": 1
}
```

---

## 数据库设计

### users 表

**users**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | | 主键 |
| username | | 用户名 |
| email | | 邮箱 |
| password_hash | | 密码哈希 |
| created_at | | 创建时间 |
| updated_at | | 更新时间 |

如果你暂时不做完整登录系统，也至少要有 user_id 或设备 ID，否则历史记录无法归属。

---

### avatar_jobs 表

**avatar_jobs**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | | 主键 |
| user_id | | 用户 ID |
| status | | 任务状态 |
| original_image_url | | 原图 URL |
| aligned_image_url | | 对齐图 URL |
| result_id | | 结果 ID |
| error_code | | 错误码 |
| error_message | | 错误消息 |
| progress | | 进度百分比 |
| current_stage | | 当前阶段 |
| model_version | | 模型版本 |
| created_at | | 创建时间 |
| started_at | | 开始时间 |
| finished_at | | 完成时间 |

status 建议枚举：

- `queued`
- `processing`
- `succeeded`
- `failed`
- `cancelled`

---

### avatar_results 表

**avatar_results**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | | 主键 |
| user_id | | 用户 ID |
| job_id | | 关联任务 ID |
| result_json | JSONB | 完整结果 JSON |
| blendshape_json | JSONB | blendshape 数据 |
| parts_json | JSONB | 部件匹配数据 |
| preview_url | | 预览图 URL |
| model_version | | 模型版本 |
| created_at | | 创建时间 |

result_json 可以用 PostgreSQL 的 JSONB 类型。

---

### avatar_assets 表（可选）

如果你的卡通部件资源有版本管理，建议建表：

**avatar_assets**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | | 主键 |
| type | | 部件类型 |
| asset_index | | 部件编号 |
| asset_name | | 部件名称 |
| asset_version | | 资源版本 |
| file_url | | 文件 URL |
| metadata_json | JSONB | 元数据 |
| is_active | | 是否启用 |

比如：

- `type` = hair / eye / eyebrow / mouth / lip
- `asset_index` = 12
- `asset_version` = v1

这样以后建模师更新资源时，后端可以知道某个历史结果使用的是哪一版资源。

---

## 算法服务如何接入

推荐把算法封装成独立模块：

```
app/
  api/
  core/
  db/
  models/
  schemas/
  services/
  workers/
  algorithms/
```

比如：

```python
# algorithms/pipeline.py

def generate_cartoon_avatar(image_path: str) -> dict:
    face = detect_and_align_face(image_path)
    mesh_3d = reconstruct_3dmm(face)
    blend_shape = fit_cartoon_blendshape(mesh_3d)
    parts = match_cartoon_parts(face, mesh_3d)

    return {
        "blend_shape": blend_shape,
        "parts": parts
    }
```

Worker 里调用：

```python
@celery_app.task
def process_avatar_job(job_id: str):
    job = load_job(job_id)
    update_job_status(job_id, "processing")

    result = generate_cartoon_avatar(job.original_image_path)

    save_result(job_id, result)
    update_job_status(job_id, "succeeded")
```

---

## 如何尽可能压缩处理时间

这是你项目的关键。

### 1. API 服务不要跑算法

FastAPI 只负责：

- 接收请求
- 存储文件
- 创建任务
- 返回状态
- 查询结果

算法交给 Worker。否则高并发时 API 会被推理任务堵死。

---

### 2. 模型常驻内存

不要每个任务都重新加载模型。

错误做法：

```python
def process(image):
    model = load_model()
    return model(image)
```

正确做法：

```python
model = load_model_once()

def process(image):
    return model(image)
```

Worker 启动时加载：

```python
face_detector = load_face_detector()
model_3dmm = load_3dmm_model()
cartoon_fitter = load_cartoon_fitter()
part_matcher = load_part_matcher()
```

这样可以节省大量时间。

---

### 3. 拆分 CPU 和 GPU Worker

比如：

CPU Worker：

- 图片校验
- 图片解码
- 人脸裁剪
- 特征匹配
- JSON 组装

GPU Worker：

- 3DMM 推理
- 深度模型推理
- blend shape 拟合

如果 3DMM 是最耗时步骤，应重点优化 GPU 推理。

---

### 4. 模型加速

可选路线：

```
PyTorch 原始模型
    ↓
TorchScript / ONNX
    ↓
ONNX Runtime GPU
    ↓
TensorRT
```

越往后性能越好，但工程复杂度也越高。

建议阶段：

1. 先用 PyTorch 跑通服务
2. 再导出 ONNX
3. 再考虑 TensorRT

---

### 5. 图片预处理限制

前端上传图不要无限大。

建议限制：

- 格式：jpg / png / webp
- 大小：最大 5MB
- 分辨率：最大 2048x2048
- 处理前统一缩放到 512 或 1024

很多时候用户上传 4000x3000 图片，但算法只需要人脸区域。先检测人脸，再裁剪对齐，可以显著节省后续计算。

---

### 6. 缓存重复请求

如果用户重复上传同一张图片，可以避免重复计算。

做法：

```python
image_hash = sha256(image_bytes)
```

数据库查：

同一个 `user_id + image_hash + model_version` 是否已有成功结果。

如果有，直接返回历史 result_id。

---

### 7. 算法 Pipeline 内部并行

部分任务可以并行：

- 3DMM 重建
- 五官特征提取
- 头发区域分析

如果它们互不依赖，可以在 Worker 内部用线程池或进程池并行。

但是要小心：

- Python GIL
- GPU 显存争用
- 模型是否线程安全

---

### 8. 部件匹配提前建索引

如果你现在是遍历所有头发、眉毛、嘴唇模板逐个算相似度，高并发下会慢。

建议对预设部件提前建特征库：

```
hair_features.npy
eye_features.npy
mouth_features.npy
```

然后使用近邻搜索：

- FAISS
- Annoy
- ScaNN

推荐用 FAISS。

流程：

```
用户图片提取特征
    ↓
FAISS 查询 top-k
    ↓
规则/模型二次排序
    ↓
返回最匹配部件编号
```

---

## 高并发设计

### 服务拆分

```
Nginx
  |
FastAPI API 实例 x N
  |
Redis Queue
  |
Worker 实例 x M
  |
GPU Worker x K
```

FastAPI 可以横向扩展：

```bash
uvicorn app.main:app --workers 4
```

或者用 Gunicorn：

```bash
gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4
```

Worker 根据机器资源扩展：

- CPU Worker 多开
- GPU Worker 按 GPU 数量开

---

### 限流和排队

必须做限流，否则有人连续上传图片会拖垮服务。

可以限制：

- 单用户每分钟最多上传 5 次
- 单用户最多同时排队 2 个任务
- 单 IP 每分钟最多 20 次
- 图片最大 5MB

Redis 适合做限流。

---

### 任务优先级

如果以后有会员或付费用户，可以加任务优先级：

- premium queue
- normal queue
- low priority queue

Celery 支持不同 queue。

---

### 超时控制

每个任务必须有最大执行时间。

比如：

- 单任务最多 30 秒
- 超过则标记 failed
- 错误码：`PROCESSING_TIMEOUT`

否则 Worker 可能被异常图片卡死。

---

## 文件存储设计

不建议把图片存在数据库。推荐：

```
object-storage/
  users/{user_id}/jobs/{job_id}/original.jpg
  users/{user_id}/jobs/{job_id}/aligned.jpg
  users/{user_id}/jobs/{job_id}/preview.png
  users/{user_id}/jobs/{job_id}/debug/
```

数据库只存 URL 或 object key。

例如：

```json
{
  "original_image_key": "users/u123/jobs/j456/original.jpg"
}
```

如果涉及隐私，URL 不要长期公开。用后端生成临时签名 URL。

---

## Unity 前端如何对接

Unity 可以使用 UnityWebRequest 上传：

```csharp
UnityWebRequest.Post(url, formData)
```

流程：

1. 用户选择/拍摄图片
2. Unity 上传图片到 `/avatar/jobs`
3. 后端返回 job_id
4. Unity 每 1 秒请求 `/avatar/jobs/{job_id}`
5. 如果 succeeded，请求 `/avatar/results/{result_id}`
6. Unity 根据 JSON 加载 blend shape 和部件

如果你想更实时，也可以用 WebSocket：

```
Unity 上传图片
后端返回 job_id
Unity 建立 WebSocket
后端推送进度和完成事件
```

但第一版建议用轮询，简单稳定。

---

## 返回 JSON 的版本管理

这个非常重要。

你的算法和卡通基准模型未来一定会变。如果不做版本管理，历史 JSON 可能无法在新 Unity 资源下复现。

建议结果里必须带：

```json
{
  "schema_version": "1.0",
  "algorithm_version": "avatar-algo-1.2.0",
  "cartoon_base_model_version": "base-face-2026-04",
  "asset_library_version": "asset-lib-2026-04"
}
```

Unity 端根据版本判断是否兼容。

---

## 错误码设计

不要只返回 "failed"，要有明确错误码。

常见错误：

| 错误码 | 说明 |
|--------|------|
| `INVALID_IMAGE_FORMAT` | 图片格式无效 |
| `IMAGE_TOO_LARGE` | 图片过大 |
| `NO_FACE_DETECTED` | 未检测到人脸 |
| `MULTIPLE_FACES_DETECTED` | 检测到多张人脸 |
| `FACE_TOO_SMALL` | 人脸过小 |
| `FACE_OCCLUDED` | 人脸被遮挡 |
| `LOW_CONFIDENCE` | 置信度过低 |
| `MODEL_INFERENCE_FAILED` | 模型推理失败 |
| `PROCESSING_TIMEOUT` | 处理超时 |
| `INTERNAL_ERROR` | 内部错误 |

这对前端提示用户很重要。

例如：

```json
{
  "status": "failed",
  "error_code": "NO_FACE_DETECTED",
  "message": "No face was detected. Please upload a clear frontal face image."
}
```

---

## 安全和隐私

人脸图片属于敏感数据，生产环境必须考虑：

1. HTTPS
2. 鉴权
3. 上传文件类型校验
4. 文件大小限制
5. 图片病毒扫描（可选）
6. 原图定期删除策略
7. 用户可以删除历史记录
8. 日志里不要打印人脸图片 URL 或完整用户隐私数据
9. 数据库备份加密
10. 对象存储权限私有化

建议支持：

```
DELETE /api/v1/avatar/results/{result_id}
```

删除用户历史记录和相关图片。

---

## 项目目录建议

```
avatar-backend/
├── app/
│   ├── main.py
│   ├── api/
│   │   └── v1/
│   │       ├── avatar_jobs.py
│   │       ├── avatar_results.py
│   │       └── users.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── logging.py
│   │   └── errors.py
│   ├── db/
│   │   ├── session.py
│   │   └── base.py
│   ├── models/
│   │   ├── user.py
│   │   ├── avatar_job.py
│   │   ├── avatar_result.py
│   │   └── avatar_asset.py
│   ├── schemas/
│   │   ├── avatar_job.py
│   │   ├── avatar_result.py
│   │   └── user.py
│   ├── services/
│   │   ├── storage_service.py
│   │   ├── avatar_job_service.py
│   │   ├── avatar_result_service.py
│   │   └── rate_limit_service.py
│   ├── workers/
│   │   ├── celery_app.py
│   │   └── avatar_tasks.py
│   ├── algorithms/
│   │   ├── pipeline.py
│   │   ├── face_detect.py
│   │   ├── face_align.py
│   │   ├── reconstruct_3dmm.py
│   │   ├── cartoon_fit.py
│   │   └── part_match.py
│   ├── repositories/
│   │   ├── avatar_job_repository.py
│   │   └── avatar_result_repository.py
│   └── utils/
│       ├── image_utils.py
│       └── hash_utils.py
├── migrations/
├── tests/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── alembic.ini
```

---

## 本地开发环境建议

用 Docker Compose 起这些服务：

- FastAPI
- PostgreSQL
- Redis
- MinIO
- Celery Worker

本地结构：

```
Unity -> localhost FastAPI -> Redis/PostgreSQL/MinIO -> Worker
```

生产结构：

```
Unity -> HTTPS/Nginx -> FastAPI 集群 -> Redis/PostgreSQL/Object Storage -> GPU Worker 集群
```

---

## 最小可行版本 MVP

不要一开始就做特别复杂。建议第一版只做这些：

1. Unity 上传图片
2. FastAPI 保存图片
3. 数据库创建任务
4. Celery Worker 调用你的算法
5. 保存结果 JSON
6. Unity 轮询任务状态
7. Unity 获取结果 JSON
8. 用户能查询历史记录

第一版架构：

```
FastAPI + PostgreSQL + Redis + Celery + 本地文件存储
```

第二版再升级：

| 第一版 | 第二版 |
|--------|--------|
| 本地文件存储 | MinIO / S3 |
| PyTorch | ONNX / TensorRT |
| 普通轮询 | WebSocket 推送 |
| 单 Worker | GPU Worker 集群 |

---

## 一个推荐处理流程

完整链路如下：

1. Unity 上传图片
2. FastAPI 校验图片
3. 计算 image_hash
4. 查询是否已有缓存结果
5. 如果命中，直接返回已有 result_id
6. 如果未命中，保存图片到对象存储
7. 创建 avatar_job
8. 推送任务到 Celery
9. Worker 加载图片
10. 人脸检测
11. 人脸裁剪和对齐
12. 3DMM 重建
13. 卡通基准模型 blend shape 拟合
14. 五官/头发/嘴唇等部件匹配
15. 生成 result_json
16. 保存 avatar_result
17. 更新 avatar_job 为 succeeded
18. Unity 获取 result_json
19. 前端完成三维卡通脸重建

---

## 我的建议

你的项目后端最核心的技术决策是：

- FastAPI 不直接跑算法，只创建任务
- 算法放到 Worker 中异步执行
- 图片放对象存储
- JSON 结果放 PostgreSQL
- Redis 负责队列、缓存、限流

如果你后续要真正落地，我建议按这个顺序开发：

1. 先把算法封装成一个纯 Python 函数：输入图片路径，输出 JSON
2. 再做 FastAPI 上传接口
3. 再加 PostgreSQL 存任务和结果
4. 再加 Celery 异步任务
5. 再加 Unity 轮询接口
6. 最后优化推理速度和并发
