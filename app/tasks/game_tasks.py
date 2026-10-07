from datetime import datetime
from typing import Any, Dict, List
from tasks.celery_app import celery_app
from database.repository import save_finished_game
from server.logger import logger


@celery_app.task(
    name="save_finished_game_task",
    bind=True,
    max_retries=5,
    default_retry_delay=10,
)
def save_finished_game_task(
    self,
    room_id: int,
    started_at_iso: str,
    finished_at_iso: str,
    duration_seconds: int,
    players_data: List[Dict[str, Any]],
    final_scores: Dict[str, int],
    winners: List[str],
) -> int:
    """
    Tarea asincrónica de Celery para persistir el resultado de una partida en PostgreSQL.
    Con política de reintentos automáticos (hasta 5 reintentos cada 10 segundos)
    en caso de problemas de conectividad con la db.
    """
    try:
        started_at = datetime.fromisoformat(started_at_iso)
        finished_at = datetime.fromisoformat(finished_at_iso)

        game_id = save_finished_game(
            room_id=room_id,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            active_players=players_data,
            final_scores=final_scores,
            winners=winners,
        )
        logger.info(f"[CELERY WORKER] Partida de Sala #{room_id} persistida exitosamente con ID {game_id} en PostgreSQL.")
        return game_id
    except Exception as exc:
        logger.error(
            f"[CELERY WORKER] Error al persistir partida de Sala #{room_id}: {exc}. "
            f"Reintentando (intento {self.request.retries + 1}/5) en 10s..."
        )
        raise self.retry(exc=exc)
