"""
Generic CRUD repository.

Provides common get/list/add/delete operations so that concrete
repositories only need to define entity-specific query methods.
"""

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Thin abstraction over SQLAlchemy Session for a single entity type."""

    def __init__(self, db: Session, model: type[ModelT]):
        self.db = db
        self.model = model

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())

    def get(self, entity_id: str) -> ModelT | None:
        return self.db.get(self.model, entity_id)

    def add(self, entity: ModelT) -> ModelT:
        self.db.add(entity)
        return entity

    def delete(self, entity: ModelT) -> None:
        self.db.delete(entity)

    def flush(self) -> None:
        self.db.flush()

    def commit(self) -> None:
        self.db.commit()

    def refresh(self, entity: ModelT) -> ModelT:
        self.db.refresh(entity)
        return entity
