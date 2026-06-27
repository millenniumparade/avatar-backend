"""Mesh 点位提取。"""


def extract_mesh_points(ply_path: str, work_dir: str) -> dict:
    """从 PLY 中提取 FaceVerse 点位。

    输入:
        ply_path: FaceVerse 重建生成的 PLY 文件。
        work_dir: 本次任务工作目录。

    输出:
        dict:
            faceverse_points: 关键点或顶点数组。
            points_file_path: 序列化后的点位文件路径。
    """
    raise NotImplementedError("后续接入 getpoints 或等价点位提取逻辑。")

