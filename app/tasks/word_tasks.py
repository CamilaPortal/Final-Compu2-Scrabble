import os
from tasks.celery_app import celery_app

DICTIONARY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "game", "dictionary.txt"
)

_WORDS = None

def _get_words():
    global _WORDS
    if _WORDS is None:
        _WORDS = set()
        if os.path.exists(DICTIONARY_PATH):
            with open(DICTIONARY_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    w = line.strip().upper()
                    if len(w) >= 2:
                        _WORDS.add(w)
    return _WORDS

@celery_app.task(name="validate_word_task")
def validate_word_task(word: str) -> bool:
    """
    Tarea de Celery para validar si una palabra
    existe en el diccionario cargado en memoria.
    """
    if not word:
        return False
    cleaned = word.strip().upper()
    if len(cleaned) < 2:
        return False
    words = _get_words()
    return cleaned in words
