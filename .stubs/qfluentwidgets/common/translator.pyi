from PyQt6.QtCore import QLocale, QObject, QTranslator

class FluentTranslator(QTranslator):
    def __init__(self, locale: QLocale | None = None, parent: QObject | None = None) -> None: ...
