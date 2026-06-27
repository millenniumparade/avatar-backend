"""Unity 卡通部件资源表模型。"""

from uuid import UUID, uuid4

from sqlalchemy import Boolean, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AvatarAsset(Base):
    """Unity 资源库索引。

    用于记录 hair/eye/eyebrow/mouth/glasses 等资源的编号、版本和特征文件位置。
    """

    __tablename__ = "avatar_assets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    type: Mapped[str] = mapped_column(String(64), index=True)
    asset_index: Mapped[int] = mapped_column(Integer)
    asset_name: Mapped[str] = mapped_column(String(128))
    asset_version: Mapped[str] = mapped_column(String(64))
    feature_vector_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

