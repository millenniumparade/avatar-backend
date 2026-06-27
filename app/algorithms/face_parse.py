"""人脸解析。"""


def parse_face(aligned_face_path: str, work_dir: str, models: dict[str, object] | None = None) -> dict:
    """解析头发、眼镜、皮肤和五官区域。

    输入:
        aligned_face_path: 裁剪对齐后的人脸图片路径。
        work_dir: 本次任务工作目录。
        models: 预加载的人脸解析模型。

    输出:
        dict:
            parse_image_path: 解析图路径。
            hair_mask_path: 头发 mask 路径。
            glasses_mask_path: 眼镜 mask 路径。
            skin_color: RGB 皮肤色。
            hair_color: RGB 发色。
            has_glasses: 是否佩戴眼镜。
    """
    raise NotImplementedError("后续接入 face parsing inference。")

