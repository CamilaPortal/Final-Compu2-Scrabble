import os

DICTIONARY_PATH = os.path.join(os.path.dirname(__file__), "dictionary.txt")

_WORDS = None

def _load_dictionary():
    global _WORDS
    if _WORDS is None:
        _WORDS = set()
        if os.path.exists(DICTIONARY_PATH):
            with open(DICTIONARY_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    _WORDS.add(line.strip().upper())
    return _WORDS

def validate_word(word):
    words = _load_dictionary()
    return word.strip().upper() in words
