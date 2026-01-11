# app/services/storage/history_store.py

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserHistory


class HistoryStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def load(self, *, user_id: str) -> Any:
        q = select(UserHistory).where(UserHistory.user_id == user_id)
        r = await self.db.execute(q)
        row = r.scalar_one_or_none()

        if not row or row.history is None:
            return []

        # Normalize to a safe JSON value (prefer list)
        h = row.history
        if isinstance(h, (list, dict)):
            return h
        return []

    async def save(self, *, user_id: str, history: Any) -> None:
        if history is None:
            history = []

        # Ensure JSON-serializable
        try:
            json.dumps(history)
        except Exception:
            history = []

        q = select(UserHistory).where(UserHistory.user_id == user_id)
        r = await self.db.execute(q)
        row = r.scalar_one_or_none()

        if row is None:
            row = UserHistory(user_id=user_id, history=history)
            self.db.add(row)
        else:
            row.history = history

        await self.db.commit()
