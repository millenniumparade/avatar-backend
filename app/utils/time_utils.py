"""时间工具。"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """获取 UTC 当前时间。

    输入:
        无。

    输出:
        datetime: 带 UTC timezone 的当前时间。
    """
    return datetime.now(timezone.utc)

