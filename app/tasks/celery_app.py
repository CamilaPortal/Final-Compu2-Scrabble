import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "scrabble_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.word_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=60,
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

if __name__ == "__main__":
    celery_app.start()
