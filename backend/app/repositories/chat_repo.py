from sqlalchemy import select

from app.domain.models import ChatMessage
from app.repositories.base import BaseRepository


class ChatRepository(BaseRepository[ChatMessage]):
    def __init__(self, db):
        super().__init__(db, ChatMessage)

    def latest_for_project(self, project_id: str, limit: int) -> list[ChatMessage]:
        return list(self.db.scalars(
            select(ChatMessage)
            .where(ChatMessage.project_id == project_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        ))

    def add_turn(self, message: ChatMessage) -> ChatMessage:
        return self.add(message)
