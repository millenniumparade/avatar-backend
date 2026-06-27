"""FaceVerse / 3DMM 重建。"""


def reconstruct_faceverse(aligned_face_path: str, work_dir: str, models: dict[str, object] | None = None) -> dict:
    """执行 3DMM/FaceVerse 人脸重建。

    输入:
        aligned_face_path: 裁剪对齐后的人脸图片路径。
        work_dir: 本次任务工作目录。
        models: 预加载的 FaceVerse、优化器和生成器。

    输出:
        dict:
            ply_path: 重建 mesh 文件路径。
            coefficients_path: 3DMM 系数文件路径。
            render_image_path: 重建预览图路径。

    异常:
        MODEL_INFERENCE_FAILED、PROCESSING_TIMEOUT。
    """
    raise NotImplementedError("后续接入 FaceVerse fit 流程。")

