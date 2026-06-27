"""卡通部件匹配。"""


def match_avatar_parts(
    cartoon: dict,
    parse_result: dict,
    work_dir: str,
    models: dict[str, object] | None = None,
) -> dict:
    """匹配头发、眉毛、眼睛、嘴巴和眼镜等 Unity 资源编号。

    输入:
        cartoon: 卡通脸型拟合结果。
        parse_result: 人脸解析结果。
        work_dir: 本次任务工作目录。
        models: 部件匹配模型、FAISS 索引或规则配置。

    输出:
        dict:
            hair: 头发资源编号。
            eyebrow: 眉毛资源编号。
            eye: 眼睛资源编号。
            mouth: 嘴巴资源编号。
            glasses: 眼镜资源编号，0 表示不佩戴。
    """
    raise NotImplementedError("后续接入部件模板匹配或 FAISS top-k 检索。")

