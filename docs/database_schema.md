# Avatar MVP Database Schema

This document describes the MVP database shape for the avatar generation backend.
The user-facing action is modeled as creating a generation job, not as a raw
image upload. The uploaded image is still persisted as a reusable business
entity, so users can manage historical images and reuse existing results.

## Core Flow

```text
POST /api/v1/avatar/jobs
  -> validate image
  -> calculate image_hash
  -> resolve algorithm_version, asset_library_version, schema_version
  -> find active result for same user + image_hash + versions
  -> cache hit: create succeeded job linked to existing result
  -> cache miss: create queued job and dispatch Celery task
```

The API response can stay uniform:

```json
{
  "job_id": "job_uuid",
  "status": "succeeded",
  "result_id": "result_uuid",
  "cache_hit": true
}
```

For a cache miss:

```json
{
  "job_id": "job_uuid",
  "status": "queued",
  "result_id": null,
  "cache_hit": false,
  "estimated_wait_seconds": 10
}
```

## Table Overview

```text
users
  1 -> many uploaded_images
  1 -> many avatar_jobs
  1 -> many avatar_results

uploaded_images
  1 -> many avatar_jobs
  1 -> many avatar_results

avatar_jobs
  many -> 1 uploaded_images
  0/1 -> 1 avatar_results

avatar_results
  many -> 1 uploaded_images
  many -> 1 avatar_jobs

avatar_artifacts
  optional debug/intermediate files for a job
```

## users

MVP can use `device_id` instead of a full account system.

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | Primary key |
| device_id | varchar | Optional unique device/user identifier |
| username | varchar | Optional |
| email | varchar | Optional unique email |
| password_hash | varchar | Optional for later auth |
| created_at | timestamptz | Creation time |
| updated_at | timestamptz | Update time |

## uploaded_images

Represents an image the user has uploaded and can manage later.

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | Primary key |
| user_id | UUID | Owner |
| image_hash | varchar | SHA-256 of normalized/uploaded bytes |
| original_image_key | varchar | Object storage key for original image |
| thumbnail_key | varchar | Optional key for history list preview |
| mime_type | varchar | Image MIME type |
| file_size | integer | Bytes |
| width | integer | Optional image width |
| height | integer | Optional image height |
| status | varchar | `active` or `deleted` |
| created_at | timestamptz | Creation time |
| deleted_at | timestamptz | Soft delete time |

Recommended uniqueness:

```text
unique active image per user + image_hash
```

## avatar_jobs

Represents one user generation request. A cache hit can still create a job with
`status=succeeded`, so the frontend always handles one consistent workflow.

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | Primary key |
| user_id | UUID | Owner |
| image_id | UUID | Source image |
| status | varchar | `queued`, `processing`, `succeeded`, `failed`, `cancelled` |
| progress | integer | 0-100 |
| current_stage | varchar | Current algorithm stage |
| result_id | UUID | Linked result after success |
| celery_task_id | varchar | Queue task identifier |
| cache_hit | boolean | Whether result was reused |
| algorithm_version | varchar | Algorithm version |
| asset_library_version | varchar | Unity asset library version |
| schema_version | varchar | HumanInfo JSON schema version |
| error_code | varchar | Structured failure code |
| error_message | text | Human-readable failure message |
| created_at | timestamptz | Creation time |
| started_at | timestamptz | Worker start time |
| finished_at | timestamptz | End time |

## avatar_results

Represents the reusable `HumanInfo.json` result for one image/version tuple.

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | Primary key |
| user_id | UUID | Owner |
| image_id | UUID | Source image |
| job_id | UUID | First job that produced this result |
| result_json | JSONB | Full Unity-consumable HumanInfo payload |
| result_json_key | varchar | Optional object storage key for JSON file |
| preview_image_key | varchar | Optional preview image |
| schema_version | varchar | HumanInfo JSON schema version |
| algorithm_version | varchar | Algorithm version |
| asset_library_version | varchar | Unity asset library version |
| status | varchar | `active` or `deleted` |
| created_at | timestamptz | Creation time |
| deleted_at | timestamptz | Soft delete time |

Recommended uniqueness:

```text
unique active result per user + image_id + algorithm_version + asset_library_version + schema_version
```

## avatar_artifacts

Optional table for intermediate/debug products such as aligned images, masks,
PLY files, point files, and logs. These files are not required by the user
workflow and can have a retention policy.

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | Primary key |
| job_id | UUID | Owning job |
| artifact_type | varchar | `aligned_image`, `ply`, `points`, `mask`, `debug`, etc. |
| object_key | varchar | Object storage key |
| metadata_json | JSONB | Optional metadata |
| created_at | timestamptz | Creation time |
| expires_at | timestamptz | Optional cleanup deadline |

## Redis Keys

Redis should not be the source of truth. It is used for queueing, short-lived
state, idempotency, and throttling.

```text
job:{job_id}:progress
  Short-lived status/progress/stage cache.

lock:user:{user_id}:image:{image_hash}:algo:{algorithm_version}:{asset_library_version}:{schema_version}
  Prevents duplicate concurrent generation for the same cache key.

rate:user:{user_id}:upload
rate:ip:{ip}:upload
  Upload rate limiting.

result:{result_id}
  Optional short-lived cache of result_json.
```

## Deletion Policy

Default to soft delete:

```text
DELETE /api/v1/avatar/images/{image_id}
  -> uploaded_images.status = deleted
  -> avatar_results.status = deleted
  -> unfinished avatar_jobs.status = cancelled
  -> enqueue object storage cleanup
```

This keeps history auditable while allowing delayed physical cleanup of object
storage files.
