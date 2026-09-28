from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, db: Session):
        super().__init__(db, User)

    def get_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(User.email == email))
