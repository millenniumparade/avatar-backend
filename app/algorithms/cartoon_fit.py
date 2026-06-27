"""卡通脸型拟合。"""


def fit_cartoon_model(
    mesh_points: dict,
    parse_result: dict,
    work_dir: str,
    models: dict[str, object] | None = None,
) -> dict:
    """拟合 Unity 卡通基准模型的 blend shape。

    输入:
        mesh_points: FaceVerse 点位和 mesh 特征。
        parse_result: 头发、眼镜、肤色等解析结果。
        work_dir: 本次任务工作目录。
        models: 卡通拟合模型或规则引擎。

    输出:
        dict:
            blend_shape: Unity blend shape 参数。
            cartoon_points_path: 卡通模型点位文件路径。
            confidence: 拟合置信度。
    """
    raise NotImplementedError("后续接入 run_commands_5003.sh 或纯 Python 卡通拟合逻辑。")

