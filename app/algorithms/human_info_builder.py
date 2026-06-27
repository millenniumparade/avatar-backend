"""HumanInfo JSON 构建。"""

from app.algorithms.types import PipelineConfig


def build_human_info(
    cartoon: dict,
    parts: dict,
    parse_result: dict,
    reconstruction: dict,
    config: PipelineConfig,
) -> dict:
    """组装 Unity 可消费的 HumanInfo JSON。

    输入:
        cartoon: blend shape 和卡通点位结果。
        parts: Unity 部件编号。
        parse_result: 肤色、发色、眼镜等外观信息。
        reconstruction: 3DMM/FaceVerse 重建结果。
        config: schema、算法和资源版本信息。

    输出:
        dict: 最终 HumanInfo JSON 内容。
    """
    raise NotImplementedError("后续根据 Unity 字段约定组装完整 HumanInfo.json。")
