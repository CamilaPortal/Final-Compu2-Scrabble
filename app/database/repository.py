import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import case, func

from database.connection import SessionLocal
from database.models import Game, GamePlayer, User


def register_user(username: str, plain_password: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Valida y registra un nuevo usuario en la base de datos con contraseña hasheada y salt."""
    clean_user = username.strip()

    if not (3 <= len(clean_user) <= 20):
        return False, "El nombre de usuario debe tener entre 3 y 20 caracteres.", None

    if not re.match(r"^[a-zA-Z0-9_]+$", clean_user):
        return False, "El nombre de usuario solo puede contener letras, números y guiones bajos.", None

    if len(plain_password) < 4:
        return False, "La contraseña debe tener al menos 4 caracteres.", None

    normalized_user = clean_user.lower()

    with SessionLocal() as session:
        existing = session.query(User).filter(User.username == normalized_user).first()
        if existing:
            return False, f"El nombre de usuario '{clean_user}' ya está registrado.", None

        new_user = User.create_user(clean_user, plain_password)
        session.add(new_user)
        session.commit()
        session.refresh(new_user)

        return True, f"Usuario '{clean_user}' registrado exitosamente.", {
            "id": new_user.id,
            "username": new_user.username,
        }


def authenticate_user(username: str, plain_password: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Autentica las credenciales de un usuario verificando el hash y salt almacenados."""
    clean_user = username.strip()
    if not clean_user or not plain_password:
        return False, "Debe ingresar usuario y contraseña.", None

    normalized_user = clean_user.lower()

    with SessionLocal() as session:
        user = session.query(User).filter(User.username == normalized_user).first()
        if not user:
            return False, "Usuario o contraseña incorrectos.", None

        if not user.check_password(plain_password):
            return False, "Usuario o contraseña incorrectos.", None

        return True, f"Bienvenido, {clean_user}.", {
            "id": user.id,
            "username": user.username,
        }


def save_finished_game(
    room_id: int,
    started_at: datetime,
    finished_at: datetime,
    duration_seconds: int,
    active_players: List[Dict[str, Any]],
    final_scores: Dict[str, int],
    winners: List[str],
) -> int:
    """Persiste el resultado completo de una partida y los puntajes de cada jugador participante."""
    winner_str = ", ".join(winners) if winners else "Empate"

    with SessionLocal() as session:
        game = Game(
            room_id=room_id,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            player_count=len(active_players),
            winner_name=winner_str,
        )
        session.add(game)
        session.flush()  # Obtiene game.id

        for idx, p in enumerate(active_players):
            p_name = p.get("name", "Jugador")
            user_id = p.get("user_id")

            # Si no viene user_id, intentar buscar si existe el usuario registrado por nombre
            if not user_id:
                u = session.query(User).filter(User.username == p_name.lower()).first()
                if u:
                    user_id = u.id

            score = final_scores.get(p_name, 0)
            is_winner = p_name in winners

            gp = GamePlayer(
                game_id=game.id,
                user_id=user_id,
                player_name=p_name,
                score=score,
                is_winner=is_winner,
            )
            session.add(gp)

        session.commit()
        return game.id


def get_top_players(limit: int = 10) -> List[Dict[str, Any]]:
    """Calcula y devuelve el ranking histórico de jugadores ordenado por victorias y puntaje."""
    with SessionLocal() as session:
        stats = (
            session.query(
                User.username,
                func.count(GamePlayer.id).label("games_played"),
                func.sum(case((GamePlayer.is_winner == True, 1), else_=0)).label("wins"),
                func.coalesce(func.max(GamePlayer.score), 0).label("best_score"),
                func.coalesce(func.avg(GamePlayer.score), 0.0).label("avg_score"),
            )
            .join(GamePlayer, GamePlayer.user_id == User.id, isouter=True)
            .group_by(User.id, User.username)
            .order_by(
                func.sum(case((GamePlayer.is_winner == True, 1), else_=0)).desc(),
                func.coalesce(func.max(GamePlayer.score), 0).desc(),
                func.coalesce(func.avg(GamePlayer.score), 0.0).desc(),
            )
            .limit(limit)
            .all()
        )

        ranking = []
        for rank, row in enumerate(stats, start=1):
            games = int(row.games_played or 0)
            wins = int(row.wins or 0)
            win_rate = round((wins / games) * 100, 1) if games > 0 else 0.0
            ranking.append({
                "rank": rank,
                "username": row.username,
                "games_played": games,
                "wins": wins,
                "win_rate": win_rate,
                "best_score": int(row.best_score or 0),
                "avg_score": round(float(row.avg_score or 0.0), 1),
            })

        return ranking
