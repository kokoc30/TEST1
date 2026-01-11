# app/db/models.py

from __future__ import annotations

import uuid
from typing import Optional, Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    # Keep UUID string IDs (works great for Fly/Postgres and local SQLite)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Google subject (unique per Google account)
    google_sub: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)

    email: Mapped[Optional[str]] = mapped_column(String(320), index=True, nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    picture: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    history: Mapped["UserHistory"] = relationship(
        "UserHistory",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @staticmethod
    async def upsert_google_user(
        db: AsyncSession,
        *,
        google_sub: str,
        email: str = "",
        name: str = "",
        picture: str = "",
    ) -> "User":
        q = select(User).where(User.google_sub == google_sub)
        res = await db.execute(q)
        user = res.scalar_one_or_none()

        if user:
            # only overwrite if new values are non-empty
            user.email = (email or user.email) if email is not None else user.email
            user.name = (name or user.name) if name is not None else user.name
            user.picture = (picture or user.picture) if picture is not None else user.picture
            await db.commit()
            await db.refresh(user)
            return user

        user = User(
            google_sub=google_sub,
            email=(email.strip().lower() or None) if isinstance(email, str) else None,
            name=(name.strip() or None) if isinstance(name, str) else None,
            picture=(picture.strip() or None) if isinstance(picture, str) else None,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


class UserHistory(Base):
    __tablename__ = "user_histories"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Stored per-user conversation history
    history: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)

    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship("User", back_populates="history")
