import hashlib
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now
    )

    # Relación 1 a N con las participaciones en partidas
    participations: Mapped[List["GamePlayer"]] = relationship(
        "GamePlayer", back_populates="user", cascade="all, delete-orphan"
    )

    @classmethod
    def create_user(cls, username: str, plain_password: str) -> "User":
        salt = secrets.token_hex(16)
        pwd_hash = cls._hash_password(plain_password, salt)
        return cls(
            username=username.strip().lower(),
            password_hash=pwd_hash,
            salt=salt,
        )

    def check_password(self, plain_password: str) -> bool:
        expected_hash = self._hash_password(plain_password, self.salt)
        return secrets.compare_digest(self.password_hash, expected_hash)

    @staticmethod
    def _hash_password(plain_password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations=100_000,
        ).hex()

    def __repr__(self) -> str:
        return f"<User id={self.id} username='{self.username}'>"


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    player_count: Mapped[int] = mapped_column(Integer, nullable=False)
    winner_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Relación 1 a N con los detalles de cada jugador en la partida
    players: Mapped[List["GamePlayer"]] = relationship(
        "GamePlayer", back_populates="game", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Game id={self.id} room_id={self.room_id} winner='{self.winner_name}'>"


class GamePlayer(Base):
    __tablename__ = "game_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    player_name: Mapped[str] = mapped_column(String(50), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_winner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    game: Mapped["Game"] = relationship("Game", back_populates="players")
    user: Mapped[Optional["User"]] = relationship("User", back_populates="participations")

    def __repr__(self) -> str:
        return f"<GamePlayer game_id={self.game_id} name='{self.player_name}' score={self.score} is_winner={self.is_winner}>"
