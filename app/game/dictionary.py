from celery.exceptions import TimeoutError as CeleryTimeoutError
from tasks.word_tasks import validate_word_task

def validate_word(word: str) -> bool:
    """
    Valida la palabra usando la tarea distribuida de Celery en Redis.
    """
    cleaned = word.strip().upper() if word else ""
    if len(cleaned) < 2:
        return False

    try:
        task = validate_word_task.delay(cleaned)
        return bool(task.get(timeout=4.0))
    except CeleryTimeoutError:
        raise RuntimeError(
            "El Worker de Celery no responde. "
            "Asegúrese de tenerlo corriendo en una terminal con: celery -A tasks.celery_app worker --loglevel=info"
        )
