"""日志配置占位。

后续应加入 request_id、job_id、worker task_id，串联 API 和 Worker 日志。
"""

import logging


def configure_logging() -> None:
    """初始化日志格式。

    输入:
        无。

    输出:
        None。配置 Python logging 全局行为。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

