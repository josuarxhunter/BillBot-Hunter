from src.gui.translations_es import SPANISH
from utils.language import GameLanguage

_language: GameLanguage = "fr"


def set_language(language: GameLanguage) -> None:
    global _language
    _language = language


def get_language() -> GameLanguage:
    return _language


def tr(message: str, /, **values: object) -> str:
    translated = SPANISH.get(message, message) if _language == "es" else message
    return translated.format(**values) if values else translated
