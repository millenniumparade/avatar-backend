"""算法层通用数据结构。"""

from dataclasses import dataclass


@dataclass(slots=True)
class PipelineConfig:
    """算法配置。

    输入:
        algorithm_version: 算法版本。
        asset_library_version: Unity 资源库版本。
        timeout_seconds: 单任务最大处理时间。

    输出:
        传递给各算法阶段的只读配置对象。
    """

    algorithm_version: str
    asset_library_version: str
    timeout_seconds: int


@dataclass(slots=True)
class PipelineResult:
    """pipeline 输出结果。

    输出:
        human_info: Unity 可消费的 HumanInfo JSON 内容。
        preview_image_path: 预览图本地路径。
        artifact_paths: 中间调试产物路径集合。
        timing: 每个阶段耗时统计。
    """

    human_info: dict
    preview_image_path: str | None
    artifact_paths: dict[str, str]
    timing: dict[str, float]

