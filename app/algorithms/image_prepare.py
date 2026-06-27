"""图片预处理。"""


def prepare_image(input_image_path: str, work_dir: str) -> dict:
    """解码、格式转换和尺寸限制。

    输入:
        input_image_path: 用户上传原图路径。
        work_dir: 本次任务工作目录。

    输出:
        dict:
            image_path: 统一格式后的图片路径，通常为 jpg。
            width: 处理后图片宽度。
            height: 处理后图片高度。

    异常:
        INVALID_IMAGE_FORMAT、IMAGE_TOO_LARGE、IMAGE_RESOLUTION_TOO_HIGH。
    """
    raise NotImplementedError("后续接入 Pillow/OpenCV 完成图片解码、转 jpg 和缩放。")

