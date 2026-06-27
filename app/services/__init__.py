"""业务服务层。

Service 负责编排 Repository、Storage、Queue 和限流逻辑。
API 层只调用 Service，不直接访问数据库或 Worker。
"""

