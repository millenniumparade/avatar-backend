"""人脸检测、裁剪和对齐。"""


def detect_crop_align(image_path: str, work_dir: str, models: dict[str, object] | None = None) -> dict:
    """检测单张人脸并裁剪对齐。

    输入:
        image_path: 预处理后的图片路径。
        work_dir: 本次任务工作目录。
        models: 预加载的人脸检测模型。

    输出:
        dict:
            aligned_image_path: 裁剪对齐后的人脸图片路径。
            face_box: 人脸框坐标。
            landmarks: 关键点坐标。
            confidence: 检测置信度。

    异常:
        NO_FACE_DETECTED、MULTIPLE_FACES_DETECTED、FACE_TOO_SMALL、LOW_CONFIDENCE。
    """
    raise NotImplementedError("后续接入当前 inference.py 中的 process_image 或新检测模型。")

